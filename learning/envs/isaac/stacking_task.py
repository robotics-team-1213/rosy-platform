"""Contact-driven OMX-F stacking environment and a bounded RSL-RL PPO smoke run."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from stacking_fixture import BELT_TOP, DT, FIXTURE, PROFILE, UNIT, advance_joint, placed, stack_plan, target
import stacking_scene as scene
from stacking_task_helpers import run_ppo_stacking
from importer_compat import import_model, reference_model
from model_checks import check_urdf, check_vendor_manifest
from finger_pads import add_finger_pads
from run_omx_backend import FOLLOWER_STIFFNESS, FOLLOWER_DAMPING, FOLLOWER_MAX_EFFORT_NM


def run(args):
    global FIXTURE
    container = getattr(args, 'mapped_container_stack', False)
    if container:
        args.mapped_cube_stack = True
    mapped = args.mapped_long_stack or args.mapped_rl or args.mapped_cube_stack
    if mapped:
        from mapped_stack_fixture import FIXTURE
        if args.mapped_rl:
            from mapped_stack_fixture import RL_FIXTURE as FIXTURE
        elif args.mapped_cube_stack:
            from mapped_stack_fixture import CUBE_FIXTURE as FIXTURE
            if container:
                from mapped_stack_fixture import container_fixture
                FIXTURE = container_fixture(layers=args.layers, case=args.container_case)
    import numpy as np
    import torch
    import yaml
    import omni.kit.app
    import omni.kit.commands
    import omni.usd
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, PhysxSchema
    from isaacsim.core.api import World
    from isaacsim.core.api.robots import Robot
    from isaacsim.core.api.objects import FixedCuboid, VisualCuboid
    from isaacsim.core.api.materials import PhysicsMaterial
    from isaacsim.sensors.camera import Camera

    torch.manual_seed(args.seed)
    torch.set_num_threads(2)
    profile = yaml.safe_load(PROFILE.read_text())
    if profile['profile'] != 'simulation':
        raise ValueError('Only the nominal simulation profile is allowed')
    omni.kit.app.get_app().get_extension_manager().set_extension_enabled_immediate('isaacsim.asset.importer.urdf', True)
    import isaacsim.asset.importer.urdf as api
    usd = import_model(api, omni.kit.commands.execute, args.urdf, args.output_dir, 'Manipulator')
    stage = reference_model(omni.usd.get_context(), usd, Usd, UsdGeom)
    first = stage.GetPrimAtPath('/World/Imported')
    second = stage.DefinePrim('/World/ArmB', 'Xform')
    if not second.GetReferences().AddReference(usd):
        raise RuntimeError('Second OMX-F reference failed')
    variants = second.GetVariantSets()
    if 'Physics' in variants.GetNames():
        if not variants.GetVariantSet('Physics').SetVariantSelection('physx'):
            raise RuntimeError('Second arm PhysX variant unavailable')
    for prim, base, yaw in zip((first, second), FIXTURE['arm_bases_m'], FIXTURE.get('arm_base_yaws_rad', [0., 0.])):
        UsdGeom.XformCommonAPI(prim).SetTranslate(Gf.Vec3d(*base))
        UsdGeom.XformCommonAPI(prim).SetRotate(Gf.Vec3f(0., 0., math.degrees(yaw)))
    world = World(physics_dt=FIXTURE.get('physics_dt_s', DT), rendering_dt=DT, stage_units_in_meters=1.)
    mat = PhysicsMaterial('/World/GripMaterial', static_friction=1., dynamic_friction=1., restitution=0.)

    def fixed(name, position, size, color, pitch=0.):
        orientation = np.array([math.cos(pitch/2),0.,-math.sin(pitch/2),0.]) if pitch else None
        obj = world.scene.add(FixedCuboid('/World/'+name, name=name, size=1.,
            position=np.array(position), scale=np.array(size), color=np.array(color), physics_material=mat,
            orientation=orientation))
        if pitch:
            measured = obj.get_world_pose()[1]
            if not np.isfinite(measured).all() or abs(float(np.dot(measured,orientation))) < 1-1e-6:
                raise RuntimeError('Sloped conveyor orientation readback differs')
        return obj

    fixed('Table', FIXTURE.get('workplate_center_m', [0., -.20, -.025] if mapped else [0., 0., -.025]),
          FIXTURE.get('workplate_size_m', [.9, .8, .05] if mapped else [1.8, 1.8, .05]),
          [.85, .66, .05] if mapped else [.30, .32, .34])
    belt = fixed('Conveyor', FIXTURE.get('belt_center_m', [.16 if mapped else .20, -.28, .0125]), FIXTURE['belt_size_m'], [.12, .15, .18], FIXTURE.get('belt_pitch_rad',0.))
    UsdPhysics.RigidBodyAPI.Apply(belt.prim).CreateKinematicEnabledAttr(True)
    surface = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(belt.prim)
    surface.CreateSurfaceVelocityEnabledAttr(True)
    surface.CreateSurfaceVelocityLocalSpaceAttr(False)
    surface.CreateSurfaceVelocityAttr(Gf.Vec3f(*FIXTURE.get('belt_velocity_m_s', [0., FIXTURE['belt_speed_m_s'], 0.])))
    if args.mapped_cube_stack:
        for i, sign in enumerate((-1, 1)):
            center = FIXTURE['belt_center_m'][:]
            center[1] += sign*(FIXTURE['belt_size_m'][1]/2+.002)
            center[2] = .027
            pitch = FIXTURE.get('belt_pitch_rad',0.)
            if pitch:
                center[0] -= math.sin(pitch)*.0045
                center[2] = FIXTURE['belt_center_m'][2]+math.cos(pitch)*.0045
            fixed('BeltRail'+str(i), center, [FIXTURE['belt_size_m'][0], .004, .005], [.65, .65, .65], pitch)
    if args.mapped_cube_stack and 'upstream_belt_center_m' in FIXTURE:
        upstream = fixed('UpstreamConveyor', FIXTURE['upstream_belt_center_m'], FIXTURE['upstream_belt_size_m'], [.12, .15, .18])
        UsdPhysics.RigidBodyAPI.Apply(upstream.prim).CreateKinematicEnabledAttr(True)
        surface = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(upstream.prim)
        surface.CreateSurfaceVelocityEnabledAttr(True)
        surface.CreateSurfaceVelocityLocalSpaceAttr(False)
        surface.CreateSurfaceVelocityAttr(Gf.Vec3f(*FIXTURE['upstream_velocity_m_s']))
        for i, sign in enumerate((-1, 1)):
            center = FIXTURE['upstream_belt_center_m'][:]
            center[0] += sign*(FIXTURE['upstream_belt_size_m'][0]/2+.002)
            center[2] = .027
            fixed('UpstreamRail'+str(i), center, [.004, FIXTURE['upstream_belt_size_m'][1], .005], [.65, .65, .65])
    fixed('BeltStop', FIXTURE.get('belt_stop_m', [.16 if mapped else .20, -.029, .027 if mapped else .035]),
          FIXTURE.get('belt_stop_size_m', [.12, .004, .004 if mapped else .02]), [.65, .65, .65])
    floor = args.mapped_cube_stack
    if FIXTURE.get('ship_plate'):
        scene.add_ship_plate(stage, FIXTURE)
    else:
        fixed('Bin', [FIXTURE['bin_origin_m'][0]+.045, 0., FIXTURE['bin_origin_m'][2]-.001] if floor else
              ([.16, FIXTURE['bin_origin_m'][1]+FIXTURE['bin_size_m'][1]/2, .0125] if mapped else [.20, .02, .0125]),
              [.09, FIXTURE['bin_size_m'][1] if mapped else .09, .002 if floor else .025], [.30, .32, .34] if floor else [.15, .48, .7])
    if mapped:
        from mapped_stack_task import build_map
        build_map(world, stage, FIXTURE)
    origin = np.array(FIXTURE['bin_origin_m'])
    # D-969: the real cameras never see these aids, so frames that train or drive a policy are drawn without them
    aids = not (FIXTURE.get('demo_recording') or FIXTURE.get('policy'))
    for axis in range(3 if aids else 0):
        others = [i for i in range(3) if i != axis]
        for ai, a in enumerate((0., FIXTURE['bin_size_m'][others[0]])):
            for bi, b in enumerate((0., FIXTURE['bin_size_m'][others[1]])):
                center = origin.copy()
                center[axis] += FIXTURE['bin_size_m'][axis]/2
                center[others] += [a, b]
                size = np.full(3, .0007); size[axis] = FIXTURE['bin_size_m'][axis]
                name = f'Envelope{axis}_{ai}_{bi}'
                world.scene.add(VisualCuboid('/World/'+name, name=name, size=1.,
                    position=center, scale=size, color=np.array([.95, .8, .12])))
    for axis in range(0 if mapped else 2):
        for n in (1, 2):
            center = origin+np.array([.045, .045, .0001])
            center[axis] = origin[axis]+UNIT*n
            size = np.array([.09, .09, .0002]); size[axis] = .0004
            name = f'Grid{axis}_{n}'
            world.scene.add(VisualCuboid('/World/'+name, name=name, size=1.,
                position=center, scale=size, color=np.ones(3)))
    # The target is an open cargo envelope; walls would consume the zero-clearance packing space.
    for i, x in enumerate(() if mapped else (.154, .246)):
        fixed('Boundary'+str(i), [x, .02, .001], [.001, .092, .002], [.95, .8, .12])
    light = UsdLux.DomeLight.Define(stage, '/World/Light')
    light.CreateIntensityAttr(1600.)
    robots, links, joint_indices, fingers = [], [], [], []
    for root in (first, second):
        # Expose imported collision meshes so scene overrides also reach instance children in SDK 6.2.
        for prim in list(Usd.PrimRange(root)):
            if prim.IsInstance():
                prim.SetInstanceable(False)
        prims = list(Usd.PrimRange(root))
        roots = [p for p in prims if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise RuntimeError('Each OMX reference requires one articulation')
        # Match the existing OMX backend: imported adjacent finger hulls overlap and must not self-collide.
        articulation = PhysxSchema.PhysxArticulationAPI.Apply(roots[0])
        articulation.CreateEnabledSelfCollisionsAttr(False)
        if mapped:
            articulation.CreateSolverPositionIterationCountAttr(64)
            articulation.CreateSolverVelocityIterationCountAttr(16)
        tool = {p.GetName(): str(p.GetPath()) for p in prims
                if p.GetName() in ('link6', 'link7', 'end_effector_link')}
        if mapped:
            parents = [p for p in prims if p.GetName() == 'link5']
            if len(parents) != 1 or 'end_effector_link' in tool:
                raise RuntimeError('Expected one physical link5 without a dynamic TCP body')
            frame = UsdGeom.Xform.Define(stage, parents[0].GetPath().AppendChild('end_effector_link'))
            UsdGeom.XformCommonAPI(frame).SetTranslate(Gf.Vec3d(*FIXTURE.get('tcp_offset_m', [.09193, -.0016, 0.])))
            tool['end_effector_link'] = str(frame.GetPath())
        if set(tool) != {'link6', 'link7', 'end_effector_link'}:
            raise RuntimeError('Each OMX requires both finger and TCP links')
        links.append(tool)
        articulation_path = str(roots[0].GetPath())
        if mapped:
            anchors = [p for p in prims if p.GetName() == 'world_fixed' and p.IsA(UsdPhysics.FixedJoint)]
            if len(anchors) != 1:
                raise RuntimeError('Expected one OMX world anchor')
            anchor = UsdPhysics.FixedJoint(anchors[0])
            anchor.GetBody0Rel().SetTargets([])
            anchor.GetLocalPos0Attr().Set(Gf.Vec3f(*FIXTURE['arm_bases_m'][len(robots)]))
            yaw = FIXTURE.get('arm_base_yaws_rad', [0., 0.])[len(robots)]
            anchor.GetLocalRot0Attr().Set(Gf.Quatf(math.cos(yaw/2), Gf.Vec3f(0., 0., math.sin(yaw/2))))
            roots[0].RemoveAPI(UsdPhysics.ArticulationRootAPI)
            UsdPhysics.ArticulationRootAPI.Apply(anchors[0])
            fixed_articulation = PhysxSchema.PhysxArticulationAPI.Apply(anchors[0])
            fixed_articulation.CreateEnabledSelfCollisionsAttr(False)
            fixed_articulation.CreateSolverPositionIterationCountAttr(64)
            fixed_articulation.CreateSolverVelocityIterationCountAttr(16)
            articulation_path = str(root.GetPath())
        for prim in prims:
            if prim.IsA(UsdPhysics.RevoluteJoint):
                finger = prim.GetName().startswith('gripper')
                limit = profile['gripper'] if finger else profile['joints'][prim.GetName()]
                velocity_limit = math.degrees(limit['velocity'])
                velocity_attr = PhysxSchema.PhysxJointAPI.Apply(prim).CreateMaxJointVelocityAttr(velocity_limit)
                if not math.isclose(velocity_attr.Get(), velocity_limit, rel_tol=1e-6):
                    raise RuntimeError('Joint velocity limit readback failed')
                drive = UsdPhysics.DriveAPI.Apply(prim, 'angular')
                drive.CreateTypeAttr('force')
                drive.CreateStiffnessAttr(math.radians(30. if finger else FIXTURE['arm_stiffness_si']) if mapped else (30. if finger else 5000.))
                drive.CreateDampingAttr(math.radians(2. if finger else FIXTURE['arm_damping_si']) if mapped else (2. if finger else 100.))
                drive.CreateMaxForceAttr(FIXTURE.get('finger_max_efforts_nm', [.2, 2.])[0] if finger else (FIXTURE['arm_max_effort_nm'] if mapped else 30.))
                if prim.GetName() == 'gripper_joint_2':
                    drive.CreateStiffnessAttr(math.radians(FOLLOWER_STIFFNESS) if mapped else FOLLOWER_STIFFNESS)
                    drive.CreateDampingAttr(math.radians(FOLLOWER_DAMPING) if mapped else FOLLOWER_DAMPING)
                    drive.CreateMaxForceAttr(FOLLOWER_MAX_EFFORT_NM)
                    prim.CreateAttribute('newton:mimicEnabled', Sdf.ValueTypeNames.Bool).Set(False)
                    if prim.GetAttribute('newton:mimicEnabled').Get() is not False:
                        raise RuntimeError('Imported Newton mimic remains enabled')
                    for schema in prim.GetAppliedSchemas():
                        if str(schema).startswith('PhysxMimicJointAPI:'):
                            prim.RemoveAPI(PhysxSchema.PhysxMimicJointAPI, str(schema).split(':', 1)[1])
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                collision = PhysxSchema.PhysxCollisionAPI.Apply(prim)
                collision.CreateContactOffsetAttr(.0005)
                collision.CreateRestOffsetAttr(0.)
                if prim.IsA(UsdGeom.Mesh):
                    UsdPhysics.MeshCollisionAPI.Apply(prim).CreateApproximationAttr('convexHull')
        add_finger_pads(stage, tool, FIXTURE.get('gripper'))
        robot = world.scene.add(Robot(articulation_path, name='arm'+str(len(robots))))
        robots.append(robot)
    if mapped:
        from mapped_stack_fixture import plan as mapped_plan
        plan = mapped_plan(args.mapped_cube_stack, fixture=FIXTURE)
    else:
        plan = stack_plan()
    cargo, contacts = scene.add_cargo(world, stage, plan, links, mat, FIXTURE, mapped=mapped, cube=args.mapped_cube_stack)
    eye = Gf.Vec3d(.60, -.62, .48)
    wrist_views, grasp_probes = scene.add_probes(world, stage, links, plan, (first, second), mapped=mapped,
                                                 probed=args.mapped_long_stack or args.mapped_cube_stack)
    look = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(.13, -.10, .12), Gf.Vec3d(0., 0., 1.)).GetInverse()
    rotation = look.ExtractRotationQuat()
    camera = Camera('/World/Observer', position=np.array(eye), resolution=(800, 600))
    world.reset()
    camera.initialize()
    camera.set_world_pose(np.array(eye), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
    camera.set_clipping_range(.01, 10.)
    camera.prim.GetAttribute('focalLength').Set(35.)
    camera.prim.GetAttribute('horizontalAperture').Set(36.)
    camera.prim.GetAttribute('verticalAperture').Set(27.)
    for robot in robots:
        joint_indices.append([robot.get_dof_index('joint'+str(i)) for i in range(1, 6)])
        fingers.append([robot.get_dof_index('gripper_joint_1'), robot.get_dof_index('gripper_joint_2')])
        if mapped and not robot._articulation_view._physics_view.shared_metatype.fixed_base:
            raise RuntimeError('Mapped OMX requires a native fixed base')

    real_cameras = {}

    def capture(name, overview=False):
        if name.startswith('real-'):
            view = name[len('real-'):-len('.png')].removesuffix('-final')
            return scene.real_capture(world, real_cameras, view, FIXTURE['real_cameras'][view], args.report.parent/name)
        scene.capture(world, camera, eye, args.report.parent/name, container=container, overview=overview)

    initial = None
    if mapped:
        from mapped_stack_fixture import home, tcp_from_wrist
        from mapped_stack_task import Planner
        planner = Planner(args.report.parent,scene=FIXTURE.get('planning_scene'),tcp_x_m=FIXTURE.get('tcp_offset_m',[None])[0])
        initial = planner.request('homes', bases=FIXTURE['arm_bases_m'],
            base_yaws=FIXTURE.get('arm_base_yaws_rad', [0., 0.]),
            points=[home(0, args.mapped_cube_stack, fixture=FIXTURE), home(1, args.mapped_cube_stack, fixture=FIXTURE)])
        if FIXTURE.get('gripper'):  # opt-in jaw: finger angles from its pad geometry, not the stock jaw's profile
            from palletizing_gripper import finger_angles
            initial['gripper'] = finger_angles(FIXTURE.get('release_gap_m'))

    def tcp_position(arm):
        positions, quaternions = wrist_views[arm].get_world_poses()
        return np.array(tcp_from_wrist(positions[0], quaternions[0], FIXTURE.get('tcp_offset_m', (.09193, -.0016, 0.))))

    if args.mapped_long_stack or args.mapped_cube_stack:
        from mapped_stack_task import execute
        recording = None
        if container:
            from container_recording import ContainerRecording
            import omni.replicator.core as rep
            import omni.graph.core as og
            config = FIXTURE['recording']
            position, focus = Gf.Vec3d(*config['eye']), Gf.Vec3d(*config['focus'])
            rotation = Gf.Matrix4d().SetLookAt(position, focus, Gf.Vec3d(0., 0., 1.)).GetInverse().ExtractRotationQuat()
            video_camera = Camera('/World/Recording', position=np.array(position), resolution=(config['width'], config['height']))
            video_camera.initialize()
            video_camera.set_world_pose(np.array(position), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
            video_camera.set_clipping_range(.01, 10.)
            for name, value in (('focalLength', 35.), ('horizontalAperture', 36.), ('verticalAperture', 27.)):
                video_camera.prim.GetAttribute(name).Set(value)
            reference = rep.AnnotatorRegistry.get_annotator('ReferenceTime')
            reference.attach([video_camera.get_render_product_path()])
            graph = og.Controller.graph('/Render/PostProcess/SDGPipeline')
            def reference_time():
                og.Controller.evaluate_sync(graph_id=graph)
                return reference.get_data()
            # D-969: created before the warm-up renders; one created after them still returned no image on the first frame
            views = (scene.demo_views(real_cameras, FIXTURE, stage, links) if FIXTURE.get('demo_recording') or FIXTURE.get('policy')
                     else None)
            demo_cameras = views if FIXTURE.get('demo_recording') else None
            for _ in range(20):
                world.render()
            print('CONTAINER_RENDER_RECEIPT', type(video_camera.get_current_frame().get('rendering_frame')).__name__, reference_time(), flush=True)
            recording = ContainerRecording(args.report.parent, world, video_camera, config, reference_time, demo_cameras=demo_cameras)
        from policy_client import start
        policy, observe = start(FIXTURE['policy'], views) if container and FIXTURE.get('policy') else (None, None)
        try:
            if recording is not None:
                recording.write(0, robots[0].get_joint_positions()[joint_indices[0]])
            report = execute(args, world, stage, robots, joint_indices, fingers, cargo, contacts, capture, grasp_probes,
                planner, initial, tcp_position, fixture=FIXTURE, recording=recording,
                wrists=wrist_views if container else None, observe=observe, policy=policy)
        finally:
            if recording is not None:
                recording.close()
            if policy is not None:
                policy.close()
        if recording is not None:
            report['video'] = recording.manifest()
        return report

    return run_ppo_stacking(args, world, stage, robots, links, joint_indices, fingers, cargo, contacts,
                            plan, profile, capture, tcp_position, initial, mapped=mapped, fixture=FIXTURE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--mapped-long-stack', action='store_true')
    modes.add_argument('--mapped-cube-stack', action='store_true')
    modes.add_argument('--mapped-container-stack', action='store_true')
    modes.add_argument('--mapped-rl', action='store_true')
    parser.add_argument('--layers', type=int, choices=(1, 3), default=3)
    parser.add_argument('--container-case', choices=('nominal', 'offset', 'reverse', 'column', 'nominal-estimate', 'nominal-bc-v0',
                                 'nominal-bc-v0-rl0', 'release-episodes-rl0', 'release-episodes-rl1',
                                 'release-episodes-rl2', 'release-episodes-rl3', 'nominal-bc-v0-rl3',
                                 'nominal-bc-v0-release8', 'nominal-release3', 'nominal-gap6-release3',
                                 'nominal-palletizing-v21', 'nominal-palletizing-v21-hold', 'nominal-palletizing-v21-ship',
                                 *('nominal-palletizing-v21-ship-'+n for n in ('y060-c2-g315', 'y060-c2-seat-g315', 'y080-c2-g315', 'y080-c2-seat-g315', 'surveyed-bases-demo', 'surveyed-bases-wrist-demo', 'policy-smoke', 'demo', 'surveyed-bases', 'surveyed', 'surveyed-skew-20261110', 'r08-berth-v16', 'y040', 'y050', 'y060', 'y-060', 'x150', 'y020', 'y030', 'x100', 'y-020', 'y-030', 'g315', 'y020-g315', 'y030-g315', 'y040-g315', 'y-020-g315', 'y-030-g315', 'g3225', 'y060-g315', 'y060-guard-g315', 'r290-g315', 'y080-r290-g315', 'y100-r290-guard-g315', 'y050-g315', 'y100-r290-g315', 'y-080-r290-g315', 'w05-g315', 'y060-r290-g315', 'y070-r290-g315', 'y-060-r290-g315', 'y-070-r290-g315', 'w10-g315', 'w05-r290-g315', 'w10-r290-g315', 'y020-g3225', 'y030-g3225', 'y040-g3225', 'y-020-g3225'))),
                        default='nominal')
    args = parser.parse_args()
    check_vendor_manifest()
    if args.mapped_long_stack or args.mapped_rl or args.mapped_cube_stack or args.mapped_container_stack:
        from mapped_stack_fixture import physical_model
        # The original remains unchanged; the visual-only TCP is restored as a nonphysical USD child of link5.
        model = physical_model(args.urdf)
        path = args.report.parent/'physical-omx.urdf'
        with path.open('xb') as stream:
            model.write(stream, encoding='utf-8', xml_declaration=True)
        args.urdf = path
    check_urdf(args.urdf, 'omx_f', allow_package=False)
    args.output_dir.mkdir()
    from isaacsim import SimulationApp
    app = SimulationApp(dict(headless=True, fast_shutdown=False, width=800, height=600))
    try:
        report = run(args)
    finally:
        from sdk_entrypoint import close_sdk
        close_sdk(app, headless=True)
    from importlib.metadata import version
    report['sdk_version'] = version('isaacsim')
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())


if __name__ == '__main__':
    from sdk_entrypoint import run_cli
    run_cli(main)
