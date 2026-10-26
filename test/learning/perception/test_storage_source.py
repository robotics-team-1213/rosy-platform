"""Finalized source manifests and native Isaac evidence become archive inputs."""
import hashlib
import importlib
import json
from pathlib import Path
import uuid

import pytest

from test_learning_accounts import accounts  # noqa: F401
from test_storage_pool import pool_setup  # noqa: F401
from test_storage_jobs import jobs_setup  # noqa: F401


def source_module():
    assert importlib.util.find_spec('storage_source'), 'completed source writer is missing'
    return importlib.import_module('storage_source')


def test_seal_completed_native_dataset_without_copying_payload(jobs_setup):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    (artifact / 'storage-source.json').unlink()
    (artifact / 'episode.npz').write_bytes(b'native-dataset-array')
    source_module().seal(artifact, 'dataset', {'source_revision': 'c' * 40})
    job = build().create(actor, dict(source_id='raw', artifact_id='run-one', profile='dataset'))
    assert build().run(actor, job['id'])['bytes_verified'] is True
    assert not list(cache.iterdir())
    with pytest.raises(ValueError): source_module().seal(artifact, 'dataset', {})


def test_source_writer_refuses_unverified_asset_closure_and_private_files(tmp_path):
    root = tmp_path / 'new-data'; root.mkdir(); (root / 'scene.usd').write_text('asset references')
    with pytest.raises(ValueError): source_module().seal(root, 'dataset', {})
    assert not (root / 'storage-source.json').exists()


def test_source_writer_rejects_invalid_isaac_source_revision(tmp_path):
    root = tmp_path / 'data'; root.mkdir(); (root / 'data.json').write_text('{}')
    with pytest.raises(ValueError):
        source_module().seal(root, 'isaac', dict(run_id='run-one', seed=0, source_revision='z' * 40))
    assert not (root / 'storage-source.json').exists()


@pytest.mark.parametrize('final', [False, True])
def test_isaac_export_uses_final_run_store_bytes_and_preserves_provenance(jobs_setup, monkeypatch, tmp_path, final):
    build, actor, remote, artifact, cache, inventory = jobs_setup
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / 'learning/envs/isaac'))
    from run_store import RunStore
    store = RunStore(tmp_path / 'isaac-owner')
    row = store.create(uuid.uuid4().hex, 'omx-f-import', {'seed': 42}, 'c' * 40)
    output = artifact.parent / ('archive-' + row['run_id'])
    if not final:
        with pytest.raises(ValueError): source_module().export_isaac_run(store, row['run_id'], output)
        assert not output.exists()
        return
    row = store.update(row['run_id'], 0, {'status': 'RUNNING'})
    raw = b'{"completed_frames":120}'
    (store.root / 'runs' / row['run_id'] / 'import-report.json').write_bytes(raw)
    store.finish(row['run_id'], row['revision'], dict(status='SUCCEEDED', stage='model_import',
        import_verified=True, completed_frames=120, task_success=None,
        cleanup='OWNED_PROCESSES_EXITED_GPU_RELEASED'), [dict(id='import-report', name='import-report.json',
        bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), media_type='application/json')])
    source_module().export_isaac_run(store, row['run_id'], output)
    assert (output / 'import-report.json').read_bytes() == raw
    source = json.loads((output / 'storage-source.json').read_text())
    assert source['provenance']['seed'] == 42
    assert source['provenance']['source_revision'] == 'c' * 40
    assert source['provenance']['completion_status'] == 'SUCCEEDED'
    job = build().create(actor, dict(source_id='raw', artifact_id=output.name, profile='isaac'))
    assert build().run(actor, job['id'])['status'] == 'verified'
