"""Contact-only CAD gripper task on stationary synthetic Pinky/belt supports."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from conveyor_fixture import CARGO_SIZE, CONVEYOR, DT, FIXTURE, PINKY, clock_matches, evaluate, fixture_sha256, forward, solve
from importer_compat import import_model, reference_model
from model_checks import ASSETS, check_urdf, check_vendor_manifest


def physics_step(world, tick):
    """Kit render=True advances rendering_dt, which can contain multiple physics steps."""
    world.step(render=False, update_fabric=True)
    if tick % 12 == 0:
        world.render()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    check_vendor_manifest()
    check_urdf(args.urdf, 'omx_f', allow_package=False)
    args.output_dir.mkdir()
    from isaacsim import SimulationApp
    app = SimulationApp(dict(headless=True, fast_shutdown=False, width=640, height=480))
    samples, images, image_frames, joints, tick, error = [], [], [], [], 0, None
    drive_modes = {}
    try:
        import numpy as np
        import omni.kit.app
        import omni.kit.commands
        import omni.usd
        from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics, PhysxSchema
        from isaacsim.core.api import World
        from isaacsim.core.api.robots import Robot
        from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid
        from isaacsim.core.api.materials import PhysicsMaterial
        from isaacsim.core.prims import RigidPrim
        from isaacsim.core.utils.types import ArticulationAction
        from isaacsim.sensors.camera import Camera
        from PIL import Image

        omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('isaacsim.asset.importer.urdf', True)
        import isaacsim.asset.importer.urdf as api
        usd = import_model(api, omni.kit.commands.execute, args.urdf, args.output_dir, 'Manipulator')
        stage = reference_model(omni.usd.get_context(), usd, Usd, UsdGeom)
        app.update()
        world = World(physics_dt=DT, rendering_dt=DT, stage_units_in_meters=1.)
        material = PhysicsMaterial('/World/GripMaterial', static_friction=1., dynamic_friction=1., restitution=0.)
        supports = []
        for name, surface, scale, color in [
                ('PinkyTray', PINKY, [.10, .09, .025], [.85, .36, .49]),
                ('Conveyor', CONVEYOR, [.15, .09, .025], [.18, .22, .27])]:
            center = np.array(surface)-np.array([0., 0., scale[2]/2])
            supports.append(world.scene.add(FixedCuboid('/World/'+name, name=name, size=1.,
                position=center, scale=np.array(scale), color=np.array(color), physics_material=material)))
        world.scene.add(FixedCuboid('/World/Floor', name='floor', size=1., position=np.array([0., 0., -.035]),
                                   scale=np.array([1., 1., .05]), color=np.array([.65, .65, .62])))
        cargo = world.scene.add(DynamicCuboid('/World/Cargo', name='cargo', size=CARGO_SIZE,
            position=np.array(PINKY)+np.array([0., 0., CARGO_SIZE/2+.001]), mass=.05,
            color=np.array([.95, .65, .13]), physics_material=material))
        light = UsdLux.DomeLight.Define(stage, '/World/Light')
        light.CreateIntensityAttr(1200.)
        roots = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise ValueError('One CAD articulation required')
        PhysxSchema.PhysxArticulationAPI.Apply(roots[0]).CreateEnabledSelfCollisionsAttr(False)
        links = {}
        for prim in stage.Traverse():
            if prim.GetName() in ('link6', 'link7', 'end_effector_link'):
                links[prim.GetName()] = str(prim.GetPath())
            if prim.IsA(UsdPhysics.RevoluteJoint):
                drive = UsdPhysics.DriveAPI.Apply(prim, 'angular')
                before = drive.GetTypeAttr().Get()
                drive.CreateTypeAttr(FIXTURE['drive_type'])
                if drive.GetTypeAttr().Get() != 'force':
                    raise ValueError('Explicit force drive required for declared Nm effort caps')
                drive_modes[prim.GetName()] = dict(imported=before, configured=drive.GetTypeAttr().Get())
                finger = prim.GetName().startswith('gripper')
                drive.CreateStiffnessAttr(30. if finger else FIXTURE['arm_drive_stiffness'])
                drive.CreateDampingAttr(2. if finger else FIXTURE['arm_drive_damping'])
                drive.CreateMaxForceAttr(FIXTURE['finger_max_effort_nm'] if finger else FIXTURE['arm_max_effort_nm'])
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                collision = PhysxSchema.PhysxCollisionAPI.Apply(prim)
                collision.CreateContactOffsetAttr(.0005)
                collision.CreateRestOffsetAttr(0.)
                if prim.IsA(UsdGeom.Mesh):
                    UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexHull')
        if set(links) != {'link6', 'link7', 'end_effector_link'}:
            raise ValueError('CAD tool/finger links missing')
        robot = world.scene.add(Robot(str(roots[0].GetPath()), name='omx'))
        contacts = world.scene.add(RigidPrim('/World/Cargo', name='cargo_contacts',
            track_contact_forces=True, contact_filter_prim_paths_expr=[links['link6'], links['link7'],
                '/World/PinkyTray', '/World/Conveyor'], max_contact_count=64))
        eye = Gf.Vec3d(.42, -.42, .35)
        look = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(.16, 0., .10), Gf.Vec3d(0., 0., 1.)).GetInverse()
        quat = look.ExtractRotationQuat()
        camera = Camera('/World/Observer', position=np.array(eye), resolution=(640, 480))
        world.reset()
        camera.initialize()
        camera.set_world_pose(np.array(eye), np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')
        camera.set_clipping_range(*FIXTURE['camera_clip_m'])
        camera.prim.GetAttribute('focalLength').Set(24.)
        camera.prim.GetAttribute('horizontalAperture').Set(36.)
        camera.prim.GetAttribute('verticalAperture').Set(27.)
        joints = list(robot.dof_names)
        indices = [robot.get_dof_index('joint'+str(i)) for i in range(1, 6)]
        fingers = [robot.get_dof_index('gripper_joint_1'), robot.get_dof_index('gripper_joint_2')]
        def pose(surface, lift=0.):
            return [surface[0], surface[1], surface[2]+CARGO_SIZE/2+lift]
        current = np.array(solve(pose(PINKY, .08)))
        aperture = 1.
        initial = np.zeros(robot.num_dof)
        initial[indices] = current
        initial[fingers] = [aperture, -aperture]
        robot.set_joint_positions(initial)
        controller = robot.get_articulation_controller()
        first_time, first_step = world.current_time, world.current_time_step_index
        def segment(phase, target, opening, steps):
            nonlocal tick, current, aperture
            start, old_aperture = current.copy(), aperture
            desired = np.array(solve(target))
            for n in range(steps):
                fraction = (n+1)/steps
                blend = fraction*fraction*(3-2*fraction)
                q = start+(desired-start)*blend
                grip = old_aperture+(opening-old_aperture)*blend
                positions = initial.copy()
                positions[indices] = q
                positions[fingers] = [grip, -grip]
                controller.apply_action(ArticulationAction(joint_positions=positions))
                physics_step(world, tick)
                tick += 1
                if tick > 4800 or not clock_matches(tick, world.current_time_step_index-first_step, world.current_time-first_time):
                    raise RuntimeError('Physics step budget or observed clock mismatch')
                if tick % 4 == 0:
                    p, orient = cargo.get_world_pose()
                    measured = robot.get_joint_positions()[indices]
                    tcp = np.array(UsdGeom.XformCache().GetLocalToWorldTransform(
                        stage.GetPrimAtPath(links['end_effector_link'])).ExtractTranslation())
                    force = np.asarray(contacts.get_contact_force_matrix(dt=DT))
                    if force.shape != (1, 4, 3):
                        raise ValueError('Four contact filters required')
                    samples.append(dict(tick=tick, physics_steps=world.current_time_step_index-first_step,
                        physics_time_s=world.current_time-first_time, phase=phase, position=p.tolist(), orientation=orient.tolist(),
                        linear_velocity=cargo.get_linear_velocity().tolist(), angular_velocity=cargo.get_angular_velocity().tolist(),
                        contact_forces=np.linalg.norm(force[0], axis=1).tolist(), tool_distance=float(np.linalg.norm(tcp-p)),
                        finger_joints=robot.get_joint_positions()[fingers].tolist(), tcp_position=tcp.tolist(),
                        joint_error=float(np.max(np.abs(measured-q))), tcp_error=float(np.linalg.norm(tcp-forward(measured)))))
                    if not np.isfinite(p).all() or p[2] < 0 or np.linalg.norm(p[:2]) > .7:
                        raise RuntimeError('Cargo escaped fixture')
            current, aperture = desired, opening
            if phase in {'pinky_initial', 'out_lift', 'conveyor_settle', 'back_lift', 'pinky_settle'}:
                world.render()
                world.render()
                rgba = camera.get_rgba()
                if rgba is None or rgba.shape != (480, 640, 4):
                    raise RuntimeError('Phase image unavailable')
                name = phase+'.png'
                Image.fromarray(rgba.astype(np.uint8)).save(args.report.parent/name)
                images.append(name)
                frame = camera.get_current_frame()
                image_frames.append(dict(name=name, tick=tick, physics_time_s=world.current_time-first_time,
                                         rendering_frame=frame.get('rendering_frame'), rendering_time=frame.get('rendering_time')))
        closed = FIXTURE['gripper_closed_rad']
        segment('pinky_initial', pose(PINKY, .08), 1., 240)
        segment('out_approach', pose(PINKY), 1., 180)
        segment('out_close', pose(PINKY), closed, 180)
        segment('out_raise', pose(PINKY, .08), closed, 180)
        segment('out_lift', pose(PINKY, .08), closed, 124)
        segment('out_move', pose(CONVEYOR, .08), closed, 240)
        segment('out_transport', pose(CONVEYOR, .08), closed, 124)
        segment('out_lower', pose(CONVEYOR, .004), closed, 180)
        segment('out_open', pose(CONVEYOR, .004), 1., 180)
        segment('out_retreat', pose(CONVEYOR, .08), 1., 180)
        segment('conveyor_settle', pose(CONVEYOR, .08), 1., 124)
        segment('back_approach', pose(CONVEYOR), 1., 180)
        segment('back_close', pose(CONVEYOR), closed, 180)
        segment('back_raise', pose(CONVEYOR, .08), closed, 180)
        segment('back_lift', pose(CONVEYOR, .08), closed, 124)
        segment('back_move', pose(PINKY, .08), closed, 240)
        segment('back_transport', pose(PINKY, .08), closed, 124)
        segment('back_lower', pose(PINKY, .004), closed, 180)
        segment('back_open', pose(PINKY, .004), 1., 180)
        segment('back_retreat', pose(PINKY, .08), 1., 180)
        segment('pinky_settle', pose(PINKY, .08), 1., 124)
    except Exception as exc:
        error = type(exc).__name__+': '+str(exc)
        print('CONTACT_TASK_ERROR:', error, flush=True)
    finally:
        from sdk_entrypoint import close_sdk
        close_sdk(app, headless=True)
    from importlib.metadata import version
    judgement = evaluate(samples) if error is None else dict(task_success=False, failures=[error], evidence_class='INCOMPLETE_CONTACT_TASK')
    value = dict(schema='rosy.pinky-conveyor-report/1', fixture=FIXTURE, fixture_sha256=fixture_sha256(),
        assets_sha256=hashlib.sha256((ASSETS/'manifest.json').read_bytes()).hexdigest(), sdk_version=version('isaacsim'),
        joints=joints, completed_frames=tick, samples=samples, images=images, image_frames=image_frames, judgement=judgement,
        attachment_aid=False, drive_modes=drive_modes, error=error)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    from sdk_entrypoint import run_cli
    run_cli(main)
