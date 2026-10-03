"""Bind the ROS-free transfer Skill to the existing OMX planner and owner ports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import math
from typing import TYPE_CHECKING, Protocol

from rosy.contracts.skill import SkillInvocation
from rosy.skills.manipulation.transfer import PlannedTransfer, TransferPlanner, TransferSkill

if TYPE_CHECKING:
    from core_common.protocol.schemas import FleetCellTransferGrant
    from omx_adapter.manipulation_plan import ExecutionStateSnapshot
    from omx_adapter.command_owner import TrajectoryCommand
    from omx_adapter.gripper_contract import GripperObservation
    from omx_adapter.action_runner import StopFence
    from omx_adapter.manipulation_plan import PlannedMotionPhase
    from omx_adapter.pick_place_runner import PhaseGoalPort
    from omx_adapter.pose_plan import CellPlanningProfile, CellTransferPlan, CellTransferPlanProvider


class _PhaseExecutor(Protocol):
    @property
    def active_phase_id(self) -> str | None: ...

    def start(self, planned: PlannedTransfer) -> object: ...

    def advance(self) -> object: ...

    def cancel_current(self) -> Mapping[str, object]: ...


class _PickPlaceRunner(Protocol):
    plan: object

    @property
    def active_phase_id(self) -> str | None: ...

    def start(self) -> object: ...

    def advance(self) -> object: ...

    def cancel_current(self) -> Mapping[str, object]: ...


class OMXPickPlaceExecutor:
    """Adapt the existing PickPlaceRunner API to the Skill execution port."""

    def __init__(self, runner: _PickPlaceRunner, planned: PlannedTransfer) -> None:
        if not callable(getattr(runner, "start", None)) or not callable(
                getattr(runner, "cancel_current", None)):
            raise ValueError("an OMX PickPlaceRunner with exact-goal cancellation is required")
        if getattr(runner, "plan", None) is not planned.plan:
            raise ValueError("OMX PickPlaceRunner must own the Skill's exact planned transfer")
        self.runner = runner
        self.planned = planned

    @property
    def active_phase_id(self) -> str | None:
        return self.runner.active_phase_id

    def start(self, planned: PlannedTransfer) -> object:
        if planned is not self.planned:
            raise ValueError("phase execution cannot substitute another planned transfer")
        return self.runner.start()

    def cancel_current(self) -> Mapping[str, object]:
        return self.runner.cancel_current()

    def advance(self) -> object:
        return self.runner.advance()


def _pose(value: object, field: str) -> dict[str, float]:
    if not isinstance(value, Mapping):
        raise ValueError(f"grant {field} must be a pose object")
    expected = {"x", "y", "z", "yaw"}
    if set(value) != expected:
        raise ValueError(f"grant {field} must contain x, y, z and yaw")
    return {f"{name}_m" if name != "yaw" else "yaw_rad": value[name]
            for name in expected}


def cell_transfer_invocation(grant: FleetCellTransferGrant) -> SkillInvocation:
    """Project the validated Fleet grant payload into the versioned Skill input."""
    from core_common.protocol.schemas import FleetCellTransferGrant

    if not isinstance(grant, FleetCellTransferGrant):
        raise ValueError("a validated CELL_TRANSFER Fleet grant is required")
    transfer = grant.cell_transfer
    return SkillInvocation("pallet.transfer", "1.0.0", {
        "item": transfer.item,
        "pallet_id": transfer.pallet,
        "layer_index": transfer.layer,
        "home_pose_base": _pose(transfer.home.model_dump(), "home"),
        "source_pose_base": _pose(transfer.pick.model_dump(), "pick"),
        "destination_pose_base": _pose(transfer.place.model_dump(), "place"),
        "source_approach_z_base_m": transfer.pick_approach_z,
        "destination_approach_z_base_m": transfer.place_approach_z,
        "carry_z_base_m": transfer.carry_z,
    })


class OMXAnalyticTransferPlanner(TransferPlanner):
    """Adapt grant-bound cell geometry to the existing OMX analytic IK planner."""

    def __init__(
        self,
        grant: FleetCellTransferGrant,
        *,
        profile: CellPlanningProfile,
        planner: CellTransferPlanProvider,
        execution_state: Callable[[], ExecutionStateSnapshot],
        accepted_item_geometry: Callable[[str, str], Mapping[str, float] | None],
    ) -> None:
        from core_common.protocol.schemas import FleetCellTransferGrant
        from omx_adapter.pose_plan import CellPlanningProfile

        if not isinstance(grant, FleetCellTransferGrant):
            raise ValueError("a validated CELL_TRANSFER Fleet grant is required")
        if not isinstance(profile, CellPlanningProfile):
            raise ValueError("an accepted OMX CellPlanningProfile is required")
        if not callable(getattr(planner, "plan_transfer", None)):
            raise ValueError("an OMX CellTransferPlanProvider is required")
        if not callable(execution_state) or not callable(accepted_item_geometry):
            raise ValueError("execution state and accepted recipe geometry providers are required")
        self.grant = grant
        self.profile = profile
        self.planner = planner
        self.execution_state = execution_state
        self.accepted_item_geometry = accepted_item_geometry

    def plan(self, invocation: SkillInvocation) -> CellTransferPlan:
        from omx_adapter.kinematics import TopDownPose
        from omx_adapter.pose_plan import CellTransferRequest

        if invocation != cell_transfer_invocation(self.grant):
            raise ValueError("Skill invocation does not match the Fleet CELL_TRANSFER grant")
        transfer = self.grant.cell_transfer
        geometry = self.accepted_item_geometry(transfer.recipe_sha256, transfer.item)
        if not isinstance(geometry, Mapping):
            raise ValueError("accepted recipe geometry is unavailable for this item")
        try:
            width = geometry["grasp_width_m"]
            depth = geometry["grasp_depth_m"]
            height = geometry["height_m"]
        except KeyError as exc:
            raise ValueError("accepted recipe geometry is incomplete") from exc
        if (isinstance(height, bool) or not isinstance(height, (int, float))
                or not math.isfinite(height) or height <= 0):
            raise ValueError("accepted recipe item height must be positive and finite")
        request = CellTransferRequest(
            job_id=transfer.job_id,
            recipe_sha256=transfer.recipe_sha256,
            cell_sha256=transfer.cell_sha256,
            step_index=transfer.step_index,
            item=transfer.item,
            home=TopDownPose(**transfer.home.model_dump()),
            pick=TopDownPose(**transfer.pick.model_dump()),
            place=TopDownPose(**transfer.place.model_dump()),
            pick_approach_z=transfer.pick_approach_z,
            place_approach_z=transfer.place_approach_z,
            carry_z=transfer.carry_z,
            grasp_depth_m=depth,
            grasp_width_m=width,
        )
        return self.planner.plan_transfer(request, self.profile, self.execution_state())


class _SkillPhaseExecution:
    """ActionRunner protocol wrapper; cancellation stays on the OMX goal owner."""

    def __init__(self, skill: TransferSkill, planned: PlannedTransfer,
                 executor: _PhaseExecutor) -> None:
        self.skill = skill
        self.planned = planned
        self.executor = executor

    @property
    def active_phase_id(self) -> str | None:
        return self.executor.active_phase_id

    def start(self) -> object:
        return self.skill.start(self.planned, self.executor)

    def cancel_current(self) -> Mapping[str, object]:
        return self.executor.cancel_current()

    def advance(self) -> object:
        """Advance one locally gated phase; no implicit retry or ROS dispatch loop."""
        return self.executor.advance()


def create_cell_transfer_phase_factory(
    *,
    skill: TransferSkill,
    planner_for_grant: Callable[[FleetCellTransferGrant], TransferPlanner],
    executor_for_grant: Callable[
        [FleetCellTransferGrant, object, PlannedTransfer], _PickPlaceRunner
    ],
) -> Callable[[FleetCellTransferGrant, object], _SkillPhaseExecution]:
    """Create ActionRunner's CELL_TRANSFER phase factory from local OMX ports."""
    if not isinstance(skill, TransferSkill):
        raise ValueError("a TransferSkill instance is required")
    if not callable(planner_for_grant) or not callable(executor_for_grant):
        raise ValueError("grant-bound planner and phase executor factories are required")

    def create(grant: FleetCellTransferGrant, recorder: object) -> _SkillPhaseExecution:
        invocation = cell_transfer_invocation(grant)
        planned = skill.plan(invocation, planner_for_grant(grant))
        runner = executor_for_grant(grant, recorder, planned)
        executor = OMXPickPlaceExecutor(runner, planned)
        return _SkillPhaseExecution(skill, planned, executor)

    return create


def create_omx_cell_transfer_phase_factory(
    *,
    profile: CellPlanningProfile,
    planner: CellTransferPlanProvider,
    execution_state: Callable[[], ExecutionStateSnapshot],
    accepted_item_geometry: Callable[[str, str], Mapping[str, float] | None],
    command_for_phase: Callable[[FleetCellTransferGrant, PlannedMotionPhase], TrajectoryCommand],
    goal_port: PhaseGoalPort,
    submission_fence: StopFence,
    phase_gate: Callable[[FleetCellTransferGrant, str], bool],
    current_fence: Callable[[int, int], bool],
    gripper_readback: Callable[[], GripperObservation],
    monotonic: Callable[[], float],
    now: Callable[[], datetime] | None = None,
    gripper_sensor_revision: str | None = None,
) -> Callable[[FleetCellTransferGrant, object], _SkillPhaseExecution]:
    """Compose the Skill with the actual OMX planner and phase coordinator.

    The caller supplies the existing owner's command and goal ports. This
    factory creates neither a ROS node nor another command owner. Local workflow
    code must explicitly advance phases. An accepted gripper_sensor_revision
    opts into durable hold/release verification and local Action terminalization;
    without it the caller retains responsibility for terminal workflow evidence.
    """
    from omx_adapter.pick_place_runner import PickPlaceRunner

    def planner_for_grant(grant: FleetCellTransferGrant) -> OMXAnalyticTransferPlanner:
        return OMXAnalyticTransferPlanner(
            grant, profile=profile, planner=planner, execution_state=execution_state,
            accepted_item_geometry=accepted_item_geometry,
        )

    def executor_for_grant(grant: FleetCellTransferGrant, recorder: object,
                           planned: PlannedTransfer, workflow=None, readback=None) -> PickPlaceRunner:
        return PickPlaceRunner(
            recorder, grant, planned.plan,
            command_for_phase=lambda phase: command_for_phase(grant, phase),
            goal_port=goal_port, submission_fence=submission_fence,
            phase_gate=lambda phase: phase_gate(grant, phase) and (
                workflow is None or workflow.phase_gate(phase)), current_fence=current_fence,
            current_execution_state=execution_state,
            start_state_tolerances=profile.start_state_tolerances(),
            max_joint_state_age_s=profile.max_joint_state_age_s,
            monotonic=monotonic, now=now, cell_profile=profile,
            gripper_readback=readback or gripper_readback, held_object_id=grant.cell_transfer.item,
        )

    phase_factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(), planner_for_grant=planner_for_grant,
        executor_for_grant=executor_for_grant,
    )
    if gripper_sensor_revision is None:
        return phase_factory

    from omx_adapter.pick_place_transaction import PickPlaceTransaction, PickPlaceWorkflowJournal
    from .cell_workflow import CellTransferWorkflowExecution

    if (not isinstance(gripper_sensor_revision, str) or not gripper_sensor_revision
            or gripper_sensor_revision != gripper_sensor_revision.strip()):
        raise ValueError("an accepted gripper sensor revision is required")

    def create_workflow(grant, recorder):
        if recorder.phases() or recorder.latest_workflow_state() is not None:
            raise RuntimeError("automatic replay of an existing Cell workflow is forbidden")
        workflow = PickPlaceWorkflowJournal(PickPlaceTransaction.for_cell_transfer(
            grant, gripper_sensor_revision=gripper_sensor_revision,
        ), recorder)

        def scoped_readback():
            from omx_adapter.gripper_contract import GripperObservation
            observation = gripper_readback()
            if (not isinstance(observation, GripperObservation)
                    or observation.workcell_id != grant.workcell_id
                    or observation.instance_id != grant.instance_id
                    or observation.sensor_revision != gripper_sensor_revision
                    or observation.owner_generation != grant.dispatch_generation):
                raise ValueError("gripper readback does not match the accepted Cell scope")
            return observation

        create_phase = create_cell_transfer_phase_factory(
            skill=TransferSkill(), planner_for_grant=planner_for_grant,
            executor_for_grant=lambda accepted, journal, planned: executor_for_grant(
                accepted, journal, planned, workflow, scoped_readback),
        )
        execution = create_phase(grant, recorder)

        def complete_if_current(operation):
            return submission_fence.run_if_open(
                authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
                fleet_fence_current=lambda: current_fence(grant.authority_epoch, grant.dispatch_generation),
                operation=operation)

        return CellTransferWorkflowExecution(
            execution, workflow, recorder, gripper_readback=scoped_readback,
            max_age_s=profile.max_joint_state_age_s, monotonic=monotonic, now=now,
            complete_if_current=complete_if_current,
        )

    return create_workflow
