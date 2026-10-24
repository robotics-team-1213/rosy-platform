"""One OMX cell owner per workcell in simulation (D-403 §8, D-404 §6, D-336).

``build_cell_owner`` assembles, in one process: one ``ArmCommandOwner`` (inside the injected ROS
runtime, ``allowed_owners=("pilot_sim", "rule_based")``), one SQLite journal holding the Action
store, the local stop latch and the accepted cell/recipe store, the CELL_TRANSFER phase factory
(transfer Skill + analytic planner + PickPlaceRunner), the D-336 ``ActionApi``/``UnixActionServer``
and the D-404 HTTP app from the same runtime. Only the UDS path uses the acceptance store today:
the HTTP app is the unchanged Pilot simulation app and has no /cell routes, so it does not yet
share accepted documents with UDS; seat and Action admission share one in-process coordinator.

ROS is injected (``runtime_factory``, ``goal_port_factory``) so this composition stays rclpy-free
and host-testable; ``deploy/robot/omx/run_cell_owner.py`` supplies the real runtime. Before any
runtime exists the injected ``refuse_second_owner`` guard refuses to start next to another arm
owner (Pilot simulation server or the C3 probe; D-390 §3, D-282 §3).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
import logging
import threading
from pathlib import Path
from typing import Any

from core_common.protocol.schemas import StopRequestSource
from omx_adapter.action_api import ActionApi, LocalStopApi, UnixActionServer
from omx_adapter.action_runner import ActionRunner
from omx_adapter.action_store import ActionStore
from omx_adapter.cell_acceptance import CellAcceptanceStore
from omx_adapter.command_owner import TrajectoryCommand
from omx_adapter.control_seat_admission import ControlSeatAdmission
from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.journal_identity import journal_identity
from omx_adapter.kinematics import OmxKinematics
from omx_adapter.local_stop import LocalStopController
from omx_adapter.owner_recovery_api import OwnerRecoveryApi
from omx_adapter.manipulation_plan import ExecutionStateSnapshot
from omx_adapter.pose_plan import AnalyticCellTransferPlanner, CellPlanningProfile
from rosy.integrations.robots.omx.transfer_provider import create_omx_cell_transfer_phase_factory

from .barrier_journal import BarrierJournal
from .barrier_supervisor import BarrierSupervisor, make_coordinator_hold
from .coordinator_api import CoordinatorPeerApi
from .omx_cell_documents import PalletizingCellDocumentValidator

ALLOWED_OWNERS = ("pilot_sim", "rule_based")
GRIPPER_SENSOR_REVISION = "omx-sim-gripper-joint-position-v2"
_LOG = logging.getLogger(__name__)


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
    # D-780 1, 4: a two-arm workcell names its coordinator UIDs; a one-arm workcell leaves them empty.
    coordinator_peer_uids: frozenset[int] = frozenset()
    coordinator_liveness_s: float = 2.0


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
    _executions: dict = field(default_factory=dict, repr=False)
    _execution_lock: Any = field(default_factory=threading.RLock, repr=False)
    barriers: Any = None  # BarrierSupervisor only with coordinator peers (D-780)

    def advance_pending(self) -> None:
        """One local workflow tick; only live in-memory attempts may progress."""
        with self._execution_lock:
            pending = tuple(self._executions.items())
        for action_id, (grant, execution) in pending:
            action = self.store.get_action(action_id)
            if action is None or action["state"] in {"SUCCEEDED", "FAILED", "CANCELED", "HOLD", "UNKNOWN"}:
                with self._execution_lock:
                    self._executions.pop(action_id, None)
                continue
            start_first = False
            if self.barriers is not None:
                try:
                    ended = self.barriers.tick(grant) is not None  # barrier timeout or coordinator loss
                except Exception:
                    _LOG.exception("Barrier supervision failed for %s; not advancing it", action_id)
                    continue
                if ended:
                    with self._execution_lock:
                        self._executions.pop(action_id, None)
                    continue
                # The before-first-phase barrier was released: submit the first phase now.
                start_first = action["state"] == "SUBMITTING" and self.barriers.first_phase_released(grant)
            if action["state"] == "SUBMITTING" and not start_first:
                continue
            try:
                self.stop.run_if_open(
                    authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
                    fleet_fence_current=lambda: self.runner.current_fence(
                        grant.authority_epoch, grant.dispatch_generation), operation=lambda: None)
                # Phase submission retains its own final fence; never hold the stop lock
                # while workflow progression can wait on a ROS callback's event lock.
                execution.start() if start_first else execution.advance()
            except Exception:
                _LOG.exception("Cell workflow advancement failed for %s", action_id)
                if start_first:  # a released first phase that failed to start is never left SUBMITTING
                    try:
                        self.store.hold_action(action_id, grant.attempt_id, reason="PHASE_RUNNER_START_UNKNOWN")
                    except Exception:
                        _LOG.exception("Cell first-phase hold failed for %s", action_id)
                try:
                    execution.cancel_current()
                except Exception:
                    _LOG.exception("Cell exact-goal cancellation failed for %s", action_id)
                with self._execution_lock:
                    self._executions.pop(action_id, None)
                continue
            action = self.store.get_action(action_id)
            if action is None or action["state"] in {"SUCCEEDED", "FAILED", "CANCELED", "HOLD", "UNKNOWN"}:
                with self._execution_lock:
                    self._executions.pop(action_id, None)


def build_cell_owner(settings: CellOwnerSettings, *,
                     runtime_factory: Callable[[Any], Any],
                     goal_port_factory: Callable[[Any], Any],
                     http_app_factory: Callable[[Any], Any],
                     refuse_second_owner: Callable[[], None],
                     gripper_readback: Callable[[Any], Any],
                     fleet_fence_current: Callable[[int, int], bool],
                     transfer_catalog=None) -> CellOwner:
    refuse_second_owner()
    kinematics = OmxKinematics.load()
    profile = CellPlanningProfile.load(settings.profile_path)
    if profile.kinematics_revision != kinematics.revision:
        raise RuntimeError("cell planning profile was reviewed against other kinematics")
    runtime = runtime_factory(profile.arm_command_config(
        workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        calibration_revision=settings.calibration_revision, allowed_owners=ALLOWED_OWNERS))

    store = ActionStore(settings.journal_path)
    admission = ControlSeatAdmission(runtime.owner, store)
    runtime.owner.bind_control_admission(admission)
    runtime.control_admission = admission
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
        if not stop.is_open(authority_epoch=epoch, dispatch_generation=generation):
            return False
        try:
            return fleet_fence_current(epoch, generation) is True
        except Exception:
            _LOG.exception("Fleet fence readback is unavailable")
            return False

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

    def command_for_phase(grant, phase) -> TrajectoryCommand:
        return TrajectoryCommand(
            workcell_id=settings.workcell_id, instance_id=settings.instance_id,
            command_id=f"{grant.action_id}-{phase.phase_id}", session_id=runtime.owner.session_id,
            owner="rule_based", positions=dict(zip(phase.joint_names, phase.points[-1].positions)),
            duration_s=phase.points[-1].time_from_start_s,
            source_state_sequence=phase.source_state_sequence,
            calibration_revision=settings.calibration_revision, joint_names=phase.joint_names,
            trajectory_points=phase.points, phase_id=phase.phase_id)

    executions, execution_lock = {}, threading.RLock()
    fleet_uid = settings.fleet_peer_uid
    barriers = coordinator_api = None
    if settings.coordinator_peer_uids:
        barriers, coordinator_api = _build_coordination(
            settings, store, stop, current_fence,
            cancel_active=lambda: cancel_active(fleet_uid))
    if barriers is None:
        # One-arm owner: today's always-allow gate. ActionApi already refuses pair/barrier grants
        # (BARRIERS_UNSUPPORTED) before journaling; this deny is defense in depth.
        def phase_gate(accepted, phase):
            return not accepted.cell_transfer.barriers
    else:
        phase_gate = barriers.phase_gate

    def phase_factory(grant, recorder):
        factory = create_omx_cell_transfer_phase_factory(
            profile=profile, planner=planner, execution_state=execution_state,
            accepted_item_geometry=acceptance.accepted_item_geometry,
            command_for_phase=command_for_phase, goal_port=goal_port_factory(runtime),
            submission_fence=stop, phase_gate=phase_gate,
            current_fence=current_fence, gripper_readback=lambda: gripper_readback(grant),
            monotonic=runtime.monotonic, gripper_sensor_revision=GRIPPER_SENSOR_REVISION)
        execution = factory(grant, recorder)
        with execution_lock:
            executions[grant.action_id] = (grant, execution)
        return execution
    runner = ActionRunner(
        store, _NoDirectDriver(), workcell_id=settings.workcell_id, instance_id=settings.instance_id,
        principal_for_peer=lambda uid: f"fleet-uid-{uid}", allowed_peer_uids={settings.fleet_peer_uid},
        current_fence=current_fence, capability_current=acceptance.capability_current,
        submission_fence=stop, phase_runner_factories={"CELL_TRANSFER": phase_factory},
        control_admission=admission, enabled=True)
    sources = {settings.fleet_peer_uid: StopRequestSource.FLEET}
    sources.update({uid: StopRequestSource.COORDINATOR for uid in settings.coordinator_peer_uids})
    # A coordinator stop cancels the Fleet principal's Actions; the Fleet path is unchanged.
    def cancel_active(uid):
        if barriers is not None:
            # A wait at a barrier has no goal to cancel: end it first, with its own reason (D-780 3).
            # A failing sweep never skips the goal cancel fanout below, and vice versa.
            try:
                barriers.end_fenced_waits()
            except Exception:
                _LOG.exception("Barrier wait sweep failed after a local stop")
        return runner.cancel_unresolved(
            peer_uid=fleet_uid if uid in settings.coordinator_peer_uids else uid)
    stop_api = LocalStopApi(stop, source_by_peer_uid=sources, cancel_active=cancel_active,
                            fleet_fence_current=fleet_fence_current)
    recovery_api = OwnerRecoveryApi(runtime.owner, stop, store,
                                    allowed_peer_uids={settings.fleet_peer_uid},
                                    current_fence=current_fence,
                                    read_peer_uids=settings.coordinator_peer_uids)
    if coordinator_api is not None:
        coordinator_api.read_receipt = runner.read_receipt
    owner_journal_id = journal_identity(store.path)
    transfer_preflight_api = None
    if transfer_catalog is not None:
        from omx_adapter.transfer_preflight_owner import build_transfer_preflight_api
        transfer_preflight_api = build_transfer_preflight_api(
            runtime, catalog=transfer_catalog, profile=profile, kinematics=kinematics,
            journal_id=owner_journal_id, allowed_peer_uids={settings.fleet_peer_uid})
    action_api = ActionApi(runner, stop_api=stop_api, recovery_api=recovery_api, identity={
        "workcell_id": settings.workcell_id, "instance_id": settings.instance_id,
        "simulation": True, "profile": "omx-cell-sim", "journal_id": owner_journal_id},
        coordinator_api=coordinator_api, transfer_preflight_api=transfer_preflight_api)
    uds_server = UnixActionServer(
        action_api, Path(settings.socket_root) / settings.instance_id / "control.sock")
    return CellOwner(settings, profile, runtime, store, stop, acceptance, planner, runner,
                     action_api, uds_server, http_app_factory(runtime), executions, execution_lock,
                     barriers=barriers)


def _build_coordination(settings: CellOwnerSettings, store: ActionStore, stop: LocalStopController,
                        current_fence: Callable[[int, int], bool], *, cancel_active: Callable[[], object]):
    """Barrier journal, supervisor and coordinator peer API for a two-arm workcell (D-780)."""
    journal = BarrierJournal(store.path)
    supervisor = BarrierSupervisor(
        journal, store, coordinator_liveness_s=settings.coordinator_liveness_s,
        hold_owner=make_coordinator_hold(stop, store, cancel_active=cancel_active), fence_current=current_fence)
    api = CoordinatorPeerApi(
        store, journal, supervisor, workcell_id=settings.workcell_id,
        coordinator_peer_uids=set(settings.coordinator_peer_uids),
        fleet_peer_uids={settings.fleet_peer_uid}, read_receipt=lambda _action_id: None,
        fence_current=current_fence)
    return supervisor, api


def sim_gripper_observation(owner: CellOwner, state: Any, grant: Any) -> GripperObservation:
    """SIM GRIPPER SENSOR (labelled, as in the C3b probe): finger angle against the width of the
    item in the recipe the grant names (1b C2), never another accepted recipe."""
    transfer = grant.cell_transfer
    geometry = owner.acceptance.accepted_item_geometry(transfer.recipe_sha256, transfer.item_key)
    if geometry is None:
        raise RuntimeError("the grant's recipe/item is not accepted on this owner")
    width = geometry["grasp_width_m"]
    close_q = owner.profile.gripper_close_for_width(width)
    threshold = (owner.profile.gripper_contact_for_width(width) - close_q) / 2
    q = state.positions[owner.profile.gripper_joint]
    opened = abs(q - owner.profile.gripper_open) <= owner.profile.start_state_tolerance_rad
    contact_q = owner.profile.gripper_contact_for_width(width)
    present = not opened and close_q + threshold <= q <= contact_q + threshold
    readback_state = "OPEN" if opened else ("CLOSED" if q <= contact_q + threshold else "UNKNOWN")
    return GripperObservation(owner.settings.workcell_id, owner.settings.instance_id,
                              GRIPPER_SENSOR_REVISION, state.sequence, state.received_at,
                              readback_state, present, transfer.item if present else None,
                              grant.dispatch_generation)


class _NoDirectDriver:
    """CELL_TRANSFER runs through its phase runner only (D-402 §3); no direct driver kind exists."""

    def submit(self, grant):
        raise PermissionError("the cell owner has no direct driver path")

    def cancel(self, action):
        return None


__all__ = ["ALLOWED_OWNERS", "CellOwner", "CellOwnerSettings", "build_cell_owner", "sim_gripper_observation"]
