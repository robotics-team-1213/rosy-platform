"""D-375 map registration in a separate, low-priority worker process.

A registration is seconds of CPU with Python running between the OpenCV calls. In a
thread it holds the GIL long enough to starve the ingest event loop: frame reads
stall, phone hellos time out and phones reconnect (live test, 2026-10-01). One spawned
process with one worker keeps the loop free and bounds proposals to one run at a time
for all sources. The map paint is sent once, to the worker's initializer.
"""

from __future__ import annotations

import multiprocessing
import os
from concurrent.futures import ProcessPoolExecutor

from rosy_vision.map_register import MapPaint, RegistrationResult, register_map_jpeg

# OpenCV threads inside the worker: the coarse search is many small calls, so more
# threads buy little and would compete with the Vision worker's ArUco detection.
WORKER_CV_THREADS = 2
# Added to the worker's nice value where the OS supports it (Linux site PC).
WORKER_NICENESS = 10

_paint: MapPaint | None = None


def _initialize(paint: MapPaint, cv_threads: int) -> None:
    global _paint
    import cv2

    cv2.setNumThreads(cv_threads)
    if hasattr(os, "nice"):
        try:
            os.nice(WORKER_NICENESS)
        except OSError:
            pass
    _paint = paint


def register(jpeg: bytes) -> RegistrationResult:
    """Run one registration in the worker (raises ``ValueError`` on a bad JPEG)."""
    if _paint is None:
        raise RuntimeError("map worker is not initialized")
    return register_map_jpeg(jpeg, _paint)


def start(paint: MapPaint, cv_threads: int = WORKER_CV_THREADS) -> ProcessPoolExecutor:
    """One spawned worker process holding ``paint``; submit :func:`register` to it."""
    return ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn"),
        initializer=_initialize, initargs=(paint, cv_threads))
