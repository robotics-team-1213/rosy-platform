"""D-402 §5 analytic top-down IK and URDF drift pins (ROS-free)."""

from __future__ import annotations

import copy
import math

import pytest
import yaml

from omx_adapter.kinematics import (
    ARM_JOINTS,
    DEFAULT_KINEMATICS_PATH,
    IK_JOINT_LIMIT,
    IK_OUTSIDE_WORKSPACE,
    IK_SINGULAR,
    IK_UNREACHABLE,
    IK_YAW_LIMIT,
    IkLimits,
    OmxKinematics,
    TopDownPose,
    wrap_angle,
)


PINNED_REVISION = "0a4af6a923b8b7d80b8c20506d1839c54d2e993e"
TWO_PI = 2.0 * math.pi


@pytest.fixture(scope="module")
def kin():
    return OmxKinematics.load()


def _limits(**overrides):
    values = dict(
        position_limits={name: (-math.pi, math.pi) for name in ARM_JOINTS},
        workspace_min_m=(-0.4, -0.4, -0.1), workspace_max_m=(0.4, 0.4, 0.4),
        singularity_radius_m=0.05,
    )
    values.update(overrides)
    return IkLimits(**values)


def _document():
    with open(DEFAULT_KINEMATICS_PATH, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def test_kinematics_file_pins_the_locked_open_manipulator_revision():
    document = _document()
    lock_path = DEFAULT_KINEMATICS_PATH.parents[5] / "deploy/robot/omx/stack.lock.yaml"
    with open(lock_path, encoding="utf-8") as handle:
        lock = yaml.safe_load(handle)
    assert document["source"]["revision"] == lock["vendor"]["revision"] == PINNED_REVISION
    assert document["source"]["release"] == lock["vendor"]["release"]
    assert document["source"]["file"] == "open_manipulator_description/urdf/omx_f/omx_f.urdf"


def test_urdf_geometry_drift_pins_every_chain_value():
    # Values hand-copied from omx_f.urdf at the pinned revision. Changing the
    # data file without re-reviewing D-402 geometry must fail here.
    expected = {
        "joint1": ([-0.01125, 0.0, 0.034], [0.0, 0.0, 1.0]),
        "joint2": ([0.0, 0.0, 0.0635], [0.0, 1.0, 0.0]),
        "joint3": ([0.0415, 0.0, 0.11315], [0.0, 1.0, 0.0]),
        "joint4": ([0.162, 0.0, 0.0], [0.0, 1.0, 0.0]),
        "joint5": ([0.0287, 0.0, 0.0], [1.0, 0.0, 0.0]),
        "end_effector_joint": ([0.09193, -0.0016, 0.0], None),
    }
    joints = {item["name"]: item for item in _document()["joints"]}
    assert list(joints) == list(expected)
    for name, (xyz, axis) in expected.items():
        assert joints[name]["origin"] == {"xyz": xyz, "rpy": [0.0, 0.0, 0.0]}
        assert joints[name].get("axis") == axis
        if axis is not None:
            assert joints[name]["urdf_limit"]["lower"] == pytest.approx(-TWO_PI)
            assert joints[name]["urdf_limit"]["upper"] == pytest.approx(TWO_PI)
    gripper = {item["name"]: item for item in _document()["gripper_joints"]}
    assert gripper["gripper_joint_1"]["origin"]["xyz"] == [0.0295, 0.0075, 0.0]
    assert gripper["gripper_joint_2"]["origin"]["xyz"] == [0.0295, -0.0108, 0.0]
    assert gripper["gripper_joint_2"]["mimic"] == {"joint": "gripper_joint_1", "multiplier": -1.0}
    assert _document()["srdf_gripper_states"] == {"open": 1.0, "close": 0.0}


def test_derived_closed_form_constants(kin):
    assert kin.shoulder_height_m == pytest.approx(0.0975)
    assert kin.base_xy == (-0.01125, 0.0)
    assert kin.l1 == pytest.approx(math.hypot(0.0415, 0.11315))
    assert kin.l1 == pytest.approx(0.1205204, abs=1e-6)
    assert kin.l2 == pytest.approx(0.162)
    assert kin.tool_length_m == pytest.approx(0.0287 + 0.09193)
    assert kin.planning_scene_revision == "kin:" + kin.revision
    assert len(kin.revision) == 64


def test_kinematics_rejects_a_chain_shape_the_closed_form_cannot_solve():
    document = _document()
    tilted = copy.deepcopy(document)
    tilted["joints"][2]["origin"]["rpy"] = [0.0, 0.1, 0.0]
    with pytest.raises(ValueError, match="rpy"):
        OmxKinematics(tilted)
    off_plane = copy.deepcopy(document)
    off_plane["joints"][3]["origin"]["xyz"] = [0.162, 0.01, 0.0]
    with pytest.raises(ValueError, match="arm plane"):
        OmxKinematics(off_plane)
    wrong_axis = copy.deepcopy(document)
    wrong_axis["joints"][1]["axis"] = [0.0, -1.0, 0.0]
    with pytest.raises(ValueError, match="axis"):
        OmxKinematics(wrong_axis)


def test_tool_down_sign_follows_urdf_axes(kin):
    # +y rotation turns +x toward -z, so q2 + q3 + q4 = +pi/2 points the tool down.
    down = kin.fk((0.0, 0.2, 0.3, math.pi / 2 - 0.5, 0.0))
    assert down.tool_down_error_rad == pytest.approx(0.0, abs=1e-12)
    up = kin.fk((0.0, 0.2, 0.3, -math.pi / 2 - 0.5, 0.0))
    assert up.tool_down_error_rad == pytest.approx(math.pi, abs=1e-12)
    assert kin.fk((0.0, 0.0, 0.0, 0.0, 0.0)).tool_down_error_rad == pytest.approx(math.pi / 2)


def test_known_poses_hand_checked(kin):
    # All zeros: arm straight forward, link2 vertical, forearm horizontal.
    zero = kin.fk((0.0,) * 5)
    assert (zero.x, zero.y, zero.z) == pytest.approx(
        (-0.01125 + 0.0415 + 0.162 + 0.0287 + 0.09193, -0.0016, 0.0975 + 0.11315), abs=1e-12)
    # SRDF home (0, -1.57, 1.57, 1.57, 0): link2 tilted back by 1.57, forearm horizontal,
    # tool pointing down. Hand-computed with Ry(q)(a, c) = (a cos q + c sin q, -a sin q + c cos q).
    home = kin.fk((0.0, -1.57, 1.57, 1.57, 0.0))
    c, s = math.cos(-1.57), math.sin(-1.57)
    elbow_x = -0.01125 + 0.0415 * c + 0.11315 * s
    elbow_z = 0.0975 - 0.0415 * s + 0.11315 * c
    # q4 = 1.57 is 0.0008 rad short of pi/2, so the tool tilts slightly toward +x.
    tool = 0.0287 + 0.09193
    assert home.x == pytest.approx(elbow_x + 0.162 + tool * math.cos(1.57), abs=1e-12)
    assert home.z == pytest.approx(elbow_z - tool * math.sin(1.57), abs=1e-12)
    assert home.y == pytest.approx(-0.0016, abs=1e-9)
    assert home.tool_down_error_rad == pytest.approx(0.0008, abs=1e-4)
    # Joint1 by 90 deg swings the pose around the joint1 axis at x = -0.01125.
    q1 = kin.fk((math.pi / 2, 0.0, 0.0, 0.0, 0.0))
    assert (q1.x, q1.y) == pytest.approx((-0.01125 + 0.0016, zero.x + 0.01125), abs=1e-12)


def test_srdf_home_is_on_the_elbow_up_branch(kin):
    home = (0.0, -1.57, 1.57, math.pi / 2 + 1.57 - 1.57, 0.0)
    pose = kin.fk(home)
    result = kin.solve_top_down(TopDownPose(pose.x, pose.y, pose.z, pose.yaw), _limits(
        singularity_radius_m=0.01,
    ))
    assert result.ok
    assert result.joints == pytest.approx(home, abs=1e-9)


def _grid():
    for x in (0.06, 0.1, 0.15, 0.2, 0.24):
        for y in (-0.15, -0.05, 0.0, 0.08, 0.15):
            for z in (0.005, 0.05, 0.1, 0.15):
                for yaw in (-2.5, -0.7, 0.0, 0.4, 1.2, 3.0):
                    yield TopDownPose(x, y, z, yaw)


def test_fk_of_ik_round_trip_on_grid(kin):
    limits = _limits()
    solved = 0
    for pose in _grid():
        result = kin.solve_top_down(pose, limits)
        if not result.ok:
            assert result.reason in {IK_UNREACHABLE, IK_SINGULAR}
            continue
        solved += 1
        fk = kin.fk(result.joints)
        assert (fk.x, fk.y, fk.z) == pytest.approx((pose.x, pose.y, pose.z), abs=1e-6)
        assert fk.tool_down_error_rad == pytest.approx(0.0, abs=1e-6)
        assert kin.tool_down_sum_error(result.joints) == pytest.approx(0.0, abs=1e-9)
        # The returned yaw is the target or its 180 deg twin; FK reproduces it exactly.
        assert abs(wrap_angle(fk.yaw - result.yaw)) < 1e-6
        assert abs(math.remainder(fk.yaw - pose.yaw, math.pi)) < 1e-6
    assert solved >= 400


def test_ik_of_fk_round_trip_recovers_joints(kin):
    limits = _limits()
    for q in ((0.3, 0.2, 0.4, math.pi / 2 - 0.6, 0.5),
              (-1.2, -0.5, 1.0, math.pi / 2 - 0.5, -0.4),
              (2.0, 0.6, -0.4, math.pi / 2 - 0.2, 1.5)):
        pose = kin.fk(q)
        result = kin.solve_top_down(TopDownPose(pose.x, pose.y, pose.z, pose.yaw), limits,
                                    reference_q5=q[4])
        assert result.ok
        assert result.joints == pytest.approx(q, abs=1e-6)


def test_yaw_maps_to_wrist_roll_relative_to_joint1(kin):
    limits = _limits()
    base = kin.solve_top_down(TopDownPose(0.15, 0.1, 0.05, 0.0), limits)
    q1 = base.joints[0]
    assert base.joints[4] == pytest.approx(wrap_angle(q1 - 0.0), abs=1e-6)
    turned = kin.solve_top_down(TopDownPose(0.15, 0.1, 0.05, 0.5), limits)
    assert turned.joints[4] == pytest.approx(turned.joints[0] - 0.5, abs=1e-6)


def test_yaw_wraparound_and_symmetric_candidate_nearest_reference(kin):
    limits = _limits(position_limits={**{n: (-math.pi, math.pi) for n in ARM_JOINTS},
                                      "joint5": (-2.0, 2.0)})
    # yaw = +pi and yaw = -pi are the same orientation.
    a = kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, math.pi), limits)
    b = kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, -math.pi), limits)
    assert a.ok and b.ok and a.joints == pytest.approx(b.joints, abs=1e-9)
    # q1 ~ 0, so q5 = -pi is outside +/-2.0: the 180 deg twin (q5 ~ 0) is chosen.
    assert abs(a.joints[4]) < 0.1
    assert abs(math.remainder(a.yaw - math.pi, TWO_PI)) > 3.0
    # Reference selects between in-limit candidates 2*pi apart.
    wide = _limits(position_limits={**{n: (-math.pi, math.pi) for n in ARM_JOINTS},
                                    "joint5": (-4.0, 4.0)})
    high = kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, -2.5), wide, reference_q5=3.0)
    low = kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, -2.5), wide, reference_q5=-3.0)
    assert high.joints[4] > 2.0 and low.joints[4] < -0.5
    for result in (high, low):
        fk = kin.fk(result.joints)
        assert (fk.x, fk.y, fk.z) == pytest.approx((0.15, 0.0, 0.05), abs=1e-6)


def test_rejection_outside_workspace(kin):
    limits = _limits(workspace_min_m=(-0.2, -0.2, 0.0), workspace_max_m=(0.2, 0.2, 0.2))
    assert kin.solve_top_down(TopDownPose(0.21, 0.0, 0.05, 0.0), limits).reason == IK_OUTSIDE_WORKSPACE
    assert kin.solve_top_down(TopDownPose(0.1, 0.0, -0.01, 0.0), limits).reason == IK_OUTSIDE_WORKSPACE


def test_rejection_unreachable_far_and_near(kin):
    limits = _limits(singularity_radius_m=0.001)
    far = kin.solve_top_down(TopDownPose(0.30, 0.0, 0.01, 0.0), limits)
    assert far.reason == IK_UNREACHABLE
    # Wrist 0.1206 m above a TCP just above the shoulder: planar distance < |L1 - L2|.
    near = kin.solve_top_down(TopDownPose(0.0, 0.0, -0.023, 0.0), _limits(singularity_radius_m=0.001))
    assert near.reason == IK_UNREACHABLE


def test_rejection_near_base_axis_is_singular(kin):
    limits = _limits(singularity_radius_m=0.05)
    assert kin.solve_top_down(TopDownPose(0.02, 0.0, 0.05, 0.0), limits).reason == IK_SINGULAR


def test_rejection_joint_limit(kin):
    narrow = {name: (-math.pi, math.pi) for name in ARM_JOINTS}
    narrow["joint2"] = (-0.1, 0.1)
    result = kin.solve_top_down(TopDownPose(0.1, 0.0, 0.005, 0.0), _limits(position_limits=narrow))
    assert result.reason == IK_JOINT_LIMIT


def test_rejection_yaw_cannot_be_reached(kin):
    narrow = {name: (-math.pi, math.pi) for name in ARM_JOINTS}
    narrow["joint5"] = (-0.2, 0.2)
    result = kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, 1.2), _limits(position_limits=narrow))
    assert result.reason == IK_YAW_LIMIT
    assert kin.solve_top_down(TopDownPose(0.15, 0.0, 0.05, 0.1),
                              _limits(position_limits=narrow)).ok


def test_ik_input_validation(kin):
    with pytest.raises(ValueError):
        TopDownPose(float("nan"), 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        _limits(workspace_min_m=(0.0, 0.0, 0.0), workspace_max_m=(0.1, 0.1, 0.0))
    with pytest.raises(ValueError):
        IkLimits({"joint1": (-1.0, 1.0)}, (-1, -1, -1), (1, 1, 1), 0.05)


def measure_reach_ring(kin, limits, z):
    """Min/max TCP radius from the joint1 axis solvable along +x at height z."""
    radii = []
    for step in range(0, 701):
        x = -0.01125 + step * 0.0005
        # y = -0.0016 puts the wrist (not the offset TCP) on the base x axis.
        if kin.solve_top_down(TopDownPose(x, -0.0016, z, 0.0), limits).ok:
            radii.append(x + 0.01125)
    return min(radii), max(radii)


def test_reach_ring_at_table_height(kin):
    # Unlimited joints: geometric ring. D-402 §5 estimated <= ~0.28 m from the joint2 axis.
    inner, outer = measure_reach_ring(kin, _limits(singularity_radius_m=0.001), 0.005)
    assert 0.27 < outer < 0.285
    assert inner < 0.06
