"""Subject: the learned paint mask for the lane keeper, computed off the camera thread (D-408).

The model takes ~300 ms per frame on a Pi 5 while the camera runs at ~8 Hz, so inference runs
on one worker thread on the latest frame only. The keeper asks for the newest mask no older
than `stale_s`; when there is none (no model, a failed inference, too old) the caller uses
its fallback paint source for that frame and says so.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np


class LearnedPaintWorker:
    def __init__(self, slot, *, stale_s: float = 0.6, warn: Callable[[str], None] = lambda _m: None,
                 clock: Callable[[], float] = time.monotonic, start: bool = True):
        if not stale_s > 0:
            raise ValueError("stale_s must be positive")
        self._slot, self._stale_s, self._warn, self._clock = slot, float(stale_s), warn, clock
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._pending: tuple[float, np.ndarray, int | None] | None = None   # (submitted_at, frame, tag)
        self._result: tuple[float, np.ndarray, dict] | None = None   # (done_at, mask, summary)
        self._closed = False
        self._frames = 0
        self.last_error: str | None = None
        self._thread = threading.Thread(target=self._run, name="learned-paint", daemon=True) if start else None
        if self._thread:
            self._thread.start()

    def submit(self, frame: np.ndarray, tag: int | None = None) -> None:
        """Offer the newest frame; an older frame still waiting is replaced. `tag` (the
        caller's frame counter) comes back in the summary of the mask made from this frame."""
        with self._lock:
            self._pending = (self._clock(), frame, tag)
        self._wake.set()

    def latest(self, shape: tuple[int, int]) -> tuple[np.ndarray | None, dict | None]:
        """The newest mask of this frame size whose frame was submitted no more than stale_s
        ago (inference time counts toward the age), else (None, None)."""
        with self._lock:
            result = self._result
        if result is None:
            return None, None
        done_at, mask, summary = result
        if self._clock() - done_at > self._stale_s or mask.shape != tuple(shape):
            return None, None
        return mask, summary

    def mask_for(self, frame: np.ndarray, every_n: int = 1) -> np.ndarray | None:
        """The keeper's per-frame entry: submit every `every_n`-th frame and serve the newest
        mask in between. A mask is served only while it is at most `every_n` frames old
        (every_n - 1 frames in between plus the one the inference finishes on) and no older
        than stale_s; otherwise None and the caller falls back for this frame."""
        index, self._frames = self._frames, self._frames + 1
        if index % every_n == 0:
            self.submit(frame, tag=index)
        mask, summary = self.latest(frame.shape[:2])
        if mask is None or summary["tag"] is None or index - summary["tag"] > every_n:
            return None
        return mask

    def step(self) -> None:
        """Run one pending inference now (the worker loop body; tests call it directly)."""
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        submitted_at, frame, tag = pending
        model = self._slot.poll() if self._slot is not None else None
        if model is None:
            self.last_error = f"no model ({getattr(self._slot, 'last_error', None)})"
            return
        try:
            mask, latency_ms = model.infer_mask(frame)
        except Exception as exc:  # noqa: BLE001 - a failed inference is no paint, never a crash.
            self.last_error = f"inference failed: {exc}"
            self._warn(f"learned paint: {self.last_error}")
            return
        self.last_error = None
        summary = {"model_revision": model.model_revision, "latency_ms": round(latency_ms, 1), "tag": tag}
        with self._lock:
            self._result = (submitted_at, mask, summary)

    def close(self, timeout: float = 1.0) -> None:
        self._closed = True
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self) -> None:
        while not self._closed:
            self._wake.wait(0.5)
            self._wake.clear()
            if not self._closed:
                self.step()
