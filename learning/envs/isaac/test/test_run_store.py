"""Run identity, crash recovery, terminal evidence and artifact boundaries."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib
import json
from pathlib import Path
import sys
import subprocess
import uuid

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40


def module():
    assert (ROOT / 'run_store.py').is_file(), 'Isaac run store is missing'
    sys.path.insert(0, str(ROOT))
    return importlib.import_module('run_store')


def create(store, request=None, seed=7, **kwargs):
    return store.create(request or uuid.uuid4().hex, 'omx-f-import',
                        {'seed': seed}, SHA, **kwargs)


def finish(store, run, *, status='FAILED', artifacts=None):
    return store.finish(run['run_id'], run['revision'],
                        {'status': status, 'stage': 'model_import',
                         'task_success': None, 'reason': 'fixture'}, artifacts or [])


def test_same_request_is_one_run(tmp_path):
    store = module().RunStore(tmp_path / 'runs')
    request = uuid.uuid4().hex
    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(lambda _: create(store, request), range(2)))
    assert rows[0]['run_id'] == rows[1]['run_id']
    assert rows[0]['input_sha256'] == rows[1]['input_sha256']
    assert len(store.list()) == 1
    assert len(list((tmp_path / 'runs/runs').iterdir())) == 1


def test_changed_request_conflicts_and_new_run_preserves_parent(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    request = uuid.uuid4().hex
    first = create(store, request)
    with pytest.raises(mod.RunConflict):
        create(store, request, seed=8)
    second = create(store, parent_run_id=first['run_id'])
    assert second['run_id'] != first['run_id']
    assert second['parent_run_id'] == first['run_id']
    assert second['input_sha256'] == first['input_sha256']
    assert store.get(first['run_id'])['input'] == first['input']


def test_request_reservation_survives_crash(tmp_path):
    store = module().RunStore(tmp_path / 'runs')
    request = uuid.uuid4().hex
    first = create(store, request)
    (tmp_path / 'runs/requests' / (request + '.json')).unlink()
    recovered = create(module().RunStore(tmp_path / 'runs'), request)
    assert recovered['run_id'] == first['run_id']
    assert len(store.list()) == 1


def test_terminal_result_is_immutable_and_failed_runs_remain_visible(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    row = create(store)
    final = finish(store, row)
    result = tmp_path / 'runs/runs' / row['run_id'] / 'result.json'
    original = result.read_bytes()
    with pytest.raises(mod.RunConflict):
        store.update(row['run_id'], final['revision'], {'status': 'RUNNING'})
    with pytest.raises(mod.RunConflict):
        finish(store, final, status='SUCCEEDED')
    assert result.read_bytes() == original
    assert store.list()[0]['status'] == 'FAILED'


def test_revision_and_state_fences_are_enforced(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    row = create(store)
    live = store.update(row['run_id'], 0, {'status': 'RUNNING'})
    assert live['revision'] == 1
    with pytest.raises(mod.RunConflict):
        store.update(row['run_id'], 0, {'status': 'STOP_REQUESTED'})
    with pytest.raises(ValueError):
        store.update(row['run_id'], 1, {'input': {'seed': 999}})
    with pytest.raises(ValueError):
        finish(store, live, status='SUCCEEDED')


def test_artifact_refuses_swap_and_escape(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    row = create(store)
    path = tmp_path / 'runs/runs' / row['run_id'] / 'model.usd'
    path.write_bytes(b'fixture USD')
    item = {'id': 'usd', 'name': 'model.usd', 'bytes': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
            'media_type': 'application/octet-stream'}
    finish(store, row, artifacts=[item])
    assert store.artifact(row['run_id'], 'usd')['data'] == b'fixture USD'
    path.write_bytes(b'changed USD')
    with pytest.raises(ValueError):
        store.artifact(row['run_id'], 'usd')
    path.unlink()
    path.symlink_to(tmp_path / 'outside')
    with pytest.raises((ValueError, OSError)):
        store.artifact(row['run_id'], 'usd')
    with pytest.raises(ValueError):
        store.artifact('../outside', 'usd')


@pytest.mark.parametrize('bad', ['../outside', '/etc/passwd', 'C:/outside',
                               'folder/../file', 'folder\\file'])
def test_manifest_rejects_unsafe_names(tmp_path, bad):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    item = {'id': 'bad', 'name': bad, 'bytes': 1, 'sha256': 'a' * 64,
            'media_type': 'application/octet-stream'}
    with pytest.raises(ValueError):
        finish(store, row, artifacts=[item])
    assert store.get(row['run_id'])['status'] == 'PENDING'


def test_duplicate_manifest_names_and_bounds_are_refused(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    row = create(store)
    path = tmp_path / 'runs/runs' / row['run_id'] / 'a.bin'
    path.write_bytes(b'x')
    one = {'id': 'a', 'name': 'a.bin', 'bytes': 1,
           'sha256': hashlib.sha256(b'x').hexdigest(), 'media_type': 'application/octet-stream'}
    with pytest.raises(ValueError):
        finish(store, row, artifacts=[one, dict(one, id='b', name='A.bin')])
    with pytest.raises(ValueError):
        finish(store, row, artifacts=[dict(one, bytes=mod.RUN_BYTES + 1)])


def test_partial_artifact_is_not_final_evidence(tmp_path):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    assert store.get(row['run_id'])['snapshot'] == 'OBSERVATION_NOT_ATOMIC'
    with pytest.raises(ValueError):
        store.artifact(row['run_id'], 'not-final')


def test_json_corruption_and_root_symlink_fail_closed(tmp_path):
    mod = module()
    store = mod.RunStore(tmp_path / 'runs')
    row = create(store)
    state = tmp_path / 'runs/runs' / row['run_id'] / 'state.json'
    state.write_text('{"status":"RUNNING","status":"SUCCEEDED"}')
    with pytest.raises(ValueError):
        store.get(row['run_id'])
    alias = tmp_path / 'alias'
    alias.symlink_to(tmp_path / 'runs', target_is_directory=True)
    with pytest.raises(ValueError):
        mod.RunStore(alias)


def test_input_snapshot_binds_source_assets_and_normalized_conditions():
    mod = module()
    first = mod.input_snapshot('omx-f-import', {'seed': 7}, SHA)
    assert first == mod.input_snapshot('omx-f-import', {'seed': 7}, SHA)
    assert first['input_sha256'] != mod.input_snapshot('omx-f-import', {'seed': 8}, SHA)['input_sha256']
    assert len(first['input']['assets_sha256']) == 64
    assert first['input']['config']['frames'] == 120
    with pytest.raises(ValueError):
        mod.input_snapshot('omx-f-import', {'seed': 0}, 'HEAD')


@pytest.mark.parametrize('changes', [None, [], 'invalid'])
def test_non_object_state_changes_are_rejected(tmp_path, changes):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    with pytest.raises(ValueError):
        store.update(row['run_id'], row['revision'], changes)


def test_fifo_is_rejected_without_waiting_for_a_writer(tmp_path):
    module()
    program = '''import sys,os,hashlib,uuid
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from run_store import RunStore
store=RunStore(Path(sys.argv[1]))
row=store.create(uuid.uuid4().hex,'omx-f-import',{'seed':0},'a'*40)
os.mkfifo(Path(sys.argv[1])/'runs'/row['run_id']/'pipe')
item={'id':'pipe','name':'pipe','bytes':0,'sha256':hashlib.sha256(b'').hexdigest(),
      'media_type':'application/octet-stream'}
try:
 store.finish(row['run_id'],0,{'status':'FAILED'},[item])
except ValueError:
 sys.exit(0)
sys.exit(1)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path / 'runs'), str(ROOT)],
                            capture_output=True, timeout=3)
    assert result.returncode == 0, result.stderr.decode(errors='replace')


@pytest.mark.parametrize('filename', ['result.json', 'artifacts.json'])
def test_final_evidence_tampering_is_refused(tmp_path, filename):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    finish(store, row)
    path = tmp_path / 'runs/runs' / row['run_id'] / filename
    value = json.loads(path.read_text())
    value['tampered'] = True
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        store.get(row['run_id'])


@pytest.mark.parametrize('value', [{}, [], None])
def test_invalid_state_shape_is_a_rejected_record(tmp_path, value):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    state = tmp_path / 'runs/runs' / row['run_id'] / 'state.json'
    state.write_text(json.dumps(value))
    with pytest.raises(ValueError):
        store.get(row['run_id'])
    assert store.list()[0]['status'] == 'UNKNOWN'


@pytest.mark.parametrize('filename', ['input.json', 'state.json'])
def test_process_death_during_exclusive_publish_recovers_same_request(tmp_path, filename):
    mod = module()
    request = uuid.uuid4().hex
    program = '''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from run_store import RunStore
store=RunStore(Path(sys.argv[1]))
link=os.link
def interrupt(src,dst,*args,**kwargs):
 link(src,dst,*args,**kwargs)
 if dst==sys.argv[4]:os._exit(72)
os.link=interrupt
store.create(sys.argv[3],'omx-f-import',{'seed':7},'a'*40)
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path / 'runs'),
                             str(ROOT), request, filename], capture_output=True, timeout=5)
    assert result.returncode == 72
    store = mod.RunStore(tmp_path / 'runs')
    recovered = create(store, request)
    assert recovered['run_id'] == uuid.uuid5(uuid.NAMESPACE_URL, 'rosy.isaac-run:' + request).hex
    assert recovered['input_sha256'] == mod.input_snapshot('omx-f-import', {'seed': 7}, SHA)['input_sha256']
    assert len(store.list()) == 1
    folder = tmp_path / 'runs/runs' / recovered['run_id']
    assert (folder / 'input.json').stat().st_nlink == 1
    assert (folder / 'state.json').stat().st_nlink == 1


@pytest.mark.parametrize('stage', ['artifacts.json', 'result.json', 'before-state', 'after-state'])
def test_interrupted_completion_is_recovered_or_unpublished_before_stop(tmp_path, stage):
    mod = module()
    request = uuid.uuid4().hex
    program = '''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[2])
from run_store import RunStore
store=RunStore(Path(sys.argv[1]))
row=store.create(sys.argv[3],'omx-f-import',{'seed':7},'a'*40)
row=store.update(row['run_id'],0,{'status':'RUNNING'})
link,replace=os.link,os.replace
def interrupt_link(src,dst,*args,**kwargs):
 link(src,dst,*args,**kwargs)
 if dst==sys.argv[4]:os._exit(72)
def interrupt_replace(src,dst,*args,**kwargs):
 if dst=='state.json' and sys.argv[4]=='before-state':os._exit(72)
 replace(src,dst,*args,**kwargs)
 if dst=='state.json' and sys.argv[4]=='after-state':os._exit(72)
os.link,os.replace=interrupt_link,interrupt_replace
store.finish(row['run_id'],row['revision'],{'status':'SUCCEEDED','stage':'model_import',
 'import_verified':True,'completed_frames':120,'task_success':None},[])
'''
    result = subprocess.run([sys.executable, '-c', program, str(tmp_path / 'runs'),
                             str(ROOT), request, stage], capture_output=True, timeout=5)
    assert result.returncode == 72
    store = mod.RunStore(tmp_path / 'runs')
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, 'rosy.isaac-run:' + request).hex
    recovered = store.get(run_id)
    folder = tmp_path / 'runs/runs' / run_id
    if recovered['status'] == 'RUNNING':
        assert not (folder / 'result.json').exists()
        assert not (folder / 'artifacts.json').exists()
        stopped = store.update(run_id, recovered['revision'], {'status': 'STOP_REQUESTED'})
        assert finish(store, stopped, status='STOPPED')['status'] == 'STOPPED'
    else:
        assert recovered['status'] == 'SUCCEEDED'
        with pytest.raises(mod.RunConflict):
            store.update(run_id, 1, {'status': 'STOP_REQUESTED'})
        assert json.loads((folder / 'result.json').read_text())['status'] == 'SUCCEEDED'


def test_unrelated_hardlink_is_not_cleaned_up(tmp_path):
    store = module().RunStore(tmp_path / 'runs')
    row = create(store)
    source = tmp_path / 'runs/runs' / row['run_id'] / 'input.json'
    unrelated = tmp_path / 'unrelated'
    import os
    os.link(source, unrelated)
    with pytest.raises(ValueError):
        store.get(row['run_id'])
    assert unrelated.exists() and source.stat().st_nlink == 2
