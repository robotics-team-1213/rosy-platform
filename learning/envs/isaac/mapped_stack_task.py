"""CAD board context and measured-contact three-layer reference execution."""
import math
import hashlib
import json
from pathlib import Path
import subprocess

from mapped_stack_fixture import CUBE_FIXTURE, DT, FIXTURE, PROFILE, ROOT, belt_transport_observed, cube_release_ready, cube_release_target, free_lift, grip_duration, home, judge, plan, stable_box, leveling_release_target, leveling_box_stable, leveling_sequence_observed, norm, PackingFootprintUnavailable, prefix_held, measured_motion


def stable_window(snapshot,step,ok,failure,check=None,boxes=None):
    # A reference sample, then twelve consecutive samples passing `ok` (the original 1.1s window) within ten seconds.
    window,judged=[],[]
    for attempt in range(101):
        sample=snapshot()
        if check:
            check(sample)
        if window:
            judged.append((window[-1],measured_motion([window[-1],sample])[1]))
        window=window+[sample] if window and ok(judged[-1][1]) else [sample]
        if len(window)==13:
            return window
        if attempt<100:
            for _ in range(12):
                step()
    raise ValueError(failure+(window_diagnosis(judged,boxes) if boxes else ''))


def window_diagnosis(judged,boxes):
    """Per placed box: failed judged samples, peak judged speeds and peak pose change between samples."""
    parts=[]
    for j,ok in boxes:
        bad=[s for _,s in judged if not ok(s,j)]
        if bad:
            step=max(max(abs(x-y) for x,y in zip(p['boxes'][j]['position'],s['boxes'][j]['position'])) for p,s in judged)
            parts.append('box%d fail %d/%d v %.4f w %.4f step %.1e'%(j,len(bad),len(judged),
                max(norm(s['boxes'][j]['velocity']) for _,s in judged),
                max(norm(s['boxes'][j]['angular_velocity']) for _,s in judged),step))
    return ' ['+'; '.join(parts)+']' if parts else ''


def settle_stack(index,snapshot,step,fixture):
    def placed(sample,j):
        return stable_box(sample['boxes'][j],j,True,fixture=fixture) and all(
            norm([tcp[k]-sample['boxes'][j]['position'][k] for k in range(3)])>=.04 for tcp in sample['tcps'])
    return stable_window(snapshot,step,lambda sample:all(placed(sample,j) for j in range(index+1)),
        'Released stack did not establish a stable window within ten seconds',
        boxes=[(j,placed) for j in range(index+1)])


def await_prefix(index,snapshot,step,fixture):
    # A speed-only prefix excursion waits for the original 1.1s window; displacement or contact loss stops at once.
    if not index:
        return []
    def held(sample):
        if not prefix_held(sample,index,fixture):
            raise ValueError('Prior stack moved; next placement blocked')
    def placed(sample,j):
        return stable_box(sample['boxes'][j],j,True,fixture=fixture)
    return stable_window(snapshot,step,lambda sample:all(placed(sample,j) for j in range(index)),
        'Prior stack did not establish a stable window within ten seconds',held,
        boxes=[(j,placed) for j in range(index)])


def packing_target(index,snapshot,step,source_z,fixture,commanded_tcp=None):
    # Retry measured transient rocking; contact loss and persistent geometric failure still stop.
    for attempt in range(51):
        sample=snapshot()
        if not prefix_held(sample,index,fixture):
            raise ValueError('Prior stack lost stability during packing')
        try:
            return cube_release_target(index,sample,source_z,commanded_tcp,fixture=fixture)
        except PackingFootprintUnavailable:
            if attempt==50:
                raise
            for _ in range(12):
                step()


class Planner:
    """Use the OMX owner's offline JSON producer without importing its device adapter."""
    def __init__(self, directory, *, scene=None):
        self.directory, self.count = Path(directory), 0
        self.scene = scene

    def request(self, operation, **fields):
        from stacking_report import read_regular
        self.count += 1
        request = self.directory/f'plan-request-{self.count}.json'
        output = self.directory/f'plan-frames-{self.count}.json'
        if self.scene is not None:
            fields = dict(fields,scene=self.scene)
        with request.open('x', encoding='utf-8') as stream:
            json.dump(dict(schema='rosy.omx-sim-stack-plan/1', operation=operation, **fields), stream, allow_nan=False)
        try:
            subprocess.run(['/usr/bin/python3', str(ROOT/'deploy/robot/omx/isaac_stack_plan.py'),
                '--case', str(request), '--out', str(output)], check=True, timeout=60, capture_output=True)
        except subprocess.CalledProcessError as exc:
            lines = (exc.stderr or b'').decode('utf-8', errors='replace').splitlines()
            raise ValueError('SIM planning refused: '+(lines[-1][:200] if lines else 'no diagnostic')) from None
        value = json.loads(read_regular(output, limit=16*1024*1024))
        if (value.get('schema') != 'rosy.omx-sim-stack-plan/1'
                or value.get('joints') != ['joint'+str(i) for i in range(1, 6)]
                or value.get('planning_scene') != self.scene
                or value.get('profile_sha256') != hashlib.sha256(PROFILE.read_bytes()).hexdigest()):
            raise ValueError('Offline SIM plan provenance differs')
        # Accepted exchanges are not artifacts; refused ones stay for diagnosis within the file budget.
        request.unlink()
        output.unlink()
        return value


def apply_servo(robot, targets, joints, fingers):
    import numpy as np
    from isaacsim.core.utils.types import ArticulationAction
    state = robot.get_joint_positions()
    if not np.isfinite(state).all():
        raise ValueError('Nonfinite mapped articulation')
    targets[fingers[1]] = -state[fingers[0]]
    effort = np.zeros(robot.num_dof)
    gravity = np.asarray(robot._articulation_view.get_generalized_gravity_forces())[0]
    effort[joints] = np.clip(gravity[joints], -FIXTURE['arm_max_effort_nm'], FIXTURE['arm_max_effort_nm'])
    robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=targets, joint_efforts=effort))


def build_map(world, stage, fixture=FIXTURE):
    import numpy as np
    from pxr import Gf, UsdGeom
    from isaacsim.core.api.objects import FixedCuboid, VisualCuboid
    world.scene.add(FixedCuboid('/World/PlywoodMap', name='plywood_map', size=1.,
        position=np.array(fixture['board_lower_left_m'])+np.array(fixture['board_size_m'])*np.array([.5, .5, -.5]),
        scale=np.array(fixture['board_size_m']),
        color=np.array([.35, .36, .37])))
    # shortcut: CAD paint is visually transcribed; surveyed workbench registration replaces nominal photo poses.
    paths = [[(.738, .10), (.738, .02), (1.13, .02), (1.21, .10), (1.21, 2.34),
              (1.13, 2.42), (.818, 2.42), (.738, 2.34), (.738, 1.69),
              (.338, 1.49), (.338, .56), (.738, .36), (.738, .10)],
             [(.98, .30), (.98, 2.14)], [(.738, .675), (.738, 1.375)]]
    if fixture.get('road_markup') == 'UNMODELED_IN_NEW_CAD_WORKCELL':
        paths = []
        # Stage2 is context only; its third robot is outside this two-arm task.
        world.scene.add(VisualCuboid('/World/CadStage2',name='cad_stage2',size=1.,
            position=np.array([.3595,.467,.009]),scale=np.array([.245,.760,.018]),
            color=np.array([.65,.64,.54])))
    if fixture.get('leveling_protocol'):
        center, size = fixture['leveling_center_m'],fixture['leveling_size_m']
        for axis in (0,1):
            for side,sign in enumerate((-1,1)):
                position=np.array([*center[:2],center[2]+.0004])
                position[1-axis]+=sign*size[1-axis]/2
                scale=np.array([.0006,.0006,.0006]);scale[axis]=size[axis]
                name=f'LevelingBoundary{axis}_{side}'
                world.scene.add(VisualCuboid('/World/'+name,name=name,size=1.,
                    position=position,scale=scale,color=np.array([.25,.65,.75])))
    count = 0
    for path in paths:
        for a, b in zip(path, path[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            obj = world.scene.add(VisualCuboid('/World/Tape'+str(count), name='tape'+str(count), size=1.,
                position=np.array([(a[0]+b[0])/2+fixture['board_lower_left_m'][0],
                                   (a[1]+b[1])/2+fixture['board_lower_left_m'][1], .0015]),
                scale=np.array([math.hypot(dx, dy), .01, .001]), color=np.ones(3)))
            UsdGeom.XformCommonAPI(obj.prim).SetRotate(Gf.Vec3f(0., 0., math.degrees(math.atan2(dy, dx))))
            count += 1
    for i, y in enumerate(() if 'workplate_size_m' in fixture else (-.15, .15)):
        world.scene.add(VisualCuboid('/World/YellowBench'+str(i), name='yellow_bench'+str(i), size=1.,
            position=np.array([-.10, y, -.001]), scale=np.array([.26, .25, .002]),
            color=np.array([.95, .72, .06])))


def execute(args, world, stage, robots, joints, fingers, cargo, contacts, capture, grasp_probes,
            planner, initial, tcp_position, *, fixture=None, recording=None, wrists=None):
    import numpy as np
    from pxr import UsdGeom
    cube = args.mapped_cube_stack
    fixture = (CUBE_FIXTURE if cube else FIXTURE) if fixture is None else fixture
    targets = [np.zeros(r.num_dof) for r in robots]
    tick = 0
    images, trials = [], []
    from release_corrector import corrector_command, estimate, load_corrector, load_residual, observation, policy_command
    corrector = load_corrector(fixture) if cube else None
    residual = load_residual(fixture) if cube else None
    print('MAPPED_AFTER_RESET', [r.get_joint_positions().tolist() for r in robots], flush=True)
    for i, robot in enumerate(robots):
        controller = robot.get_articulation_controller()
        gains = controller.get_gains()
        print('MAPPED_IMPORTED_GAINS', i, [np.asarray(v).tolist() for v in gains], flush=True)
        kp, kd = np.zeros(robot.num_dof), np.zeros(robot.num_dof)
        kp[joints[i]], kd[joints[i]] = FIXTURE['arm_stiffness_si'], FIXTURE['arm_damping_si']
        kp[fingers[i]], kd[fingers[i]] = [30., 300.], [2., 5.]
        controller.set_gains(kps=kp, kds=kd)
        print('MAPPED_SI_GAINS', i, [np.asarray(v).tolist() for v in controller.get_gains()], flush=True)
        view = robot._articulation_view
        print('MAPPED_FIXED_BASE', i, view._physics_view.shared_metatype.fixed_base, flush=True)
        print('MAPPED_GRAVITY', i, view.get_generalized_gravity_forces().tolist(), flush=True)
        if not view._physics_view.shared_metatype.fixed_base:
            raise ValueError('Mapped OMX must be anchored to the simulation world')
        print('MAPPED_IMPORTED_EFFORTS', i, view.get_max_efforts().tolist(), flush=True)
        efforts = np.full((1, robot.num_dof), FIXTURE['arm_max_effort_nm'])
        efforts[0, fingers[i]] = fixture.get('finger_max_efforts_nm', [.2, 2.])
        view.set_max_efforts(efforts)
        if not np.allclose(view.get_max_efforts(), efforts, atol=1e-6):
            raise ValueError('Mapped drive effort readback differs from the fixture')
        print('MAPPED_SI_EFFORTS', i, view.get_max_efforts().tolist(), flush=True)
        print('MAPPED_MASSES', i, view.get_body_masses().tolist(), flush=True)
        inertias = np.asarray(view.get_body_inertias()).reshape(-1, 3, 3)
        print('MAPPED_INERTIA_EIGENVALUES', i, np.linalg.eigvalsh(inertias).tolist(), flush=True)
        print('MAPPED_EFFORT_MODES', i, view.get_effort_modes(), flush=True)
        print('MAPPED_SELF_COLLISIONS', i, view.get_enabled_self_collisions().tolist(), flush=True)
        view.set_solver_position_iteration_counts(np.array([64]))
        view.set_solver_velocity_iteration_counts(np.array([16]))

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
            recording.write(tick, robots[0].get_joint_positions()[joints[0]])
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
            recording.write(tick, robots[0].get_joint_positions()[joints[0]], final=True)
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
        try:
            if any(np.max(np.abs(robot.get_joint_positions()[joints[i]]-targets[i][joints[i]])) > .03
                   for i, robot in enumerate(robots)):
                raise ValueError('initial arm tracking exceeds 0.03 rad')
            for index, item in enumerate(plan(cube, fixture=fixture)):
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
                if fixture.get('leveling_protocol'):
                    leveling = layer['leveling'] = dict(arm=arm,grasp_samples=[],lift_samples=[],settle_samples=[])
                    center = fixture['leveling_center_m']
                    leveling_yaw = fixture['leveling_yaws_rad'][arm]
                    move(arm,[*center[:2],carry_height],leveling_yaw)
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
                    move(arm,[*center[:2],carry_height],leveling_yaw)
                    move(arm,home(arm,cube,fixture=fixture))
                    leveling['settle_samples'] = samples(132)
                    if not all(leveling_box_stable(s['boxes'][index],index,fixture) and prefix_held(s,index,fixture)
                            for s in leveling['settle_samples']):
                        raise ValueError('Tabletop leveling did not establish flat supported stability')
                    photo('mapped-leveling-'+str(index+1)+'.png')
                    p,q = box.get_world_pose()
                    leveling['source_center_z'] = float(p[2])
                    yaw = math.atan2(2*(q[0]*q[3]+q[1]*q[2]),1-2*(q[2]**2+q[3]**2))
                    move(arm,[p[0],p[1],carry_height],yaw)
                    grip(arm,initial['gripper']['preopen'])
                    move(arm,[p[0],p[1],p[2]+.002],yaw)
                    leveling['grasp_samples'].append(grasp_snapshot(arm))
                    grip(arm,initial['gripper']['close'])
                    leveling['grasp_samples'].append(grasp_snapshot(arm))
                    move(arm,[p[0],p[1],carry_height],yaw)
                    leveling['lift_samples'] = samples(36)
                    if not leveling_sequence_observed(layer,index,fixture):
                        raise ValueError('Leveled container regrasp lacks measured second free lift')
                move(arm, [*item['target'][:2], carry_height])
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
                        move(arm, release_command)
                        layer['release_samples'].append(snapshot())
                else:
                    move(arm, [*item['target'][:2], item['target'][2]+.003])
                if cube:
                    if fixture.get('leveling_protocol'):
                        packing_target(index,snapshot,step,float(p[2]),fixture)
                    layer['release_sample'] = snapshot()
                    if not cube_release_ready(index, layer['release_sample'], float(p[2]), fixture=fixture):
                        raise ValueError('cube release correction did not converge; opening blocked')
                layer['opening_samples'] = grip(arm, initial['gripper']['release'], observe=cube, release=True)
                if cube:
                    layer['opened_sample'] = snapshot()
                move(arm, [*item['target'][:2], carry_height])
                move(arm, home(arm, cube, fixture=fixture))
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
        print('MAPPED_TRIAL', trial_index, trial['task_success'], trial.get('error'), trial['failures'], flush=True)
        if not trial['task_success']:
            break
    stage.GetRootLayer().Export(str(args.report.parent/'mapped-scene.usda'))
    if recording is not None:
        recording.write(tick, robots[0].get_joint_positions()[joints[0]], final=True)
    return dict(schema='rosy.omx-container-stack/1' if recording is not None else 'rosy.omx-map-cube-stack/1' if cube else 'rosy.omx-map-long-stack/1', fixture=fixture, seed=args.seed, trials=trials,
        task_success=len(trials) == fixture['trials'] and all(t['task_success'] for t in trials),
        controller=FIXTURE['controller'], attachment_aid=False, images=images)
