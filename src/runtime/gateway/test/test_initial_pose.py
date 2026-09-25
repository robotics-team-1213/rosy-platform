"""AMCL initial pose must carry variance or the filter ignores the click."""

from pathlib import Path

from core_features.maps import occupancy_map_id
from core_features.navigation.initial_pose import amcl_pose_covariance

GRID = {
    "width": 2,
    "height": 2,
    "resolution": 0.05,
    "origin": {"x": -1.0, "y": -0.5, "yaw": 0.0},
    "data": [0, 100, -1, 50],
}


def test_amcl_initial_pose_covariance_is_not_all_zeros():
    cov = amcl_pose_covariance()
    assert len(cov) == 36
    assert cov[0] > 0
    assert cov[7] > 0
    assert cov[35] > 0
    assert sum(cov) == cov[0] + cov[7] + cov[35]


def test_ros_bridge_publishes_amcl_covariance():
    text = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "bridge"
        / "ros_bridge.py"
    ).read_text(encoding="utf-8")
    assert "amcl_pose_covariance" in text
    assert "msg.pose.covariance" in text


def test_ros_bridge_stamps_occupancy_id_only_when_map_id_is_unset():
    text = (
        Path(__file__).resolve().parents[1]
        / "core"
        / "bridge"
        / "ros_bridge.py"
    ).read_text(encoding="utf-8")
    assert "occupancy_map_id" in text
    assert 'startswith("occupancy:")' in text


def test_occupancy_map_id_changes_with_grid_content():
    other = dict(GRID, data=[0, 0, 0, 0])
    assert occupancy_map_id(GRID).startswith("occupancy:")
    assert occupancy_map_id(GRID) != occupancy_map_id(other)
    assert occupancy_map_id(GRID) == occupancy_map_id(dict(GRID))
