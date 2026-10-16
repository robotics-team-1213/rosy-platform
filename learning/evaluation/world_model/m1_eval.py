"""D-782 §6 offline acceptance for an M1 world-model artifact on held-out sessions.

The model must beat both simple baselines at every horizon step: hold (the state does not move) and reach (the
next state equals the controller reference that drove it). The 2-sigma coverage of the ensemble spread is
reported, not gated. A pass is offline evidence only; it is not promotion, shadow or live acceptance.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
sys.path.insert(0, str(ROOT/'learning/curation/omx'))
from rosy.contracts.learning.prediction import forward, validate_artifact
from world_model_dataset import load


def _require(value, message):
    if not value:
        raise ValueError('M1 eval: ' + message)


def evaluate(dataset_root, artifact_path, output, *, split='eval'):
    _require(split in ('eval', 'test'), 'evaluate on eval, or test once for the final report')
    output = Path(output).absolute()
    _require(not output.exists(), 'new output directory required')
    dataset, dataset_sha256 = load(dataset_root)
    artifact = validate_artifact(json.loads(Path(artifact_path).read_text(encoding='utf-8')))
    _require(artifact['dataset_manifest_sha256'] == dataset_sha256, 'artifact was trained on another dataset')
    _require(artifact['horizon'] == dataset['horizon']
             and artifact['rig_revision'] == dataset['rig_revision']
             and artifact['calibration_revision'] == dataset['calibration_revision'], 'artifact scope differs')
    windows = dataset['windows'][split]
    _require(bool(windows), f'no {split} windows')
    horizon = dataset['horizon']
    sums = {name: [0.0]*horizon for name in ('model', 'hold', 'reach')}
    covered = scored = 0
    for w in windows:
        predicted, sigma = forward(artifact, w['state'], w['action'])
        for k in range(horizon):
            truth = w['next_states'][k]
            for name, guess in (('model', predicted[k]), ('hold', w['state']), ('reach', w['action'][k])):
                sums[name][k] += sum(abs(g - t) for g, t in zip(guess, truth)) / len(truth)
            for p, t, s in zip(predicted[k], truth, sigma[k]):
                scored += 1
                covered += abs(p - t) <= 2*s
    mae = {name: [v/len(windows) for v in values] for name, values in sums.items()}
    beats = [mae['model'][k] < mae['hold'][k] and mae['model'][k] < mae['reach'][k] for k in range(horizon)]
    report = dict(schema='rosy.world-model-eval-report.v1', split=split, windows=len(windows),
                  artifact_digest=artifact['digest'], dataset_manifest_sha256=dataset_sha256,
                  mae_by_step=mae, beats_both_baselines_by_step=beats, two_sigma_coverage=covered/scored,
                  verdict='pass' if all(beats) else 'reject', offline_only=True, promoted=False)
    output.mkdir(parents=True)
    (output/'eval-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--split', default='eval', choices=('eval', 'test'))
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.dataset, args.artifact, args.out, split=args.split)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(report))
    return 0 if report['verdict'] == 'pass' else 3


if __name__ == '__main__':
    raise SystemExit(main())
