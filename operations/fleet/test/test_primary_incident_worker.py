"""Single-primary execution creates its own manifest evidence, never a paired baseline clone."""
import asyncio
from dataclasses import asdict
import hashlib
import json

import pytest

from fleet.incidents.automation.contract import CaseBudget
from fleet.incidents.automation.worker import IncidentCaseWorker
from test_incident_case_worker import make_incident_worker, settled
from test_incident_feedback_export import exporter


async def primary_setup(tmp_path, change=None):
    now, seen, handoffs, log, board, store, old, poll, current = make_incident_worker(tmp_path, change=change)
    await old.aclose()
    profiles = old.profiles[:1]
    current[0] = profiles
    worker = IncidentCaseWorker(store, old.observation, board,
        profiles=profiles, providers=old.providers[:1], admission=old.admission,
        current_profiles=old.current_profiles, human_owned=old.human_owned,
        budget=lambda _: CaseBudget(now[0], now[0] + 30, 2, 2, 0, (('primary', profiles[0].max_calls),)),
        final_handoff=old.final_handoff, clock=old.clock, enabled=True)
    return worker, now, seen, handoffs, store, poll, profiles


def test_primary_only_has_no_normal_calls_and_exports_real_single_role_receipt(tmp_path):
    async def run():
        worker, now, seen, handoffs, store, poll, profiles = await primary_setup(tmp_path)
        worker.feed(poll(normal=True)); await settled(worker)
        assert not seen and not store.active_scopes()
        worker.feed(poll(2)); await settled(worker)
        assert len(seen) == 1 and seen[0][1].profile.role == 'primary'
        scope = store.active_scopes()[0]
        now[0] += 2
        worker.feed(poll(3, normal=True)); await settled(worker)
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id, [asdict(profiles[0])])
        assert exported['schema'] == 'rosy.incident.model_feedback/3'
        assert exported['case']['outcome'] == 'RESOLVED_OBSERVED'
        assert exported['case']['attempts'][0]['model_receipt']['schema'] == 'rosy.incident.model_receipt/3'
        assert exported['case']['calls'] == 1 and not handoffs
        assert scope.profile_sha256 == hashlib.sha256(json.dumps([asdict(profiles[0])], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        await worker.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('change', ['conflict', 'invalid'])
def test_primary_needing_review_hands_off_without_unconfigured_second_call(tmp_path, change):
    async def run():
        worker, _, seen, handoffs, store, poll, profiles = await primary_setup(tmp_path, change)
        worker.feed(poll()); await settled(worker)
        assert len(seen) == 1 and len(handoffs) == 1
        scope, summary = handoffs[0]
        assert summary['reason'] == 'REVIEW_PROVIDER_NOT_CONFIGURED'
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id,
                                       [asdict(profiles[0])], include_handoff=True)
        assert exported['schema'].endswith('/3') and 'handoff' in exported['case']
        assert exported['case']['calls'] == 1 and exported['field_accepted'] is False
        await worker.aclose()
    asyncio.run(run())


def test_actual_primary_export_reaches_recording_failure_and_independent_comparison(tmp_path):
    import importlib.util
    import copy
    import subprocess
    import sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    def load(name, path):
        spec = importlib.util.spec_from_file_location(name, root / path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module
    binder = load('primary_feedback', 'learning/curation/perception/incident_feedback.py')
    compare = load('primary_compare', 'learning/evaluation/decision/operational_comparison.py').compare
    async def run():
        worker, _, seen, handoffs, store, poll, profiles = await primary_setup(tmp_path, 'conflict')
        worker.feed(poll()); await settled(worker)
        scope = handoffs[0][0]
        exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id,
                                       [asdict(profiles[0])], include_handoff=True)
        recording = dict(schema=binder.SCHEMA, matches=[dict(robot_id=scope.subject_id, stuck_id=scope.case_id)], missing_incidents=[])
        analysis = dict(schema='rosy.incident.failure_analysis/1', subject_id=scope.subject_id,
            case_id=scope.case_id, model_feedback_digest=exported['digest'], reviews=[dict(
                category='judgment', source='model', author_id='private-reviewer', at='2026-10-12T00:00:00Z')])
        bound = binder.attach_failure_analysis(recording, exported, analysis)['matches'][0]
        assert bound['model_feedback']['label_state'] == bound['failure_analysis']['label_state'] == 'UNREVIEWED'
        cohort = dict(schema='rosy.incident.operational_cohort/1', domain='line_stuck', training=[], fit=[],
            evaluation=[dict(subject_id=scope.subject_id, case_id=scope.case_id,
                session_id='eval', recording_id='recording', source_sha256='a' * 64)],
            candidates=[dict(strategy='primary', strategy_sha256='b' * 64, profile_sha256=scope.profile_sha256,
                policy_revision=scope.policy_revision, exports=[dict(subject_id=scope.subject_id,
                    case_id=scope.case_id, digest=exported['digest'])])])
        report = compare(cohort, [exported])
        assert report['promotion_state'] == 'HOLD' and 'rule_baseline' in report['missing']
        assert 'primary_baseline' not in report['missing']
        forged_role = copy.deepcopy(exported)
        forged_role['case']['budget']['role_limits'] = []
        forged_role['case']['attempts'][0].update(role='reviewer', model_receipt=None)
        forged_role['digest'] = hashlib.sha256(json.dumps(forged_role['case'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        forged_cohort = copy.deepcopy(cohort)
        forged_cohort['candidates'][0]['exports'][0]['digest'] = forged_role['digest']
        with pytest.raises(ValueError): compare(forged_cohort, [forged_role])
        profile_path = tmp_path / 'profiles.json'; profile_path.write_text(json.dumps([asdict(profiles[0])]))
        export_path = tmp_path / 'export.json'
        command = [sys.executable, str(root / 'tools/incident_model_feedback.py'), str(store.path),
            '--subject', scope.subject_id, '--case', scope.case_id, '--profiles', str(profile_path),
            '--include-handoff', '--out', str(export_path)]
        result = subprocess.run(command, capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(export_path.read_text())['digest'] == exported['digest']
        cohort_path = tmp_path / 'cohort.json'; cohort_path.write_text(json.dumps(cohort))
        report_path = tmp_path / 'comparison.json'
        result = subprocess.run([sys.executable, '-S', str(root / 'learning/evaluation/decision/operational_comparison.py'),
            str(cohort_path), str(export_path), '--out', str(report_path)], capture_output=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(report_path.read_text())['promotion_state'] == 'HOLD'
        cohort['candidates'][0]['strategy'] = 'primary_reviewer'
        with pytest.raises(ValueError): compare(cohort, [exported])
        downgraded = dict(exported, schema='rosy.incident.model_feedback/1')
        with pytest.raises(ValueError): binder.attach_model_feedback(recording, downgraded)
        invalid_scope = copy.deepcopy(exported)
        invalid_scope['case']['scope'] = ['invalid']
        invalid_scope['digest'] = hashlib.sha256(json.dumps(invalid_scope['case'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        with pytest.raises(ValueError): binder.attach_model_feedback(recording, invalid_scope)
        await worker.aclose()
    asyncio.run(run())


def test_single_role_cost_evidence_uses_v3_and_rejects_legacy_downgrade():
    from dataclasses import replace
    from fleet.incidents.automation.ledger.receipt import ModelReceipt, model_receipt, checked_receipt
    from rosy.decision.deliberation import canonical
    from test_incident_model_receipt import fixture
    from test_incident_cost_receipt import evidence
    scope, problem, profiles, bound, checked, attempt = fixture()
    profiles = profiles[:1]
    scope = replace(scope, profile_sha256=hashlib.sha256(canonical([asdict(profiles[0])]).encode()).hexdigest())
    receipt = model_receipt(scope, problem, bound, checked, profiles=profiles, cost_evidence=evidence(problem, bound, checked))
    raw = checked_receipt(scope, attempt, receipt)
    assert raw['schema'] == 'rosy.incident.model_receipt/3'
    assert raw['cost_evidence']['observed_usd_charge'] is None
    with pytest.raises(ValueError):
        checked_receipt(scope, attempt, ModelReceipt(canonical(dict(raw, schema='rosy.incident.model_receipt/2'))))


@pytest.mark.parametrize('fault', ['budget', 'reviewer', 'none'])
def test_generic_store_cannot_export_unbound_single_primary_roles(tmp_path, fault):
    import sqlite3
    from fleet.incidents.automation.store import IncidentCaseStore, CaseScope
    from rosy.decision.deliberation import canonical
    from test_judgment_profiles import profile
    selected = profile()
    manifest = [asdict(selected)]
    scope = CaseScope('pinky', 'case', 'core', hashlib.sha256(canonical(manifest).encode()).hexdigest(), 'policy-1')
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    budget = CaseBudget(100, 130, 2, 0, 0)
    store.begin_case(scope, budget)
    role = 'primary' if fault == 'budget' else 'reviewer' if fault == 'reviewer' else None
    store.reserve(scope, attempt_id='model', input_hash='a' * 64, observation_revision='r1',
                  kind='model', role=role, max_cost_usd=0, worker_id='worker')
    store.mark_submitting(scope, 'model', worker_id='worker')
    store.complete(scope, 'model', worker_id='worker', state='REJECTED', actual_cost_usd=0,
                   summary={'reason': 'MODEL_RESULT_REJECTED'})
    if fault != 'budget':
        altered = asdict(budget); altered['role_limits'] = [['primary', selected.max_calls]]
        with sqlite3.connect(store.path) as connection:
            connection.execute('UPDATE fleet_incident_v2_cases SET budget_json=?', (canonical(altered),))
    with pytest.raises(ValueError): exporter().snapshot(store.path, scope.subject_id, scope.case_id, manifest)


@pytest.mark.parametrize('case', [None, [], 'invalid', True])
def test_shared_primary_contract_rejects_non_object_json(case):
    from rosy.contracts.learning.incident_profiles import validate_primary_roles
    with pytest.raises(ValueError): validate_primary_roles(case)
