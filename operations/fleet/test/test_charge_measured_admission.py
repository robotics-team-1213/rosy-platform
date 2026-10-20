"""Measured-health installation and final dispatch; synthetic fixtures, no device permit."""
import asyncio
from copy import deepcopy

import pytest

from fleet.server.app import create_app
from fleet.server.charge_policy_admission import ChargePolicyAdmission
from test_charge_bootstrap import factory, parts
from test_charge_policy import profile
from test_charge_runtime import configured


def measured(runtime, *, bindings=None):
    from fleet.server.charge_policy_admission import MeasuredChargePolicyAdmission
    current = runtime.admission
    return MeasuredChargePolicyAdmission(profiles=current.profiles, clock=current.clock,
        budget_source=current.budget_source, max_age_s=current.max_age_s,
        measured_sources=bindings if bindings is not None else {'robot-1': ('fuel_gauge', 'capacity-3')})


def sample_and_target(tmp_path, *, conservative=False):
    runtime, service, _, _, _, sample, _, _, _ = configured(tmp_path,
        policy_profile=profile(conservative_profile_verified=conservative))
    sample['battery_energy']['soc_percent'] = 75.
    target = service._target('charger-1', 1)
    return runtime, sample, target


def test_operational_bootstrap_rejects_time_only_policy_before_installing_guards(tmp_path):
    ingress, console, tasks = parts(tmp_path)
    original = tasks.charge_admission
    def legacy(context):
        runtime = factory(context)
        current = runtime.admission
        runtime.admission = runtime.service.admit_return = ChargePolicyAdmission(
            profiles=current.profiles, clock=current.clock, budget_source=current.budget_source,
            max_age_s=current.max_age_s)
        return runtime
    with pytest.raises(ValueError, match='CHARGE_RUNTIME_MEASURED_HEALTH_REQUIRED'):
        create_app(console, task_service=tasks, station_ingress=ingress, charge_runtime_factory=legacy)
    assert tasks.charge_admission is original


def test_operational_bootstrap_accepts_explicit_measured_policy_with_same_owners(tmp_path):
    ingress, console, tasks = parts(tmp_path)
    def build(context):
        runtime = factory(context)
        runtime.admission = runtime.service.admit_return = measured(runtime)
        return runtime
    app = create_app(console, task_service=tasks, station_ingress=ingress, charge_runtime_factory=build)
    runtime = app.state.charge_runtime
    assert runtime.service.store is ingress.sessions
    assert tasks.charge_admission.__self__ is runtime


@pytest.mark.parametrize('change', [
    {'soh_percent': None}, {'usable_energy_wh': None}, {'temperature_c': None},
    {'capacity_revision': 'other-calibration'}, {'battery_id': 'other-pack'},
    {'source': 'bms'}, {'captured_at': 98., 'valid_until': 110.},
    {'captured_at': 102., 'valid_until': 110.}, {'valid_until': 100.},
    {'source': 'voltage_only', 'capacity_revision': None, 'soh_percent': None, 'usable_energy_wh': None},
])
def test_missing_or_changed_measurement_cannot_use_conservative_fallback(tmp_path, change):
    runtime, sample, target = sample_and_target(tmp_path, conservative=True)
    policy = measured(runtime)
    sample['battery_energy'].update(change)
    for departing in (False, True):
        decision = policy(sample, target, departing_charge=departing)
        assert decision.decision not in ('WORK_ALLOWED', 'RETURN_REQUIRED')


def test_measured_policy_keeps_original_work_return_and_maintenance_decisions(tmp_path):
    runtime, sample, target = sample_and_target(tmp_path)
    policy = measured(runtime)
    assert policy(sample, target).decision == 'WORK_ALLOWED'
    assert policy(sample, target).required_wh == 7.5
    sample['battery_energy']['soc_percent'] = 10.
    assert policy(sample, target).decision == 'RETURN_REQUIRED'
    sample['battery_energy']['soh_percent'] = 50.
    assert policy(sample, target).decision == 'MAINTENANCE_HOLD'


def test_legacy_policy_retains_its_explicit_conservative_profile(tmp_path):
    runtime, sample, target = sample_and_target(tmp_path, conservative=True)
    sample['battery_energy'].update(source='voltage_only', capacity_revision=None,
                                  soh_percent=None, usable_energy_wh=None)
    assert type(runtime.admission) is ChargePolicyAdmission
    assert runtime.admission(sample, target).decision == 'WORK_ALLOWED'
    assert measured(runtime)(sample, target).decision == 'WAIT'


@pytest.mark.parametrize('bindings', [{}, {'other': ('fuel_gauge', 'capacity-3')},
    {'robot-1': ('voltage_only', 'capacity-3')}, {'robot-1': ('fuel_gauge', '')},
    {'robot-1': ['fuel_gauge', 'capacity-3']}, {'robot-1': ('fuel_gauge',)}, None])
def test_measured_installation_requires_exact_supported_source_and_capacity(tmp_path, bindings):
    from fleet.server.charge_policy_admission import MeasuredChargePolicyAdmission
    runtime, _, _ = sample_and_target(tmp_path)
    with pytest.raises(ValueError, match='CHARGE_MEASURED_SOURCE_PROFILE_REQUIRED'):
        MeasuredChargePolicyAdmission(profiles=runtime.admission.profiles,
            clock=runtime.admission.clock, budget_source=runtime.admission.budget_source,
            max_age_s=runtime.admission.max_age_s, measured_sources=bindings)


def test_installation_copies_binding_and_cannot_adopt_new_calibration_by_mutation(tmp_path):
    runtime, sample, target = sample_and_target(tmp_path)
    bindings = {'robot-1': ('fuel_gauge', 'capacity-3')}
    policy = measured(runtime, bindings=bindings)
    bindings['robot-1'] = ('fuel_gauge', 'capacity-new')
    assert policy(sample, target).decision == 'WORK_ALLOWED'
    sample['battery_energy']['capacity_revision'] = 'capacity-new'
    assert policy(sample, target).decision == 'WAIT'


def test_final_work_guard_rechecks_measured_health_after_last_periodic_decision(tmp_path):
    async def run():
        runtime, _, _, _, _, sample, _, _, _ = configured(tmp_path)
        runtime.admission = runtime.service.admit_return = measured(runtime)
        sample['battery_energy']['soc_percent'] = 75.
        await runtime.tick()
        assert runtime.work_admission('robot-1') is None
        # Cache corruption or incomplete readback cannot inherit the earlier decision.
        runtime._work_snapshot = deepcopy(runtime._work_snapshot)
        runtime._work_snapshot['battery_energy']['soh_percent'] = None
        assert runtime.work_admission('robot-1') is not None
    asyncio.run(run())
