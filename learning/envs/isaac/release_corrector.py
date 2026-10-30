"""Release corrector: imitate the IK packed-release command from noisy state (plan 2026-10-30, BC before RL).

The model replaces only `packing_target`'s command; release_footprint_fits, cube_release_ready, the prior-stack
window and the settle window still decide whether the gripper may open.
"""
import copy
import hashlib
import io
import json
import math
import os
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


def load_corrector(fixture):
    """The pinned model of an evaluation case, or None when the IK teacher keeps the command."""
    spec = fixture.get('release_corrector')
    return MLP.load(Path(__file__).with_name('models') / spec['file'], spec['sha256']) if spec else None


def load_residual(fixture):
    """The pinned RL residual of an exploring case, or None."""
    spec = fixture.get('release_residual')
    return Residual.load(Path(__file__).with_name('models') / spec['file'], spec['sha256']) if spec else None


def rl_rows(report):
    """(observation, noise, reward) for every explored decision: its layer's settled reward, or BLOCKED_REWARD."""
    outcomes = {r['index']: r['outcome'] for r in release_demonstrations(report)}
    rows = []
    for index, layer in enumerate(report['trials'][0].get('layers', [])):
        reward = release_reward(outcomes[index]) if index in outcomes else BLOCKED_REWARD
        rows.extend((d['observation'], d['noise'], reward) for d in layer.get('release_exploration', []))
    return rows


def estimate(sample, index, fixture, rng):
    """The sample as a 2-5 mm held-box position estimate would report it; everything else stays measured."""
    value = copy.deepcopy(sample)
    low, high = fixture['release_estimate_noise_m']
    error = rng.normal(0., 1., 3)
    error *= rng.uniform(low, high) / max(np.linalg.norm(error), 1e-12)
    box = value['boxes'][index]
    box['position'] = np.add(box['position'], error).tolist()
    return value


def corrector_command(model, sample, index, fixture, iteration, *, max_step_m=.005):
    """TCP command: the measured TCP plus the model's correction, clipped to max_step_m per axis.

    Out-of-distribution input made the v0 model extrapolate by ~25 cm in a synthetic hold; the clip bounds any
    such step, and cube_release_ready on the measured pose still decides whether the gripper opens.
    """
    arm = plan(True, fixture=fixture)[index]['arm']
    correction = np.clip(model.predict([observation(sample, index, fixture, iteration)])[0], -max_step_m, max_step_m)
    return np.add(sample['tcps'][arm], correction).tolist()


class Residual:
    """Linear correction added to the BC command, learned from release outcomes (REINFORCE between runs)."""

    def __init__(self, weights):
        self.weights = np.asarray(weights, float)

    @classmethod
    def zero(cls):
        return cls(np.zeros((FEATURES+1, 3)))

    def predict(self, x):
        x = np.asarray(x, float)
        return np.c_[x, np.ones(len(x))] @ self.weights

    @classmethod
    def update(cls, residual, observations, noises, rewards, *, lr):
        """One policy-gradient step: move the mean correction along noise that earned above-average reward.

        For a Gaussian policy the score of the mean is noise/sigma; scaling the step by sigma**2 leaves
        advantage x noise x sigma, and `lr` absorbs sigma so it is in metres per unit of reward and noise.
        """
        x = np.c_[np.asarray(observations, float), np.ones(len(observations))]
        advantage = np.asarray(rewards, float) - np.mean(rewards)
        gradient = x.T @ (advantage[:, None] * np.asarray(noises, float)) / len(x)
        return cls(residual.weights + lr * gradient)

    def save(self, path):
        buffer = io.BytesIO()
        np.savez(buffer, weights=self.weights)
        Path(path).write_bytes(buffer.getvalue())
        return hashlib.sha256(buffer.getvalue()).hexdigest()

    @classmethod
    def load(cls, path, sha256):
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError('release residual sha256 differs from the pinned file')
        return cls(np.load(io.BytesIO(raw))['weights'])


def policy_command(model, residual, sample, index, fixture, iteration, rng, *, sigma, max_step_m=.005):
    """Exploring command: BC correction + residual + Gaussian noise (sigma metres), clipped; returns the noise too."""
    arm = plan(True, fixture=fixture)[index]['arm']
    tcp = np.array(sample['tcps'][arm])
    obs = [observation(sample, index, fixture, iteration)]
    mean = model.predict(obs)[0] + residual.predict(obs)[0]
    noise = rng.normal(size=3)
    return (tcp + np.clip(mean + sigma*noise, -max_step_m, max_step_m)).tolist(), noise.tolist()


BLOCKED_REWARD = -20.  # an explored release that never settled (opening blocked or the run stopped there)


def release_reward(outcome):
    """Higher is better: settled position error (mm), distance outside the 2-5 mm gap band (x3), instability (-10)."""
    gaps = outcome.get('gaps_mm') or []
    outside = sum(max(2.-g, 0., g-5.) for g in gaps)
    return -outcome['position_error_mm'] - 3*outside - (0. if outcome['stable'] else 10.)


def train(report_paths, out_dir, *, per_snapshot=400, seed=0, epochs=400):
    """Fit the corrector on augmented release snapshots; keep weights, sha256 and holdout evidence together.

    The simulation is deterministic per seed, so repeated runs repeat releases; they are counted once. Each
    release's last pre-command snapshot is held out, the earlier ones train.
    """
    rng = np.random.default_rng(seed)
    seen, train_rows, hold_rows, snapshots, sources = set(), [], [], 0, []
    for path in report_paths:
        raw = Path(path).read_bytes()
        report = json.loads(raw)
        fixture = report['fixture']
        for index, layer in enumerate(report['trials'][0].get('layers', [])):
            if not layer.get('release_commands') or not layer.get('release_samples'):
                continue
            key = json.dumps([fixture.get('revision'), index, layer['release_commands']])
            if key in seen:
                continue
            seen.add(key)
            sources.append(hashlib.sha256(raw).hexdigest())
            group = [layer['carry_sample']] + layer['release_samples'][:-1]
            snapshots += len(group)
            for k, sample in enumerate(group):
                rows = [r for r in (augment(sample, index, fixture, rng) for _ in range(per_snapshot)) if r]
                (hold_rows if k == len(group)-1 else train_rows).extend(rows)
    x, y = np.array([r[0] for r in train_rows]), np.array([r[2] for r in train_rows])
    hx, hy = np.array([r[0] for r in hold_rows]), np.array([r[2] for r in hold_rows])
    model = MLP.fit(x, y, epochs=epochs, seed=seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    meta = dict(schema='rosy.omx-release-corrector/1', sha256=model.save(out/'release-corrector.npz'),
                features=FEATURES, releases=len(seen), snapshots=snapshots, train_rows=len(x), holdout_rows=len(hx),
                holdout_mean_abs_error_mm=float(np.abs(model.predict(hx)-hy).mean()*1000),
                holdout_mean_baseline_mm=float(np.abs(y.mean(0)-hy).mean()*1000),
                source_report_sha256=sorted(set(sources)), seed=seed, epochs=epochs,
                scope='SIM_IK_TEACHER_BC_NOT_RL_NOT_HARDWARE')
    (out/'release-corrector.json').write_text(json.dumps(meta, sort_keys=True), encoding='utf-8')
    return meta


if __name__ == '__main__':
    import sys
    if len(sys.argv) >= 4 and sys.argv[1] == 'train':
        print(json.dumps(train(sys.argv[3:], sys.argv[2]), sort_keys=True))
    elif len(sys.argv) >= 6 and sys.argv[1] == 'rl-update':
        # rl-update OUT.npz RESIDUAL.npz RESIDUAL_SHA256 REPORT.json ...
        rows = [row for path in sys.argv[5:] for row in rl_rows(json.loads(Path(path).read_text(encoding='utf-8')))]
        if not rows:
            sys.exit('rl-update: no explored decision has a settled outcome in these reports; nothing to learn')
        before = Residual.load(sys.argv[3], sys.argv[4])
        after = Residual.update(before, *zip(*rows), lr=float(os.environ.get('RL_LR', '.0002')))
        print(json.dumps(dict(decisions=len(rows), mean_reward=float(np.mean([r[2] for r in rows])),
                              sha256=after.save(sys.argv[2])), sort_keys=True))
    else:
        sys.exit('usage: release_corrector.py train OUT_DIR REPORT.json ... | rl-update OUT.npz RESIDUAL.npz SHA REPORT.json ...')
