"""Normal charger termination survives charging-window reset without trusting voltage alone."""
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import ChargeCompletionEvidence


SCOPE = dict(station_id='charger-1', robot_id='robot-1', session_id='charge-1',
             boot_id='boot-1', battery_id='pack-1')


def evidence(at, **changes):
    return ChargeCompletionEvidence.model_validate(SCOPE | dict(
        captured_at=at, valid_until=at + 0.5, pack_sample_at=at, pack_voltage_v=8.3, termination_sample_at=at,
        load_present=True, charging=False, source='charger', termination='NORMAL', faults=[]) | changes)


def tracker():
    name = 'core_features.docking.completion'
    assert importlib.util.find_spec(name) is not None, 'seating/charge completion gates are not implemented'
    return importlib.import_module(name).ChargeCompletionTracker(
        scope=SCOPE, session_started_at=100.0, min_full_voltage_v=8.2, max_voltage_v=8.45, pack_max_age_s=0.25)


def test_normal_termination_remains_verifiable_after_charging_window_resets():
    from core_features.docking.agent import DockReachability, DockStatus
    from core_features.docking.charging import ChargingConfirmation
    charging = ChargingConfirmation(window_s=0.1)
    status = DockStatus(reachability=DockReachability.OK, load_present=True, charging=True)
    charging.update(status, 8.3, now=100.0)
    assert charging.update(status, 8.3, now=100.2)
    assert not charging.update(DockStatus(reachability=DockReachability.OK, load_present=True,
                                          charging=False), 8.3, now=100.3)
    assert charging.peak_v is None
    assert tracker().update(evidence(100.3), now=100.3)


@pytest.mark.parametrize('changes', [dict(termination='UNKNOWN'), dict(termination='CHARGING', charging=True),
                                    dict(session_id='old'), dict(boot_id='old'), dict(battery_id='other'),
                                    dict(pack_sample_at=99.0), dict(pack_voltage_v=8.0),
                                    dict(pack_voltage_v=8.5)])
def test_ambiguous_wrong_session_or_stale_pack_is_not_charge_complete(changes):
    assert not tracker().update(evidence(100.0, **changes), now=100.0)


def test_expired_completion_and_new_charging_cycle_do_not_enable_departure():
    value = tracker()
    assert value.update(evidence(100.0), now=100.0)
    assert not value.update(evidence(100.0), now=100.6)
    value.reset('charge-2', session_started_at=100.7)
    assert not value.update(evidence(100.7), now=100.7)
    assert not value.update(evidence(100.8, session_id='charge-2', termination='CHARGING', charging=True), now=100.8)


def test_repolling_an_old_termination_does_not_make_the_source_event_fresh():
    stale = evidence(100.0).model_copy(update={'termination_sample_at': 90.0})
    assert not tracker().update(stale, now=100.0)


def test_fresh_normal_state_can_retain_same_session_termination_while_waiting_for_work():
    current = evidence(101.0, termination_sample_at=100.0)
    assert tracker().update(current, now=101.0)
