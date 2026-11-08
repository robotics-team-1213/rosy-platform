"""Ladder routes keep the review app's project/CSRF boundaries and write only a person's comparison record."""
import json
import os
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

import pytest

import ladder_web
from ladder_fixture import PNG, config, make_root
from learning_domains import ladder_stages
from review_app import make_server
from test_learning_collaboration import Accounts, request
from test_review_app import open_store

OLD, MID, NEW = '20261105T010000-aaaaaaaa', '20261106T010000-bbbbbbbb', '20261107T030000-cccccccc'
ROUNDS = {OLD: dict(placed=12), MID: dict(placed=40, parent=OLD), NEW: dict(placed=2, mujoco='failed')}


@contextmanager
def running(tmp_path, rounds=ROUNDS, *, configured=True):
    root = make_root(tmp_path, rounds)
    ladder = ladder_web.Ladder(config(tmp_path, root)) if configured else None
    server = make_server(open_store(tmp_path), 0, accounts=Accounts(), ladder=ladder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', root, ladder
    finally:
        server.shutdown(); server.server_close(); thread.join()


def post(base, path, body, session='reviewer', token=None):
    token = token or request(base, '/api/accounts/session', session)[1]['token']
    return request(base, '/api/learning/ladder/' + path, session, body, token)


def test_unconfigured_page_and_reads_say_so_and_writes_are_unavailable(tmp_path):
    with running(tmp_path, configured=False) as (base, root, _):
        code, data = request(base, '/api/learning/ladder/rounds', 'reader')
        assert code == 200 and data == {'configured': False, 'running': False, 'best_round_id': None, 'rounds': []}
        req = urllib.request.Request(base + '/learning/ladder', headers={'Cookie': 'rosy_learning_session=reader'})
        assert urllib.request.urlopen(req).status == 200
        assert post(base, 'start', {})[0] == 503 and post(base, 'decision', {})[0] == 503
        assert request(base, '/api/learning/ladder/rounds')[0] == 401


def two_arm_run(root, run_id, **fields):
    folder = root / 'two_arm' / run_id
    folder.mkdir(parents=True)
    value = dict(schema=ladder_web.TWO_ARM_SCHEMA, run_id=run_id, task='stack', seed=0, status='passed', steps=9, steps_pass=9,
                 final_ok=9, final_total=9, roll_below_floor_steps=['s1'], failed_steps=[], **fields)
    (folder / 'run.json').write_text(json.dumps(value), encoding='utf-8')


def test_learned_two_arm_rounds_are_read_through_a_whitelist_and_only_their_videos_are_served(tmp_path):
    with running(tmp_path) as (base, root, ladder):
        assert request(base, '/api/learning/ladder/two-arm-rounds', 'reader')[1] == {'rounds': []}
        folder = root / 'two_arm_rounds' / OLD
        (folder / 'artifacts').mkdir(parents=True)
        (folder / 'artifacts' / 'stack-seed0.mp4').write_bytes(b'video')
        (folder / 'artifacts' / 'other.txt').write_bytes(b'text')
        (folder / 'round.json').write_text(json.dumps(dict(
            schema=ladder_web.TWO_ARM_ROUND_SCHEMA, round_id=OLD, status='passed', stage='done', private_path='/home/secret', artifacts=['stack-seed0.mp4', '../evil.mp4', 'a.png'],
            eval=dict(n=21, passed=8, lifted=20, per_step={'stack/s1': 3}, whole=[dict(task='stack', seed=1, total=9, passed=2, completed=False)]))), encoding='utf-8')
        (root / 'two_arm_rounds' / NEW).mkdir()
        code, data = request(base, '/api/learning/ladder/two-arm-rounds', 'reader')
        assert code == 200 and [row['round_id'] for row in data['rounds']] == [NEW, OLD]
        assert data['rounds'][0] == {'round_id': NEW, 'unreadable': True}
        assert 'private_path' not in data['rounds'][1] and data['rounds'][1]['videos'] == ['stack-seed0.mp4']
        assert data['rounds'][1]['eval']['passed'] == 8 and data['rounds'][1]['eval']['whole'][0]['passed'] == 2
        artifacts = f'/api/learning/ladder/two-arm-rounds/{OLD}/artifacts/'
        assert request(base, artifacts + 'other.txt', 'reader')[0] == 404
        assert ladder.artifact(OLD, 'stack-seed0.mp4', 'two_arm_rounds') == (b'video', 'video/mp4')
        with pytest.raises(FileNotFoundError):
            ladder.artifact(OLD, 'stack-seed0.mp4', 'two_arm')


def test_two_arm_runs_are_read_through_a_whitelist_and_only_a_manager_starts_a_bounded_one(tmp_path, monkeypatch):
    with running(tmp_path) as (base, root, ladder):
        two_arm_run(root, OLD, private_path='/home/secret', views=['top.png', '../evil.png'])
        (root / 'two_arm' / OLD / 'artifacts').mkdir()
        (root / 'two_arm' / OLD / 'artifacts' / 'top.png').write_bytes(PNG)
        assert request(base, f'/api/learning/ladder/two-arm/{OLD}/artifacts/missing.png', 'reader')[0] == 404
        (root / 'two_arm' / NEW).mkdir()
        (root / 'two_arm' / NEW / 'run.json').write_text('{broken', encoding='utf-8')
        code, data = request(base, '/api/learning/ladder/two-arm', 'reader')
        assert code == 200 and data['running'] is False and [row['run_id'] for row in data['runs']] == [NEW, OLD]
        assert data['runs'][0] == {'run_id': NEW, 'unreadable': True}
        assert data['runs'][1]['steps_pass'] == 9 and data['runs'][1]['roll_below_floor_steps'] == ['s1'] and 'private_path' not in data['runs'][1]
        assert data['runs'][1]['views'] == ['top.png']
        started = []
        monkeypatch.setattr(ladder, 'spawn', lambda command, log: started.append(command) or type('P', (), dict(poll=lambda self: None))())
        assert post(base, 'two-arm', {'task': 'stack', 'seed': 1}, session='reader')[0] == 403
        for body in [{'task': 'stack'}, {'task': 'other', 'seed': 0}, {'task': ['stack'], 'seed': 0}, {'task': 'stack', 'seed': -1},
                     {'task': 'stack', 'seed': 1001}, {'task': 'stack', 'seed': True}, {'task': 'stack', 'seed': 0, 'out': '/tmp'}]:
            assert post(base, 'two-arm', body)[0] == 400, body
        assert started == []
        assert post(base, 'two-arm', {'task': 'rehandle', 'seed': 7})[0] == 200
        assert started[0][-4:] == ['--task', 'rehandle', '--seed', '7'] and started[0][2] == 'two-arm'
        assert post(base, 'two-arm', {'task': 'stack', 'seed': 0})[0] == 409, 'one at a time'
        assert request(base, '/api/learning/ladder/two-arm', 'reader')[1]['running'] is True


def test_one_arm_vs_two_arm_comparisons_are_whitelisted_their_videos_served_and_a_manager_starts_one(tmp_path, monkeypatch):
    with running(tmp_path) as (base, root, ladder):
        folder = root / 'two_arm_compare' / OLD
        (folder / 'artifacts').mkdir(parents=True)
        (folder / 'artifacts' / 'stack-two-arm.mp4').write_bytes(b'video')
        runs = [dict(scenario='outbound', mode='one-arm-B', concurrent=False, steps=5, steps_pass=5, completed=True, makespan_s=92.5,
                     holds=[dict(request='bar-3', reason='NO_STAND_IN_REACH')], moves_per_arm={'arm_b': 5}, log='/home/secret/run.log'),
                dict(scenario='stack', mode='two-arm', concurrent=True, steps=9, steps_pass=9, completed=True, makespan_s=148.8, overlap_s=15.1,
                     video='stack-two-arm.mp4'),
                dict(scenario='stack', mode='three-arm'), dict(scenario='other', mode='two-arm')]
        (folder / 'compare.json').write_text(json.dumps(dict(schema=ladder_web.TWO_ARM_COMPARE_SCHEMA, run_id=OLD, seed=0, status='passed',
                                                             runs=runs, videos=['stack-two-arm.mp4', '../evil.mp4'], private_path='/home/secret')), encoding='utf-8')
        code, data = request(base, '/api/learning/ladder/two-arm-compare', 'reader')
        row = data['runs'][0]
        assert code == 200 and data['running'] is False and 'private_path' not in row and row['videos'] == ['stack-two-arm.mp4']
        assert [(r['scenario'], r['mode']) for r in row['runs']] == [('outbound', 'one-arm-B'), ('stack', 'two-arm')]  # unknown modes dropped
        assert row['runs'][0]['holds'] == [{'request': 'bar-3', 'reason': 'NO_STAND_IN_REACH'}] and 'log' not in row['runs'][0]
        assert row['runs'][1]['concurrent'] is True and row['runs'][1]['overlap_s'] == 15.1
        assert ladder.artifact(OLD, 'stack-two-arm.mp4', 'two_arm_compare') == (b'video', 'video/mp4')
        assert request(base, f'/api/learning/ladder/two-arm-compare/{OLD}/artifacts/missing.mp4', 'reader')[0] == 404
        started = []
        monkeypatch.setattr(ladder, 'spawn', lambda command, log: started.append(command) or type('P', (), dict(poll=lambda self: None))())
        assert post(base, 'two-arm-compare', {'seed': 0}, session='reader')[0] == 403
        for body in [{}, {'seed': -1}, {'seed': 1001}, {'seed': True}, {'seed': 0, 'out': '/tmp'}]:
            assert post(base, 'two-arm-compare', body)[0] == 400, body
        assert post(base, 'two-arm-compare', {'seed': 3})[0] == 200
        assert started[0][2] == 'two-arm-compare' and started[0][-2:] == ['--seed', '3']
        assert post(base, 'two-arm', {'task': 'stack', 'seed': 0})[0] == 409, 'one two-arm job at a time'


def test_a_recorded_same_seed_comparison_wins_over_intervals_from_different_seeds(tmp_path):
    with running(tmp_path) as (base, root, _):
        file = root / 'rounds' / MID / 'round.json'
        record = json.loads(file.read_text(encoding='utf-8'))
        record['comparison'] = dict(against=OLD, same_seeds=True, result='unclear', parent_eval=dict(n=50, strict=dict(placed=38)))
        file.write_text(json.dumps(record), encoding='utf-8')
        assert post(base, 'decision', {'round_id': OLD, 'verdict': 'replace', 'note': '기준'})[0] == 200
        rows = {row['round_id']: row for row in request(base, '/api/learning/ladder/rounds', 'reader')[1]['rounds']}
        assert rows[MID]['comparison'] == 'unclear' and rows[MID]['same_seeds'] is True, 'its intervals alone would say better'
        assert rows[MID]['paired'] == dict(against=OLD, result='unclear', placed=38, n=50)
        record['comparison']['same_seeds'] = False
        file.write_text(json.dumps(record), encoding='utf-8')
        rows = {row['round_id']: row for row in request(base, '/api/learning/ladder/rounds', 'reader')[1]['rounds']}
        assert rows[MID]['paired'] is None and rows[MID]['comparison'] == 'better'


def test_rounds_list_newest_first_and_a_corrupt_record_is_unreadable_not_fatal(tmp_path):
    with running(tmp_path) as (base, root, _):
        bad = '20261108T010000-dddddddd'
        (root / 'rounds' / bad).mkdir()
        (root / 'rounds' / bad / 'round.json').write_text('{not json', encoding='utf-8')
        (root / 'rounds' / 'notes').mkdir()
        code, data = request(base, '/api/learning/ladder/rounds', 'reader')
        assert code == 200 and [row['round_id'] for row in data['rounds']] == [bad, NEW, MID, OLD]
        assert data['rounds'][0] == {'round_id': bad, 'unreadable': True}
        assert data['rounds'][3]['stages']['gazebo']['reason'] and data['rounds'][3]['stages']['isaac']['status'] == 'not_run'
        assert request(base, '/api/learning/ladder/rounds/' + bad, 'reader')[1]['round']['unreadable'] is True
        assert request(base, '/api/learning/ladder/rounds/not-a-round', 'reader')[0] == 404


def test_unexpected_json_shapes_are_unreadable_or_sanitised(tmp_path):
    with running(tmp_path) as (base, root, _):
        weird = '20261108T010000-dddddddd'
        (root / 'rounds' / weird).mkdir()
        (root / 'rounds' / weird / 'round.json').write_text('[1,2]', encoding='utf-8')
        record = json.loads((root / 'rounds' / OLD / 'round.json').read_text(encoding='utf-8'))
        record['stages'] = {'mujoco': 'x', 'gazebo': {'status': 'bogus', 'artifacts': [{'path': '../../etc/passwd'}, 7]}}
        record['scene'] = {'robot': {'nested': [1]}}
        (root / 'rounds' / OLD / 'round.json').write_text(json.dumps(record), encoding='utf-8')
        rows = {row['round_id']: row for row in request(base, '/api/learning/ladder/rounds', 'reader')[1]['rounds']}
        assert rows[weird]['unreadable'] and rows[OLD]['stages']['gazebo']['artifacts'] == []
        assert rows[OLD]['stages']['gazebo']['status'] == 'unknown' and rows[OLD]['stages']['mujoco']['status'] == 'unknown'


def test_comparison_is_decided_only_by_separated_intervals():
    def row(placed, n=50):
        return {'stages': {'mujoco': {'eval': {'n': n, 'strict': {'placed': placed}}}}}
    assert ladder_web.verdict(row(45), row(5)) == 'better'
    assert ladder_web.verdict(row(5), row(45)) == 'worse'
    assert ladder_web.verdict(row(12), row(15)) == 'unclear'
    assert ladder_web.verdict({'stages': {'mujoco': {}}}, row(5)) == 'unclear' and ladder_web.verdict(row(5), None) == 'unclear'


def test_decision_records_actor_from_session_and_copies_best(tmp_path):
    with running(tmp_path) as (base, root, _):
        note = '엄격 성공이 더 높다'
        for session in ('reader', 'editor'):
            assert post(base, 'decision', {'round_id': OLD, 'verdict': 'replace', 'note': note}, session)[0] == 403
        assert post(base, 'decision', {'round_id': OLD, 'verdict': 'replace', 'note': note}, token='bad')[0] == 403
        for body in [{'round_id': OLD, 'verdict': 'replace', 'note': note, 'by': 'mallory'},
                     {'round_id': OLD, 'verdict': 'replace', 'note': ' '}, {'round_id': OLD, 'verdict': 'replace', 'note': 'a\nb'},
                     {'round_id': OLD, 'verdict': 'approve', 'note': note},
                     {'round_id': '20269999T000000-00000000', 'verdict': 'replace', 'note': note},
                     {'round_id': NEW, 'verdict': 'replace', 'note': note}]:
            assert post(base, 'decision', body)[0] == 400
        assert not (root / 'decisions.jsonl').exists() and not (root / 'best.json').exists()
        code, row = post(base, 'decision', {'round_id': OLD, 'verdict': 'replace', 'note': note})
        assert code == 200 and row['by'] == 'reviewer' and row['best_before'] is None
        assert json.loads((root / 'best.json').read_text()) == {'round_id': OLD}
        code, row = post(base, 'decision', {'round_id': MID, 'verdict': 'keep', 'note': '근거 부족'})
        assert row['best_before'] == OLD and json.loads((root / 'best.json').read_text()) == {'round_id': OLD}
        post(base, 'decision', {'round_id': MID, 'verdict': 'replace', 'note': '구간이 겹치지 않는다'})
        lines = (root / 'decisions.jsonl').read_text(encoding='utf-8').splitlines()
        assert [json.loads(line)['verdict'] for line in lines] == ['replace', 'keep', 'replace']
        data = request(base, '/api/learning/ladder/rounds', 'reader')[1]
        assert data['best_round_id'] == MID and data['rounds'][1]['comparison'] == 'current'
        assert data['rounds'][2]['comparison'] == 'worse' and data['rounds'][0]['comparison'] == 'worse'
        detail = request(base, '/api/learning/ladder/rounds/' + MID, 'reader')[1]
        assert len(detail['decisions']) == 2


def test_artifacts_serve_images_inside_the_round_only(tmp_path):
    with running(tmp_path) as (base, root, _):
        folder = root / 'rounds' / OLD / 'artifacts'
        (folder / 'report.json').write_text('{}', encoding='utf-8')
        (folder / 'x.svg').write_text('<svg/>', encoding='utf-8')
        outside = tmp_path / 'secret.png'
        outside.write_bytes(PNG)
        (folder / 'link.png').symlink_to(outside)
        (folder / 'dir').symlink_to(tmp_path, target_is_directory=True)
        (tmp_path / 'inner.png').write_bytes(PNG)
        def fetch(rel):
            req = urllib.request.Request(base + f'/api/learning/ladder/rounds/{OLD}/artifacts/{rel}',
                                         headers={'Cookie': 'rosy_learning_session=reader'})
            try:
                with urllib.request.urlopen(req) as response:
                    return response.status, response.headers.get_content_type(), response.read()
            except urllib.error.HTTPError as error:
                return error.code, None, None
        assert fetch('top.png') == (200, 'image/png', PNG)
        for rel in ('report.json', 'x.svg', 'link.png', 'dir/inner.png', '%2e%2e/round.json', '../round.json', 'missing.png', '.hidden.png'):
            assert fetch(rel)[0] == 404, rel


def test_start_is_bounded_fixed_and_single(tmp_path, monkeypatch):
    script = tmp_path / 'fake_ladder.py'
    script.write_text("import json,sys,time\nopen(sys.argv[sys.argv.index('--root')+1]+'/argv.json','w').write(json.dumps(sys.argv[1:]))\ntime.sleep(5)\n")
    monkeypatch.setattr(ladder_web, 'ENTRY', script)
    with running(tmp_path) as (base, root, ladder):
        good = {'episodes': 5, 'eval_episodes': 3, 'steps': 100, 'lr': 1e-5, 'parent': OLD}
        for session in ('reader', 'editor'):
            assert post(base, 'start', good, session)[0] == 403
        for change in ({'episodes': 0}, {'episodes': True}, {'eval_episodes': 501}, {'steps': 1.5}, {'lr': 1}, {'lr': 'x'},
                       {'parent': '../../x'}, {'parent': '20269999T000000-00000000'}, {'cmd': 'rm'}, {'python': '/bin/sh'}, {'root': '/'}):
            assert post(base, 'start', {**good, **change})[0] == 400, change
        assert ladder.process is None
        try:
            assert post(base, 'start', good) == (200, {'started': True})
            code, data = post(base, 'start', good)
            assert code == 409 and '실행 중' in data['error']
            assert request(base, '/api/learning/ladder/rounds', 'reader')[1]['running'] is True
            for _ in range(100):
                if (root / 'argv.json').exists():
                    break
                threading.Event().wait(0.05)
            argv = json.loads((root / 'argv.json').read_text())
            assert argv[:5] == ['round', '--root', str(root), '--cell', str(tmp_path / 'cell')]
            assert argv[argv.index('--parent') + 1] == OLD and argv[argv.index('--episodes') + 1] == '5'
            assert argv[argv.index('--lr') + 1] == '1e-05' and argv[argv.index('--lerobot-train') + 1] == str(tmp_path / 'lerobot-train')
        finally:
            ladder.process.kill(); ladder.process.wait()


def test_home_loop_row_reads_the_ladder_without_claiming_a_decision():
    assert ladder_stages(None) == {}
    stages = ladder_stages({'rounds': 3, 'best': OLD, 'running': True})
    assert stages['train'][0] == 'active' and OLD in stages['train'][1] and '실행 중' in stages['train'][1]
    assert ladder_stages({'rounds': 0, 'best': None, 'running': False})['train'][0] == 'active'
    assert ladder_stages({'error': 'unavailable'})['train'][0] == 'blocked'
    assert not any(word in str(stages) for word in ('승인', '승격'))


def test_config_must_be_absolute_and_exact(tmp_path):
    good = config(tmp_path, tmp_path)
    ladder_web.Ladder(good)
    for bad in ({**good, 'root': 'relative'}, {k: v for k, v in good.items() if k != 'cell'}, {**good, 'extra': '/x'}):
        with pytest.raises(ValueError):
            ladder_web.Ladder(bad)
