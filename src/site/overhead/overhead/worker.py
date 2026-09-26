"""Latest-only camera-to-Fleet pipeline; no queues and no robot command path."""

from __future__ import annotations

import math
import time
import asyncio
from typing import Callable

from overhead.detect import detect_markers
from overhead.project import CameraMap, project_frame

MAX_FUTURE_S = 0.05


class VisionWorker:
    def __init__(self, *, source_id: str, ingest, camera: CameraMap, publisher,
                 detector: Callable = detect_markers, clock: Callable[[], float] = time.time,
                 max_age_s: float = 0.75) -> None:
        if not math.isfinite(max_age_s) or max_age_s <= 0:
            raise ValueError("vision max age must be positive and finite")
        self.source_id = source_id
        self.ingest = ingest
        self.camera = camera
        self.publisher = publisher
        self.detector = detector
        self.clock = clock
        self.max_age_s = max_age_s
        self._last_frame_key: tuple[int, float, float] | None = None

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
        sightings = project_frame(
            self.camera,
            source_id=self.source_id,
            seq=frame.header.seq,
            captured_at=frame.captured_at,
            markers=markers,
        )
        for sighting in sightings:
            await self.publisher.publish(sighting)
        return sightings

    async def run(self, *, stop_event: asyncio.Event, poll_interval_s: float = 0.03) -> None:
        if not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
            raise ValueError("worker poll interval must be positive and finite")
        while not stop_event.is_set():
            await self.process_latest()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval_s)
            except asyncio.TimeoutError:
                pass
