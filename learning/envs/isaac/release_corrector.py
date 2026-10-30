"""Release corrector: imitate the IK packed-release command from noisy state (plan 2026-10-30, BC before RL).

The model replaces only `packing_target`'s command; release_footprint_fits, cube_release_ready, the prior-stack
window and the settle window still decide whether the gripper may open.
"""
import copy
import hashlib
import io
import json
import math
from pathlib import Path

import numpy as np

from mapped_stack_fixture import center_neighbor, cube_release_target, measured_motion, plan, row_gaps, stable_box

FEATURES = 22  # held pos 3, quat 4, tcp 3, target 3, neighbour face y + top z 2, level 3, row 3, iteration 1


def observation(sample, index, fixture, iteration):
    """Feature vector the model sees; positions are relative to the target cell."""
    item = plan(True, fixture=fixture)[index]
    arm, box, target = item['arm'], sample['boxes'][index], item['target']
    rel = lambda v: [v[k]-target[k] for k in range(3)]  # noqa: E731
    face = [0., 0.]
    if item['cell'][1] != fixture.get('center_row', 1):
        _, y, top = center_neighbor(index, sample, fixture)
        face = [y-target[1], top-target[2]]
    level, row = item['cell'][2], item['cell'][1]
    return (rel(box['position']) + list(box['orientation']) + rel(sample['tcps'][arm]) + list(target) + face
            + [float(level == k) for k in range(3)] + [float(row == k) for k in range(3)] + [float(iteration)])


def release_demonstrations(report):
    """One row per release-feedback iteration of every released layer, with the layer's settled outcome."""
    fixture, trial = report['fixture'], report['trials'][0]
    items = plan(True, fixture=fixture)
    rows = []
    for index, layer in enumerate(trial.get('layers', [])):
        commands, after = layer.get('release_commands'), layer.get('release_samples')
        if not commands or not after or 'opened_sample' not in layer or not layer.get('settle_samples'):
            continue
        settled = measured_motion(layer['settle_samples'])[-1]
        box, target = settled['boxes'][index], items[index]['target']
        outcome = dict(position_error_mm=1000*math.dist(box['position'], target),
                       stable=stable_box(box, index, True, fixture=fixture),
                       gaps_mm=[1000*g for g in row_gaps(settled, fixture, index+1)] if fixture.get('row_gap_band_m') else None)
        arm = items[index]['arm']
        for k, (sample, command) in enumerate(zip([layer['carry_sample']] + after[:-1], commands)):
            rows.append(dict(index=index, iteration=k, observation=observation(sample, index, fixture, k),
                             action=[command[j]-sample['tcps'][arm][j] for j in range(3)], outcome=outcome))
    return rows


def augment(sample, index, fixture, rng, *, shift_m=.003, slip_m=.001, yaw_rad=.02, noise_m=(.002, .005)):
    """A perturbed held state, the teacher command recomputed from its true poses, and a noisy observation.

    Returns (noisy_obs, clean_obs, action, true_sample), or None when the teacher refuses the perturbed footprint.
    """
    truth = copy.deepcopy(sample)
    arm = plan(True, fixture=fixture)[index]['arm']
    box = truth['boxes'][index]
    shift = rng.uniform(-shift_m, shift_m, 3)
    box['position'] = (np.add(box['position'], shift)).tolist()
    truth['tcps'][arm] = (np.add(truth['tcps'][arm], shift + rng.uniform(-slip_m, slip_m, 3))).tolist()
    turn = rng.uniform(-yaw_rad, yaw_rad)
    w, x, y, z = box['orientation']
    c, s = math.cos(turn/2), math.sin(turn/2)
    box['orientation'] = [w*c-z*s, x*c-y*s, y*c+x*s, z*c+w*s]
    iteration = int(rng.integers(1, fixture.get('release_feedback_iterations', 4)))
    try:
        command = cube_release_target(index, truth, box['position'][2], fixture=fixture)
    except ValueError:
        return None
    action = [command[k]-truth['tcps'][arm][k] for k in range(3)]
    clean = observation(truth, index, fixture, iteration)
    error = rng.normal(0., 1., 3)
    error *= rng.uniform(*noise_m) / max(np.linalg.norm(error), 1e-12)  # estimate error of 2-5 mm in a random direction
    noisy = [v+e for v, e in zip(clean[:3], error)] + clean[3:]
    return noisy, clean, action, truth


class MLP:
    """Least-squares linear map plus two tanh layers fitted to its residual; numpy only, so it runs on any lab host.

    The teacher command is nearly linear in the exact TCP once the held-box estimate is noisy, and a plain tanh MLP
    underfit it (1.57 mm against ridge 0.33 mm); the residual network keeps at least the linear accuracy.
    """

    def __init__(self, params, mean, scale, linear):
        self.params, self.mean, self.scale, self.linear = params, mean, scale, linear

    @classmethod
    def fit(cls, x, y, *, hidden=64, epochs=300, lr=3e-3, seed=0):
        x, y = np.asarray(x, float), np.asarray(y, float)
        mean, scale = x.mean(0), x.std(0) + 1e-6
        rng = np.random.default_rng(seed)
        sizes = [x.shape[1], hidden, hidden, y.shape[1]]
        params = [[rng.normal(0, 1/math.sqrt(a), (a, b)), np.zeros(b)] for a, b in zip(sizes, sizes[1:])]
        moments = [[[np.zeros_like(p), np.zeros_like(p)] for p in layer] for layer in params]
        xs = (x-mean)/scale
        design = np.c_[xs, np.ones(len(xs))]
        linear = np.linalg.lstsq(design, y, rcond=None)[0]
        y = y - design @ linear
        out = np.abs(y).max() + 1e-9
        ys = y/out
        for t in range(1, epochs+1):
            acts = [xs]
            for w, b in params[:-1]:
                acts.append(np.tanh(acts[-1] @ w + b))
            grad = 2*(acts[-1] @ params[-1][0] + params[-1][1] - ys) / len(xs)
            for layer in range(len(params)-1, -1, -1):
                w = params[layer][0]
                grads = [acts[layer].T @ grad, grad.sum(0)]
                grad = (grad @ w.T) * (1 - acts[layer]**2) if layer else None
                for k, g in enumerate(grads):
                    m, v = moments[layer][k]
                    m[:] = .9*m + .1*g; v[:] = .999*v + .001*g*g
                    params[layer][k] -= lr * (m/(1-.9**t)) / (np.sqrt(v/(1-.999**t)) + 1e-8)
        params[-1] = [params[-1][0]*out, params[-1][1]*out]
        return cls(params, mean, scale, linear)

    def predict(self, x):
        xs = (np.asarray(x, float)-self.mean)/self.scale
        h = xs
        for w, b in self.params[:-1]:
            h = np.tanh(h @ w + b)
        return np.c_[xs, np.ones(len(xs))] @ self.linear + h @ self.params[-1][0] + self.params[-1][1]

    def save(self, path):
        arrays = {'mean': self.mean, 'scale': self.scale, 'linear': self.linear}
        arrays.update({f'{k}_{i}': p for i, layer in enumerate(self.params) for k, p in zip('wb', layer)})
        buffer = io.BytesIO()
        np.savez(buffer, **arrays)
        Path(path).write_bytes(buffer.getvalue())
        return hashlib.sha256(buffer.getvalue()).hexdigest()

    @classmethod
    def load(cls, path, sha256):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError('release corrector sha256 differs from the pinned model')
        data = np.load(io.BytesIO(raw))
        count = sum(1 for k in data.files if k.startswith('w_'))
        return cls([[data[f'w_{i}'], data[f'b_{i}']] for i in range(count)], data['mean'], data['scale'], data['linear'])


def describe(model_sha256, rows, holdout_error_mm):
    """Artifact metadata kept beside the weights."""
    return json.dumps(dict(schema='rosy.omx-release-corrector/1', sha256=model_sha256, features=FEATURES,
                           rows=rows, holdout_mean_abs_error_mm=holdout_error_mm,
                           scope='SIM_IK_TEACHER_BC_NOT_RL_NOT_HARDWARE'), sort_keys=True)
