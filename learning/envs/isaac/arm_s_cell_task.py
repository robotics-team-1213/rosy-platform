"""Arm S cell: replay the real cell's chunk frames (deploy/robot/omx/isaac_cell_frames.py) against the tray,
belt and Pinky frame, and record what the box, the fingers and the arm's following error did (D-872)."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from arm_s_cell_fixture import (BELT, BOX, FIXTURE, FRAME, SCENARIOS, SOFT_CONTACT_RAD, TRAY, box_start, check_case,
                                evaluate)
from importer_compat import import_model, reference_model
from model_checks import ASSETS, check_urdf, check_vendor_manifest

DT = FIXTURE['physics_dt_s']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--frames', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--steps-per-frame', type=int, default=round(1 / DT / FIXTURE['frame_fps']))
    args = parser.parse_args()
    plan = json.loads(args.frames.read_text())
    if plan.get('schema') != 'rosy.omx-isaac-cell-frames.v1' or plan.get('scenario') not in (*SCENARIOS, 'case'):
        raise SystemExit('frames must come from isaac_cell_frames.py for a known scenario or a case')
    scenario = check_case(plan.get('case')) if plan['scenario'] == 'case' else plan['scenario']
    check_vendor_manifest()
    check_urdf(args.urdf, 'omx_f', allow_package=False)
    args.output_dir.mkdir()
    from isaacsim import SimulationApp
    app = SimulationApp(dict(headless=True, fast_shutdown=False, width=640, height=480))
    samples, images, tick, error, frame_count = [], [], 0, None, 0
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
        material = PhysicsMaterial('/World/GripMaterial', static_friction=FIXTURE['friction'],
                                   dynamic_friction=FIXTURE['friction'], restitution=FIXTURE['restitution'])
        for name, part, color in [('Tray', TRAY, [.85, .85, .85]), ('Belt', BELT, [.15, .17, .2]),
                                  ('PinkyFrame', FRAME, [.1, .1, .1])]:
            thick = part['top'] + .01  # each block stands on the floor up to its top
            world.scene.add(FixedCuboid('/World/' + name, name=name, size=1.,
                position=np.array([*part['center'], part['top'] - thick / 2]),
                scale=np.array([*part['size'], thick]), color=np.array(color), physics_material=material))
        world.scene.add(FixedCuboid('/World/Floor', name='floor', size=1., position=np.array([0., 0., -.035]),
                                   scale=np.array([1., 1., .05]), color=np.array([.65, .65, .62])))
        (x, y, z), yaw = box_start(scenario)
        half = math.radians(yaw) / 2
        box = world.scene.add(DynamicCuboid('/World/Box', name='box', size=BOX, position=np.array([x, y, z + .001]),
            orientation=np.array([math.cos(half), 0., 0., math.sin(half)]), mass=FIXTURE['box_mass_kg'],
            color=np.array([.62, .38, .22]), physics_material=material))
        UsdLux.DomeLight.Define(stage, '/World/Light').CreateIntensityAttr(1200.)
        roots = [p for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise ValueError('One CAD articulation required')
        PhysxSchema.PhysxArticulationAPI.Apply(roots[0]).CreateEnabledSelfCollisionsAttr(False)
        links = {}
        for prim in stage.Traverse():
            if prim.GetName() in ('link6', 'link7'):
                links[prim.GetName()] = str(prim.GetPath())
            if prim.IsA(UsdPhysics.RevoluteJoint):
                drive = UsdPhysics.DriveAPI.Apply(prim, 'angular')
                drive.CreateTypeAttr('force')
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
        if set(links) != {'link6', 'link7'}:
            raise ValueError('CAD finger links missing')
        robot = world.scene.add(Robot(str(roots[0].GetPath()), name='omx'))
        contacts = world.scene.add(RigidPrim('/World/Box', name='box_contacts', track_contact_forces=True,
            contact_filter_prim_paths_expr=[links['link6'], links['link7'], '/World/Tray', '/World/Belt',
                                            '/World/PinkyFrame'], max_contact_count=64))
        eye = Gf.Vec3d(.38, -.30, .32)
        look = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(.10, .06, .05), Gf.Vec3d(0., 0., 1.)).GetInverse()
        quat = look.ExtractRotationQuat()
        camera = Camera('/World/Observer', position=np.array(eye), resolution=(640, 480))
        world.reset()
        camera.initialize()
        camera.set_world_pose(np.array(eye), np.array([quat.GetReal(), *quat.GetImaginary()]), camera_axes='usd')
        arm = [robot.get_dof_index('joint' + str(i)) for i in range(1, 6)]
        fingers = [robot.get_dof_index('gripper_joint_1'), robot.get_dof_index('gripper_joint_2')]
        positions = np.zeros(robot.num_dof)

        def command(q):
            positions[arm] = q[:5]
            positions[fingers] = [q[5], -q[5]]
            return positions.copy()

        robot.set_joint_positions(command(plan['start']))
        controller = robot.get_articulation_controller()
        for phase in plan['phases']:
            for target in phase['frames']:
                controller.apply_action(ArticulationAction(joint_positions=command(target)))
                for _ in range(args.steps_per_frame):
                    world.step(render=False, update_fabric=True)
                    tick += 1
                p, orient = box.get_world_pose()
                force = np.linalg.norm(np.asarray(contacts.get_contact_force_matrix(dt=DT))[0], axis=1)
                measured = robot.get_joint_positions()
                lag = float(np.max(np.abs(measured[arm] - np.array(target[:5]))))
                frame_count += 1
                # every 6th frame (5 Hz) and every frame that touches the frame or passes the soft-contact
                # bound: the report stays under the verifier's 1 MB for a whole cycle
                if frame_count % 6 and force[4] <= .05 and lag <= SOFT_CONTACT_RAD and target is not phase['frames'][-1]:
                    continue
                samples.append(dict(tick=tick, phase=phase['phase_id'], box_position=p.tolist(),
                    box_orientation=orient.tolist(), finger_contact_n=force[:2].tolist(),
                    tray_contact_n=float(force[2]), belt_contact_n=float(force[3]), frame_contact_n=float(force[4]),
                    joint_error_rad=lag,
                    fingers_rad=measured[fingers].tolist(), finger_command_rad=target[5]))
                if not np.isfinite(p).all() or p[2] < -.02:
                    raise RuntimeError('Box escaped the cell')
            world.render()
            world.render()
            rgba = camera.get_rgba()
            if rgba is not None and rgba.shape == (480, 640, 4):
                name = f"{phase['phase_id']}.png"
                Image.fromarray(rgba.astype(np.uint8)).save(args.report.parent / name)
                images.append(name)
    except Exception as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        print('ARM_S_CELL_ERROR:', error, flush=True)
    finally:
        from sdk_entrypoint import close_sdk
        close_sdk(app, headless=True)
    from importlib.metadata import version
    judgement = evaluate(samples, scenario) if error is None else dict(result='error', error=error,
                                                                        matches_expectation=False)
    value = dict(schema='rosy.arm-s-cell-report/1', scenario=scenario, fixture=FIXTURE,
        frames_sha256=hashlib.sha256(args.frames.read_bytes()).hexdigest(),
        assets_sha256=hashlib.sha256((ASSETS / 'manifest.json').read_bytes()).hexdigest(),
        sdk_version=version('isaacsim'), steps_per_frame=args.steps_per_frame, physics_steps=tick,
        samples=samples, images=images, judgement=judgement, error=error)
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    from sdk_entrypoint import run_cli
    run_cli(main)
