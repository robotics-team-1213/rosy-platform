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
samples. It sends one setting at a time, waits for the phone to echo its seq, then scores
DWELL_S seconds (the first SETTLE_S are AE settling and not scored), and locks AE and AWB at
the best EV. Display only (D-457 6): a camera setting never reaches a robot command.
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
#: A candidate EV must beat the best so far by this much to win (keeps a tie where it is).
MIN_GAIN = 0.01
DROP_FRACTION = 0.25
DROP_HOLD_S = 60.0
PROBE_INTERVAL_S = 30 * 60.0
RETUNE_MIN_S = 5 * 60.0
#: Resend a setting the phone has not echoed after this long (also the first send on a new link).
RESEND_S = 10.0
HISTORY_MAX = 64
#: Exposure time cap: 1/120 s, so a moving robot does not smear (D-589 2).
MAX_EXPOSURE_US = 8333
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


def tuning_setting(ev: int) -> CameraSetting:
    """AE and AWB free: the phone's AE converges at this EV (climb steps)."""
    return CameraSetting(ev, False, False, MAX_EXPOSURE_US, ANTIBANDING)


def locked_setting(ev: int) -> CameraSetting:
    return CameraSetting(ev, True, True, MAX_EXPOSURE_US, ANTIBANDING)


class TuningLog:
    """Per source (setting, score, time) records in one small JSON file (atomic replace)."""

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


def _record_ev(record: dict) -> int | None:
    setting = record.get("setting")
    ev = setting.get("ev") if isinstance(setting, dict) else None
    lo, hi = protocol.CAMERA_EV_RANGE
    return ev if type(ev) is int and lo <= ev <= hi else None


class Tuner:
    """Bounded hill climb over EV for one source (D-589 4). Not thread safe; one caller.

    Call ``update`` once per scored frame (``sample``) and whenever there is no sample; it
    returns a ``camera`` message to send, or None. ``now`` is a monotonic clock; records carry
    ``wall`` time.
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
        self._dwell_at: float | None = None  # when the phone echoed the current request
        self._applied: CameraSetting | None = None
        self._dwell: list[tuple[float, float, float]] = []      # (score, clip, crush) this dwell
        self._recent: list[tuple[float, float, float, float]] = []  # (t, score, clip, crush), last DWELL_S
        self._results: dict[int, float | None] = {}
        self._dir = 1
        self._origin = 0
        self._probe = False
        self._ev_range = protocol.CAMERA_EV_RANGE
        self._locked: CameraSetting | None = None
        self._baseline: float | None = None
        self._baseline_hard = False
        self._low_since: float | None = None
        self._tuned_at: float | None = None
        self._probed_at: float | None = None
        self._phone_off = False
        self.last_score: float | None = None

    # -- status -------------------------------------------------------------

    def status(self) -> dict:
        if self._phone_off:
            state = "off"
        else:
            state = {"waiting": "waiting", "climb": "tuning", "settle": "tuning", "lock": "locked",
                     "locked": "locked", "paused": "paused"}[self._phase]
        shown = self._applied or self._want
        return {"state": state,
                "score": None if self.last_score is None else round(self.last_score, 3),
                "ev": None if shown is None else shown.ev,
                "locked": bool(self._applied is not None and self._applied.ae_lock)}

    # -- driving ------------------------------------------------------------

    def update(self, now: float, *, link=None, state: CameraState | None = None,
               sample: Measurement | None = None) -> dict | None:
        if link != self._link:  # a new connection: send at once, wait for its echo
            self._link = link
            self._sent_at = None
            self._dwell_at = None
        self._applied = None if state is None else state.applied
        self._phone_off = state is not None and not state.enabled
        if state is not None and state.ev_range is not None:
            self._ev_range = (max(protocol.CAMERA_EV_RANGE[0], state.ev_range[0]),
                              min(protocol.CAMERA_EV_RANGE[1], state.ev_range[1]))
        if sample is not None:
            value = score(sample)
            self._recent = [r for r in self._recent if now - r[0] < DWELL_S] + [
                (now, value, sample.clip, sample.crush)]
            self.last_score = statistics.median(r[1] for r in self._recent)
        thermal = None if state is None else state.thermal
        if thermal is not None and thermal >= protocol.THERMAL_SEVERE:
            if self._phase != "paused":
                logger.info("camera tuning paused thermal=%d", thermal)
                self._phase = "paused"
                if self._locked is not None:
                    self._request(self._locked)
            return self._send(now, state)
        if self._phase == "paused":
            if self._locked is not None:
                self._enter_lock(self._locked)
            else:
                self._phase = "waiting"
        if self._phone_off:  # the phone's own switch is off: it ignores camera messages
            return None
        if self._phase == "waiting":
            if sample is None:
                return None
            self._start(now, probe=False)
        message = self._send(now, state)
        if message is not None:
            return message
        if not self._echoed(state):
            return None
        if self._dwell_at is None:
            self._dwell_at = now
            self._dwell = []
        if sample is not None and now - self._dwell_at >= SETTLE_S:
            self._dwell.append((score(sample), sample.clip, sample.crush))
        if self._phase == "locked":
            self._watch(now, sample)
        elif now - self._dwell_at >= DWELL_S and self._dwell:
            self._finish_dwell(now)
        return self._send(now, state)

    def _echoed(self, state: CameraState | None) -> bool:
        return state is not None and self._want is not None and state.seq == self._seq

    def _request(self, setting: CameraSetting) -> None:
        if setting != self._want:
            self._want = setting
            self._seq = (self._seq + 1) % 0x100000000
            self._sent_at = None
            self._dwell_at = None

    def _send(self, now: float, state: CameraState | None) -> dict | None:
        if self._want is None or self._echoed(state):
            return None
        if self._sent_at is not None and now - self._sent_at < RESEND_S:
            return None
        self._sent_at = now
        return protocol.make_camera(self._seq, self._want)

    def _start(self, now: float, *, probe: bool) -> None:
        self._tuned_at = now
        self._probe = probe
        if probe and self._locked is not None:
            self._origin = self._locked.ev
        else:
            self._origin = self._last_best()
        lo, hi = self._ev_range
        self._origin = min(hi, max(lo, self._origin))
        self._results = {}
        self._dir = 1
        self._low_since = None
        self._phase = "climb"
        logger.info("camera tuning start ev=%d probe=%s", self._origin, probe)
        self._request(tuning_setting(self._origin))

    def _last_best(self) -> int:
        for record in reversed(self.history):
            if record.get("kind") == "lock" and _record_ev(record) is not None:
                return _record_ev(record)
        return 0

    def _record(self, kind: str, setting: CameraSetting, value: float) -> None:
        self.history.append({"kind": kind, "setting": setting.as_dict(), "score": round(value, 4),
                             "at": round(self.wall(), 3)})
        self.history = self.history[-HISTORY_MAX:]
        if kind == "lock":
            self.log.save(self.history)

    def _finish_dwell(self, now: float) -> None:
        value = statistics.median(d[0] for d in self._dwell)
        want = self._want
        if self._phase == "climb":
            reached = self._applied is not None and self._applied.ev == want.ev
            self._results[want.ev] = value if reached else None  # the phone clamped it: unreachable
            if reached:
                self._record("measure", want, value)
            nxt = self._next_ev()
            if nxt is not None:
                self._request(tuning_setting(nxt))
                return
            best = self._best_ev()
            if best is None:  # nothing reachable: stay where the phone is
                best = self._applied.ev if self._applied is not None else 0
            if best == want.ev:
                self._enter_lock(locked_setting(best))
            else:
                self._phase = "settle"
                self._request(tuning_setting(best))
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
            logger.info("camera tuning locked ev=%d score=%.3f", want.ev, value)

    def _enter_lock(self, setting: CameraSetting) -> None:
        self._phase = "lock"
        self._request(setting)
        self._dwell_at = None  # a fresh baseline dwell, also when the setting stays the same

    def _best_ev(self) -> int | None:
        best, best_value = None, -math.inf
        for ev, value in self._results.items():  # insertion order: the origin first
            if value is not None and (best is None or value > best_value + MIN_GAIN):
                best, best_value = ev, value
        return best

    def _next_ev(self) -> int | None:
        best = self._best_ev()
        base = self._origin if best is None else best
        lo, hi = self._ev_range
        for direction in (self._dir, -self._dir):
            candidate = base + direction
            if candidate in self._results or not lo <= candidate <= hi:
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
