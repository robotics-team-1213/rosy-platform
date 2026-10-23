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
    assert set(row) == {'image_sha256', 'view', 'question_set', 'answers', 'status', 'tiers', 'actor', 'version'}
    assert row['tiers'] == {'wrist.object_in_gripper': 'confirmed', 'wrist.gripper_empty': 'confirmed'}
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


# D-857 §4-5: provisional (model consensus) vs confirmed (human) truth and the small human queue.
HELD = 'wrist.object_in_gripper'


def consensus_store(tmp_path, count, models=(('m1', 'transformers', 0.9), ('m2', 'transformers', 0.85))):
    """count wrist photos with one question; every model answers yes on odd and no on even photos."""
    store = open_store(tmp_path)
    vlm_judge.configure(store)
    question = json.dumps([{'id': HELD, 'text': 'held?', 'options': ['yes', 'no', 'unclear']}])
    with store.connect() as db:
        for number in range(1, count + 1):
            db.execute('INSERT INTO vlm_items (view, image_sha256, image_name, question_set, questions, source) '
                       'VALUES (?,?,?,?,?,?)', ('wrist', f'{number:064x}', f'{number}.jpg', 'v2', question, '{}'))
            for model, runtime, p in models:
                put(db, number, model, runtime, 'yes' if number % 2 else 'no', p)
    return store


def put(db, item, model, runtime, value, p):
    probs = {'yes': [p, 1 - p, 0], 'no': [1 - p, p, 0], 'unclear': [0, 1 - p, p]}[value]
    db.execute('INSERT OR REPLACE INTO vlm_model_answers VALUES (?,?,?,?,?,?)',
               (item, model, runtime, HELD, value, json.dumps(probs)))


def test_consensus_counts_one_model_once_and_any_dissent_breaks_it(tmp_path):
    store = consensus_store(tmp_path, 6, models=())
    cases = {1: [('m1', 'transformers', 'yes', 0.9), ('m1', 'ollama', 'yes', 0.95)],  # one model, two runtimes
             2: [('m1', 'transformers', 'yes', 0.9), ('m1@448', 'transformers', 'yes', 0.9)],  # same model, other size
             3: [('m1', 'transformers', 'yes', 0.9), ('m2', 'ollama', 'yes', 0.85)],
             4: [('m1', 'transformers', 'yes', 0.9), ('m2', 'transformers', 'yes', 0.85), ('m3', 'transformers', 'no', 0.4)],
             5: [('m1', 'transformers', 'yes', 0.9), ('m2', 'transformers', 'yes', 0.7)],  # m2 is unsure
             6: [('m1', 'transformers', 'yes', 0.5), ('m1', 'ollama', 'yes', 0.9), ('m2', 'transformers', 'yes', 0.8)]}
    with store.connect() as db:
        for item, rows in cases.items():
            for model, runtime, value, p in rows:
                put(db, item, model, runtime, value, p)
        db.execute('INSERT INTO vlm_model_answers VALUES (6, ?, ?, ?, NULL, ?)', ('m3', 'ollama', HELD, json.dumps([0, 0, 0])))
        # 6: the best runtime speaks for m1, and a missing answer is no vote.
        assert vlm_judge.provisional(db) == {3: {HELD: 'yes'}, 6: {HELD: 'yes'}}


def test_queue_is_deterministic_balanced_capped_and_blind(tmp_path, monkeypatch):
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W43')
    store = consensus_store(tmp_path, 120)
    first = vlm_judge.queue(store)
    full = {'eval': 30, 'disputed': 0, 'audit': 10, 'eval_size': 30, 'eval_done': 0, 'disputed_waiting': 0}
    assert first == vlm_judge.queue(store) and first['counts'] == {'wrist': full}
    evaluation = [row['id'] for row in first['items'] if row['kind'] == 'eval']
    assert sum(identifier % 2 for identifier in evaluation) == 15  # balanced over the provisional yes/no patterns
    with store.connect() as db:  # a third model dissents on 12 photos outside that set
        for number in [n for n in range(1, 121) if n not in evaluation][:12]:
            put(db, number, 'm3', 'transformers', 'unclear', 0.6)
    queue = vlm_judge.queue(store)  # the frozen set does not move when a model is added
    assert [row['id'] for row in queue['items'] if row['kind'] == 'eval'] == evaluation
    assert queue['counts'] == {'wrist': dict(full, disputed=12)}
    for kind in ('eval', 'disputed'):
        shown = vlm_judge.item(store, next(row['id'] for row in queue['items'] if row['kind'] == kind))
        assert shown['kind'] == kind and 'provisional' not in shown  # blind
    audit = vlm_judge.item(store, next(row['id'] for row in queue['items'] if row['kind'] == 'audit'))
    assert audit['provisional'] == {HELD: 'yes' if audit['id'] % 2 else 'no'} and audit['answers'] == {HELD: None}
    monkeypatch.setattr(vlm_judge, 'QUEUE_CAP', 15)  # 12 disputed open: room for 3 audits; the set is not counted
    assert vlm_judge.queue(store)['counts']['wrist'] == dict(full, disputed=12, audit=3)
    monkeypatch.setattr(vlm_judge, 'QUEUE_CAP', 12)
    assert vlm_judge.queue(store)['counts']['wrist']['audit'] == 0
    monkeypatch.setattr(vlm_judge, 'QUEUE_CAP', 5)  # disputed photos are capped too; the oldest open first
    capped = vlm_judge.queue(store)
    assert capped['counts']['wrist'] == dict(full, disputed=5, audit=0, disputed_waiting=7)
    opened = [row['id'] for row in capped['items'] if row['kind'] == 'disputed']
    assert opened == sorted(row['id'] for row in queue['items'] if row['kind'] == 'disputed')[:5]
    monkeypatch.setattr(vlm_judge, 'QUEUE_CAP', 50)
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W44')
    assert vlm_judge.queue(store)['counts']['wrist']['audit'] == 10


def test_evaluation_set_is_30_photos_per_view_frozen_and_topped_up_after_exclusion(tmp_path):
    store = consensus_store(tmp_path, 135, models=())  # no model answers yet: every photo is one pattern
    with store.connect() as db:  # a front view whose 40 photos each have two questions
        question = json.dumps([{'id': 'front.a', 'text': 'a?', 'options': ['yes', 'no']},
                               {'id': 'front.b', 'text': 'b?', 'options': ['yes', 'no']}])
        for number in range(136, 176):
            db.execute('INSERT INTO vlm_items (view, image_sha256, image_name, question_set, questions, source) '
                       'VALUES (?,?,?,?,?,?)', ('front', f'{number:064x}', f'{number}.jpg', 'v2', question, '{}'))
    first = vlm_judge.queue(store)
    sets = {view: [row['id'] for row in first['items'] if row['view'] == view and row['kind'] == 'eval']
            for view in ('front', 'wrist')}
    assert {view: len(ids) for view, ids in sets.items()} == {'front': 30, 'wrist': 30}
    assert all(row['kind'] == 'disputed' for row in first['items'] if row['id'] not in sets['front'] + sets['wrist'])
    with store.connect() as db:  # models arrive afterwards and agree on everything
        for number in range(1, 136):
            for model in ('m1', 'm2'):
                put(db, number, model, 'transformers', 'yes', 0.9)
    again = vlm_judge.queue(store, 'wrist')
    assert sorted(row['id'] for row in again['items'] if row['kind'] == 'eval') == sorted(sets['wrist'])
    gone = sets['wrist'][0]
    label(store, gone, 'excluded', **{HELD: None})
    label(store, sets['wrist'][1], **{HELD: 'yes'})
    topped = vlm_judge.queue(store, 'wrist')
    members = [row['id'] for row in topped['items'] if row['kind'] == 'eval']
    assert gone not in members and len(members) == 29 and set(sets['wrist'][2:]) <= set(members)
    assert topped['counts']['wrist']['eval_size'] == 30 and topped['counts']['wrist']['eval_done'] == 1
    with store.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM vlm_eval_set WHERE view='wrist'").fetchone()[0] == 31


def test_audits_confirm_or_fix_and_pause_a_question(tmp_path, monkeypatch):
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W43')
    store = consensus_store(tmp_path, 120)
    exported = [json.loads(line) for line in vlm_judge.export(store)['jsonl'].splitlines()]
    assert len(exported) == 120 and {row['status'] for row in exported} == {'provisional'}
    assert {row['tiers'][HELD] for row in exported} == {'provisional'}

    def audit(fix):
        queue = vlm_judge.queue(store)['items']
        shown = vlm_judge.item(store, next(row['id'] for row in queue if row['kind'] == 'audit'))
        answer = {HELD: 'unclear'} if fix else shown['provisional']
        return vlm_judge.save(store, shown['id'], {'version': 0, 'status': 'labelled', 'answers': answer},
                              Conflict, actor='kim')

    for fix in (False, True, False, False):
        assert audit(fix)['status'] == 'labelled'
    excluded = next(row['id'] for row in vlm_judge.queue(store)['items'] if row['kind'] == 'audit')
    label(store, excluded, 'excluded', **{HELD: None})  # an exclusion is not an audit
    assert vlm_judge.queue(store)['paused'] == [] and vlm_judge.evaluation(store)['audits'][0]['n'] == 4
    audit(True)  # 2 of 5 wrong: 40% > 10%
    queue, result = vlm_judge.queue(store), vlm_judge.evaluation(store)
    assert queue['paused'] == [HELD] and queue['counts']['wrist']['audit'] == 0
    assert result['audits'] == [{'question': HELD, 'n': 5, 'errors': 2, 'rate': 0.4, 'paused': True}]
    assert result['paused'] == [HELD] and result['provisional'][0]['provisional'] == 0
    assert result['labelled'] == 5  # confirmed answers include the confirmed and the fixed audits
    rows = [json.loads(line) for line in vlm_judge.export(store)['jsonl'].splitlines()]
    assert {row['status'] for row in rows} == {'labelled', 'excluded'}  # paused provisional answers are not used
    assert {row['tiers'][HELD] for row in rows} == {'confirmed', None}


def test_http_queue_audit_payload_and_eval_link(tmp_path, monkeypatch):
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W43')
    monkeypatch.setattr(vlm_judge, 'EVAL_SET_SIZE', 1)
    store = consensus_store(tmp_path, 3)
    with pytest.raises(ValueError, match='http'):
        make_server(store, 0, vlm_eval_url='file:///etc/passwd')
    server = make_server(store, 0, vlm_eval_url='https://model-pc.example:9445/learning/vlm')
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        code, queue = request(base, '/api/learning/vlm/queue?view=wrist')
        assert code == 200 and queue['counts'] == {'wrist': {'eval': 1, 'disputed': 0, 'audit': 2, 'eval_size': 1, 'eval_done': 0, 'disputed_waiting': 0}}
        assert request(base, '/api/learning/vlm/queue?view=Bad%20View')[0] == 400
        assert request(base, '/api/learning/vlm/queue?other=1')[0] == 400
        kinds = {row['kind']: row['id'] for row in queue['items']}
        assert 'provisional' not in request(base, '/api/learning/vlm/items/%d' % kinds['eval'])[1]
        assert set(request(base, '/api/learning/vlm/items/%d' % kinds['audit'])[1]['provisional']) == {HELD}
        code, workspace = request(base, '/api/learning')
        assert workspace['vlm_eval_url'] == 'https://model-pc.example:9445/learning/vlm'
        vlm = next(row for row in workspace['domains'] if row['id'] == 'vlm')
        assert vlm['stages'][1]['evidence'] == '확정 0 · 미확정 3 (임시 정답 3)'
    finally:
        server.shutdown(); server.server_close(); thread.join()


# D-857 §4: an offline debate round re-asks a model on disputed questions; its answer stays provisional.
def test_export_disputes_lists_only_disputed_unpaused_questions_with_every_model(tmp_path, monkeypatch):
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W43')
    store = consensus_store(tmp_path, 40, models=(('m1', 'transformers', 0.9), ('m2', 'transformers', 0.6),
                                                  ('m2', 'ollama', 0.55)))
    lines = vlm_judge.disputes(store)  # also freezes the evaluation set
    with store.connect() as db:
        frozen = {row[0] for row in db.execute('SELECT item FROM vlm_eval_set')}
    outside = sorted(set(range(1, 41)) - frozen)
    assert [line['item'] for line in lines] == outside and len(outside) == 10
    first = lines[0]
    assert first['answers'] == [{'model': 'm1', 'runtime': 'transformers', 'answer': first['answers'][0]['answer'], 'p': 0.9},
                                {'model': 'm2', 'runtime': 'transformers', 'answer': first['answers'][0]['answer'], 'p': 0.6}]
    assert first['options'] == ['yes', 'no', 'unclear'] and first['image'].endswith(f"{first['item']:064x}.jpg")
    with store.connect() as db:  # one photo reaches consensus, one is decided by a person
        put(db, outside[0], 'm2', 'transformers', first['answers'][0]['answer'], 0.85)
    label(store, outside[1], **{HELD: 'no'})
    assert [line['item'] for line in vlm_judge.disputes(store)] == outside[2:]
    with store.connect() as db:  # a paused question is not debated
        db.executemany('INSERT INTO vlm_audits (item, question, week, provisional, answer) VALUES (?,?,?,?,?)',
                       [(n, HELD, '2026-W43', 'yes', 'no') for n in range(1, 6)])
    assert vlm_judge.disputes(store) == []


def test_debate_import_replaces_the_same_models_runtimes_and_never_adds_a_model(tmp_path):
    store, body = open_store(tmp_path), bench(tmp_path, ROWS)
    vlm_judge.import_rows(store, body)
    vlm_judge.import_rows(store, dict(body, model='other-model'))
    photo = store.state / 'vlm' / 'images' / (vlm_judge.item(store, 1)['image_sha256'] + '.jpg')
    empty = 'wrist.gripper_empty'

    def argue(model, value, extra=None):
        rows = tmp_path / 'debate.jsonl'
        p = {'yes': [0.9, 0.05, 0.05], 'no': [0.05, 0.9, 0.05]}[value]
        rows.write_text(json.dumps({'frame': str(photo), 'view': 'wrist', 'long_side': 0, 'debate_round': 1,
                                    'debate': {empty: {'answer': value, 'p': p}, **(extra or {})}}) + '\n')
        return vlm_judge.import_rows(store, dict(body, rows_path=str(rows), model=model))

    assert argue('qwen3-vl-8b', 'yes')['answers_added'] == 1
    second = argue('qwen3-vl-8b', 'no')
    assert (second['items_added'], second['items_existing'], second['answers_added']) == (0, 1, 1)
    with store.connect() as db:
        rows = db.execute("SELECT answer FROM vlm_model_answers WHERE item=1 AND runtime='debate'").fetchall()
        assert [row[0] for row in rows] == ['no']  # round 2 replaced round 1
        picks = vlm_judge._picks(db)[(1, empty)]
        assert set(picks) == {'qwen3-vl-8b', 'other-model'} and picks['qwen3-vl-8b'][1:3] == ('debate', 'no')
        # The ollama runtime also said no; one model with two runtimes and a debate is still one vote.
        assert 1 not in vlm_judge.provisional(db)
    argue('other-model', 'no')
    debated = set()
    with store.connect() as db:
        assert vlm_judge.provisional(db, debated)[1] == {empty: 'no'} and debated == {(1, empty)}
    with pytest.raises(ValueError, match='question set'):
        argue('other-model', 'no', {'front.lane_tape': {'answer': 'both', 'p': [1, 0, 0, 0]}})
    with pytest.raises(ValueError, match='no earlier answer'):
        argue('third-model', 'no')  # a model that never answered cannot join through a debate
    bare = tmp_path / 'bare.jsonl'
    bare.write_text(json.dumps({'frame': str(photo), 'view': 'wrist', 'long_side': 0}) + '\n')
    with pytest.raises(ValueError, match='no model answers'):
        vlm_judge.import_rows(store, dict(body, rows_path=str(bare)))


def test_debate_consensus_moves_a_photo_out_of_the_disputed_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(vlm_judge, 'week', lambda: '2026-W43')
    store = consensus_store(tmp_path, 40, models=(('m1', 'transformers', 0.9), ('m2', 'transformers', 0.6)))
    before = vlm_judge.queue(store)
    disputed = [row['id'] for row in before['items'] if row['kind'] == 'disputed']
    assert len(disputed) == 10
    with store.connect() as db:
        put(db, disputed[0], 'm2', 'debate', 'yes' if disputed[0] % 2 else 'no', 0.85)
        put(db, disputed[1], 'm2', 'debate', 'unclear', 0.95)  # a debate that still disagrees keeps it disputed
    after = vlm_judge.queue(store)
    assert [row['id'] for row in after['items'] if row['kind'] == 'disputed'] == disputed[1:]
    assert any(row['id'] == disputed[0] for row in after['items'] if row['kind'] == 'audit') or \
        disputed[0] not in [row['id'] for row in after['items']]
    coverage = vlm_judge.evaluation(store)['provisional'][0]
    assert (coverage['provisional'], coverage['debate']) == (1, 1)


def test_bench_question_set_v3_imports_and_splits_the_ambiguous_questions():
    import importlib.util
    from pathlib import Path
    pytest.importorskip('PIL')
    path = Path(__file__).resolve().parents[3] / 'tools' / 'vlm_question_bench.py'
    spec = importlib.util.spec_from_file_location('vlm_question_bench_v3', path)
    bench_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bench_module)
    assert bench_module.QUESTION_SET == 'v3'
    checked = vlm_judge.check_questions(json.loads(json.dumps(bench_module.QUESTIONS)))  # as --dump-questions writes it
    ids = {view: [q['id'] for q in questions] for view, questions in checked.items()}
    assert ids['front'] == ['front.object_between_tapes', 'front.wall_ahead', 'front.robot_ahead', 'front.person_ahead',
                            'front.tape_left', 'front.tape_right', 'front.shape']
    assert ids['top'] == ['top.robot_count', 'top.person_present']
    assert ids['wrist'] == list(vlm_judge.CONTRADICTION)  # wrist is unchanged, so v2 wrist rows import into v3
    count = next(q for q in checked['top'] if q['id'] == 'top.robot_count')
    assert count['options'] == ['zero', 'one', 'two', 'many']
