"""A recording session raises the follower caps only for its run and always restores the cell."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

DIRECTORY = Path(__file__).parents[1] / "deploy/robot/omx"


def module():
    sys.path.insert(0, str(DIRECTORY))
    try:
        spec = importlib.util.spec_from_file_location("record_session", DIRECTORY / "record_session.py")
        result = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(result)
        return result
    finally:
        sys.path.remove(str(DIRECTORY))


m = module()
FOLLOWER = "/dev/serial/by-id/usb-follower"
LEADER = "/dev/serial/by-id/usb-leader"


class Arm:
    """Registers of several motors on one bus; `motor` selects the one read or written."""

    def __init__(self, motors):
        self.motors, self.motor, self.writes, self.closed = motors, None, [], 0

    def read(self, name):
        return self.motors[self.motor][name]

    def write(self, name, value):
        self.writes.append((self.motor, name, value))
        self.motors[self.motor][name] = value

    def cleanup_read(self, name):
        return self.read(name)

    def cleanup_write(self, name, value):
        self.write(name, value)

    def alert(self):
        return self.motors[self.motor]["torque"], self.motors[self.motor].get("alert", False)

    def reboot(self):
        self.writes.append((self.motor, "reboot", None))
        motor = self.motors[self.motor]
        motor["alert"] = motor.get("sticky", False)
        motor["torque"] = 0

    def close(self):
        self.closed += 1


def follower(changes=None):
    motors = {}
    for motor, (model, mode) in m.FOLLOWER.items():
        motors[motor] = {"model": model, "mode": mode, "torque": 0, "hw_error": 0, "pwm_limit": 20,
                         "p_gain": 400}
        if model == 1200:
            motors[motor]["current_limit"] = 50
    for motor, values in (changes or {}).items():
        motors[motor].update(values)
    return Arm(motors)


CAPS_FILE = {motor: ({"pwm": 300, "current": 250} if model == 1200 else {"pwm": 300})
             for motor, (model, _) in m.FOLLOWER.items()}
CAPS = {motor: {{"pwm": "pwm_limit", "current": "current_limit"}[k]: v for k, v in cap.items()}
        for motor, cap in CAPS_FILE.items()}


def config(tmp_path):
    path = tmp_path / "record-config.json"
    path.write_text(json.dumps({
        "robot": {"type": "omx_follower", "id": "f", "port": FOLLOWER, "use_degrees": False,
                  "max_relative_target": 5,
                  "cameras": {"top": {"type": "opencv", "index_or_path": "/dev/v4l/by-id/top", "width": 640,
                                      "height": 480, "fps": 30}}},
        "teleop": {"type": "omx_leader", "id": "l", "port": LEADER},
        "dataset": {"repo_id": "local/x", "root": str(tmp_path / "new"), "single_task": "t", "fps": 30,
                    "num_episodes": 1, "episode_time_s": 1, "reset_time_s": 1, "push_to_hub": False,
                    "private": True},
        "resume": False}))
    return path


def session(arm, leader, *, active=("rosy-omx-camera@top.service",), activating=(), run=lambda command: 0):
    calls = []

    def systemctl(verb, unit):
        calls.append((verb, unit))
        if verb != "is-active":
            return ""
        return "active" if unit in active else "activating" if unit in activating else ""

    def recorder(command):
        # while recording, LeRobot has turned the follower on
        for motor in m.FOLLOWER:
            arm.motors[motor]["torque"] = 1
        leader.motors[6]["torque"] = 1
        return run(command)

    clock = [0.0]

    def sleep(seconds):
        clock[0] += seconds

    s = m.Session(open_bus=lambda which: arm if which == "follower" else leader, systemctl=systemctl,
                  run=recorder, log=lambda **row: None, sleep=sleep, clock=lambda: clock[0])
    return s, calls


def leader_arm(**state):
    return Arm({motor: {"torque": 0, "hw_error": 0, **state} for motor in m.LEADER})


@pytest.mark.parametrize("moving, marked", [((), True), ((1,), False)])
def test_episodes_with_an_untouched_leader_are_flagged_after_recording(tmp_path, moving, marked):
    # 2026-10-24: two five-episode datasets had leader action range 0.0 in every episode.
    pd = pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    rows = []
    for episode in range(3):
        for step in range(30):
            delta = step * 0.5 if episode in moving else 0.0  # 14.5 at the end: a hand on the leader
            rows.append({"episode_index": episode, "action": [10.0 + delta, 20.0, 30.0, 40.0, 50.0, 0.4]})
    (tmp_path / "data/chunk-000").mkdir(parents=True)
    pd.DataFrame(rows).to_parquet(tmp_path / "data/chunk-000/file-000.parquet")
    result = m.static_episodes(tmp_path)
    assert result["episodes"] == 3
    assert result["static"] == [e for e in range(3) if e not in moving]
    assert (tmp_path / "DO_NOT_TRAIN.txt").exists() is marked
    assert json.loads((tmp_path / "static_episodes.json").read_text())["static"] == result["static"]


def test_a_latched_leader_voltage_alert_is_cleared_before_lerobot_connects(tmp_path):
    # 2026-10-24: LeRobot reported all six leader motors missing while each answered with alert 0x80.
    arm, leader = follower(), leader_arm(alert=True)

    def run(command):
        assert not any(motor.get("alert") for motor in leader.motors.values())
        return 0

    s, calls = session(arm, leader, run=run)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert record["leader_rebooted"] == list(m.LEADER) and record["safe_end"] is True
    assert_restored(arm, leader)


def test_an_alert_latched_during_the_session_is_cleared_for_the_next_one(tmp_path):
    arm, leader = follower(), leader_arm()

    def run(command):
        leader.motors[4]["alert"] = True  # the supply sagged while the leader moved
        return 0

    s, _ = session(arm, leader, run=run)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert record["leader_rebooted"] == [] and record["leader_rebooted_after"] == [4]
    assert record["safe_end"] is True and not leader.motors[4]["alert"]
    assert_restored(arm, leader)


@pytest.mark.parametrize("state, message", [
    ({"alert": True, "torque": 1}, "torque ON"),
    ({"alert": True, "sticky": True}, "persists"),
])
def test_a_leader_alert_that_reboot_cannot_safely_clear_refuses_before_any_cap(tmp_path, state, message):
    arm, leader = follower(), leader_arm()
    leader.motors[3].update(state)
    s, _ = session(arm, leader)
    with pytest.raises(SystemExit, match=message):
        s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert arm.writes == []


def assert_restored(arm, leader):
    for motor, (model, _) in m.FOLLOWER.items():
        assert arm.motors[motor]["torque"] == 0 and arm.motors[motor]["pwm_limit"] == 20
        if model == 1200:
            assert arm.motors[motor]["current_limit"] == 50
    assert leader.motors[6]["torque"] == 0


def test_a_session_raises_the_caps_only_while_recording_and_restores_everything(tmp_path):
    arm, leader = follower(), leader_arm()
    s, calls = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert record["exit_code"] == 0 and record["caps_restored"] is True and record["safe_end"] is True
    assert (11, "pwm_limit", 300) in arm.writes and (16, "current_limit", 250) in arm.writes
    assert_restored(arm, leader)
    assert ("stop", "rosy-omx-camera@top.service") in calls and ("start", "rosy-omx-camera@top.service") in calls
    assert ("stop", "rosy-omx-camera@front.service") not in calls  # was not running: left alone


def test_chunk_mode_runs_the_chunk_runner_and_keeps_the_cameras_for_the_judge(tmp_path):
    seen = []
    arm, leader = follower(), leader_arm()
    s, calls = session(arm, leader, active=m.SERVICES, run=lambda command: seen.append(command) or 0)
    s.chunks = {"library": str(tmp_path / "lib.json"), "io": str(tmp_path / "io"), "sha256": "x"}
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert Path(seen[0][1]).name == "chunk_runner.py" and f"--io={tmp_path / 'io'}" in seen[0]
    assert not [u for v, u in calls if v == "stop"] and record["source_mode"] == "scripted_teacher"
    assert record["safe_end"] is True
    assert_restored(arm, leader)


def test_services_stop_dependents_first_and_start_in_reverse(tmp_path):
    # Stopping camera-view first cascades into readiness's ExecStopPost restore and timed out (2026-10-24).
    arm, leader = follower(), leader_arm()
    s, calls = session(arm, leader, active=m.SERVICES)
    s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert [u for v, u in calls if v == "stop"] == list(reversed(m.SERVICES))
    assert [u for v, u in calls if v == "start"] == list(m.SERVICES)
    assert_restored(arm, leader)


def test_a_readiness_unit_waiting_to_restart_is_stopped_before_recording(tmp_path):
    # Restart=on-failure leaves it "activating" for RestartSec; firing mid-session would restart the cameras.
    arm, leader = follower(), leader_arm()
    s, calls = session(arm, leader, active=(), activating=("rosy-omx-camera-readiness.service",))
    record = s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert record["stopped_services"] == ["rosy-omx-camera-readiness.service"]
    assert calls.index(("stop", "rosy-omx-camera-readiness.service")) < calls.index(("start", "rosy-omx-camera-readiness.service"))
    assert_restored(arm, leader)


@pytest.mark.parametrize("outcome", ["fails", "raises"])
def test_a_failed_or_interrupted_recording_still_restores_the_cell(tmp_path, outcome):
    arm, leader = follower(), leader_arm()

    def run(command):
        if outcome == "raises":
            raise KeyboardInterrupt
        return 1

    s, calls = session(arm, leader, run=run)
    record = s.execute(config(tmp_path), CAPS, teleop_only=False)
    if outcome == "raises":  # an interrupt is a normal end: the record comes back for session.json
        assert record["interrupted"] is True and record["safe_end"] is True
    else:
        assert record["exit_code"] == 1
    assert_restored(arm, leader)
    assert ("start", "rosy-omx-camera@top.service") in calls


@pytest.mark.parametrize("change", [{12: {"torque": 1}}, {14: {"hw_error": 4}}, {16: {"mode": 4}}])
def test_nothing_changes_unless_every_follower_motor_is_idle(tmp_path, change):
    arm, leader = follower(change), leader_arm()
    s, calls = session(arm, leader)
    with pytest.raises(SystemExit):
        s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert arm.writes == [] and calls == []


def test_teleop_only_runs_teleoperate_on_the_robot_and_teleop_part(tmp_path):
    path = config(tmp_path)
    command = m.Session.command(path, teleop_only=True)
    assert command[:3] == [sys.executable, str(DIRECTORY / "guarded_native.py"), "teleoperate"]
    teleop = json.loads(Path(command[3].split("=", 1)[1]).read_text())
    assert set(teleop) == {"robot", "teleop", "fps", "display_data"} and teleop["fps"] == 30
    assert m.Session.command(path, teleop_only=False) == [sys.executable, str(DIRECTORY / "guarded_native.py"),
                                                        "record", f"--config_path={path}"]


@pytest.mark.parametrize("caps", [
    {k: v for k, v in CAPS_FILE.items() if k != 13},                 # a motor missing
    {**CAPS_FILE, 12: {"pwm": 300, "current": 100}},                 # XL430 has no Current Limit
    {**CAPS_FILE, 15: {"pwm": 900}},                                 # above the PWM range
    {**CAPS_FILE, 11: {"pwm": 500}},                                 # above the first-session ceiling
    {**CAPS_FILE, 16: {"current": 250}},                             # no pwm
])
def test_caps_files_must_cover_every_motor_within_range(tmp_path, caps):
    good = tmp_path / "good.json"
    good.write_text(json.dumps({str(k): v for k, v in CAPS_FILE.items()}))
    assert m.load_caps(good) == CAPS
    path = tmp_path / "caps.json"
    path.write_text(json.dumps({str(k): v for k, v in caps.items()}))
    with pytest.raises(SystemExit):
        m.load_caps(path)


CARD = """schema: rosy.omx-task-card.v1
task_id: strawberry-out-and-back
revision: 2
single_task: Take the strawberry out and put it back.
record:
  repo_id: local/omx-strawberry-out-and-back
  root_prefix: /tmp/rosy-data/omx-leader
  episode_time_s: 40
  reset_time_s: 10
  num_episodes: 5
success: {end_state: strawberry in the bowl}
"""


def test_a_task_card_plugs_its_task_into_the_device_config(tmp_path):
    card = tmp_path / "card.yaml"
    card.write_text(CARD, encoding="utf-8")
    base = json.loads(config(tmp_path).read_text())
    effective = m.compose(base, m.load_task_card(card), stamp="20261019-070000")
    dataset = effective["dataset"]
    assert dataset["single_task"] == "Take the strawberry out and put it back."
    assert (dataset["episode_time_s"], dataset["reset_time_s"], dataset["num_episodes"]) == (40, 10, 5)
    assert dataset["root"] == "/tmp/rosy-data/omx-leader/strawberry-out-and-back-r2-20261019-070000"
    assert effective["robot"] == base["robot"] and effective["teleop"] == base["teleop"]  # devices untouched
    assert base["dataset"]["single_task"] == "t"  # the base config is not mutated


@pytest.mark.parametrize("change", [
    ("schema: rosy.omx-task-card.v1", "schema: other"),
    ("task_id: strawberry-out-and-back", "task_id: ../escape"),
    ("revision: 2", "revision: two"),
    ("  root_prefix: /tmp/rosy-data/omx-leader", "  root_prefix: relative/dir"),
    ("  episode_time_s: 40", "  episode_time_s: 0"),
])
def test_a_malformed_task_card_is_refused(tmp_path, change):
    card = tmp_path / "card.yaml"
    card.write_text(CARD.replace(*change), encoding="utf-8")
    with pytest.raises(SystemExit):
        m.load_task_card(card)


def test_the_task_card_is_embedded_verbatim_with_its_hash(tmp_path):
    import hashlib
    card = tmp_path / "card.yaml"
    card.write_text(CARD, encoding="utf-8")
    arm, leader = follower(), leader_arm()
    s, _ = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True, task_card=card)
    assert record["task_card"]["sha256"] == hashlib.sha256(card.read_bytes()).hexdigest()
    assert "strawberry-out-and-back" in record["task_card"]["text"]


def test_the_repository_example_task_card_stays_valid():
    card = m.load_task_card(DIRECTORY / "task-card.example.yaml")
    assert card["schema"] == m.CARD_SCHEMA and card["record"]["episode_time_s"] > 0


def test_a_session_refuses_caps_that_are_not_the_baseline(tmp_path):
    arm, leader = follower({13: {"pwm_limit": 300}}), leader_arm()
    s, calls = session(arm, leader)
    with pytest.raises(SystemExit, match="baseline"):
        s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert arm.writes == [] and calls == []


def test_torque_that_never_reads_off_is_retried_then_reported_unsafe(tmp_path):
    arm, leader = follower(), leader_arm()
    original = arm.write

    def write(motor_name, value):  # motor 12 ignores torque OFF (e.g. the bus is gone)
        if arm.motor == 12 and motor_name == "torque" and value == 0:
            return
        original(motor_name, value)

    arm.write = write
    s, _ = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert record["safe_end"] is False and record["torque_after"][12] == 1
    assert all(arm.motors[m]["torque"] == 0 for m in (11, 13, 14, 15, 16))


def test_one_motor_failing_its_restore_does_not_leave_the_others_raised(tmp_path):
    arm, leader = follower(), leader_arm()
    original = arm.write

    def write(name, value):
        if arm.motor == 12 and name == "pwm_limit" and value == 20:
            raise RuntimeError("write failed")
        original(name, value)

    arm.write = write
    s, _ = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=False)
    assert record["safe_end"] is False and any("follower 12" in f for f in record["caps_restored"])
    assert all(arm.motors[m]["pwm_limit"] == 20 for m in (11, 13, 14, 15, 16))


def test_max_relative_target_has_a_ceiling(tmp_path):
    import json as _json
    config_value = _json.loads(config(tmp_path).read_text())
    config_value["robot"]["max_relative_target"] = 25
    with pytest.raises(ValueError, match="at most 20"):
        m.validate_config(config_value)


def bi_config(tmp_path):
    path = config(tmp_path)
    value = json.loads(path.read_text())
    robot, teleop = value['robot'], value['teleop']
    value['robot'] = {'type': 'bi_omx_follower', 'id': 'both_f', 'cameras': robot['cameras']}
    value['teleop'] = {'type': 'bi_omx_leader', 'id': 'both_l'}
    for name in ('arm_a', 'arm_b'):
        value['robot'][name] = {**robot, 'id': name + '_f', 'port': FOLLOWER + '_' + name, 'cameras': {}}
        value['teleop'][name] = {**teleop, 'id': name + '_l', 'port': LEADER + '_' + name}
    path.write_text(json.dumps(value))
    return path


@pytest.mark.parametrize('failure', [False, True])
def test_bimanual_session_cleans_both_pairs_and_hands_cameras_over_once(tmp_path, failure):
    devices = {name + '.' + role: (follower() if role == 'follower' else leader_arm())
               for name in ('arm_a', 'arm_b') for role in ('follower', 'leader')}
    calls, commands = [], []
    def recorder(command):
        commands.append(command)
        for key, device in devices.items():
            for state in device.motors.values():
                state['torque'] = 1
        if failure:
            raise KeyboardInterrupt
        return 0
    def systemctl(verb, unit):
        calls.append((verb, unit))
        return 'active' if verb == 'is-active' and unit == m.SERVICES[0] else ''
    s = m.Session(open_bus=devices.__getitem__, systemctl=systemctl, run=recorder, log=lambda **row: None)
    record = s.execute(bi_config(tmp_path), CAPS, teleop_only=False)
    assert record['safe_end'] is True
    for name in ('arm_a', 'arm_b'):
        assert_restored(devices[name + '.follower'], devices[name + '.leader'])
    assert calls.count(('stop', m.SERVICES[0])) == calls.count(('start', m.SERVICES[0])) == 1
    assert len(commands) == 1 and Path(commands[0][1]).name == 'bimanual_native.py'


def test_second_pair_preflight_failure_writes_nothing(tmp_path):
    devices = {'arm_a.follower': follower(), 'arm_b.follower': follower({12: {'torque': 1}})}
    s = m.Session(open_bus=devices.__getitem__, systemctl=lambda *args: None,
                  run=lambda command: pytest.fail('must not start'), log=lambda **row: None)
    with pytest.raises(SystemExit):
        s.execute(bi_config(tmp_path), CAPS, teleop_only=False)
    assert all(not d.writes for d in devices.values())


def test_pair_cleanup_turns_other_arm_off_before_retrying_missing_usb(tmp_path, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'serial', SimpleNamespace())
    monkeypatch.setitem(sys.modules, 'dynamixel_sdk', SimpleNamespace(PacketHandler=None, PortHandler=None))
    devices = {'arm_a.leader': leader_arm(), 'arm_b.leader': leader_arm(), 'arm_b.follower': follower()}
    clock, off_times = [0.0], []
    for state in devices['arm_b.follower'].motors.values():
        state['torque'] = 1
    write = devices['arm_b.follower'].write
    def tracked_write(name, value):
        if name == 'torque' and value == 0:
            off_times.append(clock[0])
        write(name, value)
    devices['arm_b.follower'].write = tracked_write
    def open_bus(name):
        if name == 'arm_a.follower':
            return m.SerialBus('/dev/serial/by-id/rosy-unit-test-device-disconnected-7c1a', 0)
        return devices[name]
    s = m.Session(open_bus=open_bus, systemctl=lambda *args: '', run=lambda command: 0,
                  log=lambda **row: None, clock=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0] + dt))
    value = json.loads(bi_config(tmp_path).read_text())
    record = {}
    s.finish_pairs(record, [], s.pair_sessions(value))
    assert off_times and off_times[0] < 1.0
    assert not record['safe_end'] and all(v['torque'] == 0 for v in devices['arm_b.follower'].motors.values())


@pytest.mark.parametrize('teleop_only', [False, True])
def test_bimanual_native_child_config_avoids_recursive_choice_registry(tmp_path, teleop_only):
    path = bi_config(tmp_path)
    public = path.read_text()
    command = m.Session.command(path, teleop_only=teleop_only)
    derived = Path(command[3].split('=', 1)[1])
    assert derived != path and path.read_text() == public
    native = json.loads(derived.read_text())
    for section in ('robot', 'teleop'):
        assert native[section]['type'].startswith('bi_omx_')
        for name in ('arm_a', 'arm_b'):
            assert 'type' not in native[section][name]
            assert native[section][name]['port'] == json.loads(public)[section][name]['port']


def test_body_only_is_explicit_manual_flag_and_recording_is_rejected_before_open(tmp_path):
    path = bi_config(tmp_path)
    command = m.Session.command(path, teleop_only=True, body_only=True)
    assert '--body-only' in command
    assert '--body-only' not in m.Session.command(path, teleop_only=True)
    with pytest.raises(ValueError, match='manual'):
        m.Session.command(path, teleop_only=False, body_only=True)
    s = m.Session(open_bus=lambda which: pytest.fail('must reject before serial open'),
                  systemctl=lambda *args: '', run=lambda command: 0, log=lambda **row: None)
    with pytest.raises(ValueError, match='manual'):
        s.execute(path, CAPS, teleop_only=False, body_only=True)


def gain_session(tmp_path, *, run=lambda command: 0):
    devices = {name + '.' + role: (follower({12: {'p_gain': 640 if name == 'arm_a' else 4000},
                                          14: {'p_gain': 430 if name == 'arm_a' else 550}})
                                 if role == 'follower' else leader_arm())
               for name in ('arm_a', 'arm_b') for role in ('follower', 'leader')}
    session = m.Session(open_bus=devices.__getitem__, systemctl=lambda *args: '', run=run, log=lambda **row: None)
    return session, devices, bi_config(tmp_path)


@pytest.mark.parametrize('teleop_only,body_only', [(False, False), (True, False), (True, True)])
def test_sessions_preserve_all_pid_gains(tmp_path, teleop_only, body_only):
    session, devices, path = gain_session(tmp_path)
    originals = {arm: {motor: dict(state) for motor, state in devices[arm + '.follower'].motors.items()}
                 for arm in ('arm_a', 'arm_b')}
    def run(command):
        for arm in originals:
            assert {motor: state['p_gain'] for motor, state in devices[arm + '.follower'].motors.items()} == {
                motor: state['p_gain'] for motor, state in originals[arm].items()}
        return 0
    session.run_command = run
    record = session.execute(path, CAPS, teleop_only=teleop_only, body_only=body_only)
    assert record['safe_end']
    assert all(name not in ('p_gain', 'i_gain', 'd_gain') for arm in originals
               for _, name, _ in devices[arm + '.follower'].writes)


class PacketArm(m.SerialBus):
    """Actual SerialBus packet checks, with only the wire replaced by register memory."""
    def __init__(self, arm, *, comm=0, instruction_error=0):
        from types import SimpleNamespace
        self.motors, self.writes, self.motor = arm.motors, arm.writes, 0
        self.port = None
        self.comm, self.instruction_error = comm, instruction_error
        self.packet = SimpleNamespace()
        for size in (1, 2, 4):
            setattr(self.packet, f'read{size}ByteTxRx', self.packet_read)
            setattr(self.packet, f'write{size}ByteTxRx', self.packet_write)

    def error(self):
        return (128 if self.motors[self.motor]['hw_error'] else 0) | self.instruction_error

    def packet_read(self, port, motor, address):
        from joint_tune import READS
        name = next(name for name, spec in READS.items() if spec[0] == address)
        return self.motors[motor][name], self.comm, self.error()

    def packet_write(self, port, motor, address, value):
        from joint_tune import WRITES
        name = next(name for name, spec in WRITES.items() if spec[0] == address)
        self.writes.append((motor, name, value))
        if not self.comm and not self.instruction_error:
            self.motors[motor][name] = value
        return self.comm, self.error()

    def close(self):
        pass


def test_alert_payload_stops_and_restores_caps_but_keeps_fault_and_unsafe_receipt(tmp_path):
    arm = PacketArm(follower())
    leader = leader_arm()
    def run(command):
        arm.motors[12].update(hw_error=32, torque=0)
        return 1
    s, _ = session(arm, leader, run=run)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert_restored(arm, leader)
    assert record['torque_off_confirmed'] is True
    assert record['caps_restored'] is True
    assert record['hardware_faults'][12] == {'hw_error': 32, 'packet_alert': True}
    assert not record['safe_end'] and record['manual_attention_required']
    assert arm.motors[12]['hw_error'] == 32
    assert all(name in ('torque', 'pwm_limit', 'current_limit') and (name != 'torque' or value == 0)
               for _, name, value in arm.writes)


@pytest.mark.parametrize('bad', ['comm', 'instruction_error'])
def test_invalid_fault_packets_remain_rejected_and_other_motors_restore(tmp_path, bad):
    arm = PacketArm(follower())
    leader = leader_arm()
    original_read, original_write = arm.packet_read, arm.packet_write
    def read(*args):
        value, comm, error = original_read(*args)
        return value, (9 if bad == 'comm' and arm.motor == 12 else comm), error | (1 if bad == 'instruction_error' and arm.motor == 12 else 0)
    def write(*args):
        comm, error = original_write(*args)
        return (9 if bad == 'comm' and arm.motor == 12 else comm), error | (1 if bad == 'instruction_error' and arm.motor == 12 else 0)
    def run(command):
        arm.motors[12]['hw_error'] = 32
        for size in (1, 2, 4):
            setattr(arm.packet, f'read{size}ByteTxRx', read)
            setattr(arm.packet, f'write{size}ByteTxRx', write)
        return 1
    s, _ = session(arm, leader, run=run)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert not record['safe_end'] and not record['torque_off_confirmed']
    assert record['caps_restored'] is not True
    assert all(arm.motors[motor]['pwm_limit'] == 20 for motor in (11, 13, 14, 15, 16))


@pytest.mark.parametrize('operation', ['read', 'write'])
def test_normal_serial_operations_still_reject_alert(operation):
    arm = PacketArm(follower({12: {'hw_error': 32}}))
    arm.motor = 12
    with pytest.raises(RuntimeError, match='error 128'):
        arm.read('torque') if operation == 'read' else arm.write('torque', 0)


@pytest.mark.parametrize('change', [{'model': 1200}, {'mode': 5}, {'torque': 1}])
def test_cleanup_baseline_write_requires_confirmed_follower_and_off(change):
    arm = PacketArm(follower({12: {'hw_error': 32, **change}}))
    arm.motor = 12
    with pytest.raises(RuntimeError, match='confirmed follower'):
        arm.cleanup_write('pwm_limit', 20)
    assert not arm.writes


def test_cleanup_never_writes_current_limit_on_xl430():
    arm = PacketArm(follower({12: {'hw_error': 32}}))
    arm.motor = 12
    with pytest.raises(RuntimeError, match='confirmed follower'):
        arm.cleanup_write('current_limit', 50)
    assert not arm.writes


@pytest.mark.parametrize('failure', ['alert', 'transport', 'instruction'])
def test_faulted_first_board_never_skips_second_board_cleanup(tmp_path, failure):
    devices = {name + '.' + role: (PacketArm(follower()) if role == 'follower' else leader_arm())
               for name in ('arm_a', 'arm_b') for role in ('follower', 'leader')}
    clock = [0.0]
    def run(command):
        for device in devices.values():
            for state in device.motors.values():
                state['torque'] = 1
        arm = devices['arm_a.follower']
        arm.motors[12].update(torque=0, hw_error=32)
        if failure == 'transport':
            arm.comm = 9
        elif failure == 'instruction':
            arm.instruction_error = 1
        return 1
    s = m.Session(open_bus=devices.__getitem__, systemctl=lambda *args: '', run=run, log=lambda **row: None,
                  clock=lambda: clock[0], sleep=lambda dt: clock.__setitem__(0, clock[0] + dt))
    record = s.execute(bi_config(tmp_path), CAPS, teleop_only=True, body_only=True)
    assert not record['safe_end'] and not record['pairs']['arm_a']['safe_end']
    assert record['pairs']['arm_b']['safe_end']
    assert_restored(devices['arm_b.follower'], devices['arm_b.leader'])
    if failure == 'alert':
        assert_restored(devices['arm_a.follower'], devices['arm_a.leader'])
        assert record['pairs']['arm_a']['hardware_faults'][12]['hw_error'] == 32


def test_failed_pwm_restore_still_attempts_current_cap_on_same_motor(tmp_path):
    arm, leader = follower(), leader_arm()
    original = arm.write
    def write(name, value):
        if arm.motor == 14 and name == 'pwm_limit' and value == 20:
            raise OSError('PWM restore failed')
        original(name, value)
    arm.write = write
    s, _ = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True)
    assert not record['safe_end']
    assert arm.motors[14]['current_limit'] == 50
    assert arm.motors[15]['pwm_limit'] == 20


@pytest.mark.parametrize('created', [False, True])
def test_main_binds_unique_child_monitor_path_to_receipt(tmp_path, monkeypatch, created):
    from types import SimpleNamespace
    monkeypatch.chdir(tmp_path)
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'deploy/robot/omx'))
    monkeypatch.setenv('ROSY_OMX_MONITOR_LOG', '/stale/previous-session.jsonl')
    path = config(tmp_path)
    caps = tmp_path / 'caps.json'
    caps.write_text(json.dumps(CAPS_FILE))
    captured = {}
    class Child:
        def __init__(self, command, **kwargs):
            captured.update(kwargs)
            if created:
                Path(kwargs['env']['ROSY_OMX_MONITOR_LOG']).write_text('{"event":"sample"}\n')
                Path(kwargs['env']['ROSY_OMX_MONITOR_STATE']).write_text(json.dumps({
                    'owner_id': kwargs['env']['ROSY_OMX_MONITOR_OWNER'],
                    'session_id': kwargs['env']['ROSY_OMX_MONITOR_SESSION'],
                    'status': 'active', 'observed_at': 100, 'motors': []}))
        def wait(self):
            return 0
    class FakeSession:
        def __init__(self, **kwargs):
            self.run = kwargs['run']
        def execute(self, *args, **kwargs):
            return {'safe_end': True, 'exit_code': self.run(['child'])}
    monkeypatch.setattr(m.subprocess, 'Popen', Child)
    monkeypatch.setattr(m, 'Session', FakeSession)
    monkeypatch.setattr(m, 'protect_signals', lambda: None)
    def release_lock():
        if created:
            assert json.loads(Path(captured['env']['ROSY_OMX_MONITOR_STATE']).read_text())['status'] == 'ended'
    monkeypatch.setattr(m, 'session_lock', lambda: SimpleNamespace(close=release_lock))
    with pytest.raises(SystemExit) as ended:
        m.main(['--config', str(path), '--caps', str(caps), '--teleop-only'])
    assert ended.value.code == 0
    receipt = json.loads((tmp_path / 'session.json').read_text())
    log_path = Path(receipt['motor_health_log'])
    assert log_path.is_absolute() and log_path.parent == tmp_path
    assert str(log_path) == captured['env']['ROSY_OMX_MONITOR_LOG']
    assert receipt['motor_health_log_created'] is created
    assert receipt['motor_health_owner'] == captured['env']['ROSY_OMX_MONITOR_OWNER']
    assert receipt['motor_health_session'] == captured['env']['ROSY_OMX_MONITOR_SESSION']
    assert receipt['motor_health_state'] == captured['env']['ROSY_OMX_MONITOR_STATE']
