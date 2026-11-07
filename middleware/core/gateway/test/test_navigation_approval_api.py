"""D-986: navigation re-approval over REST: who may, when a trial may move, what it records."""
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from core_common.protocol.state_components import BatteryStatus
from core_features.command.approval_trials import (ApprovalTrials, MAX_HOLD_S, TRAVEL_CAP_M, TrialRefused,
                                                   require_clearance)

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "deploy/robot/pinky_pro/native"))
OWNER = "person-a"
BODY = SimpleNamespace(body_stop_known=True, lidar_forward_deg=0.0, lidar_self_mask=(), body_lidar_x_m=0.0,
                       body_front_x_m=0.07, body_rear_x_m=-0.07, body_half_width_m=0.06, body_rotation_radius_m=0.1)
REQUIRED = [("forward", "button_release"), ("reverse", "button_release"), ("cw", "button_release"),
            ("ccw", "button_release"), ("forward", "command_loss")]


def scan(now, distance=2.0, **changes):
    count = 360
    return {"frame_id": "lidar", "ranges": [distance] * count, "angle_min": -math.pi,
            "angle_increment": 2 * math.pi / count, "angle_max": -math.pi + 2 * math.pi / count * (count - 1),
            "range_min": 0.05, "range_max": 12.0, "received_at": now, "source_stamp_ns": 1_000_000_000,
            "source_now_ns": 1_000_000_000, **changes}


class Robot:
    """A plant that obeys the last command and stops a set time after the command stream ends."""

    def __init__(self):
        self.now = 100.0
        self.x = self.yaw = 0.0
        self.linear = self.angular = 0.0
        self.commanded = (0.0, 0.0)
        self.last_command = -9.0
        self.watchdog_s = 0.5
        self.scan = scan(self.now)
        self.odom_fresh = True
        self.zeros = 0
        self.limits = SimpleNamespace(manual_linear=0.15, manual_angular=0.6)

    def get_sensor(self, _key):
        return self.scan

    def odom_sample(self):
        return (self.x, 0.0, self.yaw, 0.01) if self.odom_fresh else None

    def snapshot(self):
        return SimpleNamespace(velocity=SimpleNamespace(linear=self.linear, angular=self.angular))

    def teleop(self, linear, angular, source="manual"):
        self.zeros += linear == 0.0 and angular == 0.0
        self.send(linear, angular)
        return True, ""

    def send(self, linear, angular):
        self.commanded = (linear, angular)
        self.last_command = self.now

    def step(self, dt=0.02):
        self.now += dt
        if self.now - self.last_command > self.watchdog_s:
            self.commanded = (0.0, 0.0)
        self.linear, self.angular = self.commanded
        self.x += self.linear * dt
        self.yaw += self.angular * dt
        if self.scan:
            self.scan = {**self.scan, "received_at": self.now}


@pytest.fixture
def robot():
    return Robot()


@pytest.fixture
def trials(robot, tmp_path):
    return ApprovalTrials(robot, robot, robot, lambda: BODY, tmp_path / "trials",
                          clock=lambda: robot.now, wall=lambda: robot.now, thread=False)


def drive(robot, trials, direction, cause, *, hold_s=0.8):
    trials.start(direction, cause, OWNER, blind_zone_confirmed=True)
    held = 0.0
    while held < hold_s:
        trials.hold(OWNER, robot.send)
        for _ in range(5):
            robot.step()
            trials.tick()
        held += 0.1
    if cause == "button_release":
        trials.stop(OWNER)
    while trials.active:
        robot.step()
        trials.tick()


@pytest.mark.parametrize("direction,cause", REQUIRED)
def test_a_trial_writes_evidence_the_approval_tool_accepts(robot, trials, tmp_path, direction, cause):
    import mapping_approval
    drive(robot, trials, direction, cause)
    assert trials.last == {"direction": direction, "stop_cause": cause, "state": "recorded"}
    raw = json.loads((tmp_path / f"trials/{direction}-{cause}.json").read_text(encoding="ascii"))
    assert 0 <= mapping_approval._validate_trial(raw, direction, cause) <= 0.65


def test_five_collected_trials_seal_through_the_real_approval_tool(robot, trials, tmp_path):
    import mapping_approval
    import navigation_approval_host as host
    sums = ROOT / "test"  # the same device tree the approval tool's own tests use
    sys.path.insert(0, str(sums))
    from test_native_mapping_approval import _device
    device = _device(tmp_path)
    trials.directory = device / host.TRIALS
    for direction, cause in REQUIRED:
        drive(robot, trials, direction, cause)
    evidence = device / host.EVIDENCE
    evidence.mkdir(parents=True)
    (evidence / host.PREFLIGHT).write_text(
        json.dumps({"configured_ids": [1, 2], "responded_ids": [1, 2], "torque_free": True}), encoding="ascii")
    bundle = host._bundle(device, "person-a", "floor")
    assert mapping_approval.approve(device, bundle, evidence)["trials"] == 5
    assert mapping_approval.check(device, runtime_mode="hardware")["ready"] is True


def test_the_request_records_what_was_sent_under_a_lower_live_limit(robot, trials, tmp_path):
    robot.limits.manual_linear = 0.015
    drive(robot, trials, "forward", "button_release")
    raw = json.loads((tmp_path / "trials/forward-button_release.json").read_text(encoding="ascii"))
    assert raw["requested_linear_mps"] == 0.015


def test_the_speed_stays_inside_the_envelope_whatever_the_live_limit(robot, trials):
    import mapping_approval
    trials.start("forward", "button_release", OWNER)
    trials.hold(OWNER, robot.send)
    assert 0 < robot.commanded[0] < mapping_approval.MAX_LINEAR_MPS
    trials.abort("end")
    trials.start("ccw", "button_release", OWNER)
    trials.hold(OWNER, robot.send)
    assert 0 < robot.commanded[1] < mapping_approval.MAX_ANGULAR_RPS


def test_a_limit_too_low_to_measure_refuses_the_trial(robot, trials):
    robot.limits.manual_linear = 0.005
    with pytest.raises(TrialRefused) as refused:
        trials.start("forward", "button_release", OWNER)
    assert refused.value.code == "TRIAL_LIMIT_TOO_LOW"


def test_a_button_hold_that_goes_quiet_stops_and_leaves_no_evidence(robot, trials, tmp_path):
    trials.start("forward", "button_release", OWNER)
    trials.hold(OWNER, robot.send)
    zeros = robot.zeros
    while trials.active:
        robot.step()
        trials.tick()
    assert trials.last["state"] == "aborted" and robot.zeros == zeros + 1
    assert not (tmp_path / "trials/forward-button_release.json").exists()
    with pytest.raises(TrialRefused):
        trials.hold(OWNER, robot.send)


def test_a_command_loss_trial_sends_no_stop_of_its_own_while_the_watchdog_answers(robot, trials):
    trials.start("forward", "command_loss", OWNER)
    trials.hold(OWNER, robot.send)
    zeros = robot.zeros
    while not trials.status()["active"]["stopping"]:
        robot.step()
        trials.tick()
    while robot.now - robot.last_command < 1.0:
        robot.step()
        trials.tick()
    assert robot.zeros == zeros and robot.commanded == (0.0, 0.0)


def test_a_command_loss_trial_cannot_be_turned_into_a_release(robot, trials):
    trials.start("forward", "command_loss", OWNER)
    trials.hold(OWNER, robot.send)
    trials.stop(OWNER)
    assert trials.last["state"] == "aborted" and not trials.active


def test_the_hold_time_limit_stops_a_held_button(robot, trials):
    trials.start("cw", "button_release", OWNER)
    deadline = robot.now + MAX_HOLD_S + 1
    while trials.active and robot.now < deadline:
        trials.hold(OWNER, robot.send)
        robot.step(0.05)
        trials.tick()
    assert trials.last == {"direction": "cw", "stop_cause": "button_release", "state": "aborted",
                           "reason": "the hold ran past its time limit"}


def test_the_travel_cap_stops_the_robot(robot, trials):
    trials.start("forward", "button_release", OWNER)
    trials.hold(OWNER, robot.send)
    robot.step()
    trials.tick()
    robot.x = TRAVEL_CAP_M * 2
    robot.step()
    trials.tick()
    assert trials.last["reason"] == "the travel cap was reached"


def test_stale_odometry_stops_the_trial(robot, trials):
    trials.start("forward", "button_release", OWNER)
    trials.hold(OWNER, robot.send)
    robot.odom_fresh = False
    while trials.active:
        trials.hold(OWNER, robot.send)
        robot.step(0.05)
        trials.tick()
    assert trials.last["reason"] == "odometry went stale during the trial"


def test_another_operator_cannot_hold_or_stop_a_trial(robot, trials):
    trials.start("forward", "button_release", OWNER)
    with pytest.raises(TrialRefused, match="another operator"):
        trials.hold("person-b", robot.send)
    with pytest.raises(TrialRefused, match="another operator"):
        trials.stop("person-b")
    assert robot.commanded == (0.0, 0.0)


@pytest.mark.parametrize("change,code", [
    (lambda r: setattr(r, "scan", None), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.update(received_at=r.now - 1.0), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.update(source_now_ns=r.scan["source_stamp_ns"] + 500_000_000), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.update(ranges=[math.inf] * 360), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.update(ranges=[2.0] * 90), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.pop("source_stamp_ns"), "CLEARANCE_UNKNOWN"),
    (lambda r: r.scan.update(ranges=[0.15] * 360), "CLEARANCE_TOO_SMALL"),
])
def test_a_scan_that_shows_no_room_refuses_the_trial(robot, trials, change, code):
    change(robot)
    with pytest.raises(TrialRefused) as refused:
        trials.start("forward", "button_release", OWNER)
    assert refused.value.code == code and not trials.active


def test_a_blank_scan_behind_refuses_reverse_even_when_confirmed(robot, trials):
    for ranges in ([math.inf] * 360, [math.nan] * 360):
        robot.scan.update(ranges=ranges)
        with pytest.raises(TrialRefused) as refused:
            trials.start("reverse", "button_release", OWNER, blind_zone_confirmed=True)
        assert refused.value.code == "CLEARANCE_UNKNOWN"


@pytest.mark.parametrize("direction,beam", [("forward", 180), ("reverse", 0)])
def test_something_closer_than_the_lidar_measures_refuses_that_direction(robot, trials, direction, beam):
    ranges = [2.0] * 360
    ranges[beam] = 0.02
    robot.scan.update(ranges=ranges)
    with pytest.raises(TrialRefused) as refused:
        trials.start(direction, "button_release", OWNER, blind_zone_confirmed=True)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


@pytest.mark.parametrize("direction", ["forward", "cw"])
def test_a_band_inside_range_min_needs_a_person_in_every_direction(robot, direction):
    # The real robot: C1 range_min 0.15 m, body front 0.059 m from the LiDAR (D-422).
    robot.scan.update(range_min=0.15)
    with pytest.raises(TrialRefused) as refused:
        require_clearance(robot.scan, BODY, direction, False, robot.now)
    assert refused.value.code == "BLIND_ZONE_CONFIRMATION_REQUIRED"
    assert require_clearance(robot.scan, BODY, direction, True, robot.now)["blind_m"] > 0


def test_rotation_needs_room_beyond_the_turning_circle(robot, trials):
    robot.scan.update(ranges=[0.11] * 360)
    with pytest.raises(TrialRefused) as refused:
        trials.start("cw", "button_release", OWNER)
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_reverse_always_needs_a_person_for_what_the_lidar_cannot_see(robot, trials):
    with pytest.raises(TrialRefused) as refused:
        trials.start("reverse", "button_release", OWNER)
    assert refused.value.code == "BLIND_ZONE_CONFIRMATION_REQUIRED"
    robot.scan.update(ranges=[0.10] * 360)
    with pytest.raises(TrialRefused) as refused:
        trials.start("reverse", "button_release", OWNER, blind_zone_confirmed=True)
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_an_unknown_body_outline_fails_closed(robot):
    body = SimpleNamespace(**{**vars(BODY), "body_stop_known": False})
    with pytest.raises(TrialRefused) as refused:
        require_clearance(robot.scan, body, "forward", False, robot.now)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


class FakeAgent:
    def __init__(self):
        self.calls = []
        self.phase = "MEASURING"
        self.timeout_s = 0

    def request(self, command, *, role, user_id="", params=None):
        self.calls.append((command, role, params))
        return SimpleNamespace(ok=True, code="", detail="", reachable=True, data={
            "phase": self.phase, "runtime_mode": "motor", "reason": "", "trials": [], "needs_measurement": True,
            "approval": {"valid": False}})


@pytest.fixture
def api(core_client, monkeypatch, robot, tmp_path):
    client, svc = core_client()[:2]
    agent = FakeAgent()
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _svc: agent)
    svc.approval_trials = ApprovalTrials(robot, svc.command, svc.safety, lambda: BODY, tmp_path / "t",
                                         clock=lambda: robot.now, wall=lambda: robot.now, thread=False)
    records, headers = [], {}
    for name, role in (("viewer-a", "viewer"), ("person-a", "operator"), ("admin-a", "administrator")):
        token = f"token-{name}-" + "x" * 32
        records.append(dict(id=name, sha256=hashlib.sha256(token.encode()).hexdigest(), role=role, source="manual"))
        headers[name] = {"Authorization": f"Bearer {token}"}
    svc.config["auth"]["tokens"] = records
    svc.state.set_battery_status(BatteryStatus(filtered_voltage=7.6, charging=False))
    return client, svc, agent, headers


@pytest.mark.parametrize("path", ["/begin", "/cancel", "/navigation-start", "/trial/hold", "/trial/stop"])
def test_a_viewer_cannot_change_anything(api, path):
    client, _, agent, headers = api
    assert client.post(f"/api/v1/navigation/approval{path}", headers=headers["viewer-a"]).status_code == 403
    assert agent.calls == []


def test_anyone_with_read_sees_the_state_through_the_viewer_level(api):
    client, _, agent, headers = api
    response = client.get("/api/v1/navigation/approval", headers=headers["viewer-a"])
    assert response.status_code == 200 and response.json()["trial"] == {"active": None, "last": None}
    assert agent.calls == [("navigation_approval.status", "viewer", None)]


def test_a_login_is_the_approver_and_the_body_cannot_name_one(api):
    client, _, agent, headers = api
    url = "/api/v1/navigation/approval/seal"
    assert client.post(url, json={"test_surface": "floor", "operator": "someone"},
                       headers=headers["person-a"]).status_code == 400
    assert client.post(url, json={"test_surface": "floor"}, headers=headers["person-a"]).status_code == 200
    assert agent.calls == [("navigation_approval.seal", "operator", {"operator": "person-a", "test_surface": "floor"})]


@pytest.mark.parametrize("path,body", [("/begin", None), ("/seal", {"test_surface": "floor"}), ("/cancel", None),
                                       ("/navigation-start", None), ("/trial/hold", None), ("/trial/stop", None),
                                       ("/trial/start", {"direction": "forward", "stop_cause": "button_release"})])
def test_the_public_development_token_names_nobody(core_client, monkeypatch, robot, tmp_path, path, body):
    client, svc = core_client()[:2]
    agent = FakeAgent()
    monkeypatch.setattr("core_api_web.api.v1.host._agent", lambda _svc: agent)
    svc.approval_trials = ApprovalTrials(robot, svc.command, svc.safety, lambda: BODY, tmp_path / "t", thread=False)
    response = client.post(f"/api/v1/navigation/approval{path}", json=body,
                           headers={"Authorization": "Bearer " + "rosy-dev-" + "operator"})
    assert response.status_code == 403 and agent.calls == []


def test_a_trial_needs_the_measuring_phase(api):
    client, _, agent, headers = api
    agent.phase = "IDLE"
    response = client.post("/api/v1/navigation/approval/trial/start",
                           json={"direction": "forward", "stop_cause": "button_release"}, headers=headers["person-a"])
    assert response.status_code == 409 and "APPROVAL_NOT_MEASURING" in response.text


@pytest.mark.parametrize("battery,code", [(BatteryStatus(filtered_voltage=7.6, charging=True), "CHARGING"),
                                          (BatteryStatus(), "CHARGING_UNKNOWN")])
@pytest.mark.parametrize("path,body", [("/begin", None),
                                       ("/trial/start", {"direction": "forward", "stop_cause": "button_release"})])
def test_a_plugged_in_or_unknown_robot_is_not_measured(api, battery, code, path, body):
    client, svc, _, headers = api
    svc.state.set_battery_status(battery)
    response = client.post(f"/api/v1/navigation/approval{path}", json=body, headers=headers["person-a"])
    assert response.status_code == 409 and code in response.text
    assert not svc.approval_trials.active


def test_speed_is_not_the_callers_to_choose(api):
    client, _, _, headers = api
    assert client.post("/api/v1/navigation/approval/trial/start", headers=headers["person-a"],
                       json={"direction": "forward", "stop_cause": "button_release", "linear": 0.5}).status_code == 400


def test_a_hold_goes_through_the_teleop_checks(api):
    # This fixture's runtime is core, where teleop is withheld: the hold must hear that refusal.
    client, _, _, headers = api
    url = "/api/v1/navigation/approval/trial"
    assert client.post(f"{url}/start", json={"direction": "forward", "stop_cause": "button_release"},
                       headers=headers["person-a"]).status_code == 200
    assert "CAPABILITY_WITHHELD" in client.post(f"{url}/hold", headers=headers["person-a"]).text


def test_a_trial_over_the_api_drives_through_teleop_and_stops(api, monkeypatch):
    monkeypatch.setattr("core_api_web.api.v1.control.require_kept", lambda *_: None)
    client, svc, _, headers = api
    url = "/api/v1/navigation/approval/trial"
    started = client.post(f"{url}/start", json={"direction": "forward", "stop_cause": "button_release"},
                          headers=headers["person-a"])
    assert started.status_code == 200, started.text
    assert svc.modes.mode.value == "MANUAL"
    held = client.post(f"{url}/hold", headers=headers["person-a"])
    assert held.status_code == 200, held.text
    other = client.post(f"{url}/hold", headers=headers["admin-a"])
    assert "TRIAL_OWNER" in other.text, other.text
    stopped = client.post(f"{url}/stop", headers=headers["person-a"])
    assert stopped.status_code == 200, stopped.text
    late = client.post(f"{url}/hold", headers=headers["person-a"])
    assert late.status_code == 409, late.text
