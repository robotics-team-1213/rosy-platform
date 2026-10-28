"""Contact-driven OMX-F stacking environment and a bounded RSL-RL PPO smoke run."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import xml.etree.ElementTree as ET

from stacking_fixture import BELT_TOP, DT, FIXTURE, UNIT, placed, stack_plan, target
from importer_compat import import_model, reference_model
from model_checks import check_urdf, check_vendor_manifest
from run_omx_backend import (PAD_RADIUS, PAD_HALF_LENGTH, PAD_CONTACT_OFFSET_M, PAD_REST_OFFSET_M,
                            FOLLOWER_STIFFNESS, FOLLOWER_DAMPING, FOLLOWER_MAX_EFFORT_NM, jaw_contact_point)


def run(args):
    import numpy as np
    import torch
    from tensordict import TensorDict
    import omni.kit.app
    import omni.kit.commands
    import omni.usd
    from pxr import Gf, Usd, UsdGeom, UsdLux, UsdPhysics, UsdShade, PhysxSchema
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
    for prim, base in zip((first, second), FIXTURE['arm_bases_m']):
        UsdGeom.XformCommonAPI(prim).SetTranslate(Gf.Vec3d(*base))
    world = World(physics_dt=DT, rendering_dt=DT, stage_units_in_meters=1.)
    mat = PhysicsMaterial('/World/GripMaterial', static_friction=1., dynamic_friction=1., restitution=0.)

    def fixed(name, position, size, color):
        return world.scene.add(FixedCuboid('/World/'+name, name=name, size=1.,
            position=np.array(position), scale=np.array(size), color=np.array(color), physics_material=mat))

    fixed('Table', [0., 0., -.025], [1.8, 1.8, .05], [.30, .32, .34])
    belt = fixed('Conveyor', [.20, -.28, .0125], FIXTURE['belt_size_m'], [.12, .15, .18])
    surface = PhysxSchema.PhysxSurfaceVelocityAPI.Apply(belt.prim)
    surface.CreateSurfaceVelocityAttr(Gf.Vec3f(0., FIXTURE['belt_speed_m_s'], 0.))
    fixed('BeltStop', [.20, -.029, .035], [.12, .004, .02], [.65, .65, .65])
    fixed('Bin', [.20, .02, .0125], [.09, .09, .025], [.15, .48, .7])
    origin = np.array(FIXTURE['bin_origin_m'])
    for axis in range(3):
        others = [i for i in range(3) if i != axis]
        for ai, a in enumerate((0., .09)):
            for bi, b in enumerate((0., .09)):
                center = origin.copy()
                center[axis] += .045
                center[others] += [a, b]
                size = np.full(3, .0007); size[axis] = .09
                name = f'Envelope{axis}_{ai}_{bi}'
                world.scene.add(VisualCuboid('/World/'+name, name=name, size=1.,
                    position=center, scale=size, color=np.array([.95, .8, .12])))
    for axis in range(2):
        for n in (1, 2):
            center = origin+np.array([.045, .045, .0001])
            center[axis] = origin[axis]+UNIT*n
            size = np.array([.09, .09, .0002]); size[axis] = .0004
            name = f'Grid{axis}_{n}'
            world.scene.add(VisualCuboid('/World/'+name, name=name, size=1.,
                position=center, scale=size, color=np.ones(3)))
    # The target is an open cargo envelope; walls would consume the zero-clearance packing space.
    for i, x in enumerate((.154, .246)):
        fixed('Boundary'+str(i), [x, .02, .001], [.001, .092, .002], [.95, .8, .12])
    light = UsdLux.DomeLight.Define(stage, '/World/Light')
    light.CreateIntensityAttr(1600.)
    robots, links, joint_indices, fingers = [], [], [], []
    for root in (first, second):
        prims = list(Usd.PrimRange(root))
        roots = [p for p in prims if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise RuntimeError('Each OMX reference requires one articulation')
        tool = {p.GetName(): str(p.GetPath()) for p in prims
                if p.GetName() in ('link6', 'link7', 'end_effector_link')}
        if set(tool) != {'link6', 'link7', 'end_effector_link'}:
            raise RuntimeError('Each OMX requires both finger and TCP links')
        links.append(tool)
        for prim in prims:
            if prim.IsA(UsdPhysics.RevoluteJoint):
                finger = prim.GetName().startswith('gripper')
                drive = UsdPhysics.DriveAPI.Apply(prim, 'angular')
                drive.CreateTypeAttr('force')
                drive.CreateStiffnessAttr(30. if finger else 5000.)
                drive.CreateDampingAttr(2. if finger else 100.)
                drive.CreateMaxForceAttr(.2 if finger else 30.)
                if prim.GetName() == 'gripper_joint_2':
                    drive.CreateStiffnessAttr(FOLLOWER_STIFFNESS)
                    drive.CreateDampingAttr(FOLLOWER_DAMPING)
                    drive.CreateMaxForceAttr(FOLLOWER_MAX_EFFORT_NM)
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
            for prim in Usd.PrimRange(body):
                if prim.HasAPI(UsdPhysics.CollisionAPI):
                    UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Set(False)
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
        robot = world.scene.add(Robot(str(roots[0].GetPath()), name='arm'+str(len(robots))))
        robots.append(robot)
    plan = stack_plan()
    colors = {1: [.03, .08, .24], 2: [.15, .65, .25], 3: [.95, .4, .08]}
    cargo, contacts = [], []
    filters = [link[key] for link in links for key in ('link6', 'link7')]
    for i, item in enumerate(plan):
        box = world.scene.add(DynamicCuboid('/World/Cargo'+str(i), name='cargo'+str(i), size=1.,
            scale=np.array([UNIT*item['cells'], UNIT, UNIT]), mass=.02*item['cells'],
            position=np.array([.7, -.5+i*.065, .015]), color=np.array(colors[item['cells']]), physics_material=mat))
        cargo.append(box)
        contacts.append(world.scene.add(RigidPrim('/World/Cargo'+str(i), name='contact'+str(i),
            track_contact_forces=True, contact_filter_prim_paths_expr=filters+['/World/Bin']+
            ['/World/Cargo'+str(j) for j in range(len(plan)) if j != i], max_contact_count=128)))
    eye = Gf.Vec3d(.75, -.75, .65)
    look = Gf.Matrix4d().SetLookAt(eye, Gf.Vec3d(.13, -.07, .06), Gf.Vec3d(0., 0., 1.)).GetInverse()
    rotation = look.ExtractRotationQuat()
    camera = Camera('/World/Observer', position=np.array(eye), resolution=(800, 600))
    world.reset()
    camera.initialize()
    camera.set_world_pose(np.array(eye), np.array([rotation.GetReal(), *rotation.GetImaginary()]), camera_axes='usd')
    camera.set_clipping_range(.01, 10.)
    camera.prim.GetAttribute('focalLength').Set(18.)
    camera.prim.GetAttribute('horizontalAperture').Set(36.)
    camera.prim.GetAttribute('verticalAperture').Set(27.)
    limits_by_name = {joint.get('name'): [float(joint.find('limit').get(key)) for key in ('lower', 'upper')]
                      for joint in ET.parse(args.urdf).getroot().iter('joint')
                      if joint.get('type') in ('revolute', 'prismatic')}
    joint_limits = []
    for robot in robots:
        joint_indices.append([robot.get_dof_index('joint'+str(i)) for i in range(1, 6)])
        fingers.append([robot.get_dof_index('gripper_joint_1'), robot.get_dof_index('gripper_joint_2')])
        joint_limits.append(np.array([limits_by_name[name] for name in robot.dof_names]))

    class StackingEnv:
        # shortcut: one CPU-facing SDK world, use Isaac Lab vector scenes when measured rollout throughput is limiting.
        num_envs, num_actions, max_episode_length, device = 1, 12, 600, 'cuda:0'
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
            for i, box in enumerate(cargo):
                box.set_world_pose(np.array([.7, -.5+i*.065, .015]), np.array([1., 0., 0., 0.]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
            for i, robot in enumerate(robots):
                state = np.zeros(robot.num_dof)
                state[joint_indices[i]] = [0., -.4, .7, 1.27, 0.]
                state[fingers[i]] = [1., -1.]
                robot.set_joint_positions(state)
                robot.set_joint_velocities(np.zeros(robot.num_dof))
                robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
            self.activate()
            for _ in range(12):
                world.step(render=False, update_fabric=True)
            return self.get_observations()

        def activate(self):
            jitter = self.rng.uniform(-.003, .003, 2)
            yaw = self.rng.uniform(-.03, .03)
            cargo[self.index].set_world_pose(np.array([.20+jitter[0], -.09+jitter[1], BELT_TOP+.015+.001]),
                np.array([math.cos(yaw/2), 0., 0., math.sin(yaw/2)]))
            cargo[self.index].set_linear_velocity(np.zeros(3))
            cargo[self.index].set_angular_velocity(np.zeros(3))
            self.lifted, self.settle = False, 0

        def measured(self, index):
            position, orientation = cargo[index].get_world_pose()
            vectors = np.asarray(contacts[index].get_contact_force_matrix(dt=DT))[0]
            force = np.linalg.norm(vectors[:4], axis=-1)
            speed = max(float(np.linalg.norm(cargo[index].get_linear_velocity())),
                        UNIT*float(np.linalg.norm(cargo[index].get_angular_velocity())))
            return position, dict(position=position.tolist(), orientation=orientation.tolist(), speed=speed,
                finger_force=float(force.sum()), support_force=max(0., float(vectors[4:, 2].sum())),
                lifted=self.lifted), force

        def get_observations(self):
            values = []
            for robot in robots:
                values.extend(robot.get_joint_positions().tolist())
                values.extend(robot.get_joint_velocities().tolist())
            p, q = cargo[self.index].get_world_pose()
            values.extend(p); values.extend(q)
            values.extend(cargo[self.index].get_linear_velocity())
            values.extend(target(plan[self.index]))
            values.extend([self.index/len(plan), float(self.lifted), plan[self.index]['cells']/3,
                           float(plan[self.index]['arm'])])
            obs = torch.tensor([values], dtype=torch.float32, device=self.device)
            if not torch.isfinite(obs).all():
                raise RuntimeError('Nonfinite stacking observation')
            return TensorDict({'policy': obs}, batch_size=[1])

        def step(self, actions):
            action = actions.detach().clamp(-1., 1.).cpu().numpy()[0]
            if not np.isfinite(action).all():
                raise ValueError('Finite policy actions required')
            active = plan[self.index]['arm']
            for i, robot in enumerate(robots):
                if i != active:
                    continue
                state = robot.get_joint_positions().copy()
                limits = joint_limits[i]
                idx = joint_indices[i]
                state[idx] = np.clip(state[idx]+.03*action[i*6:i*6+5], limits[idx, 0], limits[idx, 1])
                opening = -.12+1.12*(action[i*6+5]+1)/2
                state[fingers[i]] = [opening, -opening]
                robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=state))
            for _ in range(FIXTURE['control_decimation']):
                world.step(render=False, update_fabric=True)
            self.transitions += 1
            self.episode_length_buf += 1
            p, sample, force = self.measured(self.index)
            self.lifted |= bool(p[2] > BELT_TOP+.015+.02 and np.all(force[2*active:2*active+2] > .005))
            sample['lifted'] = self.lifted
            good = placed(plan[self.index], **sample)
            self.settle = self.settle+1 if good else 0
            tcp = np.array(UsdGeom.XformCache().GetLocalToWorldTransform(
                stage.GetPrimAtPath(links[active]['end_effector_link'])).ExtractTranslation())
            reach = float(np.linalg.norm(tcp-p))
            distance = float(np.linalg.norm(p-np.array(target(plan[self.index]))))
            reward = math.exp(-20*reach)+float(self.lifted)*(2+2*math.exp(-25*distance))-.01*float(np.square(action).sum())
            done = bool(p[2] < -.01 or np.linalg.norm(p[:2]) > .6)
            for i in range(self.index):
                _, previous, _ = self.measured(i)
                previous['lifted'] = True
                # New loads may increase support forces; any displaced earlier cargo invalidates this stack.
                done |= not placed(plan[i], **previous)
            success = not done and self.settle >= FIXTURE['settle_steps']
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

    def capture(name):
        for _ in range(8):
            world.render()
        rgba = camera.get_rgba()
        if rgba is None or rgba.shape != (600, 800, 4):
            raise RuntimeError('Actual SDK image unavailable')
        Image.fromarray(rgba.astype(np.uint8)).save(args.report.parent/name)

    # Observe uncommanded cargo transport on the belt before any policy is applied.
    start = cargo[0].get_world_pose()[0].copy()
    for _ in range(120):
        world.step(render=False, update_fabric=True)
    belt_motion = (cargo[0].get_world_pose()[0]-start).tolist()
    capture('stacking-initial.png')
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
    args = parser.parse_args()
    check_vendor_manifest()
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
