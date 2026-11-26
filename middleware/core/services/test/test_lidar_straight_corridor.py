"""Positive, blocked and unknown scan-plane evidence for a native 3 cm straight segment."""
import math
from types import SimpleNamespace

import pytest
from core_features.command.lidar_corridor import assess_straight_corridor


@pytest.fixture
def corridor():
    robot = SimpleNamespace(body_stop_known=True, body_front_x_m=.042, body_rear_x_m=-.076,
        body_half_width_m=.05655, body_rotation_radius_m=.08257, body_lidar_x_m=-.038,
        lidar_forward_deg=180., lidar_self_mask=())
    step = math.tau/720
    scan = dict(ranges=[1.]*720, angle_min=-math.pi, angle_increment=step, angle_max=math.pi-step,
                frame_id="rosy_42/rplidar_link", range_min=.01, range_max=8., received_at=10.,
                source_stamp_ns=9_900_000_000, source_now_ns=10_000_000_000)
    def assess(direction="forward", d=.03, now=10.01):
        return assess_straight_corridor(scan, robot, (.042, .135, .057), "rosy_42", direction, d, now)
    return scan, robot, assess


@pytest.mark.parametrize("direction,beam", [("forward", 0), ("reverse", 360)])
def test_required_sector_is_fully_observed(corridor, direction, beam):
    scan, _, assess = corridor
    clear = assess(direction)
    assert clear["status"] == "observed_clear" and clear["required_beams"] == clear["observed_beams"] > 10
    scan["ranges"][(beam+360)%720] = None
    assert assess(direction)["status"] == "observed_clear"
    scan["ranges"][beam] = math.inf
    assert assess(direction)["reason"] == "unobserved_sector"
    scan["ranges"][beam] = .1 if direction=="forward" else .117
    assert assess(direction)["status"] == "blocked"


def test_reverse_tray_and_range_blind_spots(corridor):
    scan, robot, assess = corridor
    scan["ranges"][360] = .07
    assert assess("reverse")["reason"] == "occluded_sector"
    scan["ranges"][360] = 1.
    robot.lidar_self_mask = ((-180., -178., .15),)
    assert assess("reverse")["reason"] == "masked_sector"
    robot.lidar_self_mask = ()
    scan["range_min"] = .05
    assert assess("reverse")["reason"] == "blind_range"


def test_refuses_missing_partial_shifted_or_expired_geometry(corridor):
    scan, robot, assess = corridor
    assert assess(now=10.11)["reason"] == "scan_stale"
    assert assess(d=.04)["reason"] == "scan_invalid"
    scan["source_stamp_ns"] = scan["source_now_ns"]+1
    assert assess()["reason"] == "scan_stale"
    scan["source_stamp_ns"] = scan["source_now_ns"]
    scan["angle_max"] -= .15
    assert assess()["reason"] == "scan_invalid"
    scan["frame_id"]="rosy_45/rplidar_link"
    assert assess()["reason"] == "frame_mismatch"
    scan.clear()
    assert assess()["reason"] == "scan_missing"


@pytest.mark.parametrize("value", [None, float("nan"), 0., 9., 10**400])
def test_missing_or_out_of_spec_return_is_unknown(corridor, value):
    scan, _, assess = corridor
    scan["ranges"][0] = value
    assert assess()["reason"] == "unobserved_sector"


def test_unknown_body_mask_stamps_and_negative_distance(corridor):
    scan, robot, assess = corridor
    assert assess("reverse", d=-.01)["reason"] == "scan_invalid"
    assert assess(now=9.99)["reason"] == "scan_stale"
    robot.lidar_self_mask = ((float("nan"), 1., .1),)
    assert assess()["reason"] == "body_unknown"
    robot.body_stop_known = False
    assert assess()["reason"] == "body_unknown"


def test_near_blind_disk_entirely_inside_pinky_chassis(corridor):
    scan, robot, assess = corridor
    robot.body_lidar_x_m = -.017  # Pinky URDF, centreline mounting
    scan["range_min"] = .05
    assert assess("reverse")["status"] == "observed_clear"
    scan["ranges"][360] = None
    assert assess("reverse")["reason"] == "unobserved_sector"
    scan["range_min"] = .061
    assert assess("reverse")["reason"] == "blind_range"
