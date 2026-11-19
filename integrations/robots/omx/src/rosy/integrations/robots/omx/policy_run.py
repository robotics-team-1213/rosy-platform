"""D-1024 4.1/4.2: AI PC policy run loop. ``execute`` proposes one target per observation to CORE; ``shadow`` infers on
real observations, sends nothing and logs outputs against teacher actions and risk outputs.

CORE and the OMX owner keep every limit, the lease, the stop fence and HOLD. This module adds no authority: the
CoreArmClient it drives is SIM-only (D-800) and shadow uses an observe-only client that cannot send an action.
Run it as ``python -m rosy.integrations.robots.omx.policy_run``.

Known limit (review 2026-11-14): shadow reads through CORE's observation port, which clears CORE's pending-observation
slot and answers ARM_POLICY_BUSY while a teacher goal is active. A read-only observation mode needs a CORE and owner
session change (capture_inference_inputs needs the leased session); CORE checks are not weakened for it.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import time

from . import policy_runner as runner


class PinMismatch(ValueError):
    """Checkpoint bytes differ from the pinned sha256: the runner refuses to start (D-854 §2)."""


def verify_pin(checkpoint, expected_sha256):
    if not isinstance(expected_sha256, str) or len(expected_sha256) != 64 or any(c not in '0123456789abcdef' for c in expected_sha256):
        raise ValueError('pinned checkpoint sha256 required')
    actual = runner.checkpoint_digest(checkpoint, allow_symlinks=False)
    if actual != expected_sha256:
        raise PinMismatch('checkpoint sha256 differs from the policy pin')
    return actual


def bind_policy(artifact_path, checkpoint, policy_revision):
    """The registered policy artifact must carry CORE's policy_revision and name exactly the checkpoint's files.

    artifact_path: the registry's policy-artifact.json. Without this the operator's digest and CORE's revision could
    describe two different policies.
    """
    from rosy.contracts.learning.artifacts import validate_policy
    policy = validate_policy(json.loads(Path(artifact_path).read_text(encoding='utf-8')))
    if policy['revision'] != policy_revision:
        raise PinMismatch('registered policy revision differs from the CORE policy revision')
    root = Path(checkpoint)
    if root.is_symlink() or any(p.is_symlink() for p in root.rglob('*')):
        raise PinMismatch('a pinned checkpoint must not contain symlinks')
    actual = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in root.rglob('*') if p.is_file() and '.cache' not in p.relative_to(root).parts}
    if actual != {f['path']: f['sha256'] for f in policy['files']}:
        raise PinMismatch('checkpoint files differ from the registered policy files')
    return policy


def load_pinned(checkpoint, expected_sha256, load):
    """Pin, load, pin again: bytes swapped while the model was being read are refused (TOCTOU)."""
    verify_pin(checkpoint, expected_sha256)
    loaded = load()
    verify_pin(checkpoint, expected_sha256)
    return loaded


def check_limits(limits, joint_names):
    """limits: {joint: {min, max, step}} for exactly the installed joints; step is the per-observation delta cap."""
    if not isinstance(limits, dict) or set(limits) != set(joint_names):
        raise ValueError('limits for exactly the installed joints required')
    for name, lim in limits.items():
        if not isinstance(lim, dict) or set(lim) != {'min', 'max', 'step'} or any(
                type(v) not in (int, float) or not math.isfinite(v) for v in lim.values()):
            raise ValueError(f'finite min, max and step required for {name}')
        if not lim['min'] < lim['max'] or lim['step'] <= 0:
            raise ValueError(f'invalid limits for {name}')
    return limits


def risks(joint_names, values, positions, limits):
    """Risk outputs of a proposed target (D-793 3): non-finite, out of range, change over the step limit."""
    numbers = lambda seq: all(type(v) in (int, float) and math.isfinite(v) for v in seq)  # bool is not a joint value
    if (values is None or len(values) != len(joint_names) or len(positions) != len(joint_names)
            or not numbers(values) or not numbers(positions)):
        return ['non_finite_or_shape']
    found = []
    for name, value, position in zip(joint_names, values, positions):
        lim = limits[name]
        if not lim['min'] <= value <= lim['max']:
            found.append(f'out_of_range:{name}')
        if abs(value - position) > lim['step']:
            found.append(f'delta_over_step:{name}')
    return found


class RiskRefused(ValueError):
    """A proposed target broke a range or step limit; it is never submitted."""

    def __init__(self, found):
        super().__init__('target refused: ' + ','.join(found))
        self.risks = found


class ShadowCoreTarget(runner.CoreArmTarget):
    """Observation only. The client must be observe-only; submit is refused here as well."""

    def __init__(self, client, **kwargs):
        if getattr(client, 'observe_only', False) is not True:
            raise PermissionError('shadow needs an observe-only CORE client')
        super().__init__(client, **kwargs)

    def submit(self, positions):
        raise PermissionError('shadow mode never sends a command')


class RunLog:
    """Append-only JSONL: a header naming exactly what ran, one line per step, a summary line."""

    def __init__(self, path, header):
        self._stream = Path(path).open('x', encoding='utf-8')
        self.write(dict(kind='header', started_unix_ns=time.time_ns(), **header))

    def write(self, record):
        self._stream.write(json.dumps(record, allow_nan=False, sort_keys=True) + '\n')
        self._stream.flush()
        os.fsync(self._stream.fileno())

    def close(self):
        self._stream.close()


def execute(adapter, target, space, task, limits, log, *, steps, period_s=0.0, clock=time.perf_counter_ns,
            sleep=time.sleep):
    """Observe, infer, submit one target (max_chunk = 1) per cycle. Any failure ends the run; there is no retry.

    limits gate every target before submit, with the same classes as shadow (non-finite, range, step delta).
    """
    if adapter.n_action_steps != 1:
        raise ValueError('max_chunk=1 requires n_action_steps=1')
    check_limits(limits, adapter.joint_names)

    def guard(values, positions):
        found = risks(adapter.joint_names, values, positions, limits)
        if found:
            raise RiskRefused(found)
    for index in range(steps):
        try:
            times = runner.step(adapter, target, space, task, clock, guard)
        except Exception as exc:
            log.write(dict(kind='step', index=index, error=type(exc).__name__, risks=getattr(exc, 'risks', None)))
            log.write(dict(kind='summary', mode='execute', steps=index, stopped='error'))
            raise
        log.write(dict(kind='step', index=index, stage_ns=times))
        sleep(period_s)
    log.write(dict(kind='summary', mode='execute', steps=steps, stopped='completed'))


def shadow(adapter, target, space, task, limits, log, *, steps, teacher=None, period_s=0.0, sleep=time.sleep):
    """teacher: optional callable returning the teacher's target (list in the target unit) for this step, or None.

    Returns the count of steps with a risk output; the caller must not open that tier's L3 when it is not 0.
    """
    runner.check_binding(adapter, target, space)
    check_limits(limits, adapter.joint_names)
    risky = 0
    for index in range(steps):
        observation = target.observe()
        batch = adapter.preprocess(observation, task)
        action = adapter.infer(batch)
        try:
            values = space(adapter.postprocess(action))
        except ValueError:  # check_output refused a non-finite or mis-sized output; that is the finding.
            values = None
        found = risks(adapter.joint_names, values, observation['positions'], limits)
        teacher_values = teacher() if teacher else None
        delta = None
        if values is not None and teacher_values is not None and len(teacher_values) == len(values):
            delta = max(abs(a - b) for a, b in zip(values, teacher_values))
        risky += bool(found)
        log.write(dict(kind='step', index=index, output=values, teacher=teacher_values,
                       teacher_max_abs_diff=delta, risks=found, observed_positions=observation['positions'],
                       observed=observation.get('meta')))
        sleep(period_s)
    log.write(dict(kind='summary', mode='shadow', steps=steps, risky_steps=risky, sent_commands=0))
    return risky


def jsonl_teacher(path):
    """One teacher target per line, {"positions": [...]} in the policy's unit; None once the file is exhausted."""
    lines = iter(Path(path).read_text(encoding='utf-8').splitlines())

    def next_target():
        line = next(lines, None)
        return None if line is None else [float(v) for v in json.loads(line)['positions']]
    return next_target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('execute', 'shadow'))
    parser.add_argument('checkpoint', type=Path)
    parser.add_argument('--core-url', required=True)
    parser.add_argument('--policy-revision', required=True, help='CORE installed policy pin, 64 hex')
    parser.add_argument('--checkpoint-sha256', required=True, help='pinned checkpoint digest from the registry record')
    parser.add_argument('--out', type=Path, required=True, help='new JSONL log path')
    parser.add_argument('--steps', type=int, required=True)
    parser.add_argument('--period-s', type=float, default=0.1)
    parser.add_argument('--device', default='cuda')
    parser.add_argument('--task', default='')
    parser.add_argument('--limits', type=Path, required=True, help='JSON {joint: {min, max, step}}; gates every target')
    parser.add_argument('--policy-artifact', type=Path, required=True,
                        help="registry policy-artifact.json; its revision must equal --policy-revision and its files the checkpoint's")
    parser.add_argument('--teacher-jsonl', type=Path)
    args = parser.parse_args(argv)
    if args.steps < 1 or not math.isfinite(args.period_s) or args.period_s < 0:
        raise SystemExit('positive steps and nonnegative period required')
    token = os.environ.get('ROSY_CORE_TOKEN')
    if not token:
        raise SystemExit('ROSY_CORE_TOKEN is required')
    limits = json.loads(args.limits.read_text(encoding='utf-8'))
    digest = verify_pin(args.checkpoint, args.checkpoint_sha256)  # Before any CORE or model contact.
    bind_policy(args.policy_artifact, args.checkpoint, args.policy_revision)
    from .core_arm_client import CoreArmClient
    client = CoreArmClient(args.core_url, token=token, policy_revision=args.policy_revision,
                           observe_only=args.mode == 'shadow')
    client.connect()  # Refuses when CORE's installed policy pin differs.
    names = [c['name'] for c in client.info['cameras']]
    adapter = load_pinned(args.checkpoint, digest, lambda: runner.LeRobotAdapter(
        args.checkpoint, args.device, joint_names=client.info['joint_names'], cameras=names, unit='ros_joint_rad'))
    space = runner.ActionSpace('ros_joint_rad', 'ros_joint_rad')
    header = dict(mode=args.mode, policy_type=adapter.policy_type, checkpoint_sha256=digest,
                  policy_revision=args.policy_revision, joints=adapter.joint_names, cameras=names,
                  task_sha256=hashlib.sha256(args.task.encode()).hexdigest(), n_action_steps=adapter.n_action_steps)
    log = RunLog(args.out, header)
    try:
        if args.mode == 'execute':
            target = runner.CoreArmTarget(client, policy_type=adapter.policy_type)
            execute(adapter, target, space, args.task, limits, log, steps=args.steps, period_s=args.period_s)
            return 0
        teacher = jsonl_teacher(args.teacher_jsonl) if args.teacher_jsonl else None
        risky = shadow(adapter, ShadowCoreTarget(client, policy_type=adapter.policy_type), space, args.task,
                       limits, log, steps=args.steps, teacher=teacher, period_s=args.period_s)
        return 3 if risky else 0
    finally:
        log.close()
        client.disconnect()


if __name__ == '__main__':
    raise SystemExit(main())
