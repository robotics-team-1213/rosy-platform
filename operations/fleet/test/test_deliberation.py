"""Bounded advisory deliberation; no provider or robot calls in these fixtures."""
import asyncio
import json

import pytest

from rosy.decision.deliberation import Problem, Supervisor


def problem(**changes):
    data = dict(subject_id='pinky', case_id='lane-1', generation='g1',
                domain='door', observed_at=100.0, evidence_ids=['cam-1'],
                choices=['reobserve', 'human'], necessity='ABSTAIN')
    return Problem(**{**data, **changes})


def reply(request, choice='reobserve', **changes):
    return dict(subject_id=request.subject_id, case_id=request.case_id,
                generation=request.generation, input_hash=request.digest,
                choice=choice, evidence_ids=['cam-1'], objections=[], **changes)


class Provider:
    def __init__(self, name, answer=None):
        self.profile_id = name
        self.answer = answer
        self.calls = []

    async def __call__(self, request, prior, remaining, *, budget_usd):
        self.calls.append((prior, remaining))
        return (self.answer or reply)(request), 0.01


def run(request, providers=None, current=lambda: True):
    supervisor = Supervisor(clock=lambda: 101.0)
    return asyncio.run(supervisor.run(request, providers or [Provider('a'), Provider('b')], current=current))


def test_independent_two_opinions_one_rebuttal_are_advisory():
    first, second = Provider('a'), Provider('b')
    result = run(problem(), [first, second])
    assert result['state'] == 'CANDIDATE'
    assert result['choice'] == 'reobserve'
    assert result['action_admissible'] is False
    assert result['calls'] == 3
    assert first.calls[0][0] == second.calls[0][0] == ()
    assert len(first.calls[1][0]) == 2


def test_normal_bypasses_models():
    providers = [Provider('a'), Provider('b')]
    result = run(problem(necessity='DO_NOT_INTERVENE'), providers)
    assert result['state'] == 'NOT_NEEDED' and result['calls'] == 0
    assert not any(p.calls for p in providers)


@pytest.mark.parametrize('domain', ['door', 'arm_target'])
def test_both_domain_fixtures_have_no_new_command(domain):
    assert run(problem(domain=domain))['choice'] == 'reobserve'


@pytest.mark.parametrize('changes', [dict(choice='RESUME'), dict(evidence_ids=['invented']),
                                  dict(generation='old'), dict(input_hash='other'),
                                  dict(verified=True), dict(objections=['unsafe'])])
def test_bad_model_reply_or_unresolved_objection_holds(changes):
    def invalid(request):
        data = reply(request)
        return {**data, **changes}
    result = run(problem(), [Provider('a', invalid), Provider('b')])
    assert result['state'] == 'HOLD' and result['choice'] is None


def test_disagreement_is_not_a_vote():
    result = run(problem(), [Provider('a'), Provider('b', lambda p: reply(p, 'human'))])
    assert result['state'] == 'HOLD' and result['reason'] == 'CONFLICT'


def test_stale_future_generation_change_and_duplicate_profiles_refuse():
    assert run(problem(observed_at=90))['calls'] == 0
    assert run(problem(observed_at=102))['calls'] == 0
    assert run(problem(), current=lambda: False)['calls'] == 0
    assert run(problem(), [Provider('a'), Provider('a')])['calls'] == 0


def test_provider_error_unknown_cost_and_global_deadline_hold():
    async def broken(*args, **kwargs):
        raise OSError('private secret error')
    p = Provider('a')
    p.__class__ = type('Broken', (Provider,), {'__call__': broken})
    assert run(problem(), [p, Provider('b')])['reason'] == 'PROVIDER_UNKNOWN'
    failed_result = run(problem(), [p, Provider('b')])
    assert failed_result['cost_usd'] is None and failed_result['cost_complete'] is False
    assert failed_result['unknown_cost_calls'] == 1

    class UnknownCost(Provider):
        async def __call__(self, request, prior, remaining, **kwargs):
            return reply(request), None
    assert run(problem(), [UnknownCost('a'), Provider('b')])['state'] == 'HOLD'

    class Slow(Provider):
        async def __call__(self, *args, **kwargs):
            await asyncio.sleep(1)
    result = asyncio.run(Supervisor(clock=lambda: 101, timeout_s=0.01).run(
        problem(), [Slow('a'), Provider('b')], current=lambda: True))
    assert result['reason'] == 'TIMEOUT'


def test_same_case_concurrency_is_rejected_and_cancel_releases():
    async def scenario():
        entered = asyncio.Event()
        class Waiting(Provider):
            async def __call__(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        supervisor = Supervisor(clock=lambda: 101)
        task = asyncio.create_task(supervisor.run(problem(), [Waiting('a'), Provider('b')], current=lambda: True))
        await entered.wait()
        duplicate = await supervisor.run(problem(), [Provider('a'), Provider('b')], current=lambda: True)
        assert duplicate['reason'] == 'BUSY'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await supervisor.run(problem(), [Provider('a'), Provider('b')], current=lambda: True))['state'] == 'CANDIDATE'
    asyncio.run(scenario())


@pytest.mark.parametrize('changes', [dict(choices=['RESUME']), dict(observed_at=float('nan')),
                                  dict(evidence_ids=[]), dict(domain='invented')])
def test_input_boundary_rejects_invalid(changes):
    with pytest.raises(ValueError):
        problem(**changes)


def test_invalid_profiles_and_owner_read_failure_hold_without_calls():
    for providers in ([None, Provider('b')], [Provider(''), Provider('b')]):
        assert run(problem(), providers)['reason'] == 'PROFILES_REQUIRED'
    def failed():
        raise OSError('owner unavailable')
    assert run(problem(), current=failed)['reason'] == 'STALE_OR_CHANGED'


def test_goal_and_approved_facts_are_bound_into_input_hash():
    first = problem()
    second = problem(facts_json='{"door_state":"closed"}', goal='reach_destination')
    assert second.digest != first.digest


def test_remaining_cost_budget_is_not_reset():
    budgets = []
    class Costed(Provider):
        async def __call__(self, request, prior, remaining, *, budget_usd):
            budgets.append(budget_usd)
            return reply(request), 0.01
    result = run(problem(), [Costed('a'), Costed('b')])
    assert result['calls'] == 3
    assert budgets == pytest.approx([0.30, 0.29, 0.28])
