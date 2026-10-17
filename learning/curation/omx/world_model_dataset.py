"""D-782 W1: closed OMX collection sessions into an action-conditioned transition dataset.

Unlike behaviour-cloning intake this keeps failed and aborted attempts, because a world model must see what an
action did, not only what succeeded. Every raw byte is re-validated by collection_intake. Windows never bridge a
capture gap and splits are by session. No robot, upload, or task-success inference.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from collection_intake import validate_session
from native_review import OBJECT_RESULTS

SCHEMA = 'rosy.world-model-dataset.v1'
SPLITS = ('train', 'eval', 'test')
OUTCOMES = ('success', 'failure', 'unknown')
MAX_HORIZON = 10


def _require(value, message):
    if not value:
        raise ValueError('world-model dataset: ' + message)


def _labels(document):
    """Human outcome labels keyed by session/cycle; absent attempts stay unknown."""
    if document is None:
        return {}
    _require(isinstance(document, dict) and set(document) == {'labels'} and isinstance(document['labels'], list),
             'labels document must be {"labels": [...]}')
    result = {}
    for row in document['labels']:
        _require(isinstance(row, dict) and set(row) <= {'session_id', 'cycle_id', 'outcome', 'object_result',
                                                          'reviewer', 'reason'}, 'unknown label field')
        key = (row.get('session_id'), row.get('cycle_id'))
        _require(all(isinstance(v, str) and v for v in key) and key not in result, 'unique session/cycle label')
        _require(row.get('outcome', 'unknown') in OUTCOMES, 'outcome must be success, failure or unknown')
        _require(row.get('object_result', 'unknown') in OBJECT_RESULTS, 'unknown object_result')
        known = row.get('outcome', 'unknown') != 'unknown' or row.get('object_result', 'unknown') != 'unknown'
        _require(not known or all(isinstance(row.get(k), str) and row[k].strip() for k in ('reviewer', 'reason')),
                 'a known label needs reviewer and reason')
        result[key] = dict(outcome=row.get('outcome', 'unknown'), object_result=row.get('object_result', 'unknown'))
    return result


def _segments(rows, fps):
    """Consecutive runs whose host capture gaps stay within 1.5 frame periods."""
    limit = 1.5e9 / fps
    current = []
    for row in rows:
        if current and row['time_ns'] - current[-1]['time_ns'] > limit:
            yield current
            current = []
        current.append(row)
    if current:
        yield current


def build(sessions, output, *, horizon, splits, labels=None):
    _require(type(horizon) is int and 1 <= horizon <= MAX_HORIZON, f'horizon must be 1..{MAX_HORIZON}')
    output = Path(output).absolute()
    _require(not output.exists(), 'new output directory required')
    records = [validate_session(path, completed_only=True, require_complete=False) for path in sessions]
    _require(bool(records), 'at least one session required')
    base = records[0]['manifest']
    for record in records:
        manifest = record['manifest']
        _require(all(manifest[k] == base[k] for k in ('fps', 'rig_revision', 'calibration_revision',
                                                      'body_units', 'gripper_units')),
                 'sessions differ in fps, rig, calibration or units')
        _require(not output.is_relative_to(record['root']), 'output must be outside every source')
    ids = [r['manifest']['session_id'] for r in records]
    _require(len(set(ids)) == len(ids), 'duplicate session identity')
    _require(isinstance(splits, dict) and set(splits) == set(ids) and all(v in SPLITS for v in splits.values()),
             'every session needs exactly one train, eval or test split')
    labelled = _labels(labels)
    known_keys = {(r['manifest']['session_id'], e['cycle_id']) for r in records for e in r['manifest']['episodes']}
    _require(set(labelled) <= known_keys, 'label names an attempt that is not in these sessions')
    attempts, windows = [], {name: [] for name in SPLITS}
    for record in sorted(records, key=lambda r: r['manifest']['episodes'][0]['start_ns']):
        manifest, session_id = record['manifest'], record['manifest']['session_id']
        split = splits[session_id]
        for episode in manifest['episodes']:
            label = labelled.get((session_id, episode['cycle_id']), dict(outcome='unknown', object_result='unknown'))
            index, count = len(attempts), 0
            for segment in _segments(record['samples'][episode['episode_index']], manifest['fps']):
                for t in range(len(segment) - horizon):
                    windows[split].append(dict(
                        attempt=index, frame_index=segment[t]['frame_index'],
                        state=segment[t]['observation.state'],
                        action=[segment[t+k]['action'] for k in range(horizon)],
                        next_states=[segment[t+k]['observation.state'] for k in range(1, horizon+1)]))
                    count += 1
            attempts.append(dict(session_id=session_id, cycle_id=episode['cycle_id'],
                                 attempt_index=episode['episode_index'], split=split, complete=episode['complete'],
                                 reason=episode['reason'], frames=episode['frames'], windows=count,
                                 teacher_sha256=manifest['teacher_sha256'], **label))
    _require(windows['train'] and windows['eval'], 'nonempty train and eval windows required')
    dataset = dict(schema=SCHEMA, horizon=horizon, fps=base['fps'], step_s=1/base['fps'],
                   rig_revision=base['rig_revision'], calibration_revision=base['calibration_revision'],
                   body_units=base['body_units'], gripper_units=base['gripper_units'],
                   action_semantics='normalized controller reference per captured frame',
                   sessions=[dict(session_id=r['manifest']['session_id'], manifest_sha256=r['manifest_sha256'],
                                  split=splits[r['manifest']['session_id']]) for r in records],
                   attempts=attempts, windows=windows)
    raw = (json.dumps(dataset, allow_nan=False, sort_keys=True) + '\n').encode()
    output.mkdir(parents=True)
    (output/'dataset.json').write_bytes(raw)
    receipt = dict(schema=SCHEMA+'.receipt', dataset_sha256=hashlib.sha256(raw).hexdigest(), horizon=horizon,
                   windows={k: len(v) for k, v in windows.items()}, attempts=len(attempts),
                   incomplete_attempts=sum(not a['complete'] for a in attempts),
                   labelled_attempts=sum(a['outcome'] != 'unknown' or a['object_result'] != 'unknown'
                                         for a in attempts),
                   physical_acceptance=False, task_success_inferred=False)
    (output/'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def load(root):
    """Read a built dataset and return it with the digest that artifacts must cite."""
    raw = (Path(root)/'dataset.json').read_bytes()
    dataset = json.loads(raw)
    _require(dataset.get('schema') == SCHEMA, 'dataset schema differs')
    receipt = json.loads((Path(root)/'receipt.json').read_text(encoding='utf-8'))
    digest = hashlib.sha256(raw).hexdigest()
    _require(receipt.get('dataset_sha256') == digest, 'dataset bytes differ from receipt')
    return dataset, digest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sessions', nargs='+', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--horizon', type=int, default=4)
    parser.add_argument('--split', action='append', required=True, metavar='SESSION_ID=train|eval|test')
    parser.add_argument('--labels', type=Path)
    args = parser.parse_args(argv)
    try:
        splits = dict(item.split('=', 1) for item in args.split)
        labels = json.loads(args.labels.read_text(encoding='utf-8')) if args.labels else None
        receipt = build(args.sessions, args.out, horizon=args.horizon, splits=splits, labels=labels)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
