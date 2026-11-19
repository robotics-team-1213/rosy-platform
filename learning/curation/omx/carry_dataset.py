"""The cell's own carries -> an ACT/VLA experiment dataset (rosy.omx.experiment-dataset/1, source scripted_teacher).

A raw recording folder (episode_recorder.py) joins its attempts.jsonl row through the run_id/attempt_id
the cell stamps in task.json when it opens the episode; a recording without that binding is refused,
never matched by time. Only a carry that the ledger recorded as placed AND verified inside the
destination, and that a person labelled a success with reviewer and reason, becomes an episode: held,
failed, aborted, forced-stop, intervened and unreviewed carries stay out. Actions are the targets the
runner actually sent (ticks.jsonl); a policy's shadow predictions stay proposals and are never read as
actions here. One run (session) never straddles the train/eval split.

  python carry_dataset.py <episodes-root> --attempts <attempts.jsonl>... --labels <review.json> \
      --out <new-output> --split <run_id>=train --split <run_id>=eval [--every 2] [--size W H]
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'deploy/robot/omx'),
                str(ROOT / 'learning/training/omx')]
from episode_recorder import NAMES, aligned  # noqa: E402
from omx_output_paths import in_source_checkout  # noqa: E402

SCHEMA = 'rosy.omx.cell-carry-dataset/1'
ATTEMPT_SCHEMA = 'rosy.omx-cell-attempt.v1'
OUTCOMES = ('success', 'failure', 'unknown')
SPLITS = ('train', 'eval', 'test')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$')


def _require(condition, message):
    if not condition:
        raise ValueError('cell-carry dataset: ' + message)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _attempts(paths) -> dict:
    """attempts.jsonl rows keyed by attempt_id; duplicate rows refuse the whole build."""
    rows = {}
    for path in paths:
        for line in Path(path).read_text(encoding='utf-8').splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            _require(isinstance(row, dict) and row.get('schema') == ATTEMPT_SCHEMA
                     and isinstance(row.get('attempt_id'), str) and row.get('run_id'),
                     f'attempts rows must be {ATTEMPT_SCHEMA} with attempt_id and run_id: {Path(path).name}')
            _require(row['attempt_id'] not in rows, f'duplicate attempt row {row["attempt_id"]}')
            rows[row['attempt_id']] = row
    _require(rows, 'no attempt rows')
    return rows


def _labels(document, bindings) -> dict:
    """Person review labels keyed by (run_id, attempt_id); a known label needs reviewer and reason."""
    if document is None:
        return {}
    _require(isinstance(document, dict) and set(document) == {'labels'} and isinstance(document['labels'], list),
             'labels document must be {"labels": [...]}')
    result = {}
    for row in document['labels']:
        _require(isinstance(row, dict) and set(row) <= {'session_id', 'attempt_id', 'outcome', 'reviewer',
                                                        'reason', 'intervention'}, 'unknown label field')
        key = (row.get('session_id'), row.get('attempt_id'))
        _require(all(isinstance(value, str) and value for value in key) and key not in result,
                 'unique session/attempt label required')
        _require(key in bindings, f'label names a recording that is not here: {key[1]}')
        _require(row.get('outcome', 'unknown') in OUTCOMES, 'outcome must be success, failure or unknown')
        _require(type(row.get('intervention', False)) is bool, 'intervention must be true or false')
        _require(row.get('outcome', 'unknown') == 'unknown'
                 or all(isinstance(row.get(k), str) and row[k].strip() for k in ('reviewer', 'reason')),
                 'a known label needs reviewer and reason')
        result[key] = dict(outcome=row.get('outcome', 'unknown'), intervention=row.get('intervention', False),
                           reviewer=row.get('reviewer'), reason=row.get('reason'))
    return result


def _carry(folder: Path, task: dict, result: dict, rows: dict):
    """(carry metadata, None) when the recording is joinable and verified, (None, refusal reason) otherwise."""
    run_id, attempt_id = task.get('run_id'), task.get('attempt_id')
    if not run_id or not attempt_id:
        return None, 'task.json carries no run/attempt binding (recorded before the cell stamped ids)'
    row = rows.get(attempt_id)
    if row is None:
        return None, f'no attempts row for {attempt_id}'
    if row.get('run_id') != run_id:
        return None, 'run binding differs from the attempts row'
    context = row.get('context') or {}
    if not isinstance(context, dict) or task.get('arm_id') != context.get('arm_id', task.get('arm_id')):
        return None, 'arm binding differs from the attempts row'
    prefix, separator, dest = folder.name.rpartition('-to-')
    if not separator or not prefix.endswith('-' + str(row.get('from'))) or dest != row.get('to'):
        return None, 'folder route differs from the attempts row'
    if result.get('outcome') != 'success' or result.get('kept') is not True:
        return None, f'recorder kept this episode as "{result.get("outcome")}" (forced stop, abort or no frames)'
    if (row.get('outcome') != 'placed' or (row.get('verify') or {}).get('inside') is not True
            or row.get('fail_stage') or row.get('fail_class')):
        return None, f'ledger outcome "{row.get("outcome")}" is not a verified place'
    return dict(task=task, row=row, run_id=run_id, attempt_id=attempt_id), None


def _frames(folder: Path, task: dict, every: int, size):
    """Aligned ticks as float32 state/action and uint8 CHW camera arrays, subsampled by `every`."""
    ticks = [json.loads(line) for line in (folder / 'ticks.jsonl').read_text(encoding='utf-8').splitlines() if line]
    _require(ticks, f'{folder.name}: ticks.jsonl is empty')
    cameras = task['cameras']
    _require(isinstance(cameras, dict) and cameras, f'{folder.name}: task.json names no cameras')
    frames = {name: [json.loads(line) for line in (folder / f'{name}.jsonl').read_text(encoding='utf-8').splitlines() if line]
              for name in cameras}
    rows = aligned(ticks, frames)[::every]
    _require(rows, f'{folder.name}: no tick has a frame from every camera')
    states, actions, images, cache = [], [], {name: [] for name in cameras}, {}
    used_images = {name: {} for name in cameras}
    for tick, seqs in rows:
        state, action = tick.get('state'), tick.get('action')
        _require(isinstance(state, list) and isinstance(action, list)
                 and len(state) == len(NAMES) == len(action),
                 f'{folder.name}: tick width differs from the {len(NAMES)} recorded joints')
        for name, seq in seqs.items():
            image_path = folder / name / f'{seq:06d}.jpg'
            relative = image_path.relative_to(folder).as_posix()
            if relative not in used_images[name]:
                used_images[name][relative] = _sha256(image_path)
            if cache.get(name, (None, None))[0] == seq:
                images[name].append(cache[name][1])
                continue
            with Image.open(image_path) as image:
                pixels = np.asarray(image.convert('RGB').resize(size, Image.Resampling.BILINEAR), dtype=np.uint8)
            pixels = pixels.transpose(2, 0, 1)
            cache[name] = (seq, pixels)
            images[name].append(pixels)
        states.append(np.asarray(state, dtype=np.float32))
        actions.append(np.asarray(action, dtype=np.float32))
    return (np.stack(states), np.stack(actions),
            {name: np.stack(values) for name, values in images.items()}, used_images)


def build(episodes, attempts, output, *, splits, labels=None, every=2, size=(64, 48)):
    _require(type(every) is int and every >= 1, 'every must be a positive integer')
    _require(len(size) == 2 and all(type(v) is int and 1 <= v <= 4096 for v in size), 'camera resize W H required')
    episodes, output = Path(episodes).resolve(strict=True), Path(output).resolve()
    _require(not output.exists(), 'new output directory required')
    _require(not in_source_checkout(output), 'output belongs outside the source checkout')
    _require(not output.is_relative_to(episodes) and not episodes.is_relative_to(output),
             'output must be separate from the recordings')
    folders = sorted(path.parent for path in episodes.glob('*/result.json'))
    _require(folders, 'no episode recordings under the root')
    rows = _attempts(attempts)
    carries, refusals, bindings = [], [], set()
    for folder in folders:
        task = json.loads((folder / 'task.json').read_text(encoding='utf-8'))
        result = json.loads((folder / 'result.json').read_text(encoding='utf-8'))
        if task.get('run_id') and task.get('attempt_id'):
            bindings.add((task['run_id'], task['attempt_id']))
        carry, why = _carry(folder, task, result, rows)
        if carry is None:
            refusals.append(dict(folder=folder.name, reason=why))
        else:
            carry['folder'] = folder
            carries.append(carry)
    _require(len({c['attempt_id'] for c in carries}) == len(carries),
             'two recordings claim the same attempt id')
    labelled = _labels(labels, bindings)
    kept = []
    for carry in carries:
        label = labelled.get((carry['run_id'], carry['attempt_id']))
        if label is None:
            refusals.append(dict(folder=carry['folder'].name, reason='no person review label'))
        elif label['outcome'] != 'success':
            refusals.append(dict(folder=carry['folder'].name, reason=f'person review outcome: {label["outcome"]}'))
        elif label['intervention']:
            refusals.append(dict(folder=carry['folder'].name, reason='person review marks an intervention'))
        else:
            carry['label'] = label
            kept.append(carry)
    _require(kept, 'no reviewed verified-success carry to build from')
    _require(all(isinstance(c['task'].get('task'), str) and c['task']['task'] for c in kept),
             'every kept carry needs a nonempty task text')
    _require(len({c['task']['task'] for c in kept}) == 1, 'kept carries name different tasks; export each task separately')
    arms = {c['task'].get('arm_id') for c in kept}
    _require(len(arms) == 1 and isinstance(next(iter(arms)), str), 'kept carries name different arms')
    arm = next(iter(arms))
    _require(IDENTIFIER.match(arm), 'arm id must be a learning identifier')
    _require(len({frozenset(c['task']['cameras'].items()) for c in kept}) == 1,
             'kept carries name different cameras; export them separately')
    cameras = kept[0]['task']['cameras']
    _require(all(IDENTIFIER.match(name) for name in cameras), 'camera names must be learning identifiers')
    runs = {c['run_id'] for c in kept}
    _require(isinstance(splits, dict) and set(splits) == runs and all(v in SPLITS for v in splits.values()),
             f'exactly one train/eval/test split is required for every kept run: {sorted(runs)}')
    _require(any(splits[r] == 'train' for r in runs) and any(splits[r] == 'eval' for r in runs),
             'nonempty train and eval runs required')
    profile = dict(schema='rosy.omx.learning-profile/1', name='omx-cell-carries', mode='independent',
                   task=kept[0]['task']['task'],
                   arms=[dict(id=arm, joint_names=list(NAMES), units='normalized_-100_100')],
                   cameras=[dict(id=name, input_key='observation.images.' + name, arm_id=arm, role=name,
                                 source_identity=url, placement='fixed', shape=[3, size[1], size[0]],
                                 purposes=['policy', 'record']) for name, url in sorted(cameras.items())])
    document = dict(schema='rosy.omx.experiment-dataset/1', profile=profile, source='scripted_teacher', episodes=[])
    output.mkdir(parents=True)
    lineage = []
    for carry in kept:
        _require(IDENTIFIER.match(carry['attempt_id']), 'attempt id must be a learning identifier')
        state, action, images, image_hashes = _frames(carry['folder'], carry['task'], every, size)
        filename = f'{carry["attempt_id"]}.npz'
        with (output / filename).open('xb') as stream:
            np.savez_compressed(stream, **{'observation.state': state, 'action': action},
                                **{'observation.images.' + name: values for name, values in images.items()})
        document['episodes'].append(dict(id=carry['attempt_id'], session_id=carry['run_id'],
                                         parent_id=carry['folder'].name, split=splits[carry['run_id']],
                                         file=filename, sha256=_sha256(output / filename)))
        lineage.append(dict(id=carry['attempt_id'], session_id=carry['run_id'], split=splits[carry['run_id']],
                            folder=carry['folder'].name, arm_id=arm, attempt=carry['row'].get('attempt'),
                            **{'from': carry['row'].get('from'), 'to': carry['row'].get('to')},
                            frames=len(state), verify=carry['row'].get('verify'),
                            reviewer=carry['label']['reviewer'], review_reason=carry['label']['reason'],
                            source_sha256={**{name: _sha256(carry['folder'] / name) for name in
                                           ('task.json', 'ticks.jsonl', 'result.json',
                                            *(f'{camera}.jsonl' for camera in cameras))},
                                           **{name: digest for files in image_hashes.values()
                                              for name, digest in files.items()}}))
    (output / 'dataset.json').write_text(json.dumps(document, indent=1), encoding='utf-8')
    from experiment_dataset import load_dataset
    loaded = load_dataset(output, method='act')
    receipt = dict(schema=SCHEMA, dataset_revision=loaded.revision, source=loaded.source,
                   episodes=lineage, refusals=refusals,
                   input_sha256={str(Path(path).resolve()): _sha256(path) for path in attempts},
                   review_sha256=hashlib.sha256(json.dumps(labels, sort_keys=True).encode()).hexdigest(),
                   splits={run: splits[run] for run in sorted(runs)}, every=every, size=list(size),
                   action_source='episode_recorder ticks.jsonl action: the joint targets the runner sent',
                   shadow_predictions='not read; a policy output stays a proposal and never an action',
                   task_success_inferred=False, physical_acceptance=False)
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('episodes', type=Path)
    parser.add_argument('--attempts', type=Path, nargs='+', required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--split', action='append', required=True, metavar='RUN_ID=train|eval|test')
    parser.add_argument('--every', type=int, default=2)
    parser.add_argument('--size', type=int, nargs=2, default=(64, 48), metavar=('W', 'H'))
    args = parser.parse_args(argv)
    try:
        pairs = [item.split('=', 1) for item in args.split]
        _require(all(len(pair) == 2 for pair in pairs), '--split must be RUN_ID=train|eval|test')
        splits = dict(pairs)
        _require(len(splits) == len(pairs), 'each run needs exactly one split')
        receipt = build(args.episodes, args.attempts, args.out, splits=splits,
                        labels=json.loads(args.labels.read_text(encoding='utf-8')),
                        every=args.every, size=tuple(args.size))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
