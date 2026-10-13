import asyncio
import json

import pytest

from fleet.server.deliberation_journal import DeliberationJournal
from rosy.decision.deliberation import Supervisor
from test_deliberation import Provider, problem


@pytest.mark.parametrize('conditional_first', [False, True])
def test_cached_case_cannot_change_evaluation_policy(tmp_path, conditional_first):
    class ReviewSupervisor(Supervisor):
        policy_id = 'conditional-review-v1'
    first, second = (ReviewSupervisor, Supervisor) if conditional_first else (Supervisor, ReviewSupervisor)
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    providers = [Provider('a'), Provider('b')]
    request = problem()
    asyncio.run(journal.run(request, first(clock=lambda: 101), providers, current=lambda: True))
    calls = sum(len(p.calls) for p in providers)
    result = asyncio.run(journal.run(request, second(clock=lambda: 101), providers, current=lambda: True))
    assert result['state'] == 'HOLD' and result['reason'] == 'EVALUATION_POLICY_CHANGED'
    assert result['choice'] is None and result['action_admissible'] is False
    assert sum(len(p.calls) for p in providers) == calls


def test_durable_candidate_duplicate_and_content_conflict(tmp_path):
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    providers = [Provider('a'), Provider('b')]
    request = problem()
    first = asyncio.run(journal.run(request, Supervisor(clock=lambda: 101), providers, current=lambda: True))
    again = asyncio.run(DeliberationJournal(journal.path).run(
        request, Supervisor(clock=lambda: 101), providers, current=lambda: True))
    assert first == again and sum(len(p.calls) for p in providers) == 3
    assert first['action_admissible'] is False
    with pytest.raises(ValueError, match='CONTENT_CHANGED'):
        asyncio.run(journal.run(problem(evidence_ids=['another']), Supervisor(), providers, current=lambda: True))
    assert journal.read(request)['state'] == 'CANDIDATE'


def test_restart_unknown_never_replays_and_changed_case_is_suppressed(tmp_path):
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    journal.begin(problem())
    providers = [Provider('a'), Provider('b')]
    result = asyncio.run(journal.run(problem(), Supervisor(clock=lambda: 101), providers, current=lambda: True))
    assert result['reason'] == 'RESTART_OR_INFLIGHT_UNKNOWN'
    assert not any(p.calls for p in providers)
    request = problem(case_id='next')
    result = asyncio.run(journal.run(request, Supervisor(clock=lambda: 101), providers, current=lambda: False))
    assert result['state'] == 'HOLD' and result['calls'] == 0


def test_journal_failure_blocks_provider_and_result_failure_blocks_delivery(tmp_path):
    providers = [Provider('a'), Provider('b')]
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    def failed(*args):
        raise OSError('journal unavailable')
    journal.begin = failed
    with pytest.raises(OSError):
        asyncio.run(journal.run(problem(), Supervisor(clock=lambda: 101), providers, current=lambda: True))
    assert not any(p.calls for p in providers)


def test_cached_result_rechecks_current_and_pending_generation_blocks(tmp_path):
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    request = problem()
    providers = [Provider('a'), Provider('b')]
    asyncio.run(journal.run(request, Supervisor(clock=lambda: 101), providers, current=lambda: True))
    stale = asyncio.run(journal.run(request, Supervisor(clock=lambda: 110), providers, current=lambda: True))
    assert stale['state'] == 'HOLD' and stale['choice'] is None
    journal.begin(problem(case_id='pending'))
    blocked = journal.begin(problem(case_id='pending', generation='next'))
    assert blocked['reason'] == 'BUSY_OR_BUDGET_EXHAUSTED'


def test_capacity_and_per_opinion_durable_failure_block_new_calls(tmp_path):
    journal = DeliberationJournal(tmp_path / 'fleet.db', max_rows=1)
    providers = [Provider('a'), Provider('b')]
    original = journal.write
    writes = []
    def capture(request, result, terminal):
        writes.append((result['calls'], terminal))
        return original(request, result, terminal)
    journal.write = capture
    asyncio.run(journal.run(problem(), Supervisor(clock=lambda: 101), providers, current=lambda: True))
    assert writes == [(1, False), (2, False), (3, False), (3, True)]
    with pytest.raises(ValueError, match='CAPACITY'):
        journal.begin(problem(case_id='other'))

    another = DeliberationJournal(tmp_path / 'other.db')
    def failed(*args):
        raise OSError('durable opinion write failed')
    another.write = failed
    providers = [Provider('a'), Provider('b')]
    with pytest.raises(OSError):
        asyncio.run(another.run(problem(), Supervisor(clock=lambda: 101), providers, current=lambda: True))
    assert sum(len(p.calls) for p in providers) == 1

