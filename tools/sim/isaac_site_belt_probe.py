"""Measure a rigid container transported by the R08 Isaac belt surface."""

import json
import math
from pathlib import Path
import sys

from isaacsim import SimulationApp

print("SITE_TRACE starting Kit", flush=True)
app = SimulationApp({
    "headless": True, "fast_shutdown": True, "width": 320, "height": 240, "anti_aliasing": 0,
    "extra_args": ['--/app/extensions/excluded=["isaacsim.gui.menu"]'],
})


def main():
    source = Path(sys.argv[1]).with_name("world_261026_ab_candidate.usda")
    try:
        import omni.timeline
        import omni.usd
        from pxr import Gf, PhysxSchema, Usd, UsdGeom, UsdPhysics

        context = omni.usd.get_context()
        print("SITE_TRACE opening exact composed stage", flush=True)
        assert context.open_stage(str(source))
        app.update()
        stage = context.get_stage()
        assert Path(stage.GetRootLayer().realPath).samefile(source)
        stage.SetEditTarget(Usd.EditTarget(stage.GetSessionLayer()))
        stage.SetTimeCodesPerSecond(60)
        stage.SetEndTimeCode(900)
        belt = stage.GetPrimAtPath("/World/Conveyor")
        assert belt.HasAPI(UsdPhysics.CollisionAPI)
        assert UsdPhysics.RigidBodyAPI(belt).GetKinematicEnabledAttr().Get()
        surface = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(belt)
        surface.CreateSurfaceVelocityEnabledAttr(True)
        surface.CreateSurfaceVelocityLocalSpaceAttr(False)
        surface.CreateSurfaceVelocityAttr(Gf.Vec3f(-0.02, 0, 0))
        cargo = stage.GetPrimAtPath("/World/Cargo0")
        assert cargo.HasAPI(UsdPhysics.CollisionAPI) and cargo.HasAPI(UsdPhysics.RigidBodyAPI)
        position = cargo.GetAttribute("xformOp:translate")
        start = position.Get()
        position.Set(type(start)(0.35, start[1], start[2]))
        body = UsdGeom.Xformable(cargo)
        clock = omni.timeline.get_timeline_interface()
        clock.play()
        print("SITE_TRACE moving surface enabled", flush=True)
        trace = []
        for tick in range(660):
            app.update()
            if tick % 30 == 0 or tick == 659:
                transform = body.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
                trace.append({"time_s": clock.get_current_time(), "xyz_m": list(transform.ExtractTranslation())})
        clock.stop()
        travelled = trace[0]["xyz_m"][0] - trace[-1]["xyz_m"][0]
        end = trace[-1]["xyz_m"]
        stable = math.dist(trace[-2]["xyz_m"], end) <= 0.004
        passed = (
            trace[-1]["time_s"] >= 10 and travelled >= 0.10 and abs(end[0] - 0.207) <= 0.025
            and stable and all(0.025 <= item["xyz_m"][2] <= 0.045 for item in trace)
        )
        print("SITE_NATIVE " + json.dumps({
            "stage": "belt_transit", "passed": passed, "surface_speed_m_s": -0.02,
            "travelled_m": travelled, "final_stable": stable, "trace": trace,
        }, allow_nan=False), flush=True)
    except BaseException:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        raise
    finally:
        app.close()


if __name__ == "__main__":
    main()
