"""Run the single OMX cell owner in the simulation container (D-403 §8, C4b G2b).

One process: the ROS runtime (one ArmCommandOwner), the D-336 UDS socket in a thread and the
Pilot simulation HTTP app on the main thread, assembled by rosy_agent.omx_cell_owner. It refuses
to start beside pilot_sim_server or the C3 probe. Simulation only; not a device entrypoint.
Wave 1 gaps (see C4b logs): the Pilot HTTP app has no /cell routes or seat<->Action exclusion yet
(G9), the Fleet stop chain (G7) still needs live ROS/UDS fault acceptance, while phase
progression uses the existing locally gated Cell workflow.
"""

from __future__ import annotations

import os
import secrets
import sys
import threading
from pathlib import Path

REPO = Path(os.environ.get("ROSY_SIM_REPO", "/repo"))
for _part in ("src/contracts/foundation", "contracts/skill/src", "src/products/omx/adapter", "apps/agent/src",
              "operations/execution/src", "operations/processes/palletizing/src", "modules/skills/api/src",
              "modules/skills/manipulation/src", "integrations/robots/omx/src", "deploy/robot/omx"):
    sys.path.append(str(REPO / _part))

from cell_sim_tools import refuse_second_owner  # noqa: E402

WORKCELL_ID, INSTANCE_ID = "omx_cell_sim", "omx_cell_sim_01"


def main() -> None:
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("the cell owner requires localhost-only ROS discovery")
    if Path("/dev/serial/by-id").exists() or list(Path("/dev").glob("video*")):
        raise RuntimeError("the simulation cell owner refuses hardware device grants")
    fleet_uid = int(os.environ["ROSY_FLEET_PEER_UID"])
    from rosy_agent.fleet_fence import fleet_fence_from_environment
    fleet_fence = fleet_fence_from_environment()
    refuse_second_owner()

    import rclpy
    import uvicorn
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from rclpy.parameter import Parameter

    from omx_adapter.pilot_sim_api import create_pilot_sim_app
    from omx_adapter.pilot_sim_runtime import PilotSimRuntime
    from omx_adapter.ros_runtime import RosArmCommandRuntime, RosArmPhaseGoalPort
    from rosy_agent.omx_cell_owner import CellOwnerSettings, build_cell_owner, sim_gripper_observation

    rclpy.init()
    node = Node("rosy_omx_cell_owner", parameter_overrides=[Parameter("use_sim_time", value=True)])
    holder: dict = {}

    def runtime_factory(config):
        return RosArmCommandRuntime(node, config, joint_state_topic="/joint_states",
                                    trajectory_action="/arm_controller/follow_joint_trajectory",
                                    owner_clock="sim")

    def gripper_readback(grant):
        return sim_gripper_observation(holder["owner"], holder["owner"].runtime.latest_joint_state, grant)

    root = Path(os.environ.get("ROSY_CELL_OWNER_JOURNAL", "/var/lib/rosy-omx-cell"))
    owner = build_cell_owner(
        CellOwnerSettings(WORKCELL_ID, INSTANCE_ID, root / "owner.sqlite3",
                          Path(os.environ.get("ROSY_OMX_SOCKET_ROOT", "/run/rosy/omx")), fleet_uid,
                          REPO / "deploy/robot/omx/sim/cell_profile.yaml", "omx-f-gazebo-only-v1",
                          "gz-world-is-link0-v1", 0.001),
        runtime_factory=runtime_factory, goal_port_factory=RosArmPhaseGoalPort,
        http_app_factory=lambda runtime: create_pilot_sim_app(
            runtime=PilotSimRuntime(runtime), pilot_root=REPO / "src/hmi/pilot",
            common_root=REPO / "src/hmi/web_common", pairing_code=secrets.token_urlsafe(12)),
        refuse_second_owner=lambda: None,  # checked above, before rclpy
        gripper_readback=gripper_readback,
        fleet_fence_current=fleet_fence,
    )
    holder["owner"] = owner
    workflow_timer = node.create_timer(0.05, owner.advance_pending)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    threading.Thread(target=executor.spin, daemon=True).start()
    uds = threading.Thread(target=owner.uds_server.serve_forever, daemon=True)
    uds.start()
    try:
        # Loopback by default: no sim compose/run script publishes this port. Set
        # ROSY_CELL_OWNER_HTTP_HOST only for a container that publishes it deliberately.
        uvicorn.run(owner.http_app, host=os.environ.get("ROSY_CELL_OWNER_HTTP_HOST", "127.0.0.1"),
                    port=8088, access_log=False)
    finally:
        owner.uds_server.stop()
        node.destroy_timer(workflow_timer)
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
