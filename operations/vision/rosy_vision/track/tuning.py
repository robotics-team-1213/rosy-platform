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

``score`` is the only formula. Bounded hill climb (D-589 4): ``Tuner`` is a pure state
machine driven with the caller's clock, the phone's last ``camera_state`` and the score
samples. It climbs in real EV (-2.0..+1.0, 1/3 EV levels, sent as the device's compensation
index), sends one setting at a time, waits for the phone to echo its seq in mode "vision", then
scores DWELL_S seconds (the first SETTLE_S are AE settling and not scored), and locks AE and AWB
at the best level. Display only (D-457 6): a camera setting never reaches a robot command.
"""

from __future__ import annotations

import json
import logging
import math
import os
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
#: The climb works in real EV: -2.0 .. +1.0 in 1/3 EV levels (thirds -6 .. +3). Each level is
#: sent as the nearest compensation index (``ev`` = level / supported.ev_step); on an S21-class
#: phone one index is 0.1 EV, so index -6..+3 alone would only be -0.6..+0.3 EV.
EV_THIRDS = range(-6, 4)
#: A candidate level must beat the best so far by this much to win (keeps a tie where it is).
MIN_GAIN = 0.01
DROP_FRACTION = 0.25
DROP_HOLD_S = 60.0
PROBE_INTERVAL_S = 30 * 60.0
RETUNE_MIN_S = 5 * 60.0
#: The phone keeps a request fresh for protocol.CAMERA_FRESH_S (60 s) only, then unlocks and
#: falls back to its local loop: the current setting is sent again this often, echoed or not.
RESEND_S = 20.0
HISTORY_MAX = 64
#: Exposure cap asked for. With AE on the phone caps exposure through the AE fps floor and never
#: picks above 30 fps, so 1/30 s is the shortest real cap; applied.max_exposure_us says what it got.
MAX_EXPOSURE_US = 33333
ANTIBANDING = "60hz"

STATES = ("off", "waiting", "tuning", "locked", "paused")


@dataclass(frozen=True)
class Measurement:
    paint_contrast: float | None
    clip: float
    crush: float
    marker_rate: float | None = None
    lane_source: str = "paint"  # "paint" (site mesh) or "bright" (brightest share of the track)


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
        return Measurement(float(contrast), clip, crush, marker_rate, source)

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
    """AE and AWB free: the phone's AE converges at this compensation index (climb steps)."""
    return CameraSetting(index, False, False, MAX_EXPOSURE_US, ANTIBANDING)


def locked_setting(index: int) -> CameraSetting:
    return CameraSetting(index, True, True, MAX_EXPOSURE_US, ANTIBANDING)


def ev_levels(state: CameraState) -> list[int]:
    """Distinct compensation indices for the EV_THIRDS levels on this device, low to high."""
    if state.ev_step <= 0:
        return [min(state.ev_max, max(state.ev_min, 0))]
    return sorted({min(state.ev_max, max(state.ev_min, round(third / 3.0 / state.ev_step)))
                   for third in EV_THIRDS})


class TuningLog:
    """Per source (setting, real EV, score, time) records in one small JSON file (atomic replace)."""

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
    """Bounded hill climb over EV for one source (D-589 4). Not thread safe; one caller.

    Call ``update`` once per frame with the phone's last ``camera_state`` and the frame's
    measurement (or None); it returns a ``camera`` message to send, or None. ``now`` is a
    monotonic clock; records carry ``wall`` time. Nothing is sent before the phone's first
    ``camera_state`` on a link: its ``supported.ev_step`` turns EV into the index.
    """

    def __init__(self, *, log: TuningLog | None = None, wall: Callable[[], float] = time.time) -> None:
        self.log = log or TuningLog(None)
        self.wall = wall
        self.history: list[dict] = self.log.load()
        self._phase = "waiting"     # waiting, climb, settle, lock, locked, paused
        self._want: CameraSetting | None = None
        self._seq = 0
        self._sent_at: float | None = None
        self._link = None
        self._state: CameraState | None = None
        self._dwell_at: float | None = None  # when the phone echoed the current request
        self._dwell: list[tuple[float, float, float]] = []      # (score, clip, crush) this dwell
        self._recent: list[tuple[float, float, float, float]] = []  # (t, score, clip, crush), last DWELL_S
        self._levels: list[int] = [0]
        self._results: dict[int, float | None] = {}  # level position -> dwell score (None: unreachable)
        self._dir = 1
        self._origin = 0
        self._probe = False
        self._locked: CameraSetting | None = None
        self._baseline: float | None = None
        self._baseline_hard = False
        self._low_since: float | None = None
        self._tuned_at: float | None = None
        self._probed_at: float | None = None
        self.last_score: float | None = None

    # -- status -------------------------------------------------------------

    def status(self) -> dict:
        state = self._state
        if state is not None and state.mode == "disabled":
            name = "off"
        else:
            name = {"waiting": "waiting", "climb": "tuning", "settle": "tuning", "lock": "locked",
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
            self._sent_at = None
            self._dwell_at = None
        self._state = state
        if sample is not None:
            value = score(sample)
            self._recent = [r for r in self._recent if now - r[0] < DWELL_S] + [
                (now, value, sample.clip, sample.crush)]
            self.last_score = statistics.median(r[1] for r in self._recent)
        if state is None or state.mode == "disabled":
            return None  # nothing known yet on this link, or the phone's own switch is off
        if state.thermal >= protocol.THERMAL_SEVERE or state.mode == "thermal_hold":
            if self._phase != "paused":
                logger.info("camera tuning paused thermal=%d mode=%s", state.thermal, state.mode)
                self._phase = "paused"
                if self._locked is not None:
                    self._request(self._locked)
            return self._send(now)
        if self._phase == "paused":
            if self._locked is not None:
                self._enter_lock(self._locked)
            else:
                self._phase = "waiting"
        if self._phase == "waiting":
            if sample is None:
                return None
            self._start(now, probe=False)
        if self._echoed():
            if self._dwell_at is None:
                self._dwell_at = now
                self._dwell = []
            if sample is not None and now - self._dwell_at >= SETTLE_S:
                self._dwell.append((score(sample), sample.clip, sample.crush))
            if self._phase == "locked":
                self._watch(now, sample)
            elif now - self._dwell_at >= DWELL_S and self._dwell:
                self._finish_dwell(now)
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
            self._dwell_at = None

    def _send(self, now: float) -> dict | None:
        if self._want is None or (self._sent_at is not None and now - self._sent_at < RESEND_S):
            return None
        self._sent_at = now
        return protocol.make_camera(self._seq, self._want)

    def _real(self, index: int) -> float:
        return round(index * self._state.ev_step, 3) if self._state.ev_step > 0 else 0.0

    def _start(self, now: float, *, probe: bool) -> None:
        self._tuned_at = now
        self._probe = probe
        self._levels = ev_levels(self._state)
        target = self._real(self._locked.ev) if probe and self._locked is not None else self._last_best()
        self._origin = min(range(len(self._levels)),
                           key=lambda i: abs(self._real(self._levels[i]) - target))
        self._results = {}
        self._dir = 1
        self._low_since = None
        self._phase = "climb"
        logger.info("camera tuning start ev=%.2f probe=%s", self._real(self._levels[self._origin]), probe)
        self._request(tuning_setting(self._levels[self._origin]))

    def _last_best(self) -> float:
        for record in reversed(self.history):
            if record.get("kind") == "lock" and _record_ev(record) is not None:
                return _record_ev(record)
        return 0.0

    def _record(self, kind: str, setting: CameraSetting, value: float) -> None:
        self.history.append({"kind": kind, "setting": setting.as_dict(), "ev": self._real(setting.ev),
                             "score": round(value, 4), "at": round(self.wall(), 3)})
        self.history = self.history[-HISTORY_MAX:]
        if kind == "lock":
            self.log.save(self.history)

    def _finish_dwell(self, now: float) -> None:
        value = statistics.median(d[0] for d in self._dwell)
        want = self._want
        if self._phase == "climb":
            reached = self._state.applied.ev == want.ev
            self._results[self._levels.index(want.ev)] = value if reached else None  # clamped
            if reached:
                self._record("measure", want, value)
            nxt = self._next_position()
            if nxt is not None:
                self._request(tuning_setting(self._levels[nxt]))
                return
            best = self._best_position()
            index = self._state.applied.ev if best is None else self._levels[best]
            if index == want.ev:
                self._enter_lock(locked_setting(index))
            else:
                self._phase = "settle"
                self._request(tuning_setting(index))
        elif self._phase == "settle":
            self._enter_lock(locked_setting(want.ev))
        elif self._phase == "lock":
            self._baseline = value
            self._baseline_hard = (statistics.median(d[1] for d in self._dwell) > CLIP_CRUSH_HARD
                                   or statistics.median(d[2] for d in self._dwell) > CLIP_CRUSH_HARD)
            self._locked = want
            self._phase = "locked"
            self._low_since = None
            self._probed_at = now
            self._record("lock", want, value)
            logger.info("camera tuning locked ev=%.2f index=%d score=%.3f",
                        self._real(want.ev), want.ev, value)

    def _enter_lock(self, setting: CameraSetting) -> None:
        self._phase = "lock"
        self._request(setting)
        self._dwell_at = None  # a fresh baseline dwell, also when the setting stays the same

    def _best_position(self) -> int | None:
        best, best_value = None, -math.inf
        for position, value in self._results.items():  # insertion order: the origin first
            if value is not None and (best is None or value > best_value + MIN_GAIN):
                best, best_value = position, value
        return best

    def _next_position(self) -> int | None:
        best = self._best_position()
        base = self._origin if best is None else best
        for direction in (self._dir, -self._dir):
            candidate = base + direction
            if candidate in self._results or not 0 <= candidate < len(self._levels):
                continue
            if self._probe and abs(candidate - self._origin) > 1:
                continue
            self._dir = direction
            return candidate
        return None

    def _watch(self, now: float, sample: Measurement | None) -> None:
        """Locked: tune again on a sustained drop, on clip/crush, and probe every 30 min."""
        if sample is None or not self._recent:
            return
        clip = statistics.median(r[2] for r in self._recent)
        crush = statistics.median(r[3] for r in self._recent)
        since = math.inf if self._tuned_at is None else now - self._tuned_at
        window_full = now - self._recent[0][0] >= DWELL_S - SETTLE_S
        if (window_full and max(clip, crush) > CLIP_CRUSH_HARD
                and (not self._baseline_hard or since >= RETUNE_MIN_S)):
            logger.info("camera tuning again clip=%.3f crush=%.3f", clip, crush)
            self._start(now, probe=False)
            return
        if self._baseline is not None and self.last_score < (1.0 - DROP_FRACTION) * self._baseline:
            if self._low_since is None:
                self._low_since = now
            if now - self._low_since >= DROP_HOLD_S and since >= RETUNE_MIN_S:
                logger.info("camera tuning again score=%.3f baseline=%.3f", self.last_score, self._baseline)
                self._start(now, probe=False)
                return
        else:
            self._low_since = None
        if self._probed_at is not None and now - self._probed_at >= PROBE_INTERVAL_S and since >= RETUNE_MIN_S:
            self._probed_at = now
            self._start(now, probe=True)
