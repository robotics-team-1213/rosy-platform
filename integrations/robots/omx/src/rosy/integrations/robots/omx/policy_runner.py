"""D-854 Policy Runner: one inference loop with pluggable policy types, unit spaces and arm targets.

The runner proposes joint targets only. CORE and the OMX owner keep admission, limits, the stop fence and
HOLD (D-800, D-858). LeRobot and torch are imported inside the LeRobot adapter only.
"""
import argparse
from contextlib import nullcontext
import base64
import hashlib
import json
import math
from pathlib import Path
import statistics
import time

#: Policy types the runner may load for execution (D-854 §1). Adding one needs an ADR revision and adapter tests.
ALLOWED_POLICY_TYPES = frozenset({'act'})
#: The latency bench may also time these before they are allowed for execution (D-854 step 5).
BENCH_POLICY_TYPES = ALLOWED_POLICY_TYPES | {'smolvla'}
#: Policy and target units. The first two are rosy.contracts.learning.action_space names; CORE speaks ROS joint rad.
UNITS = frozenset({'lerobot_norm_v1', 'dynamixel_rad_v1', 'ros_joint_rad'})
STAGES = ('observe', 'preprocess', 'infer', 'postprocess', 'submit')


class ActionSpace:
    """Policy output unit -> ArmTarget unit. Only declared conversions exist; anything else is refused.

    shortcut: identity only. lerobot_norm_v1 -> CORE ROS joint rad needs the measured ROS joint <-> Dynamixel
    motor map (sign, origin, gripper units), which no code defines yet (D-854 step 2 decision 2026-10-24).
    """

    def __init__(self, policy_unit, target_unit):
        if policy_unit not in UNITS or target_unit not in UNITS:
            raise ValueError('unknown unit')
        if policy_unit != target_unit:
            raise ValueError(f'no defined conversion {policy_unit} -> {target_unit}')
        self.policy_unit = self.target_unit = target_unit

    def __call__(self, values):
        return list(values)


class LeRobotAdapter:
    """LeRobot 0.4.4 policies through their saved pre/post processors, in predict_action's steps and AMP setting.

    ``unit`` is the checkpoint's declared action unit (from its dataset's action_space); the runner checks it.
    """

    def __init__(self, checkpoint, device, *, joint_names, cameras, unit, allowed_types=ALLOWED_POLICY_TYPES,
                 single_step_override=False):
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        from lerobot.policies.utils import prepare_observation_for_inference
        import torch

        if unit not in UNITS:
            raise ValueError('declared policy unit required')
        config = PreTrainedConfig.from_pretrained(checkpoint)
        if config.type not in allowed_types or not allowed_types <= BENCH_POLICY_TYPES:
            raise ValueError(f'policy type {config.type} is not allowed (D-854)')
        if getattr(config, 'temporal_ensemble_coeff', None) is not None:
            raise ValueError('temporal ensembling queues actions across observations')
        # CORE admits one target per observation until action chunks are decided (D-854 §3).
        self.saved_n_action_steps = config.n_action_steps
        if config.n_action_steps != 1:
            if not single_step_override:
                raise ValueError('n_action_steps=1 required; pass single_step_override to bench full inference')
            config.n_action_steps = 1
        config.pretrained_path, config.device = checkpoint, device
        self.policy = get_policy_class(config.type).from_pretrained(checkpoint, config=config)
        self.pre, self.post = make_pre_post_processors(policy_cfg=config, pretrained_path=checkpoint,
            preprocessor_overrides={'device_processor': {'device': device}})
        for part in (self.policy, self.pre, self.post):
            part.reset()
        self.policy_type, self.n_action_steps, self.unit = config.type, config.n_action_steps, unit
        self.joint_names, self.cameras = list(joint_names), list(cameras)
        self._torch, self._device, self._prepare = torch, torch.device(device), prepare_observation_for_inference
        self.use_amp = bool(config.use_amp) and self._device.type == 'cuda'

    def _context(self):
        torch = self._torch
        amp = torch.autocast(device_type=self._device.type) if self.use_amp else nullcontext()
        return torch.inference_mode(), amp

    def _sync(self):
        if self._device.type == 'cuda':
            self._torch.cuda.synchronize(self._device)  # Stage times must include the GPU work, not only its launch.

    def preprocess(self, observation, task):
        """observation: {'positions': [...], 'images': {name: HWC uint8}}; same steps as lerobot predict_action."""
        import numpy as np
        frame = {'observation.state': np.asarray(observation['positions'], dtype=np.float32),
                 **{f'observation.images.{name}': observation['images'][name] for name in self.cameras}}
        mode, amp = self._context()
        with mode, amp:
            batch = self.pre(self._prepare(frame, self._device, task, None))
        self._sync()
        return batch

    def infer(self, batch):
        mode, amp = self._context()
        with mode, amp:
            action = self.policy.select_action(batch)
        self._sync()
        return action

    def postprocess(self, action):
        mode, amp = self._context()
        with mode, amp:
            values = self.post(action).squeeze(0).tolist()
        return check_output(values, self.joint_names)


def check_output(values, joint_names):
    if len(values) != len(joint_names) or not all(math.isfinite(v) for v in values):
        raise ValueError('policy output differs from the installed joints')
    return values


def check_binding(adapter, target, space):
    """The policy, unit conversion and target must agree on units and joint order before any step."""
    if (adapter.unit, space.target_unit) != (space.policy_unit, target.unit):
        raise ValueError('policy, action space and target units differ')
    if list(adapter.joint_names) != list(target.joint_names):
        raise ValueError('policy joint order differs from the target')


def step(adapter, target, space, task, clock=time.perf_counter_ns):
    """One observe -> infer -> submit cycle; returns the per-stage nanoseconds. A failure never submits."""
    check_binding(adapter, target, space)
    marks = [clock()]
    observation = target.observe()
    marks.append(clock())
    batch = adapter.preprocess(observation, task)
    marks.append(clock())
    action = adapter.infer(batch)
    marks.append(clock())
    values = space(adapter.postprocess(action))
    marks.append(clock())
    target.submit(dict(zip(adapter.joint_names, values)))
    marks.append(clock())
    return {stage: b - a for stage, a, b in zip(STAGES, marks, marks[1:])}


class CoreArmTarget:
    """CORE arm policy HTTP (D-800, D-854 §3) through a connected CoreArmClient; ROS joint rad, cameras in order.

    CoreArmClient stops on an uncertain reply; the owner watchdog covers a lost connection.
    """
    unit = 'ros_joint_rad'

    def __init__(self, client):
        import numpy as np
        if not client.is_connected:
            raise ValueError('connect the CORE client first')
        self.client, self._np, self.joint_names = client, np, list(client.info['joint_names'])

    def observe(self):
        source = self.client.get_observation()
        images = {}
        for camera in source['cameras']:
            _, height, width = camera['shape']
            raw = base64.b64decode(camera['rgb_base64'], validate=True)
            images[camera['name']] = self._np.frombuffer(raw, dtype=self._np.uint8).reshape(height, width, 3).copy()
        return {'positions': [source['positions'][n] for n in self.joint_names], 'images': images}

    def submit(self, positions):
        return self.client.send_action(positions)


class SyntheticTarget:
    """Latency bench target: fixed frames, no CORE. Observe and submit stages then measure nothing real."""

    def __init__(self, joint_names, shapes, unit, seed=0):
        import numpy as np
        rng = np.random.default_rng(seed)
        self.joint_names, self.unit = list(joint_names), unit
        self._observation = {'positions': [0.0] * len(joint_names),
                             'images': {n: rng.integers(0, 256, (h, w, 3), dtype=np.uint8) for n, (h, w) in shapes.items()}}

    def observe(self):
        return self._observation

    def submit(self, positions):
        return positions


def summarize(samples):
    """Nearest-rank p50/p95/p99, max and mean per stage and for the end-to-end sum, in nanoseconds."""
    def quantiles(values):
        values = sorted(values)
        pick = lambda q: values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]
        return dict(p50=pick(.50), p95=pick(.95), p99=pick(.99), max=values[-1], mean=int(statistics.fmean(values)))
    if not samples:
        raise ValueError('no samples')
    report = {stage: quantiles([s[stage] for s in samples]) for stage in STAGES}
    report['end_to_end'] = quantiles([sum(s.values()) for s in samples])
    return report


def measure(adapter, target, space, task, *, warmup, steps, clock=time.perf_counter_ns):
    first = step(adapter, target, space, task, clock)
    for _ in range(warmup):
        step(adapter, target, space, task, clock)
    samples = [step(adapter, target, space, task, clock) for _ in range(steps)]
    return dict(first_step=first, warmup=warmup, steps=steps, stages=summarize(samples))


def checkpoint_digest(path):
    """sha256 over every file's relative path and bytes, so the report names exactly what ran (D-854 §2)."""
    digest = hashlib.sha256()
    root = Path(path)
    files = sorted(p for p in root.rglob('*') if p.is_file() and '.cache' not in p.relative_to(root).parts) if root.is_dir() else []
    if not files:
        raise ValueError('a local checkpoint directory with files is required')  # a Hub ID would hash nothing
    for item in files:
        digest.update(item.relative_to(root).as_posix().encode() + b'\0' + item.read_bytes())
    return digest.hexdigest()


def checkpoint_identity(path):
    """A Hugging Face cache snapshot is named by repo and revision; any other checkpoint by its path."""
    parts = Path(path).resolve().parts
    if len(parts) >= 3 and parts[-2] == 'snapshots' and parts[-3].startswith('models--'):
        return dict(hub_repo='/'.join(parts[-3].split('--')[1:]), hub_revision=parts[-1])
    return dict(checkpoint=str(path))


def main(argv=None):
    parser = argparse.ArgumentParser(description='D-854 policy latency bench on synthetic frames (no CORE, no robot)')
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--joints', nargs='+', required=True)
    parser.add_argument('--camera', action='append', required=True, metavar='NAME=HxW')
    parser.add_argument('--unit', choices=sorted(UNITS), default='lerobot_norm_v1')
    parser.add_argument('--task', default='')
    parser.add_argument('--warmup', type=int, default=50)
    parser.add_argument('--steps', type=int, default=1000)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.out.exists():
        raise SystemExit('report exists; choose a new path')
    checkpoint_sha256 = checkpoint_digest(args.checkpoint)
    shapes = {}
    for item in args.camera:
        name, size = item.split('=', 1)
        height, width = (int(v) for v in size.lower().split('x'))
        shapes[name] = (height, width)
    adapter = LeRobotAdapter(args.checkpoint, args.device, joint_names=args.joints, cameras=list(shapes),
                             unit=args.unit, allowed_types=BENCH_POLICY_TYPES, single_step_override=True)
    report = measure(adapter, SyntheticTarget(args.joints, shapes, args.unit), ActionSpace(args.unit, args.unit),
                     args.task, warmup=args.warmup, steps=args.steps)
    import importlib.metadata as metadata
    import torch
    device = adapter._device
    report.update(policy_type=adapter.policy_type, n_action_steps=adapter.n_action_steps,
                  saved_n_action_steps=adapter.saved_n_action_steps, use_amp=adapter.use_amp, device=str(device),
                  gpu=torch.cuda.get_device_name(device) if device.type == 'cuda' else None,
                  **checkpoint_identity(args.checkpoint), checkpoint_sha256=checkpoint_sha256,
                  versions={k: metadata.version(k) for k in ('lerobot', 'torch')}, cameras=shapes,
                  target='synthetic: observe/submit stages exclude CORE and network')
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report['stages']['end_to_end']))


if __name__ == '__main__':
    main()
