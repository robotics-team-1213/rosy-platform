"""Operator orchestration keeps human review as the admission gate for offline training."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest


@pytest.fixture
def module():
    path = Path(__file__).resolve().parents[1]/'collection_pipeline.py'
    spec = importlib.util.spec_from_file_location('collection_pipeline', path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def prepared(tmp_path):
    root = tmp_path/'prepared'
    root.mkdir()
    episodes = [dict(episode_index=i, frames=2, content_sha256=str(i)*64, session_id=f'session-{i}',
                     cycle_id=f'cycle-{i}', outcome='unknown', split='exclude', reviewer='', reason='')
                for i in range(3)]
    report = dict(source_mode='scripted_teacher', episodes=episodes, repo_id='fixture/omx')
    for name, value in (('inspection.json', report), ('decisions.json', episodes),
                        ('capture.json', {'schema': 'fixture'}), ('environment.json', {'schema': 'fixture'}),
                        ('intake-receipt.json', {'reader_verified': True, 'sessions': [{'manifest_sha256': 'a'*64}]})):
        (root/name).write_text(json.dumps(value))
    return root, report


def test_unknown_default_decisions_cannot_create_training_output(module, prepared, tmp_path, monkeypatch):
    root, _ = prepared
    def unexpected(*args, **kwargs):
        pytest.fail('unreviewed defaults reached a writer or trainer')
    monkeypatch.setattr(module.native, 'split_reviewed', unexpected)
    monkeypatch.setattr(module.cycle, 'run_cycle', unexpected)
    with pytest.raises(ValueError, match='nonempty'):
        module.train(root, root/'decisions.json', tmp_path/'run')
    assert not (tmp_path/'run').exists()


def test_reviewed_training_orchestrates_existing_helpers_and_binds_receipts(module, prepared, tmp_path, monkeypatch):
    root, report = prepared
    decisions = copy.deepcopy(report['episodes'])
    for decision, split in zip(decisions, ('train', 'eval', 'test')):
        decision.update(outcome='success', split=split, reviewer='human', reason='reviewed recording')
    labels = tmp_path/'human.json'
    labels.write_text(json.dumps(decisions))
    calls = []
    def split(source, actual, reviewed, output):
        assert source == root and actual == report and reviewed == decisions
        calls.append('split')
        output.mkdir()
        (output/'split-receipt.json').write_text(json.dumps({'source': actual, 'decisions': reviewed}))
    def run(splits, output, **kwargs):
        assert calls == ['split'] and splits == tmp_path/'run/splits'
        assert kwargs == dict(steps=2, batch_size=1, device='cpu')
        calls.append('train')
        output.mkdir()
        (output/'cycle-receipt.json').write_text(json.dumps({'offline_only': True}))
        return {'offline_only': True}
    monkeypatch.setattr(module.native, 'split_reviewed', split)
    monkeypatch.setattr(module.cycle, 'run_cycle', run)
    result = module.train(root, labels, tmp_path/'run', steps=2, batch_size=1)
    assert calls == ['split', 'train']
    assert result['prepared_files']['intake-receipt.json']
    assert result['decisions_sha256'] and result['split_receipt_sha256'] and result['cycle_receipt_sha256']
    assert result['device_execution'] is False and result['uploaded'] is False
    assert json.loads((tmp_path/'run/pipeline-receipt.json').read_text()) == result


def test_prepare_returns_explicit_review_paths_and_structured_next_argv(module, tmp_path, monkeypatch):
    output = tmp_path/'prepared'
    calls = []
    def prepare(sessions, destination, repo_id, **kwargs):
        calls.append((sessions, destination, repo_id, kwargs))
        return {'reader_verified': True}
    monkeypatch.setattr(module.intake, 'prepare', prepare)
    result = module.prepare([tmp_path/'raw'], output, 'fixture/omx', completed_only=True)
    assert calls == [([tmp_path/'raw'], output, 'fixture/omx', {'completed_only': True, 'camera_references': None})]
    assert result['decisions'] == str(output/'decisions.json')
    assert result['inspection'] == str(output/'inspection.json')
    argv = result['next_command']['argv']
    assert argv[2:4] == ['train', str(output)]
    assert argv[argv.index('--decisions')+1] == str(output/'decisions.json')
    assert result['review_required'] is True
