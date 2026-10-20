"""Charging decisions budget the return and dock, not just the next task."""
import importlib
import importlib.util

import pytest

from core_common.protocol.station_charging import BatteryEnergyEvidence, ChargePolicyProfile


def battery(**changes):
    return BatteryEnergyEvidence.model_validate(dict(
        battery_id='pack-1', captured_at=100.0, valid_until=105.0, source='fuel_gauge',
        capacity_revision='capacity-3', soc_percent=75.0, soh_percent=85.0,
        usable_energy_wh=10.0, temperature_c=25.0, fault=None) | changes)


def profile(**changes):
    return ChargePolicyProfile.model_validate(dict(
        profile_id='sim-profile', revision='profile-1', battery_id='pack-1', reevaluate_interval_s=1.0,
        return_soc_percent=20.0, redeploy_soc_percent=70.0, reserve_wh=1.0,
        max_work_s=120.0, max_return_s=60.0, conservative_profile_verified=False,
        min_temperature_c=10.0, max_temperature_c=45.0, min_soh_percent=60.0) | changes)


def decide(sample=None, policy=None, **changes):
    name = 'rosy.execution.site.charge_policy'
    assert importlib.util.find_spec(name) is not None, 'battery-aware charge policy is not implemented'
    return importlib.import_module(name).evaluate_charge_policy(
        sample or battery(), policy or profile(), **(dict(
            now=100.2, work_wh=4.0, return_wh=2.0, dock_wh=0.5, reserve_wh=1.0,
            dock_valid=True, work_duration_s=100.0, return_duration_s=50.0,
            departing_charge=False) | changes))


def test_work_must_leave_return_docking_and_reserve_energy():
    accepted = decide()
    assert accepted.decision == 'WORK_ALLOWED'
    assert accepted.required_wh == 7.5
    assert decide(work_wh=8.0).decision == 'RETURN_REQUIRED'
    assert decide(battery(usable_energy_wh=2.0)).decision == 'MAINTENANCE_HOLD'
    assert decide(reserve_wh=0.0).required_wh == 7.5


def test_aged_capacity_low_soc_and_hot_or_faulty_pack_affect_admission():
    assert decide(battery(usable_energy_wh=6.0, soh_percent=65.0)).decision == 'RETURN_REQUIRED'
    assert decide(battery(soc_percent=19.0)).decision == 'RETURN_REQUIRED'
    for sample in (battery(soh_percent=50.0), battery(temperature_c=50.0), battery(fault='PACK_FAULT')):
        assert decide(sample).decision == 'MAINTENANCE_HOLD'


@pytest.mark.parametrize('changes', [dict(now=106.0), dict(dock_valid=False), dict(work_wh=None),
                                    dict(return_wh=None), dict(work_wh=float('nan')),
                                    dict(return_wh=-1.0), dict(dock_wh=None)])
def test_missing_or_invalid_budget_and_expired_evidence_do_not_admit_work(changes):
    assert decide(**changes).decision != 'WORK_ALLOWED'


def test_unknown_health_uses_only_an_explicit_verified_conservative_time_profile():
    unknown = battery(source='voltage_only', capacity_revision=None, soh_percent=None, usable_energy_wh=None)
    assert decide(unknown).decision == 'WAIT'
    conservative = profile(conservative_profile_verified=True)
    assert decide(unknown, conservative, work_wh=None, return_wh=None, dock_wh=None).decision == 'WORK_ALLOWED'
    assert decide(unknown, conservative, work_duration_s=121.0).decision == 'WAIT'
    assert decide(unknown, conservative, return_duration_s=61.0).decision == 'WAIT'
    assert decide(unknown, conservative, work_duration_s=None).decision == 'WAIT'
    assert unknown.soh_percent is None


def test_battery_swap_and_post_charge_hysteresis_are_not_silently_accepted():
    assert decide(battery(battery_id='new-pack')).decision == 'WAIT'
    assert decide(battery(soc_percent=65.0), departing_charge=True).decision == 'WAIT'
    assert decide(battery(soc_percent=70.0), departing_charge=True).decision == 'WORK_ALLOWED'


def test_finite_return_costs_whose_sum_overflows_hold_without_throwing():
    result = decide(return_wh=1e308, dock_wh=1e308)
    assert result.decision == 'WAIT' and result.reason == 'ENERGY_BUDGET_OVERFLOW'
    assert result.required_wh is None
