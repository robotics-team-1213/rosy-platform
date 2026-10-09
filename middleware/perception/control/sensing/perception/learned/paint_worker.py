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
        self._pending: tuple[float, np.ndarray, int | None, float | None, int] | None = None   # (submitted_at, frame, tag, stamp, generation)
        self._result: tuple[float, np.ndarray, dict] | None = None   # (done_at, mask, summary)
        self._closed = False
        self._frames = 0
        self._generation = 0
        self._last_stamp: float | None = None
        self._period: float | None = None   # EMA of the frame stamp interval
        self._clean_cache = None
        self._busy = False
        self._last_submit: int | None = None   # frame index of the last when_idle submission
        self.reuse: dict | None = None
        self.last_error: str | None = None
        self.used_model_revision: str | None = None
        self._thread = threading.Thread(target=self._run, name="learned-paint", daemon=True) if start else None
        if self._thread:
            self._thread.start()

    def submit(self, frame: np.ndarray, tag: int | None = None, stamp: float | None = None) -> None:
        """Offer the newest frame; an older frame still waiting is replaced. `tag` (the
        caller's frame counter) comes back in the summary of the mask made from this frame."""
        with self._lock:
            self._pending = (self._clock(), frame, tag, stamp, self._generation)
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

    def mask_for(self, frame: np.ndarray, every_n: int = 1, stamp: float | None = None,
                 clean: Callable[[np.ndarray], np.ndarray] | None = None, *,
                 motion: Callable | None = None, max_age_s: float = 0.0,
                 reuse_n: int | None = None, when_idle: bool = False) -> np.ndarray | None:
        """The keeper's per-frame entry: submit every `every_n`-th frame and serve the newest
        mask in between. `stamp` is the frame's time (default: the worker clock). `clean`
        post-processes a mask once per new mask (the result is cached), so a reused mask costs
        no connected-components pass.

        With `motion` (D-570) the mask is moved to this frame: `motion(cleaned, src_stamp, stamp)`
        returns (warped mask, dxy, dyaw) or a fallback reason, and a mask whose frame is at most
        `max_age_s` older is served warped. Otherwise (and without `motion`) a mask is served
        unwarped only while it is at most `reuse_n` (default `every_n`) frames old, at most that
        many observed frame periods (x1.5) old by frame stamps, and no older than stale_s; else
        None and the caller falls back for this frame. `when_idle` submits only while the worker
        is idle (no frame waits behind a running inference), still at most every `every_n` frames.
        `self.reuse` says what happened (keep_debug telemetry)."""
        self.used_model_revision = None
        reuse_n = every_n if reuse_n is None else reuse_n
        stamp = self._clock() if stamp is None else float(stamp)
        if self._last_stamp is not None and stamp > self._last_stamp:
            dt = stamp - self._last_stamp
            if self._period is None:
                self._period = dt
            elif dt <= 2.0 * self._period:   # a pause is a gap, not a slower camera
                self._period = 0.8 * self._period + 0.2 * dt
        self._last_stamp = stamp
        index, self._frames = self._frames, self._frames + 1
        if when_idle:
            with self._lock:
                idle = self._pending is None and not self._busy
            if idle and (self._last_submit is None or index - self._last_submit >= every_n):
                self._last_submit = index
                self.submit(frame, tag=index, stamp=stamp)
        elif index % every_n == 0:
            self.submit(frame, tag=index, stamp=stamp)
        with self._lock:
            result = self._result
        if result is None or result[1].shape != frame.shape[:2] or result[2]["tag"] is None:
            self.reuse = dict(paint_mask_age_s=None, paint_compensated=False, paint_motion_dxy_m=None,
                              paint_motion_dyaw_rad=None, paint_fallback_reason='no_mask')
            return None
        submitted_at, mask, summary = result
        age_s = stamp - summary["stamp"]
        self.reuse = dict(paint_mask_age_s=round(age_s, 3), paint_compensated=False, paint_motion_dxy_m=None,
                          paint_motion_dyaw_rad=None, paint_fallback_reason=None if motion is not None else 'off')
        if motion is not None:
            moved = 'too_old' if not 0.0 <= age_s <= max_age_s else motion(
                self._cleaned(result, clean), summary["stamp"], stamp)
            if not isinstance(moved, str):
                warped, dxy, dyaw = moved
                self.reuse.update(paint_compensated=True, paint_motion_dxy_m=round(dxy, 4),
                                  paint_motion_dyaw_rad=round(dyaw, 4))
                self.used_model_revision = summary['model_revision']
                return warped
            self.reuse['paint_fallback_reason'] = moved
        if (self._clock() - submitted_at > self._stale_s or index - summary["tag"] > reuse_n
                or age_s < 0 or (self._period is not None and age_s > 1.5 * reuse_n * self._period)):
            return None
        self.used_model_revision = summary['model_revision']
        return mask if clean is None else self._cleaned(result, clean)

    def _cleaned(self, result, clean):
        if clean is None:
            return result[1]
        if self._clean_cache is None or self._clean_cache[0] is not result:
            self._clean_cache = (result, clean(result[1]))
        return self._clean_cache[1]

    def reset(self) -> None:
        """Forget the cached mask, the pending frame and the frame counter (the keeper restarted:
        a gap, no ground, another mode). An inference already running is discarded."""
        with self._lock:
            self._generation += 1
            self._pending = self._result = None
        self._clean_cache = None
        self.used_model_revision = None
        self.reuse = None
        self._frames, self._last_stamp, self._period, self._last_submit = 0, None, None, None

    def step(self) -> None:
        """Run one pending inference now (the worker loop body; tests call it directly)."""
        with self._lock:
            pending, self._pending = self._pending, None
            self._busy = pending is not None
        if pending is None:
            return
        try:
            self._infer(*pending)
        finally:
            self._busy = False

    def _infer(self, submitted_at, frame, tag, stamp, generation) -> None:
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
        summary = {"model_revision": model.model_revision, "latency_ms": round(latency_ms, 1), "tag": tag, "stamp": stamp}
        with self._lock:
            if generation == self._generation:   # a reset during the inference drops its mask
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
