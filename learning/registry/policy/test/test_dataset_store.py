import hashlib
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(ROOT / 'learning/registry/policy'), str(ROOT / 'contracts/learning/src'), str(ROOT / 'test')]
from dataset_store import DatasetStore, closure
from rosy.contracts.learning import seal
sys.path[:0] = [str(ROOT / p) for p in ('learning/curation/omx', 'middleware/apps/device/omx/adapter',
    'middleware/apps/device/omx/adapter/test', 'contracts/foundation')]
from test_demonstration import complete_episode
from common_episode import convert


def dataset(root):
    raw = root.parent / (root.name + '-raw')
    manifest = complete_episode(raw)
    ep = convert(raw / manifest['episode_id'], root)
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            payload = path.read_bytes()
            files.append({'path': path.relative_to(root).as_posix(), 'bytes': len(payload),
                          'sha256': hashlib.sha256(payload).hexdigest()})
    doc = seal({'schema': 'rosy.dataset-manifest/1', 'episodes': [ep['revision']],
                'transformation': {'tool_revision': 'fixture', 'config_sha256': 'c' * 64},
                'files': files})
    (root / 'dataset-manifest.json').write_text(json.dumps(doc))
    return doc


def test_snapshot_and_restart_verify_all_episode_files(tmp_path):
    source = tmp_path / 'source'; doc = dataset(source)
    store = DatasetStore(tmp_path / 'store')
    store.register(source); store.register(source)
    (source / 'source/samples.jsonl').write_bytes(b'mutated source')
    assert DatasetStore(store.root).require([doc['revision']]) == [doc['revision']]
    (store.root / doc['revision'] / 'source/samples.jsonl').write_bytes(b'tamper')
    with pytest.raises(ValueError, match='hash'):
        store.require([doc['revision']])


def test_missing_episode_or_undeclared_stream_is_rejected(tmp_path):
    root = tmp_path / 'source'; doc = dataset(root)
    doc['files'] = [ref for ref in doc['files'] if ref['path'] != 'source/samples.jsonl']
    (root / 'dataset-manifest.json').write_text(json.dumps(seal(doc)))
    with pytest.raises(ValueError, match='closure'):
        closure(root)
    doc['files'] = []; doc['episodes'] = ['f' * 64]
    with pytest.raises(ValueError):
        DatasetStore(tmp_path / 'store').require(doc['episodes'])


def test_require_refuses_unsafe_revision_before_filesystem_read(tmp_path):
    with pytest.raises(ValueError, match='revision'):
        DatasetStore(tmp_path / 'store').require(['../outside'])


def test_store_does_not_keep_database_file_open(tmp_path):
    source = tmp_path / 'source'; doc = dataset(source)
    store = DatasetStore(tmp_path / 'store')
    store.register(source); store.require([doc['revision']])
    # Windows cannot unlink an open SQLite file; no garbage-collector dependency.
    (store.root / 'datasets.sqlite3').unlink()
    assert not (store.root / 'datasets.sqlite3').exists()


def test_pinky_policy_cannot_promote_on_omx_dataset(tmp_path):
    source = tmp_path / 'source'; doc = dataset(source)
    store = DatasetStore(tmp_path / 'store'); store.register(source)
    with pytest.raises(ValueError, match='policy.*Episode'):
        store.require_policy({'profile': 'pinky_base_velocity_v1', 'robot_type': 'pinky_pro',
                              'environment': 'real', 'dataset_revisions': [doc['revision']]})


def test_compatibility_does_not_trust_reopened_unhashed_episode(tmp_path, monkeypatch):
    source = tmp_path / 'source'; doc = dataset(source)
    store = DatasetStore(tmp_path / 'store'); store.register(source)
    original = store.require
    def interleaved(revisions, **kwargs):
        result = original(revisions, **kwargs)
        path = store.root / doc['revision'] / 'manifest.json'
        episode = json.loads(path.read_text())
        episode.update(profile='pinky_recording_session_v1', robot_type='pinky_pro', environment='real')
        path.write_text(json.dumps(episode))  # Intentionally neither hashed nor resealed.
        return result
    monkeypatch.setattr(store, 'require', interleaved)
    with pytest.raises(ValueError, match='policy.*Episode'):
        store.require_policy({'profile': 'pinky_base_velocity_v1', 'robot_type': 'pinky_pro',
                              'environment': 'real', 'dataset_revisions': [doc['revision']]})


def test_hash_consistent_bad_joint_target_never_enters_store(tmp_path):
    root = tmp_path / 'source'; dataset(root)
    samples = root / 'source/samples.jsonl'
    rows = [json.loads(row) for row in samples.read_text().splitlines()]
    rows[0]['action'][0] = 2.0
    samples.write_text('\n'.join(json.dumps(row) for row in rows) + '\n')
    original = root / 'source/manifest.json'
    manifest = json.loads(original.read_text())
    manifest['samples_sha256'] = hashlib.sha256(samples.read_bytes()).hexdigest()
    original.write_text(json.dumps(manifest))
    def refreshed(ref):
        payload = (root / ref['path']).read_bytes()
        return {**ref, 'sha256': hashlib.sha256(payload).hexdigest(), 'bytes': len(payload)}
    common = root / 'manifest.json'; ep = json.loads(common.read_text())
    ep['sources'] = [refreshed(ref) for ref in ep['sources']]
    ep['streams'] = {key: refreshed(ref) for key, ref in ep['streams'].items()}
    ep['outcome']['evidence'] = [refreshed(ref) for ref in ep['outcome']['evidence']]
    ep = seal(ep); common.write_text(json.dumps(ep))
    doc = json.loads((root / 'dataset-manifest.json').read_text())
    doc['files'] = [refreshed(ref) for ref in doc['files']]
    doc['episodes'] = [ep['revision']]
    doc = seal(doc); (root / 'dataset-manifest.json').write_text(json.dumps(doc))
    store = DatasetStore(tmp_path / 'store')
    with pytest.raises(ValueError, match='joint_limit'):
        store.register(root)
    assert not (store.root / doc['revision']).exists()


@pytest.mark.parametrize('profile', ['pinky_recording_session_v1', 'pilot_recording_v1'])
def test_unsupported_profile_cannot_bypass_body_validation(tmp_path, profile):
    root = tmp_path / 'source'; doc = dataset(root)
    path = root / 'manifest.json'; ep = json.loads(path.read_text())
    ep['profile'] = profile; ep = seal(ep); path.write_text(json.dumps(ep))
    for ref in doc['files']:
        if ref['path'] == 'manifest.json':
            ref.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    doc['episodes'] = [ep['revision']]
    (root / 'dataset-manifest.json').write_text(json.dumps(seal(doc)))
    with pytest.raises(ValueError, match='profile validator not implemented|Pinky recording metadata required'):
        DatasetStore(tmp_path / 'store').register(root)
