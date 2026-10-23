"""VLM question truth: people label, models are only compared (D-475, D-514, D-542)."""
import hashlib
import json
import threading
import urllib.request
from contextlib import contextmanager

import pytest

import vlm_judge
from review_app import make_server
from review_store import Conflict
from test_learning_collaboration import Accounts, request
from test_review_app import open_store

QUESTIONS = {'wrist': {'wrist.object_in_gripper': ['Is an object held between the gripper fingers?', ['yes', 'no', 'unclear']],
                       'wrist.gripper_empty': ['Is the gripper empty?', ['yes', 'no', 'unclear']]},
             'front': {'front.lane_tape': ['Which lane boundary tapes are visible on the floor?', ['both', 'left', 'right', 'none']]}}


def answer(value, size=3):
    return {'answer': value, 'p': [round(1 / size, 4)] * size, 'mass': 0.9, 's': 0.01}


def wrist(frame, held, empty, **extra):
    return {'frame': frame, 'view': 'wrist', 'long_side': 0, 'size': [4, 4], 'preprocess_s': 0.0, 'timings': {},
            'answers': {'wrist.object_in_gripper': answer(held), 'wrist.gripper_empty': answer(empty)}, **extra}


def bench(tmp_path, rows):
    for name in ('a.jpg', 'b.jpg', 'c.jpg'):
        (tmp_path / name).write_bytes(b'\xff\xd8' + name.encode())
    path = tmp_path / 'rows.jsonl'
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return {'rows_path': str(path), 'question_set': 'v2', 'questions': QUESTIONS, 'model': 'qwen3-vl-8b'}


ROWS = [wrist('a.jpg', 'yes', 'yes', ollama_questions={'answers': {'wrist.object_in_gripper': answer('none_in_top'),
                                                                  'wrist.gripper_empty': answer('no')}}),
        wrist('b.jpg', 'no', 'yes'), wrist('c.jpg', 'yes', 'no'),
        {'frame': 'a.jpg', 'view': 'front', 'long_side': 448, 'answers': {'front.lane_tape': answer('both', 4)}}]


def label(store, identifier, status='labelled', **answers):
    return vlm_judge.save(store, identifier, {'version': vlm_judge.item(store, identifier)['version'],
                                              'status': status, 'answers': answers}, Conflict, actor='kim')


def test_import_is_idempotent_and_adds_only_new_model_answers(tmp_path):
    store, body = open_store(tmp_path), bench(tmp_path, ROWS)
    first = vlm_judge.import_rows(store, body)
    assert (first['items_added'], first['answers_added']) == (4, 2 + 2 + 2 + 2 + 1)
    label(store, 1, **{'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': 'no'})
    again = vlm_judge.import_rows(store, body)
    assert (again['items_added'], again['items_existing'], again['answers_added']) == (0, 4, 0)
    other = vlm_judge.import_rows(store, dict(body, model='other-model'))
    assert (other['items_added'], other['answers_added']) == (0, 9)
    assert vlm_judge.item(store, 1)['version'] == 1 and len(vlm_judge.items(store)) == 4
    with pytest.raises(ValueError, match='new version'):
        changed = json.loads(json.dumps(QUESTIONS))
        changed['wrist']['wrist.gripper_empty'][0] = 'Is the gripper open?'
        vlm_judge.import_rows(store, dict(body, questions=changed))
    stored = store.state / 'vlm' / 'images' / (hashlib.sha256(b'\xff\xd8a.jpg').hexdigest() + '.jpg')
    assert stored.read_bytes() == b'\xff\xd8a.jpg'


@pytest.mark.parametrize('row, message', [
    (dict(wrist('a.jpg', 'maybe', 'no')), 'not one of its options'),
    (dict(wrist('a.jpg', 'yes', 'no'), view='side'), 'view must be one of'),
    (dict(wrist('missing.jpg', 'yes', 'no')), 'existing JPEG'),
    (dict(wrist('a.jpg', 'yes', 'no'), answers={'wrist.gripper_empty': answer('no')}), 'exactly the question set'),
])
def test_import_refuses_bad_rows_before_writing(tmp_path, row, message):
    store = open_store(tmp_path)
    with pytest.raises(ValueError, match=message):
        vlm_judge.import_rows(store, bench(tmp_path, [ROWS[1], row]))
    assert vlm_judge.items(store) == []
    for bad in [{'wrist': {'wrist.x': ['text', ['yes']]}}, {'Bad View': {}}, []]:
        with pytest.raises(ValueError):
            vlm_judge.import_rows(store, dict(bench(tmp_path, ROWS), questions=bad))
    with pytest.raises(ValueError):
        vlm_judge.import_rows(store, dict(bench(tmp_path, ROWS), rows_path=str(tmp_path / 'none.jsonl')))


def test_labels_need_every_answer_and_current_version(tmp_path):
    store = open_store(tmp_path)
    vlm_judge.import_rows(store, bench(tmp_path, ROWS))
    with pytest.raises(ValueError, match='모든 질문'):
        label(store, 1, **{'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': None})
    with pytest.raises(ValueError, match='options'):
        label(store, 1, **{'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': 'maybe'})
    excluded = label(store, 1, 'excluded', **{'wrist.object_in_gripper': None, 'wrist.gripper_empty': None})
    assert (excluded['status'], excluded['version'], excluded['actor']) == ('excluded', 1, 'kim')
    with pytest.raises(Conflict):
        vlm_judge.save(store, 1, {'version': 0, 'status': 'excluded', 'answers': excluded['answers']}, Conflict)
    with store.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM vlm_label_events').fetchone()[0] == 1


def test_evaluation_counts_labelled_photos_only(tmp_path):
    store = open_store(tmp_path)
    vlm_judge.import_rows(store, bench(tmp_path, ROWS))
    label(store, 1, **{'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': 'no'})
    label(store, 2, **{'wrist.object_in_gripper': 'no', 'wrist.gripper_empty': 'unclear'})
    label(store, 3, 'excluded', **{'wrist.object_in_gripper': None, 'wrist.gripper_empty': None})
    result = vlm_judge.evaluation(store)
    assert result['labelled'] == 2
    hf = next(m for m in result['models'] if m['runtime'] == 'transformers')
    assert hf['contradictions'] == 1  # photo 1 only; photo 3's yes/no is excluded and photo 2 is no/yes
    rows = {q['question']: q for q in hf['questions']}
    held = rows['wrist.object_in_gripper']
    assert (held['n'], held['agreement'], held['balanced_accuracy']) == (2, 1.0, 1.0)
    empty = rows['wrist.gripper_empty']
    # human no -> model yes, human unclear -> model yes: recall 0 for both present classes.
    assert (empty['agreement'], empty['balanced_accuracy']) == (0.0, 0.0)
    assert empty['confusion']['unclear']['yes'] == 1 and empty['confusion']['no']['yes'] == 1
    ollama = next(m for m in result['models'] if m['runtime'] == 'ollama')
    missing = {q['question']: q for q in ollama['questions']}['wrist.object_in_gripper']
    assert (missing['n'], missing['missing'], missing['agreement']) == (0, 1, None)
    human = {row['question']: row for row in result['human']}
    assert human['wrist.gripper_empty']['unclear_rate'] == 0.5
    label(store, 4, **{'front.lane_tape': 'left'})
    tape = {q['question']: q for m in vlm_judge.evaluation(store)['models'] for q in m['questions']}['front.lane_tape']
    assert tape['balanced_accuracy'] == 0.0 and tape['n'] == 1


def test_export_hash_and_image_hash_check(tmp_path):
    store = open_store(tmp_path)
    vlm_judge.import_rows(store, bench(tmp_path, ROWS))
    label(store, 2, **{'wrist.object_in_gripper': 'no', 'wrist.gripper_empty': 'yes'})
    exported = vlm_judge.export(store)
    assert exported['count'] == 1 and hashlib.sha256(exported['jsonl'].encode()).hexdigest() == exported['sha256']
    row = json.loads(exported['jsonl'])
    assert set(row) == {'image_sha256', 'view', 'question_set', 'answers', 'status', 'actor', 'version'}
    data, mime, digest = vlm_judge.image(store, 2)
    assert mime == 'image/jpeg' and hashlib.sha256(data).hexdigest() == digest
    (store.state / 'vlm' / 'images' / (digest + '.jpg')).write_bytes(b'changed')
    with pytest.raises(ValueError, match='differs'):
        vlm_judge.image(store, 2)


@contextmanager
def running(tmp_path, accounts=True):
    store = open_store(tmp_path)
    body = bench(tmp_path, ROWS)
    server = make_server(store, 0, accounts=Accounts() if accounts else None)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', store, body
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_http_permissions_conflict_and_hidden_model_answers(tmp_path):
    with running(tmp_path) as (base, store, body):
        assert request(base, '/api/learning/vlm/summary')[0] == 401
        _, editor = request(base, '/api/learning/vlm/summary', 'editor')
        assert request(base, '/api/learning/vlm/import', 'editor', body, editor['token'])[0] == 403
        _, manager = request(base, '/api/learning/vlm/summary', 'reviewer')
        assert request(base, '/api/learning/vlm/import', 'reviewer', body, manager['token'])[0] == 403
        assert vlm_judge.items(store) == []  # server paths are imported by the CLI on that server only
        vlm_judge.import_rows(store, body)
        code, listed = request(base, '/api/learning/vlm/items?view=wrist&status=pending', 'reader')
        assert code == 200 and [row['id'] for row in listed['items']] == [1, 2, 3]
        code, one = request(base, '/api/learning/vlm/items/1', 'reader')
        assert code == 200 and one['questions'][0]['id'] == 'wrist.object_in_gripper'
        for text in (json.dumps(listed), json.dumps(one)):
            assert 'qwen3' not in text and '"p"' not in text and str(tmp_path) not in text
        answers = {'wrist.object_in_gripper': 'yes', 'wrist.gripper_empty': 'no'}
        save = {'version': 0, 'status': 'labelled', 'answers': answers}
        _, reader = request(base, '/api/learning/vlm/summary', 'reader')
        assert request(base, '/api/learning/vlm/items/1', 'reader', save, reader['token'])[0] == 403
        code, saved = request(base, '/api/learning/vlm/items/1', 'editor', save, editor['token'])
        assert code == 200 and (saved['version'], saved['actor']) == (1, 'editor')
        code, error = request(base, '/api/learning/vlm/items/1', 'editor', save, editor['token'])
        assert code == 409 and '다시 불러오세요' in error['error']
        assert request(base, '/api/learning/vlm/items?status=done', 'reader')[0] == 400
        code, evaluation = request(base, '/api/learning/vlm/evaluation', 'reader')
        assert code == 200 and evaluation['labelled'] == 1
        code, exported = request(base, '/api/learning/vlm/export', 'reader')
        assert code == 200 and exported['count'] == 1
        req = urllib.request.Request(base + '/api/learning/vlm/images/1', headers={'Cookie': 'rosy_learning_session=reader'})
        with urllib.request.urlopen(req) as response:
            raw = response.read()
            assert response.headers['ETag'] == '"' + hashlib.sha256(raw).hexdigest() + '"'
            assert response.headers['Cache-Control'] == 'no-cache'


def test_local_mode_has_no_actor_and_serves_the_page(tmp_path):
    with running(tmp_path, accounts=False) as (base, store, body):
        _, summary = request(base, '/api/learning/vlm/summary')
        assert request(base, '/api/learning/vlm/import', body=body, token='wrong')[0] == 403
        assert request(base, '/api/learning/vlm/import', body=body, token=summary['token'])[0] == 200
        answers = {'wrist.object_in_gripper': None, 'wrist.gripper_empty': None}
        code, saved = request(base, '/api/learning/vlm/items/2', body={'version': 0, 'status': 'excluded', 'answers': answers},
                              token=summary['token'])
        assert code == 200 and saved['actor'] is None
        for path, marker in [('/learning/vlm', 'Rosy Learning — VLM 판단'), ('/vlm.js', '/api/learning/vlm/'),
                             ('/vlm.css', '.vlm-work'), ('/learning-shell.js', '/learning/vlm'),
                             ('/learning/evaluate', 'Rosy Learning — 평가·승격'), ('/evaluate.js', '/api/learning/vlm/evaluation')]:
            with urllib.request.urlopen(base + path) as response:
                assert marker in response.read().decode('utf-8')
