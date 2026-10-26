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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]/"tools/sim"))
from omx_cell_world import boxes, quaternion  # noqa: E402  The same work scene as Gazebo (D-877).

SIM_STATES, SIM_COMMANDS = "/sim/joint_states", "/sim/joint_commands"
CAMERAS = {"top": "/top_camera/image_raw", "front": "/front_camera/image_raw"}
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
        from pxr import Gf, PhysicsSchemaTools, Sdf, Usd, UsdGeom, UsdPhysics

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
        if not any(p.IsA(UsdPhysics.Scene) for p in stage.Traverse()):
            UsdPhysics.Scene.Define(stage, Sdf.Path("/World/physicsScene"))
        PhysicsSchemaTools.addGroundPlane(stage, "/World/groundPlane", "Z", 1500, Gf.Vec3f(0, 0, -0.02), Gf.Vec3f(0.5))
        # shortcut: Isaac's default physics material, not the SDF friction; set it when the grasp test needs it.
        for box in boxes():
            cube = UsdGeom.Cube.Define(stage, Sdf.Path(f"/World/Cell/{box['name']}"))
            cube.GetSizeAttr().Set(1.0)
            pose = UsdGeom.Xformable(cube)
            pose.AddTranslateOp().Set(Gf.Vec3d(*box["pos"]))
            pose.AddOrientOp().Set(Gf.Quatf(*quaternion(box["rpy"])))
            pose.AddScaleOp().Set(Gf.Vec3f(*box["size"]))
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
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
                 ("Articulation", "isaacsim.core.nodes.IsaacArticulationController")]
        values = [("PublishClock.inputs:topicName", "clock"),
                  ("PublishJoints.inputs:topicName", SIM_STATES.lstrip("/")),
                  ("PublishJoints.inputs:targetPrim", [Sdf.Path(roots[0])]),
                  ("SubscribeJoints.inputs:topicName", SIM_COMMANDS.lstrip("/")),
                  ("Articulation.inputs:targetPrim", [Sdf.Path(roots[0])])]
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
                   ("Context.outputs:context", "SubscribeJoints.inputs:context")]
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
        deadline = time.monotonic()+args.seconds
        while app.is_running() and time.monotonic() < deadline:
            app.update()
    finally:
        from sdk_entrypoint import close_sdk
        close_sdk(app, headless=True)


if __name__ == "__main__":
    from sdk_entrypoint import run_cli

    run_cli(main)
