import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'), str(ROOT / 'test')]
from dataset_store import DatasetStore, closure
from rosy.contracts.learning import seal
from test_learning_artifact_contracts import episode


def dataset(root):
    root.mkdir(exist_ok=True)
    raw = b'recorded stream'
    (root / 'stream').write_bytes(raw)
    ref = {'path': 'stream', 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    ep = episode(); ep['sources'] = [ref]; ep['streams'] = {key: ref for key in ep['streams']}
    ep = seal(ep)
    blob = json.dumps(ep).encode(); (root / 'episode.json').write_bytes(blob)
    doc = seal({'schema': 'rosy.dataset-manifest/1', 'episodes': [ep['revision']],
                'transformation': {'tool_revision': 'fixture', 'config_sha256': 'c' * 64},
                'files': [ref, {'path': 'episode.json', 'bytes': len(blob), 'sha256': hashlib.sha256(blob).hexdigest()}]})
    (root / 'dataset-manifest.json').write_text(json.dumps(doc))
    return doc


def test_snapshot_and_restart_verify_all_episode_files(tmp_path):
    source = tmp_path / 'source'; doc = dataset(source)
    store = DatasetStore(tmp_path / 'store')
    store.register(source); store.register(source)
    (source / 'stream').write_bytes(b'mutated source')
    assert DatasetStore(store.root).require([doc['revision']]) == [doc['revision']]
    (store.root / doc['revision'] / 'stream').write_bytes(b'tamper')
    with pytest.raises(ValueError, match='hash'):
        store.require([doc['revision']])


def test_missing_episode_or_undeclared_stream_is_rejected(tmp_path):
    root = tmp_path / 'source'; doc = dataset(root)
    doc['files'] = doc['files'][1:]
    (root / 'dataset-manifest.json').write_text(json.dumps(seal(doc)))
    with pytest.raises(ValueError, match='closure'):
        closure(root)
    doc['files'] = []; doc['episodes'] = ['f' * 64]
    with pytest.raises(ValueError):
        DatasetStore(tmp_path / 'store').require(doc['episodes'])


def test_require_refuses_unsafe_revision_before_filesystem_read(tmp_path):
    with pytest.raises(ValueError, match='revision'):
        DatasetStore(tmp_path / 'store').require(['../outside'])
