"""Import ROSY into Isaac Sim 5.1/6.x and run the single-robot ROS 2 graph.

Run with Isaac Sim's python.sh, never the system Python. Outputs stay in --output-dir.
"""

import argparse
import os
import time
from pathlib import Path
import xml.etree.ElementTree as ET

from graph_contract import robot_contract
from model_checks import check_urdf
from prepare_urdf import validate_output_path
from importer_compat import import_model, reference_model
import command_watchdog
from drive_runtime import force_zero_wheels


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--urdf", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--namespace", required=True)
    parser.add_argument("--robot-prim", help="Articulation root prim path if auto-discovery is ambiguous")
    parser.add_argument("--chassis-prim", help="base_footprint prim path if auto-discovery is ambiguous")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--frames", type=int, default=0, help="0 runs until interrupted")
    return parser.parse_args()


def main():
    args = parse_args()
    contract = robot_contract(args.namespace)
    expected_domain = 40 + int(args.namespace[-2:])
    if os.environ.get("ROS_DOMAIN_ID") != str(expected_domain):
        raise SystemExit(f"ROS_DOMAIN_ID must be {expected_domain} for {args.namespace}")
    if not args.urdf.is_file():
        raise SystemExit(f"URDF not found: {args.urdf}")
    try:
        check_urdf(args.urdf, "pinky", allow_package=False)
    except (ValueError, OSError, ET.ParseError) as exc:
        raise SystemExit(f"Pinky URDF preflight failed: {exc}") from exc
    if args.frames < 0:
        raise SystemExit("--frames must be zero or positive")

    try:
        output_dir = validate_output_path(args.output_dir / "rosy.usd").parent
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    output_dir.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    # Kit's default immediate exit(0) would hide exceptions raised below.
    simulation_app = SimulationApp({"headless": args.headless, "fast_shutdown": False})
    guard = None
    wheel_drives = []
    watchdog_ready = False
    try:
        import omni.graph.core as og
        import omni.kit.app
        import omni.kit.commands
        import omni.timeline
        import omni.usd
        from pxr import Gf, PhysicsSchemaTools, Sdf, Usd, UsdGeom, UsdPhysics

        manager = omni.kit.app.get_app().get_extension_manager()
        for name in ("isaacsim.asset.importer.urdf", "isaacsim.ros2.bridge", "omni.graph.scriptnode",
                     "isaacsim.core.nodes", "isaacsim.robot.wheeled_robots"):
            manager.set_extension_enabled_immediate(name, True)
        import isaacsim.asset.importer.urdf as urdf_api

        # 5.1 ships these ROS nodes inside the bridge; 6.x splits the extension.
        if hasattr(urdf_api, "URDFImporter"):
            manager.set_extension_enabled_immediate("isaacsim.ros2.nodes", True)
        usd_path = import_model(urdf_api, omni.kit.commands.execute, args.urdf, output_dir, "Wheeled")
        reference_model(omni.usd.get_context(), usd_path, Usd, UsdGeom)
        simulation_app.update()
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            raise RuntimeError("Isaac Sim did not open the imported USD stage")

        def find_prim(name, explicit=None, api=None):
            if explicit:
                prim = stage.GetPrimAtPath(explicit)
                if not prim.IsValid():
                    raise RuntimeError(f"USD prim not found: {explicit}")
                return explicit
            matches = [str(prim.GetPath()) for prim in stage.Traverse()
                       if (prim.HasAPI(api) if api else prim.GetName() == name)]
            if len(matches) != 1:
                raise RuntimeError(f"Expected one {name} prim, found {matches}; pass its prim path explicitly")
            return matches[0]

        robot_prim = find_prim("articulation root", args.robot_prim, UsdPhysics.ArticulationRootAPI)
        chassis_prim = find_prim("base_footprint", args.chassis_prim)
        wheel_drives = []
        for joint_name in contract["wheel_joints"]:
            joint = stage.GetPrimAtPath(find_prim(joint_name))
            if not joint.IsA(UsdPhysics.RevoluteJoint):
                raise RuntimeError(f"Wheel is not a revolute joint: {joint_name}")
            drive = UsdPhysics.DriveAPI.Apply(joint, "angular")
            drive.CreateStiffnessAttr(0.0)
            damping = drive.GetDampingAttr().Get()
            if damping is None or damping <= 0:
                drive.CreateDampingAttr(1.0)
            drive.CreateTargetVelocityAttr(0.0)
            wheel_drives.append(drive)
        guard = command_watchdog.CommandWatchdog()
        command_watchdog.ACTIVE_WATCHDOG = guard

        if not stage.GetPrimAtPath("/World").IsValid():
            UsdGeom.Xform.Define(stage, Sdf.Path("/World"))
        if not any(prim.IsA(UsdPhysics.Scene) for prim in stage.Traverse()):
            UsdPhysics.Scene.Define(stage, Sdf.Path("/World/physicsScene"))
        PhysicsSchemaTools.addGroundPlane(stage, "/World/groundPlane", "Z", 1500,
                                          Gf.Vec3f(0, 0, 0), Gf.Vec3f(0.5))

        keys = og.Controller.Keys
        ns = contract["namespace"]
        og.Controller.edit(
            {"graph_path": "/World/ROSYDrive", "evaluator_name": "execution"},
            {
                keys.CREATE_NODES: [
                    ("Tick", "omni.graph.action.OnPlaybackTick"),
                    ("Context", "isaacsim.ros2.bridge.ROS2Context"),
                    ("Twist", "isaacsim.ros2.bridge.ROS2SubscribeTwist"),
                    ("Linear", "omni.graph.nodes.BreakVector3"),
                    ("Angular", "omni.graph.nodes.BreakVector3"),
                    ("Diff", "isaacsim.robot.wheeled_robots.DifferentialController"),
                    ("Receipt", "omni.graph.scriptnode.ScriptNode"),
                    ("Gate", "omni.graph.scriptnode.ScriptNode"),
                    ("Articulation", "isaacsim.core.nodes.IsaacArticulationController"),
                ],
                keys.SET_VALUES: [
                    ("Twist.inputs:nodeNamespace", ns),
                    ("Twist.inputs:topicName", contract["command_topic"]),
                    ("Diff.inputs:maxLinearSpeed", contract["max_linear_speed"]),
                    ("Diff.inputs:maxAngularSpeed", contract["max_angular_speed"]),
                    ("Diff.inputs:wheelDistance", contract["wheel_distance"]),
                    ("Diff.inputs:wheelRadius", contract["wheel_radius"]),
                    ("Articulation.inputs:jointNames", list(contract["wheel_joints"])),
                    ("Articulation.inputs:targetPrim", [Sdf.Path(robot_prim)]),
                    ("Receipt.inputs:script", command_watchdog.RECEIPT_SCRIPT),
                    ("Gate.inputs:script", command_watchdog.GATE_SCRIPT),
                ],
                keys.CONNECT: [
                    ("Tick.outputs:tick", "Twist.inputs:execIn"),
                    ("Tick.outputs:deltaSeconds", "Diff.inputs:dt"),
                    ("Context.outputs:context", "Twist.inputs:context"),
                    ("Twist.outputs:execOut", "Diff.inputs:execIn"),
                    ("Twist.outputs:linearVelocity", "Linear.inputs:tuple"),
                    ("Linear.outputs:x", "Diff.inputs:linearVelocity"),
                    ("Twist.outputs:angularVelocity", "Angular.inputs:tuple"),
                    ("Angular.outputs:z", "Diff.inputs:angularVelocity"),
                    ("Twist.outputs:execOut", "Receipt.inputs:execIn"),
                    ("Tick.outputs:tick", "Gate.inputs:execIn"),
                    ("Gate.outputs:execOut", "Articulation.inputs:execIn"),
                ],
            },
        )
        array_type = og.Type(og.BaseDataType.DOUBLE, array_depth=1)
        gate_node = og.Controller.node("/World/ROSYDrive/Gate")
        og.Controller.create_attribute(gate_node, "inputs:wheelVelocity", array_type)
        og.Controller.create_attribute(gate_node, "velocityCommand", array_type,
                                       attr_port=og.AttributePortType.ATTRIBUTE_PORT_TYPE_OUTPUT)
        og.Controller.edit("/World/ROSYDrive", {
            keys.CONNECT: [
                ("/World/ROSYDrive/Diff.outputs:velocityCommand", "/World/ROSYDrive/Gate.inputs:wheelVelocity"),
                ("/World/ROSYDrive/Gate.outputs:velocityCommand",
                 "/World/ROSYDrive/Articulation.inputs:velocityCommand"),
            ],
        })
        force_zero_wheels(og.Controller, wheel_drives)
        watchdog_ready = True
        og.Controller.edit(
            {"graph_path": "/World/ROSYState", "evaluator_name": "execution"},
            {
                keys.CREATE_NODES: [
                    ("Tick", "omni.graph.action.OnPlaybackTick"),
                    ("Context", "isaacsim.ros2.bridge.ROS2Context"),
                    ("Time", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                    ("Odom", "isaacsim.core.nodes.IsaacComputeOdometry"),
                    ("PublishOdom", "isaacsim.ros2.bridge.ROS2PublishOdometry"),
                    ("PublishTF", "isaacsim.ros2.bridge.ROS2PublishRawTransformTree"),
                    ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
                    ("PublishJoints", "isaacsim.ros2.bridge.ROS2PublishJointState"),
                ],
                keys.SET_VALUES: [
                    ("Odom.inputs:chassisPrim", [Sdf.Path(chassis_prim)]),
                    ("PublishOdom.inputs:nodeNamespace", ns),
                    ("PublishOdom.inputs:topicName", contract["odom_topic"]),
                    ("PublishOdom.inputs:odomFrameId", contract["odom_frame"]),
                    ("PublishOdom.inputs:chassisFrameId", contract["base_frame"]),
                    ("PublishTF.inputs:parentFrameId", contract["odom_frame"]),
                    ("PublishTF.inputs:childFrameId", contract["base_frame"]),
                    ("PublishJoints.inputs:nodeNamespace", ns),
                    ("PublishJoints.inputs:topicName", "joint_states"),
                    ("PublishJoints.inputs:targetPrim", [Sdf.Path(robot_prim)]),
                ],
                keys.CONNECT: [
                    ("Tick.outputs:tick", "Odom.inputs:execIn"),
                    ("Odom.outputs:execOut", "PublishOdom.inputs:execIn"),
                    ("Odom.outputs:angularVelocity", "PublishOdom.inputs:angularVelocity"),
                    ("Odom.outputs:linearVelocity", "PublishOdom.inputs:linearVelocity"),
                    ("Odom.outputs:orientation", "PublishOdom.inputs:orientation"),
                    ("Odom.outputs:position", "PublishOdom.inputs:position"),
                    ("Time.outputs:simulationTime", "PublishOdom.inputs:timeStamp"),
                    ("Tick.outputs:tick", "PublishTF.inputs:execIn"),
                    ("Odom.outputs:orientation", "PublishTF.inputs:rotation"),
                    ("Odom.outputs:position", "PublishTF.inputs:translation"),
                    ("Time.outputs:simulationTime", "PublishTF.inputs:timeStamp"),
                    ("Tick.outputs:tick", "PublishClock.inputs:execIn"),
                    ("Time.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
                    ("Tick.outputs:tick", "PublishJoints.inputs:execIn"),
                    ("Time.outputs:simulationTime", "PublishJoints.inputs:timeStamp"),
                    ("Context.outputs:context", "PublishOdom.inputs:context"),
                    ("Context.outputs:context", "PublishTF.inputs:context"),
                    ("Context.outputs:context", "PublishClock.inputs:context"),
                    ("Context.outputs:context", "PublishJoints.inputs:context"),
                ],
            },
        )
        print(f"Isaac Sim USD: {usd_path}; ROS 2 namespace: /{ns}; robot: {robot_prim}; chassis: {chassis_prim}")
        timeline = omni.timeline.get_timeline_interface()

        def on_timeline_event(event):
            if event.type in (int(omni.timeline.TimelineEventType.STOP),
                              int(omni.timeline.TimelineEventType.PAUSE)):
                guard.reset()
                force_zero_wheels(og.Controller, wheel_drives)

        timeline_subscription = timeline.get_timeline_event_stream().create_subscription_to_pop(on_timeline_event)
        timeline.play()
        count = 0
        while simulation_app.is_running() and (args.frames == 0 or count < args.frames):
            if guard.filter((1.0, 1.0), time.monotonic(), timeline.is_playing()) == (0.0, 0.0):
                force_zero_wheels(og.Controller, wheel_drives)
            simulation_app.update()
            if guard.filter((1.0, 1.0), time.monotonic(), timeline.is_playing()) == (0.0, 0.0):
                force_zero_wheels(og.Controller, wheel_drives)
            count += 1
        guard.reset()
        force_zero_wheels(og.Controller, wheel_drives)
        timeline.stop()
        del timeline_subscription  # Keep the subscription alive through the loop.
    finally:
        try:
            if guard is not None:
                guard.reset()
                if watchdog_ready:
                    force_zero_wheels(og.Controller, wheel_drives)
        finally:
            command_watchdog.ACTIVE_WATCHDOG = None
            simulation_app.close()


if __name__ == "__main__":
    from sdk_entrypoint import run_cli

    run_cli(main)
