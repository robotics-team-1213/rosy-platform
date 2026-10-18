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


def session(arm, leader, *, active=("rosy-omx-camera@top.service",), run=lambda command: 0):
    calls = []

    def systemctl(verb, unit):
        calls.append((verb, unit))
        return "active" if verb == "is-active" and unit in active else ""

    def recorder(command):
        # while recording, LeRobot has turned the follower on
        for motor in m.FOLLOWER:
            arm.motors[motor]["torque"] = 1
        leader.motors[6]["torque"] = 1
        return run(command)

    s = m.Session(open_bus=lambda which: arm if which == "follower" else leader, systemctl=systemctl,
                  run=recorder, log=lambda **row: None, sleep=lambda s: None)
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
    assert record["exit_code"] == 0 and record["caps_restored"] is True
    assert (11, "pwm_limit", 300) in arm.writes and (16, "current_limit", 250) in arm.writes
    assert_restored(arm, leader)
    assert ("stop", "rosy-omx-camera@top.service") in calls and ("start", "rosy-omx-camera@top.service") in calls
    assert ("stop", "rosy-omx-camera@front.service") not in calls  # was not running: left alone


@pytest.mark.parametrize("outcome", ["fails", "raises"])
def test_a_failed_or_interrupted_recording_still_restores_the_cell(tmp_path, outcome):
    arm, leader = follower(), leader_arm()

    def run(command):
        if outcome == "raises":
            raise KeyboardInterrupt
        return 1

    s, calls = session(arm, leader, run=run)
    if outcome == "raises":
        with pytest.raises(KeyboardInterrupt):
            s.execute(config(tmp_path), CAPS, teleop_only=False)
    else:
        assert s.execute(config(tmp_path), CAPS, teleop_only=False)["exit_code"] == 1
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


def test_the_task_card_is_embedded_verbatim_with_its_hash(tmp_path):
    import hashlib
    card = tmp_path / "task-card.yaml"
    card.write_text("task_id: strawberry-out-and-back
revision: 1
", encoding="utf-8")
    arm, leader = follower(), leader_arm()
    s, _ = session(arm, leader)
    record = s.execute(config(tmp_path), CAPS, teleop_only=True, task_card=card)
    assert record["task_card"]["sha256"] == hashlib.sha256(card.read_bytes()).hexdigest()
    assert "strawberry-out-and-back" in record["task_card"]["text"]
