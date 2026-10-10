"""D-607 8: Fleet's REALIGN (PIVOT on a turn spot, KTURN) through the real line-follow manager."""

import math

import pytest

from core_features.line_follow.manager import (
    LineFollowConfig, LineFollowManager, LineFollowMode, LineObservation)
from core_features.line_follow.recovery.stuck.stuck_recovery import AnswerRefused

REV = "a" * 64
WALL = 1_800_000_000.0
LIDAR_X = -0.017
BODY = dict(body_front_x_m=0.04205, body_rear_x_m=-0.076, body_half_width_m=0.05655,
            body_rotation_radius_m=0.08257, body_lidar_x_m=LIDAR_X)


class _Events:
    def __init__(self):
        self.seen = []

    def publish(self, name, **kwargs):
        self.seen.append((name, kwargs.get("data")))


def _ring(radius=0.4, extra=()):
    """Base-frame returns all around (every rotation sector seen), as LiDAR-origin points."""
    base = [(radius * math.cos(math.radians(a)), radius * math.sin(math.radians(a))) for a in range(0, 360, 10)]
    return [(x - LIDAR_X, y) for x, y in [*base, *extra]]


class Rig:
    """A CAMERA_LINE manager held by a NOMINAL-ground HOLD (-> no_motion stuck), with odom that
    integrates the decided twist, a fixed LiDAR ring, the camera and the IR row."""

    def __init__(self, **overrides):
        self.t, self.x, self.y, self.yaw, self.twist = 10.0, 0.0, 0.0, 0.0, (0.0, 0.0)
        self.ir, self.extra = None, ()
        self.events = _Events()
        config = LineFollowConfig(**{"ir_guard_enabled": True, "ir_calibration_revision": REV,
                                     "obstacle_mode": "path", "recovery_local_enabled": True,
                                     "stuck_realign_enabled": True, **BODY, **overrides})
        self.m = LineFollowManager(self.events, config=config, clock=lambda: self.t)
        self.m._wall = lambda: WALL + self.t
        self.m.bind_recovery(console_linked=lambda: True, calibration_active=lambda: False,
                             linear_ceiling=lambda: 0.1)
        self.m.set_mode(LineFollowMode.CAMERA_LINE)
        while self.m.status().stuck is None and self.t < 20.0:
            self.step()
        assert self.m.status().stuck.cause == "no_motion"

    def feed(self):
        t, m = self.t, self.m
        self.fed = t
        stamp = round(t * 1e9)
        m.observe_return_pose(stamp_ns=stamp, source_now_ns=stamp, frame="odom", x=self.x, y=self.y,
                              yaw=self.yaw, received_at=t)
        m.observe(LineObservation(source=LineFollowMode.CAMERA_LINE, stamp=t, visible=True, error=0.0,
                                  confidence=0.9, ground="NOMINAL"), received_at=t, source_now=t)
        m.observe(LineObservation(source=LineFollowMode.IR_LINE, stamp=t, visible=self.ir is not None,
                                  error=self.ir, confidence=0.9 if self.ir is not None else 0.0,
                                  ir_calibrated=True, calibration_revision=REV), received_at=t, source_now=t)
        points = _ring(extra=self.extra)
        m.observe_scan_points(points, received_at=t)
        m.observe_body_points(points, range_min=0.0, received_at=t)

    def step(self, dt=0.1):
        linear, angular = self.twist
        self.yaw += angular * dt
        self.x += linear * math.cos(self.yaw) * dt
        self.y += linear * math.sin(self.yaw) * dt
        self.t += dt
        self.feed()
        d = self.m.tick(self.t + 0.01)
        self.twist = (d.linear, d.angular)
        return d

    def realign(self, **body):
        req = {"kind": "PIVOT", "angle_rad": 1.2, "pose_stamp": WALL + self.fed, "attempt": 1,
               "turn_spot": True, **body}
        return self.m.stuck_decision(self.m.status().stuck.stuck_id, "REALIGN", by="operator", realign=req)

    def run(self, seconds=30.0):
        seen = []
        while self.m.status().stuck is not None and self.m.status().stuck.phase.startswith("REALIGN") \
                and seconds > 0:
            seen.append(self.step())
            seconds -= 0.1
        return seen

    def results(self):
        return [d for name, d in self.events.seen if name == "nav.line_stuck_local_result"]


def _refused(rig, why, **body):
    with pytest.raises(AnswerRefused) as caught:
        rig.realign(**body)
    assert caught.value.code == "STUCK_DECISION_REFUSED" and why in str(caught.value), str(caught.value)


def test_pivot_at_a_turn_spot_turns_on_odom_through_the_ir_centre_and_closes_on_lane_evidence():
    rig = Rig()
    rig.ir = 0.0                                              # paint under the IR centre: exempt on a spot
    assert rig.realign() == "realign" and rig.m.status().stuck.phase == "REALIGNING"
    seen = rig.run()
    turning = [d for d in seen if d.angular != 0.0]
    assert turning and all(d.linear == 0.0 and d.angular > 0.0 for d in turning)
    assert abs(rig.yaw - 1.2) <= math.radians(10.0) + 0.03
    assert rig.results()[-1]["result"] == "recovered" and rig.m.status().stuck is None


def test_pivot_off_a_turn_spot_and_malformed_answers_are_refused():
    rig = Rig()
    _refused(rig, "realign_kind", turn_spot=False)
    _refused(rig, "realign_kind", kind="UTURN")
    _refused(rig, "realign_angle", angle_rad=2.0)
    _refused(rig, "realign_unset", kind="KTURN", back_m=0.1, back_radius_m=0.05, fwd_radius_m=0.05)
    _refused(rig, "pose_stamp_unknown", pose_stamp=WALL + rig.fed - 10.0)
    assert rig.m.status().stuck.phase == "WAITING_CONSOLE" and rig.step().angular == 0.0


def test_kturn_backs_on_an_arc_then_drives_forward_to_the_target():
    rig = Rig()
    # reverse arc 0.03 m on R 0.05 turns 0.6 rad; the forward arc turns the rest
    assert rig.realign(kind="KTURN", angle_rad=-1.4, back_m=0.03, back_radius_m=0.05, fwd_radius_m=0.05,
                       turn_spot=False) == "realign"
    seen = [d for d in rig.run(60.0) if d.linear != 0.0 or d.angular != 0.0]
    assert seen[0].linear < 0.0 and seen[0].angular < 0.0           # reverse arc, turning right
    assert any(d.linear > 0.0 and d.angular < 0.0 for d in seen)     # then the forward arc
    assert all(abs(d.angular) <= 0.3 + 1e-9 and abs(d.linear) <= 0.03 + 1e-9 for d in seen)
    assert abs(rig.yaw + 1.4) <= math.radians(10.0) + 0.03
    assert rig.results()[-1]["result"] == "recovered"


def test_kturn_is_refused_with_the_rear_strip_blocked():
    rig = Rig()
    rig.extra = ((-0.076 - 0.03, 0.0),)                               # 3 cm behind the body rear
    rig.step()
    _refused(rig, "rear_blocked", kind="KTURN", angle_rad=-1.0, back_m=0.06, back_radius_m=0.05,
             fwd_radius_m=0.05, turn_spot=False)


def test_an_object_ahead_during_the_forward_arc_stops_it_for_fleet():
    rig = Rig()
    rig.realign(kind="KTURN", angle_rad=-1.2, back_m=0.02, back_radius_m=0.05, fwd_radius_m=0.05,
                turn_spot=False)
    while not rig.step().linear > 0.0:                                 # into the forward arc
        assert rig.m.status().stuck.phase == "REALIGNING"
    rig.extra = ((0.055, 0.0),)
    assert (rig.step().linear, rig.twist[1]) == (0.0, 0.0)
    assert rig.results()[-1] == pytest.approx(rig.results()[-1]) and \
        rig.results()[-1]["reason"] == "object_within_stop_distance"
    assert rig.m.status().stuck.phase == "WAITING_CONSOLE"


def test_kturn_stops_when_the_ir_centre_sees_paint():
    rig = Rig()
    rig.realign(kind="KTURN", angle_rad=-1.0, back_m=0.06, back_radius_m=0.05, fwd_radius_m=0.05,
                turn_spot=False)
    assert rig.step().linear < 0.0
    rig.ir = 0.0
    assert rig.step().linear == 0.0 and rig.results()[-1]["reason"] == "lane_departure"


def test_estop_mode_off_ends_the_turn_and_it_never_restarts():
    rig = Rig()
    rig.realign()
    assert rig.step().angular > 0.0
    rig.m.set_mode(LineFollowMode.OFF, reason="estop")
    assert rig.m.status().stuck is None and rig.step().angular == 0.0
    rig.m.set_mode(LineFollowMode.CAMERA_LINE)
    assert all(rig.step().angular == 0.0 for _ in range(30))


def test_refused_while_the_crosswalk_gate_is_armed():
    rig = Rig()
    rig.m._crosswalk_armed = lambda: True
    _refused(rig, "crosswalk_gate")


def test_two_realigns_per_stuck_then_refused():
    rig = Rig()
    stuck_id = rig.m.status().stuck.stuck_id
    for _ in range(2):
        rig.realign()
        rig.m.stuck_decision(stuck_id, "WAIT", by="operator")
    _refused(rig, "realign_attempts_exhausted")


def test_a_running_realign_refuses_another_moving_answer():
    rig = Rig()
    rig.realign()
    _refused(rig, "realign_active")
    with pytest.raises(AnswerRefused, match="realign_active"):
        rig.m.stuck_decision(rig.m.status().stuck.stuck_id, "BACK_AND_RETRY", by="operator")


def test_off_by_default_refuses_and_does_not_offer_realign():
    rig = Rig(stuck_realign_enabled=False)
    assert "REALIGN" not in rig.m.status().stuck.decisions
    _refused(rig, "realign_kind")
    assert "REALIGN" in Rig().m.status().stuck.decisions
