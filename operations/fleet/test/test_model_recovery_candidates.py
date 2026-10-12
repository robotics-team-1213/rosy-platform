"""D-722 model proposals are bound to recorded evidence, never dispatch authority."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from fleet.incidents.automation.store import CaseBudget, CaseScope, IncidentCaseStore
from fleet.incidents.automation.ledger.receipt import model_receipt
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import judgment, judgment_schema
from test_judgment_profiles import problem, profile
from test_model_judgment import bound, payload


def recovery_context():
    return dict(phase='ASKING', attempts=0, max_attempts=2, local_enabled=True, cause='lane_lost')


def recovery_problem():
    return replace(problem(), choices=('human', 'reobserve', 'back_and_retry'),
                   facts_json=canonical(dict(state='blocked', recovery=recovery_context())))


def recovery_payload(p):
    raw = payload(p)
    raw.update(verdict='candidate', alternatives=[
        dict(choice=c, probability=.98 if c == 'back_and_retry' else .01) for c in p.choices],
        next_step=dict(tool_name='propose_lane_back', arguments={'rationale': 'Recheck bounded recovery'},
                       evidence_ids=list(p.evidence_ids)))
    raw['evidence_ids'] = list(p.evidence_ids)
    raw['success_check'].update(evidence_ids=list(p.evidence_ids), expected_facts={'state': 'normal'})
    return raw


def setup(tmp_path, *, terminal='COMPLETED', trace=True):
    p, selected = recovery_problem(), profile()
    b = bound(p)
    checked = judgment(p, b, recovery_payload(p))
    scope = CaseScope(p.subject_id, p.case_id, 'core',
        hashlib.sha256(canonical([asdict(selected)]).encode()).hexdigest(), 'policy-1')
    now = [101.0]
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: now[0])
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 0), worker_id='worker')
    store.reserve(scope, attempt_id='model-1', input_hash=p.digest, observation_revision=p.generation,
                  kind='model', max_cost_usd=0, worker_id='worker', role='primary')
    store.mark_submitting(scope, 'model-1', worker_id='worker')
    store.complete(scope, 'model-1', worker_id='worker', state=terminal,
        actual_cost_usd=0, summary={'reason': 'MODEL_CHECKED'},
        model_receipt=model_receipt(scope, p, b, checked, profiles=(selected,)) if trace else None)
    from fleet.incidents.automation.execution.recovery_candidates import RecoveryCandidates
    return now, store, scope, RecoveryCandidates(store)


def test_candidate_persists_without_charging_or_claiming_execution(tmp_path):
    _, store, scope, journal = setup(tmp_path)
    before = store.case(scope)
    candidate = journal.propose(scope, 'model-1', worker_id='worker')
    assert candidate['state'] == 'RECORDED' and candidate['action_admissible'] is False
    assert candidate['action'] == 'BACK_AND_RETRY'
    assert candidate['expected_stuck'] == {'phase': 'ASKING', 'attempts': 0}
    assert candidate['input_hash'] == recovery_problem().digest
    assert store.case(scope) == before
    assert journal.propose(scope, 'model-1', worker_id='worker') == candidate
    from fleet.incidents.automation.execution.recovery_candidates import RecoveryCandidates
    reopened = RecoveryCandidates(IncidentCaseStore(store.path, clock=lambda: 101))
    assert reopened.candidates(scope) == (candidate,)


def test_concurrent_duplicate_candidates_have_one_durable_record(tmp_path):
    _, _, scope, journal = setup(tmp_path)
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: journal.propose(scope, 'model-1', worker_id='worker'), range(2)))
    assert results[0] == results[1] and journal.candidates(scope) == (results[0],)


@pytest.mark.parametrize('terminal,trace', [('UNKNOWN', True), ('REJECTED', True), ('COMPLETED', False)])
def test_noncompleted_or_untraced_model_cannot_propose(tmp_path, terminal, trace):
    _, _, scope, journal = setup(tmp_path, terminal=terminal, trace=trace)
    with pytest.raises(ValueError): journal.propose(scope, 'model-1', worker_id='worker')
    assert journal.candidates(scope) == ()


@pytest.mark.parametrize('changed', ['worker', 'profile', 'owner', 'policy', 'expired', 'held', 'tampered'])
def test_candidate_rechecks_full_scope_and_recorded_source(tmp_path, changed):
    now, store, scope, journal = setup(tmp_path)
    worker = 'worker'
    if changed == 'worker': worker = 'foreign'
    if changed == 'profile': scope = replace(scope, profile_sha256='a' * 64)
    if changed == 'owner': scope = replace(scope, owner_id='foreign')
    if changed == 'policy': scope = replace(scope, policy_revision='foreign')
    if changed == 'expired': now[0] = 130
    if changed == 'held': store.close_case(scope, state='HOLD', reason='INCIDENT_HUMAN_OWNED')
    if changed == 'tampered':
        with store._transaction() as conn:
            saved = conn.execute('SELECT receipt_json FROM fleet_incident_v2_model_receipts').fetchone()[0]
            raw = json.loads(saved); raw['judgment']['input_hash'] = 'a' * 64
            conn.execute('UPDATE fleet_incident_v2_model_receipts SET receipt_json=?', (canonical(raw),))
    with pytest.raises(ValueError): journal.propose(scope, 'model-1', worker_id=worker)


@pytest.mark.parametrize('argument', ['speed', 'distance', 'robot_id', 'url', 'token'])
def test_model_cannot_supply_physical_parameters(argument):
    p = recovery_problem(); raw = recovery_payload(p)
    raw['next_step']['arguments'][argument] = 'untrusted'
    with pytest.raises(ValueError): judgment(p, bound(p), raw)


def test_back_tool_is_not_exposed_to_existing_read_only_problem():
    p = problem()
    schema = judgment_schema(p, bound(p))
    assert 'propose_lane_back' not in canonical(schema)
    changed = recovery_payload(recovery_problem())
    changed.update(input_hash=p.digest, generation=p.generation)
    changed['alternatives'] = payload(p)['alternatives']
    with pytest.raises(ValueError): judgment(p, bound(p), changed)


@pytest.mark.parametrize('changed', ['scope', 'action', 'expected_stuck', 'candidate_id', 'input_hash', 'action_admissible', 'source'])
def test_candidate_read_revalidates_payload_and_completed_source(tmp_path, changed):
    _, store, scope, journal = setup(tmp_path)
    candidate = journal.propose(scope, 'model-1', worker_id='worker')
    with store._transaction() as conn:
        if changed == 'source':
            conn.execute("UPDATE fleet_incident_v2_attempts SET state='UNKNOWN'")
        else:
            candidate[changed] = True if changed == 'action_admissible' else 'foreign'
            conn.execute('UPDATE fleet_incident_v2_recovery_candidates SET payload_json=?', (canonical(candidate),))
    with pytest.raises(ValueError): journal.candidates(scope)


def test_closed_candidate_is_historical_and_non_executable(tmp_path):
    _, store, scope, journal = setup(tmp_path)
    candidate = journal.propose(scope, 'model-1', worker_id='worker')
    store.close_case(scope, state='HOLD', reason='INCIDENT_HUMAN_OWNED')
    assert journal.candidates(scope) == (candidate,)
    assert candidate['action_admissible'] is False


@pytest.mark.parametrize('seq,stamp', [(2, 'stamp-1'), (1, 'stamp-2'), (True, 'stamp-1')])
def test_recovery_context_requires_exact_assessment_revision(seq, stamp):
    from fleet.incidents.automation.execution.recovery_candidates import observed_recovery
    snapshot = {'robots': [dict(robot_id='pinky', online=True, state=dict(seq=seq, timestamp=stamp,
        line_follow={'stuck': dict(stuck_id='lane-1', **recovery_context())}))]}
    assert observed_recovery(snapshot, 'pinky', 'lane-1', 'core:1:stamp-1') is None


def test_recovery_context_accepts_matching_assessment_revision():
    from fleet.incidents.automation.execution.recovery_candidates import observed_recovery
    snapshot = {'robots': [dict(robot_id='pinky', online=True, state=dict(seq=1, timestamp='stamp-1',
        line_follow={'stuck': dict(stuck_id='lane-1', **recovery_context())}))]}
    assert observed_recovery(snapshot, 'pinky', 'lane-1', 'core:1:stamp-1') == recovery_context()


def test_opt_in_worker_records_model_candidate_without_robot_dispatch(tmp_path):
    from fleet.incidents.automation.worker import IncidentCaseWorker
    from test_incident_case_worker import make_incident_worker, settled
    async def run():
        now, seen, handoffs, _, board, store, old, poll, current = make_incident_worker(tmp_path)
        await old.aclose()
        providers = []
        for source in old.providers:
            async def call(p, b, prior, remaining, **kw):
                seen.append((p, b, prior))
                return recovery_payload(p), 0
            call.profile, call.adapter = source.profile, source.adapter
            providers.append(call)
        worker = IncidentCaseWorker(store, old.observation, board, profiles=old.profiles,
            providers=tuple(providers), admission=old.admission, current_profiles=lambda: current[0],
            human_owned=old.human_owned, budget=old.budget, final_handoff=old.final_handoff,
            clock=lambda: now[0], enabled=True, recovery_enabled=True)
        snapshot = poll()
        snapshot['robots'][0]['state']['line_follow']['stuck'].update(recovery_context())
        snapshot['robots'][0]['state']['line_follow']['stuck']['stuck_id'] = 'lane-1'
        board.observe(snapshot['robots']); board.flush()
        worker.feed(snapshot); await settled(worker)
        scope = store.active_scopes()[0]
        assert len(worker.recovery_candidates.candidates(scope)) == 1 and handoffs == []
        assert all('back_and_retry' in p.choices for p, _, _ in seen)
        calls = store.case(scope)['calls']
        worker.feed(snapshot); await settled(worker)
        assert store.case(scope)['calls'] == calls
        await worker.aclose()
    asyncio.run(run())
