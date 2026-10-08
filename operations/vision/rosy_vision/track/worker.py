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

from core_common.protocol.overhead_detections import OverheadDetection, OverheadDetectionsPayload
from rosy_vision.project import CameraMap, Point
from rosy_vision.track.background_blob import BackgroundBlobDetector
from rosy_vision.track.calibration import choose
from rosy_vision.track.fleet_client import TrackPublishError
from rosy_vision.track import led_identity
from rosy_vision.track.model import (
    Calibration, Detection, DetectorResult, Frame, RobotDetector, ROBOT_TOP_HEIGHT_M,
    ROTATION_RADIUS_M, MAX_DETECTIONS,
)
from rosy_vision.track import geometry

logger = logging.getLogger("rosy_vision.track")

CONFIG_REFRESH_S = 2.0
FAILURE_LOG_INTERVAL_S = 30.0
_SEQ_MODULUS = 0x100000000


def decode_jpeg(jpeg: bytes) -> np.ndarray | None:
    if not isinstance(jpeg, bytes) or not jpeg:
        return None
    return cv2.imdecode(np.frombuffer(jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)


def build_payload(*, source_id: str, map_id: str, calibration_revision: str | None,
                  processor_revision: str, captured_at: float, seq: int,
                  result: DetectorResult) -> OverheadDetectionsPayload:
    detections = () if result.status != "OK" else tuple(
        OverheadDetection(x=round(d.x, 4), y=round(d.y, 4), footprint_m=round(d.footprint_m, 4),
                          score=round(d.score, 3), marker_id=d.marker_id)
        for d in result.detections)
    return OverheadDetectionsPayload(
        source_id=source_id, map_id=map_id, calibration_revision=calibration_revision,
        processor_revision=processor_revision, captured_at=captured_at, seq=seq,
        status=result.status, detections=detections)


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
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.camera = camera
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
        # D-472: the one open identity challenge Fleet named, its ring samples, and the last reported.
        self._identity_id: str | None = None
        self._identity_samples: list[led_identity.Sample] = []
        self._identity_done: str | None = None
        self.led_config = led_identity.LedConfig()

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

    async def run_config_sync(self, stop_event: asyncio.Event,
                              interval_s: float = CONFIG_REFRESH_S) -> None:
        while not stop_event.is_set():
            await self.refresh_config()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass

    async def process(self, frame, markers: Mapping[int, Sequence[Point]]
                      ) -> OverheadDetectionsPayload | None:
        """Track one frame and publish the result; None when skipped (undecodable, or busy)."""
        if self._busy:
            return None
        self._busy = True
        try:
            return await self._process(frame, markers)
        finally:
            self._busy = False

    async def _process(self, frame, markers) -> OverheadDetectionsPayload | None:
        config = self._config or {}
        relearn = config.get("relearn_seq")
        if type(relearn) is not int:
            relearn = None
        lens = self.ingest.source_lens(self.camera.source_id)
        if self._executor is None:
            self._executor = ThreadPoolExecutor(
                max_workers=1, thread_name_prefix=f"rosy-vision-track-{self.camera.source_id}")
        challenge = _challenge(config.get("identity_challenge"), self.led_config)
        step = await asyncio.get_running_loop().run_in_executor(
            self._executor, functools.partial(
                self._detect, frame.jpeg, frame.captured_at, markers, config.get("calibration"),
                lens, relearn, challenge=challenge))
        if challenge is not None:
            await self._report_identity(challenge, frame.captured_at)
        if step is None:
            return None
        calibration, result = step
        payload = build_payload(
            source_id=self.camera.source_id, map_id=self.camera.map_id,
            calibration_revision=None if calibration is None else calibration.revision,
            processor_revision=self.detector.processor_revision, captured_at=frame.captured_at,
            seq=self._seq, result=result)
        self._seq = (self._seq + 1) % _SEQ_MODULUS
        try:
            await self.client.publish(payload)
        except TrackPublishError as exc:
            self._publish_log.failed((("status", exc.status_code), ("code", exc.code)))
        except httpx.HTTPError as exc:
            self._publish_log.failed((("error_type", type(exc).__name__),))
        else:
            self._publish_log.ok()
        return payload

    async def _report_identity(self, challenge: dict, now: float) -> None:
        """D-472: once the window has passed, send Fleet the verdict (never an image)."""
        request_id = challenge["request_id"]
        if now <= challenge["not_after"] or self._identity_done == request_id:
            return
        self._identity_done = request_id
        samples = self._identity_samples if self._identity_id == request_id else []
        verdict = led_identity.decide(samples, not_before=challenge["not_before"],
                                      not_after=challenge["not_after"], now=now, config=self.led_config)
        self._identity_samples = []
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
                         result: DetectorResult, challenge: dict | None) -> None:
        """Ring samples of the anonymous blobs while a challenge window is open (detection thread)."""
        if (challenge is None or result.status != "OK"
                or not challenge["not_before"] <= captured_at <= challenge["not_after"]):
            return
        if challenge["request_id"] != self._identity_id:
            self._identity_id, self._identity_samples = challenge["request_id"], []
        inverse = np.linalg.inv(geometry.as_matrix(calibration.image_to_map))
        scale_x = image.shape[1] / calibration.image_size[0]
        scale_y = image.shape[0] / calibration.image_size[1]
        blobs = []
        for d in result.detections:
            if d.marker_id is not None:
                continue
            # ponytail: floor-plane inverse, no parallax; the ring's outer radius absorbs the
            # top-height offset. Use the lens camera model if the field measurement says so.
            (px, py), (ex, ey) = geometry.apply(inverse, [(d.x, d.y), (d.x + d.footprint_m / 2, d.y)])
            if not all(math.isfinite(v) for v in (px, py, ex, ey)):
                continue
            radius = math.hypot((ex - px) * scale_x, (ey - py) * scale_y)
            blobs.append(led_identity.Blob(px * scale_x, py * scale_y, radius, d.x, d.y))
        if len(self._identity_samples) < led_identity.MAX_SAMPLES:
            self._identity_samples.append(led_identity.sample_frame(
                image, captured_at=captured_at, calibration_revision=calibration.revision,
                blobs=blobs, color=challenge["color"], config=self.led_config))

    def _detect(self, jpeg: bytes, captured_at: float, markers, record, lens, relearn: int | None,
                challenge: dict | None = None) -> tuple[Calibration | None, DetectorResult] | None:
        """Detection-thread half of a step: relearn, decode, choose the calibration, detect."""
        if relearn is not None:
            if self._relearn_seen is not None and relearn > self._relearn_seen:
                self.detector.reset()  # if this raises, the old baseline stays: tried again
            self._relearn_seen = relearn
        image = self.decode(jpeg)
        if image is None:
            return None
        size = (int(image.shape[1]), int(image.shape[0]))
        calibration = choose(self.camera, markers, record, frame_size=size, lens=lens)
        if calibration is None:
            return None, DetectorResult((), "CALIBRATION_REQUIRED")
        result = self.detector.detect(Frame(image, captured_at), calibration)
        self._identity_sample(image, captured_at, calibration, result, challenge)
        matrix = geometry.as_matrix(calibration.image_to_map)
        camera = geometry.camera_from_homography(matrix, calibration.image_size, calibration.hfov_deg)
        measured = []
        for marker_id in self.camera.robot_markers.values():
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
