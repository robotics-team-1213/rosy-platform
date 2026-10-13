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


# -- tuner: guarded expose-and-lock -----------------------------------------------------------

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
        if self.mode != "vision":
            return  # disabled or holding: the phone keeps what it has
        self.seq = seq
        index = min(self.ev_max, max(self.ev_min, setting.ev))
        self.applied = CameraSetting(index, setting.ae_lock, setting.awb_lock, 33333, setting.antibanding)

    def state(self):
        return CameraState(self.seq, self.applied, self.mode, self.ev_min, self.ev_max, self.ev_step,
                           16000, 200, self.thermal)

    def real_ev(self):
        return round(self.applied.ev * self.ev_step, 3)


def _scene(clip_above=None, crush_below=None, luma=120.0):
    """Clip 0.1 at real EV above ``clip_above``, crush 0.1 below ``crush_below``, else clean."""
    def quality(ev, locked, now):
        clip = 0.1 if clip_above is not None and ev > clip_above + 1e-6 else 0.005
        crush = 0.1 if crush_below is not None and ev < crush_below - 1e-6 else 0.005
        return Measurement(4.5, clip, crush, luma=luma)
    return quality


def _run(tuner, phone, start, seconds, quality, link=1, watch=None):
    """Drive at 3 fps. Returns the end time; ``watch(now)`` is called after each update."""
    now = start
    while now < start + seconds:
        sample = quality(phone.real_ev(), phone.applied.ae_lock, now)
        message = tuner.update(now, link=link, state=phone.state(), sample=sample)
        if message is not None:
            phone.receive(now, message)
        if watch is not None:
            watch(now)
        now += STEP_S
    return now


def _requests(phone, start=0):
    """Distinct requests (new seq) as (index, ae_lock), keep-alive resends left out."""
    out, last = [], None
    for _, message in phone.sent[start:]:
        if message["seq"] != last:
            out.append((message["ev"], message["ae_lock"]))
            last = message["seq"]
    return out


def test_ev_levels_are_thirds_of_an_ev_as_device_indices():
    assert tuning.ev_levels(Phone().state()) == LEVELS
    assert tuning.ev_levels(Phone(ev_min=-6, ev_max=6, ev_step=1 / 3).state()) == list(range(-6, 4))
    assert tuning.ev_levels(Phone(ev_min=-4, ev_max=4, ev_step=0.5).state()) == [-4, -3, -2, -1, 0, 1, 2]
    assert tuning.ev_levels(Phone(ev_min=0, ev_max=0, ev_step=0.0).state()) == [0]


def test_a_clean_scene_locks_where_it_starts_and_relearns_once():
    tuner, phone = Tuner(seq=100), Phone()
    seen = []
    _run(tuner, phone, 0.0, 30.0, _scene(), watch=lambda now: seen.append(
        (now, tuner.active, tuner.take_relearn())))
    assert _requests(phone) == [(0, False), (0, True)]
    sent = phone.sent[-1][1]
    assert sent["awb_lock"] is True and sent["max_exposure_us"] == 33333 and sent["antibanding"] == "60hz"
    relearns = [now for now, _, relearn in seen if relearn]
    lock_sent = [t for t, m in phone.sent if m["ae_lock"]][0]
    assert len(relearns) == 1 and relearns[0] >= lock_sent + tuning.SETTLE_S
    assert all(active for now, active, _ in seen if now < relearns[0] and now > 0.5)
    assert not any(active for now, active, _ in seen if now >= relearns[0])
    assert tuner.status() == {"state": "locked", "score": pytest.approx(score(Measurement(4.5, 0.005, 0.005))),
                              "ev": 0.0, "locked": True}
    assert tuner.history[-1]["kind"] == "lock"
    assert {"clip", "crush", "luma", "score", "at", "ev"} <= set(tuner.history[-1])


def test_clipping_steps_down_a_third_per_dwell_then_locks():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 60.0, _scene(clip_above=-0.7))
    assert _requests(phone) == [(0, False), (-3, False), (-7, False), (-7, True)]
    firsts = {}
    for t, m in phone.sent:
        firsts.setdefault(m["seq"], t)
    times = sorted(firsts.values())
    assert all(b - a >= tuning.DWELL_S for a, b in zip(times, times[1:]))


def test_crushing_steps_up_then_locks():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 60.0, _scene(crush_below=0.6))
    assert _requests(phone) == [(0, False), (3, False), (7, False), (7, True)]


def test_a_tune_is_bounded_by_the_range_and_six_steps():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 120.0, _scene(clip_above=-9.0))
    assert _requests(phone) == [(0, False), (-3, False), (-7, False), (-10, False), (-13, False),
                                (-17, False), (-20, False), (-20, True)]
    tuner, phone = Tuner(), Phone(ev_min=-5)
    _run(tuner, phone, 0.0, 120.0, _scene(clip_above=-9.0))
    assert _requests(phone)[-1] == (-5, True)


def test_a_tune_never_steps_back_to_a_level_it_left():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 60.0, _scene(clip_above=-0.1, crush_below=-0.1))  # clips at 0, crushes at -1/3
    assert _requests(phone) == [(0, False), (-3, False), (-3, True)]


def test_current_setting_is_resent_well_inside_the_phone_freshness():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 300.0, _scene())
    times = [t for t, _ in phone.sent]
    assert max(b - a for a, b in zip(times, times[1:])) <= tuning.RESEND_S + STEP_S
    assert tuning.RESEND_S < protocol.CAMERA_FRESH_S / 2


def test_no_probe_while_the_scene_stays():
    tuner, phone = Tuner(), Phone()
    _run(tuner, phone, 0.0, 2 * 3600.0, _scene())
    assert _requests(phone) == [(0, False), (0, True)]


def test_nothing_is_sent_before_the_phone_reports_and_old_apps_show_unsupported():
    tuner, phone = Tuner(), Phone()
    for step in range(30):
        assert tuner.update(step * STEP_S, link=1, state=None, sample=_scene()(0, False, 0)) is None
    assert tuner.status(9.9)["state"] == "waiting"
    assert tuner.status(tuning.UNSUPPORTED_S + 0.1)["state"] == "unsupported"
    assert tuner.update(20.0, link=1, state=phone.state(), sample=None) is None  # no score yet
    assert tuner.status(20.0)["state"] == "waiting"


def test_seq_starts_random_unless_given():
    assert Tuner(seq=7).update(0.0, link=1, state=Phone().state(), sample=_scene()(0, False, 0))["seq"] == 8
    starts = {Tuner()._seq for _ in range(8)}
    assert len(starts) > 1 and all(1 <= seq <= 0xFFFFFFFF for seq in starts)


def test_a_new_link_sends_at_once():
    tuner, phone = Tuner(), Phone()
    first = tuner.update(0.0, link=1, state=phone.state(), sample=_scene()(0, False, 0))
    assert first is not None and first["type"] == "camera"
    assert tuner.update(5.0, link=1, state=phone.state(), sample=_scene()(0, False, 0)) is None
    assert tuner.update(5.5, link=2, state=phone.state(), sample=_scene()(0, False, 0)) == first


def test_starts_from_the_last_locked_ev(tmp_path):
    path = tmp_path / "cam.tuning.json"
    tuner, phone = Tuner(log=TuningLog(path)), Phone()
    _run(tuner, phone, 0.0, 60.0, _scene(clip_above=-0.7))
    records = json.loads(path.read_text(encoding="utf-8"))
    assert records[-1]["kind"] == "lock" and records[-1]["ev"] == pytest.approx(-0.7)
    # Another device (1/3 EV per index), unlocked: tunes from the nearest level to -0.7 EV.
    again, phone = Tuner(log=TuningLog(path)), Phone(ev_min=-6, ev_max=6, ev_step=1 / 3)
    _run(again, phone, 0.0, 2.0, _scene())
    assert _requests(phone) == [(-2, False)]


def test_unreadable_record_file_starts_at_zero(tmp_path):
    path = tmp_path / "cam.tuning.json"
    path.write_text("{not json", encoding="utf-8")
    tuner, phone = Tuner(log=TuningLog(path)), Phone()
    _run(tuner, phone, 0.0, 1.0, _scene())
    assert phone.sent[0][1]["ev"] == 0


def test_a_phone_already_locked_at_the_last_lock_is_adopted_without_a_tune(tmp_path):
    path = tmp_path / "cam.tuning.json"
    _run(Tuner(log=TuningLog(path)), Phone(), 0.0, 60.0, _scene(clip_above=-0.7))
    restarted, phone = Tuner(log=TuningLog(path)), Phone()
    phone.applied, phone.seq = tuning.locked_setting(-7), 12345  # still locked from before
    flags = []
    _run(restarted, phone, 0.0, 30.0, _scene(clip_above=-0.7),
         watch=lambda now: flags.append((restarted.active, restarted.take_relearn())))
    assert _requests(phone) == [(-7, True)]  # the same lock, kept fresh
    assert flags and not any(active or relearn for active, relearn in flags)
    assert restarted.status()["state"] == "locked"


def test_a_phone_locked_elsewhere_is_tuned(tmp_path):
    path = tmp_path / "cam.tuning.json"
    _run(Tuner(log=TuningLog(path)), Phone(), 0.0, 60.0, _scene(clip_above=-0.7))
    restarted, phone = Tuner(log=TuningLog(path)), Phone()
    phone.applied = tuning.locked_setting(0)
    _run(restarted, phone, 0.0, 30.0, _scene(clip_above=-0.7))
    assert _requests(phone)[0] == (-7, False)


def _locked(quality):
    tuner, phone = Tuner(), Phone()
    end = _run(tuner, phone, 0.0, 60.0, quality)
    assert tuner.status()["state"] == "locked"
    return tuner, phone, end, len(_requests(phone))


def _with(clip=0.005, crush=0.005, luma=120.0):
    return lambda ev, locked, now: Measurement(4.5, clip, crush, luma=luma)


def test_clip_past_the_limit_tunes_again_with_a_doubling_backoff():
    tuner, phone, end, count = _locked(_with())
    # The tune started at 0: the first backoff (5 min) holds the retune until t = 300 s.
    end = _run(tuner, phone, end, 300.0 - end - 1.0, _with(clip=0.3))
    assert len(_requests(phone)) == count
    end = _run(tuner, phone, end, 3.0, _with(clip=0.3))
    assert len(_requests(phone)) == count + 1 and phone.sent[-1][1]["ae_lock"] is False
    # Clipping everywhere: it locks again at -2.0 with clip 0.3 (hysteresis limit 0.35) and the
    # next retune waits for the doubled backoff, 10 min after this tune started.
    retuned = end
    end = _run(tuner, phone, end, 200.0, _with(clip=0.3))
    assert _requests(phone)[-1] == (-20, True)
    count = len(_requests(phone))
    end = _run(tuner, phone, end, retuned + 590.0 - end, _with(clip=0.4))
    assert len(_requests(phone)) == count
    _run(tuner, phone, end, 20.0, _with(clip=0.4))
    assert len(_requests(phone)) > count and _requests(phone)[count] == (-20, False)


def test_a_scene_that_already_clipped_at_the_lock_needs_to_get_worse():
    tuner, phone, end, count = _locked(_with(clip=0.2))  # clip everywhere: locks at -2.0
    end = _run(tuner, phone, end, 900.0, _with(clip=0.24))
    assert len(_requests(phone)) == count
    _run(tuner, phone, end, 10.0, _with(clip=0.3))
    assert len(_requests(phone)) > count and _requests(phone)[count] == (-20, False)


def test_a_single_bad_frame_does_not_tune_again():
    tuner, phone, end, count = _locked(_with())
    bad = lambda ev, locked, now: _with(clip=0.5 if int(now * 3) % 9 == 0 else 0.005)(ev, locked, now)
    _run(tuner, phone, 400.0, 120.0, bad)
    assert len(_requests(phone)) == count


@pytest.mark.parametrize("held,retunes", [(50.0, False), (65.0, True)])
def test_a_light_change_of_half_an_ev_held_60_s_tunes_again(held, retunes):
    tuner, phone, end, count = _locked(_with(luma=120.0))
    brighter = 120.0 * 2 ** (0.6 / tuning.DISPLAY_GAMMA)  # +0.6 EV of linear light
    end = _run(tuner, phone, end, held, _with(luma=brighter))
    _run(tuner, phone, end, 10.0, _with(luma=120.0))
    assert (len(_requests(phone)) > count) is retunes


def test_a_small_light_change_does_not_tune_again():
    tuner, phone, end, count = _locked(_with(luma=120.0))
    _run(tuner, phone, end, 300.0, _with(luma=120.0 * 2 ** (0.4 / tuning.DISPLAY_GAMMA)))
    assert len(_requests(phone)) == count


@pytest.mark.parametrize("hold", ["thermal", "mode"])
def test_thermal_hold_pauses_mid_tune_keeps_what_the_phone_has_and_tunes_after_cooling(hold):
    tuner, phone = Tuner(), Phone()
    end = _run(tuner, phone, 0.0, 6.0, _scene(clip_above=-0.7))  # first step sent
    assert _requests(phone) == [(0, False), (-3, False)]
    if hold == "thermal":
        phone.thermal = protocol.THERMAL_SEVERE
    else:
        phone.mode = "thermal_hold"
    end = _run(tuner, phone, end, 120.0, _scene(clip_above=-0.7))
    assert tuner.status()["state"] == "paused" and not tuner.active
    assert _requests(phone) == [(0, False), (-3, False)]  # the same request kept fresh, unlocked
    phone.thermal, phone.mode = 1, "vision"
    _run(tuner, phone, end, 60.0, _scene(clip_above=-0.7))
    assert _requests(phone)[2:] == [(0, False), (-3, False), (-7, False), (-7, True)]


def test_phone_switch_off_wins_over_thermal_and_sends_nothing():
    tuner, phone = Tuner(), Phone(mode="disabled")
    phone.thermal = 4
    _run(tuner, phone, 0.0, 30.0, _scene())
    assert phone.sent == [] and tuner.status()["state"] == "off"


def test_an_echo_without_ae_lock_ends_the_tune_at_the_deadline():
    class NoLock(Phone):
        def receive(self, now, message):
            super().receive(now, message)
            self.applied = CameraSetting(self.applied.ev, False, False, 33333, "60hz")

    tuner, phone = Tuner(), NoLock()
    flags = []
    _run(tuner, phone, 0.0, tuning.TUNE_DEADLINE_S + 20.0, _scene(),
         watch=lambda now: flags.append((now, tuner.active, tuner.take_relearn())))
    assert [now for now, active, _ in flags if active][-1] < tuning.TUNE_DEADLINE_S + 0.5
    assert [now for now, _, relearn in flags if relearn] == pytest.approx(
        [min(now for now, _, _ in flags if now >= tuning.TUNE_DEADLINE_S)])
    assert tuner.status()["state"] == "locked"
    assert _requests(phone) == [(0, False), (0, True)]  # no endless re-asking


def test_a_link_switch_mid_tune_without_camera_state_ends_at_the_deadline():
    tuner, phone = Tuner(), Phone()
    end = _run(tuner, phone, 0.0, 3.0, _scene())
    assert tuner.active
    now = end
    while now < tuning.TUNE_DEADLINE_S + 5.0:  # the new link never reports camera_state
        tuner.update(now, link=2, state=None, sample=_scene()(0, False, now))
        now += STEP_S
    assert not tuner.active and tuner.take_relearn() is True and tuner.take_relearn() is False


def test_a_deadline_lock_takes_its_baseline_from_the_next_full_window():
    class NoLock(Phone):
        def receive(self, now, message):
            super().receive(now, message)
            self.applied = CameraSetting(self.applied.ev, False, False, 33333, "60hz")

    tuner, phone = Tuner(), NoLock()
    end = _run(tuner, phone, 0.0, tuning.TUNE_DEADLINE_S + 10.0, _scene())
    count = len(_requests(phone))
    _run(tuner, phone, end, 400.0, lambda ev, locked, now: Measurement(4.5, 0.3, 0.005, luma=120.0))
    assert len(_requests(phone)) > count  # clip past the limit still tunes again
