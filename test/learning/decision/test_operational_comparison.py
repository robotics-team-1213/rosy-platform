"""Producer-bound cohort comparison cannot promote unreviewed operational evidence."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'operations/fleet/test'))
from test_incident_feedback_export import fixture, exporter


def compare(cohort, exports):
    path = ROOT / 'learning/evaluation/decision/operational_comparison.py'
    assert path.exists(), 'operational comparison consumer missing'
    spec = importlib.util.spec_from_file_location('operational_comparison', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.compare(cohort, exports)


def evidence(tmp_path):
    store, scope, profiles = fixture(tmp_path)
    store.complete(scope, 'attempt', worker_id='private-worker', state='UNKNOWN',
                   actual_cost_usd=None, summary={'reason': 'PROVIDER_OUTCOME_UNKNOWN'})
    exported = exporter().snapshot(store.path, scope.subject_id, scope.case_id, profiles)
    lineage = dict(session_id='session-eval', recording_id='recording-eval', source_sha256='d' * 64)
    cohort = dict(schema='rosy.incident.operational_cohort/1', domain='line_stuck', training=[], fit=[],
        evaluation=[dict(subject_id=scope.subject_id, case_id=scope.case_id, **lineage)],
        candidates=[dict(strategy='primary_reviewer', strategy_sha256='e' * 64,
            profile_sha256=scope.profile_sha256, policy_revision=scope.policy_revision,
            exports=[dict(subject_id=scope.subject_id, case_id=scope.case_id, digest=exported['digest'])])])
    return cohort, [exported]


def test_actual_unknown_export_preserves_liability_and_missing_evidence(tmp_path):
    cohort, exports = evidence(tmp_path)
    before = copy.deepcopy((cohort, exports))
    report = compare(cohort, exports)
    row = report['candidates'][0]
    assert report['state'] == report['promotion_state'] == 'HOLD'
    assert report['field_accepted'] is False and report['truth_admitted'] is False
    assert row['case_count'] == 1 and row['outcomes'] == {'UNRESOLVED': 1}
    assert row['known_marginal_micros'] == 0 and row['reserved_liability_micros'] == 100000
    assert row['unknown_cost_attempts'] == 1 and row['observed_invoice_micros'] is None
    assert row['normal_command_count'] is None and row['recurrence_count'] is None
    assert {'rule_baseline', 'primary_baseline', 'independent_truth', 'acceptance_limits'} <= set(report['missing'])
    assert before == (cohort, exports)


@pytest.mark.parametrize('fault', ['session_leak', 'recording_leak', 'hash_leak', 'duplicate',
                                  'digest', 'policy', 'profile', 'extra_export', 'rule_masquerade'])
def test_changed_scope_lineage_or_strategy_is_rejected(tmp_path, fault):
    cohort, exports = evidence(tmp_path)
    lineage = cohort['evaluation'][0]
    if fault.endswith('_leak'):
        field = dict(session_leak='session_id', recording_leak='recording_id', hash_leak='source_sha256')[fault]
        cohort['training'] = [dict(session_id='training', recording_id='training', source_sha256='f' * 64)]
        cohort['training'][0][field] = lineage[field]
    elif fault == 'duplicate': cohort['evaluation'].append(copy.deepcopy(lineage))
    elif fault == 'digest': exports[0]['case']['spent_micros'] = 1
    elif fault == 'policy': cohort['candidates'][0]['policy_revision'] = 'changed'
    elif fault == 'profile': cohort['candidates'][0]['profile_sha256'] = 'f' * 64
    elif fault == 'extra_export': exports.append(copy.deepcopy(exports[0]))
    else: cohort['candidates'][0]['strategy'] = 'rule'
    with pytest.raises(ValueError): compare(cohort, exports)


def test_missing_case_export_is_rejected_not_zero_filled(tmp_path):
    cohort, exports = evidence(tmp_path)
    with pytest.raises(ValueError): compare(cohort, [])


def test_closed_report_contains_no_provider_or_person_text(tmp_path):
    cohort, exports = evidence(tmp_path)
    report = compare(cohort, exports)
    assert 'private-' not in json.dumps(report)
    assert 'profiles' not in report['candidates'][0]
