"""Bounded native Isaac map diagnostic with CPU residual Q-learning (D-638).

Uses the CORE final port in process, never ROS, Fleet or a robot endpoint.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import xml.etree.ElementTree as ET

from prepare_urdf import REPOSITORY, validate_output_path
from model_checks import check_urdf
from importer_compat import import_model, reference_model
from drive_runtime import configure_velocity_drive, configure_passive_drive, passive_caster_joints
from graph_contract import robot_contract
from map_task import load_track, MapTask, QPolicy, SimulationOwner


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--train-episodes', type=int, default=6)
    parser.add_argument('--time-limit', type=float, default=400.)
    parser.add_argument('--source-revision', required=True)
    args = parser.parse_args()
    if not 1 <= args.train_episodes <= 20 or not 0 < args.time_limit <= 600 or not math.isfinite(args.time_limit):
        raise ValueError('bounded episode count and time limit required')
    if len(args.source_revision) != 40 or any(c not in '0123456789abcdef' for c in args.source_revision):
        raise ValueError('exact committed source revision required')
    if os.environ.get('ROSY_CONFIG') or os.environ.get('ROSY_NAMESPACE'):
        raise ValueError('diagnostic refuses operational CORE environment')
    check_urdf(args.urdf, 'pinky', allow_package=False)
    passive = passive_caster_joints(ET.parse(args.urdf).getroot())
    output = validate_output_path(args.output_dir / 'result.json').parent
    output.mkdir(parents=True, exist_ok=False)
    for path in ('contracts/motion/src', 'contracts/skill/src', 'contracts/foundation',
                 'middleware/core/gateway', 'middleware/core/services'):
        sys.path.insert(0, str(REPOSITORY / path))
    track = load_track()
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'fast_shutdown': False, 'width': 640, 'height': 480,
                         'anti_aliasing': 0, 'extra_args': ['--/app/extensions/excluded=["isaacsim.gui.menu"]']})
    owner = None
    stop_robot = None
    summary = dict(source_revision=args.source_revision, map_sha256=track['source_sha256'],
                   segments=track['segments'], algorithm='CPU residual Q-learning, pursuit yaw gain',
                   operating_acceptance='HOLD', episodes=[])
    try:
        import numpy as np
        import omni.kit.app
        import omni.kit.commands
        import omni.usd
        from pxr import Gf, Sdf, Usd, UsdGeom, UsdPhysics
        manager = omni.kit.app.get_app().get_extension_manager()
        manager.set_extension_enabled_immediate('isaacsim.asset.importer.urdf', True)
        import isaacsim.asset.importer.urdf as urdf_api
        from isaacsim.core.api import World
        from isaacsim.robot.wheeled_robots.robots import WheeledRobot
        from isaacsim.robot.wheeled_robots.controllers import DifferentialController
        from core.bridge.cmd_vel import cmd_vel_cycle
        from rosy.contracts.motion import MotionIntent, MotionHeader, MotionKind, PriorityClass, BaseTwist

        usd_path = import_model(urdf_api, omni.kit.commands.execute, args.urdf, output, 'Wheeled')
        stage = reference_model(omni.usd.get_context(), usd_path, Usd, UsdGeom)
        app.update()
        roots = [str(p.GetPath()) for p in stage.Traverse() if p.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots) != 1:
            raise RuntimeError('single articulation root required: ' + repr(roots))
        contract = robot_contract('rosy_98')
        for name in (*contract['wheel_joints'], *passive):
            matches = [p for p in stage.Traverse() if p.GetName() == name and p.IsA(UsdPhysics.RevoluteJoint)]
            if len(matches) != 1:
                raise RuntimeError('unique joint required: ' + name)
            drive = UsdPhysics.DriveAPI.Apply(matches[0], 'angular')
            if name in passive:
                configure_passive_drive(drive)
            else:
                configure_velocity_drive(drive)
        world = World(stage_units_in_meters=1., physics_dt=1 / 60., rendering_dt=1 / 60.)
        world.scene.add_default_ground_plane(color=np.array([.3, .3, .3]))
        scene = track['scene']
        UsdGeom.Xform.Define(stage, '/World/Track')
        for i, wall in enumerate(scene.walls):
            cube = UsdGeom.Cube.Define(stage, f'/World/Track/wall_{i}')
            cube.CreateSizeAttr(1.)
            cube.AddTranslateOp().Set(Gf.Vec3d(wall.cx, wall.cy, wall.height / 2))
            cube.AddScaleOp().Set(Gf.Vec3d(wall.size_x, wall.size_y, wall.height))
            cube.CreateDisplayColorAttr([Gf.Vec3f(1.)])
            UsdPhysics.CollisionAPI.Apply(cube.GetPrim())
        paint = UsdGeom.Mesh.Define(stage, '/World/Track/paint')
        vertices = [Gf.Vec3f(*v) for t in scene.lines for v in t]
        paint.CreatePointsAttr(vertices)
        paint.CreateFaceVertexCountsAttr([3] * len(scene.lines))
        paint.CreateFaceVertexIndicesAttr(list(range(len(vertices))))
        paint.CreateSubdivisionSchemeAttr('none')
        paint.CreateDoubleSidedAttr(True)
        paint.CreateDisplayColorAttr([Gf.Vec3f(1.)])
        robot = world.scene.add(WheeledRobot(prim_path=roots[0], name='pinky',
                               wheel_dof_names=list(contract['wheel_joints']), create_robot=False))
        world.reset()
        diff = DifferentialController(name='pinky_diff', wheel_radius=contract['wheel_radius'],
                                      wheel_base=contract['wheel_distance'], max_linear_speed=.06,
                                      max_angular_speed=.8)
        owner = SimulationOwner()
        policy = QPolicy(seed=17)
        frame = 0
        epoch = 0
        power = type('DiagnosticPower', (), {'on_activity': lambda self, source: None})()

        def send(twist):
            robot.apply_wheel_actions(diff.forward(command=np.array([twist.linear, twist.angular])))

        def read_pose():
            position, quaternion = robot.get_world_pose()
            linear = robot.get_linear_velocity()
            angular = robot.get_angular_velocity()
            w, x, y, z = map(float, quaternion)
            yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
            values = (float(position[0]), float(position[1]), yaw,
                      math.hypot(float(linear[0]), float(linear[1])), float(angular[2]))
            if not all(math.isfinite(v) for v in (*values, *position, *quaternion, *linear, *angular)):
                raise RuntimeError('nonfinite physical readback')
            if abs(float(position[2])) > .1 or abs(x) > .3 or abs(y) > .3:
                raise RuntimeError('robot lost floor contact or tipped')
            return values

        def step():
            nonlocal frame
            if not app.is_running():
                raise RuntimeError('SDK stopped before task result')
            world.step(render=frame % 30 == 0)
            frame += 1

        def physical_stop():
            owner.stop()
            since = None
            begin = world.current_time
            while world.current_time - begin < 2.:
                cmd_vel_cycle(command=owner, power=power, send=send)
                step()
                pose = read_pose()
                if pose[3] < .005 and abs(pose[4]) < .02:
                    if since is None:
                        since = world.current_time
                    if world.current_time - since >= .3:
                        return dict(linear_mps=pose[3], angular_radps=pose[4],
                                    settle_s=world.current_time - begin)
                else:
                    since = None
            raise RuntimeError('actual stop not confirmed; reset refused')

        stop_robot = physical_stop
        summary['initial_stop'] = physical_stop()
        baseline = None
        for phase, seed in [('baseline', 101), *[('train', i) for i in range(args.train_episodes)],
                            ('eval', 202), ('eval', 303)]:
            physical_stop()
            rng = random.Random(seed)
            route = track['points']
            if phase == 'train':
                # shortcut: short route curricula learn local yaw correction; full-map eval must still pass.
                start = rng.randrange(0, len(route) - 120)
                route = route[start:start + 100]
            heading = math.atan2(route[1][1] - route[0][1], route[1][0] - route[0][0])
            heading += rng.uniform(-.025, .025)
            robot.set_world_pose(position=np.array([*route[0], .005]),
                                 orientation=np.array([math.cos(heading / 2), 0., 0., math.sin(heading / 2)]))
            robot.set_world_velocity(np.zeros(6))
            robot.set_joint_velocities(np.zeros(robot.num_dof))
            for _ in range(30):
                cmd_vel_cycle(command=owner, power=power, send=send)
                step()
            initial = read_pose()
            if math.dist(initial[:2], route[0]) > .015 or initial[3] >= .005 or abs(initial[4]) >= .02:
                raise RuntimeError('reset pose or rest readback differs')
            epoch += 1
            owner.begin(epoch)
            task = MapTask(route, half_size=(scene.size_x / 2, scene.size_y / 2),
                           time_limit=min(60., args.time_limit) if phase == 'train' else args.time_limit)
            start_time = world.current_time
            wall_start = time.monotonic()
            previous = None
            frozen = policy.export() if phase == 'eval' else None
            with (output / f'trace-{epoch}-{phase}-{seed}.jsonl').open('w') as trace:
                while True:
                    pose = read_pose()
                    now = time.monotonic()
                    elapsed = world.current_time - start_time
                    result = task.observe(*pose, elapsed)
                    state, speed, angular = task.pursuit(*pose[:3])
                    if phase == 'train' and previous is not None:
                        policy.update(*previous, result['reward'], state,
                                      terminated=result['terminated'] or result['truncated'])
                    action = 1 if phase == 'baseline' else policy.choose(state, explore=phase == 'train')
                    angular = max(-.8, min(.8, angular * policy.gains[action]))
                    if result['goal_reached'] or result['terminated'] or result['truncated']:
                        owner.stop()
                        speed, angular = 0., 0.
                    else:
                        intent = MotionIntent(MotionKind.BASE_TWIST,
                            MotionHeader(f'isaac:{epoch}:{frame}', 'isaac-pinky', 'learned_policy',
                                PriorityClass.POLICY, now, .1, envelope_ref='isaac-map-v1', state_sequence=epoch,
                                limits={'linear_mps': .06, 'angular_radps': .8}), BaseTwist(speed, angular))
                        owner.submit(intent, observed_at=now, now=now)
                    cmd_vel_cycle(command=owner, power=power, send=send)
                    trace.write(json.dumps(dict(frame=frame, sim_s=elapsed, wall_s=time.monotonic() - wall_start,
                                                pose=pose, action=action, candidate=[speed, angular], **result)) + '\n')
                    if result['terminated'] or result['truncated']:
                        break
                    if owner.halted and not result['goal_reached']:
                        raise RuntimeError('policy envelope HOLD during active route')
                    previous = (state, action)
                    step()
            episode = dict(phase=phase, seed=seed, epoch=epoch, **result,
                           sim_s=elapsed, wall_s=time.monotonic() - wall_start, stop=physical_stop())
            summary['episodes'].append(episode)
            print('EPISODE ' + json.dumps(episode), flush=True)
            if phase == 'baseline':
                baseline = result
            if phase == 'eval' and policy.export() != frozen:
                raise RuntimeError('evaluation mutated policy')
            if phase == 'train':
                (output / 'policy.json').write_text(json.dumps(policy.export(), sort_keys=True))
        summary['updates'] = policy.updates
        summary['policy_sha256'] = hashlib.sha256((output / 'policy.json').read_bytes()).hexdigest()
        summary['full_map_complete'] = all(e['complete'] for e in summary['episodes'] if e['phase'] == 'eval')
        summary['baseline_complete'] = baseline['complete']
        summary['final_stop'] = physical_stop()
        (output / 'result.json').write_text(json.dumps(summary, indent=2, sort_keys=True))
        print('RESULT ' + json.dumps(summary), flush=True)
        if not summary['full_map_complete']:
            raise RuntimeError('held-out full-map completion failed; candidate not accepted')
    except Exception as exc:
        summary['error'] = str(exc)
        (output / 'result.json').write_text(json.dumps(summary, indent=2, sort_keys=True))
        raise
    finally:
        try:
            if stop_robot is not None:
                summary['cleanup_stop'] = stop_robot()
        finally:
            app.close()


if __name__ == '__main__':
    from sdk_entrypoint import run_cli
    run_cli(main)
