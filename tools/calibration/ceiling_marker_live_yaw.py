"""Collect one opt-in Fleet lamp challenge and a rear cue from the same live frames."""

from concurrent.futures import Future, ThreadPoolExecutor
import math
from threading import Event
import time
from urllib.error import HTTPError

from ceiling_marker_led_yaw import LedUnobserved, combine, estimate_led
from ceiling_marker_yaw import (
    CueUnavailable,
    EstimateError,
    _approved_record,
    _request,
    cargo_frame_sample,
    check_candidate_source,
    check_cargo_record,
    estimate_cargo,
    live_frame_stamp,
)


FRAME_INTERVAL_S = 0.25


def _collect_frames(fleet, context, lease, record, deadline, ready, stop, window_end):
    frames = {}
    rotation = None
    while not stop.is_set() and time.monotonic() < deadline:
        try:
            jpeg, headers = _request(fleet, lease["frame_path"], lease["lease"], context, raw=True)
        except HTTPError as exc:
            if exc.code not in (404, 429):
                raise
            # A dashboard using the same preview may temporarily consume its read budget.
            stop.wait(FRAME_INTERVAL_S)
            continue
        stamp = live_frame_stamp(headers, record, expected_rotation=rotation)
        if stamp is not None:
            rotation = int(headers["X-Frame-Rotation-Deg"])
            frames[stamp] = jpeg
            ready.set()
            if window_end.done() and stamp >= window_end.result():
                break
        stop.wait(FRAME_INTERVAL_S)
    return sorted(frames.items()), rotation


def _request_challenge(fleet, token, context, robot, source):
    receipt = _request(fleet, f"/api/fleet/robots/{robot}/identify", token, context, {"color": "blue"})
    if receipt.get("robot_id") != robot or not receipt.get("request_id"):
        raise EstimateError("Fleet did not return this robot's identification receipt")
    identity = _request(fleet, "/api/fleet/tracking/identity", token, context)
    row = next((item for item in identity.get("pendings", [])
                if item.get("request_id") == receipt["request_id"]), {})
    if (row.get("robot_id") != robot or row.get("color") != "blue"
            or source not in (row.get("sources") or []) or row.get("not_after") != receipt.get("not_after")):
        raise EstimateError("Fleet did not report the exact blue challenge on this camera")
    start, end = row.get("not_before"), row.get("not_after")
    if (type(start) not in (int, float) or type(end) not in (int, float)
            or not math.isfinite(start) or not math.isfinite(end) or not 0 < end - start <= 6):
        raise EstimateError("Fleet reported an invalid identification window")
    return row


def collect_live_candidate(fleet, *, token, context, source, robot, marker, heading_edge, revision, seconds,
                           cargo_height_m=None, transverse=False, forward_motion=False, site_camera_config=None):
    if not token:
        raise EstimateError("live LED identification needs a named Fleet operator token")
    if not math.isfinite(seconds) or not 7 <= seconds <= 45:
        raise EstimateError("live LED capture needs a bounded duration of 7–45 seconds")
    scope = dict(source=source, robot=robot, marker=marker, revision=revision, site_camera_config=site_camera_config)
    record = _approved_record(fleet, token, context, source)
    check_cargo_record(record, source=source, revision=revision)
    lease = _request(fleet, "/api/fleet/vision/lease", token, context, {"source_id": source})
    ready, stop, window_end = Event(), Event(), Future()
    deadline = time.monotonic() + seconds
    with ThreadPoolExecutor(max_workers=1) as workers:
        capture = workers.submit(_collect_frames, fleet, context, lease, record, deadline, ready, stop, window_end)
        try:
            if not ready.wait(min(6, seconds - 6)):
                if capture.done():
                    capture.result()  # Preserve the camera's refusal.
                raise EstimateError("no compatible live frame before requesting identification")
            current, provenance = check_candidate_source(fleet, token, context, **scope)
            if current != record:
                raise EstimateError("approved calibration changed while opening the camera")
            challenge = _request_challenge(fleet, token, context, robot, source)
            window_end.set_result(challenge["not_after"])
            frames, rotation = capture.result()
        finally:
            stop.set()

    if check_candidate_source(fleet, token, context, **scope) != (record, provenance):
        raise EstimateError("approved source or calibration changed during capture")
    options = dict(source=source, marker=marker, heading_edge=heading_edge)
    cargo = None
    if cargo_height_m is not None:
        try:
            rows = (cargo_frame_sample(record, jpeg, stamp, cargo_height_m=cargo_height_m,
                                       transverse=transverse, **options) for stamp, jpeg in frames)
            cargo = estimate_cargo([row for row in rows if row is not None], forward_motion=forward_motion)
        except CueUnavailable:
            pass
    try:
        if frames[0][0] > challenge["not_before"] or frames[-1][0] < challenge["not_after"]:
            raise LedUnobserved("live frames did not cover the full identification window")
        led = estimate_led(frames, record, robot=robot, challenge=challenge, **options)
    except LedUnobserved as exc:
        if cargo is None:
            raise
        result = {**cargo, "led_unavailable": str(exc)}
    else:
        result = combine(cargo, led)
    return {**result, "map_id": record["map_id"], "frame_rotation_deg": rotation, **provenance}
