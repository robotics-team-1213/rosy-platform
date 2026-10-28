"""Operator-review proposals (D-360 field corners, D-375 map homography) for :class:`IngestServer`.

Moved out of ``ingest.py`` unchanged (D-766 size, before the D-772 station additions); the
server binds these functions as methods, so ``self`` is the ``IngestServer``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import BrokenExecutor
from dataclasses import dataclass
from typing import Mapping

import cv2
from websockets.http11 import Headers, Response

from rosy_vision import map_worker
from rosy_vision.field_detect import DETECTOR_VERSION, FieldDetection, detect_field_jpeg
from rosy_vision.map_register import REGISTER_VERSION, RegistrationResult

logger = logging.getLogger("rosy_vision.ingest")

# Field detection is ~30 ms of CPU per frame: at most one run per source per this
# interval, whoever asks; readers in between get the last result.
_FIELD_DETECT_INTERVAL_S = 1.0
# Map registration (D-375) is seconds of CPU per frame and runs in a separate worker
# process (never on this event loop's threads): one run in flight per source, the next
# at least this long after the last one finished, one worker for all sources.
_MAP_REGISTER_INTERVAL_S = 1.0


@dataclass
class _FieldRun:
    """The last field detection for one source; ``detection`` is None while it runs or after it failed."""

    frame: LatestFrame
    started: float
    detection: FieldDetection | None = None


@dataclass
class _MapRun:
    """The last map registration for one source. ``finished`` is None while it runs (the
    next run may start ``_MAP_REGISTER_INTERVAL_S`` after it); ``failed`` marks an error."""

    frame: LatestFrame
    finished: float | None = None
    failed: bool = False
    result: RegistrationResult | None = None


async def _field_proposal_response(self, source: str, frame: LatestFrame) -> Response:
    """D-360: a field-corner proposal for operator review. Never applied to sightings.

    Detection runs off the event loop, at most once per source per
    ``_FIELD_DETECT_INTERVAL_S`` across all lease subjects.
    """
    run = self._field_cache.get(source)
    now_mono = time.monotonic()
    if run is None or (run.frame is not frame
                       and now_mono - run.started >= _FIELD_DETECT_INTERVAL_S):
        run = _FieldRun(frame=frame, started=now_mono)
        self._field_cache[source] = run
        try:
            run.detection = await asyncio.to_thread(detect_field_jpeg, frame.jpeg)
        except (ValueError, cv2.error):
            return _http_response(422, b"field detection failed\n",
                                  extra={"X-Frame-State": "detection-error"})
    detection = run.detection
    if detection is None:  # still running for another reader, or failed on this frame
        return _http_response(429, b"field detection busy\n", extra={"Retry-After": "1"})
    frame = run.frame
    age = max(0.0, time.time() - frame.captured_at)
    width, height = detection.image_size
    body = {
        "source": source,
        "frame_seq": frame.header.seq,
        "frame_age_ms": round(age * 1000),
        "image": {"width": width, "height": height},
        "proposal": detection.proposal.to_dict() if detection.proposal else None,
        "reason": detection.reason,
        "detector": {"version": DETECTOR_VERSION, "elapsed_ms": round(detection.elapsed_ms, 1)},
        "lens": self.source_lens(source),
    }
    return _http_response(200, (json.dumps(body, separators=(",", ":")) + "\n").encode(), extra={
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
    })

async def _map_proposal_response(self, source: str, frame: LatestFrame) -> Response:
    """D-375: an image-to-map homography proposal from the lane paint, for operator review.

    Never applied to sightings or ``CameraMap``. ``proposal`` is set only when the fit
    passed every gate; a rejected fit is returned as ``rejected_fit`` with the reason
    (its coverage and cut sides still tell the installer where to move the camera).
    Runs off the event loop on one shared worker thread, single flight per source,
    and a new run only ``_MAP_REGISTER_INTERVAL_S`` after the last one finished. A read
    that arrives mid-run gets the source's last successful result (its own
    ``frame_seq``/age, ``X-Proposal-State: previous``), or 429 when there is none yet.
    A failed run answers 422 until the next run replaces it.
    """
    run = self._map_cache.get(source)
    state = "current"
    if run is not None and run.finished is None:  # single flight per source
        run = self._map_done.get(source)
        state = "previous"
        if run is None:
            return _http_response(429, b"map registration busy\n", extra={"Retry-After": "1"})
    elif run is None or (run.frame is not frame
                         and time.monotonic() - run.finished >= _MAP_REGISTER_INTERVAL_S):
        run = _MapRun(frame=frame)
        self._map_cache[source] = run
        try:
            if self._map_executor is None:
                self._map_executor = map_worker.start(self.map_paint)
            run.result = await asyncio.get_running_loop().run_in_executor(
                self._map_executor, self._map_job, frame.jpeg)
        except Exception as exc:  # noqa: BLE001 - any failure is a per-frame 422, never a crash
            logger.exception("map registration failed for source %s", source)
            run.failed = True
            if isinstance(exc, BrokenExecutor):  # worker died: start a fresh one next time
                self.close_map_worker()
        finally:
            run.finished = time.monotonic()
        # Only a run that is still this source's current one: a reconnect mid-run cleared
        # the caches, and the old connection's fit must not come back as "previous".
        if not run.failed and self._map_cache.get(source) is run:
            self._map_done[source] = run
    if run.failed:
        return _http_response(422, b"map registration failed\n",
                              extra={"X-Frame-State": "detection-error"})
    result = run.result
    frame = run.frame
    age = max(0.0, time.time() - frame.captured_at)
    width, height = result.image_size
    fit = result.registration.to_dict() if result.registration is not None else None
    body = {
        "source": source,
        "frame_seq": frame.header.seq,
        "frame_age_ms": round(age * 1000),
        "image": {"width": width, "height": height},
        "map_frame": "map",
        "accepted": result.accepted,
        "proposal": fit if result.accepted else None,
        # A rejected fit keeps only placement hints, never a homography to misuse.
        "rejected_fit": None if result.accepted or fit is None else {
            key: fit[key] for key in ("score", "precision", "coverage", "cut_sides",
                                      "cut_directions", "side_outside")},
        "reason": result.reason,
        "registrar": {"version": REGISTER_VERSION, "elapsed_ms": round(result.elapsed_ms, 1)},
    }
    return _http_response(200, (json.dumps(body, separators=(",", ":")) + "\n").encode(), extra={
        "Content-Type": "application/json", "Cache-Control": "no-store",
        "X-Frame-Seq": str(frame.header.seq),
        "X-Frame-Age-Ms": str(round(age * 1000)),
        "X-Proposal-State": state,
    })


def _http_response(status: int, body: bytes, *, extra: Mapping[str, str] | None = None) -> Response:
    reason = {200: "OK", 401: "Unauthorized", 404: "Not Found", 409: "Conflict",
              422: "Unprocessable Content", 429: "Too Many Requests",
              503: "Service Unavailable"}[status]
    headers = Headers({"Content-Length": str(len(body)), "X-Content-Type-Options": "nosniff",
                       "Cache-Control": "no-store", **dict(extra or {})})
    return Response(status, reason, headers, body)
