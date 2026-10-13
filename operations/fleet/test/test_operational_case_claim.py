"""Real SQLite operating epochs and single-case submissions; no field acceptance."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, replace
import hashlib
import hmac
import json

import httpx
import pytest

from fleet.incidents.automation.store import CaseBudget, CaseScope, IncidentCaseStore
from fleet.incidents.automation.ledger.receipt import model_receipt
from fleet.incidents.automation.recovery_candidates import RecoveryCandidates
from fleet.stuck.reports import LineStuckAnswerLog
from rosy.contracts.learning import seal
from rosy.contracts.learning.incident_operation import APPROVE, REVOKE
from rosy.decision.deliberation import canonical
from rosy.decision.deliberation.judgment import judgment
from rosy.decision.deliberation.profiles import bind_profile
from test_judgment_profiles import adapter, profile
from test_model_recovery_candidates import recovery_problem, recovery_payload

KEY = b'operating-state-source-fixture-key'
TRUST = {'reviewer': {'key': KEY, 'kinds': {APPROVE, REVOKE}}}


def test_candidate_import_keeps_actual_class_identity():
    from fleet.incidents.automation.operating.candidates import RecoveryCandidates as moved
    assert moved is RecoveryCandidates


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def opened(tmp_path, *, generation='g1'):
    from fleet.incidents.automation.operating.state import OperationalState
    now = [101.0]
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: now[0])
    log = LineStuckAnswerLog(store.path)
    p = replace(recovery_problem(), observed_at=100, generation=generation)
    selected = profile(calibration_revision='cal-1')
    bound = bind_profile(p, selected, adapter(), required_modalities=('text',))
    checked = judgment(p, bound, recovery_payload(p))
    scope = CaseScope(p.subject_id, p.case_id, 'core', digest([asdict(selected)]), 'policy-1')
    store.begin_case(scope, CaseBudget(100, 130, 2, 2, 0), worker_id='worker')
    store.reserve(scope, attempt_id='model-1', input_hash=p.digest, observation_revision=p.generation,
        kind='model', max_cost_usd=0, worker_id='worker', role='primary')
    store.mark_submitting(scope, 'model-1', worker_id='worker')
    store.complete(scope, 'model-1', worker_id='worker', state='COMPLETED', actual_cost_usd=0,
        summary={'reason': 'MODEL_CHECKED'}, model_receipt=model_receipt(scope, p, bound, checked, profiles=(selected,)))
    RecoveryCandidates(store).propose(scope, 'model-1', worker_id='worker')
    report = dict(schema='rosy.incident.operational_acceptance/1', state='PASS_FOR_OPERATION',
                  missing=[], field_accepted=True, truth_admitted=True)
    binding = dict(profile_set_sha256=scope.profile_sha256, full_profile_sha256=digest(asdict(selected)),
        model_revision=selected.model_revision, calibration_sha256='c' * 64, domain='line_follow',
        action='BACK_AND_RETRY', action_contract='rosy.line_stuck.conditional_back/1',
        policy_revision=scope.policy_revision, installation_sha256='d' * 64,
        evaluation_sha256=digest(report), coverage_sha256='f' * 64,
        limits_sha256='1' * 64, truth_sha256='2' * 64, evaluation_state='REVIEWED_FOR_OPERATION')
    proof = dict(binding=binding, report=report, profiles=[asdict(selected)], profile=asdict(selected),
                 approved_calibrations={'cal-1': 'c' * 64})
    trust = [TRUST]
    def evidence(grant_id):
        if grant_id != 'line-back': raise ValueError('UNREGISTERED_GRANT')
        return proof
    state = OperationalState(store, trusted=lambda: trust[0], evidence=evidence)
    return now, store, log, scope, state, proof, trust


def signed(proof, epoch, kind=APPROVE):
    payload = seal(dict(schema='rosy.incident.operation/1', kind=kind, binding=proof['binding'],
                        expected_epoch=epoch, valid_from_s=100, expires_s=130))
    wire = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()
    return dict(principal='reviewer', payload=payload, signature=hmac.new(KEY, wire, hashlib.sha256).hexdigest())


def claim(state, scope, **kwargs):
    return state.claim_model(scope, 'line-back', 'model-1', expected_epoch=kwargs.get('epoch', 1),
        generation=kwargs.get('generation', 'g1'), guard=kwargs.get('guard', lambda conn: True))


def test_real_epoch_cas_restart_and_signed_revoke(tmp_path):
    _, store, _, scope, state, proof, trust = opened(tmp_path)
    assert state.epoch() == 0
    receipt = signed(proof, 0)
    state.apply('line-back', receipt)
    assert state.epoch() == 1 and state.grant('line-back')['receipt'] == receipt
    with pytest.raises(ValueError): state.apply('line-back', receipt)
    from fleet.incidents.automation.operating.state import OperationalState
    reopened = OperationalState(store, trusted=lambda: trust[0], evidence=lambda _: proof)
    assert reopened.grant('line-back')['epoch'] == 1
    reopened.apply('line-back', signed(proof, 1, REVOKE))
    assert reopened.epoch() == 2
    with pytest.raises(ValueError): claim(reopened, scope)


@pytest.mark.parametrize('changed', ['hold', 'report', 'calibration', 'profiles', 'trust'])
def test_current_original_evidence_and_trust_are_rechecked(tmp_path, changed):
    _, _, _, scope, state, proof, trust = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    if changed == 'hold': proof['report']['state'] = 'HOLD'
    if changed == 'report': proof['report']['extra'] = 'changed'
    if changed == 'calibration': proof['approved_calibrations'] = {}
    if changed == 'profiles': proof['profiles'][0]['model_revision'] = 'changed'
    if changed == 'trust': trust[0] = {}
    with pytest.raises(ValueError): claim(state, scope)
    assert state.submission(scope.subject_id, scope.case_id) is None


def test_signed_reviewed_metadata_cannot_import_an_original_hold_report(tmp_path):
    _, _, _, _, state, proof, _ = opened(tmp_path)
    proof['report']['state'] = 'HOLD'
    proof['binding']['evaluation_sha256'] = digest(proof['report'])
    with pytest.raises(ValueError): state.apply('line-back', signed(proof, 0))
    assert state.epoch() == 0


def test_single_case_claim_is_durable_and_does_not_reset_model_budget(tmp_path):
    _, store, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0)); before = store.case(scope)
    record = claim(state, scope)
    assert record['state'] == 'SUBMITTING' and record['actor'] == 'model'
    assert record['expected_stuck'] == {'phase': 'ASKING', 'attempts': 0}
    assert store.case(scope) == before
    with pytest.raises(ValueError): claim(state, scope)
    state.finish(scope, state='UNKNOWN', reply={'code': 'DISCONNECTED'})
    with pytest.raises(ValueError): claim(state, scope)


def test_two_model_consumers_have_one_claim(tmp_path):
    _, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    def attempt(_):
        try: return claim(state, scope)['state']
        except ValueError: return 'REFUSED'
    with ThreadPoolExecutor(2) as pool: results = list(pool.map(attempt, range(2)))
    assert sorted(results) == ['REFUSED', 'SUBMITTING']


@pytest.mark.parametrize('fault', ['epoch', 'generation', 'scope', 'expired', 'guard'])
def test_claim_refuses_changed_context_without_consuming_slot(tmp_path, fault):
    now, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0)); options = {}
    if fault == 'epoch': options['epoch'] = 0
    if fault == 'generation': options['generation'] = 'new'
    if fault == 'scope': scope = replace(scope, policy_revision='foreign')
    if fault == 'expired': now[0] = 130
    if fault == 'guard': options['guard'] = lambda conn: False
    with pytest.raises(ValueError): claim(state, scope, **options)
    assert state.submission(scope.subject_id, scope.case_id) is None


@pytest.mark.parametrize('legacy', ['FLEET_STUCK_DISPATCH_PENDING', 'STUCK_DECISION_OUTCOME_UNKNOWN', 'accepted'])
def test_existing_legacy_submission_blocks_new_model_claim(tmp_path, legacy):
    _, _, log, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    log.append(dict(at='1970-01-01T00:01:41+00:00', audit_id=None, outcome=None, message=None,
        robot_id=scope.subject_id, stuck_id=scope.case_id, decision='BACK_AND_RETRY',
        principal_id='fleet-resolver', accepted=True if legacy == 'accepted' else None,
        code=None if legacy == 'accepted' else legacy))
    with pytest.raises(ValueError): claim(state, scope)


def test_rule_and_model_share_the_same_case_slot(tmp_path):
    _, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    state.claim_rule(scope.subject_id, scope.case_id, generation='g1', decision='BACK_AND_RETRY', guard=lambda conn: True)
    with pytest.raises(ValueError): claim(state, scope)


def test_revocation_after_claim_preserves_unknown_and_core_reply_fact(tmp_path):
    _, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0)); claim(state, scope)
    state.apply('line-back', signed(proof, 1, REVOKE))
    record = state.finish(scope, state='ACK', reply={'outcome': 'back'})
    assert record['state'] == 'UNKNOWN' and record['reply'] == {'outcome': 'back'}
    with pytest.raises(ValueError): claim(state, scope, epoch=2)


@pytest.mark.parametrize('during_get', ['unchanged', 'revoke', 'hold', 'unsupported'])
def test_actual_http_client_claims_after_get_and_before_one_post(tmp_path, during_get):
    from fleet.swarm.transport import HttpRobotClient, RobotApiError
    from fleet.swarm.robots import RobotEndpoint
    _, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    calls = []
    def handler(request):
        calls.append(request.method)
        if request.method == 'GET':
            assert state.submission(scope.subject_id, scope.case_id) is None
            if during_get == 'revoke': state.apply('line-back', signed(proof, 1, REVOKE))
            if during_get == 'hold': proof['report']['state'] = 'HOLD'
            return httpx.Response(200, json={'stuck': {'conditional_back': during_get != 'unsupported'}})
        record = state.submission(scope.subject_id, scope.case_id)
        assert record['state'] == 'SUBMITTING'
        assert json.loads(request.content)['expected_stuck'] == record['expected_stuck']
        return httpx.Response(200, json={'outcome': 'back'})
    async def run():
        async with httpx.AsyncClient(base_url='http://source-fixture', transport=httpx.MockTransport(handler)) as http:
            client = HttpRobotClient(RobotEndpoint(scope.subject_id, 'http://source-fixture', 'fake'), http=http)
            async def guard():
                claim(state, scope)
                return True
            invoke = client.line_stuck_decision(scope.case_id, 'BACK_AND_RETRY',
                expected_stuck={'phase': 'ASKING', 'attempts': 0}, before_submit=guard)
            if during_get == 'unchanged':
                reply = await invoke
                assert state.finish(scope, state='ACK', reply=reply)['state'] == 'ACK'
            else:
                with pytest.raises((ValueError, RobotApiError)): await invoke
                assert state.submission(scope.subject_id, scope.case_id) is None
    asyncio.run(run())
    assert calls == (['GET', 'POST'] if during_get == 'unchanged' else ['GET'])


def test_revoke_remains_possible_when_original_evidence_expires_or_holds(tmp_path):
    now, _, _, _, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    proof['report']['state'] = 'HOLD'; now[0] = 131
    assert state.apply('line-back', signed(proof, 1, REVOKE))['epoch'] == 2


def test_final_guard_cannot_replace_current_owner_evidence(tmp_path):
    _, _, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    def guard(conn):
        proof['report']['state'] = 'HOLD'
        return True
    with pytest.raises(ValueError): claim(state, scope, guard=guard)
    assert state.submission(scope.subject_id, scope.case_id) is None


@pytest.mark.parametrize('change', ['deadline', 'hold'])
def test_final_guard_cannot_expire_or_close_the_case(tmp_path, change):
    now, store, _, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    with store._transaction() as conn:
        budget = json.loads(conn.execute('SELECT budget_json FROM fleet_incident_v2_cases').fetchone()[0])
        budget['deadline'] = 110
        conn.execute('UPDATE fleet_incident_v2_cases SET budget_json=?', (canonical(budget),))
    def guard(conn):
        if change == 'deadline': now[0] = 111
        else: conn.execute("UPDATE fleet_incident_v2_cases SET state='HOLD'")
        return True
    with pytest.raises(ValueError): claim(state, scope, guard=guard)
    assert state.submission(scope.subject_id, scope.case_id) is None


def test_rule_terminal_receipt_preserves_unknown_and_never_releases_slot(tmp_path):
    _, _, _, scope, state, _, _ = opened(tmp_path)
    state.claim_rule(scope.subject_id, scope.case_id, generation='g1', decision='BACK_AND_RETRY', guard=lambda _: True)
    with pytest.raises(ValueError):
        state.finish_rule(scope.subject_id, scope.case_id, generation='foreign', state='ACK', reply={})
    assert state.finish_rule(scope.subject_id, scope.case_id, generation='g1', state='UNKNOWN', reply={})['state'] == 'UNKNOWN'
    assert state.finish_rule(scope.subject_id, scope.case_id, generation='g1', state='ACK', reply={'outcome': 'back'})['state'] == 'UNKNOWN'
    with pytest.raises(ValueError):
        state.claim_rule(scope.subject_id, scope.case_id, generation='g1', decision='RESUME', guard=lambda _: True)


@pytest.mark.parametrize('kind', [APPROVE, REVOKE])
def test_history_resealed_with_bad_signature_is_not_an_authenticated_epoch(tmp_path, kind):
    _, store, _, _, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    if kind == REVOKE: state.apply('line-back', signed(proof, 1, REVOKE))
    with store._transaction() as conn:
        event = json.loads(conn.execute('SELECT body FROM fleet_operation_events ORDER BY epoch DESC LIMIT 1').fetchone()[0])
        event['receipt']['signature'] = 'f' * 64
        conn.execute('UPDATE fleet_operation_events SET body=? WHERE epoch=?', (canonical(seal(event)), event['epoch']))
    with pytest.raises(ValueError): state.epoch()


def test_model_claim_and_existing_pending_audit_roll_back_together(tmp_path):
    _, store, log, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    def rejected_audit(conn):
        log.append(dict(at='1970-01-01T00:01:41+00:00', audit_id=None, robot_id=scope.subject_id,
            stuck_id=scope.case_id, decision='BACK_AND_RETRY', principal_id='fleet-resolver',
            accepted=None, outcome=None, code='FLEET_STUCK_DISPATCH_PENDING', message=None), connection=conn)
        return False
    with pytest.raises(ValueError):
        state.claim_model(scope, 'line-back', 'model-1', expected_epoch=1, generation='g1',
            guard=lambda _: True, on_claim=rejected_audit)
    assert state.submission(scope.subject_id, scope.case_id) is None
    with store._transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_line_stuck_answers').fetchone()[0] == 0


def test_board_transaction_pending_is_not_published_before_commit(tmp_path):
    from fleet.stuck.board import LineStuckBoard
    _, store, log, scope, state, proof, _ = opened(tmp_path)
    state.apply('line-back', signed(proof, 0))
    board = LineStuckBoard(log=log)
    def expired_audit(conn):
        board.record(robot_id=scope.subject_id, stuck_id=scope.case_id, decision='BACK_AND_RETRY',
            principal_id='fleet-resolver', accepted=None, code='FLEET_STUCK_DISPATCH_PENDING',
            durable=True, connection=conn)
        assert board.answers() == []
        proof['report']['state'] = 'HOLD'
        return True
    with pytest.raises(ValueError):
        state.claim_model(scope, 'line-back', 'model-1', expected_epoch=1, generation='g1',
            guard=lambda _: True, on_claim=expired_audit)
    assert board.answers() == [] and state.submission(scope.subject_id, scope.case_id) is None
    with store._transaction() as conn:
        assert conn.execute('SELECT COUNT(*) FROM fleet_line_stuck_answers').fetchone()[0] == 0
