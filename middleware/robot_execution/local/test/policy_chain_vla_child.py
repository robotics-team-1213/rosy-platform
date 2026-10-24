"""D-866 P0 child: the D-854 policy runner with a SmolVLA checkpoint against a SIM CORE (GPU venv, no ROS).

The parent (policy_chain_vla_gazebo.py) drives it line by line on stdin; every reply is one `VLA_CHILD=` JSON line.
"""
import json
import sys
import time

from rosy.integrations.robots.omx import policy_runner as runner
from rosy.integrations.robots.omx.core_arm_client import CoreArmClient, CoreArmError

#: CORE camera name -> the SmolVLA base checkpoint's image key.
CAMERA_KEYS = {'top': 'camera1', 'front': 'camera2'}


def emit(value):
    print('VLA_CHILD=' + json.dumps(value), flush=True)


def clamp(raw, observed, limits, max_step):
    """Keep each target within max_step of the observed joint and inside its limits.

    shortcut: the untrained base model's output is arbitrary; this only makes it admissible so the execution
    contract can be exercised. Remove when a fine-tuned checkpoint runs (D-864 §5).
    """
    out = []
    for value, now, (low, high) in zip(raw, observed, limits):
        out.append(min(high, max(low, min(now + max_step, max(now - max_step, value)))))
    return out


class SimProbeTarget(runner.CoreArmTarget):
    """CoreArmTarget for the P0 probe: renames cameras to the checkpoint keys and clamps the proposal."""

    def __init__(self, client, *, policy_type, limits, max_step, keys=CAMERA_KEYS):
        super().__init__(client, policy_type=policy_type, sim_probe=True)
        self.limits, self.max_step, self.keys = list(limits), max_step, dict(keys)
        self.delay_s, self.last = 0.0, {}
        self._observed_at, self._positions = None, None

    def observe(self):
        observation = super().observe()
        if set(observation['images']) != set(self.keys):
            raise ValueError('CORE cameras differ from the probe camera keys')
        observation['images'] = {self.keys[name]: image for name, image in observation['images'].items()}
        self._observed_at, self._positions = time.monotonic(), list(observation['positions'])
        return observation

    def submit(self, positions):
        raw = [positions[name] for name in self.joint_names]
        target = clamp(raw, self._positions, self.limits, self.max_step)
        if self.delay_s:
            time.sleep(max(0.0, self._observed_at + self.delay_s - time.monotonic()))
        self.last = dict(raw=raw, submitted=target, observed=self._positions,
                         observe_to_submit_s=time.monotonic()-self._observed_at)
        return super().submit(dict(zip(self.joint_names, target)))


def main():
    settings = json.loads(sys.stdin.readline())
    import torch
    torch.set_num_threads(settings.get('torch_threads', 2))  # Share the run's CPU quota with Gazebo, CORE and Fleet.
    joints, checkpoint = settings['joint_names'], settings['checkpoint']
    adapter = runner.LeRobotAdapter(checkpoint, 'cuda', joint_names=joints, cameras=list(CAMERA_KEYS.values()),
                                    unit='ros_joint_rad', allowed_types=runner.SIM_PROBE_POLICY_TYPES,
                                    single_step_override=True)
    space = runner.ActionSpace('ros_joint_rad', 'ros_joint_rad')
    shape = tuple(settings['camera_shape'][1:])
    warm = runner.measure(adapter, runner.SyntheticTarget(joints, {k: shape for k in CAMERA_KEYS.values()},
                                                          'ros_joint_rad'), space, settings['task'],
                          warmup=settings.get('warmup', 20), steps=20)
    import importlib.metadata as metadata
    import torch
    emit(dict(ready=True, ros_imported='rclpy' in sys.modules, policy_type=adapter.policy_type,
              n_action_steps=adapter.n_action_steps, saved_n_action_steps=adapter.saved_n_action_steps,
              use_amp=adapter.use_amp, checkpoint_sha256=runner.checkpoint_digest(checkpoint),
              **runner.checkpoint_identity(checkpoint), gpu=torch.cuda.get_device_name(adapter._device),
              versions={k: metadata.version(k) for k in ('lerobot', 'torch', 'transformers')},
              warmup=warm['stages']['end_to_end'], cuda_peak_bytes=torch.cuda.max_memory_allocated()))
    core = json.loads(sys.stdin.readline())
    client = CoreArmClient(core['url'], token=open(core['token_file'], encoding='utf-8').read().strip(),
                           policy_revision=core['policy_revision'])
    client.connect()
    target = SimProbeTarget(client, policy_type=adapter.policy_type, limits=settings['limits'],
                            max_step=settings['max_step_rad'])
    emit(dict(connected=client.is_connected, cameras=client.info['cameras']))
    for line in sys.stdin:
        op = json.loads(line)['op']
        try:
            if op in ('step', 'stale'):
                target.delay_s = settings['stale_delay_s'] if op == 'stale' else 0.0
                marks = []
                def clock():
                    marks.append(time.perf_counter_ns())
                    return marks[-1]
                try:
                    stages = runner.step(adapter, target, space, settings['task'], clock=clock)
                finally:
                    partial = {stage: b-a for stage, a, b in zip(runner.STAGES, marks, marks[1:])}
                    target.last['stages'] = partial
                emit(dict(op=op, **target.last))
            elif op == 'stop':
                client.disconnect()
                emit(dict(op=op, stopped=True))
            elif op == 'reconnect':
                results = []
                for fresh in (False, True):
                    probe = CoreArmClient(core['url'], token=client._token,
                                          policy_revision=core['policy_revision']) if fresh else client
                    try:
                        if probe.is_connected:
                            probe.disconnect()
                        probe.connect()
                        results.append(dict(fresh=fresh, refused=False))
                    except CoreArmError as error:
                        results.append(dict(fresh=fresh, refused=True, code=error.code, status=error.status))
                emit(dict(op=op, results=results))
                break
        except CoreArmError as error:
            emit(dict(op=op, refused=True, code=error.code, status=error.status, **target.last))
        except Exception as error:  # Report and let the parent decide; never retry a motion.
            emit(dict(op=op, error_type=type(error).__name__, error=str(error)[:300]))


if __name__ == '__main__':
    main()
