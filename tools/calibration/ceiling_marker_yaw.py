"""Ceiling robot sticker yaw offset from one straight forward drive (D-587 5).

Runs inside the site Vision container (it has OpenCV and rosy_vision), or on a PC with the
repo's operations/overhead, contracts/foundation and operations/apps/games on PYTHONPATH. Needs no sighting,
so it works before any ``marker_yaw_offset_deg`` is installed (a robot without one sends no
sightings, D-587 4):

    docker exec -i [-e ROSY_FLEET_TOKEN] rosy-site-vision-1 python3 - \
        --robot rosy_41 --marker 41 --fleet https://proxy:8443 --insecure \
        [--origin https://127.0.0.1:8443] \
        [--source ceiling_north] [--heading-edge 0,1] [--seconds 12] \
        < tools/calibration/ceiling_marker_yaw.py

Drive the robot straight forward for 0.3 m or more while this runs (Fleet manual drive or
the CORE dashboard). The tool reads the raw ceiling frames through a viewer lease, detects
the robot's ArUco marker, projects it with the source's approved D-457 record and the same
parallax step and geometry gate as the Vision sightings (``track.marker_sightings.marker_pose``),
takes the travel direction from the marker positions (main axis, oriented by time) and
compares the raw marker yaw with it. While driving forward the travel direction is the robot
front, so the difference is the sticker offset. The odom heading is not used: it is in the
odom frame, whose turn against the map is unknown.

Prints the ``marker_yaw_offset_deg`` value for site-cameras.yaml and the nearest multiple of
90. It never writes any file or config; the operator installs the line. Refuses (exit 2)
with fewer than 5 samples, under 0.25 m of travel, more than 0.02 m off a straight line or
more than 5 deg of yaw spread.

Offline (no Fleet, no token): ``--frames DIR --record record.json`` reads recorded raw
frames of one straight forward drive (file mtime = capture time) and the approved record.

Set ``--cargo-height-m`` to the measured height of the orange cargo top and
``--calibration-revision`` to the approved revision at capture. This mode reads live raw
frames, ``--frames DIR`` or ``--cargo-video MP4`` and emits a rear-cue candidate only.
Stationary evidence cannot establish that the orange object is attached to the robot.
For a D-950 transverse container, ``--transverse-cargo`` uses the normal of its long edge.
Use ``--forward-motion`` only for a known straight forward segment.

Token: ``ROSY_FLEET_TOKEN`` (viewer or above) from an authenticated session.
Development mode also requires login. The token is never printed. ``estimate`` is stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
import sys
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Sequence

MIN_SAMPLES = 5
MIN_TRAVEL_M = 0.25
MAX_LINE_RESIDUAL_M = 0.02
MAX_YAW_SPREAD_DEG = 5.0
MIN_COMOTION_M = 0.03
MAX_COMOTION_RESIDUAL_M = 0.015
# Candidate search around the marker, bounded by the body and rear tray footprint.
REAR_CUE_DISTANCE_M = (0.025, 0.18)
# Visible top of the nominal 90 x 30 mm cargo, with room for partial edge dropout.
CARGO_TOP_AREA_M2 = (0.5 * 0.09 * 0.03, 1.8 * 0.09 * 0.03)


class EstimateError(ValueError):
    pass


class CueUnavailable(EstimateError):
    pass


@dataclass(frozen=True)
class CueSample:
    captured_at: float
    marker: tuple[float, float, float]
    cargo: tuple[float, float]
    front_yaw: float | None = None


def _wrap(angle: float) -> float:
    return math.atan2(math.sin(angle), math.cos(angle))


def estimate(samples: Sequence[tuple[float, float, float, float]], current_offset_deg: float = 0.0) -> dict:
    """samples: (captured_at, x, y, yaw rad) of one marker over a forward straight drive.

    With the raw marker yaw and current_offset_deg 0 the result is the sticker offset."""
    return _estimate_travel(samples, current_offset_deg, MIN_TRAVEL_M)


def _estimate_travel(samples, current_offset_deg, min_travel_m):
    rows = sorted(samples)
    if len(rows) < MIN_SAMPLES:
        raise EstimateError(f"only {len(rows)} sightings; need {MIN_SAMPLES}")
    n = len(rows)
    mx = sum(r[1] for r in rows) / n
    my = sum(r[2] for r in rows) / n
    sxx = sum((r[1] - mx) ** 2 for r in rows)
    syy = sum((r[2] - my) ** 2 for r in rows)
    sxy = sum((r[1] - mx) * (r[2] - my) for r in rows)
    axis = 0.5 * math.atan2(2 * sxy, sxx - syy)
    ux, uy = math.cos(axis), math.sin(axis)
    along = [(r[1] - mx) * ux + (r[2] - my) * uy for r in rows]
    across = [-(r[1] - mx) * uy + (r[2] - my) * ux for r in rows]
    travel_m = max(along) - min(along)
    if travel_m < min_travel_m:
        raise EstimateError(f"travel {travel_m:.3f} m; drive straight for at least {min_travel_m} m")
    residual = max(abs(v) for v in across)
    if residual > MAX_LINE_RESIDUAL_M:
        raise EstimateError(f"path is {residual:.3f} m off a straight line; drive straight")
    mt = sum(r[0] for r in rows) / n
    if sum((r[0] - mt) * a for r, a in zip(rows, along)) < 0:
        axis += math.pi
    travel = _wrap(axis)
    diffs = [_wrap(r[3] - travel) for r in rows]
    delta = math.atan2(sum(math.sin(d) for d in diffs), sum(math.cos(d) for d in diffs))
    spread = max(abs(math.degrees(_wrap(d - delta))) for d in diffs)
    if spread > MAX_YAW_SPREAD_DEG:
        raise EstimateError(f"yaw spread {spread:.1f} deg; the robot turned or the marker is noisy")
    offset = math.degrees(_wrap(math.radians(current_offset_deg) + delta))
    nearest = (round(offset / 90.0) * 90) % 360
    return {"samples": n, "travel_m": round(travel_m, 3), "line_residual_m": round(residual, 4),
            "travel_deg": round(math.degrees(travel), 1), "difference_deg": round(math.degrees(delta), 1),
            "yaw_spread_deg": round(spread, 2), "offset_deg": round(offset, 1),
            "nearest_90_deg": nearest if nearest <= 180 else nearest - 360}


def estimate_cargo(samples: Sequence[CueSample], *, forward_motion: bool = False) -> dict:
    """A candidate from marker-relative orange rear evidence. Never an installation decision."""
    if any(not all(math.isfinite(v) for v in (row.captured_at, *row.marker, *row.cargo))
           or row.front_yaw is not None and not math.isfinite(row.front_yaw) for row in samples):
        raise EstimateError("non-finite rear cue evidence")
    distinct = {row.captured_at: row for row in samples}
    rows = sorted(distinct.values(), key=lambda row: row.captured_at)
    if len(rows) < MIN_SAMPLES:
        raise CueUnavailable(f"only {len(rows)} distinct rear cue frames; need {MIN_SAMPLES}")

    vectors = [(row.marker[0] - row.cargo[0], row.marker[1] - row.cargo[1]) for row in rows]
    if any(not REAR_CUE_DISTANCE_M[0] <= math.hypot(*v) <= REAR_CUE_DISTANCE_M[1] for v in vectors):
        raise EstimateError("rear cue is outside the marker neighbourhood")
    transverse = rows[0].front_yaw is not None
    if any((row.front_yaw is not None) != transverse for row in rows):
        raise EstimateError("mixed rear cue heading methods")
    diffs = [_wrap(row.marker[2] - (row.front_yaw if row.front_yaw is not None else math.atan2(y, x)))
             for row, (x, y) in zip(rows, vectors)]
    delta = math.atan2(sum(math.sin(d) for d in diffs), sum(math.cos(d) for d in diffs))
    spread = max(abs(math.degrees(_wrap(d - delta))) for d in diffs)

    window = max(1, len(rows) // 4)
    start, end = rows[:window], rows[-window:]
    marker_delta = [median(r.marker[j] for r in end) - median(r.marker[j] for r in start) for j in (0, 1)]
    cargo_delta = [median(r.cargo[j] for r in end) - median(r.cargo[j] for r in start) for j in (0, 1)]
    travel = math.hypot(*marker_delta)
    residual = math.dist(marker_delta, cargo_delta)
    associated = travel >= MIN_COMOTION_M
    if associated and residual > MAX_COMOTION_RESIDUAL_M:
        raise EstimateError("orange object does not co-move with the marker")
    if spread > MAX_YAW_SPREAD_DEG:
        raise EstimateError(f"rear cue angles disagree by {spread:.1f} deg")

    offset = math.degrees(delta)
    if forward_motion and associated:
        expected = _estimate_travel([(r.captured_at, *r.marker) for r in rows], 0.0, MIN_COMOTION_M)
        if abs(math.degrees(_wrap(math.radians(offset - expected["offset_deg"])))) > MAX_YAW_SPREAD_DEG:
            raise EstimateError("rear cue conflicts with forward travel")
    return {"candidate_offset_deg": round(offset, 1), "samples": len(rows),
            "yaw_spread_deg": round(spread, 2), "marker_displacement_m": round(travel, 4),
            "relative_displacement_m": round(residual, 4),
            "association": "co_moves" if associated else "unverified_stationary",
            "heading_method": "transverse_cargo" if transverse else "cargo_centroid",
            "forward_cross_check": forward_motion and associated, "installation_allowed": False}


def check_cargo_record(record: dict, *, source: str, revision: str | None) -> None:
    if (not revision or record.get("source_id") != source or record.get("calibration_revision") != revision
            or not record.get("map_id") or not record.get("approved_by")):
        raise EstimateError("need the source's approved calibration record at the capture revision")


#: Browser origin Fleet checks on session requests; --origin sets it (the site's own console URL).
ORIGIN: list[str] = []


def _request(fleet: str, path: str, token: str | None, context, body: dict | None = None,
             *, raw: bool = False):
    headers = {"Origin": ORIGIN[0] if ORIGIN else fleet, "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(fleet + path, headers=headers, method="GET" if body is None else "POST",
                                     data=None if body is None else json.dumps(body).encode("utf-8"))
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        data = response.read()
        return (data, response.headers) if raw else json.loads(data)


def frame_sample(record: dict, jpeg: bytes, size: tuple[int, int], captured_at: float, *,
                 source: str, marker: int, heading_edge: tuple[int, int]) -> tuple | None:
    """(captured_at, x, y, raw marker yaw) for one raw frame, or None; needs rosy_vision."""
    from rosy_vision.detect import detect_markers
    from rosy_vision.project import QR_SIDE_BAND_M, ROBOT_ARUCO_SIDE_BAND_M
    from rosy_vision.track.calibration import from_record
    from rosy_vision.track.marker_sightings import marker_pose, solved_camera

    markers = detect_markers(jpeg, expected_marker_ids=(marker,))
    quad = markers.get(marker)
    calibration = from_record(record, source_id=source, map_id=record["map_id"], frame_size=size,
                              lens=record.get("lens")) if min(size) > 0 else None
    camera = solved_camera(calibration) if calibration is not None else None
    if quad is None or camera is None or not math.isfinite(captured_at):
        return None
    band = QR_SIDE_BAND_M if marker in markers.qr_ids else ROBOT_ARUCO_SIDE_BAND_M
    pose = marker_pose(calibration, quad, heading_edge, camera, side_band_m=band)
    return None if pose is None else (captured_at, *pose)


def _transverse_heading(contour, area, cue, marker) -> float | None:
    import cv2

    rect = cv2.minAreaRect(contour)
    short, long = sorted(rect[1])
    # The visible orange surface should be rectangular and long enough to resolve an axis.
    if short <= 0 or long / short < 1.6 or area < 0.65 * short * long:
        return None
    box = cv2.boxPoints(rect)
    edge = max((box[(i + 1) % 4] - box[i] for i in range(4)), key=lambda v: math.hypot(*v))
    normal = math.atan2(edge[1], edge[0]) + math.pi / 2
    rear_to_marker = math.atan2(marker[1] - cue[1], marker[0] - cue[0])
    alignment = math.cos(normal - rear_to_marker)
    if abs(alignment) < 0.5:  # the marker must lie clearly to one side of the transverse axis
        return None
    return _wrap(normal if alignment > 0 else normal + math.pi)


def cargo_frame_sample(record: dict, jpeg: bytes, captured_at: float, *, source: str, marker: int,
                       heading_edge: tuple[int, int], cargo_height_m: float,
                       transverse: bool = False) -> CueSample | None:
    """Project a single, unambiguous nearby orange component in the same calibrated map."""
    import cv2
    import numpy as np
    from rosy_vision.detect import detect_markers
    from rosy_vision.project import QR_SIDE_BAND_M, ROBOT_ARUCO_SIDE_BAND_M
    from rosy_vision.stack_tiers import MIN_BLOB_PX, ORANGE_HSV
    from rosy_vision.track import geometry
    from rosy_vision.track.calibration import from_record
    from rosy_vision.track.marker_sightings import marker_pose, solved_camera

    markers = detect_markers(jpeg, expected_marker_ids=(marker,))
    image = markers.image
    if marker not in markers or image is None or not math.isfinite(captured_at):
        return None
    calibration = from_record(record, source_id=source, map_id=record["map_id"],
                              frame_size=(image.shape[1], image.shape[0]), lens=record.get("lens"))
    camera = solved_camera(calibration) if calibration is not None else None
    if camera is None or not 0 <= cargo_height_m < camera[2]:
        raise EstimateError("frame is incompatible with the approved projection or cargo height")
    band = QR_SIDE_BAND_M if marker in markers.qr_ids else ROBOT_ARUCO_SIDE_BAND_M
    pose = marker_pose(calibration, markers[marker], heading_edge, camera, side_band_m=band)
    if pose is None:
        return None

    orange = cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV), *ORANGE_HSV)
    contours, _ = cv2.findContours(orange, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    matrix = geometry.as_matrix(calibration.image_to_map)
    cues = []
    for contour in contours:
        if cv2.contourArea(contour) < MIN_BLOB_PX:
            continue
        pixels = geometry.undistort_points(contour.reshape(-1, 2).astype(float), calibration.lens_profile)
        mapped = geometry.apply(matrix, pixels)
        if not np.isfinite(mapped).all():
            continue
        cargo = np.asarray([geometry.parallax_correct(point, camera, cargo_height_m) for point in mapped],
                           dtype=np.float32)
        moments = cv2.moments(cargo)
        area = moments["m00"]
        if not CARGO_TOP_AREA_M2[0] <= area <= CARGO_TOP_AREA_M2[1]:
            continue
        cue = (moments["m10"] / area, moments["m01"] / area)
        if not REAR_CUE_DISTANCE_M[0] <= math.dist(cue, pose[:2]) <= REAR_CUE_DISTANCE_M[1]:
            continue
        front_yaw = _transverse_heading(cargo, area, cue, pose) if transverse else None
        if not transverse or front_yaw is not None:
            cues.append(CueSample(captured_at, pose, cue, front_yaw))
    if len(cues) > 1:
        raise CueUnavailable("multiple orange objects near the marker")
    return cues[0] if cues else None


def collect_cargo_video(path: str, record: dict, **kwargs) -> list[CueSample]:
    import cv2

    samples = []
    seen = set()
    video = cv2.VideoCapture(path)
    try:
        fps = video.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise EstimateError("cannot read the raw video frame rate")
        index = 0
        while True:
            ok, frame = video.read()
            if not ok:
                break
            digest = hashlib.sha256(frame.tobytes()).digest()
            if digest not in seen:
                seen.add(digest)
                encoded, jpeg = cv2.imencode(".jpg", frame)
                if encoded:
                    sample = cargo_frame_sample(record, jpeg.tobytes(), index / fps, **kwargs)
                    if sample is not None:
                        samples.append(sample)
            index += 1
    finally:
        video.release()
    return samples


def _approved_record(fleet, token, context, source):
    records = _request(fleet, "/api/fleet/calibrations", token, context).get("calibrations", [])
    record = next((r for r in records if r.get("source_id") == source), None)
    if record is None:
        raise EstimateError(f"no approved calibration record for {source}")
    return record


def collect(fleet: str, *, source: str, marker: int, heading_edge: tuple[int, int], seconds: float,
            token: str | None, context, cargo_height_m: float | None = None,
            revision: str | None = None, record: dict | None = None, transverse: bool = False) -> list:
    """(captured_at, x, y, raw marker yaw) from the raw frames; needs rosy_vision (Vision container)."""
    record = record if record is not None else _approved_record(fleet, token, context, source)
    if cargo_height_m is not None:
        check_cargo_record(record, source=source, revision=revision)
    samples: dict[float, tuple] = {}
    lease, lease_at = None, -math.inf
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if time.monotonic() - lease_at > 50:
            lease = _request(fleet, "/api/fleet/vision/lease", token, context, {"source_id": source})
            lease_at = time.monotonic()
        try:
            jpeg, headers = _request(fleet, lease["frame_path"], lease["lease"], context, raw=True)
        except OSError:
            time.sleep(0.25)
            continue
        captured_at = float(headers.get("X-Frame-Captured-At", "nan"))
        size = (int(headers.get("X-Frame-Width", 0)), int(headers.get("X-Frame-Height", 0)))
        if cargo_height_m is None:
            sample = frame_sample(record, jpeg, size, captured_at, source=source, marker=marker,
                                  heading_edge=heading_edge)
        else:
            if headers.get("X-Frame-Rectified") != "false":
                raise EstimateError("cargo heading needs raw, unrectified frames")
            age_ms = float(headers.get("X-Frame-Age-Ms", "nan"))
            sample = (cargo_frame_sample(record, jpeg, captured_at, source=source, marker=marker,
                                         heading_edge=heading_edge, cargo_height_m=cargo_height_m,
                                         transverse=transverse)
                      if 0 <= age_ms <= 1000 else None)
        if sample is not None:
            samples[captured_at] = sample
        time.sleep(0.25)
    if cargo_height_m is not None:
        current = _approved_record(fleet, token, context, source)
        if current != record:
            raise EstimateError("approved calibration changed during capture")
    return list(samples.values())


def collect_offline(frames: str, record: dict, *, source: str, marker: int,
                    heading_edge: tuple[int, int], cargo_height_m: float | None = None,
                    transverse: bool = False) -> list:
    """Recorded raw frames (*.jpg, file mtime = capture time) of one straight drive."""
    import cv2
    import numpy as np

    samples = []
    seen = set()
    for path in sorted(Path(frames).glob("*.jpg")):
        jpeg = path.read_bytes()
        captured_at = path.stat().st_mtime
        if cargo_height_m is None:
            image = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                continue
            sample = frame_sample(record, jpeg, (image.shape[1], image.shape[0]), captured_at,
                                  source=source, marker=marker, heading_edge=heading_edge)
        else:
            digest = hashlib.sha256(jpeg).digest()
            if digest in seen:
                continue
            seen.add(digest)
            sample = cargo_frame_sample(record, jpeg, captured_at, source=source, marker=marker,
                                        heading_edge=heading_edge, cargo_height_m=cargo_height_m,
                                        transverse=transverse)
        if sample is not None:
            samples.append(sample)
    return samples


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--robot", required=True, help="robot id for the printed config line")
    parser.add_argument("--marker", type=int, required=True, help="its ArUco id (D-562: robot number)")
    parser.add_argument("--source", default="ceiling_north")
    parser.add_argument("--heading-edge", default="0,1", help="the source's heading_edge corners")
    parser.add_argument("--fleet", default="https://proxy:8443")
    parser.add_argument("--seconds", type=float, default=12.0)
    parser.add_argument("--dev-session", action="store_true", help="retired; use ROSY_FLEET_TOKEN")
    parser.add_argument("--insecure", action="store_true", help="skip TLS verification (site self-signed cert)")
    parser.add_argument("--origin", help="Origin header for session requests (default: --fleet)")
    offline = parser.add_mutually_exclusive_group()
    offline.add_argument("--frames", help="offline: folder of recorded raw JPEG frames")
    offline.add_argument("--cargo-video", help="offline: recorded raw video for a rear cue candidate")
    parser.add_argument("--record", help="offline: the approved D-457 record as JSON")
    parser.add_argument("--calibration-revision", help="approved revision at candidate frame capture")
    parser.add_argument("--cargo-height-m", type=float, help="measured orange cargo top height; enables candidate mode")
    parser.add_argument("--transverse-cargo", action="store_true", help="long cargo edge lies across the robot")
    parser.add_argument("--forward-motion", action="store_true", help="recorded segment is known to be straight forward")
    parser.add_argument("--led-challenge", help="Fleet identify receipt for the recorded raw JPEG frames")
    args = parser.parse_args(argv)
    if args.dev_session:
        parser.error("--dev-session is retired; sign in and provide ROSY_FLEET_TOKEN")
    candidate_mode = args.cargo_height_m is not None or args.led_challenge is not None
    if args.cargo_video and args.cargo_height_m is None:
        parser.error("--cargo-video needs --cargo-height-m")
    if args.transverse_cargo and args.cargo_height_m is None:
        parser.error("--transverse-cargo needs --cargo-height-m")
    if args.led_challenge and not args.frames:
        parser.error("--led-challenge needs --frames")
    if candidate_mode and not args.calibration_revision:
        parser.error("candidate mode needs --calibration-revision")
    if (args.frames or args.cargo_video) and not args.record:
        parser.error("offline frames need --record")
    if args.cargo_height_m is not None and not (math.isfinite(args.cargo_height_m) and args.cargo_height_m >= 0):
        parser.error("--cargo-height-m must be finite and non-negative")
    fleet = args.fleet.rstrip("/")
    ORIGIN[:] = [args.origin] if args.origin else []
    try:
        edge = tuple(int(v) for v in args.heading_edge.split(","))
    except ValueError:
        parser.error("--heading-edge needs two corner indices in 0..3")
    if len(edge) != 2 or len(set(edge)) != 2 or any(not 0 <= i <= 3 for i in edge):
        parser.error("--heading-edge needs two distinct corner indices in 0..3")
    context = ssl._create_unverified_context() if args.insecure else None
    if candidate_mode:
        try:
            result = _candidate(args, fleet, context, edge)
        except (OSError, ValueError) as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({**result, "robot_id": args.robot, "source_id": args.source,
                          "calibration_revision": args.calibration_revision, "use": "observation-only",
                          "installation_allowed": False}))
        return 0
    if args.frames:
        with open(args.record, encoding="utf-8") as handle:
            record = json.load(handle)
        try:
            result = estimate(collect_offline(args.frames, record, source=args.source,
                                              marker=args.marker, heading_edge=edge))
        except EstimateError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result))
        return 0
    token = os.environ.get("ROSY_FLEET_TOKEN")
    print(f"drive {args.robot} straight forward now; reading marker {args.marker} for {args.seconds:.0f} s",
          flush=True)
    try:
        samples = collect(fleet, source=args.source, marker=args.marker, heading_edge=edge,
                          seconds=args.seconds, token=token, context=context)
        result = estimate(samples, 0.0)
    except EstimateError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    print(f"site-cameras.yaml source: marker_yaw_offset_deg: {{{args.robot}: {result['offset_deg']}}}"
          f"  (nearest 90: {result['nearest_90_deg']})")
    return 0


def _candidate(args, fleet, context, edge):
    frame_options = {"source": args.source, "marker": args.marker, "heading_edge": edge}
    cargo_options = {**frame_options, "cargo_height_m": args.cargo_height_m, "transverse": args.transverse_cargo}
    if not (args.frames or args.cargo_video):
        token = os.environ.get("ROSY_FLEET_TOKEN")
        record = _approved_record(fleet, token, context, args.source)
        rows = collect(fleet, seconds=args.seconds, token=token, context=context, record=record,
                       revision=args.calibration_revision, **cargo_options)
        return {**estimate_cargo(rows, forward_motion=args.forward_motion), "map_id": record["map_id"]}

    record = json.loads(Path(args.record).read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise EstimateError("approved calibration record must be a JSON object")
    check_cargo_record(record, source=args.source, revision=args.calibration_revision)
    cargo = None
    if args.cargo_height_m is not None:
        try:
            rows = (collect_cargo_video(args.cargo_video, record, **cargo_options) if args.cargo_video
                    else collect_offline(args.frames, record, **cargo_options))
            cargo = estimate_cargo(rows, forward_motion=args.forward_motion)
        except CueUnavailable:
            if not args.led_challenge:
                raise
    if not args.led_challenge:
        return {**cargo, "map_id": record["map_id"]}

    from ceiling_marker_led_yaw import LedUnobserved, combine, estimate_led

    challenge = json.loads(Path(args.led_challenge).read_text(encoding="utf-8"))
    frames = [(path.stat().st_mtime, path.read_bytes()) for path in sorted(Path(args.frames).glob("*.jpg"))]
    try:
        led = estimate_led(frames, record, challenge=challenge, robot=args.robot, **frame_options)
    except LedUnobserved as exc:
        if cargo is None:
            raise
        return {**cargo, "map_id": record["map_id"], "led_unavailable": str(exc)}
    return {**combine(cargo, led), "map_id": record["map_id"]}


if __name__ == "__main__":
    sys.exit(main())
