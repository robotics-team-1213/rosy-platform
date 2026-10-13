import json
import hashlib
import pytest
from learning_workspace import Workspace


def test_registration_persists_and_detects_changed_missing_corrupt_reports(tmp_path):
    output = tmp_path / 'run'
    output.mkdir()
    report = output / 'state.json'
    report.write_text(json.dumps({'schema': 'rosy.learning.job/1', 'outcome': 'running',
                                 'steps': {'train': {'status': 'failed', 'error': 'quality rejected'}}}))
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    item = workspace.register({'kind': 'perception', 'name': '학습 결과', 'path': str(output)})
    assert item['reports'][0]['status'] == 'unchanged'
    assert item['reports'][0]['steps'][0]['status'] == 'failed'
    assert Workspace(workspace.db).list()[0]['id'] == item['id']
    report.write_text('{"outcome":"ready"}')
    assert workspace.list()[0]['reports'][0]['status'] == 'changed'
    report.write_text('bad')
    assert workspace.list()[0]['reports'][0]['status'] == 'invalid'
    report.unlink()
    assert workspace.list()[0]['reports'][0]['status'] == 'missing'


def test_stale_remove_and_duplicate_do_not_overwrite(tmp_path):
    (tmp_path / 'comparison-report.json').write_text('{"verdict":"research_only"}')
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    body = {'kind': 'pinky', 'path': str(tmp_path), 'name': 'Pinky'}
    item = workspace.register(body)
    with pytest.raises(ValueError, match='already'):
        workspace.register(body)
    with pytest.raises(ValueError, match='version'):
        workspace.remove({'id': item['id'], 'version': 999})
    workspace.remove({'id': item['id'], 'version': item['version']})
    assert workspace.list() == []
    assert (tmp_path / 'comparison-report.json').exists()


def test_unrecognized_or_empty_inputs_and_external_links_rejected(tmp_path, monkeypatch):
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    for body in ({'kind': 'execute', 'path': str(tmp_path), 'name': 'x'},
                 {'kind': 'omx', 'path': '//unknown-host/results', 'name': 'x'},
                 {'kind': 'omx', 'path': str(tmp_path), 'name': ''},
                 {'kind': 'omx', 'path': str(tmp_path / 'absent'), 'name': 'x'}):
        with pytest.raises(ValueError):
            workspace.register(body)
    # Exercise link rejection even where Windows cannot create unprivileged symlinks.
    external = tmp_path / 'external.json'
    external.write_text('{"verdict":"pass"}')
    folder = tmp_path / 'run'
    folder.mkdir()
    report = folder / 'offline-report.json'
    report.write_text(external.read_text())
    from pathlib import Path
    original = Path.is_symlink
    monkeypatch.setattr(Path, 'is_symlink', lambda path: path == report or original(path))
    with pytest.raises(ValueError, match='link'):
        workspace.register({'kind': 'omx', 'path': str(folder), 'name': 'x'})


def test_report_values_are_bounded_and_credentials_not_returned(tmp_path):
    (tmp_path / 'state.json').write_text(json.dumps({'outcome': 'running',
        'inputs': {'token': 'private-value'}, 'steps': {'train': {'status': 'failed'}}}))
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    item = workspace.register({'kind': 'perception', 'path': str(tmp_path), 'name': 'x'})
    assert 'private-value' not in json.dumps(item)
    assert item['qualified'] is False


def test_canonical_dataset_and_policy_artifact_filenames(tmp_path):
    (tmp_path / 'dataset-manifest.json').write_text('{"schema":"rosy.dataset-manifest/1"}')
    (tmp_path / 'policy-artifact.json').write_text('{"schema":"rosy.policy-artifact/1"}')
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    for kind, file in [('raw', 'dataset-manifest.json'), ('policy', 'policy-artifact.json')]:
        item = workspace.register({'kind': kind, 'path': str(tmp_path), 'name': kind})
        assert any(row['name'] == file and row['status'] == 'unchanged' for row in item['reports'])


def test_declared_jpg_opens_separately_and_refuses_changed_bytes(tmp_path):
    image = tmp_path / 'overlay.jpg'
    raw = b'\xff\xd8preview\xff\xd9'
    image.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    (tmp_path / 'summary.json').write_text(json.dumps({
        'status': 'candidate_evaluated', 'verdict': 'HOLD',
        'metrics': [{'label': 'Independent mIoU', 'value': 0.9323}],
        'images': [{'name': image.name, 'sha256': digest}],
    }))
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    item = workspace.register({'kind': 'perception', 'name': 'candidate', 'path': str(tmp_path)})
    report = next(row for row in item['reports'] if row['name'] == 'summary.json')
    assert report['metrics'][0]['value'] == 0.9323
    assert workspace.image(item['id'], image.name) == (raw, digest)
    with pytest.raises(ValueError, match='not declared'):
        workspace.image(item['id'], '../summary.json')
    image.write_bytes(b'\xff\xd8changed\xff\xd9')
    assert next(row for row in workspace.list()[0]['reports'] if row['name'] == 'summary.json')['status'] == 'invalid'
    with pytest.raises(ValueError, match='not declared'):
        workspace.image(item['id'], image.name)
