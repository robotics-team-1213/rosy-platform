"""VLM judge evaluation and export: model agreement with confirmed (human) truth; never an approval (D-853 §3).

Split from vlm_judge.py (the store, queue and CLI). The export leaves the blind photos out of the provisional tier.
"""
import json

import vlm_judge


def _models(rows, answers):
    """Per model and runtime: agreement with the given confirmed rows only."""
    truth = {row['id']: json.loads(row['answers']) for row in rows}
    meta = {row['id']: (row['question_set'], {q['id']: q for q in json.loads(row['questions'])}) for row in rows}
    groups, picks = {}, {}
    for row in answers:
        if row['item'] not in truth:
            continue
        question_set, questions = meta[row['item']]
        key = (row['model'], row['runtime'], question_set, row['question'])
        group = groups.setdefault(key, {'options': questions[row['question']]['options'], 'pairs': [], 'missing': 0})
        if row['answer'] is None:
            group['missing'] += 1
        else:
            group['pairs'].append((truth[row['item']][row['question']], row['answer']))
        picks.setdefault((row['model'], row['runtime']), {}).setdefault(row['item'], {})[row['question']] = row['answer']
    models = {}
    for (model, runtime, question_set, qid), group in groups.items():
        pairs, options = group['pairs'], group['options']
        recalls = [sum(m == c for h, m in pairs if h == c) / sum(h == c for h, _ in pairs)
                   for c in options if any(h == c for h, _ in pairs)]
        entry = models.setdefault((model, runtime), {'model': model, 'runtime': runtime, 'questions': [],
            'contradictions': sum(all(answer.get(q) == 'yes' for q in vlm_judge.CONTRADICTION)
                                  for answer in picks[(model, runtime)].values())})
        entry['questions'].append({
            'question_set': question_set, 'question': qid, 'options': options, 'n': len(pairs),
            'missing': group['missing'],
            'agreement': round(sum(h == m for h, m in pairs) / len(pairs), 4) if pairs else None,
            'balanced_accuracy': round(sum(recalls) / len(recalls), 4) if recalls else None,
            'confusion': {h: {m: sum(p == (h, m) for p in pairs) for m in options} for h in options}})
    return list(models.values())


def evaluation(store):
    """Agreement with confirmed (human) answers only, plus provisional coverage and audits; never an approval.

    ``eval_set`` repeats the comparison on the frozen evaluation set alone: those photos were labelled blind,
    while audited photos were labelled with the consensus shown."""
    if not vlm_judge._ready(store):
        return {'labelled': 0, 'models': [], 'human': [], 'provisional': [], 'audits': [], 'paused': [],
                'eval_set': {'labelled': 0, 'models': []}}
    vlm_judge.queue(store)  # freeze the evaluation set first
    with store.connect() as db:
        rows = db.execute(vlm_judge.SELECT + " WHERE l.status='labelled'").fetchall()
        answers = db.execute("SELECT a.* FROM vlm_model_answers a JOIN vlm_labels l ON l.item=a.item "
                             "WHERE l.status='labelled' ORDER BY a.model, a.runtime, a.question").fetchall()
        frozen = {row[0] for row in db.execute('SELECT item FROM vlm_eval_set')}
        everything, usable, stats, paused = vlm_judge._state(db)
        debated = set()
        vlm_judge.provisional(db, debated)
    coverage = {}
    for row in everything:
        if row['status'] is None:
            for question in json.loads(row['questions']):
                entry = coverage.setdefault((row['question_set'], question['id']),
                                            {'pending': 0, 'provisional': 0, 'debate': 0})
                entry['pending'] += 1
                used = question['id'] in usable.get(row['id'], {})
                entry['provisional'] += used
                entry['debate'] += used and (row['id'], question['id']) in debated
    human = {}
    for row in rows:
        for qid, value in json.loads(row['answers']).items():
            entry = human.setdefault((row['question_set'], qid), {'n': 0, 'unclear': 0})
            entry['n'] += 1
            entry['unclear'] += value == 'unclear'
    blind = [row for row in rows if row['id'] in frozen]
    return {'labelled': len(rows), 'models': _models(rows, answers),
            'eval_set': {'labelled': len(blind), 'models': _models(blind, answers)},
            'human': [{'question_set': key[0], 'question': key[1], 'n': value['n'],
                       'unclear_rate': round(value['unclear'] / value['n'], 4)} for key, value in sorted(human.items())],
            'provisional': [{'question_set': key[0], 'question': key[1], **value,
                             'coverage': round(value['provisional'] / value['pending'], 4)}
                            for key, value in sorted(coverage.items())],
            'audits': [{'question': qid, **entry} for qid, entry in sorted(stats.items())], 'paused': sorted(paused)}


def export(store):
    """JSONL with its sha256: decided photos (answers tier `confirmed`) and undecided photos whose every unpaused
    question has a model consensus (status and tier `provisional`). Photos of the frozen evaluation set and
    disputed photos stay blind and are left out until people decide them. Only `confirmed` is truth (D-857 §4)."""
    if not vlm_judge._ready(store):
        return {'count': 0, 'sha256': vlm_judge.sha(b''), 'jsonl': ''}
    vlm_judge.queue(store)  # freeze the evaluation set first
    with store.connect() as db:
        rows, usable, _, paused = vlm_judge._state(db)
        frozen = {row[0] for row in db.execute('SELECT item FROM vlm_eval_set')}
    lines = []
    for row in rows:
        questions = [q['id'] for q in json.loads(row['questions'])]
        if row['status'] in ('labelled', 'excluded'):
            answers, tier, status = json.loads(row['answers']), 'confirmed', row['status']
        elif (usable.get(row['id']) and row['id'] not in frozen
              and all(qid in paused or qid in usable[row['id']] for qid in questions)):
            answers = {qid: usable[row['id']].get(qid) for qid in questions}
            tier, status = 'provisional', 'provisional'
        else:
            continue
        lines.append(json.dumps({'image_sha256': row['image_sha256'], 'view': row['view'],
                                 'question_set': row['question_set'], 'answers': answers, 'status': status,
                                 'tiers': {qid: None if value is None else tier for qid, value in answers.items()},
                                 'actor': row['actor'], 'version': row['version'] or 0},
                                ensure_ascii=False, sort_keys=True) + '\n')
    text = ''.join(lines)
    return {'count': len(lines), 'sha256': vlm_judge.sha(text.encode('utf-8')), 'jsonl': text}
