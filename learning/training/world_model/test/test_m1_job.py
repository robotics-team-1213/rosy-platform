"""D-782 M1 training: train split only, deterministic, digest-bound and never a promotion."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT/'learning/curation/omx/test'))
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
import world_model_fixture as fixture
from rosy.contracts.learning.prediction import validate_artifact


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def dataset(tmp_path):
    builder = _load('world_model_dataset', ROOT/'learning/curation/omx/world_model_dataset.py')
    roots = fixture.sessions(tmp_path, frames=40)
    builder.build([r for r, _ in roots.values()], tmp_path/'dataset', horizon=2,
                  splits={n: s for n, (_, s) in roots.items()})
    return tmp_path/'dataset'


@pytest.fixture
def job():
    return _load('m1_job', ROOT/'learning/training/world_model/m1_job.py')


def test_training_writes_a_valid_digest_bound_artifact(job, dataset, tmp_path):
    report = job.train(dataset, tmp_path/'run', members=3)
    artifact = validate_artifact(json.loads((tmp_path/'run/artifact.json').read_text()), report['artifact_digest'])
    assert artifact['train_windows'] == 76 and len(artifact['members']) == 3
    assert report['promoted'] is False and report['deployed'] is False
    assert report['train_mae'] < 1.0  # linear synthetic dynamics are learnable


def test_same_seed_reproduces_and_output_is_never_overwritten(job, dataset, tmp_path):
    first = job.train(dataset, tmp_path/'a', seed=1)
    second = job.train(dataset, tmp_path/'b', seed=1)
    assert first['artifact_digest'] == second['artifact_digest']
    with pytest.raises(ValueError, match='new output'):
        job.train(dataset, tmp_path/'a')


def test_eval_and_test_windows_do_not_shape_the_model(job, dataset, tmp_path):
    before = job.train(dataset, tmp_path/'a')
    data = json.loads((dataset/'dataset.json').read_text())
    data['windows']['eval'] = data['windows']['eval'][:1]
    data['windows']['test'] = []
    raw = (json.dumps(data, allow_nan=False, sort_keys=True)+'\n').encode()
    (dataset/'dataset.json').write_bytes(raw)
    receipt = json.loads((dataset/'receipt.json').read_text())
    receipt['dataset_sha256'] = hashlib.sha256(raw).hexdigest()
    (dataset/'receipt.json').write_text(json.dumps(receipt))
    after = job.train(dataset, tmp_path/'b')
    members = [json.loads((tmp_path/name/'artifact.json').read_text())['members'] for name in ('a', 'b')]
    assert members[0] == members[1]
    # Same weights, but the artifact still cites the exact dataset bytes it came from.
    assert before['artifact_digest'] != after['artifact_digest']
