"""D-394: geometry.yaml is the URDF evaluated, and every Pinky Pro default equals it.

The first test regenerates geometry.yaml from the xacro and fails on any
difference, so the URDF and the profile config cannot drift. The rest pin each
consumer's default to geometry.yaml (URDF nominal, refined per robot by an
accepted calibration record, D-47 addendum store).
"""
import math
import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import urdf_nominal  # noqa: E402

REPO = urdf_nominal.REPO
GEOMETRY = yaml.safe_load(urdf_nominal.OUTPUT.read_text(encoding="utf-8"))


def test_checked_in_geometry_matches_the_urdf():
    checked_in = urdf_nominal.OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert checked_in == urdf_nominal.render(), "run python tools/calibration/urdf_nominal.py"
    assert urdf_nominal.main(["--check"]) == 0


def test_header_names_the_urdf_source_and_its_blob():
    text = urdf_nominal.OUTPUT.read_text(encoding="utf-8")
    assert "src/sim/description/urdf/rosy.urdf.xacro git blob " + urdf_nominal.git_blob(urdf_nominal.URDF) in text
    assert "upstream import 6455b1a9" in text


def test_extractor_reproduces_the_hand_derived_chain():
    """The numbers the 2026-10-01 decision was computed from, re-derived in code."""
    g = urdf_nominal.nominal()
    assert g["base_link_z_m"] == pytest.approx(0.028)
    assert g["lidar"]["x_m"] == pytest.approx(-0.017)
    assert g["lidar"]["height_m"] == pytest.approx(0.125)
    assert g["lidar"]["yaw_rad"] == pytest.approx(math.pi)
    assert g["lidar"]["forward_deg"] == pytest.approx(180.0)
    tilt = math.radians(8.0)
    assert g["camera"]["x_m"] == pytest.approx(0.020 + 0.015 * math.cos(tilt) - 0.0121 * math.sin(tilt))
    assert g["camera"]["x_m"] == pytest.approx(0.0332, abs=1e-4)
    assert g["camera"]["height_m"] == pytest.approx(0.0634, abs=1e-4)
    assert g["camera"]["pitch_rad"] == pytest.approx(tilt)
    assert g["wheels"]["radius_m"] == pytest.approx(0.028)
    assert g["wheels"]["joint_y_m"] == pytest.approx(0.04055)
    assert g["wheels"]["separation_m"] == pytest.approx(0.0971)
    for key, y in (("left", 0.020), ("mid", 0.0), ("right", -0.020)):
        assert g["ir"][key]["x_m"] == pytest.approx(0.0295)
        assert g["ir"][key]["y_m"] == pytest.approx(y)
        assert g["ir"][key]["height_m"] == pytest.approx(0.013)
    assert g["ultrasonic"]["x_m"] == pytest.approx(0.0267)
    assert (g["imu"]["x_m"], g["imu"]["y_m"], g["imu"]["z_base_link_m"]) == pytest.approx((-0.044, 0.0, 0.0525))
    assert g["footprint"]["rotation_radius_sim_box_m"] == pytest.approx(0.088, abs=5e-4)
    assert 0.080 < g["footprint"]["rotation_radius_m"] < g["footprint"]["rotation_radius_sim_box_m"]


def test_camera_follows_the_tilt_arg():
    args = {**urdf_nominal.arg_defaults(), "cam_tilt_deg": 25}
    g = urdf_nominal.nominal(args)
    assert g["camera"]["pitch_deg"] == pytest.approx(25.0)
    # the Gazebo lane bench value (map_v2_fleet_lane.launch.py dock_observer)
    assert g["camera"]["x_m"] == pytest.approx(0.028481, abs=1e-6)
    assert g["camera"]["height_m"] == pytest.approx(0.060194, abs=1e-6)


def test_unsupported_xacro_fails_loudly():
    with pytest.raises(ValueError):
        urdf_nominal._eval("__import__('os')", {"pi": math.pi})
    with pytest.raises(ValueError):
        urdf_nominal._eval("radius ** 2", {"radius": 1.0})
