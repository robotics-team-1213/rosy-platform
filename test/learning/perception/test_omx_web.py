"""D-792 S4: the read-only OMX page lists registered intake folders without exposing host paths."""
import json
import threading
import urllib.request

from review_app import ReviewStore, make_server
from test_review_return import fixture_inputs


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
