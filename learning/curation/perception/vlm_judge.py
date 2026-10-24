"""Human truth for closed VLM questions (T1) and model-vs-human evaluation; evaluation truth only.

Labels are people's answers per photo. Model answers are stored beside them for evaluation and never fill,
approve or change a label; nothing here is exported into perception training (D-475, D-514, D-542).
D-857 §4-5: a model consensus is a *provisional* answer, derived on read and never stored; a person's answer is
*confirmed*. People see only a small queue: a fixed evaluation set and disputed photos (both blind), plus a weekly
audit of provisional answers (shown, 맞음/고침). Consensus never approves or promotes anything (D-514 §5, D-853 §3).
Evaluation and export: vlm_judge_report.py. Design: docs/plans/2026-10-23-vlm-fast-judge-design.md. Screen and routes: docs/review-app.md.

CLI: python vlm_judge.py import --state <review-state> --rows <bench rows.jsonl>
     --questions <questions.json> --model <model name>
     python vlm_judge.py export-disputes --state <review-state> --out <debate.jsonl>
     python vlm_judge.py unpause --state <review-state> --question <id> --actor <name>
Writes need a separate evaluation state (review_app.py --empty-eval, D-475, D-853 §4); reads of a state without
VLM tables return empty results and create nothing.
Debate (D-857 §4): export-disputes lists disputed (photo, question) pairs with every model's current answer;
``tools/vlm_question_bench.py --debate-input`` re-asks one model offline on the model PC (D-459: this app never
calls a model) and its rows' ``debate`` block imports as runtime ``debate`` of the same model name.
questions.json is ``tools/vlm_question_bench.py --dump-questions`` output: {question_set, questions}.
--model names the bench run (rows carry no model name); a row's long_side other than 0 is appended as @<px>.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
from pathlib import Path

STATUSES = ('pending', 'labelled', 'excluded')
# D-857 §5 start values, tuned in operation.
CONSENSUS_MODELS, CONSENSUS_P = 2, 0.8  # distinct models that agree, each with p >= CONSENSUS_P
EVAL_SET_SIZE, QUEUE_CAP, AUDIT_PER_WEEK = 30, 50, 10  # items per view (frozen); open disputed+audit per view; audits
AUDIT_PAUSE_RATE, AUDIT_PAUSE_MIN = 0.10, 5  # pause a question's provisional answers above this audit error rate
KINDS = ('eval', 'disputed', 'audit')
RUNTIMES = (('answers', 'transformers'), ('ollama_questions', 'ollama'), ('debate', 'debate'))
CONTRADICTION = ('wrist.object_in_gripper', 'wrist.gripper_empty')
IMAGE_TYPES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
ROWS_LIMIT, IMAGE_LIMIT, ITEM_LIMIT = 64 * 1024 * 1024, 32 * 1024 * 1024, 20000
NAME = re.compile(r'[a-z][a-z0-9_]{0,31}')
QID = re.compile(r'[a-z][a-z0-9_]{0,31}\.[a-z0-9_]{1,64}')
OPTION = re.compile(r'[a-z_]{1,32}')
SET = re.compile(r'[A-Za-z0-9_.-]{1,32}')
MODEL = re.compile(r'[A-Za-z0-9_.:/@+-]{1,120}')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def configure(store):
    with store.connect() as db:
        db.executescript('''CREATE TABLE IF NOT EXISTS vlm_items (
            id INTEGER PRIMARY KEY, view TEXT NOT NULL, image_sha256 TEXT NOT NULL, image_name TEXT NOT NULL,
            question_set TEXT NOT NULL, questions TEXT NOT NULL, source TEXT NOT NULL,
            imported_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(image_sha256, view, question_set));
            CREATE TABLE IF NOT EXISTS vlm_model_answers (
            item INTEGER NOT NULL, model TEXT NOT NULL, runtime TEXT NOT NULL, question TEXT NOT NULL,
            answer TEXT, p TEXT, PRIMARY KEY(item, model, runtime, question));
            CREATE TABLE IF NOT EXISTS vlm_labels (
            item INTEGER PRIMARY KEY, answers TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
            actor TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS vlm_label_events (
            id INTEGER PRIMARY KEY, ts TEXT DEFAULT CURRENT_TIMESTAMP, item INTEGER, version INTEGER,
            status TEXT, answers TEXT, actor TEXT);
            CREATE TABLE IF NOT EXISTS vlm_audits (
            item INTEGER NOT NULL, question TEXT NOT NULL, week TEXT NOT NULL, provisional TEXT NOT NULL,
            answer TEXT, actor TEXT, ts TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(item, question));
            CREATE TABLE IF NOT EXISTS vlm_eval_set (
            view TEXT NOT NULL, item INTEGER NOT NULL, added_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(view, item));
            CREATE TABLE IF NOT EXISTS vlm_unpauses (
            id INTEGER PRIMARY KEY, question TEXT NOT NULL, after INTEGER NOT NULL, actor TEXT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP);''')


def _writable(store):
    """VLM truth lives only in a separate evaluation state (D-475, D-853 §4); --empty-eval marks it."""
    with store.connect() as db:
        row = db.execute("SELECT value FROM metadata WHERE key='workspace_kind'").fetchone()
    if not row or row[0] != 'evaluation':
        raise ValueError('VLM 정답은 별도 평가 state(review_app.py --empty-eval)에서만 저장합니다.')
    configure(store)


def _ready(store):
    """True when this state holds VLM tables; reads never create them."""
    with store.connect() as db:
        found = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='vlm_items'").fetchone()
    if found:
        configure(store)  # tables added after the first import (audits, evaluation set) for older states
    return bool(found)


def check_questions(questions):
    """{view: {qid: [text, [options]]}} -> {view: [{id, text, options}]}; refuses anything else."""
    if not isinstance(questions, dict) or not 0 < len(questions) <= 16:
        raise ValueError('questions must map 1-16 views to their questions')
    result = {}
    for view, entries in questions.items():
        if not NAME.fullmatch(view) or not isinstance(entries, dict) or not 0 < len(entries) <= 32:
            raise ValueError(f'view {view!r} needs 1-32 questions')
        result[view] = []
        for qid, value in entries.items():
            if (not QID.fullmatch(qid) or not isinstance(value, list) or len(value) != 2
                    or not isinstance(value[0], str) or not 0 < len(value[0]) <= 300
                    or not isinstance(value[1], list) or not 2 <= len(value[1]) <= 9
                    or any(not isinstance(o, str) or not OPTION.fullmatch(o) for o in value[1])
                    or len(set(value[1])) != len(value[1])):
                raise ValueError(f'question {qid!r} needs text and 2-9 unique lowercase options')
            result[view].append({'id': qid, 'text': value[0], 'options': value[1]})
    return result


def _model_answers(row, view_questions, model):
    found = []
    ids = {q['id'] for q in view_questions}
    for key, runtime in RUNTIMES:
        block = row.get(key)
        if block is None:
            continue
        answers = block.get('answers') if runtime == 'ollama' and isinstance(block, dict) else block
        # A debate re-asks only a photo's disputed questions; the other runtimes answer the whole set.
        if (not isinstance(answers, dict) or not answers
                or (not set(answers) <= ids if runtime == 'debate' else set(answers) != ids)):
            raise ValueError(f'{key} must answer exactly the question set of view {row["view"]!r}')
        for question in view_questions:
            if question['id'] not in answers:
                continue
            entry = answers[question['id']]
            answer = entry.get('answer') if isinstance(entry, dict) else None
            if runtime in ('ollama', 'debate') and answer == 'none_in_top':
                answer = None  # no option among Ollama's top tokens; counted as missing, never as an option
            elif answer not in question['options']:
                raise ValueError(f'{question["id"]} answer {answer!r} is not one of its options')
            p = entry.get('p')
            if (not isinstance(p, list) or len(p) != len(question['options'])
                    or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in p)):
                raise ValueError(f'{question["id"]} needs one probability per option')
            found.append((model, runtime, question['id'], answer, json.dumps(p)))
    if not found:
        raise ValueError(f'row of view {row["view"]!r} carries no model answers')
    return found


def import_rows(store, body):
    """Copy each bench photo once and add its model answers; never creates duplicates or touches labels."""
    if not isinstance(body, dict) or set(body) != {'rows_path', 'question_set', 'questions', 'model'}:
        raise ValueError('rows_path, question_set, questions and model are required')
    if not isinstance(body['question_set'], str) or not SET.fullmatch(body['question_set']):
        raise ValueError('question_set must be a short version name')
    if not isinstance(body['model'], str) or not MODEL.fullmatch(body['model']):
        raise ValueError('model must be a short model name')
    questions = check_questions(body['questions'])
    if not isinstance(body['rows_path'], str) or not body['rows_path']:
        raise ValueError('rows_path must name a rows.jsonl file')
    rows_path = Path(body['rows_path']).resolve()
    if not rows_path.is_file() or rows_path.stat().st_size > ROWS_LIMIT:
        raise ValueError('rows_path must be an existing rows.jsonl under 64 MiB')
    raw = rows_path.read_bytes()
    source = json.dumps({'rows': rows_path.name, 'rows_sha256': sha(raw)})
    parsed, images = [], {}
    for number, line in enumerate(raw.decode('utf-8').splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or row.get('view') not in questions or not isinstance(row.get('frame'), str):
            raise ValueError(f'row {number}: view must be one of {sorted(questions)} with a frame path')
        long_side = row.get('long_side', 0)
        if type(long_side) is not int or not 0 <= long_side <= 10000:
            raise ValueError(f'row {number}: long_side must be a non-negative integer')
        frame = Path(row['frame'])
        frame = (frame if frame.is_absolute() else rows_path.parent / frame).resolve()
        if (frame.suffix.lower() not in IMAGE_TYPES or not frame.is_file()
                or frame.stat().st_size > IMAGE_LIMIT or len(frame.name) > 200):
            raise ValueError(f'row {number}: frame must be an existing JPEG/PNG under 32 MiB')
        images[frame] = None
        if len(images) > ITEM_LIMIT:
            raise ValueError(f'rows must name at most {ITEM_LIMIT} photos')
        model = body['model'] + (f'@{long_side}' if long_side else '')
        parsed.append((row['view'], frame, _model_answers(row, questions[row['view']], model)))
    if not parsed:
        raise ValueError('rows.jsonl has no rows')
    _writable(store)
    folder = store.state / 'vlm' / 'images'
    folder.mkdir(parents=True, exist_ok=True)
    digests = {}
    for frame in images:
        data = frame.read_bytes()
        digest = digests[frame] = sha(data)
        target = folder / (digest + _ext(frame.name))
        if not target.exists():
            temporary = target.with_suffix('.tmp')
            temporary.write_bytes(data)
            os.replace(temporary, target)
        elif sha(target.read_bytes()) != digest:
            raise ValueError('stored VLM photo differs from its hash; restore it before importing')
    added = existing = answers = 0
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for view, frame, found in parsed:
            text = json.dumps(questions[view], ensure_ascii=False)
            row = db.execute('SELECT id, questions FROM vlm_items WHERE image_sha256=? AND view=? AND question_set=?',
                             (digests[frame], view, body['question_set'])).fetchone()
            if row is None:
                item = db.execute('INSERT INTO vlm_items (view, image_sha256, image_name, question_set, questions, source) '
                                  'VALUES (?,?,?,?,?,?)', (view, digests[frame], frame.name, body['question_set'],
                                                           text, source)).lastrowid
                added += 1
            elif row['questions'] != text:
                raise ValueError(f'question set {body["question_set"]} already has other {view} questions; use a new version')
            else:
                item = row['id']
                existing += 1
            for value in found:  # a later debate round replaces the earlier one; other runtimes are kept once
                # A debate revises a model's own opinion; it must not add a model to the question (D-857 §4).
                if value[1] == 'debate' and not db.execute(
                        "SELECT 1 FROM vlm_model_answers WHERE item=? AND question=? AND runtime!='debate' "
                        "AND (model=? OR substr(model, 1, ?)=?)",
                        (item, value[2], _base(value[0]), len(_base(value[0])) + 1, _base(value[0]) + '@')).fetchone():
                    raise ValueError(f'{value[0]} has no earlier answer to debate for {value[2]}')
                verb = 'INSERT OR REPLACE' if value[1] == 'debate' else 'INSERT OR IGNORE'
                answers += db.execute(f'{verb} INTO vlm_model_answers VALUES (?,?,?,?,?,?)', (item, *value)).rowcount
    return {'items_added': added, 'items_existing': existing, 'answers_added': answers,
            'rows_sha256': sha(raw)}


def _ext(name):
    suffix = Path(name).suffix.lower()
    return '.jpg' if suffix == '.jpeg' else suffix


def _label(row):
    if row['status'] is None:
        return {'status': 'pending', 'version': 0, 'actor': None, 'updated_at': None, 'answers': None}
    return {'status': row['status'], 'version': row['version'], 'actor': row['actor'],
            'updated_at': row['updated_at'], 'answers': json.loads(row['answers'])}


SELECT = ('SELECT i.id, i.view, i.image_sha256, i.image_name, i.question_set, i.questions, '
          'l.status, l.version, l.actor, l.updated_at, l.answers FROM vlm_items i LEFT JOIN vlm_labels l ON l.item=i.id')


def _base(model):
    """Runtimes and long sides of one model are one opinion: the model name before '@'."""
    return model.split('@', 1)[0]


def _picks(db):
    """{(item, question): {model: (model, runtime, answer, p)}}: one opinion per model (D-857 §4).

    A model's runtimes and long sides are one opinion, its most confident answer; once it has debated the question
    its debate answer replaces the others, so a debate never adds a model. A debate without an option
    (``none_in_top``, stored null) also replaces them as an explicit no-answer that blocks consensus for that
    question; a stale earlier answer never counts again."""
    options = {row['id']: {q['id']: q['options'] for q in json.loads(row['questions'])}
               for row in db.execute('SELECT id, questions FROM vlm_items')}
    picks = {}
    for row in db.execute("SELECT item, model, runtime, question, answer, p FROM vlm_model_answers "
                          "WHERE answer IS NOT NULL OR runtime='debate'"):
        p = 0.0 if row['answer'] is None else json.loads(row['p'])[options[row['item']][row['question']].index(row['answer'])]
        mine, base = picks.setdefault((row['item'], row['question']), {}), _base(row['model'])
        old = mine.get(base)
        if old is None or (row['runtime'] == 'debate', p) > (old[1] == 'debate', old[3]):
            mine[base] = (row['model'], row['runtime'], row['answer'], p)
    return picks


def provisional(db, debated=None):
    """{item: {question: answer}} where models agree (D-857 §4); derived on every read, never stored as truth.

    ``debated`` (a set) collects the (item, question) pairs whose consensus includes a debate answer."""
    result = {}
    for (identifier, qid), mine in _picks(db).items():
        picks = list(mine.values())
        # Any model answering otherwise is a disagreement, however unsure it is.
        if len({pick[2] for pick in picks}) == 1 and sum(pick[3] >= CONSENSUS_P for pick in picks) >= CONSENSUS_MODELS:
            result.setdefault(identifier, {})[qid] = picks[0][2]
            if debated is not None and any(pick[1] == 'debate' for pick in picks):
                debated.add((identifier, qid))
    return result


def disputes(store):
    """Disputed (photo, question) pairs for an offline debate round: pending, outside the evaluation set (people
    answer those), question not paused, no consensus. Each carries every model's current opinion."""
    if not _ready(store):
        return []
    queue(store)  # freeze the evaluation set first
    with store.connect() as db:
        rows, usable, _, paused = _state(db)
        frozen = {row[0] for row in db.execute('SELECT item FROM vlm_eval_set')}
        picks = _picks(db)
    lines = []
    for row in rows:
        if row['status'] is not None or row['id'] in frozen:
            continue
        for question in json.loads(row['questions']):
            if question['id'] in paused or question['id'] in usable.get(row['id'], {}):
                continue
            lines.append({'item': row['id'], 'view': row['view'], 'question_set': row['question_set'],
                          'image': str(store.state / 'vlm' / 'images' / (row['image_sha256'] + _ext(row['image_name']))),
                          'question': question['id'], 'text': question['text'], 'options': question['options'],
                          'answers': [{'model': model, 'runtime': pick[1], 'answer': pick[2], 'p': round(pick[3], 4)}
                                      for model, pick in sorted(picks.get((row['id'], question['id']), {}).items())]})
    return lines


def audits(db):
    """{question: {n, errors, rate, paused}} over every audit so far (D-857 §5)."""
    stats = {}
    # An unpause (manage) starts the question's count again from audits saved after it; older rows stay as history.
    after = ({row[0]: row[1] for row in db.execute('SELECT question, MAX(after) FROM vlm_unpauses GROUP BY question')}
             if db.execute("SELECT 1 FROM sqlite_master WHERE name='vlm_unpauses'").fetchone() else {})
    for row in db.execute('SELECT rowid, question, provisional, answer FROM vlm_audits'):
        if row['rowid'] <= after.get(row['question'], 0):
            continue
        entry = stats.setdefault(row['question'], {'n': 0, 'errors': 0})
        entry['n'] += 1
        entry['errors'] += row['answer'] != row['provisional']
    for entry in stats.values():
        entry['rate'] = round(entry['errors'] / entry['n'], 4)
        entry['paused'] = entry['n'] >= AUDIT_PAUSE_MIN and entry['errors'] / entry['n'] > AUDIT_PAUSE_RATE
    return stats


def week():
    year, number, _ = datetime.date.today().isocalendar()
    return f'{year}-W{number:02d}'


def _rank(*parts):
    return hashlib.sha256(':'.join(map(str, parts)).encode()).hexdigest()


def _state(db):
    """Rows, provisional answers that may be used (paused questions removed), audit stats and paused questions."""
    rows = db.execute(SELECT + ' ORDER BY i.id').fetchall()
    stats = audits(db)
    paused = {qid for qid, entry in stats.items() if entry['paused']}
    usable = {identifier: {qid: answer for qid, answer in answers.items() if qid not in paused}
              for identifier, answers in provisional(db).items()}
    return rows, usable, stats, paused


def _evaluation_set(db, name, group, questions, usable):
    """The view's frozen evaluation photos (D-857 §5): chosen once, topped up only when exclusions leave it short.

    New photos are seeded by sha256 and taken round-robin over consensus patterns (the provisional answer per
    question, '' where models disagree), so later model imports do not move photos already chosen."""
    excluded = {row['id'] for row in group if row['status'] == 'excluded'}
    chosen = [row[0] for row in db.execute('SELECT item FROM vlm_eval_set WHERE view=? ORDER BY rowid', (name,))]
    members = [item for item in chosen if item not in excluded]
    if len(members) < EVAL_SET_SIZE:
        pools = {}
        for row in sorted(group, key=lambda r: _rank('eval', name, r['image_sha256'])):
            if row['id'] not in excluded and row['id'] not in chosen:
                pattern = tuple(usable.get(row['id'], {}).get(qid, '') for qid in questions[row['id']])
                pools.setdefault(pattern, []).append(row['id'])
        order, added = [pools[key] for key in sorted(pools)], []
        while len(members) + len(added) < EVAL_SET_SIZE and any(order):
            for pool in order:
                if pool and len(members) + len(added) < EVAL_SET_SIZE:
                    added.append(pool.pop(0))
        db.executemany('INSERT OR IGNORE INTO vlm_eval_set (view, item) VALUES (?,?)', [(name, item) for item in added])
        members += added
    return set(members)


def queue(store, view=None):
    """What people see (D-857 §5): open photos of the fixed evaluation set, disputed photos and this week's audit."""
    # shortcut: recomputed from all model answers on each read; cache by answer/label counts if it gets slow.
    current = week()
    if not _ready(store):
        return {'items': [], 'counts': {}, 'paused': [], 'week': current, 'cap': QUEUE_CAP}
    views, result, counts = {}, [], {}
    with store.lock, store.connect() as db:  # the lock keeps two first reads from both topping up the set
        rows, usable, _, paused = _state(db)
        done = {row[0]: row[1] for row in db.execute(
            'SELECT i.view, COUNT(DISTINCT a.item) FROM vlm_audits a JOIN vlm_items i ON i.id=a.item '
            'WHERE a.week=? GROUP BY i.view', (current,))}
        for row in rows:
            if not view or row['view'] == view:
                views.setdefault(row['view'], []).append(row)
        sets = {name: _evaluation_set(db, name, group, {row['id']: [q['id'] for q in json.loads(row['questions'])]
                                                         for row in group}, usable)
                for name, group in sorted(views.items())}
    for name, group in sorted(views.items()):
        questions = {row['id']: [q['id'] for q in json.loads(row['questions'])] for row in group}
        kinds = dict.fromkeys(sets[name], 'eval')
        pending = [row for row in group if row['status'] is None]
        disputes = [row for row in pending if row['id'] not in kinds and any(
            qid not in paused and qid not in usable.get(row['id'], {}) for qid in questions[row['id']])]
        for row in sorted(disputes, key=lambda r: r['id'])[:QUEUE_CAP]:  # oldest first; the rest wait (D-857 §5)
            kinds[row['id']] = 'disputed'
        waiting = max(0, len(disputes) - QUEUE_CAP)
        opened = [row for row in pending if row['id'] in kinds]
        # The cap counts the recurring queues only; the one-time evaluation set has its own progress.
        disputed = sum(kinds[row['id']] == 'disputed' for row in opened)
        room = max(0, min(AUDIT_PER_WEEK - done.get(name, 0), QUEUE_CAP - disputed))
        candidates = [row for row in pending if row['id'] not in kinds
                      and set(questions[row['id']]) <= set(usable.get(row['id'], {}))]
        for row in sorted(candidates, key=lambda r: _rank('audit', current, r['image_sha256']))[:room]:
            kinds[row['id']] = 'audit'
            opened.append(row)
        counts[name] = {kind: sum(kinds[row['id']] == kind for row in opened) for kind in KINDS}
        counts[name].update(eval_size=len(sets[name]), eval_done=len(sets[name]) - counts[name]['eval'],
                            disputed_waiting=waiting)
        result += [{'id': row['id'], 'view': name, 'image_name': row['image_name'], 'question_set': row['question_set'],
                    'kind': kinds[row['id']]} for row in opened]
    result.sort(key=lambda row: (KINDS.index(row['kind']), row['id']))
    return {'items': result, 'counts': counts, 'paused': sorted(paused), 'week': current, 'cap': QUEUE_CAP}


def items(store, view=None, status=None):
    """Item list for navigation; no questions, labels' answers or model answers."""
    if not _ready(store):
        return []
    with store.connect() as db:
        rows = db.execute(SELECT + ' ORDER BY i.id').fetchall()
    result = []
    for row in rows:
        label = _label(row)
        if (view and row['view'] != view) or (status and label['status'] != status):
            continue
        result.append({'id': row['id'], 'view': row['view'], 'image_name': row['image_name'],
                       'question_set': row['question_set'], 'status': label['status'], 'version': label['version']})
    return result


def item(store, identifier):
    """One photo with its questions and the current human label; model answers are never included."""
    if not _ready(store):
        raise ValueError('VLM item not found')
    with store.connect() as db:
        row = db.execute(SELECT + ' WHERE i.id=?', (identifier,)).fetchone()
    if row is None:
        raise ValueError('VLM item not found')
    questions = json.loads(row['questions'])
    label = _label(row)
    if label['answers'] is None:
        label['answers'] = {q['id']: None for q in questions}
    kind = next((entry['kind'] for entry in queue(store, row['view'])['items'] if entry['id'] == identifier), None)
    result = {'id': row['id'], 'view': row['view'], 'image_sha256': row['image_sha256'], 'kind': kind,
              'image_name': row['image_name'], 'question_set': row['question_set'], 'questions': questions, **label}
    if kind == 'audit':  # only an audit shows the consensus; the evaluation set and disputed photos stay blind
        with store.connect() as db:
            result['provisional'] = provisional(db)[identifier]
    return result


def save(store, identifier, body, conflict, *, actor=None):
    """Optimistic-version label write; labelled needs every question answered, excluded may leave nulls."""
    if (not isinstance(body, dict) or set(body) != {'version', 'status', 'answers'} or type(body['version']) is not int
            or body['status'] not in ('labelled', 'excluded') or not isinstance(body['answers'], dict)):
        raise ValueError('version, status (labelled or excluded) and answers are required')
    _writable(store)
    with store.lock:
        current = item(store, identifier)
        questions = {q['id']: q['options'] for q in current['questions']}
        if set(body['answers']) != set(questions):
            raise ValueError('answers must name every question of this photo')
        for qid, answer in body['answers'].items():
            if answer is not None and answer not in questions[qid]:
                raise ValueError(f'{qid}: {answer!r} is not one of its options')
            if answer is None and body['status'] == 'labelled':
                raise ValueError('정답을 저장하려면 모든 질문에 답하세요.')
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT version FROM vlm_labels WHERE item=?', (identifier,)).fetchone()
            if (row['version'] if row else 0) != body['version']:
                raise conflict('다른 사람이 먼저 저장했습니다. 다시 불러오세요.')
            version, answers = body['version'] + 1, json.dumps(body['answers'], ensure_ascii=False)
            if current['kind'] == 'audit' and body['status'] == 'labelled':  # 맞음 or 고침 of a shown consensus
                for qid, value in current['provisional'].items():
                    db.execute('INSERT OR REPLACE INTO vlm_audits (item, question, week, provisional, answer, actor) '
                               'VALUES (?,?,?,?,?,?)', (identifier, qid, week(), value, body['answers'][qid], actor))
            db.execute('INSERT OR REPLACE INTO vlm_labels (item, answers, status, version, actor, updated_at) '
                       'VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)', (identifier, answers, body['status'], version, actor))
            db.execute('INSERT INTO vlm_label_events (item, version, status, answers, actor) VALUES (?,?,?,?,?)',
                       (identifier, version, body['status'], answers, actor))
    return item(store, identifier)


def image(store, identifier):
    """Stored photo bytes re-hashed on every read (D-469); a changed file is refused, not served."""
    if not _ready(store):
        raise ValueError('VLM item not found')
    with store.connect() as db:
        row = db.execute('SELECT image_sha256, image_name FROM vlm_items WHERE id=?', (identifier,)).fetchone()
    if row is None:
        raise ValueError('VLM item not found')
    data = (store.state / 'vlm' / 'images' / (row['image_sha256'] + _ext(row['image_name']))).read_bytes()
    if sha(data) != row['image_sha256']:
        raise ValueError('stored VLM photo differs from its hash')
    return data, IMAGE_TYPES[_ext(row['image_name'])], row['image_sha256']


def summary(store):
    if not _ready(store):
        return {'total': 0, 'views': {}, 'question_sets': [], 'labellers': []}
    with store.connect() as db:
        rows = db.execute(SELECT).fetchall()
        actors = db.execute('SELECT actor, COUNT(*) AS n FROM vlm_labels WHERE actor IS NOT NULL '
                            'GROUP BY actor ORDER BY actor').fetchall()
    views = {}
    for row in rows:
        views.setdefault(row['view'], dict.fromkeys(STATUSES, 0))[_label(row)['status']] += 1
    return {'total': len(rows), 'views': views, 'question_sets': sorted({row['question_set'] for row in rows}),
            'labellers': [{'actor': row['actor'], 'labels': row['n']} for row in actors]}


def unpause(store, question, *, actor=None):
    """Resume a paused question's provisional answers (manage): its audit count restarts after this point."""
    _writable(store)
    if not isinstance(question, str) or not QID.fullmatch(question):
        raise ValueError('question must be a question id')
    with store.lock, store.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not audits(db).get(question, {}).get('paused'):
            raise ValueError(f'{question} is not paused')
        after = db.execute('SELECT COALESCE(MAX(rowid), 0) FROM vlm_audits').fetchone()[0]
        db.execute('INSERT INTO vlm_unpauses (question, after, actor) VALUES (?,?,?)', (question, after, actor))
    return {'question': question, 'actor': actor}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    command = sub.add_parser('import', help='add bench photos and model answers to a review state')
    command.add_argument('--state', type=Path, required=True)
    command.add_argument('--rows', type=Path, required=True)
    command.add_argument('--questions', type=Path, required=True, help='vlm_question_bench.py --dump-questions output')
    command.add_argument('--model', required=True, help='model name the rows were produced with')
    command = sub.add_parser('export-disputes', help='write disputed (photo, question) pairs for a debate round')
    command.add_argument('--state', type=Path, required=True)
    command.add_argument('--out', type=Path, required=True)
    command = sub.add_parser('unpause', help='resume a paused question; records who did it and when')
    command.add_argument('--state', type=Path, required=True)
    command.add_argument('--question', required=True)
    command.add_argument('--actor', required=True, help='the person resuming it, kept in vlm_unpauses')
    args = parser.parse_args(argv)
    from review_store import ReviewStore
    if not (args.state / 'reviews.sqlite3').is_file():
        parser.error('--state must be an existing review state (start review_app.py once first)')
    if args.command == 'unpause':
        print(json.dumps(unpause(ReviewStore(args.state), args.question, actor=args.actor), indent=2))
        return 0
    if args.command == 'export-disputes':
        lines = disputes(ReviewStore(args.state))
        args.out.write_text(''.join(json.dumps(line, ensure_ascii=False) + '\n' for line in lines), encoding='utf-8')
        counts = {}
        for line in lines:
            counts[line['question']] = counts.get(line['question'], 0) + 1
        print(json.dumps({'pairs': len(lines), 'questions': counts}, indent=2))
        return 0
    dumped = json.loads(args.questions.read_text(encoding='utf-8'))
    result = import_rows(ReviewStore(args.state), {'rows_path': str(args.rows), 'model': args.model,
                                                   'question_set': dumped.get('question_set'),
                                                   'questions': dumped.get('questions')})
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
