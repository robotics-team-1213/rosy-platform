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

    def close(self):
        self.closed += 1


def follower(changes=None):
    motors = {}
    for motor, (model, mode) in m.FOLLOWER.items():
        motors[motor] = {"model": model, "mode": mode, "torque": 0, "hw_error": 0, "pwm_limit": 20}
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


def leader_arm():
    return Arm({6: {"torque": 0}})


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
    assert Path(command[0]).name == "lerobot-teleoperate"
    teleop = json.loads(Path(command[1].split("=", 1)[1]).read_text())
    assert set(teleop) == {"robot", "teleop", "fps", "display_data"} and teleop["fps"] == 30
    assert Path(m.Session.command(path, teleop_only=False)[0]).name == "lerobot-record"


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
