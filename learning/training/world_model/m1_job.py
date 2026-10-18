"""D-782 M1: low-dimensional action-conditioned dynamics as a bootstrap ridge ensemble.

Input is the current normalized joint/gripper state plus the next `horizon` controller references; output is the
change to each of the next `horizon` states. Member disagreement is the uncertainty. Train split only, train-only
normalization, deterministic seed, new output directory. Training is not promotion or deployment.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'contracts/learning/src'))
sys.path.insert(0, str(ROOT/'learning/curation/omx'))
from rosy.contracts.learning.prediction import ARTIFACT_SCHEMA, artifact_digest, forward, validate_artifact
from world_model_dataset import load


def _require(value, message):
    if not value:
        raise ValueError('M1 job: ' + message)


def design(windows):
    """Feature rows [state, flattened action] and target rows [next_state - state, ...]."""
    x = np.array([w['state'] + [v for a in w['action'] for v in a] for w in windows], dtype=np.float64)
    y = np.array([[v - s for n in w['next_states'] for v, s in zip(n, w['state'])] for w in windows],
                 dtype=np.float64)
    return x, y


def fit_member(xs, y, ridge):
    x_mean, y_mean = xs.mean(axis=0), y.mean(axis=0)
    xc, yc = xs - x_mean, y - y_mean
    weights = np.linalg.solve(xc.T @ xc + ridge*np.eye(xs.shape[1]), xc.T @ yc)
    return y_mean - x_mean @ weights, weights


def train(dataset_root, output, *, members=5, ridge=1.0, seed=7820):
    _require(type(members) is int and 2 <= members <= 32, 'members must be 2..32')
    _require(ridge > 0, 'positive ridge strength required')
    output = Path(output).absolute()
    _require(not output.exists(), 'new output directory required')
    dataset, dataset_sha256 = load(dataset_root)
    windows = dataset['windows']['train']
    _require(len(windows) >= 2, 'at least two train windows required')
    x, y = design(windows)
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-9] = 1.0
    xs = (x - mean) / std
    rng = np.random.default_rng(seed)
    ensemble = []
    for _ in range(members):
        pick = rng.integers(0, len(windows), size=len(windows))
        bias, weights = fit_member(xs[pick], y[pick], ridge)
        ensemble.append(dict(bias=bias.tolist(), weights=weights.tolist()))
    states = np.array([w['state'] for w in windows] + [n for w in windows for n in w['next_states']])
    actions = np.array([a for w in windows for a in w['action']])
    artifact = dict(schema=ARTIFACT_SCHEMA, kind='m1_linear_ensemble', horizon=dataset['horizon'],
                    step_s=dataset['step_s'], rig_revision=dataset['rig_revision'],
                    calibration_revision=dataset['calibration_revision'], dataset_manifest_sha256=dataset_sha256,
                    feature_mean=mean.tolist(), feature_std=std.tolist(),
                    state_min=states.min(axis=0).tolist(), state_max=states.max(axis=0).tolist(),
                    action_min=actions.min(axis=0).tolist(), action_max=actions.max(axis=0).tolist(),
                    members=ensemble, ridge_lambda=ridge, seed=seed, train_windows=len(windows))
    artifact['digest'] = artifact_digest(artifact)
    validate_artifact(artifact)
    errors = []
    for w in windows:
        predicted, _ = forward(artifact, w['state'], w['action'])
        errors.extend(abs(p - n) for row_p, row_n in zip(predicted, w['next_states']) for p, n in zip(row_p, row_n))
    output.mkdir(parents=True)
    (output/'artifact.json').write_text(json.dumps(artifact, sort_keys=True) + '\n', encoding='utf-8')
    report = dict(schema='rosy.world-model-train-report.v1', artifact_digest=artifact['digest'],
                  dataset_manifest_sha256=dataset_sha256, train_windows=len(windows), members=members,
                  ridge_lambda=ridge, seed=seed, train_mae=float(np.mean(errors)),
                  promoted=False, deployed=False, offline_only=True)
    (output/'train-report.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('dataset', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--members', type=int, default=5)
    parser.add_argument('--ridge', type=float, default=1.0)
    parser.add_argument('--seed', type=int, default=7820)
    args = parser.parse_args(argv)
    try:
        report = train(args.dataset, args.out, members=args.members, ridge=args.ridge, seed=args.seed)
    except (ValueError, OSError) as exc:
        parser.exit(2, f'refused: {exc}\n')
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
