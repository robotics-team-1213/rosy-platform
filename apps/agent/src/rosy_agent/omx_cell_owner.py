"""One OMX cell owner per workcell in simulation (D-403 §8, D-404 §6, D-336).

``build_cell_owner`` assembles, in one process: one ``ArmCommandOwner`` (inside the injected ROS
runtime, ``allowed_owners=("pilot_sim", "rule_based")``), one SQLite journal holding the Action
store, the local stop latch and the accepted cell/recipe store, the CELL_TRANSFER phase factory
(transfer Skill + analytic planner + PickPlaceRunner), the D-336 ``ActionApi``/``UnixActionServer``
and the D-404 HTTP app. The HTTP API and the UDS socket see the same acceptance store.

ROS is injected (``runtime_factory``, ``goal_port_factory``) so this composition stays rclpy-free
and host-testable; ``deploy/robot/omx/run_cell_owner.py`` supplies the real runtime. Before any
runtime exists the injected ``refuse_second_owner`` guard refuses to start next to another arm
owner (Pilot simulation server or the C3 probe; D-390 §3, D-282 §3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core_common.protocol.schemas import StopRequestSource
from omx_adapter.action_api import ActionApi, LocalStopApi, UnixActionServer
from omx_adapter.action_runner import ActionRunner
from omx_adapter.action_store import ActionStore
from omx_adapter.cell_acceptance import CellAcceptanceStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.kinematics import OmxKinematics
from omx_adapter.local_stop import LocalStopController
from omx_adapter.manipulation_plan import ExecutionStateSnapshot
from omx_adapter.pick_place_runner import PickPlaceRunner
from omx_adapter.pose_plan import AnalyticCellTransferPlanner, CellPlanningProfile
from rosy.integrations.robots.omx.transfer_provider import (
    OMXAnalyticTransferPlanner, create_cell_transfer_phase_factory,
)
from rosy.skills.manipulation.transfer import TransferSkill

from .omx_cell_documents import PalletizingCellDocumentValidator

ALLOWED_OWNERS = ("pilot_sim", "rule_based")


@dataclass(frozen=True)
class CellOwnerSettings:
    workcell_id: str
    instance_id: str
    journal_path: Path
    socket_root: Path
    fleet_peer_uid: int
    profile_path: Path
    calibration_revision: str
    transform_revision: str
    stack_tol_m: float


@dataclass
class CellOwner:
    settings: CellOwnerSettings
    profile: CellPlanningProfile
    runtime: Any
    store: ActionStore
    stop: LocalStopController
    acceptance: CellAcceptanceStore
    planner: AnalyticCellTransferPlanner
    runner: ActionRunner
    action_api: ActionApi
    uds_server: UnixActionServer
    http_app: Any


def build_cell_owner(settings: CellOwnerSettings, *,
                     runtime_factory: Callable[[Any], Any],
                     goal_port_factory: Callable[[Any], Any],
                     http_app_factory: Callable[[Any], Any],
                     refuse_second_owner: Callable[[], None],
                     gripper_readback: Callable[[], Any],
                     fleet_fence_current: Callable[[int, int], bool]) -> CellOwner:
    refuse_second_owner()
    kinematics = OmxKinematics.load()
    profile = CellPlanningProfile.load(settings.profile_path)
    if profile.kinematics_revision != kinematics.revision:
        raise RuntimeError("cell planning profile was reviewed against other kinematics")
    runtime = runtime_factory(profile.arm_command_config(
        workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        calibration_revision=settings.calibration_revision, allowed_owners=ALLOWED_OWNERS))

    store = ActionStore(settings.journal_path)
    stop = LocalStopController(store.path, workcell_id=settings.workcell_id,
                               instance_id=settings.instance_id)
    acceptance = CellAcceptanceStore(
        store.path, workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        kinematics_revision=kinematics.revision, config_revision=profile.revision,
        validator=PalletizingCellDocumentValidator(tol_m=settings.stack_tol_m),
        unresolved_actions=lambda: store.unresolved_actions(workcell_id=settings.workcell_id),
    )
    planner = AnalyticCellTransferPlanner(
        kinematics, accepted_cell_sha256=acceptance.accepted_cell_sha256,
        accepted_item_geometry=acceptance.accepted_item_geometry, monotonic=runtime.monotonic)

    def current_fence(epoch: int, generation: int) -> bool:
        return stop.is_open(authority_epoch=epoch, dispatch_generation=generation)

    def execution_state() -> ExecutionStateSnapshot:
        state = runtime.latest_joint_state
        if state is None:
            raise RuntimeError("no joint state from the owner yet")
        return ExecutionStateSnapshot(
            sequence=state.sequence, joint_positions=dict(state.positions),
            calibration_revision=settings.calibration_revision,
            transform_revision=settings.transform_revision,
            planning_scene_revision=kinematics.planning_scene_revision,
            observed_at_monotonic_s=state.received_at)

    def runner_for_grant(grant, recorder, planned) -> PickPlaceRunner:
        def command_for_phase(phase) -> TrajectoryCommand:
            return TrajectoryCommand(
                workcell_id=settings.workcell_id, instance_id=settings.instance_id,
                command_id=f"{grant.action_id}-{phase.phase_id}", session_id=runtime.owner.session_id,
                owner="rule_based", positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
                duration_s=phase.points[-1].time_from_start_s,
                source_state_sequence=phase.source_state_sequence,
                calibration_revision=settings.calibration_revision, joint_names=phase.joint_names,
                trajectory_points=phase.points, phase_id=phase.phase_id)

        return PickPlaceRunner(
            recorder, grant, planned.plan, command_for_phase=command_for_phase,
            goal_port=goal_port_factory(runtime), submission_fence=stop,
            phase_gate=lambda _phase_id: True, current_fence=current_fence,
            current_execution_state=execution_state,
            start_state_tolerances=profile.start_state_tolerances(),
            max_joint_state_age_s=profile.max_joint_state_age_s, monotonic=runtime.monotonic,
            cell_profile=profile, gripper_readback=gripper_readback,
            held_object_id=grant.cell_transfer.item)

    phase_factory = create_cell_transfer_phase_factory(
        skill=TransferSkill(),
        planner_for_grant=lambda grant: OMXAnalyticTransferPlanner(
            grant, profile=profile, planner=planner, execution_state=execution_state,
            accepted_item_geometry=acceptance.accepted_item_geometry),
        executor_for_grant=runner_for_grant)
    runner = ActionRunner(
        store, _NoDirectDriver(), workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={settings.fleet_peer_uid},
        current_fence=current_fence, capability_current=acceptance.capability_current,
        submission_fence=stop, phase_runner_factories={"CELL_TRANSFER": phase_factory}, enabled=True)
    stop_api = LocalStopApi(stop, source_by_peer_uid={settings.fleet_peer_uid: StopRequestSource.FLEET},
                            cancel_active=lambda uid: runner.cancel_unresolved(peer_uid=uid),
                            fleet_fence_current=fleet_fence_current)
    action_api = ActionApi(runner, stop_api=stop_api)
    uds_server = UnixActionServer(
        action_api, Path(settings.socket_root) / settings.instance_id / "control.sock")
    return CellOwner(settings, profile, runtime, store, stop, acceptance, planner, runner,
                     action_api, uds_server, http_app_factory(runtime))


class _NoDirectDriver:
    """CELL_TRANSFER runs through its phase runner only (D-402 §3); no direct driver kind exists."""

    def submit(self, grant):
        raise PermissionError("the cell owner has no direct driver path")

    def cancel(self, action):
        return None


__all__ = ["ALLOWED_OWNERS", "CellOwner", "CellOwnerSettings", "build_cell_owner"]
