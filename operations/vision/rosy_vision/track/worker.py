"""Markerless tracking step per fresh frame (D-457 2-4). Display only, no robot command.

VisionWorker calls ``process`` with the frame and the ArUco markers it already found.
The corner markers win when all four are in view; otherwise the approved paint-fit
record from Fleet is used (calibration.py). Without either the payload says
CALIBRATION_REQUIRED and carries no detections. ``run_config_sync`` reads the record
and the relearn counter every CONFIG_REFRESH_S on the event loop; a failed read keeps
the last good config (Fleet still checks every revision, 409).

Decoding and detection run on one dedicated thread per source, never on the ingest event
loop (2026-10-01 starvation lesson): the detector holds MOG2 state and is single-threaded,
and its work is OpenCV calls that release the GIL. The CLI awaits each step inline and
tracks its sources one after another, so steps never overlap; the busy check (a frame
offered while one is still in progress is skipped, not queued) is only a guard for that.

Relearn: Fleet's ``relearn_seq`` asks for a relearn when it goes up. A lower value (Fleet
restarted, the counter is 0 again) only becomes the new baseline. Rejected publishes and
failed config reads are logged when the (status, code) changes and then at most every
FAILURE_LOG_INTERVAL_S while it keeps failing.

``seq`` is this worker's own counter, not the phone header seq (a phone reconnect restarts
that); Fleet orders detections by ``captured_at``.

D-587: with a ``sightings`` publisher, identified robot markers projected through the approved
record are also sent as sightings (marker_sightings.py), after the detections, except for the
robots VisionWorker already sighted from this frame's measured calibration.

D-600: Fleet's ``occupied`` robot regions go to the detector before each step (``set_occupied``);
its ``unknown_floor`` rides the payload.

D-589: each step also measures the frame (tuning.Scorer, on the detection thread) and drives
the per-source Tuner on the event loop; its ``camera`` messages go to the phone over the
ingest connection (never awaited inline) and its status rides on the detections payload as
``tuning``. While a tune runs, the background detection pauses (LEARNING; ArUco robot markers
are still reported) and the intermediate settings are not learned. Once the lock is confirmed and settled the detector
learns again once (``camera_changed``, an automatic reset that replays a D-539 background kept
under the same settings; never the operator relearn). Outside a tune, a camera change is new
``applied`` settings in mode "vision" (the lock included) or a return to "vision" from another mode.
A tune that does not end within tuning.TUNE_DEADLINE_S keeps its setting and relearns once.
With ``auto_tune`` off nothing is sent and ``tuning`` is left out; camera changes still relearn.
A Fleet that refuses ``tuning`` (422) gets the payload again without it, and never again.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Mapping, Sequence

import cv2
import httpx
import numpy as np

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload, UnknownFloor
from rosy_vision.project import CameraMap, Point
from rosy_vision.track.background_blob import BackgroundBlobDetector
from rosy_vision.track.calibration import from_markers, from_record
from rosy_vision.publish import SightingPublishError
from rosy_vision.track.fleet_client import TrackPublishError
from rosy_vision.track.marker_sightings import robot_sightings
from rosy_vision.track import led_identity
from rosy_vision.track import tuning
from rosy_vision.track.model import (
    Calibration, Detection, DetectorResult, Frame, RobotDetector, ROBOT_TOP_HEIGHT_M,
    ROTATION_RADIUS_M, MAX_DETECTIONS, ROBOT_MARKER_IDS,
)
from rosy_vision.track import geometry

logger = logging.getLogger("rosy_vision.track")

CONFIG_REFRESH_S = 2.0
#: How far back the LED ring reaches: a whole identify window (<= 6 s) plus the config read delay.
RING_S = 6.0 + 2 * CONFIG_REFRESH_S + 1.0
FAILURE_LOG_INTERVAL_S = 30.0
_SEQ_MODULUS = 0x100000000


def decode_jpeg(jpeg: bytes) -> np.ndarray | None:
    if not isinstance(jpeg, bytes) or not jpeg:
        return None
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def build_payload(*, source_id: str, map_id: str, calibration_revision: str | None,
                  processor_revision: str, captured_at: float, seq: int,
                  result: DetectorResult, tuning: dict | None = None,
                  unknown_floor=()) -> OverheadDetectionsPayload:
    detections = () if result.status != "OK" else tuple(
        OverheadDetection(x=round(d.x, 4), y=round(d.y, 4), footprint_m=round(d.footprint_m, 4),
                          score=round(d.score, 3), marker_id=d.marker_id)
        for d in result.detections)
    return OverheadDetectionsPayload(
        source_id=source_id, map_id=map_id, calibration_revision=calibration_revision,
        processor_revision=processor_revision, captured_at=captured_at, seq=seq,
        status=result.status, detections=detections,
        unknown_floor=() if result.status != "OK" else tuple(
            UnknownFloor(x=round(x, 3), y=round(y, 3), radius_m=round(min(r, 2.0), 3)) for x, y, r in unknown_floor),
        tuning=tuning)


class _FailureLog:
    """One warning per change of failure, then a "still failing" line every interval."""

    def __init__(self, what: str, source_id: str, clock: Callable[[], float]) -> None:
        self._what = what
        self._source_id = source_id
        self._clock = clock
        self._key: tuple | None = None
        self._logged_at = 0.0

    def ok(self) -> None:
        self._key = None

    def failed(self, key: tuple) -> None:
        now = self._clock()
        detail = " ".join(f"{name}={value}" for name, value in key)
        if key != self._key:
            logger.warning("%s source=%s %s", self._what, self._source_id, detail)
        elif now - self._logged_at >= FAILURE_LOG_INTERVAL_S:
            logger.warning("%s still failing source=%s %s", self._what, self._source_id, detail)
        else:
            return
        self._key = key
        self._logged_at = now


class TrackWorker:
    def __init__(self, *, camera: CameraMap, ingest, client, detector: RobotDetector | None = None,
                 decode: Callable[[bytes], np.ndarray | None] = decode_jpeg,
                 clock: Callable[[], float] = time.monotonic, sightings=None,
                 auto_tune: bool = True, tuner: tuning.Tuner | None = None) -> None:
        self.camera = camera
        #: D-587: SightingPublisher for identified robot markers, or None (display only).
        self.sightings = sightings
        self.ingest = ingest
        self.client = client
        self.detector = detector if detector is not None else BackgroundBlobDetector()
        self.decode = decode
        self._config: dict | None = None
        self._relearn_seen: int | None = None
        self._seq = 0
        self._busy = False
        self._executor: ThreadPoolExecutor | None = None
        self._publish_log = _FailureLog("detections not accepted", camera.source_id, clock)
        self._config_log = _FailureLog("tracking config read failed", camera.source_id, clock)
        self._sighting_log = _FailureLog("marker sighting not accepted", camera.source_id, clock)
        #: D-587: the approved record's Calibration when the last _detect used it (single flight).
        self._approved: Calibration | None = None
        # D-472: LED samples of the last RING_S for every identify colour, kept before any
        # challenge arrives. Fleet's challenge reaches this worker on the CONFIG_REFRESH_S
        # config read, up to 2 s after the window opened; sampling only from then left the
        # window's head empty, so every site verdict was frames_missing (2026-10-09).
        self._identity_ring: list[tuple[float, dict[str, led_identity.Sample]]] = []
        self._identity_done: list[str] = []  # D-596: request ids answered (several may be open)
        self.led_config = led_identity.LedConfig()
        # D-589 recognition tuning.
        self.auto_tune = auto_tune
        self.tuner = tuner if tuner is not None else tuning.Tuner()
        self.scorer = tuning.Scorer(getattr(ingest, "map_paint", None))
        self._presence = tuning.MarkerPresence()
        self._measurement: tuning.Measurement | None = None  # the last step's, set on the thread
        self._camera_seen: str | None = None
        self._was_vision = False
        self._relearn_due: str | None = None
        self._identifying = False  # D-596 window open on the last frame
        self._send_tuning = True
        self._sends: set[asyncio.Future] = set()
        self._clock = clock

    @property
    def config(self) -> dict | None:
        return self._config

    def close(self) -> None:
        """Stop the detection thread (a later ``process`` starts a new one)."""
        executor, self._executor = self._executor, None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    async def refresh_config(self) -> None:
        try:
            self._config = await self.client.fetch_config()
        except TrackPublishError as exc:
            self._config_log.failed((("status", exc.status_code), ("code", exc.code)))
        except httpx.HTTPError as exc:
            self._config_log.failed((("error_type", type(exc).__name__),))
        else:
            self._config_log.ok()
            # D-560: the ingest warps the map plane with the same record tracking uses.
            self.ingest.report_calibration(self.camera.source_id,
                                           (self._config or {}).get("calibration"),
                                           self.camera.map_id)

    async def run_config_sync(self, stop_event: asyncio.Event,
                              interval_s: float = CONFIG_REFRESH_S) -> None:
        while not stop_event.is_set():
            await self.refresh_config()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass

    async def process(self, frame, markers: Mapping[int, Sequence[Point]],
                      sighted: frozenset[str] = frozenset(),
                      camera: CameraMap | None = None) -> OverheadDetectionsPayload | None:
        """Track one frame and publish the result; None when skipped (undecodable, or busy).

        D-587 1: ``sighted`` are robots this frame already produced a sighting for; ``camera``
        is VisionWorker's CameraMap for this frame (D-580 roster markers), default ours."""
        if self._busy:
            return None
        self._busy = True
        try:
            return await self._process(frame, markers, sighted, camera or self.camera)
        finally:
            self._busy = False

    async def _process(self, frame, markers, sighted=frozenset(),
                       camera: CameraMap | None = None) -> OverheadDetectionsPayload | None:
        config = self._config or {}
        relearn = config.get("relearn_seq")
        if type(relearn) is not int:
            relearn = None
        lens = self.ingest.source_lens(self.camera.source_id)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"rosy-vision-track-{self.camera.source_id}")
        challenges = _challenges(config, self.led_config)
        # D-596 1: the background stays frozen through every open window (a standing robot blinks).
        hold = max((c["not_after"] for c in challenges), default=None)
        if hasattr(self.detector, "set_occupied"):  # D-600: before the step, never during it
            self.detector.set_occupied(config.get("occupied"))
        link_of = getattr(self.ingest, "camera_link", None)
        link, camera_state = (None, None) if link_of is None else link_of(self.camera.source_id)
        # D-589: decided from the last tuner step (one frame earlier); the phone applies a new
        # request later than that anyway.
        suspend = self.auto_tune and self.tuner.active
        event = self._camera_event(camera_state)
        if suspend:
            event = None  # an intermediate tune step: not a background to learn
        if self._relearn_due is not None:  # the lock is confirmed and settled: learn once
            event, self._relearn_due = (self._relearn_due or None, False), None
        self._measurement = None
        step = await asyncio.get_running_loop().run_in_executor(
            self._executor, functools.partial(
                self._detect, frame.jpeg, frame.captured_at, markers, config.get("calibration"),
                lens, relearn, event, suspend, hold))
        # D-589 x D-596: no tune step or retune is judged while an LED identify window is open
        # (an exposure change would hide the blink); the request is still kept fresh.
        self._identifying = hold is not None and frame.captured_at <= hold
        for challenge in challenges:
            await self._report_identity(challenge, frame.captured_at)
        if step is None:
            return None
        calibration, result = step
        status = self._tune(link, camera_state, self._measurement)
        if self.sightings is not None:
            await self._publish_sightings(camera or self.camera, self._approved, frame, markers, sighted)
        payload = build_payload(
            source_id=self.camera.source_id, map_id=self.camera.map_id,
            calibration_revision=None if calibration is None else calibration.revision,
            processor_revision=self.detector.processor_revision, captured_at=frame.captured_at,
            seq=self._seq, result=result, tuning=status if self._send_tuning else None,
            unknown_floor=getattr(self.detector, "unknown_floor", ()))
        self._seq = (self._seq + 1) % _SEQ_MODULUS
        try:
            try:
                await self.client.publish(payload)
            except TrackPublishError as exc:
                if exc.status_code != 422 or payload.tuning is None:
                    raise
                # A Fleet older than D-589 refuses the field: once without it, then never again.
                logger.warning("Fleet refused the tuning field source=%s; not sent again",
                               self.camera.source_id)
                self._send_tuning = False
                payload = payload.model_copy(update={"tuning": None})
                await self.client.publish(payload)
        except TrackPublishError as exc:
            self._publish_log.failed((("status", exc.status_code), ("code", exc.code)))
        except httpx.HTTPError as exc:
            self._publish_log.failed((("error_type", type(exc).__name__),))
        else:
            self._publish_log.ok()
        return payload

    def _tune(self, link, camera_state, measurement) -> dict | None:
        """D-589: drive the tuner and send its camera message; the status for Fleet."""
        if not self.auto_tune:
            return None
        now = self._clock()
        sample = None if self._identifying else measurement
        message = self.tuner.update(now, link=link, state=camera_state, sample=sample)
        if message is not None and link is not None:
            # Fire and forget: a slow phone must not hold the tracking step.
            task = asyncio.ensure_future(self.ingest.send_camera(self.camera.source_id, message))
            self._sends.add(task)
            task.add_done_callback(self._sends.discard)
        if self.tuner.take_relearn():
            # Unknown settings (no camera_state, e.g. the deadline after a link switch): "" resets
            # without a D-539 replay.
            self._relearn_due = "" if camera_state is None else camera_state.applied.fingerprint()
        return self.tuner.status(now)

    def _camera_event(self, state) -> tuple[str, bool] | None:
        """(fingerprint, first) when the camera changed for tracking, else None (D-589 4).

        A change is new applied settings (the lock included) in mode "vision" or a return to
        "vision" from another mode; a reconnect with the same settings is none. ``first`` marks the first settings ever reported: they only name
        the settings an already learned background was made under.
        """
        vision = state is not None and state.mode == "vision"
        event = None
        if vision:
            fingerprint = state.applied.fingerprint()
            if self._camera_seen is None:
                event = (fingerprint, True)
            elif fingerprint != self._camera_seen or not self._was_vision:
                event = (fingerprint, False)
            self._camera_seen = fingerprint
        self._was_vision = vision
        return event

    async def _publish_sightings(self, camera: CameraMap, approved, frame, markers, sighted) -> None:
        """D-587: identified robot markers as sightings; a failure is logged, never raised."""
        try:
            sightings = robot_sightings(camera, approved, markers, captured_at=frame.captured_at,
                                        seq=frame.header.seq, skip=sighted)
        except (TypeError, ValueError, ArithmeticError, np.linalg.LinAlgError) as exc:
            self._sighting_log.failed((("error_type", type(exc).__name__),))
            return
        for sighting in sightings:
            try:
                await self.sightings.publish(sighting)
            except SightingPublishError as exc:
                self._sighting_log.failed((("status", exc.status_code), ("code", exc.code)))
            except (httpx.HTTPError, ValueError) as exc:  # ValueError: a non-JSON error body
                self._sighting_log.failed((("error_type", type(exc).__name__),))
            else:
                self._sighting_log.ok()

    async def _report_identity(self, challenge: dict, now: float) -> None:
        """D-472: once the window has passed, send Fleet the verdict (never an image)."""
        request_id = challenge["request_id"]
        if now <= challenge["not_after"] or request_id in self._identity_done:
            return
        self._identity_done = self._identity_done[-15:] + [request_id]
        samples = [by_color[challenge["color"]] for at, by_color in self._identity_ring
                   if challenge["not_before"] <= at <= challenge["not_after"] and challenge["color"] in by_color]
        verdict = led_identity.decide(samples, not_before=challenge["not_before"],
                                      not_after=challenge["not_after"], now=now, config=self.led_config)
        body = {"source_id": self.camera.source_id, "map_id": self.camera.map_id,
                "request_id": request_id, "processor_revision": led_identity.PROCESSOR_REVISION,
                **verdict}
        try:
            await self.client.publish_identity(body)
        except TrackPublishError as exc:
            self._publish_log.failed((("identity_status", exc.status_code), ("code", exc.code)))
        except httpx.HTTPError as exc:
            self._publish_log.failed((("identity_error_type", type(exc).__name__),))

    def _identity_sample(self, image: np.ndarray, captured_at: float, calibration: Calibration,
                         result: DetectorResult) -> None:
        """Ring samples of the anonymous blobs for every identify colour (detection thread)."""
        self._identity_ring = [(at, by) for at, by in self._identity_ring if captured_at - RING_S <= at < captured_at]
        if result.status != "OK":
            return
        matrix = geometry.as_matrix(calibration.image_to_map)
        inverse = np.linalg.inv(matrix)
        camera = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
        shrink = 1.0 if camera is None else (camera[2] - ROBOT_TOP_HEIGHT_M) / camera[2]
        scale_x = image.shape[1] / calibration.image_size[0]
        scale_y = image.shape[0] / calibration.image_size[1]
        blobs = []
        for d in result.detections:
            if d.marker_id is not None:
                continue
            # Undo the detector's height correction before returning to the original image.
            x, y = (d.x, d.y) if camera is None else (
                camera[0] + (d.x - camera[0]) / shrink,
                camera[1] + (d.y - camera[1]) / shrink)
            (px, py), (ex, ey) = geometry.apply(inverse, [(x, y), (x + d.footprint_m / (2 * shrink), y)])
            if not all(math.isfinite(v) for v in (px, py, ex, ey)):
                continue
            radius = math.hypot((ex - px) * scale_x, (ey - py) * scale_y)
            blobs.append(led_identity.Blob(px * scale_x, py * scale_y, radius, d.x, d.y))
        # ponytail: MAX_SAMPLES (64) bounds memory; above ~5.8 fps it, not RING_S, sets the reach,
        # so a window head could drop out again. Raise it with the camera rate.
        self._identity_ring = self._identity_ring[-(led_identity.MAX_SAMPLES - 1):]
        self._identity_ring.append((captured_at, {
            color: led_identity.sample_frame(image, captured_at=captured_at,
                                             calibration_revision=calibration.revision, blobs=blobs,
                                             color=color, config=self.led_config)
            for color in self.led_config.hues}))

    def _detect(self, jpeg: bytes, captured_at: float, markers, record, lens,
                relearn: int | None, camera: tuple[str, bool] | None = None, suspend: bool = False,
                hold: float | None = None) -> tuple[Calibration | None, DetectorResult] | None:
        """Detection-thread half of a step: relearn, hold, decode, choose the calibration, detect,
        and measure the frame for tuning (``self._measurement``). ``camera`` is a D-589 camera
        change (fingerprint, first); ``suspend`` (a tune runs) skips detection: LEARNING;
        ``hold`` (D-596) freezes the background through the open LED identify windows."""
        if camera is not None:
            # D-589: an automatic reset, not an operator relearn. No fingerprint: plain reset.
            changed = getattr(self.detector, "camera_changed", None)
            if changed is not None and camera[0] is not None:
                changed(camera[0], first=camera[1])
            elif not camera[1]:
                self.detector.reset()
        if relearn is not None:
            if self._relearn_seen is not None and relearn > self._relearn_seen:
                # D-539: an operator relearn may be kept for restarts; other detectors just reset.
                getattr(self.detector, "relearn", self.detector.reset)()  # if this raises, tried again
            self._relearn_seen = relearn
        if hold is not None and hasattr(self.detector, "hold"):
            self.detector.hold(hold)
        image = self.decode(jpeg)
        if image is None:
            return None
        size = (int(image.shape[1]), int(image.shape[0]))
        # D-595 order (calibration.choose): the approved (frozen) record wins; this frame's corner
        # markers only without one.
        approved = None if record is None else from_record(
            record, source_id=self.camera.source_id, map_id=self.camera.map_id,
            frame_size=size, lens=lens)
        by_markers = from_markers(self.camera, markers, frame_size=size, lens=lens)
        calibration = approved or by_markers
        # D-587: a frame with all four corner markers has its sightings from project_frame.
        self._approved = approved if by_markers is None else None
        if calibration is None:
            return None, DetectorResult((), "CALIBRATION_REQUIRED")
        robot_ids = set(self.camera.robot_markers.values()).union(ROBOT_MARKER_IDS)
        rate = self._presence.rate(captured_at, robot_ids.intersection(markers))
        try:
            self._measurement = self.scorer.measure(image, calibration, rate)
        except (cv2.error, ValueError, np.linalg.LinAlgError) as exc:  # tracking goes on unscored
            logger.warning("tuning score failed source=%s error=%s",
                           self.camera.source_id, type(exc).__name__)
        if suspend:  # only the background detection pauses; markers below still count
            result = DetectorResult((), "LEARNING")
        else:
            result = self.detector.detect(Frame(image, captured_at), calibration)
        self._identity_sample(image, captured_at, calibration, result)
        matrix = geometry.as_matrix(calibration.image_to_map)
        camera = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
        measured = []
        for marker_id in sorted(set(self.camera.robot_markers.values()).union(ROBOT_MARKER_IDS)):
            quad = markers.get(marker_id)
            if quad is None:
                continue
            try:
                points = np.asarray(quad, dtype=float)
            except (TypeError, ValueError):
                continue
            if points.shape != (4, 2) or not np.all(np.isfinite(points)):
                continue
            x, y = geometry.apply(matrix, [points.mean(axis=0)])[0]
            if not math.isfinite(x) or not math.isfinite(y):
                continue
            if camera is not None:
                x, y = geometry.parallax_correct((x, y), camera, ROBOT_TOP_HEIGHT_M)
            min_x, min_y, max_x, max_y = calibration.track_bounds_m
            if min_x <= x <= max_x and min_y <= y <= max_y:
                measured.append(Detection(float(x), float(y), 2 * ROTATION_RADIUS_M, 1.0, marker_id))
        if measured:
            # Fleet removes a single duplicate per marker. Removing here as well
            # would erase a second, adjacent robot when Fleet processes the frame.
            anonymous = list(result.detections) if result.status == "OK" else []
            result = DetectorResult(tuple((measured + anonymous)[:MAX_DETECTIONS]), "OK")
        return calibration, result


def _challenges(config: Mapping, led: led_identity.LedConfig) -> list[dict]:
    """D-596: Fleet's ``identity_challenges`` (else the single v1.130 ``identity_challenge``), checked."""
    raw = config.get("identity_challenges")
    if not isinstance(raw, list):
        raw = [config.get("identity_challenge")]
    found = {}
    for item in raw[:len(led.hues)]:  # at most one per colour
        challenge = _challenge(item, led)
        if challenge is not None:
            found.setdefault(challenge["request_id"], challenge)
    return list(found.values())


def _challenge(raw, config: led_identity.LedConfig) -> dict | None:
    """Fleet's ``identity_challenge``, checked; None when absent or malformed."""
    if not isinstance(raw, dict):
        return None
    request_id, color = raw.get("request_id"), raw.get("color")
    start, end = raw.get("not_before"), raw.get("not_after")
    if (not isinstance(request_id, str) or not request_id or color not in config.hues
            or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                   for v in (start, end))
            or not 0.0 < end - start <= led_identity.MAX_WINDOW_S):
        return None
    return {"request_id": request_id, "color": color, "not_before": float(start), "not_after": float(end)}
