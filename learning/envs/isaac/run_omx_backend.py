"""D-877 Isaac Sim backend adapter for the OMX-F: the shared simulator layer's topics from an Isaac stage.

Publishes /clock, /sim/joint_states and the top/front cameras on simulation time and applies /sim/joint_commands
to the articulation (tools/sim/omx_topic_backend.py serves the trajectory Action). Run with the Isaac SDK Python
and its bundled Jazzy libraries, never with the system ROS environment (Python 3.11 vs 3.12):
  tools/sim/run_omx_backend_conformance.sh isaac 240x320 5
"""

import argparse
from pathlib import Path
import sys
import time

from prepare_omx_urdf import prepare
from importer_compat import import_model, reference_model
# Drive gains, effort caps and friction of the Isaac contact fixture that lifted cargo on 2026-10-25
# (docs/solutions/runtime-errors/isaac-imported-gripper-drive-modes-must-match-gain-units-2026-10-25.md).
from conveyor_fixture import FIXTURE

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/"tools/sim"))
from omx_cell_world import PAD_HALF_LENGTH, PAD_RADIUS, boxes, jaw_contact_point, quaternion  # noqa: E402  Gazebo scene (D-877)

SIM_STATES, SIM_COMMANDS = "/sim/joint_states", "/sim/joint_commands"
CAMERAS = {"top": "/top_camera/image_raw", "front": "/front_camera/image_raw"}
OBJECTS = "/sim/object_tf"  # Evaluation facts (tools/sim/omx_backend_conformance.py OBJECTS), never a policy input.
TOP_CAMERA_POS = (0.12, 0.0, 0.65)  # Above the work area, looking down (cell top camera ~650 mm, D-794).
RENDER_HZ = 60.0


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--shape", required=True, metavar="HxW")
    parser.add_argument("--camera-hz", type=float, required=True)
    parser.add_argument("--seconds", type=float, default=600.0, help="Wall-clock bound; the runner stops it earlier")
    return parser.parse_args()


def main():
    args = parse_args()
    height, width = (int(v) for v in args.shape.lower().split("x"))
    urdf = prepare("omx_f", args.output_dir / "omx_f.urdf")
    from isaacsim import SimulationApp

    app = SimulationApp({"headless": True, "fast_shutdown": False, "width": width, "height": height,
                         "anti_aliasing": 0, "extra_args": ['--/app/extensions/excluded=["isaacsim.gui.menu"]']})
    try:
        import carb.settings
        import omni.graph.core as og
        import omni.kit.app
        import omni.kit.commands
        import omni.timeline
        import omni.usd
        from pxr import Gf, PhysicsSchemaTools, PhysxSchema, Sdf, Usd, UsdGeom, UsdPhysics, UsdShade

        manager = omni.kit.app.get_app().get_extension_manager()
        for name in ("isaacsim.asset.importer.urdf", "isaacsim.ros2.bridge", "isaacsim.core.nodes",
                     "isaacsim.sensors.camera"):
            manager.set_extension_enabled_immediate(name, True)
        import isaacsim.asset.importer.urdf as urdf_api

        if hasattr(urdf_api, "URDFImporter"):
            manager.set_extension_enabled_immediate("isaacsim.ros2.nodes", True)
        usd_path = import_model(urdf_api, omni.kit.commands.execute, urdf, args.output_dir, "Manipulator")
        reference_model(omni.usd.get_context(), usd_path, Usd, UsdGeom)
        app.update()
        stage = omni.usd.get_context().get_stage()
        roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        links = [str(p.GetPath()) for p in stage.Traverse() if p.GetName() == "link5"]
        if len(roots) != 1 or len(links) != 1:
            raise RuntimeError(f"expected one OMX articulation and link5, found {roots} {links}")
        # The finger collision hulls overlap; self-collision jammed gripper_joint_2 against link6 (2026-10-27).
        # Gazebo and the MuJoCo backend do not self-collide the arm either.
        PhysxSchema.PhysxArticulationAPI.Apply(stage.GetPrimAtPath(roots[0])).CreateEnabledSelfCollisionsAttr(False)
        if not any(p.IsA(UsdPhysics.Scene) for p in stage.Traverse()):
            UsdPhysics.Scene.Define(stage, Sdf.Path("/World/physicsScene"))
        PhysicsSchemaTools.addGroundPlane(stage, "/World/groundPlane", "Z", 1500, Gf.Vec3f(0, 0, -0.02), Gf.Vec3f(0.5))
        joints = {p.GetName(): p for p in stage.Traverse() if p.IsA(UsdPhysics.RevoluteJoint)}
        imported = {name: dict(drive=UsdPhysics.DriveAPI(p, "angular").GetTypeAttr().Get(),
                               axis=UsdPhysics.RevoluteJoint(p).GetAxisAttr().Get(),
                               mimic=[str(s) for s in p.GetAppliedSchemas() if "Mimic" in str(s)])
                    for name, p in joints.items()}
        print("OMX_ISAAC_IMPORTED_JOINTS=" + repr(imported), flush=True)
        # The importer leaves the arm and gripper_joint_1 on acceleration drives and gripper_joint_2 on a force
        # drive, and does not drive the URDF mimic: the second finger swung free and shoved the block (2026-10-27).
        for name, prim in joints.items():
            drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
            drive.CreateTypeAttr(FIXTURE["drive_type"])
            finger = name.startswith("gripper")
            drive.CreateStiffnessAttr(30.0 if finger else FIXTURE["arm_drive_stiffness"])
            drive.CreateDampingAttr(2.0 if finger else FIXTURE["arm_drive_damping"])
            drive.CreateMaxForceAttr(FIXTURE["finger_max_effort_nm"] if finger else FIXTURE["arm_max_effort_nm"])
        # The importer's mimic on gripper_joint_2 referenced gripper_joint_1's rotX (its axis is Z) with damping ratio
        # 0.005, and corrected it still did not couple the fingers (2026-10-27). The follower is removed from the mimic
        # and driven like gripper_joint_1, its target set each frame to the mirror of gripper_joint_1 (main loop).
        follower = joints["gripper_joint_2"]
        for instance in [str(s).split(":", 1)[1] for s in follower.GetAppliedSchemas() if str(s).startswith("PhysxMimicJointAPI:")]:
            follower.RemoveAPI(PhysxSchema.PhysxMimicJointAPI, instance)
        grip = UsdShade.Material.Define(stage, Sdf.Path("/World/GripMaterial"))
        surface = UsdPhysics.MaterialAPI.Apply(grip.GetPrim())
        surface.CreateStaticFrictionAttr(FIXTURE["friction"])
        surface.CreateDynamicFrictionAttr(FIXTURE["friction"])
        surface.CreateRestitutionAttr(FIXTURE["restitution"])
        # The imported finger collision closed past a 30 mm block without touching it (2026-10-27). As in the MuJoCo
        # backend, each finger collides through one capsule across the finger, its inner surface on the
        # Gazebo-calibrated contact point (cell_profile.yaml gripper.jaw; link7 mirrors link6).
        x, y = jaw_contact_point()
        for finger, side in (("link6", 1), ("link7", -1)):
            body = next(p for p in stage.Traverse() if p.GetName() == finger and p.HasAPI(UsdPhysics.RigidBodyAPI))
            for prim in Usd.PrimRange(body):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
            pad = UsdGeom.Capsule.Define(stage, body.GetPath().AppendChild("grip_pad"))
            pad.CreateAxisAttr("Z")
            pad.CreateRadiusAttr(PAD_RADIUS)
            pad.CreateHeightAttr(2*PAD_HALF_LENGTH)
            UsdGeom.Xformable(pad).AddTranslateOp().Set(Gf.Vec3d(x, side*(y + PAD_RADIUS), 0.0))
            pad.CreatePurposeAttr("guide")
            UsdPhysics.CollisionAPI.Apply(pad.GetPrim())
            UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(grip, UsdShade.Tokens.weakerThanDescendants, "physics")
        for box in boxes():
            cube = UsdGeom.Cube.Define(stage, Sdf.Path(f"/World/Cell/{box['name']}"))
            cube.GetSizeAttr().Set(1.0)
            pose = UsdGeom.Xformable(cube)
            pose.AddTranslateOp().Set(Gf.Vec3d(*box["pos"]))
            pose.AddOrientOp().Set(Gf.Quatf(*quaternion(box["rpy"])))
            pose.AddScaleOp().Set(Gf.Vec3f(*box["size"]))
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
            UsdShade.MaterialBindingAPI.Apply(cube.GetPrim()).Bind(grip, UsdShade.Tokens.weakerThanDescendants, "physics")
            if not box["static"]:
                UsdPhysics.RigidBodyAPI.Apply(cube.GetPrim())
                UsdPhysics.MassAPI.Apply(cube.GetPrim()).GetMassAttr().Set(box["mass"])

        cameras = {"top": "/World/top_camera", "front": links[0] + "/front_camera"}
        for name, path in cameras.items():
            camera = UsdGeom.Camera.Define(stage, Sdf.Path(path))
            pose = UsdGeom.XformCommonAPI(camera)
            if name == "top":
                pose.SetTranslate(Gf.Vec3d(*TOP_CAMERA_POS))  # USD cameras look down -Z: straight down here.
            else:
                pose.SetTranslate(Gf.Vec3d(0.05, 0.0, 0.03))
                pose.SetRotate(Gf.Vec3f(0.0, -90.0, 0.0))  # Along the wrist's +X.

        # Simulation runs at wall-clock pace, so the shared layer's controllers see real-time sim time.
        settings = carb.settings.get_settings()
        settings.set("/app/runLoops/main/rateLimitEnabled", True)
        settings.set("/app/runLoops/main/rateLimitFrequency", int(RENDER_HZ))

        keys = og.Controller.Keys
        nodes = [("Tick", "omni.graph.action.OnPlaybackTick"),
                 ("Context", "isaacsim.ros2.bridge.ROS2Context"),
                 ("Time", "isaacsim.core.nodes.IsaacReadSimulationTime"),
                 ("PublishClock", "isaacsim.ros2.bridge.ROS2PublishClock"),
                 ("PublishJoints", "isaacsim.ros2.bridge.ROS2PublishJointState"),
                 ("SubscribeJoints", "isaacsim.ros2.bridge.ROS2SubscribeJointState"),
                 ("Articulation", "isaacsim.core.nodes.IsaacArticulationController"),
                 ("PublishObjects", "isaacsim.ros2.bridge.ROS2PublishTransformTree")]
        values = [("PublishClock.inputs:topicName", "clock"),
                  ("PublishJoints.inputs:topicName", SIM_STATES.lstrip("/")),
                  ("PublishJoints.inputs:targetPrim", [Sdf.Path(roots[0])]),
                  ("SubscribeJoints.inputs:topicName", SIM_COMMANDS.lstrip("/")),
                  ("Articulation.inputs:targetPrim", [Sdf.Path(roots[0])]),
                  ("PublishObjects.inputs:topicName", OBJECTS.lstrip("/")),
                  ("PublishObjects.inputs:parentPrim", [Sdf.Path("/World")]),
                  ("PublishObjects.inputs:targetPrims",
                   [Sdf.Path(f"/World/Cell/{box['name']}") for box in boxes() if not box["static"]])]
        connect = [("Tick.outputs:tick", "PublishClock.inputs:execIn"),
                   ("Tick.outputs:tick", "PublishJoints.inputs:execIn"),
                   ("Tick.outputs:tick", "SubscribeJoints.inputs:execIn"),
                   ("SubscribeJoints.outputs:execOut", "Articulation.inputs:execIn"),
                   ("SubscribeJoints.outputs:jointNames", "Articulation.inputs:jointNames"),
                   ("SubscribeJoints.outputs:positionCommand", "Articulation.inputs:positionCommand"),
                   ("Time.outputs:simulationTime", "PublishClock.inputs:timeStamp"),
                   ("Time.outputs:simulationTime", "PublishJoints.inputs:timeStamp"),
                   ("Context.outputs:context", "PublishClock.inputs:context"),
                   ("Context.outputs:context", "PublishJoints.inputs:context"),
                   ("Context.outputs:context", "SubscribeJoints.inputs:context"),
                   ("Tick.outputs:tick", "PublishObjects.inputs:execIn"),
                   ("Time.outputs:simulationTime", "PublishObjects.inputs:timeStamp"),
                   ("Context.outputs:context", "PublishObjects.inputs:context")]
        skip = max(0, round(RENDER_HZ/args.camera_hz)-1)
        for name, path in cameras.items():
            product, helper = f"Render_{name}", f"Camera_{name}"
            nodes += [(product, "isaacsim.core.nodes.IsaacCreateRenderProduct"),
                      (helper, "isaacsim.ros2.bridge.ROS2CameraHelper")]
            values += [(f"{product}.inputs:cameraPrim", [Sdf.Path(path)]),
                       (f"{product}.inputs:width", width), (f"{product}.inputs:height", height),
                       (f"{helper}.inputs:type", "rgb"), (f"{helper}.inputs:topicName", CAMERAS[name].lstrip("/")),
                       (f"{helper}.inputs:frameId", f"{name}_camera_optical"),
                       (f"{helper}.inputs:frameSkipCount", skip)]
            connect += [("Tick.outputs:tick", f"{product}.inputs:execIn"),
                        (f"{product}.outputs:execOut", f"{helper}.inputs:execIn"),
                        (f"{product}.outputs:renderProductPath", f"{helper}.inputs:renderProductPath"),
                        ("Context.outputs:context", f"{helper}.inputs:context")]
        og.Controller.edit({"graph_path": "/World/OMXBackend", "evaluator_name": "execution"},
                           {keys.CREATE_NODES: nodes, keys.SET_VALUES: values, keys.CONNECT: connect})
        omni.timeline.get_timeline_interface().play()
        print(f"OMX_ISAAC_BACKEND_READY articulation={roots[0]} usd={usd_path}", flush=True)
        app.update()
        import numpy as np
        from isaacsim.core.prims import SingleArticulation
        from isaacsim.core.utils.types import ArticulationAction
        arm = SingleArticulation(roots[0])
        arm.initialize()
        lead, follow = arm.get_dof_index("gripper_joint_1"), arm.get_dof_index("gripper_joint_2")
        mirror = np.array([follow])
        deadline = time.monotonic()+args.seconds
        while app.is_running() and time.monotonic() < deadline:
            app.update()
            # The URDF mimic, gripper_joint_2 = -gripper_joint_1, on the measured lead finger: a finger stopped by
            # an item stops its twin at the mirror angle too.
            arm.apply_action(ArticulationAction(joint_positions=-arm.get_joint_positions()[[lead]], joint_indices=mirror))
    finally:
        from sdk_entrypoint import close_sdk
        close_sdk(app, headless=True)


if __name__ == "__main__":
    from sdk_entrypoint import run_cli

    run_cli(main)
