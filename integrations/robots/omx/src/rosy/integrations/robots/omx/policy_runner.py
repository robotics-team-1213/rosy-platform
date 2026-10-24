"""D-854 Policy Runner: one inference loop with pluggable policy types, unit spaces and arm targets.

The runner proposes joint targets only. CORE and the OMX owner keep admission, limits, the stop fence and
HOLD (D-800, D-858). LeRobot and torch are imported inside the LeRobot adapter only.
"""
import argparse
import base64
import json
import math
from pathlib import Path
import statistics
import time

#: Policy types this runner may load (D-854 §1). Adding one needs an ADR revision and the adapter tests.
ALLOWED_POLICY_TYPES = frozenset({'act', 'smolvla'})
STAGES = ('observe', 'preprocess', 'infer', 'postprocess', 'submit')


class ActionSpace:
    """Policy output unit -> ArmTarget unit. Only declared conversions exist; anything else is refused.

    shortcut: identity only. lerobot_norm_v1 -> CORE ROS joint rad needs the measured ROS joint <-> Dynamixel
    motor map (sign, origin, gripper units), which no code defines yet (D-854 step 2 decision 2026-10-24).
    """

    def __init__(self, policy_unit, target_unit):
        if policy_unit != target_unit:
            raise ValueError(f'no defined conversion {policy_unit} -> {target_unit}')
        self.policy_unit = self.target_unit = target_unit

    def __call__(self, values):
        return list(values)


class LeRobotAdapter:
    """LeRobot 0.4.4 policies through their saved pre/post processors; one adapter serves ACT and SmolVLA."""

    def __init__(self, checkpoint, device, *, joint_names, cameras, single_step_override=False):
        from lerobot.configs.policies import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        from lerobot.policies.utils import prepare_observation_for_inference
        import torch

        config = PreTrainedConfig.from_pretrained(checkpoint)
        if config.type not in ALLOWED_POLICY_TYPES:
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
        self.policy_type, self.n_action_steps = config.type, config.n_action_steps
        self.joint_names, self.cameras = list(joint_names), list(cameras)
        self._torch, self._device, self._prepare = torch, torch.device(device), prepare_observation_for_inference

    def _sync(self):
        if self._device.type == 'cuda':
            self._torch.cuda.synchronize()  # Stage times must include the GPU work, not only its launch.

    def preprocess(self, observation, task):
        """observation: {'positions': [...], 'images': {name: HWC uint8}}; same steps as lerobot predict_action."""
        import numpy as np
        frame = {'observation.state': np.asarray(observation['positions'], dtype=np.float32),
                 **{f'observation.images.{name}': observation['images'][name] for name in self.cameras}}
        with self._torch.inference_mode():
            batch = self.pre(self._prepare(frame, self._device, task, None))
        self._sync()
        return batch

    def infer(self, batch):
        with self._torch.inference_mode():
            action = self.policy.select_action(batch)
        self._sync()
        return action

    def postprocess(self, action):
        with self._torch.inference_mode():
            values = self.post(action).squeeze(0).tolist()
        if len(values) != len(self.joint_names) or not all(math.isfinite(v) for v in values):
            raise ValueError('policy output differs from the installed joints')
        return values


def step(adapter, target, space, task, clock=time.perf_counter_ns):
    """One observe -> infer -> submit cycle; returns the per-stage nanoseconds. A failure leaves stop to the target."""
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
    """CORE arm policy HTTP (D-800, D-854 §3) through CoreArmClient; rad, installed cameras in order."""
    unit = 'ros_joint_rad'

    def __init__(self, client):
        import numpy as np
        self.client, self._np = client, np

    def observe(self):
        source = self.client.get_observation()
        images = {}
        for camera in source['cameras']:
            _, height, width = camera['shape']
            raw = base64.b64decode(camera['rgb_base64'], validate=True)
            images[camera['name']] = self._np.frombuffer(raw, dtype=self._np.uint8).reshape(height, width, 3)
        return {'positions': [source['positions'][n] for n in self.client.info['joint_names']], 'images': images}

    def submit(self, positions):
        return self.client.send_action(positions)


class SyntheticTarget:
    """Latency bench target: fixed frames, no CORE. Observe and submit stages then measure nothing real."""
    unit = 'ros_joint_rad'

    def __init__(self, joint_names, shapes, seed=0):
        import numpy as np
        rng = np.random.default_rng(seed)
        self.joint_names = list(joint_names)
        self._observation = {'positions': [0.0] * len(joint_names),
                             'images': {n: rng.integers(0, 256, (h, w, 3), dtype=np.uint8) for n, (h, w) in shapes.items()}}

    def observe(self):
        return self._observation

    def submit(self, positions):
        return positions


def summarize(samples):
    """p50/p95/p99/max per stage and for the end-to-end sum, in nanoseconds."""
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


def main(argv=None):
    parser = argparse.ArgumentParser(description='D-854 policy latency bench on synthetic frames (no CORE, no robot)')
    parser.add_argument('checkpoint')
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--joints', nargs='+', required=True)
    parser.add_argument('--camera', action='append', required=True, metavar='NAME=HxW')
    parser.add_argument('--task', default='')
    parser.add_argument('--warmup', type=int, default=50)
    parser.add_argument('--steps', type=int, default=1000)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    shapes = {}
    for item in args.camera:
        name, size = item.split('=', 1)
        height, width = (int(v) for v in size.lower().split('x'))
        shapes[name] = (height, width)
    adapter = LeRobotAdapter(args.checkpoint, args.device, joint_names=args.joints, cameras=list(shapes),
                             single_step_override=True)
    report = measure(adapter, SyntheticTarget(args.joints, shapes), ActionSpace('ros_joint_rad', 'ros_joint_rad'),
                     args.task, warmup=args.warmup, steps=args.steps)
    import importlib.metadata as metadata
    import torch
    report.update(policy_type=adapter.policy_type, n_action_steps=adapter.n_action_steps,
                  saved_n_action_steps=adapter.saved_n_action_steps, device=args.device,
                  gpu=torch.cuda.get_device_name() if args.device.startswith('cuda') else None,
                  versions={k: metadata.version(k) for k in ('lerobot', 'torch')}, cameras=shapes,
                  target='synthetic: observe/submit stages exclude CORE and network')
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
    print(json.dumps(report['stages']['end_to_end']))


if __name__ == '__main__':
    main()
