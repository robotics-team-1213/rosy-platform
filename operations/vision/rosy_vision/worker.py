"""Latest-only camera-to-Fleet pipeline; no queues and no robot command path."""

from __future__ import annotations

import math
import time
import asyncio
import logging
from typing import Callable

from rosy_vision.detect import detect_markers
from rosy_vision.field_calib import FieldCalibrator
from rosy_vision.field_detect import detect_field_jpeg
from rosy_vision.project import CameraMap, project_frame, project_place_markers

MAX_FUTURE_S = 0.05
#: Field-boundary detection cadence (D-484): the camera is fixed, so the quad is
#: re-measured at this spacing, not per frame.
FIELD_INTERVAL_S = 1.0
#: Minimum spacing between paint registrations while orientation stays unresolved.
PAINT_RETRY_S = 5.0
#: D-564: place markers do not move; Fleet's teach freshness is 2 s.
PLACE_MARKER_INTERVAL_S = 0.5

logger = logging.getLogger("rosy_vision")


class VisionWorker:
    def __init__(self, *, source_id: str, ingest, camera: CameraMap, publisher,
                 detector: Callable = detect_markers, clock: Callable[[], float] = time.time,
                 max_age_s: float = 0.75, tracker=None,
                 calibrator: FieldCalibrator | None = None,
                 field_detector: Callable = detect_field_jpeg,
                 field_interval_s: float = FIELD_INTERVAL_S,
                 paint_registrar=None,
                 paint_retry_s: float = PAINT_RETRY_S) -> None:
        if not math.isfinite(max_age_s) or max_age_s <= 0:
            raise ValueError("vision max age must be positive and finite")
        if not math.isfinite(field_interval_s) or field_interval_s <= 0:
            raise ValueError("field interval must be positive and finite")
        if not math.isfinite(paint_retry_s) or paint_retry_s <= 0:
            raise ValueError("paint retry interval must be positive and finite")
        self.source_id = source_id
        self.ingest = ingest
        self.camera = camera
        self.publisher = publisher
        self.detector = detector
        self.clock = clock
        self.max_age_s = max_age_s
        self._last_frame_key: tuple[int, float, float] | None = None
        # D-457: optional markerless tracking step (rosy_vision.track.worker.TrackWorker).
        self.tracker = tracker
        # D-484: optional field-boundary calibration source.
        self.calibrator = calibrator
        self.field_detector = field_detector
        self.field_interval_s = field_interval_s
        self.paint_registrar = paint_registrar
        self.paint_retry_s = paint_retry_s
        self._last_field_at = -math.inf
        self._last_paint_at = -math.inf
        self._paint_task: asyncio.Task | None = None
        self._last_place_at = -math.inf

    async def process_latest(self) -> tuple:
        if self.source_id != self.camera.source_id:
            return ()
        frame = self.ingest.latest_frame(self.source_id)
        if frame is None:
            return ()
        key = (frame.header.seq, frame.captured_at, frame.received_at)
        if key == self._last_frame_key:
            return ()
        self._last_frame_key = key

        age_s = self.clock() - frame.captured_at
        if age_s < -MAX_FUTURE_S or age_s > self.max_age_s:
            return ()

        markers = self.detector(frame.jpeg)
        # Installer guidance only (phone status); ids, never pixels, leave this process.
        self.ingest.report_markers(
            self.source_id,
            [marker_id for marker_id in (self.camera.corner_marker_ids or ())
             if marker_id in markers],
            [robot for robot, marker_id in self.camera.robot_markers.items() if marker_id in markers],
        )
        homography = await self._field_calibration_step(frame) if self.calibrator else None
        sightings = project_frame(
            self.camera,
            source_id=self.source_id,
            seq=frame.header.seq,
            captured_at=frame.captured_at,
            markers=markers,
            homography=homography,
        )
        try:
            for sighting in sightings:
                await self.publisher.publish(sighting)
        finally:
            # A rejected sighting must not cost the frame its tracking step, and a tracking
            # failure must not mask the sighting error.
            if self.camera.place_markers:
                await self._publish_place_markers(frame, markers, homography)
            if self.tracker is not None:
                try:
                    await self.tracker.process(frame, markers)
                except Exception as exc:
                    # Do not log URLs, request bodies, headers, or arbitrary exception text.
                    logger.error("tracking step failed source=%s error_type=%s",
                                 self.source_id, type(exc).__name__)
        return sightings

    async def _publish_place_markers(self, frame, markers, homography) -> None:
        """D-564: at most every ``PLACE_MARKER_INTERVAL_S``; a rejection is logged, never raised."""
        now = self.clock()
        if now - self._last_place_at < PLACE_MARKER_INTERVAL_S:
            return
        payload = project_place_markers(self.camera, seq=frame.header.seq, captured_at=frame.captured_at,
                                        markers=markers, homography=homography)
        if payload is None:
            return
        self._last_place_at = now
        try:
            await self.publisher.publish_place_markers(payload)
        except Exception as exc:  # noqa: BLE001 - logged by type only, never the body
            logger.error("place marker publish failed source=%s error_type=%s",
                         self.source_id, type(exc).__name__)

    async def _field_calibration_step(self, frame):
        """D-484: re-measure the field quad at a fixed cadence and report the state.

        The heavy paint registration never blocks this coroutine: it runs as a
        single-flight background task on the low-priority worker process.
        """
        now_mono = time.monotonic()
        if now_mono - self._last_field_at >= self.field_interval_s:
            self._last_field_at = now_mono
            try:
                detection = await asyncio.to_thread(self.field_detector, frame.jpeg)
            except Exception as exc:  # noqa: BLE001 - a bad frame never stops the pipeline
                # Do not log URLs, request bodies, headers, or arbitrary exception text.
                logger.error("field detection failed source=%s error_type=%s",
                             self.source_id, type(exc).__name__)
                return self.calibrator.homography()
            state = self.calibrator.feed(detection)
            self.ingest.report_field(self.source_id, state.to_dict())
            if self.calibrator.needs_orientation() and self.paint_registrar is not None:
                self._request_orientation(frame.jpeg)
        return self.calibrator.homography()

    def _request_orientation(self, jpeg: bytes) -> None:
        if self._paint_task is not None and not self._paint_task.done():
            return
        if time.monotonic() - self._last_paint_at < self.paint_retry_s:
            return
        self._last_paint_at = time.monotonic()
        self._paint_task = asyncio.create_task(self._resolve_orientation(jpeg))

    async def _resolve_orientation(self, jpeg: bytes) -> None:
        try:
            result = await self.paint_registrar(jpeg)
        except Exception as exc:  # noqa: BLE001 - logged by type only, never the body
            logger.error("paint registration failed source=%s error_type=%s",
                         self.source_id, type(exc).__name__)
            return
        if result is None or not result.accepted or result.registration is None:
            return
        ok, reason = self.calibrator.resolve_orientation(
            result.registration.map_to_image, result.image_size)
        if ok:
            self.ingest.report_field(self.source_id, self.calibrator.snapshot().to_dict())
            logger.info("field orientation resolved source=%s rotation=%d",
                        self.source_id, self.calibrator.snapshot().orientation or 0)
        else:
            logger.info("field orientation rejected source=%s reason=%s", self.source_id, reason)

    async def run(self, *, stop_event: asyncio.Event, poll_interval_s: float = 0.03) -> None:
        if not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
            raise ValueError("worker poll interval must be positive and finite")
        while not stop_event.is_set():
            await self.process_latest()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_s)
            except asyncio.TimeoutError:
                pass
