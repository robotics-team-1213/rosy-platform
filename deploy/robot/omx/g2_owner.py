"""Canonical fenced owner with explicitly labelled detachable-joint simulation aid."""
import argparse
import json
import os
from pathlib import Path
import secrets
import threading
import time

from g2_common import ROOT, configure_imports
from g2_ports import SimAidGoalPort, isolation_guard, refuse_g2_owner, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    args = parser.parse_args()
    isolation_guard(ROOT)
    configure_imports()
    from cell_sim_tools import refuse_second_owner
    from g2_aid import OneShotSimAid
    refuse_second_owner()
    refuse_g2_owner()
    # Exclusive run lock complements the canonical scan for older owner entrypoints.
    lock = (args.run / "owner.lock").open("x")
    lock.write(str(os.getpid()))
    lock.flush()
    import rclpy
    import uvicorn
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter
    from core_common.protocol.schemas import FleetCellTransferGrant
    from omx_adapter.pilot_sim_api import create_pilot_sim_app
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort
    from omx_adapter.gripper_contract import verify_held_object
    from rosy_agent.omx_cell_owner import CellOwnerSettings, build_cell_owner, sim_gripper_observation
    from rosy_agent.fleet_fence import HttpFleetFenceReadback
    run = args.run.resolve()
    credentials = json.loads((run / "credentials.json").read_text())
    rclpy.init()
    node = Node("rosy_g2_cell_owner", parameter_overrides=[Parameter("use_sim_time", value=True)])
    holder = {}
    aid = OneShotSimAid()
    # Discover entity before receiving any grant, never delay a live attach on gz model lookup.
    aid._robot_entity_id(attempts=1)

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
        verify_held_object(sim_gripper_observation(owner, owner.runtime.latest_joint_state, grant),
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
        return create_pilot_sim_app(runtime=pilot, pilot_root=ROOT / "middleware/ui/pilot",
                                    common_root=ROOT / "shared/web", pairing_code=secrets.token_urlsafe(12))

    def on_goal_event(event):
        pilot = holder.get("pilot")
        if pilot is not None:
            pilot.on_goal_event(event)

    owner = build_cell_owner(CellOwnerSettings(
        "omx_cell_sim", "omx_cell_sim_01", run / "owner.sqlite3", run / "uds", os.getuid(),
        ROOT / "deploy/robot/omx/sim/cell_profile.yaml", "omx-f-gazebo-only-v1",
        "gz-world-is-link0-v1", 0.001),
        runtime_factory=lambda config: RosArmCommandRuntime(node, config,
                                                            joint_state_topic="/joint_states",
                                                            trajectory_action="/arm_controller/follow_joint_trajectory",
                                                            owner_clock="sim", on_goal_event=on_goal_event),
        goal_port_factory=lambda runtime: SimAidGoalPort(RosArmPhaseGoalPort(runtime), before=before),
        http_app_factory=http_app_factory,
        refuse_second_owner=lambda: None,
        gripper_readback=lambda grant: sim_gripper_observation(
            holder["owner"], holder["owner"].runtime.latest_joint_state, grant),
        fleet_fence_current=HttpFleetFenceReadback("http://127.0.0.1:8090/api/fleet/dispatch-control",
                                                   credentials["site"]["viewer"]["token"], timeout_s=0.25))
    holder["owner"] = owner
    accepted_cell = owner.acceptance.accept_cell(json.loads((run / "cell.json").read_text()),
                                                 actor_id="g2-sim-acceptor")
    accepted_recipe = owner.acceptance.accept_recipe(json.loads((run / "recipe.json").read_text()),
                                                     actor_id="g2-sim-acceptor")
    write_json(run / "owner-acceptance.json", {"cell": accepted_cell, "recipe": accepted_recipe})
    timer = None
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    try:
        # No Fleet Action endpoint exists until the reserved startup goal is measured ready.
        from g2_startup import prepare_home
        from omx_adapter.kinematics import ARM_JOINTS, OmxKinematics, TopDownPose
        deadline = time.monotonic()+60.
        while True:
            sample = owner.runtime.latest_joint_state
            if (sample is not None and owner.runtime.action_port.server_is_ready()
                    and owner.runtime.owner.state == "ready"
                    and 0 <= owner.runtime.monotonic()-sample.received_at
                    <= owner.profile.max_joint_state_age_s):
                break
            if time.monotonic() >= deadline:
                raise RuntimeError("SIM startup owner readiness timed out")
            time.sleep(.05)
        home = json.loads((run / "cell.json").read_text())["home"]
        q = OmxKinematics.load().solve_top_down(TopDownPose(**home), owner.profile.ik_limits()).joints
        target = dict(zip(ARM_JOINTS, q))
        target[owner.profile.gripper_joint] = owner.profile.gripper_open
        try:
            write_json(run / "startup-home.json", prepare_home(owner.runtime, owner.profile, target))
        except Exception as exc:
            write_json(run / "startup-home-failure.json", {"result": "HOLD", "error": str(exc),
                                                          "fixture": "SIM_STARTUP_HOME"})
            raise
        timer = node.create_timer(0.05, owner.advance_pending)
        threading.Thread(target=owner.uds_server.serve_forever, daemon=True).start()
        uvicorn.run(owner.http_app, host="127.0.0.1", port=8088, access_log=False)
    finally:
        owner.uds_server.stop()
        if timer is not None:
            node.destroy_timer(timer)
        executor.shutdown(timeout_sec=5)
        node.destroy_node()
        rclpy.shutdown()
        lock.close()


if __name__ == "__main__":
    main()
