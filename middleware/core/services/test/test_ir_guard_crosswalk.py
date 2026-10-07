"""D-491: the IR lane guard rests only while its sensor row is in a known crosswalk zone."""
import pytest

from core_common.protocol.lane_containment import LaneContainmentEvidence
from core_features.line_follow.crosswalk_zone import CrosswalkZones
from core_features.line_follow.manager import LineFollowManager
from core_features.line_follow.model import LineFollowConfig, LineFollowMode, LineObservation

REV = "a" * 64


class Bus:
    def publish(self, *args, **kwargs):
        pass


def rig(**config):
    clock = [1.0]
    values = dict(ir_guard_enabled=True, ir_calibration_revision=REV, ir_row_x_m=0.0295)
    values.update(config)
    manager = LineFollowManager(Bus(), clock=lambda: clock[0], config=LineFollowConfig(**values))
    manager.set_mode(LineFollowMode.CAMERA_LINE)
    return clock, manager


def step(r, t, x, *, y=0.0, yaw=0.0, ir_error=None, crosswalk=None, ground="CALIBRATED",
         uncertainty=0.005, ir_calibrated=True):
    clock, manager = r
    clock[0] = t
    manager.observe_return_pose(stamp_ns=round(t * 1e9), source_now_ns=round(t * 1e9),
                                frame="odom", x=x, y=y, yaw=yaw, received_at=t)
    raw = dict(stamp=t, geometry_id="rig-a", ground_source=ground, uncertainty_m=uncertainty,
               boundaries=[dict(side="left", slope=0.0, intercept_m=0.09, observed_x_min_m=0.1,
                                observed_x_max_m=0.4),
                           dict(side="right", slope=0.0, intercept_m=-0.09, observed_x_min_m=0.1,
                                observed_x_max_m=0.4)])
    if crosswalk is not None:
        raw["crosswalk"] = dict(near_m=crosswalk[0], far_m=crosswalk[1])
    manager.observe(LineObservation(LineFollowMode.CAMERA_LINE, t, True, 0.0, 0.9,
                                    ground="NOMINAL" if ground == "NOMINAL" else None,
                                    containment=LaneContainmentEvidence.model_validate(raw)),
                    received_at=t, source_now=t)
    manager.observe(LineObservation(LineFollowMode.IR_LINE, t, ir_error is not None, ir_error,
                                    0.9 if ir_error is not None else 0.0, ir_calibrated=ir_calibrated,
                                    calibration_revision=REV if ir_calibrated else None), received_at=t, source_now=t)
    return manager.tick(t)


def drive_to(r, x_end, *, crosswalk=(0.15, 0.27), ground="CALIBRATED", ir_error=0.0):
    """Camera sees the crosswalk once from x=0, then the robot drives on to x_end."""
    step(r, 1.0, 0.0, crosswalk=crosswalk, ground=ground)
    t, x = 1.0, 0.0
    while x < x_end - 1e-9:
        t, x = t + 0.05, min(x_end, x + 0.01)
        step(r, t, x)
    return step(r, t + 0.05, x_end, ir_error=ir_error)


@pytest.mark.parametrize("ir_error", [0.0, -0.8, 0.8])
def test_guard_rests_on_the_crosswalk_the_camera_saw(ir_error):
    r = rig()
    decision = drive_to(r, 0.15, ir_error=ir_error)   # IR row at 0.1795, inside 0.15..0.27
    assert decision.linear > 0
    assert r[1].status().reason == "ir_guard_crosswalk"


def test_without_a_seen_crosswalk_the_centre_reading_still_stops():
    r = rig()
    assert drive_to(r, 0.15, crosswalk=None).linear == 0
    assert r[1].status().reason == "lane_departure"


@pytest.mark.parametrize("ground,uncertainty", [("NOMINAL", 0.005), ("CALIBRATED", None),
                                                ("CALIBRATED", 0.02)])
def test_uncalibrated_or_unbounded_projection_admits_no_zone(ground, uncertainty):
    zones = CrosswalkZones()
    zones.observe(LaneContainmentEvidence.model_validate(dict(
        stamp=1.0, geometry_id="g", ground_source=ground, uncertainty_m=uncertainty, boundaries=[],
        crosswalk=dict(near_m=0.15, far_m=0.27))), epoch=0, received_at=1.0)
    assert zones._zones == []


def test_unbounded_projection_keeps_the_stop():
    r = rig()
    step(r, 1.0, 0.0, crosswalk=(0.15, 0.27), uncertainty=None)
    t, x = 1.0, 0.0
    while x < 0.15 - 1e-9:
        t, x = t + 0.05, x + 0.01
        step(r, t, x, uncertainty=None)
    assert step(r, t + 0.05, 0.15, ir_error=0.0, uncertainty=None).linear == 0
    assert r[1].status().reason == "lane_departure"


def test_past_the_far_edge_the_guard_is_back():
    r = rig()
    # IR row at 0.3295; far 0.27 + uncertainty 0.005 + 5 % of 0.30 m travelled = 0.29.
    assert drive_to(r, 0.30).linear == 0
    assert r[1].status().reason == "lane_departure"


def test_zone_length_is_capped():
    r = rig()
    # 0.10..0.45 seen, capped to 0.10..0.30; IR row at 0.3495 is past it.
    assert drive_to(r, 0.32, crosswalk=(0.10, 0.45)).linear == 0


def test_odometry_break_drops_the_zone():
    r = rig()
    step(r, 1.0, 0.0, crosswalk=(0.15, 0.27))
    step(r, 1.05, 0.0)                     # the zone is anchored at its image pose
    r[1].invalidate_return_pose()
    t, x = 1.0, 0.0
    while x < 0.15 - 1e-9:
        t, x = t + 0.05, x + 0.01
        step(r, t, x)
    assert step(r, t + 0.05, 0.15, ir_error=0.0).linear == 0


def test_unknown_ir_row_never_rests():
    r = rig(ir_row_x_m=None)
    assert drive_to(r, 0.15).linear == 0


def test_ir_row_config_is_validated():
    with pytest.raises(ValueError):
        LineFollowConfig(ir_row_x_m=float("nan"))
    with pytest.raises(ValueError):
        LineFollowConfig(crosswalk_zone_max_m=0.0)
    with pytest.raises(ValueError):
        LineFollowConfig(crosswalk_odom_error_fraction=-0.1)


def test_a_dead_ir_still_stops_inside_a_zone():
    r = rig()
    drive_to(r, 0.15)
    assert step(r, r[0][0] + 0.05, 0.15, ir_error=0.0, ir_calibrated=False).linear == 0
    assert r[1].status().reason == "lane_guard_stale"


def test_turning_off_the_crosswalk_ends_the_rest():
    r = rig()
    assert drive_to(r, 0.17).linear > 0
    t = r[0][0]
    for k in range(1, 23):   # quarter turn in place (0.1 rad a tick), then 0.06 m on the new heading
        yaw = min(1.5708, k * 0.1)
        decision = step(r, t + k * 0.05, 0.17, y=max(0.0, (k - 16) * 0.01), yaw=yaw, ir_error=0.0)
    # Inside the rest budget and the corridor: only the heading check ends it.
    assert decision.linear == 0 and r[1].status().reason == "lane_departure"


def test_drifting_into_the_next_lane_ends_the_rest():
    r = rig()
    assert drive_to(r, 0.15).linear > 0
    for k in range(1, 15):   # 1 cm sideways per tick: no odom jump, inside the rest budget
        decision = step(r, r[0][0] + 0.05, 0.15, y=k * 0.01, ir_error=0.0)
    assert decision.linear == 0 and r[1].status().reason == "lane_departure"


def test_chained_detections_cannot_extend_the_rest_past_the_budget():
    r = rig()
    t, x, rests = 1.0, 0.0, []
    for _ in range(60):          # a false crosswalk reported every frame, IR firing throughout
        t, x = t + 0.05, x + 0.01
        rests.append(step(r, t, x, ir_error=0.0, crosswalk=(0.0, 0.25)).linear > 0)
    budget = 0.20 * 1.1 + 0.03
    assert sum(rests) * 0.01 <= budget + 0.02
    assert not rests[-1] and r[1].status().reason == "lane_departure"
    step(r, t + 0.05, x + 0.01, crosswalk=(0.0, 0.25))          # IR clear once re-arms
    assert step(r, t + 0.1, x + 0.02, ir_error=0.0, crosswalk=(0.0, 0.25)).linear > 0


def test_a_stale_ir_reading_does_not_re_arm_a_spent_rest():
    r = rig()
    t, x = 1.0, 0.0
    for _ in range(60):
        t, x = t + 0.05, x + 0.01
        step(r, t, x, ir_error=0.0, crosswalk=(0.0, 0.25))
    step(r, t + 0.05, x + 0.01, ir_error=0.0, crosswalk=(0.0, 0.25), ir_calibrated=False)
    assert step(r, t + 0.1, x + 0.02, ir_error=0.0, crosswalk=(0.0, 0.25)).linear == 0
