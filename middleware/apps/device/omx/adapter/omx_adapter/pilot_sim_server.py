"""Run the Pilot HTTP server inside an isolated OMX Gazebo container."""

from __future__ import annotations

import os
import hashlib
import re
import secrets
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import rclpy
import uvicorn
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
import yaml

from core_common.protocol.omx_sim import GRIPPER_GOAL_MAX_DURATION_S

from .command_owner import ArmCommandConfig
from .pilot_sim_api import create_pilot_sim_app
from .pilot_sim_runtime import (PilotSimRuntime, sim_admission_limits, urdf_position_limits,
                                urdf_velocity_limits)
from .pilot_sim_capture import PilotSimCapture
from .pilot_sim_camera import PilotSimCamera
from .pose_plan import CellPlanningProfile
from .ros_runtime import RosArmCommandRuntime


def main() -> None:
    if os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST":
        raise RuntimeError("Pilot simulation requires localhost-only ROS discovery")
    if Path("/dev/serial/by-id").exists() or list(Path("/dev").glob("video*")):
        raise RuntimeError("Pilot simulation refuses hardware device grants")
    repo = Path(os.environ.get("ROSY_SIM_REPO", "/repo"))
    revision = os.environ.get("ROSY_SIM_SOURCE_REVISION", "")
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("explicit ROSY_SIM_SOURCE_REVISION is required for demonstration provenance")
    world = repo / "integrations/simulation/gazebo/worlds/omx_pilot_workcell.sdf"
    cell_path = repo / "deploy/robot/omx/sim/cell_profile.yaml"
    cell = CellPlanningProfile.load(cell_path)
    source_hasher = hashlib.sha256()
    for file in sorted((repo / "middleware/apps/device/omx/adapter/omx_adapter").glob("*.py")):
        source_hasher.update(file.name.encode() + b"\0" + file.read_bytes())
    source_hasher.update((repo / "contracts/foundation/core_common/protocol/omx_sim.py").read_bytes())
    source_hasher.update((repo / "contracts/foundation/core_common/protocol/controls.py").read_bytes())
    source_hasher.update(cell_path.read_bytes())
    vendor_revision = yaml.safe_load((repo / "deploy/robot/omx/stack.lock.yaml").read_text())["vendor"]["revision"]
    source = {"source_revision": revision, "source_tree_sha256": source_hasher.hexdigest(),
              "vendor_revision": vendor_revision,
              "world_sha256": hashlib.sha256(world.read_bytes()).hexdigest()}
    record_root = Path(os.environ.get("ROSY_SIM_RECORD_ROOT", "/recordings")).resolve()
    if record_root.is_relative_to(repo.resolve()):
        raise RuntimeError("recordings must be outside the source checkout")
    urdf_limits = urdf_position_limits()
    config = ArmCommandConfig(
        enabled=True, workcell_id="omx_pilot_sim", instance_id="omx_pilot_sim_01",
        joint_names=cell.joint_names,
        # SIM admission = the reviewed nominal cell profile ranges within the vendor URDF (D-411 C).
        # These are not hardware calibration values.
        position_limits=sim_admission_limits(cell.position_limits, urdf_limits),
        allowed_owners=("pilot_sim",), calibration_revision="omx-f-gazebo-only-v1",
        # Gripper goals take up to 2.0 s; OmxSimJog stays <= 1.0 s by schema.
        max_joint_state_age_s=cell.max_joint_state_age_s, max_goal_duration_s=GRIPPER_GOAL_MAX_DURATION_S,
        action_timeout_s=8.0,
    )
    rclpy.init()
    node = Node("rosy_omx_pilot_sim", parameter_overrides=[Parameter("use_sim_time", value=True)])
    facade: PilotSimRuntime | None = None

    def on_event(event):
        if event.kind != "RUNNING_FEEDBACK":
            print(f"OMX Pilot ROS event: {event.kind} command={event.command_id} "
                  f"goal_id_present={bool(event.goal_id)} status={event.status}", flush=True)
        if facade is not None:
            try:
                facade.on_goal_event(event)
            except Exception as exc:
                print(f"OMX Pilot ROS event handler failed: {type(exc).__name__}: {exc}", flush=True)
                raise

    arm = RosArmCommandRuntime(
        node, config, joint_state_topic="/joint_states",
        trajectory_action="/arm_controller/follow_joint_trajectory",
        on_goal_event=on_event,
    )
    # Pilot is offered the admission range above inset by the start-state tolerance (D-411 B, C);
    # gripper goals are paced at the slower of the cell and URDF gripper speeds.
    gripper_velocity = min(cell.velocity_limits[cell.gripper_joint], urdf_velocity_limits()[cell.gripper_joint])
    facade = PilotSimRuntime(arm, gripper=cell.gripper_joint, range_inset_rad=cell.start_state_tolerance_rad,
                             gripper_open=cell.gripper_open, gripper_closed=cell.gripper_closed,
                             gripper_velocity=gripper_velocity, gripper_preload=cell.gripper_preload_rad)
    facade.capture = PilotSimCapture(
        facade, record_root, source, sim_time_ns=lambda: node.get_clock().now().nanoseconds)
    camera = PilotSimCamera(node, facade.capture, source["world_sha256"])
    facade.camera_available = True
    executor = MultiThreadedExecutor(num_threads=3)
    executor.add_node(node)
    spinner = ThreadPoolExecutor(max_workers=1)
    spinner.submit(executor.spin)
    code = secrets.token_urlsafe(12)
    code_file = Path("/run/rosy-omx-pilot/pairing-code")
    code_file.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(code_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(code)
    print("OMX Pilot pairing code is available via the local container CLI", flush=True)
    app = create_pilot_sim_app(
        runtime=facade, pilot_root=repo / "middleware/ui/pilot",
        common_root=repo / "shared/web", pairing_code=code,
    )
    try:
        uvicorn.run(app, host="0.0.0.0", port=8088, access_log=False)
    finally:
        code_file.unlink(missing_ok=True)
        facade.cancel_active()
        executor.shutdown()
        camera.destroy()
        arm.destroy()
        node.destroy_node()
        rclpy.shutdown()
        spinner.shutdown(wait=True)


if __name__ == "__main__":
    main()
