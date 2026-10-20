"""A zero command cannot establish physical seating or continuous standstill."""
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import SeatingEvidence


SCOPE = dict(robot_id='robot-1', station_id='charger-1', session_id='charge-1',
             boot_id='boot-1', pose_revision=1, odom_epoch='odom-1')


def seating(at, **changes):
    return SeatingEvidence.model_validate(SCOPE | dict(
        captured_at=at, valid_until=at + 0.3, motion_sample_at=at, contact_sample_at=at, position_sample_at=at,
        position_error_m=0.002, heading_error_rad=0.01, measured_linear_m_s=0.0,
        measured_angular_rad_s=0.0, load_present=True) | changes)


def gate():
    name = 'core_features.docking.completion'
    assert importlib.util.find_spec(name) is not None, 'seating/charge completion gates are not implemented'
    return importlib.import_module(name).SeatingGate(
        scope=SCOPE, position_tolerance_m=0.012, heading_tolerance_rad=0.05,
        linear_limit_m_s=0.003, angular_limit_rad_s=0.01,
        still_s=0.4, debounce_s=0.3, sample_max_age_s=0.25)


def test_requires_continuous_measured_stop_contact_and_target_tolerance():
    value = gate()
    assert not value.update(seating(100.0), now=100.0)
    assert not value.update(seating(100.2), now=100.2)
    assert value.update(seating(100.41), now=100.41)


@pytest.mark.parametrize('changes', [dict(load_present=False), dict(measured_linear_m_s=0.02),
                                    dict(measured_angular_rad_s=0.02), dict(position_error_m=0.02),
                                    dict(heading_error_rad=0.1), dict(session_id='old'),
                                    dict(boot_id='old'), dict(pose_revision=2),
                                    dict(motion_sample_at=99.0), dict(contact_sample_at=99.0)])
def test_invalid_or_moving_sample_cannot_complete_seating(changes):
    value = gate()
    value.update(seating(100.0), now=100.0)
    value.update(seating(100.2), now=100.2)
    assert not value.update(seating(100.41, **changes), now=100.41)


def test_missing_samples_replay_and_clock_reversal_break_continuity():
    value = gate()
    value.update(seating(100.0), now=100.0)
    assert not value.update(seating(100.5), now=100.5)
    assert not value.update(seating(100.5), now=100.5)
    assert not value.update(seating(100.2), now=100.2)


def test_fresh_motion_and_contact_cannot_refresh_old_camera_position():
    value = gate()
    value.update(seating(100.0), now=100.0)
    value.update(seating(100.2), now=100.2)
    stale_position = seating(100.41).model_copy(update={'position_sample_at': 99.0})
    assert not value.update(stale_position, now=100.41)
