"""D-792 S4: the read-only OMX page lists registered intake folders without exposing host paths."""
import json
import threading
import urllib.request
import urllib.error

import pytest

from review_app import ReviewStore, make_server
from test_review_return import fixture_inputs


@pytest.mark.parametrize('file,contents', [
    ('inspection.json', None), ('inspection.json', 'null'),
    ('inspection.json', '{'), ('decisions.json', '{}'),
    ('decisions.json', '[null]'), ('camera-setup.json', '[]'),
    *[('inspection.json', json.dumps(dict(episodes=[], camera_keys=value)))
      for value in (None, 42, 'front', [42])],
    ('decisions.json', '[]'),
    ('decisions.json', '[{"episode_index":0}]'),
    ('decisions.json', '[{"episode_index":null,"frames":12}]'),
    ('camera-setup.json', '{"episodes":[{"episode_index":0,"checks":{"top":null}}]}'),
])
def test_bad_registered_intake_does_not_hide_other_sets_or_leak_paths(tmp_path, file, contents):
    from learning_workspace import Workspace
    from omx_web import get
    from types import SimpleNamespace
    workspace = Workspace(tmp_path / 'workspace.sqlite3')
    for name in ('good', 'bad'):
        root = tmp_path / name
        prepared(root)
        # Register the prepared folder before simulating an interrupted or corrupt write.
        workspace.register(dict(kind='omx', name=name, path=str(root)))
    target = tmp_path / 'bad' / file
    if contents is None:
        target.unlink()
    else:
        target.write_text(contents)
    responses = []
    assert get(SimpleNamespace(send=responses.append), '/api/learning/omx', workspace)
    rows = {row['name']: row for row in responses[0]['sets']}
    assert rows['good']['episodes'] and rows['bad']['error']
    raw = json.dumps(responses, ensure_ascii=False)
    assert str(tmp_path) not in raw and json.dumps(str(tmp_path))[1:-1] not in raw


def prepared(root, *, camera=True):
    root.mkdir()
    decisions = [dict(episode_index=i, frames=12, outcome='unknown', object_result='unknown', split='exclude',
                      reviewer='', reason='', content_sha256=str(i) * 64, session_id='s1', cycle_id=f'c{i}')
                 for i in range(2)]
    (root / 'intake-receipt.json').write_text(json.dumps(dict(schema='rosy.omx-collection-intake.v1')))
    (root / 'inspection.json').write_text(json.dumps(dict(source_mode='scripted_teacher', episodes=decisions)))
    (root / 'decisions.json').write_text(json.dumps(decisions))
    if camera:
        check = dict(verdict='ok', pose_error_rad=None)
        (root / 'camera-setup.json').write_text(json.dumps(dict(
            schema='rosy.omx-camera-setup-intake/1', mode='shadow', references={'top': 'a' * 64},
            camera_info_sha256={'top': 'b' * 64},
            episodes=[dict(episode_index=0, session_id='s1', checks={'top': dict(
                reference_revision='a' * 64, mode='shadow', before=check, after=dict(check, verdict='adjust'))})])))


def test_registered_intake_folders_are_listed_read_only(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    server = make_server(ReviewStore(tmp_path / 'state', source, human, images), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    try:
        token = json.load(urllib.request.urlopen(url + '/api/workspace'))['token']
        prepared(tmp_path / 'prepared')
        (tmp_path / 'run').mkdir()
        (tmp_path / 'run' / 'state.json').write_text('{"status": "training"}')
        for name, folder in (('day 1', 'prepared'), ('ACT run', 'run')):
            request = urllib.request.Request(url + '/api/learning/register', json.dumps(
                {'kind': 'omx', 'name': name, 'path': str(tmp_path / folder)}).encode(),
                headers={'X-Pinky-Token': token})
            urllib.request.urlopen(request).read()
        with urllib.request.urlopen(url + '/learning/omx') as page:
            assert b'omx.js' in page.read()
        raw = urllib.request.urlopen(url + '/api/learning/omx').read().decode()
        assert str(tmp_path) not in raw and json.dumps(str(tmp_path))[1:-1] not in raw
        sets = json.loads(raw)['sets']
        assert [s['name'] for s in sets] == ['day 1']  # the ACT run folder is not a prepared intake folder
        day = sets[0]
        assert day['trainable']['ok'] is False and day['trainable']['reason']
        assert [e['split'] for e in day['episodes']] == ['exclude', 'exclude']
        assert day['episodes'][0]['camera'] == {'top': {'before': 'ok', 'after': 'adjust', 'pose_error_rad': None}}
        assert day['episodes'][1]['camera'] == {}
        assert day['camera_setup']['references'] == {'top': 'a' * 64}
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def native(root, setup, *, camera=False):
    """A prepare-native intake: inspection.json records the refusal-checked ``{role: revision}``."""
    prepared(root, camera=camera)
    report = json.loads((root / 'inspection.json').read_text())
    report.update(camera_keys=[f'observation.images.{role}' for role in setup], camera_setup=setup)
    (root / 'inspection.json').write_text(json.dumps(report))


def test_prepare_native_camera_reference_links_only_stored_revisions(tmp_path):
    from learning_workspace import Workspace
    from omx_web import get
    from types import SimpleNamespace
    workspace, store = Workspace(tmp_path / 'workspace.sqlite3'), tmp_path / 'state' / 'camera-setup'
    store.mkdir(parents=True)
    (store / f'{"c" * 64}.json').write_text('{}')
    for name, setup, camera in (('native', {'top': 'c' * 64, 'wrist': 'd' * 64}, False),
                                ('both', {'top': 'c' * 64}, True), ('bad', {'top': '../../x'}, False)):
        native(tmp_path / name, setup, camera=camera)
        workspace.register(dict(kind='omx', name=name, path=str(tmp_path / name)))
    prepared(tmp_path / 'shadow')
    workspace.register(dict(kind='omx', name='shadow', path=str(tmp_path / 'shadow')))
    responses = []
    assert get(SimpleNamespace(send=responses.append), '/api/learning/omx', workspace, None, tmp_path / 'state')
    rows = {row['name']: row for row in responses[0]['sets']}
    assert rows['native']['camera_reference'] == {'top': {'revision': 'c' * 64, 'reference': True},
                                                  'wrist': {'revision': 'd' * 64, 'reference': False}}
    assert rows['native']['camera_setup'] is None
    assert rows['both']['camera_reference']['top']['reference'] and rows['both']['camera_setup']['mode'] == 'shadow'
    assert rows['shadow']['camera_reference'] is None and rows['shadow']['camera_setup']
    assert rows['bad']['error'] and 'camera_reference' not in rows['bad']
    raw = json.dumps(responses, ensure_ascii=False)
    assert str(tmp_path) not in raw and json.dumps(str(tmp_path))[1:-1] not in raw


def test_segment_reviews_append_versions_and_leave_original_labels_untouched(tmp_path):
    source, human, images = fixture_inputs(tmp_path)
    store = ReviewStore(tmp_path/'state', source, human, images)
    server = make_server(store, 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{server.server_port}'
    def request(path, body, token=None, origin=None):
        headers = {'Content-Type': 'application/json'}
        if token: headers['X-Pinky-Token'] = token
        if origin: headers['Origin'] = origin
        return urllib.request.urlopen(urllib.request.Request(url+path,json.dumps(body).encode(),headers))
    try:
        token = json.load(urllib.request.urlopen(url+'/api/workspace'))['token']
        root = tmp_path/'prepared'
        prepared(root)
        original = (root/'decisions.json').read_bytes()
        row = json.load(request('/api/learning/register', dict(kind='omx', name='source',path=str(root)),token))
        decision = json.loads(original)[0]
        segment = {key:decision[key] for key in ('episode_index','frames','content_sha256','session_id','cycle_id')}
        segment.update(start_frame=2,end_frame=6,object='cube',intervention=False,
                       outcome='unknown',split='exclude',reviewer='person',reason='uncertain retention')
        body = dict(id=row['id'],version=0,segments=[segment])
        for options in ({}, {'token':token,'origin':'https://invalid.example'}):
            with pytest.raises(urllib.error.HTTPError) as denied:
                request('/api/learning/omx/segments',body,**options)
            assert denied.value.code == 403
        first = json.load(request('/api/learning/omx/segments',body,token))
        assert first['version'] == 1 and first['document']['segments'][0]['outcome'] == 'unknown'
        with pytest.raises(urllib.error.HTTPError) as stale:
            request('/api/learning/omx/segments',body,token)
        assert stale.value.code == 409
        body['version'] = 1
        body['segments'][0]['outcome'] = 'failure'
        second = json.load(request('/api/learning/omx/segments',body,token))
        assert second['version'] == 2
        value = json.load(urllib.request.urlopen(url+'/api/learning/omx'))['sets'][0]
        assert value['segment_review'] == second
        assert (root/'decisions.json').read_bytes() == original
        with store.connect() as db:
            documents = db.execute('SELECT document FROM omx_segment_reviews ORDER BY version').fetchall()
        assert len(documents) == 2 and json.loads(documents[0][0])['segments'][0]['outcome'] == 'unknown'
        body['version'] = 2
        body['segments'][0]['split'] = 'train'
        with pytest.raises(urllib.error.HTTPError) as refused:
            request('/api/learning/omx/segments',body,token)
        assert refused.value.code == 400
    finally:
        server.shutdown();server.server_close();thread.join()


def test_collaboration_requires_manage_and_owns_segment_reviewer(tmp_path):
    from learning_workspace import Workspace
    from test_learning_collaboration import running, request
    with running(tmp_path) as (url, accounts, store):
        root = tmp_path / 'prepared'
        prepared(root)
        row = Workspace(store.db).register(dict(kind='omx', name='source', path=str(root)))
        decision = json.loads((root / 'decisions.json').read_text())[0]
        segment = {key: decision[key] for key in ('episode_index', 'frames', 'content_sha256', 'session_id', 'cycle_id')}
        segment.update(start_frame=2, end_frame=6, object='cube', intervention=False,
                       outcome='unknown', split='exclude', reviewer='forged', reason='uncertain retention')
        body = dict(id=row['id'], version=0, segments=[segment])
        assert request(url, '/api/learning/omx')[0] == 401
        for session in ('reader', 'editor'):
            _, workspace = request(url, '/api/workspace', session)
            assert request(url, '/api/learning/omx', session)[0] == 200
            assert request(url, '/api/learning/omx/segments', session, body, workspace['token'])[0] == 403
        _, workspace = request(url, '/api/workspace', 'reviewer')
        for invalid in (None, 42):
            assert request(url, '/api/learning/omx/segments', 'reviewer',
                           dict(body, segments=invalid), workspace['token'])[0] == 400
        _, listed = request(url, '/api/learning/omx', 'reviewer')
        assert listed['sets'][0]['segment_review']['version'] == 0
        status, saved = request(url, '/api/learning/omx/segments', 'reviewer', body, workspace['token'])
        assert status == 200 and saved['document']['segments'][0]['reviewer'] == 'reviewer'
        accounts.active = False
        body['version'] = 1
        assert request(url, '/api/learning/omx/segments', 'reviewer', body, workspace['token'])[0] == 403


def saved_review(tmp_path, root, segments):
    """Register a prepared folder and save one segment review the way /learning/omx does."""
    from types import SimpleNamespace
    from learning_workspace import Workspace
    import omx_web
    workspace = Workspace(tmp_path/'reviews.sqlite3')
    row = workspace.register(dict(kind='omx', name='source', path=str(root)))
    sent = []
    omx_web.post(SimpleNamespace(send=sent.append), '/api/learning/omx/segments',
                 dict(id=row['id'], version=0, segments=segments), workspace, ValueError)
    return workspace, row['id'], sent[0]


def test_dataset_step_reads_the_latest_saved_review_read_only_and_refuses_marked_or_missing(
        tmp_path, monkeypatch, capsys):
    import os
    import sqlite3
    import omx_web
    import native_segments
    root = tmp_path/'prepared'
    prepared(root)
    decision = json.loads((root/'decisions.json').read_text())[0]
    segment = {key: decision[key] for key in ('episode_index', 'frames', 'content_sha256', 'session_id', 'cycle_id')}
    segment.update(start_frame=2, end_frame=6, object='cube', intervention=False,
                   outcome='failure', split='exclude', reviewer='person', reason='dropped')
    workspace, identifier, saved = saved_review(tmp_path, root, [segment])
    other = tmp_path/'other'
    prepared(other)
    unsaved = workspace.register(dict(kind='omx', name='unsaved', path=str(other)))['id']
    empty = tmp_path/'empty.sqlite3'
    sqlite3.connect(empty).close()
    before = {db: (db.read_bytes(), os.stat(db).st_mtime_ns) for db in (workspace.db, empty)}
    # omx.js download bytes; the manual path json.loads this file
    downloaded = json.dumps(saved['document'], indent=2, ensure_ascii=False) + '\n'
    calls = []
    monkeypatch.setattr(native_segments, 'export_segments', lambda *args: calls.append(args))
    omx_web.export_saved(workspace.db, identifier, tmp_path/'out')
    assert calls == [(root, json.loads((root/'inspection.json').read_text()), json.loads(downloaded), tmp_path/'out')]
    monkeypatch.undo()
    (root/'DO_NOT_TRAIN.txt').write_text('leader never moved\n')
    with pytest.raises(SystemExit) as refused:
        omx_web.main(['export-segments', '--db', str(workspace.db), '--id', identifier, '--out', str(tmp_path/'out')])
    assert refused.value.code == 2 and 'DO_NOT_TRAIN' in capsys.readouterr().err and not (tmp_path/'out').exists()
    with pytest.raises(ValueError, match='saved segment review required'):
        omx_web.export_saved(workspace.db, unsaved, tmp_path/'out')
    with pytest.raises(ValueError, match='review database'):
        omx_web.export_saved(empty, identifier, tmp_path/'out')
    with pytest.raises(OSError):
        omx_web.export_saved(tmp_path/'missing.sqlite3', identifier, tmp_path/'out')
    assert not (tmp_path/'missing.sqlite3').exists()
    assert {db: (db.read_bytes(), os.stat(db).st_mtime_ns) for db in (workspace.db, empty)} == before


BYTE_DRIVER = r'''
import hashlib, json, pathlib, subprocess, sys
from types import SimpleNamespace
source, scratch = map(pathlib.Path, sys.argv[1:])
sys.path[:0] = [str(source/'learning/curation/perception'), str(source/'learning/curation/omx')]
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset
import omx_web, native_segments
from learning_workspace import Workspace
native = native_segments.native
features = {key: dict(dtype='float32', shape=(6,), names=native.JOINTS) for key in ('action', 'observation.state')}
features['observation.images.front'] = dict(dtype='video', shape=(32, 32, 3), names=['height', 'width', 'channels'])
root = scratch/'prepared'
writer = LeRobotDataset.create(repo_id='local/segment-source', root=root, fps=30, robot_type='omx_follower',
    features=features, use_videos=True, video_backend='pyav', vcodec='h264', batch_encoding_size=1)
try:
    for episode in range(2):
        for frame in range(8):
            writer.add_frame(dict(action=np.full(6, episode*10+frame, dtype=np.float32),
                **{'observation.state': np.full(6, episode*10+frame-1, dtype=np.float32),
                   'observation.images.front': np.full((32, 32, 3), frame*20, dtype=np.uint8)}, task='pick'))
        writer.save_episode(parallel_encoding=False)
finally:
    writer.finalize()
report = native.inspect_dataset(root, 'local/segment-source', body_units='normalized_-100_100',
                                rig_revision='rig', calibration_revision='cal', source_mode='leader_native')
native.write_json(root/'inspection.json', report)
native.write_json(root/'intake-receipt.json', dict(schema='rosy.omx-collection-intake.v1'))
segments = [dict(**{k: e[k] for k in ('episode_index', 'content_sha256', 'frames', 'session_id', 'cycle_id') if k in e},
                 start_frame=2, end_frame=5, object='큐브', intervention=False, outcome='success',
                 reviewer='human', reason='observed grasp', split=split)
            for e, split in zip(report['episodes'], ('train', 'eval'))]
workspace = Workspace(scratch/'reviews.sqlite3')
identifier = workspace.register(dict(kind='omx', name='source', path=str(root)))['id']
sent = []
omx_web.post(SimpleNamespace(send=sent.append), '/api/learning/omx/segments',
             dict(id=identifier, version=0, segments=segments), workspace, ValueError)
download = scratch/'omx-segments.json'  # the bytes omx.js downloads
download.write_text(json.dumps(sent[0]['document'], indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
db_before = workspace.db.read_bytes()
for command in ([source/'learning/curation/omx/native_segments.py', root, '--report', root/'inspection.json',
                 '--segments', download, '--out', scratch/'manual'],
                [source/'learning/curation/perception/omx_web.py', 'export-segments', '--db', workspace.db,
                 '--id', identifier, '--out', scratch/'db']):
    subprocess.run([sys.executable, '-B', *map(str, command)], check=True, timeout=600)
def files(side):
    return {p.relative_to(scratch/side).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ('train', 'eval') for p in sorted((scratch/side/name).rglob('*')) if p.is_file()}
reader = native.load_dataset(scratch/'db/train', 'local/segment-source_train')
print(json.dumps(dict(
    receipt_identical=(scratch/'manual/split-receipt.json').read_bytes() == (scratch/'db/split-receipt.json').read_bytes(),
    manual=files('manual'), db=files('db'), db_unchanged=workspace.db.read_bytes() == db_before,
    splits=json.loads((scratch/'db/split-receipt.json').read_text())['splits'],
    readback=[reader[i]['action'][0].item() for i in range(len(reader))])))
'''


def test_db_export_is_byte_identical_to_the_downloaded_json_export(tmp_path):
    """D-857 P0: the review DB path writes the same receipt and dataset bytes as the manual CLI.

    Runs the LeRobot part in the existing pinned learner venv (lerobot 0.4.4); the test venv has none.
    """
    import os
    import subprocess
    from pathlib import Path
    if os.environ.get('ROSY_RUN_PINNED_LEARNING') != '1':
        pytest.skip('explicit existing isolated learner environment required')
    python = Path.home()/'.local/share/rosy-learning-center/venv-cpu/bin/python'
    assert python.is_file(), 'existing pinned learner Python is unavailable'
    source = Path(__file__).resolve().parents[3]
    env = {key: os.environ[key] for key in ('HOME', 'PATH', 'USER', 'LOGNAME') if key in os.environ}
    env.update(HF_HUB_OFFLINE='1', HF_DATASETS_OFFLINE='1', CUDA_VISIBLE_DEVICES='', OMP_NUM_THREADS='2')
    with (tmp_path/'learner.log').open('wb') as log:
        result = subprocess.run([str(python), '-I', '-B', '-c', BYTE_DRIVER, str(source), str(tmp_path)],
                                stdout=log, stderr=subprocess.STDOUT, env=env, timeout=900, check=False)
    output = (tmp_path/'learner.log').read_text(errors='replace')
    assert result.returncode == 0, output[-4000:]
    proof = json.loads(output.splitlines()[-1])
    assert proof['receipt_identical'] and proof['db_unchanged']
    assert len(proof['db']) >= 10 and proof['manual'] == proof['db']  # every child file, byte for byte
    assert proof['splits'] == {'train': [0], 'eval': [1]}
    assert proof['readback'] == [2, 3, 4]  # same check as test_real_lerobot_segment_readback
