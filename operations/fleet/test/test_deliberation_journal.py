import asyncio
import json

import pytest

from fleet.server.deliberation_journal import DeliberationJournal
from rosy.decision.deliberation import Supervisor
from test_deliberation import Provider, problem


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

