import asyncio
from dataclasses import replace

import pytest

from fleet.server.deliberation_journal import DeliberationJournal
from fleet.server.incident_deliberation import run_line_judgment
from rosy.decision.deliberation import Supervisor
from rosy_situation.assessment import AssessmentInput, EvidenceRef, assess
from rosy_situation.snapshot_assessment import POLICY


def judgment(condition='blocked', case='lane-1', revision='core:1:stamp', observed=100):
    request = AssessmentInput('pinky', case, revision, 'core', condition,
        (EvidenceRef('pinky', 'core_state', revision, observed, case),), since=100)
    return assess(request, now=101, policy=POLICY)


class Provider:
    def __init__(self, profile_id, change=lambda: None):
        self.profile_id, self.change, self.calls = profile_id, change, []

    async def __call__(self, problem, prior, remaining, *, budget_usd):
        self.calls.append(problem)
        self.change()
        return dict(subject_id=problem.subject_id, case_id=problem.case_id,
            generation=problem.generation, input_hash=problem.digest,
            choice='reobserve', evidence_ids=list(problem.evidence_ids), objections=[]), .01


def test_current_pinky_judgment_is_advisory_and_not_replayed(tmp_path):
    current = judgment()
    journal = DeliberationJournal(tmp_path / 'fleet.db')
    providers = [Provider('a'), Provider('b')]
    async def run():
        return await run_line_judgment(current, journal, Supervisor(clock=lambda: 101),
            providers, current=lambda: current)
    first = asyncio.run(run())
    assert first == asyncio.run(run()) and first['state'] == 'CANDIDATE'
    assert first['action_admissible'] is False and first['calls'] == 3
    problem = providers[0].calls[0]
    assert problem.domain == 'line_follow' and problem.observed_at == 100
    assert problem.facts_json == '{"state":"blocked"}'
    assert problem.choices == ('reobserve', 'human')


@pytest.mark.parametrize('condition,observed,state', [('normal', 100, 'NOT_NEEDED'),
    ('unknown', 100, 'HOLD'), ('blocked', 90, 'HOLD')])
def test_normal_or_insufficient_observation_never_calls_models(tmp_path, condition, observed, state):
    receipt = judgment(condition, case=None if condition == 'normal' else 'lane-1', observed=observed)
    providers = [Provider('a'), Provider('b')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        Supervisor(clock=lambda: 101), providers, current=lambda: receipt))
    assert result['state'] == state and result['calls'] == 0
    assert not any(p.calls for p in providers)


@pytest.mark.parametrize('change', ['case', 'revision', 'policy', 'stale'])
def test_changed_receipt_discards_candidate(tmp_path, change):
    first = judgment()
    latest = [first]
    replacements = dict(case=judgment(case='lane-2'), revision=judgment(revision='core:2:stamp'),
        policy=replace(first, policy_revision='changed'), stale=judgment(observed=90))
    providers = [Provider('a', lambda: latest.__setitem__(0, replacements[change])), Provider('b')]
    result = asyncio.run(run_line_judgment(first, DeliberationJournal(tmp_path / 'fleet.db'),
        Supervisor(clock=lambda: 101), providers, current=lambda: latest[0]))
    assert result['state'] == 'HOLD' and result['choice'] is None and result['calls'] == 1
