"""D-47 addendum: CORE line_follow takes the calibrated LiDAR mount, the hand value only as fallback.

The Pinky Pro's C1 nose sits near scan angle 180-190 deg. These tests pin
the resolution order (accepted store record > adapter binding > hand value)
and that the obstacle sector and path follow a 190-deg mount.
"""
import math

import pytest

from core.bridge import observation
from core.lidar_mount import resolve_lidar_forward_deg
from core_common.calibration_store import CalibrationStore
from core_features.line_follow.clearance import front_clearance, scan_points
from core_features.line_follow.manager import LineFollowConfig, LineFollowManager

ROBOT = "rosy-test"


def _scan(values_by_deg, n=360):
    """angle_min=-pi, 1 deg steps; {scan deg: range}, inf elsewhere."""
    ranges = [math.inf] * n
    for deg, value in values_by_deg.items():
        ranges[(deg + 180) % n] = value
    return {"ranges": ranges, "angle_min": -math.pi, "angle_max": math.pi * (n - 2) / n,
            "range_min": 0.05, "range_max": 12.0}


def test_hand_value_is_only_the_fallback(tmp_path):
    deg, source = resolve_lidar_forward_deg({"lidar_forward_deg": 180.0}, hand_default=0.0,
                                            store=CalibrationStore(tmp_path), robot=ROBOT)
    assert deg == 180.0 and "hand value" in source


def test_adapter_binding_beats_the_hand_value(tmp_path):
    deg, source = resolve_lidar_forward_deg({"lidar_forward_deg": 180.0}, hand_default=0.0,
                                            adapter_parameters={"lidar_yaw_offset": 3.31612558},
                                            store=CalibrationStore(tmp_path), robot=ROBOT)
    assert deg == pytest.approx(190.0, abs=1e-6) and "adapter" in source


def test_accepted_store_record_wins_and_a_candidate_does_not(tmp_path):
    store = CalibrationStore(tmp_path)
    rid = store.add(ROBOT, "lidar_mount", {"lidar_yaw_offset": math.radians(181.9)}, method="t/1")
    deg, source = resolve_lidar_forward_deg({"lidar_forward_deg": 180.0}, hand_default=0.0,
                                            adapter_parameters={"lidar_yaw_offset": 3.31612558},
                                            store=store, robot=ROBOT)
    assert deg == pytest.approx(190.0, abs=1e-6)          # candidate: not used
    store.set_status(ROBOT, "lidar_mount", rid, "accepted", actor="operator")
    deg, source = resolve_lidar_forward_deg({"lidar_forward_deg": 180.0}, hand_default=0.0,
                                            adapter_parameters={"lidar_yaw_offset": 3.31612558},
                                            store=store, robot=ROBOT)
    assert deg == pytest.approx(181.9, abs=1e-6) and rid in source


def test_manager_binds_the_resolved_mount_and_remembers_its_source():
    manager = LineFollowManager(object(), config=LineFollowConfig(lidar_forward_deg=180.0))
    manager.use_lidar_forward(190.0, "calibration record x")
    assert manager.config.lidar_forward_deg == 190.0
    assert manager.lidar_forward_source == "calibration record x"


def test_sector_follows_a_190_deg_mount():
    # An obstacle at scan angle 205 deg: 15 deg off the nose for a 190 mount
    # (inside the +-20 sector), 25 deg off for a 180 mount (outside).
    sample = _scan({-155: 0.15})       # -155 == 205 deg
    assert front_clearance(sample, forward_deg=190.0, half_angle_deg=20.0) == 0.15
    assert front_clearance(sample, forward_deg=180.0, half_angle_deg=20.0) is None


def test_path_points_rotate_with_the_mount():
    sample = _scan({-170: 0.30})       # 190 deg: dead ahead of a 190 mount
    (x, y), = scan_points(sample, forward_deg=190.0)
    assert x == pytest.approx(0.30, abs=1e-9) and y == pytest.approx(0.0, abs=1e-9)
    (x, y), = scan_points(sample, forward_deg=180.0)
    # A 180 mount puts the same return 10 deg to the left: the path check would
    # look past an obstacle that is really dead ahead.
    assert y == pytest.approx(0.30 * math.sin(math.radians(10.0)), abs=1e-9)


class _Services:
    def __init__(self, forward_deg):
        self.line_follow = LineFollowManager(object(), config=LineFollowConfig(obstacle_mode="sector"))
        self.line_follow.use_lidar_forward(forward_deg, "test")
        self.seen = []
        self.line_follow.observe_clearance = lambda d, received_at: self.seen.append(d)


def test_bridge_uses_the_bound_mount_for_the_front_sector():
    services = _Services(190.0)
    observation.front_clearance(services, _scan({-155: 0.15}), received_at=1.0)
    assert services.seen == [0.15]
    services = _Services(180.0)
    observation.front_clearance(services, _scan({-155: 0.15}), received_at=1.0)
    assert services.seen == [None]
