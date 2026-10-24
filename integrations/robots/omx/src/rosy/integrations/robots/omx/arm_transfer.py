"""Installed physical transfer execution through the existing OMX owner ports."""
from dataclasses import dataclass
import math

from pydantic import TypeAdapter

from core_common.protocol.arm_transfer import ArmRevision
from core_common.protocol.arm_transfer_preflight import ArmDigest, ArmPhysicalRef
from core_common.protocol.schemas import FleetArmTransferGrant
from omx_adapter.gripper_contract import GripperObservation
from omx_adapter.kinematics import OmxKinematics
from omx_adapter.manipulation_plan import ExecutionStateSnapshot
from omx_adapter.installed_transfer_factory import InstalledArmTransferFactory
from omx_adapter.managed_transfer_port import _ManagedTransferPort
from omx_adapter.phase_gate import PHASE_WAIT
from omx_adapter.pick_place_runner import PickPlaceRunner
from omx_adapter.pick_place_transaction import PickPlaceTransaction, PickPlaceWorkflowJournal
from omx_adapter.transfer_motion import ArmPlanningProfile, TransferMotionRequest, validate_transfer_motion_plan
from omx_adapter.transfer_object_bindings import TransferObjectBindings
from omx_adapter.transfer_planner import AnalyticTransferPlanner

from .cell_workflow import CellTransferWorkflowExecution


@dataclass(frozen=True)
class ArmTransferInstallation:
    bindings: TransferObjectBindings
    capability_revision: str
    config_revision: str
    resource_policy_digest: str

    def __post_init__(self):
        if not isinstance(self.bindings, TransferObjectBindings):
            raise ValueError("installed physical object bindings are required")
        for name in ("capability_revision", "config_revision"):
            TypeAdapter(ArmRevision).validate_python(getattr(self, name))
        TypeAdapter(ArmDigest).validate_python(self.resource_policy_digest)

    def geometry(self, grant):
        if not isinstance(grant, FleetArmTransferGrant):
            raise ValueError("a neutral arm transfer grant is required")
        catalog, body = self.bindings.catalog, grant.arm_transfer
        if ((grant.workcell_id, grant.instance_id) != (catalog.workcell_id, catalog.instance_id)
                or grant.capability_revision != self.capability_revision
                or grant.config_revision != self.config_revision
                or body.resource_policy_digest != self.resource_policy_digest
                or body.source not in catalog.poses or body.target not in catalog.poses):
            raise ValueError("grant does not match the installed transfer capability")
        return self.bindings.resolve(body.object_ref, catalog_digest=body.catalog_digest,
                                     bindings_digest=body.bindings_digest)

    def capability_current(self, grant):
        try:
            self.geometry(grant)
            return True
        except (TypeError, ValueError):
            return False


def create_arm_transfer_phase_factory(*, installation, profile, kinematics, execution_state,
                                      command_for_phase, goal_port, submission_fence, phase_gate,
                                      current_fence, gripper_readback, gripper_sensor_revision,
                                      monotonic, now=None, control_admission=None):
    """No node, driver or loop is created; the caller supplies admitted owner ports."""
    if (not isinstance(installation, ArmTransferInstallation) or not isinstance(profile, ArmPlanningProfile)
            or not isinstance(kinematics, OmxKinematics)):
        raise ValueError("installed capability, planning profile and device kinematics are required")
    catalog = installation.bindings.catalog
    if (catalog.profile_revision != profile.revision or catalog.kinematics_revision != kinematics.revision
            or profile.kinematics_revision != kinematics.revision
            or catalog.planning_scene_revision != kinematics.planning_scene_revision):
        raise ValueError("catalog, profile and kinematics must share installed revisions")
    TypeAdapter(ArmPhysicalRef).validate_python(gripper_sensor_revision)
    if any(not callable(port) for port in (execution_state, command_for_phase, phase_gate,
                                           current_fence, gripper_readback, monotonic)):
        raise ValueError("owner state, clock, gripper and phase ports are required")

    def clock():
        value = monotonic()
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("owner monotonic clock is invalid")
        return float(value)

    planner = AnalyticTransferPlanner(kinematics, monotonic=clock)

    def validate_state(state, timestamp):
        if (not isinstance(state, ExecutionStateSnapshot)
                or not 0 <= timestamp - state.observed_at_monotonic_s <= profile.max_joint_state_age_s
                or state.calibration_revision != catalog.calibration_revision
                or state.transform_revision != catalog.transform_revision
                or state.planning_scene_revision != catalog.planning_scene_revision):
            raise ValueError("measured owner state or installed revisions changed")

    def create(grant, recorder):
        geometry = installation.geometry(grant)
        if recorder.phases() or recorder.latest_workflow_state() is not None:
            raise RuntimeError("automatic replay of an existing neutral workflow is forbidden")
        state, started = execution_state(), clock()
        validate_state(state, started)
        pick, place = catalog.poses[grant.arm_transfer.source], catalog.poses[grant.arm_transfer.target]
        request = TransferMotionRequest(catalog.home, pick.pose, place.pose,
                                        pick.approach_z, place.approach_z, catalog.carry_z)
        plan = planner.plan_transfer(request, profile, state, geometry=geometry)
        checked = clock()
        if not started <= plan.planned_at_monotonic_s <= checked:
            raise ValueError("owner monotonic clock moved backwards")
        validate_state(state, checked)
        validate_transfer_motion_plan(plan, profile, kinematics_revision=kinematics.revision,
                                      now_monotonic_s=checked)
        workflow = PickPlaceWorkflowJournal(PickPlaceTransaction.for_arm_transfer(
            grant, gripper_sensor_revision=gripper_sensor_revision), recorder)

        def readback():
            observation = gripper_readback()
            if (not isinstance(observation, GripperObservation)
                    or observation.workcell_id != grant.workcell_id or observation.instance_id != grant.instance_id
                    or observation.sensor_revision != gripper_sensor_revision
                    or observation.owner_generation != grant.dispatch_generation):
                raise ValueError("gripper observation does not match the installed owner")
            return observation

        def gate(phase):
            try:
                installation.geometry(grant)
                validate_state(execution_state(), clock())
                if workflow.phase_gate(phase) is not True:
                    return False
                decision = phase_gate(grant, phase)
                if decision is True or decision is PHASE_WAIT:
                    return decision
                workflow.cancel(reason="ARM_TRANSFER_PHASE_DENIED")
                return False
            except Exception:
                workflow.cancel(reason="ARM_TRANSFER_STATE_UNAVAILABLE")
                raise

        admitted_port = (goal_port if control_admission is None else
                         _ManagedTransferPort(control_admission, goal_port, grant, recorder))
        execution = PickPlaceRunner(
            recorder, grant, plan, command_for_phase=lambda phase: command_for_phase(grant, phase),
            goal_port=admitted_port, submission_fence=submission_fence, phase_gate=gate,
            current_fence=current_fence, current_execution_state=execution_state,
            start_state_tolerances=profile.start_state_tolerances(),
            max_joint_state_age_s=profile.max_joint_state_age_s,
            monotonic=clock, now=now, cell_profile=profile, gripper_readback=readback,
            held_object_id=grant.arm_transfer.object_ref)
        if control_admission is not None:
            admitted_port.bind_executor(execution)

        def complete_if_current(operation):
            try:
                installation.geometry(grant)
                validate_state(execution_state(), clock())
                return submission_fence.run_if_open(
                    authority_epoch=grant.authority_epoch, dispatch_generation=grant.dispatch_generation,
                    fleet_fence_current=lambda: current_fence(grant.authority_epoch, grant.dispatch_generation),
                    operation=operation)
            except Exception:
                workflow.cancel(reason="ARM_TRANSFER_COMPLETION_UNCONFIRMED")
                raise

        return CellTransferWorkflowExecution(execution, workflow, recorder, gripper_readback=readback,
                                             max_age_s=profile.max_joint_state_age_s, monotonic=clock,
                                             complete_if_current=complete_if_current, now=now)

    if control_admission is None:
        return create
    return InstalledArmTransferFactory(create, installation.bindings, installation.capability_revision,
        installation.config_revision, installation.resource_policy_digest, control_admission, goal_port)
