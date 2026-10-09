"""D-589 recognition-driven camera tuning: the quality score and a bounded hill climb.

Score (D-589 1). Measured inside the approved calibration's track rectangle only, on a copy
whose long side is at most WORK_LONG_SIDE pixels, on luma (OpenCV BGR to gray):

- ``paint_contrast``: median luma of the lane paint minus median luma of the carpet, over
  the carpet noise. The paint is the site map lane paint (D-375 ``road_lines.stl``) warped
  into the frame through the calibration and grown by PAINT_BAND_PX, because an approved fit
  sits 1-3 work pixels off the real lines (2026-10-09 frames); the lane white is the median
  of the brighter half of that band. The carpet is the track minus the paint grown by
  CARPET_GAP_PX. Without a paint mesh the
  brightest BRIGHT_SHARE of the track stands in for the paint and the whole track for the
  carpet. Noise is the robust standard deviation 1.4826 x MAD, so parked robots, tape and
  signs do not inflate it.
- ``clip`` and ``crush``: share of track pixels at luma >= CLIP_LEVEL and <= CRUSH_LEVEL.
- ``marker_rate``: share of the robot markers present (seen in the last MARKER_PRESENT_S)
  that this frame shows. Left out (None) when no robot marker is present.

``score`` is the only formula. It is telemetry (shown to Fleet), not control: on the
2026-10-10 site frames it was flat within +-0.01 across every exposure that neither clips nor
crushes, below the 0.022 noise of one dwell, so nothing can be ranked by it (D-589 4).

Guarded expose-and-lock (D-589 4): ``Tuner`` is a pure state machine driven with the caller's
clock, the phone's last ``camera_state`` and the measurements. From the last locked EV, with
AE free, one DWELL_S dwell (the first SETTLE_S are AE settling) after the phone echoes the seq
in mode "vision": clip above CLIP_TUNE steps 1/3 EV down, crush above CRUSH_TUNE steps up,
else AE and AWB lock. Locked, it tunes again only on clip/crush past RETUNE_HARD or a sustained
light change. No probing. Display only (D-457 6): a camera setting never reaches a robot command.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from rosy_vision import protocol
from rosy_vision.protocol import CameraSetting, CameraState
from rosy_vision.track import geometry
from rosy_vision.track.model import Calibration

logger = logging.getLogger("rosy_vision.track")

WORK_LONG_SIDE = 640
CLIP_LEVEL = 247
CRUSH_LEVEL = 16
#: Above this clip or crush share the score is cut hard (D-589 1).
CLIP_CRUSH_SOFT = 0.05
#: Above this clip or crush share a locked camera tunes again at once (D-589 4).
CLIP_CRUSH_HARD = 0.15
#: paint_contrast at which the contrast term is one half. Start value: the 2026-10-09 site
#: frames (grey speckled carpet, robust noise about 20 levels) measure about 4-5.
CONTRAST_HALF = 1.5
#: Weight of marker_rate in the score when markers are present.
MARKER_WEIGHT = 0.3
#: Brightest share of the track used as paint when the site has no paint mesh.
BRIGHT_SHARE = 0.03
#: Paint band: the warped paint mask grown by this many work pixels on each side.
PAINT_BAND_PX = 2
#: Carpet: the track minus the paint grown by this many work pixels.
CARPET_GAP_PX = 4
MIN_PAINT_PX = 30
MIN_CARPET_PX = 500
MARKER_PRESENT_S = 600.0

DWELL_S = 4.0
SETTLE_S = 1.0
#: Tune levels in real EV: -2.0 .. +1.0 in 1/3 EV (thirds -6 .. +3), each sent as the nearest
#: compensation index (``ev`` = level / supported.ev_step; on an S21-class phone 0.1 EV).
EV_THIRDS = range(-6, 4)
#: A tune steps down 1/3 EV while the track clips more than CLIP_TUNE, up while it crushes more
#: than CRUSH_TUNE, and locks otherwise; never back to a level it left, at most MAX_STEPS steps.
CLIP_TUNE = 0.02
CRUSH_TUNE = 0.05
MAX_STEPS = 6
#: Locked: tune again when clip or crush passes RETUNE_HARD (a scene that already did at the
#: lock: when it gets RETUNE_HYSTERESIS worse), at most once per backoff (5 min, doubling) ...
RETUNE_HARD = 0.15
RETUNE_HYSTERESIS = 0.05
BACKOFF_START_S = 5 * 60.0
#: ... or when the track median brightness moves more than LUMA_SHIFT_EV for LUMA_HOLD_S.
LUMA_SHIFT_EV = 0.5
LUMA_HOLD_S = 60.0
#: Luma to linear light for that comparison (sRGB-like encoding).
DISPLAY_GAMMA = 2.2
#: Connected this long without a camera_state: an app without D-589 ("unsupported").
UNSUPPORTED_S = 15.0
#: The phone keeps a request fresh for protocol.CAMERA_FRESH_S (60 s) only, then unlocks and
#: falls back to its local loop: the current setting is sent again this often, echoed or not.
RESEND_S = 20.0
HISTORY_MAX = 64
#: Exposure cap asked for. With AE on the phone caps exposure through the AE fps floor and never
#: picks above 30 fps, so 1/30 s is the shortest real cap; applied.max_exposure_us says what it got.
MAX_EXPOSURE_US = 33333
ANTIBANDING = "60hz"

STATES = ("off", "waiting", "tuning", "locked", "paused", "unsupported")


@dataclass(frozen=True)
class Measurement:
    paint_contrast: float | None
    clip: float
    crush: float
    marker_rate: float | None = None
    lane_source: str = "paint"
    luma: float = 0.0  # median track luma (8-bit), for the light-change guard  # "paint" (site mesh) or "bright" (brightest share of the track)


def score(m: Measurement) -> float:
    """The one recognition score in [0, 1] (D-589 1). Higher is better."""
    contrast = max(0.0, m.paint_contrast or 0.0)
    value = contrast / (contrast + CONTRAST_HALF)
    if m.marker_rate is not None:
        value = (1.0 - MARKER_WEIGHT) * value + MARKER_WEIGHT * min(1.0, max(0.0, m.marker_rate))
    excess = max(0.0, m.clip - CLIP_CRUSH_SOFT) + max(0.0, m.crush - CLIP_CRUSH_SOFT)
    if excess > 0.0:
        value *= max(0.0, 0.5 - 5.0 * excess)
    return min(1.0, max(0.0, value))


def _robust(values: np.ndarray) -> tuple[float, float]:
    median = float(np.median(values))
    return median, 1.4826 * float(np.median(np.abs(values - median)))


class Scorer:
    """Measures frames for one source; caches the track and paint masks per calibration."""

    def __init__(self, paint=None) -> None:
        self.paint = paint  # rosy_vision.map_register.MapPaint or None
        self._key: tuple | None = None
        self._masks: tuple[np.ndarray, np.ndarray | None, np.ndarray | None] | None = None

    def measure(self, image: np.ndarray, calib: Calibration,
                marker_rate: float | None = None) -> Measurement | None:
        """None when the track is not in this frame."""
        gray = cv2.cvtColor(_work_image(image), cv2.COLOR_BGR2GRAY)
        track, paint, carpet = self._masks_for(calib, gray.shape)
        inside = gray[track]
        if inside.size < MIN_CARPET_PX:
            return None
        clip = float(np.count_nonzero(inside >= CLIP_LEVEL)) / inside.size
        crush = float(np.count_nonzero(inside <= CRUSH_LEVEL)) / inside.size
        values = inside.astype(np.float32)
        if paint is not None and np.count_nonzero(paint) >= MIN_PAINT_PX and np.count_nonzero(carpet) >= MIN_CARPET_PX:
            band = gray[paint]
            lane = float(np.median(band[band >= np.median(band)]))
            carpet_median, noise = _robust(gray[carpet].astype(np.float32))
            source = "paint"
        else:
            cut = np.quantile(values, 1.0 - BRIGHT_SHARE)
            lane = float(np.median(values[values >= cut]))
            carpet_median, noise = _robust(values)
            source = "bright"
        contrast = (lane - carpet_median) / max(noise, 1.0)
        return Measurement(float(contrast), clip, crush, marker_rate, source, float(np.median(inside)))

    def _masks_for(self, calib: Calibration, shape: tuple[int, int]):
        key = (calib.image_to_map, calib.image_size, calib.track_bounds_m, shape, id(self.paint))
        if key != self._key:
            height, width = shape
            work_to_map = geometry.as_matrix(calib.image_to_map) @ geometry.centre_scale(
                calib.image_size[0] / width, calib.image_size[1] / height)
            vs, us = np.mgrid[0:height, 0:width]
            floor = geometry.apply(work_to_map, np.c_[us.ravel(), vs.ravel()])
            min_x, min_y, max_x, max_y = calib.track_bounds_m
            with np.errstate(invalid="ignore"):
                track = ((floor[:, 0] >= min_x) & (floor[:, 0] <= max_x)
                         & (floor[:, 1] >= min_y) & (floor[:, 1] <= max_y)).reshape(height, width)
            paint = carpet = None
            if self.paint is not None:
                raster_to_map = np.linalg.inv(np.vstack([self.paint.raster_matrix, [0.0, 0.0, 1.0]]))
                raster_to_work = np.linalg.inv(work_to_map) @ raster_to_map
                warped = cv2.warpPerspective(self.paint.raster, raster_to_work, (width, height),
                                             flags=cv2.INTER_NEAREST)
                size = 2 * PAINT_BAND_PX + 1
                paint = (cv2.dilate(warped, np.ones((size, size), np.uint8)) > 0) & track
                size = 2 * CARPET_GAP_PX + 1
                carpet = track & ~(cv2.dilate(warped, np.ones((size, size), np.uint8)) > 0)
            self._masks = (track, paint, carpet)
            self._key = key
        return self._masks


class MarkerPresence:
    """marker_rate: of the robot markers seen in the last MARKER_PRESENT_S, the share in this frame."""

    def __init__(self, present_s: float = MARKER_PRESENT_S) -> None:
        self.present_s = present_s
        self._last: dict[int, float] = {}

    def rate(self, now: float, seen: set[int]) -> float | None:
        for marker_id in seen:
            self._last[marker_id] = now
        self._last = {k: at for k, at in self._last.items() if now - at <= self.present_s}
        if not self._last:
            return None
        return len(seen & set(self._last)) / len(self._last)


def _work_image(image: np.ndarray) -> np.ndarray:
    height, width = image.shape[:2]
    long_side = max(width, height)
    if long_side <= WORK_LONG_SIDE:
        return image
    factor = WORK_LONG_SIDE / long_side
    size = (max(1, round(width * factor)), max(1, round(height * factor)))
    return cv2.resize(image, size, interpolation=cv2.INTER_AREA)


def tuning_setting(index: int) -> CameraSetting:
    """AE and AWB free: the phone's AE converges at this compensation index (tune steps)."""
    return CameraSetting(index, False, False, MAX_EXPOSURE_US, ANTIBANDING)


def locked_setting(index: int) -> CameraSetting:
    return CameraSetting(index, True, True, MAX_EXPOSURE_US, ANTIBANDING)


def ev_levels(state: CameraState) -> list[int]:
    """Distinct compensation indices for the EV_THIRDS levels on this device, low to high."""
    if state.ev_step <= 0:
        return [min(state.ev_max, max(state.ev_min, 0))]
    return sorted({min(state.ev_max, max(state.ev_min, round(third / 3.0 / state.ev_step)))
                   for third in EV_THIRDS})


def luma_ev(luma: float) -> float:
    """A gamma-encoded 8-bit luma as linear light in EV (log2), for comparing scene brightness."""
    return math.log2(max(luma, 1.0) / 255.0) * DISPLAY_GAMMA


class TuningLog:
    """Per source records (setting, clip, crush, luma, score, time) in one small JSON file."""

    def __init__(self, path: Path | None) -> None:
        self.path = None if path is None else Path(path)

    def load(self) -> list[dict]:
        if self.path is None:
            return []
        try:
            records = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if not isinstance(records, list):
            return []
        return [r for r in records if isinstance(r, dict) and _record_ev(r) is not None][-HISTORY_MAX:]

    def save(self, records: list[dict]) -> None:
        if self.path is None:
            return
        temporary = self.path.with_name(self.path.name + ".new")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(records[-HISTORY_MAX:]), encoding="utf-8")
            os.replace(temporary, self.path)
        except OSError as exc:  # tuning goes on; the next start begins at EV 0
            logger.warning("tuning record not kept path=%s error=%s", self.path, type(exc).__name__)


def _record_ev(record: dict) -> float | None:
    ev = record.get("ev")
    if isinstance(ev, bool) or not isinstance(ev, (int, float)) or not math.isfinite(ev):
        return None
    return float(ev)


class Tuner:
    """Guarded expose-and-lock for one source (D-589 4). Not thread safe; one caller.

    Call ``update`` once per frame with the link, the phone's last ``camera_state`` and the
    frame's measurement (or None); it returns a ``camera`` message to send, or None.
    ``active`` is true while a tune runs (tracking publishes LEARNING and ignores the steps);
    ``take_relearn`` is true once when the lock is confirmed and settled (learn the background
    again, once). ``now`` is a monotonic clock; records carry ``wall`` time. Nothing is sent
    before the phone's first ``camera_state`` on a link: its ``supported.ev_step`` turns EV
    into the index.
    """

    def __init__(self, *, log: TuningLog | None = None, wall: Callable[[], float] = time.time,
                 seq: int | None = None) -> None:
        self.log = log or TuningLog(None)
        self.wall = wall
        self.history: list[dict] = self.log.load()
        self._phase = "waiting"      # waiting, tuning, settle, locked, paused
        self._want: CameraSetting | None = None
        # Random start: a restarted Vision never reuses a seq the phone may still echo.
        self._seq = random.randrange(1, 0x100000000) if seq is None else seq
        self._sent_at: float | None = None
        self._link = None
        self._link_at: float | None = None
        self._state: CameraState | None = None
        self._echo_at: float | None = None   # when the phone echoed the current request
        self._dwell: list[tuple[float, float, float, float]] = []  # (clip, crush, luma, score)
        self._recent: list[tuple[float, float, float, float]] = []  # (t, clip, crush, luma), last DWELL_S
        self._levels: list[int] = [0]
        self._position = 0
        self._visited: set[int] = set()
        self._steps = 0
        self._locked: CameraSetting | None = None
        self._baseline: tuple[float, float, float] | None = None  # (worst of clip/crush, luma EV, score)
        self._relearn = False
        self._relearn_sent = False
        self._shift_since: float | None = None
        self._tuned_at: float | None = None
        self._backoff = BACKOFF_START_S
        self.last_score: float | None = None

    # -- status -------------------------------------------------------------

    @property
    def active(self) -> bool:
        """A tune is running: its intermediate settings are not backgrounds to learn."""
        return self._phase == "tuning" or (self._phase == "settle" and not self._relearn_sent)

    def take_relearn(self) -> bool:
        """True once after a lock is confirmed and settled."""
        relearn, self._relearn = self._relearn, False
        return relearn

    def status(self, now: float | None = None) -> dict:
        state = self._state
        if state is not None and state.mode == "disabled":
            name = "off"
        elif (state is None and self._link is not None and self._link_at is not None and now is not None
              and now - self._link_at >= UNSUPPORTED_S):
            name = "unsupported"  # connected, frames arrive, never a camera_state: an older app
        else:
            name = {"waiting": "waiting", "tuning": "tuning", "settle": "tuning",
                    "locked": "locked", "paused": "paused"}[self._phase]
        ev = None if state is None or state.ev_step <= 0 else round(state.applied.ev * state.ev_step, 2)
        return {"state": name,
                "score": None if self.last_score is None else round(self.last_score, 3),
                "ev": ev,
                "locked": bool(state is not None and state.applied.ae_lock)}

    # -- driving ------------------------------------------------------------

    def update(self, now: float, *, link=None, state: CameraState | None = None,
               sample: Measurement | None = None) -> dict | None:
        if link != self._link:  # a new connection: send at once once the phone has reported
            self._link = link
            self._link_at = now
            self._sent_at = None
            self._echo_at = None
        self._state = state
        if sample is not None:
            self.last_score = score(sample)
            self._recent = [r for r in self._recent if now - r[0] < DWELL_S] + [
                (now, sample.clip, sample.crush, sample.luma)]
        if state is None:
            return None
        if state.mode == "disabled":  # the phone's own switch wins (over thermal hold too)
            if self._phase != "waiting":
                self._phase = "waiting"  # switched on again: tune (or adopt) afresh
            return None
        if state.thermal >= protocol.THERMAL_SEVERE or state.mode == "thermal_hold":
            if self._phase != "paused":
                logger.info("camera tuning paused thermal=%d mode=%s", state.thermal, state.mode)
                self._phase = "paused"  # the phone keeps what it has; keep it fresh
            return self._send(now)
        if self._phase == "paused":
            self._phase = "waiting"  # cooled down: tune again
        if self._phase == "waiting":
            if sample is None:
                return None
            if not self._adopt(now):
                self._start(now)
        if self._echoed():
            if self._echo_at is None:
                self._echo_at = now
                self._dwell = []
            if sample is not None and now - self._echo_at >= SETTLE_S:
                self._dwell.append((sample.clip, sample.crush, sample.luma, score(sample)))
            if self._phase == "tuning" and now - self._echo_at >= DWELL_S and self._dwell:
                self._step(now)
            elif self._phase == "settle":
                self._settle(now)
            elif self._phase == "locked":
                self._watch(now, sample)
        return self._send(now)

    def _echoed(self) -> bool:
        state = self._state
        return (state is not None and self._want is not None and state.seq == self._seq
                and state.mode == "vision")

    def _request(self, setting: CameraSetting) -> None:
        if setting != self._want:
            self._want = setting
            self._seq = self._seq % 0xFFFFFFFF + 1  # 0 is the phone's "none seen"
            self._sent_at = None
            self._echo_at = None

    def _send(self, now: float) -> dict | None:
        if self._want is None or (self._sent_at is not None and now - self._sent_at < RESEND_S):
            return None
        self._sent_at = now
        return protocol.make_camera(self._seq, self._want)

    def _real(self, index: int) -> float:
        return round(index * self._state.ev_step, 3) if self._state.ev_step > 0 else 0.0

    def _last_locked(self) -> float:
        for record in reversed(self.history):
            if record.get("kind") == "lock" and _record_ev(record) is not None:
                return _record_ev(record)
        return 0.0

    def _nearest(self, target: float) -> int:
        return min(range(len(self._levels)), key=lambda i: abs(self._real(self._levels[i]) - target))

    def _adopt(self, now: float) -> bool:
        """Startup: the phone is already locked at the last locked setting: keep it, no tune."""
        state = self._state
        self._levels = ev_levels(state)
        if not any(r.get("kind") == "lock" for r in self.history):
            return False
        index = self._levels[self._nearest(self._last_locked())]
        if not (state.mode == "vision" and state.applied.ae_lock and state.applied.ev == index):
            return False
        logger.info("camera tuning adopts the phone's lock ev=%.2f", self._real(index))
        self._request(locked_setting(index))
        self._locked = self._want
        self._phase = "settle"
        self._relearn_sent = True  # nothing changed: no relearn, only a fresh baseline
        self._tuned_at = now
        return True

    def _start(self, now: float) -> None:
        self._tuned_at = now
        self._levels = ev_levels(self._state)
        self._position = self._nearest(self._last_locked())
        self._visited = {self._position}
        self._steps = 0
        self._shift_since = None
        self._phase = "tuning"
        logger.info("camera tuning start ev=%.2f", self._real(self._levels[self._position]))
        self._request(tuning_setting(self._levels[self._position]))

    def _medians(self) -> tuple[float, float, float, float]:
        return tuple(statistics.median(d[i] for d in self._dwell) for i in range(4))

    def _record(self, kind: str, setting: CameraSetting, values) -> None:
        clip, crush, luma, value = values
        self.history.append({"kind": kind, "setting": setting.as_dict(), "ev": self._real(setting.ev),
                             "clip": round(clip, 4), "crush": round(crush, 4), "luma": round(luma, 1),
                             "score": round(value, 4), "at": round(self.wall(), 3)})
        self.history = self.history[-HISTORY_MAX:]
        if kind == "lock":
            self.log.save(self.history)

    def _step(self, now: float) -> None:
        """One dwell of a tune: step 1/3 EV away from clip or crush, else lock here."""
        values = self._medians()
        clip, crush = values[0], values[1]
        self._record("measure", self._want, values)
        move = -1 if clip > CLIP_TUNE else (1 if crush > CRUSH_TUNE else 0)
        target = self._position + move
        if (move and self._steps < MAX_STEPS and 0 <= target < len(self._levels)
                and target not in self._visited):
            self._position = target
            self._visited.add(target)
            self._steps += 1
            self._request(tuning_setting(self._levels[target]))
            return
        self._phase = "settle"
        self._relearn_sent = False
        self._request(locked_setting(self._levels[self._position]))

    def _settle(self, now: float) -> None:
        """Lock echoed: after SETTLE_S relearn once, then one dwell gives the baseline."""
        if not self._state.applied.ae_lock and self._state.ae_lock_supported:
            return  # the phone has not locked yet
        if not self._relearn_sent and now - self._echo_at >= SETTLE_S:
            self._relearn = self._relearn_sent = True
        if now - self._echo_at >= DWELL_S and self._dwell:
            values = self._medians()
            self._baseline = (max(values[0], values[1]), luma_ev(values[2]), values[3])
            if self._baseline[0] <= RETUNE_HARD:
                self._backoff = BACKOFF_START_S
            self._locked = self._want
            self._phase = "locked"
            self._shift_since = None
            self._record("lock", self._want, values)
            logger.info("camera tuning locked ev=%.2f index=%d clip=%.3f crush=%.3f",
                        self._real(self._want.ev), self._want.ev, values[0], values[1])

    def _watch(self, now: float, sample: Measurement | None) -> None:
        """Locked: tune again on clip/crush (with hysteresis and backoff) or a light change."""
        if sample is None or not self._recent or self._baseline is None:
            return
        if now - self._recent[0][0] < DWELL_S - SETTLE_S:
            return  # judge a full window, never one frame (a hand, a sleeve)
        worst = max(statistics.median(r[1] for r in self._recent),
                    statistics.median(r[2] for r in self._recent))
        base_worst, base_ev, _ = self._baseline
        limit = RETUNE_HARD if base_worst <= RETUNE_HARD else base_worst + RETUNE_HYSTERESIS
        if worst > limit and now - self._tuned_at >= self._backoff:
            logger.info("camera tuning again worst=%.3f limit=%.3f backoff_s=%.0f", worst, limit, self._backoff)
            self._backoff *= 2
            self._start(now)
            return
        shift = abs(luma_ev(statistics.median(r[3] for r in self._recent)) - base_ev)
        if shift > LUMA_SHIFT_EV:
            if self._shift_since is None:
                self._shift_since = now
            if now - self._shift_since >= LUMA_HOLD_S:
                logger.info("camera tuning again light shift_ev=%.2f", shift)
                self._start(now)
        else:
            self._shift_since = None
