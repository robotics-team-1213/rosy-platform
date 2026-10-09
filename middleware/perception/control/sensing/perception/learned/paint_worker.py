"""Subject: the learned paint mask for the lane keeper, computed off the camera thread (D-408).

The model takes ~300 ms per frame on a Pi 5 while the camera runs at ~8 Hz, so inference runs
on one worker thread on the latest frame only. The keeper asks for the newest mask no older
than `stale_s`; when there is none (no model, a failed inference, too old) the caller uses
its fallback paint source for that frame and says so.

target "drivable" (learned_paint_target): the model's infer_drivable gives the drivable way
(kind "drivable") or, without a usable drivable class, the lane_marking mask (kind
"lane_marking"); the caller cleans each kind with its own function and reads `used_paint_kind`.
The same inference's crosswalk class mask (info "crosswalk_mask", D-597 amendment) is served beside
the paint as `used_crosswalk`, moved like the paint when the paint is warped (D-570).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import numpy as np

#: D-570: a warped mask is also bounded by the worker clock (a stalled stamp clock is no licence).
WARP_CLOCK_MARGIN_S = 0.1
#: learned_paint_target values: the model's lane_marking classes, or its drivable class (D-597).
TARGETS = ("lane_marking", "drivable")


class LearnedPaintWorker:
    def __init__(self, slot, *, stale_s: float = 0.6, warn: Callable[[str], None] = lambda _m: None,
                 clock: Callable[[], float] = time.monotonic, start: bool = True,
                 target: str = "lane_marking"):
        if not stale_s > 0:
            raise ValueError("stale_s must be positive")
        if target not in TARGETS:
            raise ValueError(f"target must be one of {TARGETS}")
        self.target = target
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
        self.reuse: dict | None = None
        self.last_error: str | None = None
        self.used_model_revision: str | None = None
        self.used_paint_kind: str | None = None
        self.used_drivable: dict | None = None
        self.used_crosswalk: np.ndarray | None = None
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
                 reuse_n: int | None = None,
                 clean_drivable: Callable[[np.ndarray], np.ndarray] | None = None) -> np.ndarray | None:
        """The keeper's per-frame entry: submit every `every_n`-th frame and serve the newest
        mask in between. `stamp` is the frame's time (default: the worker clock). `clean`
        post-processes a mask once per new mask (the result is cached), so a reused mask costs
        no connected-components pass.

        With `motion` (D-570) the mask is moved to this frame: `motion(cleaned, src_stamp, stamp)`
        returns (warped mask, dxy, dyaw) or why not, and a mask whose frame is at most `max_age_s`
        older (and submitted at most max(stale_s, max_age_s) + WARP_CLOCK_MARGIN_S ago by the
        worker clock) is served warped. Otherwise (and without `motion`) a mask is served
        unwarped only while it is at most `reuse_n` (default `every_n`) frames old, at most that
        many observed frame periods (x1.5) old by frame stamps, and no older than stale_s; else
        None and the caller falls back for this frame. `self.reuse` says what happened
        (keep_debug telemetry: paint_reuse warped|unwarped|fresh|none, paint_warp_skipped).
        A mask of kind "drivable" is cleaned by `clean_drivable` instead of `clean` (required then)."""
        self.used_model_revision = self.used_paint_kind = self.used_drivable = self.used_crosswalk = None
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
        if index % every_n == 0:
            self.submit(frame, tag=index, stamp=stamp)
        with self._lock:
            result = self._result
        self.reuse = dict(paint_reuse='none', paint_warp_skipped='no_mask', paint_mask_age_s=None,
                          paint_motion_dxy_m=None, paint_motion_dyaw_rad=None)
        if result is None or result[1].shape != frame.shape[:2] or result[2]["tag"] is None:
            return None
        submitted_at, mask, summary = result
        age_s = stamp - summary["stamp"]
        self.reuse.update(paint_mask_age_s=round(age_s, 3), paint_warp_skipped='off')
        if motion is not None:
            if age_s < 0:
                moved = 'clock_back'
            elif (age_s > max_age_s
                  or self._clock() - submitted_at > max(self._stale_s, max_age_s) + WARP_CLOCK_MARGIN_S):
                moved = 'too_old'
            else:
                moved = motion(self._cleaned(result, clean, clean_drivable), summary["stamp"], stamp)
            if not isinstance(moved, str):
                warped, dxy, dyaw = moved
                crosswalk = summary.get("crosswalk")
                if crosswalk is not None:
                    crosswalk = motion(crosswalk, summary["stamp"], stamp)
                    crosswalk = None if isinstance(crosswalk, str) else crosswalk[0]
                self.reuse.update(paint_reuse='warped', paint_warp_skipped=None,
                                  paint_motion_dxy_m=round(dxy, 4), paint_motion_dyaw_rad=round(dyaw, 4))
                self._mark_used(summary)
                self.used_crosswalk = crosswalk
                return warped
            self.reuse['paint_warp_skipped'] = moved
        if (self._clock() - submitted_at > self._stale_s or index - summary["tag"] > reuse_n
                or age_s < 0 or (self._period is not None and age_s > 1.5 * reuse_n * self._period)):
            return None
        self.reuse['paint_reuse'] = 'fresh' if index == summary["tag"] else 'unwarped'
        self._mark_used(summary)
        return self._cleaned(result, clean, clean_drivable)

    def _mark_used(self, summary) -> None:
        self.used_model_revision = summary['model_revision']
        self.used_paint_kind = summary.get('paint_kind', 'lane_marking')
        self.used_drivable = summary.get('drivable')
        self.used_crosswalk = summary.get('crosswalk')

    def _cleaned(self, result, clean, clean_drivable=None):
        if result[2].get('paint_kind') == 'drivable':
            if clean_drivable is None:
                raise ValueError("a drivable paint mask needs clean_drivable")
            clean = clean_drivable
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
        self.used_model_revision = self.used_paint_kind = self.used_drivable = self.used_crosswalk = None
        self.reuse = None
        self._frames, self._last_stamp, self._period = 0, None, None

    def step(self) -> None:
        """Run one pending inference now (the worker loop body; tests call it directly)."""
        with self._lock:
            pending, self._pending = self._pending, None
        if pending is None:
            return
        submitted_at, frame, tag, stamp, generation = pending
        model = self._slot.poll() if self._slot is not None else None
        if model is None:
            self.last_error = f"no model ({getattr(self._slot, 'last_error', None)})"
            return
        try:
            if self.target == "drivable":
                mask, kind, drivable, latency_ms = model.infer_drivable(frame)
            else:
                (mask, latency_ms), kind, drivable = model.infer_mask(frame), "lane_marking", None
        except Exception as exc:  # noqa: BLE001 - a failed inference is no paint, never a crash.
            self.last_error = f"inference failed: {exc}"
            self._warn(f"learned paint: {self.last_error}")
            return
        self.last_error = None
        crosswalk = drivable.pop("crosswalk_mask", None) if drivable else None
        summary = {"model_revision": model.model_revision, "latency_ms": round(latency_ms, 1), "tag": tag, "stamp": stamp,
                   "paint_kind": kind, "drivable": drivable, "crosswalk": crosswalk}
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
