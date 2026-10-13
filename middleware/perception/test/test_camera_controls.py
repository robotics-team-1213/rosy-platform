"""Freezing the sensor is the precondition for every colour-reference method.

Measured before the lock existed: with the floor reference frozen, a 1.3x gain
step on one unchanged real frame flipped blocked False -> True, and a per-channel
white-balance shift drove near-floor 1.00 -> 0.00. So a lock that silently fails
open is worse than no lock -- it hides the drift instead of reporting it.
"""
import pytest

from control.sensing.perception.camera_controls import (
    COLOUR_GAIN_MAX, LOCK_MAX_ATTEMPTS, LOCKED_KEYS, lock_action, lock_controls,
    lock_summary, static_controls)


def settled(**overrides):
    """Metadata shaped like a real capture_metadata() after AE/AWB converged."""
    return dict({'ExposureTime': 19999, 'AnalogueGain': 2.5,
                 'ColourGains': (1.8, 1.6), 'Lux': 120.0}, **overrides)


def test_lock_emits_only_the_three_implicit_disable_controls():
    controls = lock_controls(settled())
    assert set(controls) == set(LOCKED_KEYS)
    assert controls == {'ExposureTime': 19999, 'AnalogueGain': 2.5,
                        'ColourGains': (1.8, 1.6)}


def test_lock_never_emits_the_explicit_enable_flags():
    # Setting ExposureTime+AnalogueGain disables AE and ColourGains disables AWB
    # implicitly. Sending AeEnable/AwbEnable as well has reported sequencing bugs.
    controls = lock_controls(settled())
    assert 'AeEnable' not in controls and 'AwbEnable' not in controls


@pytest.mark.parametrize('missing', LOCKED_KEYS)
def test_missing_metadata_stays_in_auto(missing):
    metadata = settled()
    del metadata[missing]
    assert lock_controls(metadata) is None


@pytest.mark.parametrize('metadata', [
    settled(ExposureTime=0),
    settled(ExposureTime=-1),
    settled(AnalogueGain=0.0),
    settled(AnalogueGain=-2.0),
    settled(AnalogueGain=float('nan')),
    settled(AnalogueGain=float('inf')),
    settled(ColourGains=(0.0, 1.6)),
    settled(ColourGains=(1.8, 0.0)),
    settled(ColourGains=(COLOUR_GAIN_MAX + 0.1, 1.6)),
    settled(ColourGains=(1.8, float('nan'))),
    settled(ColourGains=(1.8,)),
    settled(ColourGains=1.8),
    settled(ExposureTime='19999us'),
    settled(AnalogueGain=True),
    # bools survive float(), so an unguarded True would become a unity gain.
    settled(ExposureTime=True),
    settled(ColourGains=(True, 1.6)),
    settled(ColourGains=(1.8, True)),
    None,
    # int(float('inf')) raises OverflowError, which is neither TypeError nor
    # ValueError: without an explicit finiteness check first, an unreadable
    # exposure escaped as an exception instead of as "stay in auto".
    settled(ExposureTime=float('inf')),
    settled(ExposureTime=float('-inf')),
    settled(ExposureTime=float('nan')),
    # An hour of exposure is a bad metadata read, not a dim room.
    settled(ExposureTime=10 ** 30),
])
def test_unusable_metadata_cannot_freeze_the_sensor(metadata):
    assert lock_controls(metadata) is None


def test_colour_gain_ceiling_is_inclusive():
    controls = lock_controls(settled(ColourGains=(COLOUR_GAIN_MAX, COLOUR_GAIN_MAX)))
    assert controls['ColourGains'] == (COLOUR_GAIN_MAX, COLOUR_GAIN_MAX)


def test_static_controls_pin_the_frame_period_to_the_requested_rate():
    controls = static_controls(8.0)
    assert controls['FrameDurationLimits'] == (125000, 125000)
    # Denoise stays Fast (HighQuality is documented to cost framerate) and
    # sharpening stays off so it cannot invent floor/obstacle boundary edges.
    assert controls['NoiseReductionMode'] == 1
    assert controls['Sharpness'] == 0.0


@pytest.mark.parametrize('fps', [0, -8.0, float('nan'), float('inf'), None, 'fast'])
def test_static_controls_reject_an_unusable_rate(fps):
    assert static_controls(fps) is None


def test_lock_waits_until_the_isp_has_settled():
    assert lock_action(True, now=1.0, deadline=3.5, attempts=0) == 'wait'
    assert lock_action(True, now=3.5, deadline=3.5, attempts=0) == 'attempt'
    assert lock_action(True, now=9.0, deadline=3.5, attempts=0) == 'attempt'


def test_lock_disabled_by_parameter_short_circuits_every_other_condition():
    assert lock_action(False, now=9.0, deadline=3.5, attempts=0) == 'disabled'
    assert lock_action(False, now=0.0, deadline=None, attempts=99) == 'disabled'


def test_lock_waits_when_there_is_no_deadline_to_settle_against():
    assert lock_action(True, now=9.0, deadline=None, attempts=0) == 'wait'


def test_repeated_failures_give_up_rather_than_freeze_on_a_bad_read():
    for attempts in range(LOCK_MAX_ATTEMPTS):
        assert lock_action(True, now=9.0, deadline=3.5, attempts=attempts) == 'attempt'
    assert lock_action(True, now=9.0, deadline=3.5,
                       attempts=LOCK_MAX_ATTEMPTS) == 'exhausted'


@pytest.mark.parametrize('now,deadline', [
    (float('nan'), 3.5), (3.5, float('nan')), ('soon', 3.5), (3.5, 'soon')])
def test_an_unusable_clock_waits_instead_of_locking(now, deadline):
    assert lock_action(True, now=now, deadline=deadline, attempts=0) == 'wait'


def test_a_pose_fit_records_sharpness_off_with_the_lock_it_started_under():
    from control.sensing.perception.camera_controls import controls_are_locked, image_controls_record
    assert not controls_are_locked('')
    assert not controls_are_locked('settling')
    assert not controls_are_locked('auto (lock disabled by parameter)')
    assert controls_are_locked('exposure=19999us gain=2.500 colour_gains=1.800,1.600')
    assert controls_are_locked('v4l2 exposure=1.000 gain=0.000 white_balance=0.000')
    assert image_controls_record('exposure=19999us gain=2.500 colour_gains=1.800,1.600') == {
        'Sharpness': 0.0, 'NoiseReductionMode': 1,
        'capture_controls': 'exposure=19999us gain=2.500 colour_gains=1.800,1.600'}


def test_summary_records_what_the_camera_was_frozen_at():
    assert lock_summary(None) == 'auto'
    assert lock_summary(lock_controls(settled())) == (
        'exposure=19999us gain=2.500 colour_gains=1.800,1.600')


# Re-lock watch: a frozen exposure that no longer fits the scene must re-run the
# settle -> lock sequence (robot rosy_26, 2026-10-06: locked in dim light, 47-71 %
# of the road clipped in room light hours later).
def watch(dwell=3.0, interval=30.0):
    from control.sensing.perception.camera_controls import RelockWatch
    return RelockWatch(dwell, interval)


def feed(w, reason, start, stop, step=0.125):
    """Feed one frame per step in [start, stop); return the times it fired."""
    fired, t = [], start
    while t < stop:
        if w.update(reason, t):
            fired.append(t)
        t += step
    return fired


@pytest.mark.parametrize('reason', ['overexposed', 'low_light'])
def test_persistent_bad_exposure_relocks_exactly_once_after_the_dwell(reason):
    w = watch()
    fired = feed(w, reason, 100.0, 120.0)
    assert fired == [103.0]


@pytest.mark.parametrize('reason', ['overexposed', 'low_light'])
def test_a_single_bad_frame_does_not_relock(reason):
    w = watch()
    assert not w.update(reason, 100.0)
    assert not w.update('usable', 100.125)
    assert feed(w, 'usable', 100.25, 200.0) == []


def test_a_usable_frame_restarts_the_dwell():
    w = watch()
    assert feed(w, 'overexposed', 100.0, 102.9) == []
    assert not w.update('usable', 102.9)
    assert feed(w, 'overexposed', 103.0, 105.9) == []
    assert w.update('overexposed', 106.0)


def test_relock_is_rate_limited_and_fires_as_soon_as_allowed():
    w = watch(dwell=3.0, interval=30.0)
    assert feed(w, 'overexposed', 100.0, 133.0) == [103.0]
    # still bad, but the interval has not elapsed: wait, then fire at 133.0
    assert feed(w, 'overexposed', 133.0, 140.0) == [133.0]


def test_underexposed_or_unknown_reasons_never_relock():
    w = watch()
    assert feed(w, 'underexposed', 0.0, 60.0) == []
    assert feed(w, 'resolution_mismatch', 60.0, 120.0) == []


def test_zero_dwell_disables_the_relock():
    assert feed(watch(dwell=0.0), 'overexposed', 0.0, 60.0) == []


def band_frame(clipped, base=100):
    """320x240 frame whose road band (rows 35-95 %, cols 10-90 %) is `clipped` fraction white."""
    import numpy as np
    frame = np.full((240, 320, 3), base, np.uint8)
    road = frame[84:228, 32:288]
    road[:int(round(road.shape[0] * clipped))] = 255
    return frame


def stats_feed(w, frame, start, stop, step=0.125):
    from control.sensing.perception.camera_visibility import road_clip_stats, visibility_reason
    clip, med = road_clip_stats(frame)
    reason = visibility_reason(frame)
    fired, t = [], start
    while t < stop:
        if w.update(reason, t, clip, med):
            fired.append(t)
        t += step
    return fired


def test_half_clipped_band_is_usable_to_visibility_yet_relocks_once():
    from control.sensing.perception.camera_visibility import visibility_reason
    frame = band_frame(0.5)
    assert visibility_reason(frame) == 'usable'     # the 95 % bar is unchanged
    assert stats_feed(watch(), frame, 100.0, 120.0) == [103.0]


def test_ten_percent_clipped_band_does_not_relock():
    assert stats_feed(watch(), band_frame(0.10), 100.0, 200.0) == []


def test_one_60_percent_frame_among_normal_frames_does_not_relock():
    from control.sensing.perception.camera_visibility import road_clip_stats, visibility_reason
    w = watch()
    bad, ok = band_frame(0.6), band_frame(0.0)
    assert not w.update(visibility_reason(bad), 100.0, *road_clip_stats(bad))
    assert stats_feed(w, ok, 100.125, 200.0) == []


def test_bright_median_alone_relocks():
    w = watch()
    assert not w.update('usable', 100.0, 0.0, 240.0)
    assert w.update('usable', 103.0, 0.0, 240.0)
