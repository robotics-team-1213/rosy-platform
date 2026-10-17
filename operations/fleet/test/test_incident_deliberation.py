import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from fleet.server.ledger.deliberation_journal import DeliberationJournal
from fleet.server.incident_deliberation import FleetBaseline, run_line_judgment
from rosy.decision.deliberation import ConditionalReview, Supervisor
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


def test_board_explicit_caller_uses_existing_core_observation(tmp_path):
    from fleet.stuck.board import LineStuckBoard
    board = LineStuckBoard(wall=lambda: 101)
    board.observe([dict(robot_id='pinky', online=True, state_age_s=1,
        state=dict(seq=1, timestamp=datetime.fromtimestamp(100, timezone.utc).isoformat(),
            line_follow=dict(mode='CAMERA_LINE', stuck=dict(stuck_id='lane-1', phase='ASKING'))))])
    result = asyncio.run(board.deliberate('pinky', DeliberationJournal(tmp_path / 'fleet.db'),
        Supervisor(clock=lambda: 101), [Provider('a'), Provider('b')]))
    assert result['state'] == 'CANDIDATE' and result['action_admissible'] is False


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


@pytest.mark.parametrize('owner,source', [('unknown', 'core_state'), ('core', 'invented')])
def test_wrong_owner_or_source_never_calls_models(tmp_path, owner, source):
    receipt = judgment()
    request = replace(receipt.request, owner=owner,
        evidence=(replace(receipt.request.evidence[0], source=source),))
    receipt = replace(receipt, request=request)
    providers = [Provider('a'), Provider('b')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        Supervisor(clock=lambda: 101), providers, current=lambda: receipt))
    assert result['state'] == 'HOLD' and result['calls'] == 0


def test_scoped_fleet_baseline_mismatch_requests_one_comparison(tmp_path):
    receipt = judgment()
    baseline = FleetBaseline.from_assessment(receipt, 'human')
    providers = [Provider('qwen'), Provider('glm')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        ConditionalReview(clock=lambda: 101), providers, current=lambda: receipt,
        baseline=baseline, current_baseline=lambda: baseline))
    assert result['review_trigger'] == 'fleet_qwen_disagreement' and result['calls'] == 2
    assert providers[0].calls[0].fleet_choice == 'human'
    assert result['state'] == 'HOLD' and result['action_admissible'] is False


@pytest.mark.parametrize('change', ['case', 'revision', 'policy', 'missing_current'])
def test_wrong_baseline_scope_does_not_submit_models(tmp_path, change):
    receipt = judgment()
    baseline = FleetBaseline.from_assessment(receipt, 'human')
    other = dict(case=FleetBaseline.from_assessment(judgment(case='other'), 'human'),
        revision=FleetBaseline.from_assessment(judgment(revision='other'), 'human'),
        policy=replace(baseline, policy_revision='other'), missing_current=baseline)[change]
    providers = [Provider('qwen'), Provider('glm')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        ConditionalReview(clock=lambda: 101), providers, current=lambda: receipt, baseline=other,
        current_baseline=None if change == 'missing_current' else lambda: other))
    assert result['state'] == 'HOLD' and result['calls'] == 0
    assert all(not p.calls for p in providers)


def test_fleet_choice_change_while_qwen_runs_prevents_glm_call(tmp_path):
    receipt = judgment()
    baseline = FleetBaseline.from_assessment(receipt, 'human')
    current_baseline = [baseline]
    providers = [Provider('qwen', lambda: current_baseline.__setitem__(0,
        FleetBaseline.from_assessment(receipt, 'reobserve'))), Provider('glm')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        ConditionalReview(clock=lambda: 101), providers, current=lambda: receipt,
        baseline=baseline, current_baseline=lambda: current_baseline[0]))
    assert result['reason'] == 'STALE_OR_CHANGED' and result['calls'] == 1
    assert not providers[1].calls


def test_no_fleet_advisory_choice_is_invented_from_assessment(tmp_path):
    receipt = judgment()
    providers = [Provider('qwen'), Provider('glm')]
    result = asyncio.run(run_line_judgment(receipt, DeliberationJournal(tmp_path / 'fleet.db'),
        ConditionalReview(clock=lambda: 101), providers, current=lambda: receipt))
    assert result['calls'] == 1 and providers[0].calls[0].fleet_choice is None
    assert not providers[1].calls


def test_board_forwards_scoped_baseline_for_shadow_comparison(tmp_path):
    from fleet.stuck.board import LineStuckBoard
    board = LineStuckBoard(wall=lambda: 101)
    board.observe([dict(robot_id='pinky', online=True, state_age_s=1,
        state=dict(seq=1, timestamp=datetime.fromtimestamp(100, timezone.utc).isoformat(),
            line_follow=dict(mode='CAMERA_LINE', stuck=dict(stuck_id='lane-1', phase='ASKING'))))])
    baseline = FleetBaseline.from_assessment(board.intervention_assessment('pinky'), 'human')
    result = asyncio.run(board.deliberate('pinky', DeliberationJournal(tmp_path / 'fleet.db'),
        ConditionalReview(clock=lambda: 101), [Provider('qwen'), Provider('glm')],
        baseline=baseline, current_baseline=lambda: baseline))
    assert result['calls'] == 2 and result['review_trigger'] == 'fleet_qwen_disagreement'
    assert result['state'] == 'HOLD' and result['action_admissible'] is False
