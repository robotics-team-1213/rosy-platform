"""Bounded native Isaac map diagnostic with CPU residual Q-learning (D-638).

Uses the CORE final port in process, never ROS, Fleet or a robot endpoint.
"""
import argparse
from dataclasses import replace
import hashlib
import json
import math
import os
from pathlib import Path
import random
import sys
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'learning/envs/isaac'))
from prepare_urdf import REPOSITORY, validate_output_path
from model_checks import check_urdf
from importer_compat import import_model, reference_model
from drive_runtime import configure_velocity_drive, configure_passive_drive, passive_caster_joints, configure_contact_solver
from graph_contract import robot_contract
from map_task import MAP, load_track, MapTask, QPolicy, SimulationOwner
from floor_visuals import map_visual_profile, add_track_visuals, configure_ground_collision, verify_ground_collision
from camera_checks import (camera_tick, camera_episode_usable, camera_admission_error, camera_sample_due,
                           remember_camera_action, learn_transition, camera_snapshot_due, CameraLearningWindow)


def episode_phases(train_episodes, *, camera, evaluation_only):
    evaluations = ([(707, 0.), (808, math.pi / 2), (909, math.pi), (1001, -math.pi / 2)]
                   if evaluation_only else [(202, 0.), (303, 0.)] + ([(404, 0.)] if camera else []))
    phases = [] if evaluation_only else [('baseline', 101, 0.),
                                         *[('train', seed, 0.) for seed in range(train_episodes)]]
    return phases + [(phase, seed, angle) for seed, angle in evaluations
                     for phase in (('baseline', 'eval') if camera else ('eval',))]


def camera_route_guide(task, pose, result, stamp):
    ahead = task.index
    while ahead < len(task.points) - 1 and task.distance[ahead] - task.distance[task.index] < .25:
        ahead += 1
    dx, dy = task.points[ahead][0] - pose[0], task.points[ahead][1] - pose[1]
    centre = task.points[task.index]
    after = next((p for p in task.points[task.index + 1:] if math.dist(centre, p) > 1e-9), None)
    if after is None:
        before = next(p for p in reversed(task.points[:task.index]) if math.dist(centre, p) > 1e-9)
        local_x, local_y = centre[0] - before[0], centre[1] - before[1]
    else:
        local_x, local_y = after[0] - centre[0], after[1] - centre[1]
    relative = lambda x, y: math.degrees(math.atan2(math.sin(math.atan2(y, x) - pose[2]),
                                                   math.cos(math.atan2(y, x) - pose[2])))
    # A route tangent alone does not prove a Fleet turn spot or the native body's sweep clearance.
    return (relative(dx, dy), stamp, False, relative(local_x, local_y),
            result['deviation_m'], result['progress_m'])


def policy_state_sha256(state):
    return hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()


def camera_comparison(baseline, evaluated):
    fields = ('seed', 'initial_heading_offset_rad', 'initial_target_pose', 'time_limit_s', 'policy_state_sha256')
    if (baseline['phase'] != 'baseline' or evaluated['phase'] != 'eval'
            or evaluated['epoch'] != baseline['epoch'] + 1
            or any(baseline[key] != evaluated[key] for key in fields)):
        raise ValueError('paired camera evaluation conditions differ')
    before, after = baseline['initial_pose'], evaluated['initial_pose']
    if not all(math.isfinite(value) for value in (*before, *after)):
        raise ValueError('paired camera start is nonfinite')
    position_delta = math.dist(before[:2], after[:2])
    heading_delta = abs(math.atan2(math.sin(after[2] - before[2]), math.cos(after[2] - before[2])))
    # Match the native reset position tolerance and the configured initial heading jitter bound.
    if position_delta > .015 or heading_delta > .025:
        raise ValueError('paired camera physical starts differ')
    return dict(seed=evaluated['seed'], initial_heading_offset_rad=evaluated['initial_heading_offset_rad'],
                baseline_epoch=baseline['epoch'], eval_epoch=evaluated['epoch'],
                baseline_complete=baseline['complete'], eval_complete=evaluated['complete'],
                baseline_sim_s=baseline['sim_s'], eval_sim_s=evaluated['sim_s'],
                initial_position_delta_m=position_delta, initial_heading_delta_rad=heading_delta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--urdf', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--train-episodes', type=int, default=6)
    parser.add_argument('--time-limit', type=float, default=400.)
    parser.add_argument('--source-revision', required=True)
    parser.add_argument('--policy-file', type=Path, help='fixed saved policy; evaluate four initial directions')
    parser.add_argument('--record-video', action='store_true', help='record actual headless Isaac camera frames')
    parser.add_argument('--camera-model', type=Path, help='existing frozen perception model; CAMERA_LINE diagnostic')
    parser.add_argument('--camera-model-revision')
    parser.add_argument('--camera-model-sha256')
    args = parser.parse_args()
    if not 1 <= args.train_episodes <= 20 or not 0 < args.time_limit <= 600 or not math.isfinite(args.time_limit):
        raise ValueError('bounded episode count and time limit required')
    if len(args.source_revision) != 40 or any(c not in '0123456789abcdef' for c in args.source_revision):
        raise ValueError('exact committed source revision required')
    if os.environ.get('ROSY_CONFIG') or os.environ.get('ROSY_NAMESPACE'):
        raise ValueError('diagnostic refuses operational CORE environment')
    check_urdf(args.urdf, 'pinky', allow_package=False)
    for path in ('contracts/foundation', 'contracts/motion/src', 'contracts/skill/src',
                 'middleware/core/gateway', 'middleware/core/services', 'middleware/core/events', 'middleware/perception'):
        sys.path.insert(0, str(REPOSITORY / path))
    camera_args = (args.camera_model, args.camera_model_revision, args.camera_model_sha256)
    if any(camera_args) and not all(camera_args):
        raise ValueError('camera model folder, exact revision and SHA256 required together')
    perception_model = perception = None
    if args.camera_model:
        from camera_lane import CameraQPolicy, LearnedCameraLane, camera_model_identity
        from control.sensing.perception.learned.runner import LaneSegModel
        # The frozen v2 has no wall class; its lane-mask fallback cannot use the wall floor gate.
        perception_model = LaneSegModel.open(args.camera_model, threads=1, allow_spinning=False, floor_gate=False)
        perception = camera_model_identity(perception_model, revision=args.camera_model_revision,
                                            sha256=args.camera_model_sha256)
    saved = None
    policy_bytes = None
    if args.policy_file:
        with args.policy_file.open('rb') as policy_input:
            policy_bytes = policy_input.read(65537)
        if len(policy_bytes) > 65536:
            raise ValueError('bounded saved policy required')
        saved = (QPolicy.restore(json.loads(policy_bytes)) if perception is None else
                 CameraQPolicy.restore(json.loads(policy_bytes), perception=perception))
    passive = passive_caster_joints(ET.parse(args.urdf).getroot())
    output = validate_output_path(args.output_dir / 'result.json').parent
    output.mkdir(parents=True, exist_ok=False)
    track = load_track()
    from isaacsim import SimulationApp
    app = SimulationApp({'headless': True, 'fast_shutdown': False, 'width': 640, 'height': 480,
                         'anti_aliasing': 0, 'extra_args': ['--/app/extensions/excluded=["isaacsim.gui.menu"]']})
    owner = None
    stop_robot = None
    recorder = None
    camera = None
    front_camera = None
    lane = None
    policy = None
    summary = dict(source_revision=args.source_revision, map_sha256=track['source_sha256'],
                   segments=track['segments'], algorithm='CPU residual Q-learning, pursuit yaw gain',
                   operating_acceptance='HOLD', episodes=[], learning_steps={})
    if perception is not None:
        summary.update(algorithm='CPU residual Q-learning, existing CAMERA_LINE yaw gain', perception=perception,
                       camera_acceptance='HOLD', camera_guidance='map route direction + native odom, camera required')
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
        world = World(stage_units_in_meters=1., physics_dt=1 / 240., rendering_dt=1 / 240.)
        profile = map_visual_profile(MAP)
        ground = world.scene.add_ground_plane(size=profile['ground_size'],
            color=np.array(profile['ground_colour']), restitution=0.)
        summary['ground_collision'] = configure_ground_collision(stage, ground.prim_path)
        scene = track['scene']
        add_track_visuals(stage, track, profile)
        robot = world.scene.add(WheeledRobot(prim_path=roots[0], name='pinky',
                               wheel_dof_names=list(contract['wheel_joints']), create_robot=False))
        if args.record_video or perception is not None:
            from isaacsim.sensors.camera import Camera
            from pxr import UsdLux
            light = UsdLux.DomeLight.Define(stage, '/World/RecordingLight')
            light.CreateIntensityAttr(1000.)
        if args.record_video:
            # Explicit renders must refresh receipts even before physics time advances.
            camera = Camera(prim_path='/World/RecordingCamera', resolution=(960, 540), frequency=-1)
            camera.set_world_pose(position=np.array([0., 0., 2.]),
                                  orientation=np.array([1., 0., 0., 0.]), camera_axes='usd')
            camera.set_focal_length(20.)
            camera.set_horizontal_aperture(36.)
        if perception is not None:
            import yaml
            from control.sensing.perception.camera_ground import ground_plane
            from isaacsim.core.utils.rotations import quat_to_rot_matrix, rot_matrix_to_quat
            camera_profile = yaml.safe_load((REPOSITORY / 'middleware/devices/pinky/profile/config/camera_nominal.yaml').read_text())
            front_camera = Camera(prim_path='/World/FrontCamera', resolution=(320, 240), frequency=-1)
            default_clip = front_camera.get_clipping_range()
            # USD's 1 m near plane hides the Pinky's entire 0.6 m ground view.
            front_camera.set_clipping_range(.01, 10.)
            if not np.allclose(front_camera.get_clipping_range(), [.01, 10.]):
                raise RuntimeError('native front camera clipping differs')
            front_camera.set_focal_length(20.)
            front_camera.set_horizontal_aperture(320. * 20. / camera_profile['fx'])
            front_camera.set_vertical_aperture(240. * 20. / camera_profile['fx'])
            pitch = camera_profile['pitch_rad']
            mount_rotation = np.array([[math.cos(pitch), 0., math.sin(pitch)],
                                       [0., 1., 0.], [-math.sin(pitch), 0., math.cos(pitch)]])
            mount_position = np.array([camera_profile['x_offset_m'], 0., camera_profile['height_m']])

            def position_front_camera():
                base_position, base_orientation = robot.get_world_pose()
                rotation = quat_to_rot_matrix(base_orientation)
                position = base_position + rotation @ mount_position
                orientation = rot_matrix_to_quat(rotation @ mount_rotation)
                front_camera.set_world_pose(position=position, orientation=orientation, camera_axes='world')

        world.reset()
        verify_ground_collision(stage, ground.prim_path, summary['ground_collision'])
        solver_iterations = configure_contact_solver(robot)
        if front_camera is not None:
            from native_scan import NativeScan
            from core_common.robot_body import NOMINAL_BODY
            geometry = yaml.safe_load((REPOSITORY / 'middleware/devices/pinky/profile/config/geometry.yaml').read_text())
            scan_body = replace(NOMINAL_BODY, rotation_radius_m=geometry['footprint']['rotation_radius_sim_box_m'])
            native_scan = NativeScan(stage)
            front_camera.initialize()
            position_front_camera()
            intrinsics = front_camera.get_intrinsics_matrix()
            if not np.allclose(intrinsics, [[camera_profile['fx'], 0., 160.],
                                           [0., camera_profile['fx'], 120.], [0., 0., 1.]], atol=.001):
                raise RuntimeError('native camera intrinsics differ from configured geometry')
            summary['front_camera'] = dict(resolution=[320, 240], intrinsics=intrinsics.tolist(),
                default_clipping=list(default_clip), clipping=list(front_camera.get_clipping_range()),
                model_floor_gate=False,
                mount_position=mount_position.tolist(), pitch_rad=pitch,
                geometry='configured URDF nominal mount; native simulation, not physical calibration', sample_sim_s=.1)
        if camera is not None:
            camera.initialize()
            summary['recording'] = dict(kind='native Isaac camera RGBA', resolution=[960, 540],
                sample_sim_s=.2, encoded_fps=25, playback_speed=5., camera_axes='usd',
                position=[0., 0., 2.], orientation=[1., 0., 0., 0.])
        stiffness, damping = robot.get_articulation_controller().get_gains()
        summary['physics'] = dict(dt_s=world.get_physics_dt(), restitution=0.,
                                 solver_iterations=solver_iterations,
                                 dofs=robot.dof_names, stiffness=stiffness.tolist(), damping=damping.tolist())
        print('PHYSICS ' + json.dumps(summary['physics']), flush=True)
        diff = DifferentialController(name='pinky_diff', wheel_radius=contract['wheel_radius'],
                                      wheel_base=contract['wheel_distance'], max_linear_speed=.06,
                                      max_angular_speed=.8)
        owner = SimulationOwner()
        policy = saved or (QPolicy(seed=17) if perception is None else CameraQPolicy(seed=17, perception=perception))
        if saved is not None:
            (output / 'policy.json').write_bytes(policy_bytes)
            summary['evaluation_only'] = True
        frame = 0
        epoch = 0
        power = type('DiagnosticPower', (), {'on_activity': lambda self, source: None})()
        dispatch_receipts, cycle_warnings = [], []

        def send(twist):
            robot.apply_wheel_actions(diff.forward(command=np.array([twist.linear, twist.angular])))
            dispatch_receipts.append((twist.linear, twist.angular))

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
            # Camera episodes render explicitly at their local observation/recording cadence.
            world.step(render=front_camera is None and frame % (48 if recorder is not None else 30) == 0)
            frame += 1

        def physical_stop():
            owner.stop()
            since = None
            begin = world.current_time
            samples = []
            while world.current_time - begin < 2.:
                cmd_vel_cycle(command=owner, power=power, send=send)
                step()
                pose = read_pose()
                samples.append(dict(sim_s=world.current_time, pose=pose,
                                    z_m=float(robot.get_world_pose()[0][2]),
                                    joints=list(map(float, robot.get_joint_velocities()))))
                if pose[3] < .005 and abs(pose[4]) < .02:
                    if since is None:
                        since = world.current_time
                    if world.current_time - since >= .3:
                        return dict(linear_mps=pose[3], angular_radps=pose[4],
                                    settle_s=world.current_time - begin)
                else:
                    since = None
            (output / f'stop-failed-{frame}.json').write_text(json.dumps(samples, indent=2))
            raise RuntimeError('actual stop not confirmed; reset refused; last readback=' + repr(samples[-1]))

        stop_robot = physical_stop
        summary['initial_stop'] = physical_stop()
        baseline = None
        phases = episode_phases(args.train_episodes, camera=perception is not None,
                                evaluation_only=saved is not None)
        if perception is not None:
            summary['camera_comparisons'] = []
        for phase, seed, heading_offset in phases:
            physical_stop()
            rng = random.Random(seed)
            route = track['points']
            if phase == 'train':
                # shortcut: short route curricula learn local yaw correction; full-map eval must still pass.
                start = rng.randrange(0, len(route) - 120)
                route = route[start:start + 100]
            heading = math.atan2(route[1][1] - route[0][1], route[1][0] - route[0][0])
            heading += rng.uniform(-.025, .025)
            heading += heading_offset
            robot.set_world_pose(position=np.array([*route[0], .005]),
                                 orientation=np.array([math.cos(heading / 2), 0., 0., math.sin(heading / 2)]))
            robot.set_world_velocity(np.zeros(6))
            robot.set_joint_velocities(np.zeros(robot.num_dof))
            for _ in range(round(.5 / world.get_physics_dt())):
                cmd_vel_cycle(command=owner, power=power, send=send)
                step()
            initial = read_pose()
            if math.dist(initial[:2], route[0]) > .015 or initial[3] >= .005 or abs(initial[4]) >= .02:
                summary['reset_failure'] = dict(phase=phase, seed=seed, target_xy=route[0],
                    actual_pose=initial, position_error_m=math.dist(initial[:2], route[0]))
                raise RuntimeError('reset pose or rest readback differs: ' + json.dumps(summary['reset_failure']))
            epoch += 1
            owner.begin(epoch)
            if lane is not None:
                lane.close()
            lane = None
            if front_camera is not None:
                ground = ground_plane(camera_profile['height_m'] + float(robot.get_world_pose()[0][2]),
                    pitch, float(intrinsics[0, 0]), 160., 120., .6)
                lane = LearnedCameraLane(perception_model, ground, camera_x=camera_profile['x_offset_m'],
                                         body=scan_body)
                position_front_camera()
                for _ in range(20):
                    world.render()
            task = MapTask(route, half_size=(scene.size_x / 2, scene.size_y / 2),
                           time_limit=min(60., args.time_limit) if phase == 'train' else args.time_limit)
            start_time = world.current_time
            initial_pose = read_pose()
            wall_start = time.monotonic()
            episode_start_frame = frame
            previous = None
            last_applied = None
            camera_learning = CameraLearningWindow()
            frozen = policy.export() if phase == 'eval' or (perception is not None and phase == 'baseline') else None
            if phase == 'eval' and (policy.updates == 0 or not any(
                    value != 0. for values in policy.table.values() for value in values)):
                raise RuntimeError('no measured Q-learning update; rule fallback is not trained evaluation')
            learned_steps = 0
            camera_frames = camera_visible_frames = 0
            captured_failures = set()
            if camera is not None and (phase == 'eval' or (perception is not None and phase == 'baseline')):
                from native_recording import NativeRecorder
                # Initialize the native render product before accepting episode frames.
                for _ in range(20):
                    world.render()
                pixels = camera.get_rgba()
                if pixels.shape != (540, 960, 4) or np.ptp(pixels[:, :, :3]) < 20:
                    raise RuntimeError('native recording camera has no visible image')
                recorder = NativeRecorder(output / f'isaac-{phase}-{seed}.mp4')
            with (output / f'trace-{epoch}-{phase}-{seed}.jsonl').open('w') as trace:
                while True:
                    pose = read_pose()
                    recording_step = frame - episode_start_frame if perception is not None else frame - 1
                    if recorder is not None and (recorder.frames == 0 or recording_step % 48 == 0):
                        if perception is not None:
                            world.render()
                        image_frame = camera.get_current_frame()
                        recorder.write(camera.get_rgba(),
                            render_frame=image_frame['rendering_frame'],
                            render_time=float(image_frame['rendering_time']),
                            sim_s=world.current_time - start_time, pose=pose)
                    now = time.monotonic()
                    elapsed = world.current_time - start_time
                    result = task.observe(*pose, elapsed)
                    if lane is None:
                        state, speed, angular = task.pursuit(*pose[:3])
                    else:
                        if camera_sample_due(frame, episode_start_frame):
                            position_front_camera()
                            world.render()
                            image = front_camera.get_current_frame()
                            rgba = front_camera.get_rgba()
                            if rgba.shape != (240, 320, 4) or rgba.dtype != np.uint8:
                                lane.invalidate('invalid_native_camera')
                            else:
                                guide = camera_route_guide(task, pose, result, world.current_time)
                                if lane.observe_scan(native_scan.capture(world.current_time), body=scan_body):
                                    lane.observe(np.ascontiguousarray(rgba[:, :, 2::-1]),
                                        stamp=float(image['rendering_time']), source_now=world.current_time,
                                        pose=pose[:3], guide=guide)
                                if camera_snapshot_due(camera_frames, lane.last, captured_failures):
                                    import cv2
                                    name = (f'front-camera-{epoch}-{phase}-{seed}.png' if camera_frames == 0 else
                                            f'front-camera-failure-{epoch}-{phase}-{seed}-{camera_frames}.png')
                                    if not cv2.imwrite(str(output / name), rgba[:, :, 2::-1]):
                                        raise RuntimeError('native camera diagnostic frame could not be saved')
                                    lane.last['diagnostic_frame'] = name
                                    captured_failures.add((lane.last.get('reason'), lane.last.get('strategy')))
                            camera_frames += 1
                            camera_visible_frames += int(lane.observation is not None)
                        if lane.stamp is not None and world.current_time - lane.stamp > lane.manager.config.stale_after_s:
                            lane.invalidate('camera_source_stale')
                        state = lane.state()
                        now = time.monotonic()
                    learning_step = None
                    terminal_credit = None
                    if phase == 'train' and lane is None:
                        learning_step = learn_transition(policy, previous, state, result)
                    action = (camera_learning.choose(policy, state, lane.last.get('source_stamp'), frame=frame,
                              train=phase == 'train', baseline=phase == 'baseline') if lane is not None else
                              1 if phase == 'baseline' or state is None else policy.choose(state, explore=phase == 'train'))
                    if lane is None:
                        angular = max(-.8, min(.8, angular * policy.gains[action]))
                    else:
                        decision, state = camera_tick(lane, now, gain=policy.gains[action])
                        speed, angular = decision.linear, decision.angular
                        if lane.manager.status().state == 'LOST' and not result['terminated']:
                            result = dict(result, terminated=True, truncated=False, complete=False,
                                          reason='camera_lane_lost', reward=result['reward'] - 10.,
                                          camera_failure_reason=lane.last.get('reason'))
                    if phase == 'train' and lane is not None:
                        if state is None and result['terminated'] and result['reason'] == 'camera_lane_lost':
                            terminal_credit = (last_applied if result.get('camera_failure_reason') ==
                                               'camera_target_unavailable' else None)
                        learning_step = camera_learning.learn(policy, state, result, credit=last_applied)
                    if phase == 'train':
                        counts = summary['learning_steps']
                        counts[learning_step] = counts.get(learning_step, 0) + 1
                    if result['goal_reached'] or result['terminated'] or result['truncated']:
                        owner.stop()
                        speed, angular = 0., 0.
                    else:
                        if phase == 'eval' and state is not None and any(value != 0. for value in policy.table.get(state, ())):
                            learned_steps += 1
                        intent = MotionIntent(MotionKind.BASE_TWIST,
                            MotionHeader(f'isaac:{epoch}:{frame}', 'isaac-pinky', 'learned_policy',
                                PriorityClass.POLICY, now, .1, envelope_ref='isaac-map-v1', state_sequence=epoch,
                                limits={'linear_mps': .06, 'angular_radps': .8}), BaseTwist(speed, angular))
                        if lane is None:
                            owner.submit(intent, observed_at=now, now=now)
                        else:
                            if not lane.manager.apply_if_current(decision, lambda _decision:
                                owner.submit(intent, observed_at=now, now=now, preserve_curvature=True)):
                                owner.stop()
                    dispatch_receipts.clear()
                    cycle_warnings.clear()
                    cmd_vel_cycle(command=owner, power=power, send=send, warn=cycle_warnings.append)
                    if phase == 'train' and lane is not None:
                        last_applied = remember_camera_action(last_applied, state, action, frame,
                            (speed, angular), dispatch_receipts, cycle_warnings, owner.halted)
                    trace.write(json.dumps(dict(frame=frame, sim_s=elapsed, wall_s=time.monotonic() - wall_start,
                                                pose=pose, action=action, candidate=[speed, angular],
                                                learning_step=learning_step,
                                                camera_learning=camera_learning.last_update,
                                                terminal_credit=terminal_credit, dispatch=dispatch_receipts,
                                                cycle_warnings=cycle_warnings,
                                                **({'camera': lane.last, 'line': lane.manager.status().model_dump()}
                                                   if lane is not None else {}), **result)) + '\n')
                    if result['terminated'] or result['truncated']:
                        break
                    if owner.halted and not result['goal_reached']:
                        raise RuntimeError('policy envelope HOLD during active route')
                    previous = (state, action) if state is not None else None
                    step()
            episode = dict(phase=phase, seed=seed, epoch=epoch, **result,
                           sim_s=elapsed, wall_s=time.monotonic() - wall_start,
                           initial_heading_offset_rad=heading_offset, initial_pose=initial_pose,
                           initial_target_pose=[*route[0], heading], time_limit_s=task.time_limit,
                           learned_state_steps=learned_steps, stop=physical_stop())
            if frozen is not None:
                episode['policy_state_sha256'] = policy_state_sha256(frozen)
            if lane is not None:
                episode.update(camera_frames=camera_frames, camera_visible_frames=camera_visible_frames,
                               camera_usable=camera_visible_frames > 0)
            if recorder is not None:
                # Record the true completed stop even when it falls between sample ticks.
                for _ in range(2):
                    world.render()
                image_frame = camera.get_current_frame()
                recorder.write(camera.get_rgba(), render_frame=image_frame['rendering_frame'],
                    render_time=float(image_frame['rendering_time']),
                    sim_s=world.current_time - start_time, pose=read_pose())
                recorder.close()
                episode['video'] = dict(file=recorder.path.name, frames=recorder.frames,
                    sha256=hashlib.sha256(recorder.path.read_bytes()).hexdigest())
                recorder = None
            summary['episodes'].append(episode)
            if phase == 'baseline' and seed == 101 and saved is None:
                baseline = result
            if frozen is not None and policy.export() != frozen:
                raise RuntimeError('evaluation mutated policy')
            if phase == 'eval' and learned_steps == 0 and lane is None:
                raise RuntimeError('evaluation visited no learned state')
            if lane is not None:
                # Keep failed headings rejected, but measure the remaining headings after a verified stop.
                error = camera_admission_error(phase, camera_visible_frames, learned_steps)
                if error is not None:
                    episode['admission_error'] = error
            if (phase == 'eval' and perception is not None and not episode.get('admission_error')
                    and not summary['episodes'][-2].get('admission_error')):
                summary['camera_comparisons'].append(camera_comparison(summary['episodes'][-2], episode))
            print('EPISODE ' + json.dumps(episode), flush=True)
            if phase == 'train':
                (output / 'policy.json').write_text(json.dumps(policy.export(), sort_keys=True))
        summary['updates'] = policy.updates
        summary['policy_sha256'] = hashlib.sha256((output / 'policy.json').read_bytes()).hexdigest()
        summary['camera_admission_errors'] = [dict(phase=e['phase'], seed=e['seed'], error=e['admission_error'])
                                              for e in summary['episodes'] if e.get('admission_error')]
        summary['full_map_complete'] = (not summary['camera_admission_errors'] and
            all(e['complete'] for e in summary['episodes'] if e['phase'] == 'eval'))
        summary['baseline_complete'] = baseline['complete'] if baseline is not None else None
        summary['final_stop'] = physical_stop()
        (output / 'result.json').write_text(json.dumps(summary, indent=2, sort_keys=True))
        print('RESULT ' + json.dumps(summary), flush=True)
        if summary['camera_admission_errors']:
            raise RuntimeError('camera episode admission failed; candidate not accepted')
        if not summary['full_map_complete']:
            raise RuntimeError('held-out full-map completion failed; candidate not accepted')
    except Exception as exc:
        summary['error'] = str(exc)
        (output / 'result.json').write_text(json.dumps(summary, indent=2, sort_keys=True))
        raise
    finally:
        summary['updates'] = 0 if policy is None else policy.updates
        try:
            cleanup_error = None
            try:
                if stop_robot is not None:
                    summary['cleanup_stop'] = stop_robot()
            except Exception as exc:
                summary['cleanup_error'] = str(exc)
                cleanup_error = exc
            try:
                if recorder is not None:
                    recorder.close()
            except Exception as exc:
                summary['video_cleanup_error'] = str(exc)
                cleanup_error = cleanup_error or exc
            try:
                if lane is not None:
                    lane.close()
            except Exception as exc:
                summary['lane_cleanup_error'] = str(exc)
                cleanup_error = cleanup_error or exc
            if cleanup_error is not None:
                raise cleanup_error
        finally:
            try:
                try:
                    camera_error = None
                    for owned_camera in (camera, front_camera):
                        if owned_camera is not None:
                            try:
                                try:
                                    owned_camera.pause()
                                finally:
                                    owned_camera.destroy()
                            except Exception as exc:
                                camera_error = camera_error or exc
                    if camera_error is not None:
                        raise camera_error
                finally:
                    from sdk_entrypoint import close_sdk
                    close_sdk(app, headless=True)
            except Exception as exc:
                summary['sdk_shutdown_error'] = str(exc)
                raise
            finally:
                (output / 'result.json').write_text(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == '__main__':
    from sdk_entrypoint import run_cli
    run_cli(main)
