import copy
import importlib.util
import json
import hashlib
from pathlib import Path
import sqlite3
import subprocess
import sys
import asyncio
import pytest
from test_operational_comparison import evidence, compare, ROOT
from test_rule_selection import make_loop


def exporter():
    path = ROOT / 'learning/curation/pinky/fleet_rules.py'
    spec = importlib.util.spec_from_file_location('rule_export', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def data(tmp_path):
    loop, source = make_loop(tmp_path / 'rules', autonomous=True)
    source['state']['line_follow']['stuck']['stuck_id'] = 'case'
    asyncio.run(loop.run_once())
    receipt = loop.rule_selections.read()[0]['receipt']
    args = dict(subject_id='pinky', case_id='case', owner_id='core',
                config_sha256=receipt['config_sha256'], policy_revision=receipt['assessment']['policy_revision'],
                start=99, end=102)
    result = exporter().snapshot(loop.rule_selections.path, **args)
    model_path = tmp_path / 'models'
    model_path.mkdir()
    cohort, models = evidence(model_path)
    cohort['schema'] = 'rosy.incident.operational_cohort/2'
    cohort['rules'] = [dict(strategy_sha256='f'*64, config_sha256=args['config_sha256'],
        owner_id='core', policy_revision=args['policy_revision'],
        exports=[dict(subject_id='pinky', case_id='case', digest=result['digest'])])]
    return loop, args, cohort, [*models, result]


def test_actual_rule_export_and_model_cohort_keep_unknowns_and_hold(tmp_path):
    loop, args, cohort, exports = data(tmp_path)
    before = loop.rule_selections.path.read_bytes()
    assert exporter().snapshot(loop.rule_selections.path, **args) == exports[-1]
    report = compare(cohort, exports)
    rule = report['candidates'][-1]
    assert report['state'] == 'HOLD' and report['field_accepted'] is False
    assert rule['strategy'] == 'rule' and rule['case_count'] == 1
    assert rule['selections'] == {'HOLD': 1} and rule['necessities'] == {'INTERVENE': 1}
    assert rule['outcomes'] is None and rule['known_marginal_micros'] is None
    assert rule['model_call_count'] is None and rule['normal_command_count'] is None
    assert 'rule_operational_baseline' in report['missing']
    assert before == loop.rule_selections.path.read_bytes()


@pytest.mark.parametrize('fault', ['digest', 'case', 'config', 'mixed', 'row_id', 'time', 'missing'])
def test_unbound_or_incomplete_rule_evidence_is_rejected(tmp_path, fault):
    _, _, cohort, exports = data(tmp_path)
    result = copy.deepcopy(exports[-1])
    if fault == 'digest': result['digest'] = '0'*64
    elif fault == 'case': result['scope']['case_id'] = 'other'
    elif fault == 'config': result['records'][0]['receipt']['config_sha256'] = '0'*64
    elif fault == 'mixed': result['records'][0]['receipt']['strategy'] = 'MIXED'
    elif fault == 'row_id': result['records'][0]['selection_id'] = True
    elif fault == 'time': result['records'][0]['received_at'] = 200
    else: result['records'] = []
    if fault != 'digest':
        for record in result['records']:
            raw = json.dumps(record['receipt'], sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()
            record['sha256'] = hashlib.sha256(raw).hexdigest()
        raw = json.dumps(dict(scope=result['scope'], records=result['records']),
                         sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        result['digest'] = hashlib.sha256(raw).hexdigest()
        cohort['rules'][0]['exports'][0]['digest'] = result['digest']
    with pytest.raises(ValueError): compare(cohort, [*exports[:-1], result])


def test_export_rejects_database_identity_and_payload_corruption(tmp_path):
    loop, args, _, _ = data(tmp_path)
    with sqlite3.connect(loop.rule_selections.path) as db:
        db.execute("UPDATE fleet_rule_selections SET robot_id='other'")
    with pytest.raises(ValueError): exporter().snapshot(loop.rule_selections.path, **args)


def test_export_and_compare_cli_need_no_fleet_import_and_never_overwrite(tmp_path):
    loop, args, cohort, exports = data(tmp_path)
    output = tmp_path / 'rule.json'
    command = [sys.executable, '-I', '-S', exporter().__file__, str(loop.rule_selections.path), str(output)]
    for key, value in args.items(): command += ['--'+key.replace('_', '-'), str(value)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_bytes()) == exports[-1]
    assert subprocess.run(command, capture_output=True, timeout=15).returncode != 0
    cohort_path = tmp_path / 'cohort.json'
    cohort_path.write_text(json.dumps(cohort), encoding='utf-8')
    model_path = tmp_path / 'model.json'
    model_path.write_text(json.dumps(exports[0]), encoding='utf-8')
    report_path = tmp_path / 'comparison.json'
    command = [sys.executable, '-I', '-S',
               str(ROOT / 'learning/evaluation/decision/operational_comparison.py'),
               str(cohort_path), str(model_path), str(output), '--out', str(report_path)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(report_path.read_bytes()) == compare(cohort, exports)
    assert subprocess.run(command, capture_output=True, timeout=15).returncode != 0


@pytest.mark.parametrize('change', [dict(case_id='x'*513), dict(start=True),
                                  dict(end=float('nan')), dict(end=90000)])
def test_export_rejects_unbounded_scope(tmp_path, change):
    loop, args, _, _ = data(tmp_path)
    with pytest.raises(ValueError):
        exporter().snapshot(loop.rule_selections.path, **{**args, **change})


def test_complete_envelope_and_newline_are_inside_byte_limit(tmp_path):
    loop, args, _, exports = data(tmp_path)
    module = exporter()
    value = exports[-1]
    size = len(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()) + 1
    module.MAX_EXPORT_BYTES = size
    assert module.snapshot(loop.rule_selections.path, **args) == value
    module.MAX_EXPORT_BYTES = size - 1
    with pytest.raises(ValueError, match='RULE_EXPORT_LIMIT'):
        module.snapshot(loop.rule_selections.path, **args)
