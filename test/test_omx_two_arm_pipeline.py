"""The two-arm pipeline drives the Leader under caps and mirrors it on the Followers.

The fakes here stand in for the two Dynamixel buses: they move toward their goal, they can
stall a joint to reproduce a loaded arm, and they record every register write so the tests
can see what the pipeline touched.
"""
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

OMX = Path(__file__).parents[1] / "deploy/robot/omx"


def load(name):
    sys.path.insert(0, str(OMX))
    try:
        spec = importlib.util.spec_from_file_location(f"omx_test_{name}", OMX / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(OMX))


pipeline = load("two_arm_pipeline")
actuator_module = load("leader_actuator")
NAMES = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll", "gripper")
BODY = NAMES[:5]


class Bus:
    """One bus whose motors move toward their goal; a stalled joint holds its PWM at the cap."""

    def __init__(self, *, leader=False, position=2028, pwm_limit=20, current_limit=50, stall=(), speed=20,
                 droop=None):
        self.motors = {n: SimpleNamespace(id=i + (1 if leader else 11)) for i, n in enumerate(NAMES)}
        self.calibration = {n: SimpleNamespace(range_min=0, range_max=4095, drive_mode=0, homing_offset=0)
                            for n in NAMES}
        self.present = dict.fromkeys(NAMES, position)
        self.goals = dict(self.present)
        self.droop = dict.fromkeys(NAMES, 0)
        self.droop.update(droop or {})
        self.torque = dict.fromkeys(NAMES, 0)
        self.pwm = dict.fromkeys(NAMES, 0)
        self.pwm_limits = dict.fromkeys(NAMES, pwm_limit)
        self.current_limit = current_limit
        self.profiles = {(n, register): 1 for n in NAMES
                         for register in ("Profile_Velocity", "Profile_Acceleration")}
        self.gains = {n: {"p": 640, "i": 0} for n in NAMES}
        self.temperature = dict.fromkeys(NAMES, 41)
        self.stall = set(stall)
        self.speed = speed
        self.events = []
        self.connected = False
        self.hardware_error = set()

    # --- bus surface used by the guard and the actuator
    @property
    def pwm_limit(self):
        """The body-wide value, for the tests that do not set a per-joint cap."""
        values = {self.pwm_limits[name] for name in BODY}
        assert len(values) == 1, f"per-joint caps: {self.pwm_limits}"
        return values.pop()

    @pwm_limit.setter
    def pwm_limit(self, value):
        self.pwm_limits = dict.fromkeys(NAMES, value)

    def connect(self):
        self.connected = True

    @property
    def is_connected(self):
        return self.connected

    def disconnect(self, *args):
        self.connected = False

    def _names(self, motors):
        """Accept names or ids, as the driver does; the fake keeps one key per joint."""
        values = NAMES if motors is None else motors
        if isinstance(values, (str, int)):
            values = [values]
        by_id = {motor.id: name for name, motor in self.motors.items()}
        return [by_id.get(value, value) for value in values]

    def enable_torque(self, motors=None, **kwargs):
        for name in self._names(motors):
            self.torque[name] = 1
            self.events.append(("torque_on", name))

    def disable_torque(self, motors=None, **kwargs):
        for name in self._names(motors):
            self.torque[name] = 0
            self.events.append(("torque_off", name))

    def read(self, register, motor, **kwargs):
        if register == "Torque_Enable":
            return self.torque[motor]
        if register == "Hardware_Error_Status":
            return 32 if motor in self.hardware_error else 0
        if register == "PWM_Limit":
            return self.pwm_limits[motor]
        if register == "Current_Limit":
            return self.current_limit
        if register == "Present_PWM":
            return self.pwm[motor]
        if register == "Present_Position":
            return self.present[motor]
        if register == "Position_P_Gain":
            return self.gains[motor]["p"]
        if register == "Position_I_Gain":
            return self.gains[motor]["i"]
        if register == "Present_Temperature":
            return self.temperature[motor]
        if register == "Operating_Mode":
            return 5 if motor == "gripper" else 4
        if register in ("Profile_Velocity", "Profile_Acceleration"):
            return self.profiles[motor, register]
        raise AssertionError(register)

    def write(self, register, motor, value, **kwargs):
        self.events.append((register, motor, value))
        if register in ("Profile_Velocity", "Profile_Acceleration"):
            self.profiles[motor, register] = value
        elif register == "PWM_Limit":
            self.pwm_limits[motor] = value
        elif register == "Current_Limit":
            self.current_limit = value
        elif register == "Position_P_Gain":
            self.gains[motor]["p"] = value
        elif register == "Position_I_Gain":
            self.gains[motor]["i"] = value

    def sync_read(self, register, motors=None, *, normalize=True, num_retry=0):
        assert register in ("Present_Position", "Goal_Position")
        source = self.present if register == "Present_Position" else self.goals
        values = {n: source[n] for n in (motors or NAMES)}
        return self.norm(values) if normalize else values

    def sync_write(self, register, values, *, normalize=True):
        assert register == "Goal_Position" and not normalize
        self.events.append(("goal", dict(values)))
        self.goals.update(values)

    def norm(self, values):
        return {n: v / 4095 * (100 if n == "gripper" else 200) - (0 if n == "gripper" else 100)
                for n, v in values.items()}

    def _normalize(self, values):
        by_name = {n: values[m.id] for n, m in self.motors.items() if m.id in values}
        return {self.motors[n].id: v for n, v in self.norm(by_name).items()}

    def _unnormalize(self, values):
        return {m.id: int((values[m.id] + (0 if n == "gripper" else 100)) /
                          (100 if n == "gripper" else 200) * 4095)
                for n, m in self.motors.items() if m.id in values}

    # --- the fake motor
    def advance(self):
        for name in NAMES:
            if not self.torque[name]:
                self.pwm[name] = 0
                continue
            goal, position = self.goals[name], self.present[name]
            if name in self.stall:
                self.pwm[name] = self.pwm_limits[name]
                continue
            self.pwm[name] = 0
            # A drooped joint settles short of its goal: a position-only loop's holding torque.
            settled = goal - self.droop[name]
            self.present[name] = position + max(-self.speed, min(self.speed, settled - position))


class Rig:
    """Two arms, one clock and the sleep the pipeline uses."""

    def __init__(self, arms=("arm_a",), follower_position=2028, leader_position=2028, stall=(),
                 leader_droop=None):
        self.followers = {arm: Bus(position=follower_position, stall=stall) for arm in arms}
        self.leaders = {arm: Bus(leader=True, position=leader_position, pwm_limit=330,
                                 droop=leader_droop) for arm in arms}
        self.now = [1000.0]
        self.rows = []

    def log(self, **row):
        self.rows.append(row)

    def sleep(self, seconds):
        self.now[0] += seconds
        for bus in list(self.followers.values()) + list(self.leaders.values()):
            bus.advance()

    def arms(self):
        return [pipeline.Arm(arm, SimpleNamespace(bus=self.followers[arm], cameras={}),
                             SimpleNamespace(bus=self.leaders[arm], cameras={}))
                for arm in self.followers]

    def clock(self):
        return self.now[0]


def config(**overrides):
    body = {"schema": pipeline.SCHEMA,
            "arms": {"arm_a": {"follower": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_A-if00",
                               "leader": "/dev/serial/by-id/usb-ROBOTIS_OpenRB-150_B-if00"}},
            "poses": "poses.json",
            "limits": {"tolerance_deg": 2.5},
            "leader_drive": {"pwm": 150, "current": 100},
            "follower_caps": {"pwm": 150, "current": 100}}
    body.update(overrides)
    return body


def poses(arm="arm_a", **named):
    table = {"arm_a": {"park": {name: 2028 for name in BODY}}}
    table["arm_a"].update(named)
    return {"schema": pipeline.POSE_SCHEMA, "poses": table}


# --------------------------------------------------------------------- configuration


def test_a_config_must_name_the_two_by_id_buses_of_every_arm():
    pipeline.validate_config(config())
    with pytest.raises(ValueError, match="by-id"):
        pipeline.validate_config(config(arms={"arm_a": {"follower": "/dev/ttyACM0", "leader": "/dev/ttyACM1"}}))
    with pytest.raises(ValueError, match="schema"):
        pipeline.validate_config(config(schema="something/1"))
    with pytest.raises(ValueError, match="tolerance"):
        pipeline.validate_config(config(limits={"tolerance_deg": 0}))
    with pytest.raises(ValueError, match="caps"):
        pipeline.validate_config(config(leader_drive={"pwm": 900, "current": 100}))


def test_a_per_joint_cap_must_name_a_body_joint_and_stay_inside_the_guard_bound():
    pipeline.validate_config(config(follower_caps={"pwm": 120, "current": 100,
                                                   "per_joint": {"shoulder_lift": {"pwm": 300}}}))
    with pytest.raises(ValueError, match="no body joint"):
        pipeline.validate_config(config(follower_caps={"per_joint": {"gripper": {"pwm": 300}}}))
    with pytest.raises(ValueError, match="1..400"):
        pipeline.validate_config(config(follower_caps={"per_joint": {"shoulder_lift": {"pwm": 500}}}))
    with pytest.raises(ValueError, match="pwm and current"):
        pipeline.validate_config(config(follower_caps={"per_joint": {"shoulder_lift": {"torque": 1}}}))
    with pytest.raises(ValueError, match="integer"):
        pipeline.validate_config(config(follower_caps={"per_joint": {"shoulder_lift": {"pwm": "300"}}}))


def test_a_follower_gain_must_name_a_body_joint_and_stay_inside_the_servo_range():
    pipeline.validate_config(config(follower_gains={"per_joint": {"shoulder_lift": {"p": 1200},
                                                                 "wrist_flex": {"p": 600, "i": 40}}}))
    with pytest.raises(ValueError, match="no body joint"):
        pipeline.validate_config(config(follower_gains={"per_joint": {"gripper": {"p": 1200}}}))
    with pytest.raises(ValueError, match="p and i"):
        pipeline.validate_config(config(follower_gains={"per_joint": {"shoulder_lift": {"d": 1200}}}))
    with pytest.raises(ValueError, match="0..2000"):
        pipeline.validate_config(config(follower_gains={"per_joint": {"shoulder_lift": {"p": 2001}}}))
    with pytest.raises(ValueError, match="integer"):
        pipeline.validate_config(config(follower_gains={"per_joint": {"shoulder_lift": {"p": True}}}))
    with pytest.raises(ValueError, match="must set p and/or i"):
        pipeline.validate_config(config(follower_gains={"per_joint": {"shoulder_lift": {}}}))


def test_a_leader_gain_must_name_a_body_joint_and_stay_inside_the_servo_range():
    pipeline.validate_config(config(leader_gains={"per_joint": {"shoulder_lift": {"p": 1200}}}))
    with pytest.raises(ValueError, match="no body joint"):
        pipeline.validate_config(config(leader_gains={"per_joint": {"gripper": {"p": 1200}}}))
    with pytest.raises(ValueError, match="0..2000"):
        pipeline.validate_config(config(leader_gains={"per_joint": {"shoulder_lift": {"i": -1}}}))
    with pytest.raises(ValueError, match="p and i"):
        pipeline.validate_config(config(leader_gains={"per_joint": {"shoulder_lift": {"pwm": 1}}}))


def test_a_leader_gravity_bias_must_be_ticks_on_a_body_joint():
    pipeline.validate_config(config(leader_gravity_ticks={"per_joint": {"shoulder_lift": 34}}))
    with pytest.raises(ValueError, match="no body joint"):
        pipeline.validate_config(config(leader_gravity_ticks={"per_joint": {"gripper": 34}}))
    with pytest.raises(ValueError, match="integer of ticks"):
        pipeline.validate_config(config(leader_gravity_ticks={"per_joint": {"shoulder_lift": 34.5}}))
    with pytest.raises(ValueError, match="integer of ticks"):
        pipeline.validate_config(config(leader_gravity_ticks={"per_joint": {"shoulder_lift": True}}))
    with pytest.raises(ValueError, match="0..120 ticks"):
        pipeline.validate_config(config(leader_gravity_ticks={"per_joint": {"shoulder_lift": 121}}))


def test_a_pose_must_name_every_body_joint_of_a_known_arm():
    pipeline.validate_poses(poses(), {"arm_a": None})
    with pytest.raises(ValueError, match="exactly"):
        pipeline.validate_poses({"schema": pipeline.POSE_SCHEMA,
                                 "poses": {"arm_a": {"park": {"shoulder_pan": 10}}}}, {"arm_a": None})
    with pytest.raises(ValueError, match="unknown arm"):
        pipeline.validate_poses({"schema": pipeline.POSE_SCHEMA,
                                 "poses": {"arm_z": {"park": {name: 1 for name in BODY}}}}, {"arm_a": None})


# --------------------------------------------------------------------- preflight


def test_the_preflight_refuses_an_arm_that_is_not_at_rest():
    rig = Rig()
    arms = rig.arms()
    rig.followers["arm_a"].torque["shoulder_pan"] = 1
    with pytest.raises(ValueError, match="torque is ON"):
        pipeline.stage_preflight(arms, config=config(), log=rig.log)

    rig = Rig()
    rig.followers["arm_a"].hardware_error.add("wrist_flex")
    with pytest.raises(ValueError, match="hardware error 32 latched; power-cycle"):
        pipeline.stage_preflight(rig.arms(), config=config(), log=rig.log)


def test_two_receipts_of_the_same_stage_in_one_second_do_not_overwrite(tmp_path):
    first = pipeline.write_receipt(tmp_path, "drive", {"stage": "drive", "result": [1]})
    second = pipeline.write_receipt(tmp_path, "drive", {"stage": "drive", "result": [2]})
    assert first != second
    assert json.loads(first.read_text(encoding="utf-8"))["result"] == [1]
    assert json.loads(second.read_text(encoding="utf-8"))["result"] == [2]


def test_the_health_stage_reports_a_latched_error_and_writes_nothing():
    # The run after a bad drive needs the facts, not a refusal: preflight cannot be used while
    # a motor holds a latched error, and it must not hide what the other joints report.
    rig = Rig()
    rig.leaders["arm_a"].hardware_error.add("shoulder_lift")
    rig.leaders["arm_a"].temperature["shoulder_lift"] = 53
    result = pipeline.stage_health(rig.arms(), log=rig.log)
    leader = [bus for bus in result["buses"] if bus["role"] == "leader"][0]
    assert leader["motors"]["shoulder_lift"]["hardware_error"] == 32
    assert leader["motors"]["shoulder_lift"]["temperature"] == 53
    assert leader["motors"]["shoulder_pan"]["hardware_error"] == 0
    assert all(not bus.events for bus in list(rig.followers.values()) + list(rig.leaders.values()))


def test_a_failed_stage_still_leaves_a_receipt_that_names_the_failure(tmp_path, monkeypatch):
    rig = Rig()
    monkeypatch.setattr(pipeline, "load_json", lambda path: config())
    monkeypatch.setattr(pipeline, "open_arm", lambda arm_id, follower, leader: rig.arms()[0])
    monkeypatch.setattr(pipeline, "close_arm", lambda arm: None)
    monkeypatch.setattr(pipeline, "session_lock", lambda: SimpleNamespace(close=lambda: None))
    argv = ["--config", str(tmp_path / "config.json"), "--stage", "drive", "--pose", "park",
            "--attest", "hands-off:tester:2026-10-23T09:00:00+09:00",
            "--receipts", str(tmp_path / "receipts")]

    def blocked(*args, **kwargs):
        raise ValueError("arm_a_leader shoulder_lift: blocked at the cap; PWM=400 limit=400")

    monkeypatch.setattr(pipeline, "stage_drive", blocked)
    with pytest.raises(ValueError, match="blocked at the cap"):
        pipeline.main(argv)
    [receipt] = list((tmp_path / "receipts").glob("drive-*.json"))
    body = json.loads(receipt.read_text(encoding="utf-8"))
    assert body["error"] == ("ValueError: arm_a_leader shoulder_lift: blocked at the cap; "
                             "PWM=400 limit=400")
    assert body["result"] == []

    monkeypatch.setattr(pipeline, "stage_drive", lambda *args, **kwargs: {"stage": "drive", "arms": []})
    pipeline.main(argv)
    bodies = [json.loads(path.read_text(encoding="utf-8"))
              for path in (tmp_path / "receipts").glob("drive-*.json")]
    [successful] = [body for body in bodies if body["error"] is None]
    assert successful["result"] == [{"stage": "drive", "arms": []}]


def test_the_preflight_refuses_a_follower_whose_caps_are_not_at_rest():
    rig = Rig()
    rig.followers["arm_a"].pwm_limit = 300
    with pytest.raises(ValueError, match="resting baseline"):
        pipeline.stage_preflight(rig.arms(), config=config(), log=rig.log)


def test_the_preflight_reports_the_ids_and_the_resting_caps():
    rig = Rig()
    result = pipeline.stage_preflight(rig.arms(), config=config(), log=rig.log)
    row = result["arms"][0]
    assert row["follower_ids"]["shoulder_pan"] == 11 and row["leader_ids"]["shoulder_pan"] == 1
    assert row["follower_pwm_limits"]["shoulder_lift"] == 20
    assert row["leader_pwm_limits"]["shoulder_lift"] == 330


# --------------------------------------------------------------------- gap and park


def test_the_gap_stage_reads_both_poses_without_commanding_anything():
    rig = Rig(follower_position=2028, leader_position=2028 + 40)
    result = pipeline.stage_gap(rig.arms(), log=rig.log)
    assert result["arms"][0]["gap_degrees"]["shoulder_pan"] == pytest.approx(3.516, abs=0.01)
    assert not any(event[0] == "goal" for event in rig.followers["arm_a"].events)


def test_the_park_stage_writes_the_followers_present_pose(tmp_path):
    rig = Rig(follower_position=2100)
    path = tmp_path / "poses.json"
    result = pipeline.stage_park(rig.arms(), poses_path=path, log=rig.log)
    written = json.loads(path.read_text())
    assert written["schema"] == pipeline.POSE_SCHEMA
    assert written["poses"]["arm_a"]["park"]["shoulder_pan"] == 2100
    assert result["arms"][0]["park"]["shoulder_pan"] == 2100


# --------------------------------------------------------------------- align


def test_the_align_stage_moves_the_follower_onto_the_leaders_pose():
    rig = Rig(follower_position=2028, leader_position=2028 + 40)
    result = pipeline.stage_align(rig.arms(), config=config(), log=rig.log, clock=rig.clock,
                                  sleep=rig.sleep, timeout_s=30)
    assert result["arms"][0]["aligned"] is True
    # The guard accepts an alignment inside 0.5 degree, so the follower settles there.
    assert abs(rig.followers["arm_a"].present["shoulder_pan"] - (2028 + 40)) <= 3
    assert rig.followers["arm_a"].torque["gripper"] == 0
    # The stage ends torque OFF and puts the resting caps back.
    assert not any(rig.followers["arm_a"].torque.values())
    assert rig.followers["arm_a"].pwm_limit == 20


def test_the_diagnosis_names_the_joint_that_hit_the_cap_not_the_largest_gap():
    # The field run: shoulder_lift stalled at the cap while wrist_flex still held a
    # larger gap, and the report pointed the operator at the wrong joint.
    rig = Rig(follower_position=2028, leader_position=2028, stall=("shoulder_lift",))
    leader = rig.leaders["arm_a"]
    leader.present["shoulder_lift"] = leader.goals["shoulder_lift"] = 2028 + 40
    leader.present["wrist_flex"] = leader.goals["wrist_flex"] = 2028 + 120
    with pytest.raises(RuntimeError, match="blocked_by_load"):
        pipeline.stage_align(rig.arms(), config=config(), log=rig.log, clock=rig.clock,
                             sleep=rig.sleep, timeout_s=30)
    row = [entry for entry in rig.rows if entry.get("stage") == "align"][-1]
    assert row["joint"] == "shoulder_lift"
    assert row["stop_joint"] == "shoulder_lift"
    assert row["pwm"] is not None and row["pwm_limit"] == 150
    assert row["action"].startswith("support the arm")


def test_the_align_stage_names_the_joint_that_is_blocked_by_a_load():
    rig = Rig(follower_position=2028, leader_position=2028 + 40, stall=("shoulder_pan",))
    with pytest.raises(RuntimeError, match="blocked_by_load"):
        pipeline.stage_align(rig.arms(), config=config(), log=rig.log, clock=rig.clock,
                             sleep=rig.sleep, timeout_s=30)
    row = [entry for entry in rig.rows if entry.get("joint") == "shoulder_pan"]
    assert row and row[0]["action"].startswith("support the arm")


def per_joint_config():
    return config(follower_caps={"pwm": 150, "current": 100,
                                 "per_joint": {"shoulder_lift": {"pwm": 300}}})


def test_the_align_stage_gives_one_joint_its_own_cap_and_restores_every_joint():
    rig = Rig(follower_position=2028, leader_position=2028 + 40)
    pipeline.stage_align(rig.arms(), config=per_joint_config(), log=rig.log, clock=rig.clock,
                         sleep=rig.sleep, timeout_s=30)
    writes = [event for event in rig.followers["arm_a"].events if event[0] == "PWM_Limit"]
    assert ("PWM_Limit", "shoulder_lift", 300) in writes
    assert ("PWM_Limit", "shoulder_pan", 150) in writes
    # The stage hands each joint back the value it found, so the arm rests at the baseline.
    assert rig.followers["arm_a"].pwm_limits["shoulder_lift"] == 20
    assert rig.followers["arm_a"].pwm_limits["shoulder_pan"] == 20
    assert rig.followers["arm_a"].pwm_limit == 20


def gain_config():
    return config(follower_gains={"per_joint": {"shoulder_lift": {"p": 1200}}})


def test_the_align_stage_sets_the_gains_with_torque_off_and_restores_them():
    # The field run: a P-only shoulder stopped 3 degrees short at 57% of its cap, so the
    # run has to be able to state a gain that closes the steady-state error, and give the
    # servo back the gain it found when the run ends.
    rig = Rig(follower_position=2028, leader_position=2028 + 40)
    result = pipeline.stage_align(rig.arms(), config=gain_config(), log=rig.log, clock=rig.clock,
                                  sleep=rig.sleep, timeout_s=30)
    assert result["arms"][0]["p_gains"]["shoulder_lift"] == 1200
    assert result["arms"][0]["p_gains"]["wrist_flex"] == 640
    assert rig.followers["arm_a"].gains["shoulder_lift"] == {"p": 640, "i": 0}
    events = rig.followers["arm_a"].events
    applied = events.index(("Position_P_Gain", "shoulder_lift", 1200))
    torque_on = next(index for index, event in enumerate(events) if event[0] == "torque_on")
    assert applied < torque_on


def test_the_load_stop_uses_the_joints_own_cap_not_the_shared_one():
    rig = Rig(follower_position=2028, leader_position=2028, stall=("shoulder_lift",))
    leader = rig.leaders["arm_a"]
    leader.present["shoulder_lift"] = leader.goals["shoulder_lift"] = 2028 + 40
    with pytest.raises(RuntimeError, match="blocked_by_load"):
        pipeline.stage_align(rig.arms(), config=per_joint_config(), log=rig.log, clock=rig.clock,
                             sleep=rig.sleep, timeout_s=30)
    row = [entry for entry in rig.rows if entry.get("stage") == "align"][-1]
    assert row["joint"] == "shoulder_lift"
    assert row["pwm"] == 300 and row["pwm_limit"] == 300
    assert row["pwm_limits"]["shoulder_pan"] == 150


# --------------------------------------------------------------------- drive


def test_the_drive_stage_refuses_to_move_the_leader_without_the_hands_off_attestation():
    rig = Rig()
    with pytest.raises(ValueError, match="hands-off"):
        pipeline.stage_drive(rig.arms(), poses=poses(), pose_name="park", attestation=None,
                             config=config(), log=rig.log, clock=rig.clock, sleep=rig.sleep)
    assert not any(event[0] == "torque_on" for event in rig.leaders["arm_a"].events)


def test_the_drive_stage_moves_the_leader_and_the_follower_mirrors_it():
    rig = Rig(follower_position=2028, leader_position=2028)
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2028 + 60
    result = pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                                  attestation="hands-off:tester:2026-10-22T23:00:00+09:00",
                                  config=config(), log=rig.log, clock=rig.clock, sleep=rig.sleep,
                                  timeout_s=120)
    assert abs(result["arms"][0]["leader"]["shoulder_pan"] - (2028 + 60)) <= 2
    assert abs(result["arms"][0]["follower"]["shoulder_pan"] - (2028 + 60)) <= 4
    assert rig.leaders["arm_a"].torque["shoulder_pan"] == 0
    assert rig.leaders["arm_a"].pwm_limit == 330
    assert rig.leaders["arm_a"].current_limit == 50
    assert rig.leaders["arm_a"].profiles[("shoulder_pan", "Profile_Velocity")] == 1
    assert rig.leaders["arm_a"].torque["gripper"] == 0
    # The Follower ends torque OFF with its resting caps back.
    assert not any(rig.followers["arm_a"].torque.values())
    assert rig.followers["arm_a"].pwm_limit == 20
    assert rig.followers["arm_a"].current_limit == 50


def test_the_drive_stage_gives_each_joint_its_own_cap_and_restores_every_joint():
    rig = Rig(follower_position=2028, leader_position=2028)
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2028 + 60
    pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                         attestation="hands-off:tester:2026-10-22T23:00:00+09:00",
                         config=per_joint_config(), log=rig.log, clock=rig.clock, sleep=rig.sleep,
                         timeout_s=120)
    writes = [event for event in rig.followers["arm_a"].events if event[0] == "PWM_Limit"]
    assert ("PWM_Limit", "shoulder_lift", 300) in writes
    assert ("PWM_Limit", "elbow_flex", 150) in writes
    assert rig.followers["arm_a"].pwm_limits["shoulder_lift"] == 20
    assert rig.followers["arm_a"].pwm_limit == 20


def test_the_drive_stage_sets_the_leader_gains_and_restores_them():
    # The field drive timed out with the Leader's shoulder 4.75 degrees short at 56% of its
    # PWM cap: the Leader's factory P is 400, so it needs the same lever as the Follower.
    rig = Rig(follower_position=2028, leader_position=2028)
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2028 + 60
    result = pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                                  attestation="hands-off:tester:2026-10-22T23:00:00+09:00",
                                  config=config(leader_gains={"per_joint": {"shoulder_lift": {"p": 1200}}}),
                                  log=rig.log, clock=rig.clock, sleep=rig.sleep, timeout_s=120)
    assert result["arms"][0]["leader_p_gains"]["shoulder_lift"] == 1200
    assert result["arms"][0]["leader_p_gains"]["shoulder_pan"] == 640
    assert rig.leaders["arm_a"].gains["shoulder_lift"] == {"p": 640, "i": 0}


def test_the_drive_stage_sets_the_follower_gains_and_restores_them():
    rig = Rig(follower_position=2028, leader_position=2028)
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2028 + 60
    result = pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                                  attestation="hands-off:tester:2026-10-22T23:00:00+09:00",
                                  config=gain_config(), log=rig.log, clock=rig.clock,
                                  sleep=rig.sleep, timeout_s=120)
    assert result["arms"][0]["p_gains"]["shoulder_lift"] == 1200
    assert rig.followers["arm_a"].gains["shoulder_lift"] == {"p": 640, "i": 0}


def test_the_follower_copies_the_leaders_delta_and_not_its_absolute_pose():
    rig = Rig(follower_position=2100, leader_position=2028)
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2088
    pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                         attestation="hands-off:tester:2026-10-22T23:00:00+09:00",
                         config=config(), log=rig.log, clock=rig.clock, sleep=rig.sleep, timeout_s=120)
    assert abs(rig.leaders["arm_a"].present["shoulder_pan"] - 2088) <= 2
    # The Follower copies the Leader's delta (+60), not the Leader's absolute pose (2088).
    assert abs(rig.followers["arm_a"].present["shoulder_pan"] - (2100 + 60)) <= 4


def test_the_drive_stage_lifts_a_drooping_leader_joint_with_a_gravity_bias():
    # The field Leader holds its shoulder 34 ticks (3.0 degrees) short of every goal it is
    # given: a position-only loop spends that error on holding torque. The bias buys it back.
    rig = Rig(leader_droop={"shoulder_pan": 34})
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2088
    result = pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                                  attestation="hands-off:tester:2026-10-23T09:00:00+09:00",
                                  config=config(leader_gravity_ticks={"per_joint": {"shoulder_pan": 34}}),
                                  log=rig.log, clock=rig.clock, sleep=rig.sleep, timeout_s=120)
    assert result["arms"][0]["leader_gravity_ticks"]["shoulder_pan"] == 34
    assert abs(rig.leaders["arm_a"].present["shoulder_pan"] - 2088) <= 2


def test_without_the_gravity_bias_the_same_droop_never_arrives():
    rig = Rig(leader_droop={"shoulder_pan": 34})
    target = poses(park={name: 2028 for name in BODY})
    target["poses"]["arm_a"]["park"]["shoulder_pan"] = 2088
    with pytest.raises(RuntimeError, match="did not reach"):
        pipeline.stage_drive(rig.arms(), poses=target, pose_name="park",
                             attestation="hands-off:tester:2026-10-23T09:00:00+09:00",
                             config=config(), log=rig.log, clock=rig.clock, sleep=rig.sleep,
                             timeout_s=120)


# --------------------------------------------------------------------- the actuator


def test_the_actuator_restores_the_caps_and_the_profiles_it_found():
    bus = Bus(leader=True, pwm_limit=330, current_limit=50)
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100)
    assert bus.pwm_limit == 150 and bus.current_limit == 100
    actuator.enable()
    assert all(bus.torque[name] for name in BODY) and not bus.torque["gripper"]
    failures = actuator.restore()
    assert failures == []
    assert bus.pwm_limit == 330 and bus.current_limit == 50
    assert bus.profiles[("shoulder_pan", "Profile_Velocity")] == 1
    assert not any(bus.torque.values())


def test_the_actuator_sets_a_requested_gain_and_restores_the_one_it_found():
    bus = Bus(leader=True, pwm_limit=330)
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100, gains={"shoulder_lift": {"p": 1200}})
    assert bus.gains["shoulder_lift"]["p"] == 1200
    assert bus.gains["shoulder_pan"]["p"] == 640
    assert actuator.restore() == []
    assert bus.gains["shoulder_lift"] == {"p": 640, "i": 0}


def test_the_actuator_writes_the_gravity_bias_but_keeps_the_ramp_unbiased():
    bus = Bus(leader=True, pwm_limit=330)
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100, gravity={"shoulder_lift": 34})
    actuator.enable()
    actuator.seed({name: 2028 for name in BODY})
    command = actuator.step({name: 2030 for name in BODY}, 0.5)
    actuator.write(command)
    assert bus.goals["shoulder_lift"] == int(command["shoulder_lift"]) + 34
    assert bus.goals["shoulder_pan"] == int(command["shoulder_pan"])
    assert actuator.command["shoulder_lift"] == command["shoulder_lift"]


def test_a_gravity_bias_that_leaves_the_calibrated_range_is_refused():
    bus = Bus(leader=True, pwm_limit=330)
    bus.calibration["shoulder_lift"].range_max = 2030
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100, gravity={"shoulder_lift": 40})
    actuator.seed({name: 2028 for name in BODY})
    with pytest.raises(ValueError, match="outside the calibrated range"):
        actuator.write({name: 2028 for name in BODY})


def test_the_actuator_refuses_a_gravity_bias_outside_its_bounds():
    with pytest.raises(ValueError, match="no body joint"):
        actuator_module.LeaderActuator(Bus(leader=True)).admit(
            pwm=150, current=100, gravity={"gripper": 10})
    with pytest.raises(ValueError, match="0..120 ticks"):
        actuator_module.LeaderActuator(Bus(leader=True)).admit(
            pwm=150, current=100, gravity={"shoulder_lift": 121})


def test_the_actuator_names_the_latched_hardware_error_it_refuses():
    bus = Bus(leader=True)
    bus.hardware_error.add("shoulder_lift")
    with pytest.raises(ValueError, match="hardware error 32 latched; power-cycle the arm"):
        actuator_module.LeaderActuator(bus).admit(pwm=150, current=100)


def test_the_actuator_refuses_to_admit_an_arm_that_is_already_driven():
    bus = Bus(leader=True)
    bus.torque["shoulder_lift"] = 1
    with pytest.raises(ValueError, match="torque is ON"):
        actuator_module.LeaderActuator(bus).admit(pwm=150, current=100)


def test_the_actuator_ramp_never_exceeds_its_rate_and_acceleration():
    bus = Bus(leader=True)
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100)
    actuator.seed({name: 2028 for name in BODY})
    command = actuator.step({name: 2028 + 4096 for name in BODY}, 1 / 30)
    moved = command["shoulder_pan"] - 2028
    assert 0 < moved <= actuator_module.RATE_DEG_S * actuator_module.TICKS_PER_DEGREE / 30 + 1e-6


def test_the_actuator_stops_a_joint_that_holds_its_load_at_the_cap():
    bus = Bus(leader=True, pwm_limit=330)
    bus.stall.add("shoulder_pan")
    actuator = actuator_module.LeaderActuator(bus)
    actuator.admit(pwm=150, current=100)
    actuator.enable()
    actuator.seed({name: 2028 for name in BODY})
    now = [1000.0]
    actuator.clock = lambda: now[0]
    with pytest.raises(ValueError, match="blocked at the cap"):
        for _ in range(60):
            actuator.step({name: 2400 for name in BODY}, 0.1)
            bus.advance()
            now[0] += 0.1
            actuator.check_effort({name: 2028 for name in BODY})
