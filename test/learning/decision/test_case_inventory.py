"""A frozen journal inventory prevents dropping failed or unknown evaluation cases."""
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'operations/fleet/test'))
from test_incident_feedback_export import fixture, exporter
from test_operational_comparison import evidence


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def inventory_tool(): return module('tools/incident_case_inventory.py', 'case_inventory_producer')


def consumer(): return module('learning/evaluation/decision/operational_comparison.py', 'case_inventory_consumer')


def inventory(store, scope, profiles):
    return inventory_tool().snapshot(store.path, profiles, owner=scope.owner_id, policy=scope.policy_revision,
                                     start=99, end=201)


def test_inventory_reads_unknown_active_and_terminal_cases_without_changing_database(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    before = store.case(scope)
    for case, state in [('failed', 'HOLD'), ('normal-observed', 'NOT_NEEDED')]:
        selected = replace(scope, case_id=case)
        store.begin_case(selected, store_budget())
        store.close_case(selected, state=state, reason='OFFLINE_FIXTURE')
    result = inventory(store, scope, profiles)
    assert [row['scope']['case_id'] for row in result['records']] == ['case', 'failed', 'normal-observed']
    assert result['coverage'] == 'retained_case_rows_only' and result['field_accepted'] is False
    assert result['label_state'] == 'UNREVIEWED' and store.case(scope) == before
    assert 'private-worker' not in json.dumps(result) and str(store.path) not in json.dumps(result)


def store_budget():
    from fleet.incidents.automation.store import CaseBudget
    return CaseBudget(100, 200, 2, 2, .3)


def test_case_omitted_from_cohort_is_detected_by_real_journal_inventory(tmp_path):
    cohort, exports = evidence(tmp_path)
    from fleet.incidents.automation.store import IncidentCaseStore, CaseScope
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    scope = CaseScope(**exports[0]['case']['scope'])
    store.begin_case(replace(scope, case_id='omitted-failure'), store_budget())
    receipt = inventory(store, scope, exports[0]['case']['profiles'])
    with pytest.raises(ValueError, match='INVENTORY_CASE_SET_DIFFERS'):
        consumer().compare_with_inventory(cohort, exports, [receipt], expected_digests=[receipt['digest']])


def test_inventory_matches_export_but_does_not_grant_full_coverage_or_promotion(tmp_path):
    cohort, exports = evidence(tmp_path)
    from fleet.incidents.automation.store import IncidentCaseStore, CaseScope
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    scope = CaseScope(**exports[0]['case']['scope'])
    receipt = inventory(store, scope, exports[0]['case']['profiles'])
    report = consumer().compare_with_inventory(cohort, exports, [receipt], expected_digests=[receipt['digest']])
    assert report['state'] == report['promotion_state'] == 'HOLD' and report['field_accepted'] is False
    assert report['case_inventory']['coverage'] == 'retained_case_rows_only'
    assert report['candidates'][0]['normal_command_count'] is None
    assert 'normal_command_coverage' in report['missing']
    path = tmp_path / 'inventory.json'; path.write_text(json.dumps(receipt))
    cohort_file = tmp_path / 'cohort.json'; cohort_file.write_text(json.dumps(cohort))
    exported = tmp_path / 'case.json'; exported.write_text(json.dumps(exports[0]))
    output = tmp_path / 'report.json'
    run = subprocess.run([sys.executable, str(ROOT / 'learning/evaluation/decision/operational_comparison.py'),
        str(cohort_file), str(exported), '--inventory', str(path), '--inventory-digest', receipt['digest'],
        '--out', str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    assert json.loads(output.read_text()) == report


@pytest.mark.parametrize('fault', ['pin', 'state', 'window', 'duplicate'])
def test_inventory_mutation_or_scope_drift_cannot_bias_comparison(tmp_path, fault):
    cohort, exports = evidence(tmp_path)
    from fleet.incidents.automation.store import IncidentCaseStore, CaseScope
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    scope = CaseScope(**exports[0]['case']['scope'])
    receipt = inventory(store, scope, exports[0]['case']['profiles']); pinned = receipt['digest']
    if fault == 'pin': pinned = 'f' * 64
    elif fault == 'state': receipt['records'][0]['state'] = 'NOT_NEEDED'
    elif fault == 'window': receipt['scope']['start'] = 101
    else: receipt['records'].append(receipt['records'][0])
    if fault != 'pin': receipt['digest'] = consumer().digest(dict(scope=receipt['scope'], records=receipt['records']))
    with pytest.raises(ValueError):
        consumer().compare_with_inventory(cohort, exports, [receipt], expected_digests=[pinned])


def test_two_valid_snapshots_of_same_case_cannot_overwrite_inventory_binding(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    old = exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles)
    store.complete(scope, 'attempt', worker_id='private-worker', state='UNKNOWN',
                   actual_cost_usd=None, summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    current = exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles)
    candidate = dict(strategy='primary_reviewer', profile_sha256=scope.profile_sha256,
                     policy_revision=scope.policy_revision)
    cohort = dict(schema='rosy.incident.operational_cohort/1', domain='line_follow', training=[], fit=[],
        evaluation=[dict(subject_id=scope.subject_id, case_id=scope.case_id,
                         session_id='eval', recording_id='eval', source_sha256='d' * 64)],
        candidates=[dict(**candidate, strategy_sha256=label * 64,
            exports=[dict(subject_id=scope.subject_id, case_id=scope.case_id, digest=exported['digest'])])
            for label, exported in [('e', old), ('f', current)]])
    assert len(consumer().compare(cohort, [old, current])['candidates']) == 2
    receipt = inventory(store, scope, profiles)
    with pytest.raises(ValueError, match='AMBIGUOUS_INVENTORY_CASE_EXPORT'):
        consumer().compare_with_inventory(cohort, [old, current], [receipt], expected_digests=[receipt['digest']])


def test_inventory_producer_cli_uses_readonly_source_and_exclusive_output(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    frozen = tmp_path / 'profiles.json'; frozen.write_text(json.dumps(profiles))
    output = tmp_path / 'inventory.json'
    command = [sys.executable, str(ROOT / 'tools/incident_case_inventory.py'), str(store.path),
        '--profiles', str(frozen), '--owner', scope.owner_id, '--policy', scope.policy_revision,
        '--start', '99', '--end', '201', '--out', str(output)]
    before = store.case(scope)
    run = subprocess.run(command, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    raw = output.read_bytes(); data = json.loads(raw)
    assert len(raw) <= 1024 * 1024 and raw.endswith(b'\n') and not raw.endswith(b'\r\n')
    assert data['digest'] == run.stdout.strip() and store.case(scope) == before
    assert subprocess.run(command, capture_output=True).returncode == 1 and output.read_bytes() == raw


def test_window_is_end_exclusive_and_other_owner_policy_profile_are_excluded(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    for selected in (replace(scope, case_id='owner', owner_id='arm'),
                     replace(scope, case_id='policy', policy_revision='other'),
                     replace(scope, case_id='profile', profile_sha256='f' * 64)):
        store.begin_case(selected, store_budget())
    from fleet.incidents.automation.store import CaseBudget
    store.begin_case(replace(scope, case_id='at-end'), CaseBudget(201, 231, 0, 0, 0))
    assert [row['scope']['case_id'] for row in inventory(store, scope, profiles)['records']] == ['case']


def test_resealed_metadata_still_must_match_actual_export(tmp_path):
    cohort, exports = evidence(tmp_path)
    from fleet.incidents.automation.store import IncidentCaseStore, CaseScope
    store = IncidentCaseStore(tmp_path / 'fleet.db', clock=lambda: 101)
    scope = CaseScope(**exports[0]['case']['scope'])
    receipt = inventory(store, scope, exports[0]['case']['profiles'])
    receipt['records'][0]['reason'] = 'OTHER_REASON'
    receipt['digest'] = consumer().digest(dict(scope=receipt['scope'], records=receipt['records']))
    with pytest.raises(ValueError, match='INVENTORY_CASE_STATE_DIFFERS'):
        consumer().compare_with_inventory(cohort, exports, [receipt], expected_digests=[receipt['digest']])


def test_oversized_population_is_rejected_instead_of_truncated(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    from dataclasses import asdict
    from rosy.decision.deliberation import canonical
    with store._transaction() as db:
        db.executemany('INSERT INTO fleet_incident_v2_cases VALUES (?,?,?,?,?,?,?,?,?,?)',
            [(scope.subject_id, f'case-{index}', canonical(asdict(replace(scope, case_id=f'case-{index}'))),
              canonical(asdict(store_budget())), 'ACTIVE', 'OPEN', 0, 0, 0, 0) for index in range(1000)])
    with pytest.raises(ValueError, match='INVENTORY_CASE_LIMIT'): inventory(store, scope, profiles)
