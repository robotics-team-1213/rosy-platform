"""Canonical fenced owner with explicitly labelled detachable-joint simulation aid."""
import argparse
import json
import os
from pathlib import Path
import secrets
import threading

from g2_common import ROOT, configure_imports
from g2_diagnostics import TerminalDiagnostics, dispatch_g2_event
from g2_clock import DedicatedSimClock
from g2_gripper_trace import GripperReadbackTrace
from g2_ports import SimAidGoalPort, isolation_guard, refuse_g2_owner, write_json


def create_workflow_timer(node, advance_pending):
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    # Serialize workflow independently of state, watchdog and action callbacks.
    return node.create_timer(0.05, advance_pending, callback_group=MutuallyExclusiveCallbackGroup())


def close_runtime(node, owner, workflow_timer, executor, clock, run, lock, rclpy):
    """Keep clock/context alive when bounded executor shutdown is incomplete."""
    try:
        if owner is not None:
            owner.uds_server.stop()
        if workflow_timer is not None:
            node.destroy_timer(workflow_timer)
        if executor is not None and executor.shutdown(timeout_sec=5, wait_for_threads=False) is not True:
            raise RuntimeError("owner executor did not stop")
        if owner is not None:
            owner.runtime.destroy()
    except Exception as error:
        raise RuntimeError("CLEANUP_HOLD: OWNER_SHUTDOWN_INCOMPLETE") from error
    if clock is not None:
        try:
            clock.persist_terminal(run / "clock-terminal.json", timeout=.5)
        except Exception:
            pass  # Diagnostic persistence cannot gate safe shutdown.
        try:
            stopped = clock.close(timeout=2)
        except Exception as error:
            raise RuntimeError("CLEANUP_HOLD: CLOCK_SHUTDOWN_INCOMPLETE") from error
        if stopped is not True:
            raise RuntimeError("CLEANUP_HOLD: CLOCK_SHUTDOWN_INCOMPLETE")
    node.destroy_node()
    rclpy.shutdown()
    lock.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    isolation_guard(ROOT)
    configure_imports()
    from cell_sim_tools import refuse_second_owner
    from g2_aid import OneShotSimAid
    from instance_names import names_from_environment
    names = names_from_environment()
    refuse_second_owner(namespace=names.namespace)
    refuse_g2_owner()
    # Exclusive run lock complements the canonical scan for older owner entrypoints.
    lock = (args.run / "owner.lock").open("x")
    lock.write(str(os.getpid()))
    lock.flush()
    import rclpy
    from omx_adapter.ros_owner_executor import OwnerMultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from core_common.protocol.schemas import FleetCellTransferGrant
    from omx_adapter.pilot_sim.api import create_pilot_sim_app
    from omx_adapter.pilot_sim.runtime import PilotSimRuntime
    from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort
    from omx_adapter.gripper_contract import verify_held_object
    from rosy_agent.omx_cell_owner import CellOwnerSettings, build_cell_owner, sim_gripper_observation
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    run = args.run.resolve()
    credentials = json.loads((run / "credentials.json").read_text())
    rclpy.init()
    node = Node("rosy_g2_cell_owner", parameter_overrides=[Parameter("use_sim_time", value=True)])
    clock = None
    owner = executor = workflow_timer = diagnostics = gripper_trace = None
    try:
        clock = DedicatedSimClock(node)
        write_json(run / "clock-startup.json", clock.start())
        holder = {}
        diagnostics = TerminalDiagnostics(run / "terminal-diagnostics")
        gripper_trace = GripperReadbackTrace(run / "gripper-readback")
        aid = OneShotSimAid()
        # Discover entity before receiving any grant, never delay a live attach on gz model lookup.
        aid._robot_entity_id(attempts=1)

        def gripper_readback(grant, *, context="workflow"):
            return gripper_trace.read(holder["owner"], grant, sim_gripper_observation, context=context)

        def before(command):
            phase = command.phase_id
            if phase not in {"transfer", "release"}:
                return
            action_id = command.command_id.removesuffix("-"+phase)
            staged = json.loads((run / "staging" / (action_id+".json")).read_text())
            grant = FleetCellTransferGrant.model_validate(staged["grant"])
            owner = holder["owner"]
            action = owner.store.get_action(action_id)
            if action is None or action["attempt_id"] != grant.attempt_id:
                raise RuntimeError("SIM AID requires the actual accepted attempt")
            if owner.store.latest_workflow_state(action_id, grant.attempt_id) != phase.upper():
                raise RuntimeError("SIM AID requires canonical verified-hold progression")
            verify_held_object(gripper_readback(grant, context="before_" + phase),
                               object_id=grant.cell_transfer.item, now=owner.runtime.monotonic(),
                               max_age_s=owner.profile.max_joint_state_age_s)
            # Canonical phase_gate/release readback and final stop/fence lock surround this hook.
            model = "cell_"+action_id
            receipt = aid.attach(model) if phase == "transfer" else aid.detach(model)
            write_json(run / "aid" / (action_id+"-"+phase+".json"),
                       {**receipt, "action_id": action_id, "attempt_id": grant.attempt_id,
                        "sim_aid": True, "sim_gripper_sensor": True})
            if receipt.get("confirmed") is not True or (phase == "transfer"
                                                        and receipt.get("service_ok") is not True):
                raise RuntimeError("SIM AID acknowledgement uncertain; refuse ROS goal")

        def http_app_factory(runtime):
            pilot = PilotSimRuntime(runtime)
            holder["pilot"] = pilot
            return create_pilot_sim_app(runtime=pilot, pilot_root=ROOT / "middleware/robot_ui/pilot",
                                        common_root=ROOT / "shared/web", pairing_code=secrets.token_urlsafe(12))

        def on_goal_event(event):
            dispatch_g2_event(event, holder=holder, diagnostics=diagnostics)

        fleet_fence = HttpFleetFenceReadback("http://127.0.0.1:8090/api/fleet/dispatch-control",
                                            credentials["site"]["viewer"]["token"], timeout_s=0.25)
        owner = build_cell_owner(CellOwnerSettings(
            "omx_cell_sim", "omx_cell_sim_01", run / "owner.sqlite3", run / "uds", os.getuid(),
            ROOT / "deploy/robot/omx/sim/cell_profile.yaml", "omx-f-gazebo-only-v1",
            "gz-world-is-link0-v1", 0.001),
            runtime_factory=lambda config: RosArmCommandRuntime(node, config,
                                                                joint_state_topic=names.joint_state_topic,
                                                                trajectory_action=names.trajectory_action,
                                                                owner_clock="sim", on_goal_event=on_goal_event),
            goal_port_factory=lambda runtime: SimAidGoalPort(RosArmPhaseGoalPort(runtime), before=before),
            http_app_factory=http_app_factory,
            refuse_second_owner=lambda: None,
            gripper_readback=gripper_readback,
            fleet_fence_current=fleet_fence)
        holder["owner"] = owner
        accepted_cell = owner.acceptance.accept_cell(json.loads((run / "cell.json").read_text()),
                                                     actor_id="g2-sim-acceptor")
        accepted_recipe = owner.acceptance.accept_recipe(json.loads((run / "recipe.json").read_text()),
                                                         actor_id="g2-sim-acceptor")
        gripper_trace.bind_recipe(accepted_recipe)
        write_json(run / "owner-acceptance.json", {"cell": accepted_cell, "recipe": accepted_recipe})
        from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
        home = json.loads((run / "cell.json").read_text())["home"]
        solution = OmxKinematics.load().solve_top_down(TopDownPose(**home), owner.profile.ik_limits())
        if not solution.ok:
            raise RuntimeError("simulation startup home is outside the reviewed IK profile")
        target = dict(zip(ARM_JOINTS, solution.joints))
        target[owner.profile.gripper_joint] = owner.profile.gripper_open
        # Reuse the canonical composition's workflow tick; callbacks alone do not advance phases.
        workflow_timer = create_workflow_timer(node, owner.advance_pending)
        # Clock has its own executor; these slots serve state, watchdog, action and workflow.
        executor = OwnerMultiThreadedExecutor(num_threads=4)
        executor.add_node(node)
        threading.Thread(target=executor.spin, daemon=True).start()
        from g2_startup_session import serve_startup
        server = serve_startup(owner, run, target=target,
            expected_actor=credentials["site"]["approver"]["principal_id"], fleet_fence_current=fleet_fence)
        server.join()
    finally:
        try:
            close_runtime(node, owner, workflow_timer, executor, clock, run, lock, rclpy)
        finally:
            if gripper_trace is not None:
                gripper_trace.close(timeout=.5)
            if diagnostics is not None:
                diagnostics.close(timeout=.5)


if __name__ == "__main__":
    main()
