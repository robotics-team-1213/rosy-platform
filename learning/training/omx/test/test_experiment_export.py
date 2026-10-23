"""Registered native exports retain production review and immutable source baselines."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import uuid

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_native_cycle import module, splits
from test_experiment_native import bimanual, capture


@pytest.fixture
def prepared(capture, tmp_path):
    import experiment_export as export
    _, receipt, profile, readers = capture
    root = tmp_path / 'prepared'
    (root / 'meta').mkdir(parents=True)
    (root / 'data').mkdir()
    (root / 'meta/info.json').write_text(json.dumps(readers['train'].meta.info))
    (root / 'data/part.parquet').write_bytes(b'native fixture bytes')
    report = copy.deepcopy(receipt['source'])
    report['files'] = export.pipeline.native.dataset_files(root)
    report['capture_provenance']['files'] = report['files']
    values = {'intake-receipt.json': {'reader_verified': True}, 'inspection.json': report,
              'capture.json': report['capture_provenance'], 'environment.json': {},
              'decisions.json': receipt['decisions']}
    for name, value in values.items():
        (root / name).write_text(json.dumps(value))
    row = dict(id=uuid.uuid4().hex, kind='omx', path=str(root), name='Recorded preparation')
    body = dict(prepared_id=row['id'], name='Prepared export', profile=profile,
                request_id=str(uuid.uuid4()))
    return export, root, row, body


def test_prepare_pins_only_registered_source_and_preserves_exact_profile(prepared):
    export, root, row, body = prepared
    request, fields = export.prepare_export(body, row)
    assert set(request) == {'schema', 'prepared_root', 'prepared_files', 'profile'}
    assert request['schema'] == 'rosy.omx.export-request/1'
    assert request['prepared_root'] == str(root) and request['profile'] == body['profile']
    assert set(request['prepared_files']) == set(export.pipeline.PREPARED_FILES)
    for name, digest in request['prepared_files'].items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert fields == dict(prepared_id=row['id'], name=body['name'], source='reviewed_demonstration',
                          method='act', execution_mode='native_export')


def test_export_admission_accepts_exact_additional_native_camera(prepared):
    export, root, row, body = prepared
    info = json.loads((root/'meta/info.json').read_bytes())
    info['features']['observation.images.side_left'] = {'shape': [2, 3, 3]}
    (root/'meta/info.json').write_text(json.dumps(info))
    report = json.loads((root/'inspection.json').read_bytes())
    report['files'] = export.native.dataset_files(root)
    report['capture_provenance']['files'] = report['files']
    (root/'inspection.json').write_text(json.dumps(report))
    (root/'capture.json').write_text(json.dumps(report['capture_provenance']))
    body['profile']['cameras'].append(dict(id='side', input_key='observation.images.side_left',
        arm_id=None, role='side', source_identity='camera-by-id-side',
        placement='cart-left-r3', shape=[3, 2, 3], purposes=['evaluation', 'record']))
    request, _ = export.prepare_export(body, row)
    assert request['profile'] == body['profile']
    body['profile']['cameras'][-1]['input_key'] = 'observation.images.other'
    with pytest.raises(ValueError, match='camera'):
        export.prepare_export(body, row)


def test_export_admission_accepts_a_two_arm_preparation_only_with_both_arms(capture, tmp_path):
    import experiment_export as export
    _, profile, readers = bimanual(capture)
    receipt = json.loads((capture[0] / 'split-receipt.json').read_bytes())
    root = tmp_path / 'prepared'
    (root / 'meta').mkdir(parents=True)
    (root / 'meta/info.json').write_text(json.dumps(readers['train'].meta.info))
    (root / 'data').mkdir()
    (root / 'data/part.parquet').write_bytes(b'native fixture bytes')
    report = copy.deepcopy(receipt['source'])
    report['files'] = export.pipeline.native.dataset_files(root)
    report['capture_provenance']['files'] = report['files']
    for name, value in {'intake-receipt.json': {'reader_verified': True}, 'inspection.json': report,
                        'capture.json': report['capture_provenance'], 'environment.json': {},
                        'decisions.json': receipt['decisions']}.items():
        (root / name).write_text(json.dumps(value))
    row = dict(id=uuid.uuid4().hex, kind='omx', path=str(root), name='Two-arm preparation')
    body = dict(prepared_id=row['id'], name='Two-arm export', profile=profile, request_id=str(uuid.uuid4()))
    request, _ = export.prepare_export(body, row)
    assert [arm['id'] for arm in request['profile']['arms']] == ['arm_a', 'arm_b']
    body['profile'] = copy.deepcopy(profile)
    body['profile']['arms'] = body['profile']['arms'][:1]
    body['profile']['cameras'][1]['arm_id'] = 'arm_a'
    with pytest.raises(ValueError, match='joint order'):
        export.prepare_export(body, row)


@pytest.mark.parametrize('fault', ['path', 'identity', 'request_id', 'kind', 'fixture', 'unknown', 'source_hash', 'profile', 'evidence_link', 'source_link'])
def test_bad_or_unreviewed_preparation_never_reaches_export(prepared, fault):
    export, root, row, body = prepared
    if fault == 'path':
        body['path'] = str(root)
    elif fault == 'identity':
        body['prepared_id'] = uuid.uuid4().hex
    elif fault == 'request_id':
        body['request_id'] = uuid.uuid4().hex
    elif fault == 'kind':
        row['kind'] = 'perception'
    elif fault == 'fixture':
        (root / 'intake-receipt.json').write_text(json.dumps({'reader_verified': True, 'fixture_only': True}))
    elif fault == 'unknown':
        path = root / 'decisions.json'
        decisions = json.loads(path.read_text())
        decisions[0]['outcome'] = 'unknown'
        path.write_text(json.dumps(decisions))
    elif fault == 'source_hash':
        (root / 'data/part.parquet').write_bytes(b'changed')
    elif fault == 'profile':
        body['profile']['arms'][0]['units'] = 'rad'
    elif fault in ('evidence_link', 'source_link'):
        path = root / ('decisions.json' if fault == 'evidence_link' else 'data/part.parquet')
        saved = path.with_suffix('.original')
        path.rename(saved)
        path.symlink_to(saved)
    with pytest.raises(ValueError):
        export.prepare_export(body, row)


def test_worker_revalidates_baseline_before_converter_and_preserves_originals(prepared, tmp_path, monkeypatch):
    export, root, row, body = prepared
    request, _ = export.prepare_export(body, row)
    calls = []

    def convert(actual, decisions, profile, output):
        assert actual == root and decisions == root / 'decisions.json'
        assert json.loads(profile.read_text()) == body['profile']
        calls.append(output)
        output.mkdir()
        return {'dataset_revision': 'a' * 64, 'dataset_root': str(output / 'dataset')}

    monkeypatch.setattr(export.pipeline, 'export_experiment', convert)
    before = {name: (root / name).read_bytes() for name in export.pipeline.PREPARED_FILES}
    output = tmp_path / 'run'
    result = export.run_export(request, output)
    assert calls == [output / 'export']
    assert result['dataset_revision'] == 'a' * 64 and result['act_only'] is True
    assert result['physical_learning_verified'] is result['policy_activation'] is False
    assert json.loads((output / 'result.json').read_text()) == result
    assert json.loads((output / 'progress.json').read_text())['phase'] == 'finished'
    assert all((root / name).read_bytes() == raw for name, raw in before.items())
    (root / 'decisions.json').write_text('[]')
    with pytest.raises(ValueError):
        export.run_export(request, tmp_path / 'rejected')
    assert calls == [output / 'export']


def test_worker_refuses_unknown_request_fields_and_cli_keeps_error_receipt(prepared, tmp_path):
    export, _, row, body = prepared
    request, _ = export.prepare_export(body, row)
    request['argv'] = ['anything']
    file = tmp_path / 'request.json'
    file.write_text(json.dumps(request))
    output = tmp_path / 'bad-output'
    with pytest.raises(ValueError):
        export.main(['--request', str(file), '--out', str(output)])
    failure = json.loads((output / 'error.json').read_text())
    assert failure['status'] == 'failed'
    assert failure['error'] == 'ValueError: unsupported fixed native export request'
    assert not (output / 'result.json').exists()
