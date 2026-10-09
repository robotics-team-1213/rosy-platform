"""D-589 S1: recognition score and the bounded hill climb, with a fake clock and a fake phone."""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from rosy_vision import protocol
from rosy_vision.map_register import MapPaint
from rosy_vision.protocol import CameraSetting, CameraState
from rosy_vision.track import tuning
from rosy_vision.track.model import Calibration
from rosy_vision.track.tuning import Measurement, Scorer, Tuner, TuningLog, score

STEP_S = 1.0 / 3.0  # 3 fps


def _measure(value: float, clip: float = 0.0, crush: float = 0.0) -> Measurement:
    """A measurement whose score is ``value`` (no clip/crush penalty)."""
    contrast = tuning.CONTRAST_HALF * value / (1.0 - value)
    return Measurement(contrast, clip, crush)


# -- score ---------------------------------------------------------------------------------


def test_score_rises_with_contrast_and_stays_in_unit_range():
    values = [score(Measurement(c, 0.0, 0.0)) for c in (0.0, 1.0, 1.5, 4.0, 20.0, 1e9)]
    assert values == sorted(values)
    assert values[0] == 0.0 and values[2] == pytest.approx(0.5) and values[-1] <= 1.0


def test_score_cuts_hard_above_the_clip_or_crush_limit():
    good = score(Measurement(4.5, 0.05, 0.0))
    assert score(Measurement(4.5, 0.06, 0.0)) < 0.5 * good
    assert score(Measurement(4.5, 0.0, 0.06)) < 0.5 * good
    assert score(Measurement(4.5, 0.2, 0.0)) == 0.0


def test_marker_rate_counts_only_when_present():
    without = score(Measurement(4.5, 0.0, 0.0))
    assert score(Measurement(4.5, 0.0, 0.0, marker_rate=1.0)) > without
    assert score(Measurement(4.5, 0.0, 0.0, marker_rate=0.0)) < without


def test_marker_presence_rate_and_absence():
    presence = tuning.MarkerPresence(present_s=10.0)
    assert presence.rate(0.0, set()) is None
    assert presence.rate(1.0, {41, 42}) == 1.0
    assert presence.rate(2.0, {41}) == 0.5
    assert presence.rate(20.0, set()) is None  # both left the window: no markers here


def _synthetic(carpet: int, paint_level: int, noise: float, seed: int = 0):
    """A 640x360 frame: noisy carpet with one vertical paint stripe at x 300..319, map = pixels/100."""
    rng = np.random.default_rng(seed)
    image = np.clip(rng.normal(carpet, noise, (360, 640)), 0, 255)
    image[:, 300:320] = paint_level
    image = image.astype(np.uint8)
    calib = Calibration("cam", "map", "rev", (0.01, 0, 0, 0, 0.01, 0, 0, 0, 1), (640, 360),
                        (0.2, 0.2, 6.2, 3.4))
    return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR), calib


def _stripe_paint() -> MapPaint:
    x0, x1, y0, y1 = 3.0, 3.2, 0.0, 3.6  # metres: pixels 300..320
    triangles = np.array([[[x0, y0], [x1, y0], [x1, y1]], [[x0, y0], [x1, y1], [x0, y1]]], float)
    return MapPaint.from_triangles(triangles)


@pytest.mark.parametrize("paint", [None, "stripe"])
def test_scorer_contrast_follows_paint_over_carpet_noise(paint):
    scorer = Scorer(_stripe_paint() if paint else None)
    image, calib = _synthetic(120, 220, 10.0)
    m = scorer.measure(image, calib)
    assert m.lane_source == ("paint" if paint else "bright")
    assert m.paint_contrast == pytest.approx(10.0, rel=0.2)  # (220 - 120) / 10
    noisy = scorer.measure(*_synthetic(120, 220, 25.0))
    assert noisy.paint_contrast < m.paint_contrast


def test_scorer_counts_clip_and_crush_inside_the_track_only():
    image, calib = _synthetic(120, 250, 1.0)
    image[:10, :] = 0  # outside the track rectangle (y < 0.2 m): not counted
    m = Scorer(None).measure(image, calib)
    assert m.crush == 0.0
    assert m.clip == pytest.approx(20 * 320 / (600 * 320), rel=0.05)


# -- tuner ---------------------------------------------------------------------------------

STEP_EV = 0.1  # S21-class: one compensation index is 0.1 EV
LEVELS = [-20, -17, -13, -10, -7, -3, 0, 3, 7, 10]  # -2.0 .. +1.0 EV in thirds, as indices


class Phone:
    """Applies each camera message at once and echoes its seq (like the S2 app)."""

    def __init__(self, ev_min=-20, ev_max=20, ev_step=STEP_EV, mode="vision"):
        self.applied = CameraSetting(0, False, False, 33333, "60hz")
        self.seq = 0
        self.ev_min, self.ev_max, self.ev_step = ev_min, ev_max, ev_step
        self.mode = mode
        self.thermal = 0
        self.sent: list[tuple[float, dict]] = []

    def receive(self, now, message):
        self.sent.append((now, message))
        seq, setting = protocol.parse_camera(message)
        self.seq = seq
        if self.mode != "vision":
            return
        index = min(self.ev_max, max(self.ev_min, setting.ev))
        self.applied = CameraSetting(index, setting.ae_lock, setting.awb_lock, 33333, setting.antibanding)

    def state(self):
        return CameraState(self.seq, self.applied, self.mode, self.ev_min, self.ev_max, self.ev_step,
                           16000, 200, self.thermal)

    def real_ev(self):
        return round(self.applied.ev * self.ev_step, 3)


def _run(tuner, phone, start, seconds, quality, link=1):
    """Drive at 3 fps; ``quality(real_ev, locked, t) -> Measurement``. Returns the end time."""
    now = start
    while now < start + seconds:
        sample = quality(phone.real_ev(), phone.applied.ae_lock, now)
        message = tuner.update(now, link=link, state=phone.state(), sample=sample)
        if message is not None:
            phone.receive(now, message)
        now += STEP_S
    return now


def _peak(best_ev):
    return lambda ev, locked, now: _measure(max(0.05, 0.8 - 0.3 * abs(ev - best_ev)))


def _requests(phone, start=0):
    """Distinct requests (new seq) as (index, ae_lock), keep-alive resends left out."""
    out, last = [], None
    for _, message in phone.sent[start:]:
        if message["seq"] != last:
            out.append((message["ev"], message["ae_lock"]))
            last = message["seq"]
    return out


def test_ev_levels_are_thirds_of_an_ev_as_device_indices():
    phone = Phone()
    assert tuning.ev_levels(phone.state()) == LEVELS
    assert tuning.ev_levels(Phone(ev_min=-6, ev_max=6, ev_step=1 / 3).state()) == list(range(-6, 4))
    assert tuning.ev_levels(Phone(ev_min=-4, ev_max=4, ev_step=0.5).state()) == [-4, -3, -2, -1, 0, 1, 2]
    assert tuning.ev_levels(Phone(ev_min=0, ev_max=0, ev_step=0.0).state()) == [0]


def test_climb_steps_one_level_dwells_and_locks_at_the_best():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 120.0, _peak(-2 / 3))
    assert _requests(phone) == [(0, False), (3, False), (-3, False), (-7, False), (-10, False),
                                (-7, False), (-7, True)]
    firsts = [t for t, m in phone.sent if m["seq"] != 0]
    seqs = [m["seq"] for _, m in phone.sent]
    changes = [firsts[i] for i in range(len(seqs)) if i == 0 or seqs[i] != seqs[i - 1]]
    assert all(b - a >= tuning.DWELL_S for a, b in zip(changes, changes[1:]))
    sent = phone.sent[-1][1]
    assert sent["awb_lock"] is True and sent["max_exposure_us"] == 33333 and sent["antibanding"] == "60hz"
    status = tuner.status()
    assert status == {"state": "locked", "score": pytest.approx(0.8, abs=0.02), "ev": -0.7, "locked": True}
    assert tuner.history[-1]["kind"] == "lock" and tuner.history[-1]["ev"] == pytest.approx(-0.7)


def test_current_setting_is_resent_well_inside_the_phone_freshness():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 300.0, _peak(0.0))
    times = [t for t, _ in phone.sent]
    assert max(b - a for a, b in zip(times, times[1:])) <= tuning.RESEND_S + STEP_S
    assert tuning.RESEND_S < protocol.CAMERA_FRESH_S / 2


def test_climb_stays_inside_the_device_range_and_minus_2_plus_1_ev():
    tuner, phone = Tuner(), Phone(ev_min=-5, ev_max=20)
    _run(tuner, phone, 0.0, 120.0, _peak(-2.0))
    assert min(index for index, _ in _requests(phone)) == -5
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 200.0, _peak(1.5))
    assert max(index for index, _ in _requests(phone)) == 10  # +1.0 EV


def test_nothing_is_sent_before_the_phone_reports_or_before_a_score():
    tuner, phone = Tuner(), Phone()
    for step in range(30):
        assert tuner.update(step * STEP_S, link=1, state=None, sample=_measure(0.7)) is None
        assert tuner.update(step * STEP_S, link=1, state=phone.state(), sample=None) is None
    assert tuner.status()["state"] == "waiting"


def test_a_new_link_sends_at_once():
    tuner, phone = Tuner(), Phone()
    first = tuner.update(0.0, link=1, state=phone.state(), sample=_measure(0.7))
    assert first is not None and first["type"] == "camera" and first["seq"] >= 1
    assert tuner.update(5.0, link=1, state=phone.state(), sample=_measure(0.7)) is None
    assert tuner.update(5.5, link=2, state=phone.state(), sample=_measure(0.7)) == first


def test_local_mode_is_not_an_echo():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 2.0, _peak(0.0))
    phone.mode = "local"  # the phone fell back: requests are not applied, no dwell is scored
    _run(tuner, phone, 2.0, 60.0, _peak(-2.0))
    assert _requests(phone) == [(0, False)]


def test_starts_from_the_best_last_setting(tmp_path):
    path = tmp_path / "cam.tuning.json"
    tuner, phone = Tuner(log=TuningLog(path)), Phone()
    _run(tuner, phone, 0.0, 120.0, _peak(-2 / 3))
    records = json.loads(path.read_text(encoding="utf-8"))
    assert records[-1]["kind"] == "lock" and records[-1]["ev"] == pytest.approx(-0.7)
    assert {"setting", "score", "at"} <= set(records[-1])
    # Another device (1/3 EV per index) starts at the nearest level to -0.7 EV.
    again, phone = Tuner(log=TuningLog(path)), Phone(ev_min=-6, ev_max=6, ev_step=1 / 3)
    _run(again, phone, 0.0, 2.0, _peak(0.0))
    assert phone.sent[0][1]["ev"] == -2


def test_unreadable_record_file_starts_at_zero(tmp_path):
    path = tmp_path / "cam.tuning.json"
    path.write_text("{not json", encoding="utf-8")
    tuner, phone = Tuner(log=TuningLog(path)), Phone()
    _run(tuner, phone, 0.0, 1.0, _peak(0.0))
    assert phone.sent[0][1]["ev"] == 0


def _locked(best=-1 / 3):
    tuner, phone = Tuner(), Phone()
    end = _run(tuner, phone, 0.0, 120.0, _peak(best))
    assert tuner.status()["state"] == "locked"
    return tuner, phone, end, len(_requests(phone))


def test_sustained_drop_tunes_again_only_after_hold_and_minimum_interval():
    tuner, phone, end, count = _locked()
    dropped = lambda ev, locked, now: _measure(0.4)  # more than 25 % below 0.8
    # Tuning started at 0: the 5-minute minimum holds the retune until t = 300 s.
    end = _run(tuner, phone, end, 300.0 - end - 1.0, dropped)
    assert len(_requests(phone)) == count
    _run(tuner, phone, end, 3.0, dropped)
    assert len(_requests(phone)) == count + 1 and phone.sent[-1][1]["ae_lock"] is False


def test_short_drop_does_not_tune_again():
    tuner, phone, end, count = _locked()
    end = _run(tuner, phone, 400.0, 50.0, lambda ev, locked, now: _measure(0.4))
    _run(tuner, phone, end, 120.0, _peak(-1 / 3))
    assert len(_requests(phone)) == count


def test_clip_over_limit_tunes_again_at_once():
    tuner, phone, end, count = _locked()
    _run(tuner, phone, end, 6.0, lambda ev, locked, now: _measure(0.8, clip=0.3))
    assert len(_requests(phone)) == count + 1 and phone.sent[-1][1]["ae_lock"] is False


def test_probe_every_30_minutes_tries_one_level_each_way():
    tuner, phone, end, count = _locked()
    end = _run(tuner, phone, end, tuning.PROBE_INTERVAL_S - 120.0, _peak(-1 / 3))
    assert len(_requests(phone)) == count  # locked at about 40 s: no probe before 30 min after it
    _run(tuner, phone, end, 240.0, _peak(-1 / 3))
    assert _requests(phone, 0)[count:] == [(-3, False), (0, False), (-7, False), (-3, False), (-3, True)]


def test_probe_moves_when_a_neighbour_is_better():
    tuner, phone, end, count = _locked()
    _run(tuner, phone, end, tuning.PROBE_INTERVAL_S + 60.0, _peak(0.0))
    assert _requests(phone)[-1] == (0, True)
    assert {index for index, _ in _requests(phone)[count:]} <= {-7, -3, 0}


@pytest.mark.parametrize("hold", ["thermal", "mode"])
def test_thermal_hold_pauses_and_keeps_the_last_locked_setting(hold):
    tuner, phone, end, count = _locked()
    end = _run(tuner, phone, end, 6.0, lambda ev, locked, now: _measure(0.8, clip=0.3))
    assert phone.sent[-1][1]["ae_lock"] is False  # tuning again
    if hold == "thermal":
        phone.thermal = protocol.THERMAL_SEVERE
    else:
        phone.mode = "thermal_hold"
    end = _run(tuner, phone, end, 60.0, _peak(-1 / 3))
    assert tuner.status()["state"] == "paused"
    assert (phone.sent[-1][1]["ev"], phone.sent[-1][1]["ae_lock"]) == (-3, True)
    count = len(_requests(phone))
    end = _run(tuner, phone, end, 60.0, _peak(-1.0))
    assert len(_requests(phone)) == count  # no new request while paused (keep-alive only)
    phone.thermal, phone.mode = 1, "vision"
    _run(tuner, phone, end, 10.0, _peak(-1 / 3))
    assert tuner.status()["state"] == "locked"


def test_phone_switch_off_means_no_messages_and_state_off():
    tuner, phone = Tuner(), Phone(mode="disabled")
    _run(tuner, phone, 0.0, 30.0, _peak(0.0))
    assert phone.sent == [] and tuner.status()["state"] == "off"
