"""Publish RGB frames and simulation time from an owned, isolated Isaac stage."""

import argparse
import base64
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import re
import tempfile
import time


def publish(path, value):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        staged = Path(stream.name)
    try:
        staged.write_text(json.dumps(value, allow_nan=False) + "\n", encoding="utf-8")
        staged.replace(path)
    finally:
        staged.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seconds", type=int, default=180, choices=range(10, 361), metavar="10..360")
    parser.add_argument("--belt-demo", action="store_true", help="move the R08 belt in this isolated demo")
    args = parser.parse_args()
    domain = os.environ.get("ROS_DOMAIN_ID", "")
    run_id = os.environ.get("GZ_PARTITION", "")
    if (not re.fullmatch(r"sim-[a-z0-9-]{1,80}", run_id) or not domain.isdecimal()
            or not 0 < int(domain) <= 232 or os.environ.get("ROS_AUTOMATIC_DISCOVERY_RANGE") != "LOCALHOST"):
        parser.error("requires an isolated remote_sim run")
    scene = args.stage.resolve(strict=True)
    scene_sha = sha256(scene.read_bytes()).hexdigest()
    args.out.parent.mkdir(parents=True, exist_ok=True)

    from isaacsim import SimulationApp

    app = SimulationApp({
        "headless": True, "fast_shutdown": True, "width": 640, "height": 480, "anti_aliasing": 0,
        "extra_args": ['--/app/extensions/excluded=["isaacsim.gui.menu"]'],
    })
    timeline = None
    try:
        import numpy as np
        import omni.kit.app
        import omni.timeline
        import omni.usd
        from PIL import Image
        from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics

        manager = omni.kit.app.get_app().get_extension_manager()
        for name in ("isaacsim.ros2.bridge", "isaacsim.ros2.nodes", "isaacsim.sensors.camera"):
            manager.set_extension_enabled_immediate(name, True)
        from isaacsim.sensors.camera import Camera

        context = omni.usd.get_context()
        if not context.open_stage(str(scene)):
            raise RuntimeError("Isaac could not open the requested stage")
        app.update()
        stage = context.get_stage()
        if not stage or not Path(stage.GetRootLayer().realPath).samefile(scene):
            raise RuntimeError("Isaac did not load the requested scene")
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        stage.SetTimeCodesPerSecond(60)
        stage.SetEndTimeCode((args.seconds + 60) * 60)
        cargo = stage.GetPrimAtPath("/World/Cargo0")
        if not cargo.HasAPI(UsdPhysics.RigidBodyAPI):
            raise RuntimeError("expected R08 dynamic cargo")
        if args.belt_demo:
            belt = stage.GetPrimAtPath("/World/Conveyor")
            if not belt.HasAPI(UsdPhysics.CollisionAPI) or not UsdPhysics.RigidBodyAPI(belt).GetKinematicEnabledAttr().Get():
                raise RuntimeError("expected a kinematic R08 belt collider")
            surface = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(belt)
            surface.CreateSurfaceVelocityEnabledAttr(True)
            surface.CreateSurfaceVelocityLocalSpaceAttr(False)
            surface.CreateSurfaceVelocityAttr(Gf.Vec3f(-0.02, 0, 0))
            position = cargo.GetAttribute("xformOp:translate")
            initial = position.Get()
            position.Set(type(initial)(0.35, initial[1], initial[2]))

        eye = Gf.Vec3d(1.10, -.90, 1.30)
        target = Gf.Vec3d(0.05, 0, 0.05)
        rotation = Gf.Matrix4d().SetLookAt(eye, target, Gf.Vec3d(0, 0, 1)).GetInverse().ExtractRotationQuat()
        camera = Camera("/World/LivePreviewCamera", resolution=(640, 480))
        camera.initialize()
        camera.set_world_pose(np.array(eye), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes="usd")
        camera.set_clipping_range(.01, 10.)
        timeline = omni.timeline.get_timeline_interface()
        timeline.play()
        deadline = time.monotonic() + args.seconds
        next_frame = sim_time = sequence = 0
        while app.is_running() and time.monotonic() < deadline:
            app.update()
            now = time.monotonic()
            current = timeline.get_current_time()
            if now < next_frame or current <= sim_time:
                continue
            frame = camera.get_rgba()
            if frame is None or frame.shape[:2] != (480, 640):
                continue
            image = io.BytesIO()
            Image.fromarray(frame[:, :, :3].astype(np.uint8)).save(image, format="JPEG", quality=75)
            xyz = UsdGeom.Xformable(cargo).ComputeLocalToWorldTransform(Usd.TimeCode.Default()).ExtractTranslation()
            sequence += 1
            publish(args.out, {
                "schema": "rosy.world.isaac-view.v1", "run_id": run_id, "stage_sha256": scene_sha,
                "observed_at_ms": time.time_ns() // 1_000_000, "sim_time_s": current, "sequence": sequence,
                "cargo_xyz_m": list(xyz), "scenario": "belt" if args.belt_demo else "scene",
                "jpeg": base64.b64encode(image.getvalue()).decode("ascii"),
            })
            next_frame, sim_time = now + .33, current
        if sequence < 2:
            raise RuntimeError("Isaac did not render advancing simulation frames")
        print(f"{run_id}: emitted {sequence} Isaac frames; simulation {sim_time:.3f}s", flush=True)
    finally:
        if timeline is not None:
            timeline.stop()
        app.close()


if __name__ == "__main__":
    main()
