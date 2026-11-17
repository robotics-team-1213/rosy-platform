"""Head-tracker step and the anchors POST for one source (display only, never a command).

The tracker costs a lot per frame on the N150 (0.7 fps measured 2026-11-13, markers went stale),
so it runs at most every ``STEP_INTERVAL_S``. Its anchors go to Fleet from a single-flight
background task after the detections POST: a slow or stuck anchors request can never delay a
detection, and nothing is queued (a state that finds the previous send still running is dropped).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from rosy_vision.post_guard import PostGuard
from rosy_vision.track.anchor_head_tracker import AnchorHeadTracker

logger = logging.getLogger("rosy_vision")

STEP_INTERVAL_S = 1.0
POST_TIMEOUT_S = 1.0


class AnchorFeed:
    def __init__(self, source_id: str, map_id: str, client, guard: PostGuard,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.source_id, self.map_id = source_id, map_id
        self.tracker = AnchorHeadTracker()
        #: Sightings the tracker measured on the last step (marker seen); () between steps.
        self.sightings: tuple = ()
        self._client, self._guard, self._clock = client, guard, clock
        self._next_at = 0.0
        self._pending: dict | None = None
        self._task: asyncio.Task | None = None

    def step(self, image, captured_at, calibration, result, *, processor_revision, seq):
        """Detection thread: the tracker at its own cadence; returns the (maybe filtered) result."""
        now = self._clock()
        self.sightings = ()
        if now < self._next_at:
            return result
        self._next_at = now + STEP_INTERVAL_S
        try:
            result, self.sightings, states = self.tracker.step(
                image, captured_at, calibration, result, source_id=self.source_id, map_id=self.map_id,
                processor_revision=processor_revision, seq=seq)
        except Exception as exc:  # noqa: BLE001 - display tracking never stops detections
            logger.warning("anchor head tracker failed source=%s error=%s", self.source_id, type(exc).__name__)
            return result
        # A Pinky without its own marker this frame is a home guess, not a track.
        targets = [t for t in states
                   if t.get("kind") != "pinky" or self.tracker.marker_seen(t.get("target_id"))]
        self._pending = {"source_id": self.source_id, "map_id": self.map_id,
                         "captured_at": captured_at, "targets": targets} if targets else None
        return result

    def send(self) -> None:
        """Event loop, after the detections POST: start the single-flight anchors POST."""
        payload, self._pending = self._pending, None
        if payload is None or not hasattr(self._client, "publish_anchors"):
            return
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._post(payload))

    async def _post(self, payload: dict) -> None:
        try:
            await asyncio.wait_for(
                self._guard.post(payload["captured_at"], lambda: self._client.publish_anchors(payload)),
                POST_TIMEOUT_S)
        except Exception as exc:  # noqa: BLE001 - logged by type only, never the body
            if isinstance(exc, asyncio.TimeoutError):  # the cancelled post never counted itself
                self._guard.post_errors += 1
            logger.warning("anchors not accepted source=%s error=%s", self.source_id, type(exc).__name__)
