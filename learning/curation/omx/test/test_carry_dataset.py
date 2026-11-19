"""The cell's own carries: only reviewed verified-success recordings become ACT/VLA episodes."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pytest
from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('carry_dataset', HERE.parent / 'carry_dataset.py')
carry_dataset = importlib.util.module_from_spec(spec)
spec.loader.exec_module(carry_dataset)

TASK = 'Pick the green container from the pinky and place it on the belt.'
URL = 'http://127.0.0.1:8123/top.jpg'


def record(root, name, run, n, *, outcome='placed', inside=True, recorder='success', task_text=TASK,
           bind=True, row_route=None):
    """One raw episode folder plus its would-be attempts row; folder route follows the name."""
    folder = root / f'{name}-pinky-to-belt'
    folder.mkdir(parents=True)
    base = float(ord(name[0]))  # recordings must differ in content; load_dataset refuses duplicates
    attempt_id = f'{run}-{n:03d}'
    task = {'task': task_text, 'object': 'box-1', 'cameras': {'top': URL}, 'io': '', 'payload': None}
    if bind:
        task.update(run_id=run, attempt_id=attempt_id, arm_id='arm_s')
    (folder / 'task.json').write_text(json.dumps(task), encoding='utf-8')
    (folder / 'ticks.jsonl').write_text(''.join(
        json.dumps({'t': 1000.0 + i * 0.03, 'state': [float(i) + base] * 6, 'action': [float(i) + 0.5 + base] * 6}) + '\n'
        for i in range(6)), encoding='utf-8')
    (folder / 'top').mkdir()
    (folder / 'top.jsonl').write_text(''.join(
        json.dumps({'seq': i, 't': 1000.0 + i * 0.03 - 0.01}) + '\n' for i in range(6)), encoding='utf-8')
    for i in range(6):
        Image.fromarray(np.full((24, 32, 3), i * 40 % 256, dtype=np.uint8)).save(folder / 'top' / f'{i:06d}.jpg')
    (folder / 'result.json').write_text(json.dumps(
        {'kept': recorder == 'success', 'outcome': recorder, 'frames': {'top': 6}}), encoding='utf-8')
    route = row_route or ('pinky', 'belt')
    return {'schema': 'rosy.omx-cell-attempt.v1', 'attempt_id': attempt_id, 'run_id': run,
            'from': route[0], 'to': route[1], 'attempt': n, 'outcome': outcome,
            'verify': {'inside': inside}, 'fail_stage': None, 'fail_class': None}


def review(*rows, outcome='success', intervention=False, **extra):
    return {'labels': [dict(session_id=row['run_id'], attempt_id=row['attempt_id'], outcome=outcome,
                            reviewer='op', reason='clean verified carry', intervention=intervention, **extra)
                       for row in rows]}


def write_inputs(tmp_path, rows):
    root = tmp_path / 'episodes'
    attempts = tmp_path / 'attempts.jsonl'
    attempts.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')
    return root, attempts


def build(module, tmp_path, rows, splits, labels, name='out', **kwargs):
    root, attempts = write_inputs(tmp_path, rows)
    return module.build(root, [attempts], tmp_path / name, splits=splits, labels=labels,
                        every=kwargs.pop('every', 1), size=kwargs.pop('size', (16, 12)), **kwargs)


def scenario(tmp_path):
    good_train = record(tmp_path / 'episodes', 'a', 'run-train', 1)
    good_eval = record(tmp_path / 'episodes', 'b', 'run-eval', 1)
    unbound = record(tmp_path / 'episodes', 'c', 'run-train', 2, bind=False)
    ledger_failed = record(tmp_path / 'episodes', 'd', 'run-train', 3, outcome='failed', inside=False)
    forced_stop = record(tmp_path / 'episodes', 'e', 'run-train', 4, recorder='failed')
    unreviewed = record(tmp_path / 'episodes', 'f', 'run-train', 5)
    rows = [good_train, good_eval, unbound, ledger_failed, forced_stop, unreviewed]
    return rows, review(good_train, good_eval)


def test_only_reviewed_verified_carries_become_episodes(tmp_path):
    from experiment_dataset import load_dataset
    rows, labels = scenario(tmp_path)
    receipt = build(carry_dataset, tmp_path, rows, {'run-train': 'train', 'run-eval': 'eval'}, labels)
    loaded = load_dataset(tmp_path / 'out', method='act')
    assert [e.metadata['id'] for e in loaded.episodes] == ['run-train-001', 'run-eval-001']
    assert [e.metadata['split'] for e in loaded.episodes] == ['train', 'eval']
    train = loaded.split('train')[0].arrays
    assert train['observation.state'].shape == train['action'].shape == (6, 6)
    assert train['observation.images.top'].shape == (6, 3, 12, 16)
    assert loaded.source == 'scripted_teacher'
    refused = {r['folder']: r['reason'] for r in receipt['refusals']}
    assert set(refused) == {'c-pinky-to-belt', 'd-pinky-to-belt', 'e-pinky-to-belt', 'f-pinky-to-belt'}
    assert 'no run/attempt binding' in refused['c-pinky-to-belt']
    assert 'not a verified place' in refused['d-pinky-to-belt']
    assert 'forced stop' in refused['e-pinky-to-belt']
    assert 'no person review label' in refused['f-pinky-to-belt']
    kept = receipt['episodes'][0]
    assert kept['source_sha256']['ticks.jsonl'] == hashlib.sha256(
        (tmp_path / 'episodes' / 'a-pinky-to-belt' / 'ticks.jsonl').read_bytes()).hexdigest()
    assert kept['source_sha256']['top/000000.jpg'] == hashlib.sha256(
        (tmp_path / 'episodes' / 'a-pinky-to-belt' / 'top' / '000000.jpg').read_bytes()).hexdigest()
    assert receipt['review_sha256'] == hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest()
    assert receipt['physical_acceptance'] is False


def test_failure_review_and_intervention_labels_exclude_a_carry(tmp_path):
    rows, _ = scenario(tmp_path)
    extra = record(tmp_path / 'episodes', 'g', 'run-train', 6)  # keep both split sides buildable
    rows = [*rows, extra]
    for name, intervention in (('failure', False), ('intervention', True)):
        labelled = review(rows[1], extra)['labels']
        labelled.insert(0, dict(session_id=rows[0]['run_id'], attempt_id=rows[0]['attempt_id'],
                                outcome='failure' if name == 'failure' else 'success',
                                intervention=intervention, reviewer='op', reason='watched it'))
        receipt = build(carry_dataset, tmp_path, rows, {'run-train': 'train', 'run-eval': 'eval'},
                        {'labels': labelled}, name=name)
        reason = next(r['reason'] for r in receipt['refusals'] if r['folder'] == 'a-pinky-to-belt')
        assert ('review outcome: failure' if name == 'failure' else 'marks an intervention') in reason


@pytest.mark.parametrize('fault', ['reviewer', 'duplicate_label', 'unknown_attempt'])
def test_bad_label_documents_are_refused(tmp_path, fault):
    rows, _ = scenario(tmp_path)
    labels = review(rows[0], rows[1])
    if fault == 'reviewer':
        labels['labels'][0]['reviewer'] = ''
    elif fault == 'duplicate_label':
        labels['labels'][1]['attempt_id'] = labels['labels'][0]['attempt_id']
    else:
        labels['labels'][0]['attempt_id'] = 'run-train-999'
    with pytest.raises(ValueError, match='reviewer|unique|not here'):
        build(carry_dataset, tmp_path, rows, {'run-train': 'train', 'run-eval': 'eval'}, labels)


@pytest.mark.parametrize('fault', ['missing_run', 'no_eval', 'bad_name'])
def test_sessions_need_one_split_on_both_sides(tmp_path, fault):
    rows, labels = scenario(tmp_path)
    splits = {'run-train': 'train', 'run-eval': 'eval'}
    if fault == 'missing_run':
        del splits['run-eval']
    elif fault == 'no_eval':
        splits['run-eval'] = 'train'
    else:
        splits['run-eval'] = 'holdout'
    with pytest.raises(ValueError, match='split|train and eval'):
        build(carry_dataset, tmp_path, rows, splits, labels)
    assert not (tmp_path / 'out').exists()


def test_route_or_binding_mismatch_is_refused(tmp_path):
    rows, labels = scenario(tmp_path)
    rows[0]['from'], rows[0]['to'] = 'belt', 'pinky'  # the attempts row contradicts the folder route
    extra = record(tmp_path / 'episodes', 'g', 'run-train', 6)  # keep both split sides buildable
    receipt = build(carry_dataset, tmp_path, [*rows, extra],
                    {'run-train': 'train', 'run-eval': 'eval'}, review(rows[1], extra))
    assert 'route differs' in {r['folder']: r['reason'] for r in receipt['refusals']}['a-pinky-to-belt']


def test_subsample_every_and_frames_follow_size(tmp_path):
    rows, labels = scenario(tmp_path)
    receipt = build(carry_dataset, tmp_path, rows, {'run-train': 'train', 'run-eval': 'eval'}, labels,
                    every=2, size=(8, 6))
    assert [episode['frames'] for episode in receipt['episodes']] == [3, 3]
    with np.load(tmp_path / 'out' / 'run-train-001.npz') as archive:
        assert archive['observation.images.top'].shape == (3, 3, 6, 8)


def test_mixed_tasks_or_cameras_are_refused(tmp_path):
    rows, labels = scenario(tmp_path)
    shutil.rmtree(tmp_path / 'episodes' / 'b-pinky-to-belt')
    rows[1] = record(tmp_path / 'episodes', 'b', 'run-eval', 1, task_text='Return the container to the pinky.')
    with pytest.raises(ValueError, match='task'):
        build(carry_dataset, tmp_path, rows, {'run-train': 'train', 'run-eval': 'eval'}, labels)
    assert not (tmp_path / 'out').exists()
