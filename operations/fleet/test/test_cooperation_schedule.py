"""Mode admission uses measured capacity, never the model's own confidence."""
from dataclasses import replace
import importlib
import importlib.util

import pytest


def api():
    name = 'rosy.decision.deliberation.cooperation_schedule'
    assert importlib.util.find_spec(name) is not None, 'cooperation scheduling is missing'
    return importlib.import_module(name)


def inputs(**changes):
    m = api()
    environment = m.ExecutionEnvironment('env-1', 110.0, True, True)
    measurements = m.ExecutionMeasurements('measure-1', ('a-r1', 'b-r1'), 110.0,
        1.2, 0.7, (0.02, 0.03), 0.1, True)
    return dict(requested_mode='auto', environment=environment, measurements=measurements,
        profile_keys=('a-r1', 'b-r1'), input_hash='input-1', now=101.0,
        remaining_s=2.0, remaining_usd=0.1, **changes)


@pytest.mark.parametrize('mode,parallel,seq_s,par_s,want', [
    ('auto', True, 1.2, 0.7, 'parallel'),
    ('auto', True, 0.7, 1.2, 'sequential'),
    ('auto', True, 0.7, 0.7, 'sequential'),
    ('auto', True, 0.7, 0.65, 'sequential'),
    ('auto', False, 1.2, 0.7, 'sequential'),
    ('parallel', False, 1.2, 0.7, 'hold'),
    ('sequential', True, 1.2, 0.7, 'sequential'),
])
def test_select_mode_uses_benefit_and_forced_mode(mode, parallel, seq_s, par_s, want):
    args = inputs()
    args.update(requested_mode=mode,
        environment=replace(args['environment'], parallel_ready=parallel),
        measurements=replace(args['measurements'], sequential_s=seq_s, parallel_s=par_s))
    result = api().select_mode(**args)
    assert result.mode == want
    assert result.requested_mode == mode
    assert result.cost_caps == (0.02, 0.03)


def test_auto_can_choose_parallel_when_only_it_meets_deadline():
    args = inputs()
    args.update(remaining_s=0.8)
    assert api().select_mode(**args).mode == 'parallel'
    args['measurements'] = replace(args['measurements'], parallel_accepted=False)
    assert api().select_mode(**args).mode == 'hold'


@pytest.mark.parametrize('change', ['environment_expired', 'measurement_expired', 'profile_changed',
    'no_capacity', 'no_time', 'no_money', 'parallel_unmeasured'])
def test_missing_or_stale_admission_never_guesses_capacity(change):
    args = inputs()
    if change == 'environment_expired': args['environment'] = replace(args['environment'], expires_at=100)
    if change == 'measurement_expired': args['measurements'] = replace(args['measurements'], expires_at=100)
    if change == 'profile_changed': args['profile_keys'] = ('a-r2', 'b-r1')
    if change == 'no_capacity': args['environment'] = replace(args['environment'], sequential_ready=False, parallel_ready=False)
    if change == 'no_time': args['remaining_s'] = 0.1
    if change == 'no_money': args['remaining_usd'] = 0.04
    if change == 'parallel_unmeasured':
        args.update(requested_mode='parallel', measurements=replace(args['measurements'], parallel_s=None))
    assert api().select_mode(**args).mode == 'hold'


def test_decision_hash_covers_budget_context_policy_and_requested_mode():
    m = api()
    args = inputs()
    first = m.select_mode(**args)
    assert m.select_mode(**args) == first
    for key, value in [('remaining_s', 1.9), ('remaining_usd', 0.09),
                       ('input_hash', 'input-2'), ('requested_mode', 'parallel')]:
        assert m.select_mode(**{**args, key: value}).decision_hash != first.decision_hash


@pytest.mark.parametrize('field,value', [('remaining_s', float('nan')), ('remaining_usd', -1),
    ('remaining_s', True), ('now', float('inf')), ('requested_mode', 'fastest')])
def test_invalid_selection_inputs_are_rejected(field, value):
    with pytest.raises(ValueError): api().select_mode(**{**inputs(), field: value})


def test_measurements_from_another_host_or_workload_cannot_admit_parallel():
    args = inputs()
    args['environment'] = replace(args['environment'], workload_key='other-host-workload')
    assert api().select_mode(**args).mode == 'hold'
