"""D-986: navigation re-approval over REST: who may, when a trial may move, what it records."""
import hashlib
import json
import math
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from core_common.protocol.state_components import BatteryStatus
from core_features.command.approval_trials import (ApprovalTrials, LINEAR_TOLERANCE_M, MAX_HOLD_S, RUN_MARGIN_M,
                                                   TRAVEL_CAP_M, TrialRefused, _scan_outside, _scan_travel_m,
                                                   check_floor_motion, require_clearance)

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
        self.scene_moves = False  # floor trials: the scan follows the body, unless the wheels are slipping
        self.body_x = self.body_yaw = 0.0
        self.slipping = False
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
        if not self.slipping:
            self.body_x += self.linear * dt
            self.body_yaw += self.angular * dt
        if self.scan:
            self.scan = {**self.scan, "received_at": self.now}
            if self.scene_moves:
                self.scan["ranges"] = self.room()

    def room(self):
        # An uneven room, so a turn has something to lay over itself.
        step = self.scan["angle_increment"]
        angles = [self.scan["angle_min"] + index * step for index in range(360)]
        return [1.5 + 0.4 * math.sin(2 * (a + self.body_yaw)) + 0.2 * math.sin(5 * (a + self.body_yaw))
                - self.body_x * math.cos(a) for a in angles]


@pytest.fixture
def robot():
    return Robot()


@pytest.fixture
def trials(robot, tmp_path):
    return ApprovalTrials(robot, robot, robot, lambda: BODY, tmp_path / "trials",
                          clock=lambda: robot.now, wall=lambda: robot.now, thread=False)


def drive(robot, trials, direction, cause, *, hold_s=1.5, surface="floor"):
    robot.scene_moves = True
    robot.scan["ranges"] = robot.room()
    trials.start(direction, cause, OWNER, test_surface=surface)
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
    assert trials.last["state"] == "recorded" and trials.last["scan_check"]["odom"], trials.last
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
    drive(robot, trials, "forward", "button_release", hold_s=2.0)
    raw = json.loads((tmp_path / "trials/forward-button_release.json").read_text(encoding="ascii"))
    assert raw["requested_linear_mps"] == 0.015


def test_the_speed_stays_inside_the_envelope_whatever_the_live_limit(robot, trials):
    import mapping_approval
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    assert 0 < robot.commanded[0] < mapping_approval.MAX_LINEAR_MPS
    trials.abort("end")
    trials.start("ccw", "button_release", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    assert 0 < robot.commanded[1] < mapping_approval.MAX_ANGULAR_RPS


def test_a_limit_too_low_to_measure_refuses_the_trial(robot, trials):
    robot.limits.manual_linear = 0.005
    with pytest.raises(TrialRefused) as refused:
        trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == "TRIAL_LIMIT_TOO_LOW"


def test_a_button_hold_that_goes_quiet_stops_and_leaves_no_evidence(robot, trials, tmp_path):
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
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
    trials.start("forward", "command_loss", OWNER, test_surface="lifted")
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
    trials.start("forward", "command_loss", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    trials.stop(OWNER)
    assert trials.last["state"] == "aborted" and not trials.active


def test_the_hold_time_limit_stops_a_held_button(robot, trials):
    trials.start("cw", "button_release", OWNER, test_surface="lifted")
    deadline = robot.now + MAX_HOLD_S + 1
    while trials.active and robot.now < deadline:
        trials.hold(OWNER, robot.send)
        robot.step(0.05)
        trials.tick()
    assert trials.last == {"direction": "cw", "stop_cause": "button_release", "state": "aborted",
                           "reason": "the hold ran past its time limit"}


def test_the_travel_cap_stops_the_robot(robot, trials):
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    robot.step()
    trials.tick()
    robot.x = TRAVEL_CAP_M * 2
    robot.step()
    trials.tick()
    assert trials.last["reason"] == "the travel cap was reached"


def test_stale_odometry_stops_the_trial(robot, trials):
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
    trials.hold(OWNER, robot.send)
    robot.odom_fresh = False
    while trials.active:
        trials.hold(OWNER, robot.send)
        robot.step(0.05)
        trials.tick()
    assert trials.last["reason"] == "odometry went stale during the trial"


def test_another_operator_cannot_hold_or_stop_a_trial(robot, trials):
    trials.start("forward", "button_release", OWNER, test_surface="lifted")
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
        trials.start("forward", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == code and not trials.active


def test_a_blank_scan_behind_refuses_reverse(robot, trials):
    for ranges in ([math.inf] * 360, [math.nan] * 360):
        robot.scan.update(ranges=ranges)
        with pytest.raises(TrialRefused) as refused:
            trials.start("reverse", "button_release", OWNER, test_surface="lifted")
        assert refused.value.code == "CLEARANCE_UNKNOWN"


# The real robot's outline (profile core.yaml) and real C1 scans with 0.033-0.049 m returns on the body.
PINKY = SimpleNamespace(body_stop_known=True, lidar_forward_deg=180.0, lidar_self_mask=(), body_lidar_x_m=-0.017,
                        body_front_x_m=0.04205, body_rear_x_m=-0.076, body_half_width_m=0.05655,
                        body_rotation_radius_m=0.08257)
FORWARD_BEAM, REAR_BEAM = 0, 360


def real_scans():
    doc = json.loads((ROOT / "test/fixtures/robot_body/c1_coverage_flicker_scans.json").read_text(encoding="utf-8"))
    meta = doc["meta"]
    return [{"ranges": [math.inf if r is None else r for r in ranges], "angle_min": meta["angle_min"],
             "angle_max": meta["angle_min"] + meta["angle_increment"] * (len(ranges) - 1),
             "range_min": meta["range_min"], "range_max": meta["range_max"], "received_at": 100.0,
             "source_stamp_ns": 1, "source_now_ns": 1} for ranges in doc["scans"]]


def with_obstacle(scan_, beam, distance):
    ranges = list(scan_["ranges"])
    for index in range(beam - 3, beam + 4):
        ranges[index % len(ranges)] = distance
    return {**scan_, "ranges": ranges}


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("direction", ["forward", "reverse", "cw", "ccw"])
def test_a_clear_real_scene_passes_despite_returns_on_the_body(index, direction):
    sample = real_scans()[index]
    assert any(r < sample["range_min"] for r in sample["ranges"])
    assert require_clearance(sample, PINKY, direction, 100.0)


@pytest.mark.parametrize("direction,beam,body_m", [("forward", FORWARD_BEAM, 0.059), ("reverse", REAR_BEAM, 0.059)])
def test_a_real_obstacle_at_the_limit_still_refuses(direction, beam, body_m):
    need = TRAVEL_CAP_M + RUN_MARGIN_M
    sample = real_scans()[0]
    assert require_clearance(with_obstacle(sample, beam, body_m + need + 0.005), PINKY, direction, 100.0)
    with pytest.raises(TrialRefused) as refused:
        require_clearance(with_obstacle(sample, beam, body_m + need - 0.005), PINKY, direction, 100.0)
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


@pytest.mark.parametrize("direction", ["forward", "reverse", "cw"])
def test_a_minimum_range_reaching_past_the_body_fails_closed(direction):
    sample = {**real_scans()[0], "range_min": 0.06}
    with pytest.raises(TrialRefused, match="outside the body"):
        require_clearance(sample, PINKY, direction, 100.0)


def test_an_outline_that_cannot_be_read_fails_closed():
    outline = SimpleNamespace(**{**vars(PINKY), "body_front_x_m": None})
    with pytest.raises(TrialRefused) as refused:
        require_clearance(real_scans()[0], outline, "forward", 100.0)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


def test_a_scanner_covered_by_the_robot_itself_sees_nothing():
    sample = {**real_scans()[0], "ranges": [0.04] * 720}
    with pytest.raises(TrialRefused) as refused:
        require_clearance(sample, PINKY, "forward", 100.0)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


ALL_DIRECTIONS = [("forward", FORWARD_BEAM), ("reverse", REAR_BEAM), ("cw", FORWARD_BEAM), ("ccw", FORWARD_BEAM)]


def ranged(fill, beam, good):
    ranges = [fill] * 720
    for index in range(beam, beam + good):
        ranges[index % 720] = 2.0
    return {**real_scans()[0], "ranges": ranges}


@pytest.mark.parametrize("direction,beam", ALL_DIRECTIONS)
@pytest.mark.parametrize("good", [1, 5])
@pytest.mark.parametrize("fill", [0.0, math.inf, math.nan, 0.03])
def test_a_few_seeing_beams_among_no_returns_or_self_returns_refuse(direction, beam, good, fill):
    with pytest.raises(TrialRefused) as refused:
        require_clearance(ranged(fill, beam - good // 2, good), PINKY, direction, 100.0)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


@pytest.mark.parametrize("direction,beam", ALL_DIRECTIONS)
def test_a_scan_of_only_zero_or_inf_refuses(direction, beam):
    for fill in (0.0, math.inf):
        with pytest.raises(TrialRefused) as refused:
            require_clearance(ranged(fill, beam, 0), PINKY, direction, 100.0)
        assert refused.value.code == "CLEARANCE_UNKNOWN"


@pytest.mark.parametrize("direction,sector_beams", [("forward", 180), ("reverse", 180), ("cw", 720)])
def test_the_seeing_floor_counts_the_whole_sector_even_when_the_rest_is_the_body(direction, sector_beams):
    # All other beams end on the body, so the ratio alone would pass with any few returns.
    beam = REAR_BEAM if direction == "reverse" else FORWARD_BEAM
    few = sector_beams // 4 - 2
    with pytest.raises(TrialRefused) as refused:
        require_clearance(ranged(0.03, beam - few // 2, few), PINKY, direction, 100.0)
    assert refused.value.code == "CLEARANCE_UNKNOWN"
    enough = sector_beams // 4 + 2
    assert require_clearance(ranged(0.03, beam - enough // 2, enough), PINKY, direction, 100.0)


@pytest.mark.parametrize("beam", [REAR_BEAM, 180, 540])
def test_forward_ignores_what_is_behind_and_beside(beam):
    sample = with_obstacle(real_scans()[0], beam, 0.07)
    assert require_clearance(sample, PINKY, "forward", 100.0)


@pytest.mark.parametrize("beam", [FORWARD_BEAM, 180, 540])
def test_reverse_ignores_what_is_ahead_and_beside(beam):
    sample = with_obstacle(real_scans()[0], beam, 0.07)
    assert require_clearance(sample, PINKY, "reverse", 100.0)


def test_reverse_still_refuses_what_is_behind_and_forward_what_is_ahead():
    for direction, beam in (("reverse", REAR_BEAM), ("forward", FORWARD_BEAM)):
        with pytest.raises(TrialRefused) as refused:
            require_clearance(with_obstacle(real_scans()[0], beam, 0.07), PINKY, direction, 100.0)
        assert refused.value.code == "CLEARANCE_TOO_SMALL"


@pytest.mark.parametrize("direction,beam,refused", [("ccw", 689, True), ("cw", 689, False),
                                                    ("cw", 31, True), ("ccw", 31, False)])
def test_a_turn_is_judged_only_on_the_side_it_swings_into(direction, beam, refused):
    """A return 0.11 m from the LiDAR, 16 deg off the nose: one turn swings the body into it, the other away."""
    sample = with_obstacle(real_scans()[0], beam, 0.111)
    if refused:
        with pytest.raises(TrialRefused) as caught:
            require_clearance(sample, PINKY, direction, 100.0)
        assert caught.value.code == "CLEARANCE_TOO_SMALL"
    else:
        assert require_clearance(sample, PINKY, direction, 100.0)


def test_forward_asks_no_person_while_the_body_covers_the_minimum_range():
    assert require_clearance(real_scans()[0], PINKY, "forward", 100.0)


def test_rotation_needs_room_beyond_the_turning_circle(robot, trials):
    robot.scan.update(ranges=[0.11] * 360)
    with pytest.raises(TrialRefused) as refused:
        trials.start("cw", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_reverse_asks_no_person_and_still_needs_the_room_behind(robot, trials):
    """User 2026-11-09: no blind-zone confirmation; the rear is the heading of a reverse trial, so it must be clear."""
    trials.start("reverse", "button_release", OWNER, test_surface="lifted")
    trials.abort("test")
    robot.scan.update(ranges=[0.10] * 360)
    with pytest.raises(TrialRefused) as refused:
        trials.start("reverse", "button_release", OWNER, test_surface="lifted")
    assert refused.value.code == "CLEARANCE_TOO_SMALL"


def test_an_unknown_body_outline_fails_closed(robot):
    body = SimpleNamespace(**{**vars(BODY), "body_stop_known": False})
    with pytest.raises(TrialRefused) as refused:
        require_clearance(robot.scan, body, "forward", robot.now)
    assert refused.value.code == "CLEARANCE_UNKNOWN"


def test_spinning_wheels_leave_no_floor_evidence(robot, trials, tmp_path):
    robot.slipping = True
    drive(robot, trials, "forward", "button_release")
    assert trials.last["state"] == "refused" and trials.last["code"] == "WHEELS_NOT_MOVING_BODY"
    assert not list((tmp_path / "trials").glob("*.json")) if (tmp_path / "trials").exists() else True


@pytest.mark.parametrize("direction", ["cw", "ccw"])
def test_a_turn_that_spins_only_the_wheels_leaves_no_floor_evidence(robot, trials, direction):
    robot.slipping = True
    drive(robot, trials, direction, "button_release")
    assert trials.last["code"] == "WHEELS_NOT_MOVING_BODY"


def test_a_lifted_trial_is_recorded_as_lifted_without_a_scan_check(robot, trials, tmp_path):
    robot.slipping = True
    drive(robot, trials, "forward", "button_release", surface="lifted")
    assert trials.last == {"direction": "forward", "stop_cause": "button_release", "state": "recorded",
                           "test_surface": "lifted", "scan_check": None}
    record = json.loads((tmp_path / "trials/forward-button_release.surface.json").read_text(encoding="ascii"))
    raw = (tmp_path / "trials/forward-button_release.json").read_bytes()
    assert record["test_surface"] == "lifted" and record["raw_sha256"] == hashlib.sha256(raw).hexdigest()


def test_a_scan_gone_after_a_floor_trial_fails_closed(robot, trials):
    trials.start("forward", "command_loss", OWNER, test_surface="floor")
    trials.hold(OWNER, robot.send)
    while not trials.status()["active"]["stopping"]:
        robot.step()
        trials.tick()
    robot.scan = None
    while trials.active:
        robot.step()
        trials.tick()
    assert trials.last["code"] == "SCAN_UNUSABLE"


def test_a_floor_trial_too_short_to_check_says_so(robot, trials):
    drive(robot, trials, "forward", "button_release", hold_s=0.5)
    assert trials.last["code"] == "TRIAL_TOO_SHORT"


REAL_MOVED_M = 0.0625  # scan 0 to 1 of the real fixture, driving ahead


def test_real_scans_agree_with_real_travel_within_the_tolerance():
    first, second = real_scans()[:2]
    assert check_floor_motion(first, second, PINKY, "forward", REAL_MOVED_M)["scan"] == pytest.approx(REAL_MOVED_M, abs=0.003)


@pytest.mark.parametrize("odom", [0.03, -0.03, 0.2])
def test_real_scans_refuse_odometry_they_do_not_show(odom):
    first, second = real_scans()[:2]
    with pytest.raises(TrialRefused) as refused:
        check_floor_motion(first, first, PINKY, "forward", odom)
    assert refused.value.code == "WHEELS_NOT_MOVING_BODY"
    if odom != 0.03:
        with pytest.raises(TrialRefused):
            check_floor_motion(first, second, PINKY, "forward", odom)


def test_real_neighbouring_scans_stay_inside_the_linear_tolerance():
    # 0.1 s apart while driving: what is left is noise plus at most a little real motion.
    second, third = (_scan_outside(sample, PINKY) for sample in real_scans()[1:])
    assert abs(_scan_travel_m(second, third)) < LINEAR_TOLERANCE_M / 3 + 0.001


@pytest.mark.parametrize("beams", [8, 14, 24, -10])
def test_a_real_scene_turned_by_a_known_angle_is_recovered(beams):
    first = real_scans()[1]
    step = first["angle_max"] - first["angle_min"]
    step /= len(first["ranges"]) - 1
    # Only the room turns: the robot's own returns would stay put, so they leave the scene first.
    outside = [r if math.isfinite(r) and r >= 0.3 else math.inf for r in first["ranges"]]
    start = {**first, "ranges": outside}
    turned = {**first, "ranges": [outside[(index + beams) % 720] for index in range(720)]}
    seen = check_floor_motion(start, turned, PINKY, "ccw" if beams > 0 else "cw", beams * step)
    assert seen["scan"] == pytest.approx(beams * step, abs=step)


@pytest.mark.parametrize("direction,odom", [("forward", 0.03), ("cw", -0.1)])
def test_a_scan_with_too_little_in_view_fails_closed(direction, odom):
    blank = {**real_scans()[0], "ranges": [math.inf] * 720}
    with pytest.raises(TrialRefused) as refused:
        check_floor_motion(blank, blank, PINKY, direction, odom)
    assert refused.value.code == "SCAN_UNUSABLE"


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
                                       ("/trial/start", {"direction": "forward", "stop_cause": "button_release", "test_surface": "floor"})])
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
                           json={"direction": "forward", "stop_cause": "button_release", "test_surface": "floor"}, headers=headers["person-a"])
    assert response.status_code == 409 and "APPROVAL_NOT_MEASURING" in response.text


@pytest.mark.parametrize("battery,code", [(BatteryStatus(filtered_voltage=7.6, charging=True), "CHARGING"),
                                          (BatteryStatus(), "CHARGING_UNKNOWN")])
@pytest.mark.parametrize("path,body", [("/begin", None),
                                       ("/trial/start", {"direction": "forward", "stop_cause": "button_release", "test_surface": "floor"})])
def test_a_plugged_in_or_unknown_robot_is_not_measured(api, battery, code, path, body):
    client, svc, _, headers = api
    svc.state.set_battery_status(battery)
    response = client.post(f"/api/v1/navigation/approval{path}", json=body, headers=headers["person-a"])
    assert response.status_code == 409 and code in response.text
    assert not svc.approval_trials.active


def test_speed_is_not_the_callers_to_choose(api):
    client, _, _, headers = api
    assert client.post("/api/v1/navigation/approval/trial/start", headers=headers["person-a"],
                       json={"direction": "forward", "stop_cause": "button_release", "test_surface": "floor", "linear": 0.5}).status_code == 400


def test_the_blind_zone_confirmation_is_gone_from_the_request(api):
    """User 2026-11-09: no field to confirm the rear by eye; a reverse trial starts on the scan alone."""
    client, _, _, headers = api
    url = "/api/v1/navigation/approval/trial/start"
    body = {"direction": "reverse", "stop_cause": "button_release", "test_surface": "floor"}
    assert client.post(url, headers=headers["person-a"], json={**body, "blind_zone_confirmed": True}).status_code == 400
    assert client.post(url, headers=headers["person-a"], json=body).status_code == 200


def test_a_hold_goes_through_the_teleop_checks(api):
    # This fixture's runtime is core, where teleop is withheld: the hold must hear that refusal.
    client, _, _, headers = api
    url = "/api/v1/navigation/approval/trial"
    assert client.post(f"{url}/start", json={"direction": "forward", "stop_cause": "button_release", "test_surface": "floor"},
                       headers=headers["person-a"]).status_code == 200
    assert "CAPABILITY_WITHHELD" in client.post(f"{url}/hold", headers=headers["person-a"]).text


def test_a_trial_over_the_api_drives_through_teleop_and_stops(api, monkeypatch):
    monkeypatch.setattr("core_api_web.api.v1.control.require_kept", lambda *_: None)
    client, svc, _, headers = api
    url = "/api/v1/navigation/approval/trial"
    started = client.post(f"{url}/start", json={"direction": "forward", "stop_cause": "button_release", "test_surface": "floor"},
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
