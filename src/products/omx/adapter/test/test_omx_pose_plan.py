"""D-402 CELL_TRANSFER planner, simulation cell profile, and owner acceptance (ROS-free)."""

from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from omx_adapter.command_owner import ArmCommandOwner, JointStateSnapshot, TrajectoryCommand
from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
from omx_adapter.manipulation_plan import ExecutionStateSnapshot
from omx_adapter.pose_plan import (
    CARRY_Z_INSUFFICIENT,
    CELL_HASH_MISMATCH,
    GRIPPER_NOT_OPEN,
    HOME_DEVIATION,
    PHASE_DURATION_EXCEEDED,
    STATE_INVALID,
    AnalyticCellTransferPlanner,
    CellPlanningProfile,
    CellTransferPlan,
    CellTransferPlanRejected,
    CellTransferRequest,
    validate_cell_transfer_plan,
)


PROFILE_PATH = Path(__file__).resolve().parents[5] / "deploy/robot/omx/sim/cell_profile.yaml"
CELL = "c" * 64


@pytest.fixture(scope="module")
def kin():
    return OmxKinematics.load()


@pytest.fixture(scope="module")
def profile():
    return CellPlanningProfile.load(PROFILE_PATH)


def _document():
    return yaml.safe_load(PROFILE_PATH.read_text(encoding="utf-8"))


def _request(**overrides):
    values = dict(
        job_id="job-1", recipe_sha256="a" * 64, cell_sha256=CELL, step_index=0, item="box",
        home=TopDownPose(0.12, 0.0, 0.12, 0.0),
        pick=TopDownPose(0.18, -0.12, 0.02, 0.3),
        place=TopDownPose(0.17, 0.13, 0.045, -0.5),
        pick_approach_z=0.06, place_approach_z=0.085, carry_z=0.11, grasp_depth_m=0.01,
        grasp_width_m=0.03,
    )
    values.update(overrides)
    return CellTransferRequest(**values)


def _state(kin, profile, *, home=None, sequence=7, delta=None, scene=None):
    home = home or _request().home
    joints = kin.solve_top_down(home, profile.ik_limits()).joints
    positions = dict(zip(ARM_JOINTS, joints))
    positions[profile.gripper_joint] = profile.gripper_open
    for name, value in (delta or {}).items():
        positions[name] += value
    return ExecutionStateSnapshot(
        sequence=sequence, joint_positions=positions, calibration_revision="omx-f-gazebo-only-v1",
        transform_revision="tf-sim-1", planning_scene_revision=scene or kin.planning_scene_revision,
        observed_at_monotonic_s=100.0,
    )


def _planner(kin, accepted=CELL):
    return AnalyticCellTransferPlanner(kin, accepted_cell_sha256=lambda: accepted,
                                       monotonic=lambda: 100.5)


def _plan(kin, profile, **overrides):
    return _planner(kin).plan_transfer(_request(**overrides), profile, _state(kin, profile))


# ---- profile -------------------------------------------------------------------


def test_profile_loads_with_content_hash_revision(profile, kin):
    assert profile.revision == hashlib.sha256(PROFILE_PATH.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    assert profile.kinematics_revision == kin.revision
    assert profile.joint_names == ARM_JOINTS + ("gripper_joint_1",)
    assert profile.gripper_open == 1.0 and profile.gripper_closed == 0.0
    for name in profile.joint_names:
        lower, upper = profile.position_limits[name]
        # Nominal limits are strictly inside the URDF +/-2*pi and contain the spawn pose.
        assert -2 * math.pi < lower < 0.0 < upper < 2 * math.pi
        assert profile.velocity_limits[name] == 0.5
        assert profile.acceleration_limits[name] == 0.5
    srdf_home = (0.0, -1.57, 1.57, 1.57, 0.0)
    for name, value in zip(ARM_JOINTS, srdf_home):
        lower, upper = profile.position_limits[name]
        assert lower <= value <= upper
    # Gripper included: approach/grasp check it; the runner skips it only after grasp.
    assert profile.start_state_tolerances() == {name: 0.02 for name in profile.joint_names}
    assert profile.planning_limit_fraction == 0.8


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d.update(schema="rosy.other.v1"), "schema"),
    (lambda d: d.update(profile="device"), "simulation"),
    (lambda d: d["joints"]["joint2"].update(position=[0.5, -0.5]), "increasing"),
    (lambda d: d["joints"]["joint3"].update(velocity=0.0), "positive"),
    (lambda d: d["joints"]["joint4"].update(acceleration=float("nan")), "finite"),
    (lambda d: d["joints"].pop("joint5"), "joint1..joint5"),
    (lambda d: d["gripper"].update(open=2.0), "within gripper limits"),
    (lambda d: d["gripper"].update(closed=1.0), "differ"),
    (lambda d: d["workspace"].update(min_m=[0.3, -0.28, 0.005]), "increasing"),
    (lambda d: d.update(cartesian_step_m=-0.005), "positive"),
    (lambda d: d["phase_max_duration_s"].pop("grasp"), "approach, grasp"),
    (lambda d: d["owner"].update(action_timeout_s=10.0), "longest phase"),
    (lambda d: d.update(kinematics_revision="kin"), "sha256"),
    (lambda d: d.update(planning_limit_fraction=1.2), "planning_limit_fraction"),
    (lambda d: d.update(planning_limit_fraction=0.0), "planning_limit_fraction"),
    (lambda d: d.pop("planning_limit_fraction"), "planning_limit_fraction"),
    (lambda d: d["owner"].pop("wall_clock_bound_factor"), "wall_clock_bound_factor"),
    # A5: only after-grasp phases, only arm joints, at most 0.1 rad, never below the base.
    (lambda d: d.update(phase_start_state_tolerance_rad={"approach": {"joint5": 0.05}}), "transfer, release"),
    (lambda d: d.update(phase_start_state_tolerance_rad={"transfer": {"gripper_joint_1": 0.05}}), "arm joint"),
    (lambda d: d.update(phase_start_state_tolerance_rad={"transfer": {"joint5": 0.33}}), "0.1"),
    (lambda d: d.update(phase_start_state_tolerance_rad={"transfer": {"joint5": 0.01}}), "base"),
    (lambda d: d.update(phase_start_state_tolerance_rad=[]), "mapping"),
    (lambda d: d["owner"].update(wall_clock_bound_factor=0.9), "wall_clock_bound_factor"),
])
def test_profile_validation_fails_closed(mutate, match):
    document = copy.deepcopy(_document())
    mutate(document)
    with pytest.raises(ValueError, match=match):
        CellPlanningProfile.from_mapping(document, revision="0" * 64)


def test_owner_config_is_built_from_the_profile(profile):
    config = profile.arm_command_config(workcell_id="omx_pilot_sim", instance_id="omx_pilot_sim_01",
                                        calibration_revision="omx-f-gazebo-only-v1")
    assert config.allowed_owners == ("pilot_sim", "rule_based")
    assert config.max_goal_duration_s == max(profile.phase_max_duration_s.values())
    assert dict(config.position_limits) == dict(profile.position_limits)
    assert config.wall_clock_bound_factor == profile.wall_clock_bound_factor == 4.0


# ---- planning ------------------------------------------------------------------


def test_plan_has_four_phases_with_profile_revisions(kin, profile):
    plan = _plan(kin, profile)
    assert isinstance(plan, CellTransferPlan)
    assert [phase.phase_id for phase in plan.phases] == ["approach", "grasp", "transfer", "release"]
    assert plan.kinematics_revision == kin.revision
    assert plan.profile_revision == profile.revision
    assert plan.planner_revision == "omx-analytic-top-down-v1"
    assert plan.gripper_joint_names == ("gripper_joint_1",)
    for phase in plan.phases:
        assert phase.planning_scene_revision == "kin:" + kin.revision
        assert phase.source_state_sequence == 7
        assert phase.calibration_revision == "omx-f-gazebo-only-v1"
    for before, after in zip(plan.phases, plan.phases[1:]):
        assert after.start_state_positions == before.points[-1].positions
    validate_cell_transfer_plan(plan, profile, kinematics_revision=kin.revision, now_monotonic_s=101.0)


def _arm_path(kin, phase):
    return [kin.fk(point.positions[:5]) for point in phase.points]


def test_phase_shapes_are_vertical_then_carry_height_never_diagonal(kin, profile):
    request = _request()
    plan = _plan(kin, profile)
    start = kin.fk(plan.phases[0].start_state_positions[:5])
    for phase in plan.phases:
        poses = [start] + _arm_path(kin, phase)
        for a, b in zip(poses, poses[1:]):
            assert a.tool_down_error_rad < 1e-6
            horizontal = math.hypot(b.x - a.x, b.y - a.y) > 1e-7
            if horizontal:
                # xy only moves at carry_z.
                assert a.z == pytest.approx(request.carry_z, abs=1e-6)
                assert b.z == pytest.approx(request.carry_z, abs=1e-6)
        start = poses[-1]
    approach, grasp, transfer, release = plan.phases
    end = kin.fk(approach.points[-1].positions[:5])
    assert (end.x, end.y, end.z) == pytest.approx((0.18, -0.12, 0.02), abs=1e-6)
    assert abs(math.remainder(end.yaw - 0.3, math.pi)) < 1e-6
    assert all(point.positions[5] == profile.gripper_open for point in approach.points)
    # grasp moves only the gripper, open -> width-matched close (C3b B2), never 0.0 full close.
    assert {point.positions[:5] for point in grasp.points} == {approach.points[-1].positions[:5]}
    close = profile.gripper_close_for_width(request.grasp_width_m)
    assert grasp.points[-1].positions[5] == close and close > profile.gripper_closed + 0.2
    end = kin.fk(transfer.points[-1].positions[:5])
    assert (end.x, end.y, end.z) == pytest.approx((0.17, 0.13, 0.045), abs=1e-6)
    assert abs(math.remainder(end.yaw + 0.5, math.pi)) < 1e-6
    assert all(point.positions[5] == close for point in transfer.points)
    # release opens first, then retreats to home.
    assert release.points[0].positions[:5] == transfer.points[-1].positions[:5]
    assert release.points[-1].positions[5] == profile.gripper_open
    home = kin.fk(release.points[-1].positions[:5])
    assert (home.x, home.y, home.z) == pytest.approx((0.12, 0.0, 0.12), abs=1e-6)
    # approach passes through pick approach_z, transfer through place approach_z.
    assert any(abs(p.z - 0.06) < 1e-9 and abs(p.x - 0.18) < 1e-9 for p in _arm_path(kin, approach))
    assert any(abs(p.z - 0.085) < 1e-9 and abs(p.x - 0.17) < 1e-9 for p in _arm_path(kin, transfer))


def test_every_point_is_timed_within_profile_rates(kin, profile):
    plan = _plan(kin, profile)
    for phase in plan.phases:
        times = [point.time_from_start_s for point in phase.points]
        assert all(b > a for a, b in zip(times, times[1:]))
        assert times[-1] <= profile.phase_max_duration_s[phase.phase_id]
        for point in phase.points:
            for name, v, a in zip(phase.joint_names, point.velocities, point.accelerations):
                # Planned at limit x planning_limit_fraction; the owner checks the full limit.
                fraction = profile.planning_limit_fraction
                assert abs(v) <= profile.velocity_limits[name] * fraction + 1e-9
                assert abs(a) <= profile.acceleration_limits[name] * fraction + 1e-9
        assert phase.points[-1].velocities == (0.0,) * 6


class _Handle:
    def done(self):
        return True

    def succeeded(self):
        return True

    def cancel(self):
        return None


class _Port:
    def __init__(self):
        self.sent = []

    def send_goal(self, command):
        self.sent.append(command)
        return _Handle()


def test_real_command_owner_accepts_every_generated_phase(kin, profile):
    plan = _plan(kin, profile)
    config = profile.arm_command_config(workcell_id="omx_pilot_sim", instance_id="omx_pilot_sim_01",
                                        calibration_revision="omx-f-gazebo-only-v1")
    clock = {"now": 10.0}
    port = _Port()
    owner = ArmCommandOwner(config, port, monotonic=lambda: clock["now"], session_id="session-1")
    for sequence, phase in enumerate(plan.phases, start=1):
        clock["now"] += 0.1
        assert owner.observe_joint_state(JointStateSnapshot(
            positions=dict(zip(phase.joint_names, phase.start_state_positions)),
            sequence=sequence, received_at=clock["now"], calibration_revision=config.calibration_revision,
        ))
        decision = owner.submit(TrajectoryCommand(
            workcell_id=config.workcell_id, instance_id=config.instance_id,
            command_id=f"cmd-{phase.phase_id}", session_id="session-1", owner="rule_based",
            positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s, source_state_sequence=sequence,
            calibration_revision=config.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id,
        ))
        assert decision.accepted, (phase.phase_id, decision.reason)
        assert owner.poll().reason == "completed"
    assert len(port.sent) == 4


def test_measured_phase_durations_are_reported(kin, profile):
    plan = _plan(kin, profile)
    durations = {phase.phase_id: phase.points[-1].time_from_start_s for phase in plan.phases}
    # Stroke 1.0 - close(30 mm) at 0.4 rad/s, 0.4 rad/s^2 (0.8 x 0.5): 2 x 1 s ramps + cruise.
    stroke = profile.gripper_open - profile.gripper_close_for_width(0.03)
    assert durations["grasp"] == pytest.approx(2.0 + (stroke - 0.4) / 0.4, abs=1e-9)
    assert all(value > 0 for value in durations.values())


def test_worst_case_layout_fits_the_phase_budget(kin, profile):
    # Pick and place on opposite sides near the reach edge, the layout used to size
    # phase_max_duration_s in cell_profile.yaml.
    plan = _plan(kin, profile, pick=TopDownPose(0.05, -0.21, 0.02, 1.2),
                 place=TopDownPose(0.05, 0.21, 0.02, -1.2), carry_z=0.12)
    for phase in plan.phases:
        assert phase.points[-1].time_from_start_s <= profile.phase_max_duration_s[phase.phase_id]


# ---- rejections ----------------------------------------------------------------


def _reason(callable_):
    with pytest.raises(CellTransferPlanRejected) as caught:
        callable_()
    return caught.value.reason


def test_rejects_cell_hash_mismatch_before_planning(kin, profile):
    for accepted in ("d" * 64, None):
        assert _reason(lambda: _planner(kin, accepted).plan_transfer(
            _request(), profile, _state(kin, profile))) == CELL_HASH_MISMATCH


def test_rejects_start_state_away_from_home(kin, profile):
    for delta in ({"joint2": 0.05}, {"joint5": -0.03}):
        assert _reason(lambda: _planner(kin).plan_transfer(
            _request(), profile, _state(kin, profile, delta=delta))) == HOME_DEVIATION


def test_rejects_gripper_that_is_not_open_at_the_start(kin, profile):
    # Review reproducer: gripper at -0.1 must not be snapped to open by the first approach point.
    for gripper_delta in (-1.1, -0.5, 0.05):
        assert _reason(lambda: _planner(kin).plan_transfer(
            _request(), profile, _state(kin, profile, delta={"gripper_joint_1": gripper_delta}),
        )) == GRIPPER_NOT_OPEN
    _planner(kin).plan_transfer(_request(), profile, _state(kin, profile, delta={"gripper_joint_1": -0.015}))


def test_retreat_returns_to_the_start_wrist_roll(kin, profile):
    # Home taught at yaw 1.5: q5 = -1.5 and its 180-deg twin 1.64 are both in limits.
    home = TopDownPose(0.12, 0.0, 0.12, 1.5)
    state = _state(kin, profile, home=home)
    plan = _planner(kin).plan_transfer(_request(home=home), profile, state)
    end = plan.phases[-1].points[-1].positions
    assert end[:5] == pytest.approx(tuple(state.joint_positions[name] for name in ARM_JOINTS), abs=1e-6)


def test_carry_below_home_descends_vertically_from_home_first(kin, profile):
    plan = _plan(kin, profile, carry_z=0.09)
    start = kin.fk(plan.phases[0].start_state_positions[:5])
    # 0.12 -> 0.09 m at 5 mm samples = the first 6 points.
    first = [kin.fk(point.positions[:5]) for point in plan.phases[0].points[:6]]
    assert all((p.x, p.y) == pytest.approx((start.x, start.y), abs=1e-6) for p in first)
    assert first[0].z < start.z and first[-1].z == pytest.approx(0.09, abs=1e-6)


def test_rejects_insufficient_carry_and_approach_heights(kin, profile):
    assert _reason(lambda: _plan(kin, profile, carry_z=0.07)) == CARRY_Z_INSUFFICIENT
    assert _reason(lambda: _plan(kin, profile, pick_approach_z=0.01)) == CARRY_Z_INSUFFICIENT


def test_request_carries_grasp_depth_and_approach_clears_the_item_top(kin, profile):
    # C3b B1: pick/place z are TCP heights grasp_depth_m below the item top; the open
    # fingertips (~TCP) must be at or above that top before the vertical descent.
    assert _plan(kin, profile, grasp_depth_m=0.04).phases  # 0.02 + 0.04 = 0.06 = approach
    assert _reason(lambda: _plan(kin, profile, grasp_depth_m=0.041)) == CARRY_Z_INSUFFICIENT
    with pytest.raises(ValueError, match="grasp_depth_m"):
        _request(grasp_depth_m=-0.001)
    with pytest.raises(TypeError):
        values = dict(_request().__dict__)
        values.pop("grasp_depth_m")
        CellTransferRequest(**values)


def test_rejects_wrong_state_geometry(kin, profile):
    assert _reason(lambda: _planner(kin).plan_transfer(
        _request(), profile, _state(kin, profile, scene="kin:" + "0" * 64))) == STATE_INVALID
    stale = replace(profile, kinematics_revision="0" * 64)
    assert _reason(lambda: _planner(kin).plan_transfer(
        _request(), stale, _state(kin, profile))) == STATE_INVALID


@pytest.mark.parametrize("overrides, reason", [
    ({"place": TopDownPose(0.29, 0.0, 0.03, 0.0)}, "OUTSIDE_WORKSPACE"),
    ({"place": TopDownPose(0.27, 0.0, 0.03, 0.0)}, "UNREACHABLE"),
    ({"pick": TopDownPose(0.02, 0.0, 0.03, 0.0)}, "SINGULAR"),
    ({"carry_z": 0.215}, "JOINT_LIMIT"),  # q4 beyond 2.3 rad at carry height
    ({"place": TopDownPose(-0.2, -0.05, 0.03, 0.0)}, "JOINT_LIMIT"),
])
def test_rejects_ik_failures_without_partial_plan(kin, profile, overrides, reason):
    assert _reason(lambda: _plan(kin, profile, **overrides)) == reason


def test_rejects_unreachable_yaw(kin, profile):
    narrow = dict(profile.position_limits)
    narrow["joint5"] = (-0.2, 0.2)
    tight = replace(profile, position_limits=narrow)
    assert _reason(lambda: _planner(kin).plan_transfer(
        _request(home=TopDownPose(0.12, 0.0, 0.12, 0.0), pick=TopDownPose(0.18, 0.0, 0.02, 1.2)),
        tight, _state(kin, profile))) == "YAW_LIMIT"


def test_rejects_phase_over_its_duration_instead_of_splitting(kin, profile):
    durations = dict(profile.phase_max_duration_s)
    durations["transfer"] = 1.0
    short = replace(profile, phase_max_duration_s=durations)
    assert _reason(lambda: _planner(kin).plan_transfer(
        _request(), short, _state(kin, profile))) == PHASE_DURATION_EXCEEDED


def test_plan_rejects_arm_joints_as_gripper_joints(kin, profile):
    plan = _plan(kin, profile)
    with pytest.raises(ValueError, match="gripper"):
        replace(plan, gripper_joint_names=ARM_JOINTS)
    with pytest.raises(ValueError, match="gripper"):
        replace(plan, gripper_joint_names=("joint5", "gripper_joint_1"))


def test_validate_rejects_foreign_or_tampered_plan(kin, profile):
    plan = _plan(kin, profile)
    forged = _plan(kin, profile)
    object.__setattr__(forged, "gripper_joint_names", ("joint1",))
    with pytest.raises(ValueError, match="gripper"):
        validate_cell_transfer_plan(forged, profile, kinematics_revision=kin.revision, now_monotonic_s=101.0)
    with pytest.raises(ValueError, match="profile revision"):
        validate_cell_transfer_plan(plan, replace(profile, revision="1" * 64),
                                    kinematics_revision=kin.revision, now_monotonic_s=101.0)
    with pytest.raises(ValueError, match="kinematics"):
        validate_cell_transfer_plan(plan, profile, kinematics_revision="2" * 64, now_monotonic_s=101.0)
    with pytest.raises(ValueError, match="future"):
        validate_cell_transfer_plan(plan, profile, kinematics_revision=kin.revision, now_monotonic_s=99.0)
    rates = dict(profile.velocity_limits)
    rates["joint1"] = 0.01
    with pytest.raises(ValueError, match="joint1 limits"):
        validate_cell_transfer_plan(plan, replace(profile, velocity_limits=rates),
                                    kinematics_revision=kin.revision, now_monotonic_s=101.0)


def test_phase_start_tolerances_widen_only_the_named_joint_after_grasp(profile):
    document = copy.deepcopy(_document())
    document["phase_start_state_tolerance_rad"] = {"transfer": {"joint5": 0.06}, "release": {"joint4": 0.04}}
    widened = CellPlanningProfile.from_mapping(document, revision="0" * 64)
    base = widened.start_state_tolerances()
    assert base == {name: 0.02 for name in widened.joint_names}
    assert widened.start_state_tolerances("approach") == base
    assert widened.start_state_tolerances("grasp") == base
    assert widened.start_state_tolerances("transfer") == {**base, "joint5": 0.06}
    assert widened.start_state_tolerances("release") == {**base, "joint4": 0.04}


# ---- width-matched close (C3b B2) ------------------------------------------------


def test_jaw_gap_mapping_reproduces_the_gazebo_contact_angles(profile):
    # Gazebo 2026-10-02 (cell_profile.yaml gripper.jaw): 20/30/40 mm blocks stopped
    # gripper_joint_1 at 0.3187/0.4072/0.4956 rad.
    for q, gap_mm in ((0.3187, 20.0), (0.4072, 30.0), (0.4956, 40.0)):
        assert profile.jaw_gap_m(q) * 1000 == pytest.approx(gap_mm, abs=0.1)
    assert profile.jaw_pivot_half_separation_m == pytest.approx((0.0075 + 0.0108) / 2)  # URDF pivots
    for width in (0.01, 0.02, 0.03, 0.04):
        assert profile.jaw_gap_m(profile.gripper_contact_for_width(width)) == pytest.approx(width, abs=1e-9)


def test_close_target_squeezes_by_the_profile_margin(profile):
    squeeze = profile.gripper_squeeze_m
    assert 0 < squeeze <= 0.005
    close = profile.gripper_close_for_width(0.03)
    assert profile.jaw_gap_m(close) == pytest.approx(0.03 - squeeze, abs=1e-9)
    assert profile.gripper_closed < close < profile.gripper_contact_for_width(0.03) < profile.gripper_open


def test_grasp_width_outside_the_jaw_range_is_rejected(kin, profile):
    from omx_adapter.pose_plan import GRIPPER_WIDTH_INVALID

    assert _reason(lambda: _plan(kin, profile, grasp_width_m=0.002)) == GRIPPER_WIDTH_INVALID
    assert _reason(lambda: _plan(kin, profile, grasp_width_m=0.09)) == GRIPPER_WIDTH_INVALID
    with pytest.raises(ValueError, match="grasp_width_m"):
        _request(grasp_width_m=0.0)


@pytest.mark.parametrize("mutate, match", [
    (lambda d: d["gripper"].pop("jaw"), "jaw"),
    (lambda d: d["gripper"]["jaw"].update(squeeze_m=0.0), "squeeze_m"),
    (lambda d: d["gripper"]["jaw"].update(contact_point_m=[0.06]), "contact_point_m"),
])
def test_jaw_geometry_fails_closed(mutate, match):
    document = copy.deepcopy(_document())
    mutate(document)
    with pytest.raises(ValueError, match=match):
        CellPlanningProfile.from_mapping(document, revision="0" * 64)


def test_release_opens_only_to_the_release_width_until_carry_height(kin, profile):
    # C3b Gazebo run11: a full 1.0 rad open at the place swept a fingertip into the 15 mm-gap
    # neighbour and knocked it off the pallet. Release opens to item width + release
    # clearance, retreats vertically to carry_z, and opens fully only there.
    request = _request()
    plan = _planner(kin).plan_transfer(request, profile, _state(kin, profile))
    release = plan.phases[3]
    width_open = profile.gripper_contact_for_width(request.grasp_width_m + profile.gripper_release_clearance_m)
    place_arm = plan.phases[2].points[-1].positions[:5]
    at_place = [p for p in release.points if p.positions[:5] == place_arm]
    assert at_place and max(p.positions[5] for p in at_place) == pytest.approx(width_open)
    full = [p for p in release.points if p.positions[5] > width_open + 1e-9]
    assert full, "release must still end fully open"
    for point in full:
        assert kin.fk(point.positions[:5]).z >= request.carry_z - 1e-6
    assert release.points[-1].positions[5] == profile.gripper_open
