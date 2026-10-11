"""D-679 conditional review has no real provider or execution effects."""
import asyncio

import pytest

from rosy.decision.deliberation import ConditionalReview
from test_deliberation import Provider, problem, reply


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
    first = Provider('qwen', lambda p: reply(p, **change))
    result, providers = run(first)
    assert result['state'] == 'HOLD' and result['reason'] == 'SECONDARY_REVIEW_COMPLETED'
    assert result['choice'] is None and result['action_admissible'] is False
    assert result['calls'] == 2 and result['review_trigger'] == trigger
    assert len(providers[0].calls) == len(providers[1].calls) == 1
    assert providers[1].calls[0][0] == ()
    assert all(item['generation'] == 'g1' for item in result['opinions'])


def test_unsafe_primary_never_calls_secondary():
    result, providers = run(Provider('qwen', lambda p: reply(p, objections=['unsafe'])))
    assert result['state'] == 'HOLD' and result['calls'] == 1
    assert not providers[1].calls


@pytest.mark.parametrize('cost', [None, True, float('nan'), -1, 1])
def test_primary_unknown_or_excess_cost_never_calls_secondary(cost):
    class Costed(Provider):
        async def __call__(self, request, prior, remaining, **kwargs):
            self.calls.append((prior, remaining))
            return reply(request, generation='bad'), cost
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
                return reply(p, objections=['conflict']), 0
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
            problem(necessity='INTERVENE'), [Provider('qwen', lambda p: reply(p, generation='bad')),
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
