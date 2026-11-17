"""D-1024 4.1/4.2: pin refusal, max_chunk=1, execute failure handling, shadow never sends and grades risk outputs."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'integrations/robots/omx/src'), str(ROOT / 'contracts/learning/src'),
                str(ROOT / 'learning/registry/policy'), str(ROOT / 'learning/registry/policy/test')]
from rosy.integrations.robots.omx import policy_run as run  # noqa: E402
from rosy.integrations.robots.omx import policy_runner as runner  # noqa: E402
from rosy.integrations.robots.omx.core_arm_client import CoreArmClient  # noqa: E402

NAMES = ['joint1', 'joint2']
LIMITS = {n: {'min': -1.0, 'max': 1.0, 'step': 0.1} for n in NAMES}
SPACE = runner.ActionSpace('ros_joint_rad', 'ros_joint_rad')


class Adapter:
    joint_names, unit, policy_type, n_action_steps = NAMES, 'ros_joint_rad', 'act', 1

    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def preprocess(self, observation, task):
        return observation

    def infer(self, batch):
        return next(self.outputs)

    def postprocess(self, action):
        return runner.check_output(action, NAMES)


class Target:
    joint_names, unit = NAMES, 'ros_joint_rad'

    def __init__(self):
        self.sent = []

    def observe(self):
        return {'positions': [0.0, 0.0], 'images': {}}

    def submit(self, positions):
        self.sent.append(positions)


def read(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


def test_pin_mismatch_refuses_and_match_returns_digest(tmp_path):
    (tmp_path / 'model.safetensors').write_bytes(b'weights')
    good = runner.checkpoint_digest(tmp_path)
    assert run.verify_pin(tmp_path, good) == good
    with pytest.raises(run.PinMismatch):
        run.verify_pin(tmp_path, '0' * 64)
    with pytest.raises(ValueError):
        run.verify_pin(tmp_path, 'ABC')


def test_execute_logs_every_step_and_refuses_chunking(tmp_path):
    target, log = Target(), run.RunLog(tmp_path / 'a.jsonl', {'mode': 'execute'})
    run.execute(Adapter([[0.05, 0.0], [0.1, 0.0]]), target, SPACE, 't', LIMITS, log, steps=2, sleep=lambda s: None)
    log.close()
    assert len(target.sent) == 2 and read(tmp_path / 'a.jsonl')[-1]['stopped'] == 'completed'
    chunked = Adapter([])
    chunked.n_action_steps = 4
    with pytest.raises(ValueError):
        run.execute(chunked, Target(), SPACE, 't', LIMITS, run.RunLog(tmp_path / 'b.jsonl', {}), steps=1)


def test_execute_failure_ends_the_run_without_retry(tmp_path):
    target, log = Target(), run.RunLog(tmp_path / 'a.jsonl', {})
    with pytest.raises(ValueError):  # non-finite output: runner.step refuses before submit
        run.execute(Adapter([[0.0, float('nan')], [0.0, 0.0]]), target, SPACE, 't', LIMITS, log, steps=2, sleep=lambda s: None)
    assert target.sent == [] and read(tmp_path / 'a.jsonl')[-1]['stopped'] == 'error'


def test_shadow_grades_risks_compares_teacher_and_never_submits(tmp_path):
    outputs = [[0.05, 0.0], [0.5, 0.0], [0.0, 2.0], [float('nan'), 0.0]]
    teacher = iter([[0.0, 0.0], [0.0, 0.0], None, [0.0, 0.0]])
    target, log = Target(), run.RunLog(tmp_path / 's.jsonl', {})
    risky = run.shadow(Adapter(outputs), target, SPACE, 't', LIMITS, log, steps=4,
                       teacher=lambda: next(teacher), sleep=lambda s: None)
    log.close()
    rows = read(tmp_path / 's.jsonl')
    steps = [r for r in rows if r['kind'] == 'step']
    assert risky == 3 and target.sent == [] and rows[-1]['sent_commands'] == 0
    assert steps[0]['risks'] == [] and steps[0]['teacher_max_abs_diff'] == pytest.approx(0.05)
    assert steps[1]['risks'] == ['delta_over_step:joint1']
    assert set(steps[2]['risks']) == {'out_of_range:joint2', 'delta_over_step:joint2'} and steps[2]['teacher'] is None
    assert steps[3]['risks'] == ['non_finite_or_shape']


@pytest.mark.parametrize('limits', [{}, {'joint1': LIMITS['joint1']}, {**LIMITS, 'joint2': {'min': 1, 'max': 0, 'step': 1}},
                                    {**LIMITS, 'joint2': {'min': 0, 'max': 1, 'step': 0}},
                                    {**LIMITS, 'joint2': {'min': 0, 'max': float('nan'), 'step': 1}}])
def test_shadow_refuses_bad_limits_before_observing(tmp_path, limits):
    target = Target()
    with pytest.raises(ValueError):
        run.shadow(Adapter([]), target, SPACE, 't', limits, run.RunLog(tmp_path / 'x.jsonl', {}), steps=1)


def test_observe_only_client_cannot_act_stop_or_be_used_for_execute():
    arm = CoreArmClient('http://127.0.0.1:8080', token='t', policy_revision='a' * 64, observe_only=True)
    calls = []
    arm._request = lambda method, path, body=None: calls.append(path) or dict(
        policy_revision='a' * 64, simulation=True, units='rad', joint_names=['joint1'], cameras=[{'name': 'c', 'shape': [3, 1, 1]}])
    arm.connect()
    arm._observation_id = 'o'
    with pytest.raises(PermissionError):
        arm.send_action({'joint1': 0.0})
    arm._stop_best_effort()
    arm.disconnect()
    assert calls == ['policy']  # no stop, no actions
    with pytest.raises(PermissionError):
        run.ShadowCoreTarget(CoreArmClient('http://127.0.0.1:8080', token='t', policy_revision='a' * 64))


def test_teacher_jsonl_yields_in_order_then_none(tmp_path):
    path = tmp_path / 't.jsonl'
    path.write_text('{"positions": [0.1, 0.2]}\n')
    nxt = run.jsonl_teacher(path)
    assert nxt() == [0.1, 0.2] and nxt() is None


@pytest.mark.parametrize('output, risk', [([0.0, 2.0], {'out_of_range:joint2', 'delta_over_step:joint2'}),
                                           ([0.5, 0.0], {'delta_over_step:joint1'}),
                                           ([0.0, 1.5], {'out_of_range:joint2', 'delta_over_step:joint2'})])
def test_execute_refuses_range_and_step_violations_before_submit(tmp_path, output, risk):
    target, log = Target(), run.RunLog(tmp_path / 'r.jsonl', {})
    with pytest.raises(run.RiskRefused):
        run.execute(Adapter([[0.05, 0.0], output]), target, SPACE, 't', LIMITS, log, steps=2, sleep=lambda s: None)
    rows = read(tmp_path / 'r.jsonl')
    assert target.sent == [{'joint1': 0.05, 'joint2': 0.0}]  # only the first, safe target went out
    assert set(rows[-2]['risks']) == risk and rows[-1]['stopped'] == 'error'


@pytest.mark.parametrize('limits', [None, {}, {'joint1': LIMITS['joint1']}])
def test_execute_requires_valid_limits_before_the_first_cycle(tmp_path, limits):
    target = Target()
    with pytest.raises(ValueError):
        run.execute(Adapter([[0.0, 0.0]]), target, SPACE, 't', limits, run.RunLog(tmp_path / 'l.jsonl', {}), steps=1)
    assert target.sent == []


def test_bool_is_not_a_joint_value():
    with pytest.raises(ValueError):
        runner.check_output([True, 0.0], NAMES)
    assert run.risks(NAMES, [True, 0.0], [0.0, 0.0], LIMITS) == ['non_finite_or_shape']
    assert run.risks(NAMES, [0.0, 0.0], [False, 0.0], LIMITS) == ['non_finite_or_shape']


def test_cli_requires_limits_before_any_contact(tmp_path):
    with pytest.raises(SystemExit) as exc:
        run.main(['execute', str(tmp_path), '--core-url', 'http://127.0.0.1:1', '--policy-revision', 'a' * 64,
                  '--checkpoint-sha256', 'b' * 64, '--out', str(tmp_path / 'o.jsonl'), '--steps', '1',
                  '--policy-artifact', str(tmp_path / 'p.json')])
    assert exc.value.code == 2  # argparse: --limits is required


def test_symlinked_checkpoint_is_refused_for_pins(tmp_path):
    real = tmp_path / 'real.bin'
    real.write_bytes(b'weights')
    ckpt = tmp_path / 'ckpt'
    ckpt.mkdir()
    (ckpt / 'config.json').write_bytes(b'{}')
    try:
        (ckpt / 'model.safetensors').symlink_to(real)
    except OSError:
        pytest.skip('symlinks unavailable')
    digest = runner.checkpoint_digest(ckpt)  # the bench may follow links
    with pytest.raises(ValueError, match='symlink'):
        run.verify_pin(ckpt, digest)


def test_digest_is_checked_again_after_the_model_loaded(tmp_path):
    (tmp_path / 'model.safetensors').write_bytes(b'weights')
    pin = runner.checkpoint_digest(tmp_path)
    assert run.load_pinned(tmp_path, pin, lambda: 'adapter') == 'adapter'

    def swapped_during_load():
        (tmp_path / 'model.safetensors').write_bytes(b'evil')
        return 'adapter'
    with pytest.raises(run.PinMismatch):
        run.load_pinned(tmp_path, pin, swapped_during_load)


def test_checkpoint_must_be_the_registered_policy_for_the_core_revision(tmp_path):
    from test_registry import source
    root, doc = source(tmp_path)
    artifact = root / 'policy-artifact.json'
    ckpt = tmp_path / 'ckpt'
    ckpt.mkdir()
    (ckpt / 'weights.bin').write_bytes(b'weights')
    assert run.bind_policy(artifact, ckpt, doc['revision'])['revision'] == doc['revision']
    with pytest.raises(run.PinMismatch, match='revision'):
        run.bind_policy(artifact, ckpt, '0' * 64)  # CORE runs another policy than the registered one
    (ckpt / 'weights.bin').write_bytes(b'other weights')
    with pytest.raises(run.PinMismatch, match='files'):
        run.bind_policy(artifact, ckpt, doc['revision'])  # operator digest of other bytes cannot pair with it
    (ckpt / 'weights.bin').write_bytes(b'weights')
    (ckpt / 'extra.json').write_bytes(b'{}')
    with pytest.raises(run.PinMismatch, match='files'):
        run.bind_policy(artifact, ckpt, doc['revision'])
