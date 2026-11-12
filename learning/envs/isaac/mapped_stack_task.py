"""CAD board context and measured-contact three-layer reference execution."""
import math
import hashlib  # noqa: F401
import json  # noqa: F401
from pathlib import Path  # noqa: F401
import subprocess  # noqa: F401

from guarded_release import descend
from mapped_stack_fixture import (  # noqa: F401
    CUBE_FIXTURE,
    DT,
    FIXTURE,
    PROFILE,
    ROOT,
    PackingFootprintUnavailable,
    belt_transport_observed,
    cube_release_ready,
    cube_release_target,
    free_lift,
    grip_duration,
    home,
    judge,
    leveling_box_stable,
    leveling_center,
    leveling_release_target,
    leveling_sequence_observed,
    leveling_via,
    measured_motion,
    norm,
    plan,
    prefix_held,
    seat_check,
    stable_box,
)
from mapped_stack_task_helpers import (  # noqa: F401
    Planner,
    apply_servo,
    await_prefix,
    build_map,
    configure_mapped_robots,
    packing_target,
    settle_stack,
    stable_window,
    window_diagnosis,
)


def execute(args, world, stage, robots, joints, fingers, cargo, contacts, capture, grasp_probes,
            planner, initial, tcp_position, *, fixture=None, recording=None, wrists=None, observe=None, policy=None):
    import numpy as np
    from pxr import UsdGeom
    cube = args.mapped_cube_stack
    fixture = (CUBE_FIXTURE if cube else FIXTURE) if fixture is None else fixture
    targets = [np.zeros(r.num_dof) for r in robots]
    tick = 0
    images, trials = [], []
    demo_item = [None]  # D-969: the container the current frames belong to (one episode per container)

    def demo():
        """Both arms' measured state and commanded targets, arm 0 (arm_a) first: joint1..5 then the first finger, radians."""
        return dict(item=demo_item[0], arm=None if demo_item[0] is None else plan(cube, fixture=fixture)[demo_item[0]]['arm'],
                    state=[float(v) for i, r in enumerate(robots) for v in r.get_joint_positions()[[*joints[i], fingers[i][0]]]],
                    action=[float(v) for i in range(len(robots)) for v in targets[i][[*joints[i], fingers[i][0]]]])
    from release_corrector import corrector_command, estimate, load_corrector, load_residual, observation, policy_command
    corrector = load_corrector(fixture) if cube else None
    residual = load_residual(fixture) if cube else None
    configure_mapped_robots(robots, joints, fingers, fixture)

    def step():
        nonlocal tick
        for i, robot in enumerate(robots):
            state = robot.get_joint_positions()
            if not np.isfinite(state).all():
                raise ValueError(f'nonfinite articulation arm={i} tick={tick}')
            apply_servo(robot, targets[i], joints[i], fingers[i])
        if recording is not None and (tick+1) % fixture['recording']['every_control_ticks'] == 0:
            before = world.current_time
            world.step(render=True, update_fabric=True)
            if abs(world.current_time-before-DT) > 1e-6:
                raise ValueError('Rendered control step did not preserve the physics period')
        else:
            for _ in range(FIXTURE['physics_substeps']):
                world.step(render=False, update_fabric=True)
        tick += 1
        if recording is not None:
            recording.write(tick, robots[0].get_joint_positions()[joints[0]], demo=demo())
        if tick <= 3:
            print('MAPPED_FIRST_STEP', tick, [r.get_joint_positions().tolist() for r in robots], flush=True)

    def hold(steps):
        for _ in range(steps):
            step()

    def snapshot():
        boxes, tcps = [], []
        for i, box in enumerate(cargo):
            p, q = box.get_world_pose()
            boxes.append(dict(position=p.tolist(), orientation=q.tolist(),
                velocity=box.get_linear_velocity().tolist(), angular_velocity=box.get_angular_velocity().tolist(),
                net_force=np.asarray(contacts[i].get_net_contact_forces(dt=FIXTURE['physics_dt_s']))[0].tolist(),
                forces=np.asarray(contacts[i].get_contact_force_matrix(dt=FIXTURE['physics_dt_s']))[0].tolist()))
        for i in range(2):
            tcps.append(tcp_position(i).tolist())
        value = dict(tick=tick, boxes=boxes, tcps=tcps,
            joints=[r.get_joint_positions().tolist() for r in robots],
            commands=[v.tolist() for v in targets],
            bases=[r.get_world_pose()[0].tolist() for r in robots])
        if wrists is not None:
            value['wrist_orientations'] = [view.get_world_poses()[1][0].tolist() for view in wrists]
        return value

    def samples(steps):
        result = [snapshot()]
        for n in range(steps):
            step()
            if (n+1) % 12 == 0:
                result.append(snapshot())
        return result

    def grasp_snapshot(arm):
        value = snapshot()
        filters, probes = grasp_probes[arm]
        value['arm_contacts'] = []
        for path, probe in probes:
            forces = np.asarray(probe.get_contact_force_matrix(dt=FIXTURE['physics_dt_s']))[0]
            for name, force in zip(filters, forces):
                if np.linalg.norm(force) > .01:
                    value['arm_contacts'].append(dict(body=path, other=name, force=force.tolist()))
        print('MAPPED_GRASP_CONTACT', arm, value['arm_contacts'], flush=True)
        return value

    def photo(name, overview=False):
        capture(name, overview)
        images.append(name)

    def move(arm, point, yaw=0.):
        frames = planner.request('move', base=fixture['arm_bases_m'][arm],
            base_yaw=fixture.get('arm_base_yaws_rad', [0., 0.])[arm],
            start=targets[arm][joints[arm]].tolist(), target=[float(v) for v in point], yaw=float(yaw), dt=DT)['frames']
        for q in frames:
            targets[arm][joints[arm]] = q
            step()
        hold(120)
        if cube and np.max(np.abs(robots[arm].get_joint_positions()[joints[arm]]-targets[arm][joints[arm]])) > .03:
            trial['motion_failure_sample'] = grasp_snapshot(arm)
            raise ValueError('cube arm tracking exceeds 0.03 rad; further correction blocked')

    def grip(arm, value, observe=False, release=False):
        observations = [snapshot()] if observe else []
        start = targets[arm][fingers[arm][0]]
        acceleration = fixture.get('release_gripper_acceleration_rad_s2', .4) if release else .4
        duration = grip_duration(start, value, acceleration=acceleration)
        for n, u in enumerate(np.linspace(0., 1., math.ceil(duration/DT)+1)[1:]):
            targets[arm][fingers[arm][0]] = start+(value-start)*u**3*(10+u*(-15+6*u))
            step()
            if observe and n % fixture.get('opening_sample_ticks', 3) == 0:
                observations.append(snapshot())
        for n in range(60):
            step()
            if observe and n % fixture.get('opening_sample_ticks', 3) == 0:
                observations.append(snapshot())
        return observations

    if fixture.get('release_episodes'):
        from types import SimpleNamespace
        from release_episodes import run as run_episodes

        def reset():
            for i, box in enumerate(cargo):
                parked = fixture['parking_origin_m']
                box.set_world_pose(np.array([parked[0], parked[1]+i*fixture['parking_step_y_m'], parked[2]]),
                                   np.array([1., 0., 0., 0.]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
                UsdGeom.Imageable(box.prim).MakeInvisible()
            for i, robot in enumerate(robots):
                targets[i][joints[i]] = initial['homes'][i]
                targets[i][fingers[i]] = [.6, -.6]
                robot.set_joint_positions(targets[i])
                robot.set_joint_velocities(np.zeros(robot.num_dof))
            hold(120)
        tools = SimpleNamespace(step=step, hold=hold, snapshot=snapshot, samples=samples, move=move, grip=grip, reset=reset)
        trial = dict(seed=args.seed, layers=[])  # move() records tracking failures here (run 8e96 crashed without it)
        reset()
        photo('mapped-overview.png', True)
        photo('mapped-initial.png')  # the report verifier requires both starting views
        episodes = run_episodes(tools, fixture, cargo, initial, corrector, residual, args.seed)
        photo('mapped-trial-1.png')
        if recording is not None:
            hold((-tick) % fixture['recording']['every_control_ticks'])
            recording.write(tick, robots[0].get_joint_positions()[joints[0]], final=True, demo=demo())
        trial.update(episodes=episodes)
        trial.update(judge(trial, cube, fixture=fixture))  # no full stack: the verifier recomputes this failure
        return dict(schema='rosy.omx-container-stack/1', fixture=fixture, seed=args.seed, task_success=False,
                    trials=[trial], controller=FIXTURE['controller'], attachment_aid=False, images=images)
    for trial_index in range(fixture['trials']):
        trial = dict(seed=args.seed+trial_index, layers=[])
        trials.append(trial)
        rng = np.random.default_rng(trial['seed'])
        estimate_rng = np.random.default_rng(trial['seed']+7919)  # keeps the infeed draws equal across cases
        for i, box in enumerate(cargo):
            parked = fixture.get('parking_origin_m',[-.45,.4,.016])
            box.set_world_pose(np.array([parked[0], parked[1]+i*fixture.get('parking_step_y_m',.065), parked[2]]), np.array([1., 0., 0., 0.]))
            box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
            UsdGeom.Imageable(box.prim).MakeInvisible()
        for i, robot in enumerate(robots):
            targets[i][joints[i]] = initial['homes'][i]
            targets[i][fingers[i]] = [.6, -.6]
            robot.set_joint_positions(targets[i])
            robot.set_joint_velocities(np.zeros(robot.num_dof))
        print('MAPPED_AFTER_POSE', [r.get_joint_positions().tolist() for r in robots], flush=True)
        hold(120)
        print('MAPPED_HOME', snapshot(), flush=True)
        print('MAPPED_APPLIED', [(r.get_applied_action().joint_positions.tolist(),
            r.get_applied_action().joint_velocities.tolist(), r.get_joint_velocities().tolist()) for r in robots], flush=True)
        print('MAPPED_TORQUES', [r.get_measured_joint_efforts().tolist() for r in robots], flush=True)
        if trial_index == 0:
            photo('mapped-overview.png', True)
            photo('mapped-initial.png')
            if cube:
                photo('mapped-top.png')
                photo('mapped-side.png')
            for view in fixture.get('real_cameras', {}):
                photo('real-'+view+'.png')
        try:
            if any(np.max(np.abs(robot.get_joint_positions()[joints[i]]-targets[i][joints[i]])) > .03
                   for i, robot in enumerate(robots)):
                raise ValueError('initial arm tracking exceeds 0.03 rad')
            for index, item in enumerate(plan(cube, fixture=fixture)):
                demo_item[0] = index
                arm, box = item['arm'], cargo[index]
                UsdGeom.Imageable(box.prim).MakeVisible()
                yaw_limit = fixture.get('infeed_yaw_jitter_rad', .01)
                yaw = float(rng.uniform(-yaw_limit, yaw_limit))
                jitter = fixture.get('infeed_jitter_xy_m', [.001, .001])
                infeed = fixture.get('infeed_start_m', [.16, -.09, .041])
                pitch = fixture.get('belt_pitch_rad', 0.)
                box.set_world_pose(np.array([infeed[0]+rng.uniform(-jitter[0], jitter[0]), infeed[1]+rng.uniform(-jitter[1], jitter[1]), infeed[2]]),
                    np.array([math.cos(yaw/2)*math.cos(pitch/2), math.sin(yaw/2)*math.sin(pitch/2),
                              -math.cos(yaw/2)*math.sin(pitch/2), math.sin(yaw/2)*math.cos(pitch/2)]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
                start = box.get_world_pose()[0].copy()
                hold(360)
                p, q = box.get_world_pose()
                trial['belt_displacement_m'] = (p-start).tolist()
                if not belt_transport_observed(start, p, cube, fixture=fixture):
                    raise ValueError('belt failed to transport cargo')
                yaw = math.atan2(2*(q[0]*q[3]+q[1]*q[2]), 1-2*(q[2]**2+q[3]**2))
                layer = dict(item=index, arm=arm, source_center_z=float(p[2]),
                    infeed_start=start.tolist(), infeed_settled=p.tolist(), grasp_samples=[], lift_samples=[], settle_samples=[])
                trial['layers'].append(layer)
                if policy is not None:  # D-969 step 5: the learned policy drives both arms from here, the teacher does not
                    from demo_units import to_radians, to_units
                    policy.reset()
                    spec = fixture['policy']
                    for count in range(1, spec['max_actions']+1):
                        state = to_units([float(v) for i, r in enumerate(robots) for v in r.get_joint_positions()[[*joints[i], fingers[i][0]]]])
                        action = to_radians(policy.act(state, observe()))
                        for i in range(len(robots)):
                            targets[i][[*joints[i], fingers[i][0]]] = action[6*i:6*i+6]
                        hold(spec['ticks_per_action'])
                    layer['policy'] = dict(actions=count, ticks_per_action=spec['ticks_per_action'])
                    layer['settle_samples'] = samples(132)
                    photo('mapped-layer-'+str(index+1)+'.png')
                    print('MAPPED_LAYER', trial_index, index+1, flush=True)
                    continue
                carry_height = fixture.get('carry_height_m', .145)
                move(arm, [p[0], p[1], carry_height], yaw)
                grip(arm, initial['gripper']['preopen'])
                move(arm, [p[0], p[1], p[2]+.002], yaw)
                layer['grasp_samples'].append(grasp_snapshot(arm))
                grip(arm, initial['gripper']['close'])
                layer['grasp_samples'].append(grasp_snapshot(arm))
                move(arm, [p[0], p[1], carry_height], yaw)
                layer['lift_samples'] = samples(36)
                if not all(free_lift(s['boxes'][index], arm, float(p[2])) for s in layer['lift_samples']):
                    photo('mapped-grasp-failed.png')
                    raise ValueError('bilateral free lift failed; transport interlock stopped the arm')
                if fixture.get('grasp_hold_check'):  # step 1 of the palletizing rebuild: lift, hold, stop before any placement
                    layer['hold'] = dict(finger_dof=fingers[arm][0], seconds=2, samples=samples(240))
                    raise ValueError('grasp-hold check complete; placement not attempted')
                if fixture.get('leveling_protocol'):
                    leveling = layer['leveling'] = dict(arm=arm,grasp_samples=[],lift_samples=[],settle_samples=[])
                    center = leveling_center(fixture, arm)
                    leveling_yaw = fixture['leveling_yaws_rad'][arm]
                    level_carry = fixture.get('leveling_carry_height_m', carry_height)

                    def via(yaw):  # climb and descend through a waypoint: out of reach at carry height, or a wrist singularity on the way
                        if leveling_via(fixture, arm):
                            move(arm, leveling_via(fixture, arm), yaw)
                    via(leveling_yaw)
                    move(arm,[*center[:2],level_carry],leveling_yaw)
                    leveling['prefix_window'] = await_prefix(index,snapshot,step,fixture)
                    command = None
                    for _ in range(fixture['release_feedback_iterations']):
                        command = leveling_release_target(index,snapshot(),fixture,commanded_tcp=command)
                        move(arm,command,leveling_yaw)
                    leveling['release_sample'] = snapshot()
                    command = leveling_release_target(index,leveling['release_sample'],fixture)
                    if norm([command[k]-leveling['release_sample']['tcps'][arm][k] for k in range(3)]) > .00005:
                        raise ValueError('Leveling release feedback did not converge')
                    grip(arm,initial['gripper']['release'],release=True)
                    leveling['opened_sample'] = snapshot()
                    move(arm,[*center[:2],level_carry],leveling_yaw)
                    via(leveling_yaw)
                    move(arm,home(arm,cube,fixture=fixture))
                    leveling['settle_samples'] = samples(132)
                    if not all(leveling_box_stable(s['boxes'][index],index,fixture) and prefix_held(s,index,fixture)
                            for s in leveling['settle_samples']):
                        raise ValueError('Tabletop leveling did not establish flat supported stability')
                    photo('mapped-leveling-'+str(index+1)+'.png')
                    p,q = box.get_world_pose()
                    leveling['source_center_z'] = float(p[2])
                    yaw = math.atan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2))
                    via(yaw)
                    move(arm,[p[0],p[1],level_carry],yaw)
                    grip(arm,initial['gripper']['preopen'])
                    move(arm,[p[0],p[1],p[2]+.002],yaw)
                    leveling['grasp_samples'].append(grasp_snapshot(arm))
                    grip(arm,initial['gripper']['close'])
                    leveling['grasp_samples'].append(grasp_snapshot(arm))
                    move(arm,[p[0],p[1],level_carry],yaw)
                    via(yaw)
                    leveling['lift_samples'] = samples(36)
                    if not leveling_sequence_observed(layer,index,fixture):
                        raise ValueError('Leveled container regrasp lacks measured second free lift')
                ryaw = fixture.get('release_yaw_rad', 0.) if cube else 0.  # deliberate yaw at release (MuJoCo yaw sweep candidates)
                move(arm, [*item['target'][:2], carry_height], ryaw)
                if cube:
                    layer['carry_sample'] = snapshot()
                    if fixture.get('leveling_protocol') and fixture.get('packing_strategy'):
                        layer['prefix_window'] = await_prefix(index,snapshot,step,fixture)
                    layer['release_samples'] = []
                    layer['release_commands'] = []
                    release_command = None
                    observe = ((lambda: estimate(snapshot(), index, fixture, estimate_rng))
                               if fixture.get('release_estimate_noise_m') else snapshot)
                    layer['release_controller'] = 'bc' if corrector else 'ik-estimate' if observe is not snapshot else 'ik'
                    for k in range(fixture['release_feedback_iterations']):
                        if corrector and k and residual:  # RL: explore around BC + residual, record the noise
                            seen = observe()
                            release_command, noise = policy_command(corrector, residual, seen, index, fixture, k,
                                estimate_rng, sigma=fixture['release_exploration_sigma_m'])
                            layer.setdefault('release_exploration', []).append(
                                dict(iteration=k, observation=observation(seen, index, fixture, k), noise=noise))
                        elif corrector and k:  # the IK teacher descends; the model owns the later corrections
                            release_command = corrector_command(corrector, observe(), index, fixture, k)
                        elif fixture.get('leveling_protocol'):
                            release_command=packing_target(index,observe,step,float(p[2]),fixture,release_command)
                        else:
                            release_command = cube_release_target(index, snapshot(), float(p[2]), commanded_tcp=release_command, fixture=fixture)
                        layer['release_commands'].append(release_command)
                        move(arm, release_command, ryaw)
                        layer['release_samples'].append(snapshot())
                else:
                    move(arm, [*item['target'][:2], item['target'][2]+.003])
                if cube:
                    if fixture.get('leveling_protocol'):
                        packing_target(index,snapshot,step,float(p[2]),fixture)
                    layer['release_sample'] = snapshot()
                    if not cube_release_ready(index, layer['release_sample'], float(p[2]), fixture=fixture):
                        raise ValueError('cube release correction did not converge; opening blocked')
                if cube and fixture.get('guarded_descent'):  # lower until the container stops, then open (guarded_release.py)
                    _, layer['guarded'] = descend(lambda point: move(arm, point, ryaw), lambda: float(snapshot()['boxes'][index]['position'][2]),
                                                  release_command, fixture['guarded_descent'])
                layer['opening_samples'] = grip(arm, initial['gripper']['release'], observe=cube, release=True)
                if cube:
                    layer['opened_sample'] = snapshot()
                move(arm, [*item['target'][:2], carry_height])
                move(arm, home(arm, cube, fixture=fixture))
                if fixture.get('seat_replace'):  # D-956: seat check, one corrected re-place, then HOLD
                    layer['seat'] = seat_check(snapshot()['boxes'][index], item['target'], fixture['seat_replace'])
                    if not layer['seat']['seated']:
                        p = snapshot()['boxes'][index]['position']
                        move(arm, [p[0], p[1], carry_height])
                        grip(arm, initial['gripper']['preopen'])
                        move(arm, [p[0], p[1], p[2]+.002])
                        grip(arm, initial['gripper']['close'])
                        move(arm, [p[0], p[1], carry_height])
                        # The miss is measured and corrected; what is left is an assumed residual along the original offset.
                        offset = fixture.get('release_offset_m', (0., 0.))
                        residual = fixture['seat_replace']['residual_m']
                        fixed = [item['target'][k]+math.copysign(residual, offset[k]) if offset[k] else item['target'][k] for k in (0, 1)]
                        move(arm, [*fixed, carry_height])
                        move(arm, [*fixed, item['target'][2]+fixture.get('stack_release_clearance_m', fixture['release_clearance_m'])+.002])
                        grip(arm, initial['gripper']['release'], release=True)
                        move(arm, [*fixed, carry_height])
                        move(arm, home(arm, cube, fixture=fixture))
                        layer['seat_after_replace'] = seat_check(snapshot()['boxes'][index], item['target'], fixture['seat_replace'])
                        if not layer['seat_after_replace']['seated']:
                            raise ValueError('seat check failed after one re-place; HOLD (D-956)')
                layer['settle_samples'] = (settle_stack(index,snapshot,step,fixture)
                    if fixture.get('packing_strategy') else samples(132))
                settled = (measured_motion(layer['settle_samples'])[1:] if fixture.get('packing_strategy')
                           else layer['settle_samples'])
                if not all(stable_box(s['boxes'][j], j, cube, fixture=fixture) for s in settled for j in range(index+1)):
                    raise ValueError('released stack failed stability; next infeed blocked')
                if trial_index == 0:
                    photo('mapped-layer-'+str(index+1)+'.png')
                print('MAPPED_LAYER', trial_index, index+1, flush=True)
        except (ValueError, RuntimeError) as exc:
            trial['error'] = str(exc)[:400]
            trial['failure_sample'] = snapshot()
        if recording is not None:
            hold((-tick) % fixture['recording']['every_control_ticks'])
            if trial['layers'] and trial['layers'][-1]['settle_samples']:
                settled = trial['layers'][-1]['settle_samples']
                if tick > settled[-1]['tick']:
                    settled.append(snapshot())
        trial.update(judge(trial, cube, fixture=fixture))
        photo('mapped-trial-'+str(trial_index+1)+'.png')
        if trial_index == 0:  # the finished stack through the real cameras: position-estimate error (D-947 5 order, step 2)
            for view in fixture.get('real_cameras', {}):
                photo('real-'+view+'-final.png')
        print('MAPPED_TRIAL', trial_index, trial['task_success'], trial.get('error'), trial['failures'], flush=True)
        if not trial['task_success']:
            break
    stage.GetRootLayer().Export(str(args.report.parent/'mapped-scene.usda'))
    if recording is not None:
        recording.write(tick, robots[0].get_joint_positions()[joints[0]], final=True, demo=demo())
    return dict(schema='rosy.omx-container-stack/1' if recording is not None else 'rosy.omx-map-cube-stack/1' if cube else 'rosy.omx-map-long-stack/1', fixture=fixture, seed=args.seed, trials=trials,
        task_success=len(trials) == fixture['trials'] and all(t['task_success'] for t in trials),
        controller=FIXTURE['controller'], attachment_aid=False, images=images)
