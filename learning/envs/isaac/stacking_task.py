"""Contact-driven OMX-F stacking environment and a bounded RSL-RL PPO smoke run."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from stacking_fixture import BELT_TOP, DT, FIXTURE, PROFILE, UNIT, advance_joint, placed, stack_plan, target
from importer_compat import import_model, reference_model
from model_checks import check_urdf, check_vendor_manifest
from run_omx_backend import (PAD_RADIUS, PAD_HALF_LENGTH, PAD_CONTACT_OFFSET_M, PAD_REST_OFFSET_M,
                            FOLLOWER_STIFFNESS, FOLLOWER_DAMPING, FOLLOWER_MAX_EFFORT_NM, jaw_contact_point)


def run(args):
    global FIXTURE
    mapped = args.mapped_long_stack or args.mapped_rl or args.mapped_cube_stack
    if mapped:
        from mapped_stack_fixture import FIXTURE
        if args.mapped_rl:
            from mapped_stack_fixture import RL_FIXTURE as FIXTURE
        elif args.mapped_cube_stack:
            from mapped_stack_fixture import CUBE_FIXTURE as FIXTURE
    import numpy as np
    import torch
    import yaml
    from tensordict import TensorDict
    import omni.kit.app
    import omni.kit.commands
    import omni.usd
    from pxr import Gf, Sdf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, PhysxSchema
    from isaacsim.core.api import World
    from isaacsim.core.api.robots import Robot
    from isaacsim.core.api.objects import DynamicCuboid, FixedCuboid, VisualCuboid
    from isaacsim.core.api.materials import PhysicsMaterial
    from isaacsim.core.prims import RigidPrim
    from isaacsim.core.utils.types import ArticulationAction
    from isaacsim.sensors.camera import Camera
    from PIL import Image
    from rsl_rl.runners import OnPolicyRunner

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

    def fixed(name, position, size, color):
        return world.scene.add(FixedCuboid('/World/'+name, name=name, size=1.,
            position=np.array(position), scale=np.array(size), color=np.array(color), physics_material=mat))

    fixed('Table', FIXTURE.get('workplate_center_m', [0., -.20, -.025] if mapped else [0., 0., -.025]),
          FIXTURE.get('workplate_size_m', [.9, .8, .05] if mapped else [1.8, 1.8, .05]),
          [.85, .66, .05] if mapped else [.30, .32, .34])
    belt = fixed('Conveyor', FIXTURE.get('belt_center_m', [.16 if mapped else .20, -.28, .0125]), FIXTURE['belt_size_m'], [.12, .15, .18])
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
            fixed('BeltRail'+str(i), center, [FIXTURE['belt_size_m'][0], .004, .005], [.65, .65, .65])
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
    fixed('Bin', [FIXTURE['bin_origin_m'][0]+.045, 0., FIXTURE['bin_origin_m'][2]-.001] if floor else
          ([.16, FIXTURE['bin_origin_m'][1]+FIXTURE['bin_size_m'][1]/2, .0125] if mapped else [.20, .02, .0125]),
          [.09, FIXTURE['bin_size_m'][1] if mapped else .09, .002 if floor else .025], [.30, .32, .34] if floor else [.15, .48, .7])
    if mapped:
        from mapped_stack_task import build_map
        build_map(world, stage, FIXTURE)
    origin = np.array(FIXTURE['bin_origin_m'])
    for axis in range(3):
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
            UsdGeom.XformCommonAPI(frame).SetTranslate(Gf.Vec3d(.09193, -.0016, 0.))
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
                drive.CreateMaxForceAttr(.2 if finger else (FIXTURE['arm_max_effort_nm'] if mapped else 30.))
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
        x, y = jaw_contact_point()
        for finger, side in (('link6', 1), ('link7', -1)):
            body = stage.GetPrimAtPath(tool[finger])
            disabled = 0
            for prim in Usd.PrimRange(body):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
                    disabled += 1
            if disabled == 0:
                raise RuntimeError('Imported finger collision hull was not found')
            pad = UsdGeom.Capsule.Define(stage, body.GetPath().AppendChild('grip_pad'))
            pad.CreateAxisAttr('Z'); pad.CreateRadiusAttr(PAD_RADIUS); pad.CreateHeightAttr(2*PAD_HALF_LENGTH)
            UsdGeom.Xformable(pad).AddTranslateOp().Set(Gf.Vec3d(x, side*(y+PAD_RADIUS), 0.))
            pad.CreatePurposeAttr('guide')
            UsdPhysics.CollisionAPI.Apply(pad.GetPrim())
            offsets = PhysxSchema.PhysxCollisionAPI.Apply(pad.GetPrim())
            offsets.CreateContactOffsetAttr(PAD_CONTACT_OFFSET_M)
            offsets.CreateRestOffsetAttr(PAD_REST_OFFSET_M)
            UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(UsdShade.Material.Get(stage, '/World/GripMaterial'),
                UsdShade.Tokens.weakerThanDescendants, 'physics')
            enabled = [p for p in Usd.PrimRange(body) if p.HasAPI(UsdPhysics.CollisionAPI)
                       and UsdPhysics.CollisionAPI(p).GetCollisionEnabledAttr().Get()]
            if len(enabled) != 1 or enabled[0].GetPath() != pad.GetPath():
                raise RuntimeError('Each finger requires exactly its calibrated capsule collider')
        robot = world.scene.add(Robot(articulation_path, name='arm'+str(len(robots))))
        robots.append(robot)
    if mapped:
        from mapped_stack_fixture import plan as mapped_plan
        plan = mapped_plan(args.mapped_cube_stack)
    else:
        plan = stack_plan()
    colors = {1: [.03, .08, .24], 2: [.15, .65, .25], 3: [.95, .4, .08]}
    cargo, contacts = [], []
    filters = [link[key] for link in links for key in ('link6', 'link7')]
    for i, item in enumerate(plan):
        box = world.scene.add(DynamicCuboid('/World/Cargo'+str(i), name='cargo'+str(i), size=1.,
            scale=np.array([UNIT*item['cells'], UNIT, UNIT]), mass=.02*item['cells'],
            position=np.array([.7, -.5+i*.065, .015]), color=np.array(colors[item['cells']]), physics_material=mat))
        cargo.append(box)
        if mapped:
            # Resolve the small stacked contacts with the same solver budget as the arms.
            body = PhysxSchema.PhysxRigidBodyAPI.Apply(box.prim)
            body.CreateSolverPositionIterationCountAttr(64)
            body.CreateSolverVelocityIterationCountAttr(16)
            assert body.GetSolverVelocityIterationCountAttr().Get() == 16
        contacts.append(world.scene.add(RigidPrim('/World/Cargo'+str(i), name='contact'+str(i),
            track_contact_forces=True, contact_filter_prim_paths_expr=filters+['/World/Bin']+(['/World/Conveyor'] if mapped else [])+
            ['/World/Cargo'+str(j) for j in range(len(plan)) if j != i], max_contact_count=512 if args.mapped_cube_stack else 128)))
    eye = Gf.Vec3d(.60, -.62, .48)
    wrist_views = []
    if mapped:
        for i, link in enumerate(links):
            path = stage.GetPrimAtPath(link['end_effector_link']).GetParent().GetPath()
            wrist_views.append(world.scene.add(RigidPrim(str(path), name='wrist_pose'+str(i))))
    grasp_probes = []
    probe_filters = ['/World/Table', '/World/PlywoodMap', '/World/Conveyor', '/World/BeltStop', '/World/Bin']+[
        '/World/Cargo'+str(i) for i in range(len(plan))]
    if args.mapped_long_stack or args.mapped_cube_stack:
        body_paths = [[str(p.GetPath()) for p in Usd.PrimRange(root) if p.HasAPI(UsdPhysics.RigidBodyAPI)]
                      for root in (first, second)]
        for i in range(2):
            views = []
            filters = probe_filters+body_paths[1-i]
            for j, path in enumerate(body_paths[i][1:]):
                view = world.scene.add(RigidPrim(path, name=f'grasp_probe_{i}_{j}', track_contact_forces=True,
                    contact_filter_prim_paths_expr=filters, max_contact_count=128))
                views.append((path, view))
            grasp_probes.append((filters, views))
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

    def capture(name, overview=False):
        position = Gf.Vec3d(2.2, -2.2, 3.) if overview else eye
        focus = Gf.Vec3d(0., 1.1, 0.) if overview else Gf.Vec3d(.13, -.10, .12)
        up = Gf.Vec3d(0., 0., 1.)
        if name == 'mapped-top.png':
            position, focus, up = Gf.Vec3d(.16, .10, 1.25), Gf.Vec3d(.16, .10, 0.), Gf.Vec3d(0., 1., 0.)
        elif name == 'mapped-side.png':
            position, focus = Gf.Vec3d(.8, -.05, .16), Gf.Vec3d(.03, 0., .08)
        rotation = Gf.Matrix4d().SetLookAt(position, focus, up).GetInverse().ExtractRotationQuat()
        camera.set_world_pose(np.array(position), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
        for _ in range(8):
            world.render()
        rgba = camera.get_rgba()
        if rgba is None or rgba.shape != (600, 800, 4):
            raise RuntimeError('Actual SDK image unavailable')
        Image.fromarray(rgba.astype(np.uint8)).save(args.report.parent/name)

    if mapped:
        from mapped_stack_fixture import free_lift, home, stable_box, tcp_from_wrist
        from mapped_stack_task import Planner, apply_servo
        planner = Planner(args.report.parent)
        initial = planner.request('homes', bases=FIXTURE['arm_bases_m'],
            base_yaws=FIXTURE.get('arm_base_yaws_rad', [0., 0.]),
            points=[home(0, args.mapped_cube_stack), home(1, args.mapped_cube_stack)])

    def tcp_position(arm):
        positions, quaternions = wrist_views[arm].get_world_poses()
        return np.array(tcp_from_wrist(positions[0], quaternions[0]))

    if args.mapped_long_stack or args.mapped_cube_stack:
        from mapped_stack_task import execute
        return execute(args, world, stage, robots, joint_indices, fingers, cargo, contacts, capture, grasp_probes,
                       planner, initial, tcp_position)

    def goal(item):
        return item['target'] if mapped else target(item)

    def accepted(index, sample):
        if not mapped:
            return placed(plan[index], **sample)
        for i in range(2):
            tcp = tcp_position(i)
            if np.linalg.norm(tcp-np.array(sample['position'])) < .04:
                return False
        return sample['lifted'] and stable_box(sample['body'], index)

    class StackingEnv:
        # shortcut: one CPU-facing SDK world, use Isaac Lab vector scenes when measured rollout throughput is limiting.
        num_envs, num_actions, max_episode_length, device = 1, 12, FIXTURE.get('max_episode_steps', 600), 'cuda:0'
        cfg = dict(FIXTURE)

        def __init__(self):
            self.episode_length_buf = torch.zeros(1, dtype=torch.long, device=self.device)
            self.transitions = self.completed = self.episodes = 0
            self.rng = np.random.default_rng(args.seed)
            self.belt_start = self.belt_observed = None
            self.auto_reset = True
            self.reset()

        def reset(self, seed=None):
            if seed is not None:
                self.rng = np.random.default_rng(seed)
            self.index, self.lifted, self.settle = 0, False, 0
            self.episode_length_buf.zero_()
            self.targets, self.target_velocities = [], []
            for i, box in enumerate(cargo):
                box.set_world_pose(np.array([-.45, .4+i*.065, .016] if mapped else [.7, -.5+i*.065, .015]), np.array([1., 0., 0., 0.]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
                if mapped:
                    UsdGeom.Imageable(box.prim).MakeInvisible()
            for i, robot in enumerate(robots):
                state = np.zeros(robot.num_dof)
                state[joint_indices[i]] = initial['homes'][i] if mapped else [0., -.4, .7, 1.27, 0.]
                state[fingers[i]] = [1., -1.]
                robot.set_joint_positions(state)
                robot.set_joint_velocities(np.zeros(robot.num_dof))
                robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
                self.targets.append(state.copy())
                self.target_velocities.append(np.zeros(robot.num_dof))
            self.activate()
            for _ in range(12):
                if mapped:
                    for i, robot in enumerate(robots):
                        apply_servo(robot, self.targets[i], joint_indices[i], fingers[i])
                for _ in range(FIXTURE.get('physics_substeps', 1)):
                    world.step(render=False, update_fabric=True)
            return self.get_observations()

        def activate(self):
            jitter = self.rng.uniform(-.003, .003, 2)
            yaw = self.rng.uniform(-.03, .03)
            cargo[self.index].set_world_pose(np.array([(.16 if mapped else .20)+jitter[0], -.09+jitter[1], BELT_TOP+.015+.001]),
                np.array([math.cos(yaw/2), 0., 0., math.sin(yaw/2)]))
            cargo[self.index].set_linear_velocity(np.zeros(3))
            cargo[self.index].set_angular_velocity(np.zeros(3))
            if mapped:
                UsdGeom.Imageable(cargo[self.index].prim).MakeVisible()
            self.lifted, self.settle = False, 0

        def measured(self, index):
            position, orientation = cargo[index].get_world_pose()
            vectors = np.asarray(contacts[index].get_contact_force_matrix(dt=FIXTURE.get('physics_dt_s', DT)))[0]
            force = np.linalg.norm(vectors[:4], axis=-1)
            speed = max(float(np.linalg.norm(cargo[index].get_linear_velocity())),
                        UNIT*float(np.linalg.norm(cargo[index].get_angular_velocity())))
            sample = dict(position=position.tolist(), orientation=orientation.tolist(), speed=speed,
                finger_force=float(force.sum()), support_force=max(0., float(vectors[4:, 2].sum())),
                lifted=self.lifted)
            if mapped:
                sample['body'] = dict(position=position.tolist(), orientation=orientation.tolist(),
                    velocity=cargo[index].get_linear_velocity().tolist(), angular_velocity=cargo[index].get_angular_velocity().tolist(),
                    forces=vectors.tolist(), net_force=np.asarray(contacts[index].get_net_contact_forces(dt=FIXTURE.get('physics_dt_s', DT)))[0].tolist())
            return position, sample, force

        def get_observations(self):
            values = []
            for robot in robots:
                values.extend(robot.get_joint_positions().tolist())
                values.extend(robot.get_joint_velocities().tolist())
            p, q = cargo[self.index].get_world_pose()
            values.extend(p); values.extend(q)
            values.extend(cargo[self.index].get_linear_velocity())
            values.extend(goal(plan[self.index]))
            values.extend([self.index/len(plan), float(self.lifted), plan[self.index]['cells']/3,
                           float(plan[self.index]['arm'])])
            obs = torch.tensor([values], dtype=torch.float32, device=self.device)
            if not torch.isfinite(obs).all():
                raise RuntimeError('Nonfinite stacking observation '+repr(dict(
                    step=self.transitions, cargo=self.index, values=values)))
            return TensorDict({'policy': obs}, batch_size=[1])

        def step(self, actions):
            action = actions.detach().clamp(-1., 1.).cpu().numpy()[0]
            if not np.isfinite(action).all():
                raise ValueError('Finite policy actions required')
            active = plan[self.index]['arm']
            braking = any(np.max(np.abs(self.target_velocities[i])) > 1e-8
                          for i in range(2) if i != active)
            for i, robot in enumerate(robots):
                moving = i == active and not braking
                state, speed = self.targets[i], self.target_velocities[i]
                control_dt = DT*FIXTURE['control_decimation']
                for n, idx in enumerate(joint_indices[i]):
                    limit = profile['joints']['joint'+str(n+1)]
                    state[idx], speed[idx] = advance_joint(state[idx], speed[idx],
                        action[i*6+n]*limit['velocity'] if moving else 0., limit, control_dt)
                grip = profile['gripper']
                idx = fingers[i][0]
                grip_goal = (grip['position'][0]+(grip['position'][1]-grip['position'][0])*(action[i*6+5]+1)/2
                        if moving else state[idx])
                opening, speed[idx] = advance_joint(state[idx], speed[idx], (grip_goal-state[idx])/control_dt, grip, control_dt)
                state[fingers[i]] = [opening, -opening]
                if not mapped:
                    robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
            for _ in range(FIXTURE['control_decimation']):
                if mapped:
                    for i, robot in enumerate(robots):
                        apply_servo(robot, self.targets[i], joint_indices[i], fingers[i])
                for _ in range(FIXTURE.get('physics_substeps', 1)):
                    world.step(render=False, update_fabric=True)
            self.transitions += 1
            self.episode_length_buf += 1
            p, sample, force = self.measured(self.index)
            self.lifted |= (free_lift(sample['body'], active, BELT_TOP+.015) if mapped else
                bool(p[2] > BELT_TOP+.015+.02 and np.all(force[2*active:2*active+2] > .005)))
            sample['lifted'] = self.lifted
            good = accepted(self.index, sample)
            if mapped:
                tcp = tcp_position(active)
            else:
                tcp = np.array(UsdGeom.XformCache().GetLocalToWorldTransform(
                    stage.GetPrimAtPath(links[active]['end_effector_link'])).ExtractTranslation())
            reach = float(np.linalg.norm(tcp-p))
            distance = float(np.linalg.norm(p-np.array(goal(plan[self.index]))))
            reward = math.exp(-20*reach)+float(self.lifted)*(2+2*math.exp(-25*distance))-.01*float(np.square(action).sum())
            done = bool(p[2] < -.01 or np.linalg.norm(p[:2]) > .6)
            for i in range(self.index):
                _, previous, _ = self.measured(i)
                previous['lifted'] = True
                # New loads may increase support forces; any displaced earlier cargo invalidates this stack.
                if mapped:
                    done |= np.max(np.abs(np.array(previous['position'])-np.array(goal(plan[i])))) > .01
                    good &= accepted(i, previous)
                else:
                    done |= not accepted(i, previous)
            self.settle = self.settle+1 if good else 0
            settle_steps = FIXTURE['settle_steps']//FIXTURE['control_decimation'] if mapped else FIXTURE['settle_steps']
            success = not done and self.settle >= settle_steps
            full_stack = success and self.index == len(plan)-1
            if success:
                reward += 20
                self.completed += 1
                if self.index == len(plan)-1:
                    done = True
                else:
                    self.index += 1
                    self.activate()
            timeout = bool(self.episode_length_buf[0] >= self.max_episode_length)
            info = dict(time_outs=torch.tensor([timeout and not done], device=self.device),
                        log={'Stack/placed': float(self.completed)}, stack_success=full_stack)
            done |= timeout
            if done:
                self.episodes += 1
                if self.auto_reset:
                    self.reset()
            return self.get_observations(), torch.tensor([reward], device=self.device), torch.tensor([done], device=self.device), info

    env = StackingEnv()

    # Observe uncommanded cargo transport on the belt before any policy is applied.
    start = cargo[0].get_world_pose()[0].copy()
    for _ in range(120):
        for _ in range(FIXTURE.get('physics_substeps', 1)):
            world.step(render=False, update_fabric=True)
    belt_motion = (cargo[0].get_world_pose()[0]-start).tolist()
    capture('stacking-initial.png')
    print('OMX_STACKING_SCENE_READY', json.dumps(dict(arms=2, cargo=len(plan),
        bin_size_m=FIXTURE['bin_size_m'], belt_displacement_m=belt_motion)), flush=True)
    env.reset()
    network = dict(class_name='MLPModel', hidden_dims=[64, 64], activation='elu', obs_normalization=True)
    cfg = dict(seed=args.seed, device=env.device, num_steps_per_env=32, save_interval=32,
        obs_groups={'actor': ['policy'], 'critic': ['policy']}, logger='tensorboard',
        actor=dict(network, distribution_cfg={'class_name': 'GaussianDistribution', 'init_std': .4}),
        critic=dict(network, distribution_cfg=None), algorithm=dict(class_name='PPO',
        num_learning_epochs=4, num_mini_batches=4, learning_rate=.0003, schedule='fixed', gamma=.99,
        lam=.95, entropy_coef=.005, desired_kl=.01, max_grad_norm=1., value_loss_coef=1.,
        use_clipped_value_loss=True, clip_param=.2))
    runner = OnPolicyRunner(env, cfg, log_dir=str(args.report.parent/'training'), device=env.device)
    before = torch.nn.utils.parameters_to_vector(runner.alg.get_policy().parameters()).detach().clone()
    runner.learn(num_learning_iterations=32, init_at_random_ep_len=False)
    after = torch.nn.utils.parameters_to_vector(runner.alg.get_policy().parameters()).detach()
    delta = float(torch.linalg.vector_norm(after-before))
    checkpoint = args.report.parent/'stacking-policy.pt'
    runner.save(str(checkpoint))
    trained_transitions = env.transitions
    policy = runner.get_inference_policy(device=env.device)
    env.auto_reset = False
    obs = env.reset(seed=args.seed+FIXTURE['evaluation_seed_offset'])
    evaluation_successes = 0
    for _ in range(env.max_episode_length):
        with torch.inference_mode():
            action = policy(obs)
        obs, _, done, info = env.step(action)
        evaluation_successes += int(info['stack_success'])
        if bool(done[0]):
            break
    capture('stacking-evaluation.png')
    stage.GetRootLayer().Export(str(args.report.parent/'stacking-scene.usda'))
    return dict(schema='rosy.omx-stacking-rl/1', fixture=FIXTURE, seed=args.seed,
        updates=32, transitions=trained_transitions, parameter_delta=delta,
        training_verified=bool(math.isfinite(delta) and delta > 0), task_success=evaluation_successes > 0,
        evaluation_seed=args.seed+FIXTURE['evaluation_seed_offset'], evaluation_episodes=1,
        evaluation_successes=evaluation_successes, evaluation_steps=env.transitions-trained_transitions,
        belt_displacement_m=belt_motion, articulations=[str(r.prim_path) for r in robots],
        joints=[list(r.dof_names) for r in robots], attachment_aid=False,
        checkpoint=dict(name=checkpoint.name, bytes=checkpoint.stat().st_size,
                        sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest()),
        images=['stacking-initial.png', 'stacking-evaluation.png'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--seed', type=int, required=True)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--mapped-long-stack', action='store_true')
    modes.add_argument('--mapped-cube-stack', action='store_true')
    modes.add_argument('--mapped-rl', action='store_true')
    args = parser.parse_args()
    check_vendor_manifest()
    if args.mapped_long_stack or args.mapped_rl or args.mapped_cube_stack:
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
