"""Arm S live state becomes a valid Fleet ArmObservation in radians; stale or repeated rows are not sent."""
import importlib.util
import math
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).parents[1]
OMX = ROOT / "deploy/robot/omx"
sys.path.insert(0, str(OMX))
try:
    spec = importlib.util.spec_from_file_location("arm_status_bridge", OMX / "arm_status_bridge.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
finally:
    sys.path.remove(str(OMX))


def test_follower_units_convert_to_dynamixel_radians():
    rad = m.to_radians([0.0, -50.0, 50.0, 100.0, -100.0, 50.0])
    assert rad["joint1"] == pytest.approx(0.0, abs=0.002)  # tick 2047.5 is about 0 rad
    assert rad["joint2"] == pytest.approx(-math.pi / 2, abs=0.002)
    assert rad["joint4"] == pytest.approx(math.pi, abs=0.002) and rad["joint5"] == pytest.approx(-math.pi, abs=0.002)
    assert rad["gripper_joint_1"] == pytest.approx(0.0, abs=0.002)  # gripper 50 of 0..100


def test_only_fresh_newer_rows_are_sent():
    row = {"t": 100.0, "state": [0, 0, 0, 0, 0, 50]}
    assert m.fresh_sample(row, None, 100.5) is not None
    assert m.fresh_sample(row, 100.0, 100.5) is None          # already sent
    assert m.fresh_sample(row, None, 103.0) is None           # runner stopped: stale
    assert m.fresh_sample({"t": 100.0}, None, 100.5) is None  # no state


def test_the_sample_is_a_valid_fleet_arm_observation():
    sys.path.insert(0, str(ROOT / "contracts/foundation"))
    try:
        observations = pytest.importorskip("core_common.protocol.workcell_observations")
    finally:
        sys.path.remove(str(ROOT / "contracts/foundation"))
    sample = m.fresh_sample({"t": 1792850000.5, "state": [29.0, -17.8, 24.7, 43.1, -33.3, 46.6]}, None, 1792850000.6)
    observation = observations.ArmObservation(epoch="a" * 32, sequence=1, captured_at=sample.captured_at,
                                              positions=sample.value)
    assert set(observation.positions) == set(m.JOINTS)
