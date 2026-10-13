"""D-679 conditional review has no real provider or execution effects."""
import asyncio

import pytest

from rosy.decision.deliberation import ConditionalReview
from test_deliberation import Provider, problem, reply


def changed(request, **changes):
    return {**reply(request), **changes}


def run(first=None, second=None, request=None, **kwargs):
    providers = [first or Provider('qwen'), second or Provider('glm')]
    return asyncio.run(ConditionalReview(clock=lambda: 101, **kwargs).run(
        request or problem(necessity='INTERVENE'), providers, current=lambda: True)), providers


@pytest.mark.parametrize('necessity,state', [('DO_NOT_INTERVENE', 'NOT_NEEDED'), ('ABSTAIN', 'HOLD')])
def test_normal_and_abstention_never_call_models(necessity, state):
    result, providers = run(request=problem(necessity=necessity))
    assert result['state'] == state and result['calls'] == 0
    assert all(not p.calls for p in providers)


def test_valid_primary_does_not_call_glm():
    result, providers = run()
    assert result['state'] == 'CANDIDATE' and result['calls'] == 1
    assert result['action_admissible'] is False and result['policy_id'] == 'conditional-review-v1'
    assert len(result['opinions']) == 1 and not providers[1].calls


@pytest.mark.parametrize('change,trigger', [({'generation': 'wrong'}, 'INVALID_REPLY'),
    ({'choice': 'RESUME'}, 'INVALID_REPLY'), ({'objections': ['conflict']}, 'conflict'),
    ({'objections': ['insufficient_evidence']}, 'insufficient_evidence')])
def test_problematic_primary_gets_one_independent_review_and_stays_hold(change, trigger):
    first = Provider('qwen', lambda p: changed(p, **change))
    result, providers = run(first)
    assert result['state'] == 'HOLD' and result['reason'] == 'SECONDARY_REVIEW_COMPLETED'
    assert result['choice'] is None and result['action_admissible'] is False
    assert result['calls'] == 2 and result['review_trigger'] == trigger
    assert len(providers[0].calls) == len(providers[1].calls) == 1
    assert providers[1].calls[0][0] == ()
    assert all(item['generation'] == 'g1' for item in result['opinions'])


def test_unsafe_primary_never_calls_secondary():
    result, providers = run(Provider('qwen', lambda p: changed(p, objections=['unsafe'])))
    assert result['state'] == 'HOLD' and result['calls'] == 1
    assert not providers[1].calls


@pytest.mark.parametrize('cost', [None, True, float('nan'), -1, 1])
def test_primary_unknown_or_excess_cost_never_calls_secondary(cost):
    class Costed(Provider):
        async def __call__(self, request, prior, remaining, **kwargs):
            self.calls.append((prior, remaining))
            return changed(request, generation='bad'), cost
    result, providers = run(Costed('qwen'))
    assert result['state'] == 'HOLD' and result['calls'] == 1
    assert not providers[1].calls


def test_exception_and_timeout_never_call_paid_reviewer():
    class Failed(Provider):
        async def __call__(self, *args, **kwargs):
            raise OSError('secret provider detail')
    result, providers = run(Failed('qwen'))
    assert result['reason'] == 'PROVIDER_UNKNOWN' and result['cost_usd'] is None
    assert not providers[1].calls and 'secret' not in str(result)
    class Slow(Provider):
        async def __call__(self, *args, **kwargs):
            await asyncio.sleep(1)
    result, providers = run(Slow('qwen'), timeout_s=.01)
    assert result['reason'] == 'TIMEOUT' and not providers[1].calls


def test_changed_generation_after_primary_does_not_submit_glm():
    async def scenario():
        active = True
        class Changed(Provider):
            async def __call__(self, p, *args, **kwargs):
                nonlocal active
                active = False
                return changed(p, objections=['conflict']), 0
        second = Provider('glm')
        result = await ConditionalReview(clock=lambda: 101).run(problem(necessity='INTERVENE'),
            [Changed('qwen'), second], current=lambda: active)
        assert result['reason'] == 'STALE_OR_CHANGED' and result['calls'] == 1
        assert not second.calls
    asyncio.run(scenario())


def test_secondary_cost_uses_remaining_budget_and_partial_records_keep_one_run():
    async def scenario():
        records, budgets = [], []
        class Reviewed(Provider):
            async def __call__(self, p, prior, remaining, *, budget_usd):
                budgets.append(budget_usd)
                return reply(p), .02
        async def record(value):
            records.append(value)
        result = await ConditionalReview(clock=lambda: 101, max_cost_usd=.1).run(
            problem(necessity='INTERVENE'), [Provider('qwen', lambda p: changed(p, generation='bad')),
                Reviewed('glm')], current=lambda: True, record=record)
        assert budgets == pytest.approx([.09])
        assert result['cost_usd'] == pytest.approx(.03) and result['cost_complete'] is True
        assert records[0]['review_trigger'] == 'INVALID_REPLY'
        assert records[-1]['calls'] == 2 and len(records[-1]['opinions']) == 1
    asyncio.run(scenario())


def test_cancel_releases_case_and_concurrent_duplicate_is_refused():
    async def scenario():
        entered = asyncio.Event()
        class Waiting(Provider):
            async def __call__(self, *args, **kwargs):
                entered.set()
                await asyncio.Event().wait()
        policy = ConditionalReview(clock=lambda: 101)
        request = problem(necessity='INTERVENE')
        task = asyncio.create_task(policy.run(request, [Waiting('qwen'), Provider('glm')], current=lambda: True))
        await entered.wait()
        assert (await policy.run(request, [Provider('qwen'), Provider('glm')], current=lambda: True))['reason'] == 'BUSY'
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert (await policy.run(request, [Provider('qwen'), Provider('glm')], current=lambda: True))['calls'] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', ['invalid', 'unknown_cost', 'excess_cost', 'exception', 'unsafe'])
def test_secondary_failure_never_clears_primary_hold(failure):
    class Second(Provider):
        async def __call__(self, p, prior, remaining, **kwargs):
            self.calls.append((prior, remaining))
            if failure == 'exception':
                raise OSError('private auth detail')
            return (changed(p, generation='other') if failure == 'invalid' else
                changed(p, objections=['unsafe']) if failure == 'unsafe' else reply(p)), (
                None if failure == 'unknown_cost' else 1 if failure == 'excess_cost' else .01)
    result, providers = run(Provider('qwen', lambda p: changed(p, objections=['conflict'])), Second('glm'))
    assert result['state'] == 'HOLD' and result['choice'] is None and result['calls'] == 2
    assert result['action_admissible'] is False and result['review_trigger'] == 'conflict'
    assert len(providers[1].calls) == 1 and 'private' not in str(result)
    assert result['cost_complete'] is (failure not in {'unknown_cost', 'exception'})


def test_policy_checks_scope_again_after_reviewer_response():
    async def scenario():
        active = True
        class Changed(Provider):
            async def __call__(self, p, *args, **kwargs):
                nonlocal active
                active = False
                return reply(p), 0
        result = await ConditionalReview(clock=lambda: 101).run(problem(necessity='INTERVENE'),
            [Provider('qwen', lambda p: changed(p, objections=['conflict'])), Changed('glm')],
            current=lambda: active)
        assert result['reason'] == 'STALE_OR_CHANGED' and result['calls'] == 2
        assert len(result['opinions']) == 1 and result['action_admissible'] is False
    asyncio.run(scenario())


def test_exhausted_primary_budget_does_not_submit_zero_budget_review():
    result, providers = run(Provider('qwen', lambda p: changed(p, objections=['conflict'])), max_cost_usd=.01)
    assert result['reason'] == 'COST_EXCEEDED' and result['calls'] == 1
    assert result['cost_complete'] is True and not providers[1].calls


def test_invalid_profiles_and_stale_request_never_call_models():
    policy = ConditionalReview(clock=lambda: 101)
    first, second = Provider('same'), Provider('same')
    result = asyncio.run(policy.run(problem(necessity='INTERVENE'), [first, second], current=lambda: True))
    assert result['reason'] == 'PROFILES_REQUIRED' and result['calls'] == 0
    result = asyncio.run(policy.run(problem(necessity='INTERVENE', observed_at=90),
        [first, second], current=lambda: True))
    assert result['reason'] == 'STALE_OR_CHANGED' and result['calls'] == 0
    assert not first.calls and not second.calls


def test_fleet_primary_disagreement_passes_bound_opinion_for_comparison():
    request = problem(necessity='INTERVENE', fleet_choice='human')
    result, providers = run(request=request)
    assert result['state'] == 'HOLD' and result['review_trigger'] == 'fleet_qwen_disagreement'
    assert result['calls'] == 2 and result['choice'] is None
    prior = providers[1].calls[0][0]
    assert len(prior) == 1 and prior[0]['profile_id'] == 'qwen'
    assert prior[0]['choice'] == 'reobserve' and prior[0]['input_hash'] == request.digest


def test_matching_fleet_choice_and_normal_case_do_not_call_reviewer():
    result, providers = run(request=problem(necessity='INTERVENE', fleet_choice='reobserve'))
    assert result['calls'] == 1 and not providers[1].calls
    result, providers = run(request=problem(necessity='DO_NOT_INTERVENE', fleet_choice='human'))
    assert result['calls'] == 0 and all(not p.calls for p in providers)


def test_fleet_baseline_is_allowlisted_and_changes_problem_hash():
    first, second = problem(fleet_choice='human'), problem(fleet_choice='reobserve')
    assert first.digest != second.digest and first.digest != problem().digest
    for choice in ('RESUME', 'map_correction', '', True, ['human']):
        with pytest.raises(ValueError):
            problem(fleet_choice=choice)


def test_optional_baseline_preserves_existing_problem_digest():
    import hashlib
    from dataclasses import asdict
    from rosy.decision.deliberation import canonical
    request = problem()
    legacy = asdict(request)
    legacy.pop('fleet_choice')
    assert request.digest == hashlib.sha256(canonical(legacy).encode()).hexdigest()
