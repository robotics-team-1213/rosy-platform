import importlib.util
from pathlib import Path

import pytest


MODULE = Path(__file__).parents[1] / "graph_contract.py"
spec = importlib.util.spec_from_file_location("graph_contract", MODULE)
graph_contract = importlib.util.module_from_spec(spec)
spec.loader.exec_module(graph_contract)


def test_single_robot_ros_contract_matches_core_boundary():
    contract = graph_contract.robot_contract("rosy_01")
    assert contract["command_topic"] == "cmd_vel"
    assert contract["namespace"] == "rosy_01"
    assert contract["odom_frame"] == "rosy_01/odom"
    assert contract["base_frame"] == "rosy_01/base_footprint"
    assert contract["wheel_joints"] == ("l_wheel_joint", "r_wheel_joint")
    assert contract["wheel_radius"] == 0.028
    assert contract["wheel_distance"] == 0.0961


def test_namespace_is_required_and_bounded():
    for bad in ("", "rosy", "/rosy_01", "rosy_00", "other_01", "rosy_001"):
        with pytest.raises(ValueError):
            graph_contract.robot_contract(bad)
