"""D-782 W3 shadow recording and offline verdict replay. Records verdicts; never returns a decision to a caller.

`ShadowLog` appends what the checker said about a candidate. `replay` runs the checker over a built world-model
dataset and compares stop verdicts with human labels per attempt. Neither path is wired to an owner or admission.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from checker import CheckerConfig, WorldModelChecker, PredictionRequest
from rosy.contracts.learning.prediction import StateRef

FAILURE_OBJECTS = ('grasp_missed', 'dropped', 'displaced')


class ShadowLog:
    def __init__(self, path):
        self.path = Path(path)
        if self.path.is_symlink():
            raise ValueError('shadow: log links are not accepted')

    def record(self, request, result):
        row = dict(recorded_ns=time.time_ns(), sample_id=request.state_ref.sample_id,
                   action_source=request.action_source, result=result.to_json(), shadow_only=True)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, allow_nan=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())


def _dataset(root):
    raw = (Path(root)/'dataset.json').read_bytes()
    receipt = json.loads((Path(root)/'receipt.json').read_text(encoding='utf-8'))
    if receipt.get('dataset_sha256') != hashlib.sha256(raw).hexdigest():
        raise ValueError('shadow: dataset bytes differ from receipt')
    return json.loads(raw)


def _label(attempt):
    if attempt['outcome'] == 'failure' or attempt['object_result'] in FAILURE_OBJECTS:
        return 'failure'
    if attempt['outcome'] == 'success':
        return 'success'
    return 'unknown'


def replay(dataset_root, checker, output, *, split='eval'):
    output = Path(output).absolute()
    if output.exists():
        raise ValueError('shadow: new output directory required')
    dataset = _dataset(dataset_root)
    attempts = dataset['attempts']
    seen = {}
    for w in dataset['windows'][split]:
        attempt = attempts[w['attempt']]
        now = time.time_ns()
        request = PredictionRequest(
            state_ref=StateRef(sample_id=f"{attempt['session_id']}/{attempt['cycle_id']}/{w['frame_index']}",
                               observed_at_ns=now, rig_revision=dataset['rig_revision'],
                               calibration_revision=dataset['calibration_revision']),
            state=w['state'], action=w['action'], step_s=dataset['step_s'], action_source='replay:'+split)
        verdict = checker.check(request, now).verdict
        seen.setdefault(w['attempt'], []).append(verdict)
    table = {}
    for index, verdicts in seen.items():
        blocked = any(v in ('HOLD', 'REJECT') for v in verdicts)
        key = f"{_label(attempts[index])}/{'blocked' if blocked else 'not_blocked'}"
        table[key] = table.get(key, 0) + 1
    report = dict(schema='rosy.world-model-shadow-replay.v1', split=split, attempts=len(seen),
                  windows=sum(len(v) for v in seen.values()), model_digest=checker.artifact['digest'],
                  verdicts={v: sum(x.count(v) for x in seen.values())
                            for v in ('NO_OBJECTION', 'HOLD', 'REJECT', 'ABSTAIN')},
                  attempts_by_label=table, replay_input_age='set to zero; live staleness is not exercised',
                  shadow_only=True, live_veto=False)
    output.mkdir(parents=True)
    (output/'shadow-replay.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--digest', required=True, help='approved artifact digest')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--split', default='eval', choices=('eval', 'test'))
    parser.add_argument('--hold-sigma', type=float, default=CheckerConfig.hold_sigma)
    args = parser.parse_args(argv)
    try:
        checker = WorldModelChecker(args.artifact, args.digest, CheckerConfig(hold_sigma=args.hold_sigma))
        report = replay(args.dataset, checker, args.out, split=args.split)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
