"""CAD board context and measured-contact three-layer reference execution."""
import math
import hashlib
import json
from pathlib import Path
import subprocess

from mapped_stack_fixture import CUBE_FIXTURE, DT, FIXTURE, PROFILE, ROOT, cube_release_target, free_lift, home, judge, plan, stable_box


class Planner:
    """Use the OMX owner's offline JSON producer without importing its device adapter."""
    def __init__(self, directory):
        self.directory, self.count = Path(directory), 0

    def request(self, operation, **fields):
        from stacking_report import read_regular
        self.count += 1
        request = self.directory/f'plan-request-{self.count}.json'
        output = self.directory/f'plan-frames-{self.count}.json'
        with request.open('x', encoding='utf-8') as stream:
            json.dump(dict(schema='rosy.omx-sim-stack-plan/1', operation=operation, **fields), stream, allow_nan=False)
        subprocess.run(['/usr/bin/python3', str(ROOT/'deploy/robot/omx/isaac_stack_plan.py'),
            '--case', str(request), '--out', str(output)], check=True, timeout=60, capture_output=True)
        value = json.loads(read_regular(output, limit=16*1024*1024))
        if (value.get('schema') != 'rosy.omx-sim-stack-plan/1'
                or value.get('joints') != ['joint'+str(i) for i in range(1, 6)]
                or value.get('profile_sha256') != hashlib.sha256(PROFILE.read_bytes()).hexdigest()):
            raise ValueError('Offline SIM plan provenance differs')
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


def build_map(world, stage):
    import numpy as np
    from pxr import Gf, UsdGeom
    from isaacsim.core.api.objects import FixedCuboid, VisualCuboid
    world.scene.add(FixedCuboid('/World/PlywoodMap', name='plywood_map', size=1.,
        position=np.array([0., 1.42, -.008]), scale=np.array(FIXTURE['board_size_m']),
        color=np.array([.35, .36, .37])))
    # shortcut: CAD paint is visually transcribed; surveyed workbench registration replaces nominal photo poses.
    paths = [[(.738, .10), (.738, .02), (1.13, .02), (1.21, .10), (1.21, 2.34),
              (1.13, 2.42), (.818, 2.42), (.738, 2.34), (.738, 1.69),
              (.338, 1.49), (.338, .56), (.738, .36), (.738, .10)],
             [(.98, .30), (.98, 2.14)], [(.738, .675), (.738, 1.375)]]
    count = 0
    for path in paths:
        for a, b in zip(path, path[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            obj = world.scene.add(VisualCuboid('/World/Tape'+str(count), name='tape'+str(count), size=1.,
                position=np.array([(a[0]+b[0])/2-.61, (a[1]+b[1])/2+.20, .0015]),
                scale=np.array([math.hypot(dx, dy), .01, .001]), color=np.ones(3)))
            UsdGeom.XformCommonAPI(obj.prim).SetRotate(Gf.Vec3f(0., 0., math.degrees(math.atan2(dy, dx))))
            count += 1
    for i, y in enumerate((-.15, .15)):
        world.scene.add(VisualCuboid('/World/YellowBench'+str(i), name='yellow_bench'+str(i), size=1.,
            position=np.array([-.10, y, -.001]), scale=np.array([.26, .25, .002]),
            color=np.array([.95, .72, .06])))


def execute(args, world, stage, robots, joints, fingers, cargo, contacts, capture, grasp_probes,
            planner, initial, tcp_position):
    import numpy as np
    from pxr import UsdGeom
    cube = args.mapped_cube_stack
    fixture = CUBE_FIXTURE if cube else FIXTURE
    targets = [np.zeros(r.num_dof) for r in robots]
    tick = 0
    images, trials = [], []
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
        efforts[0, fingers[i]] = [.2, 2.]
        view.set_max_efforts(efforts)
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
        for _ in range(FIXTURE['physics_substeps']):
            world.step(render=False, update_fabric=True)
        tick += 1
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
        return dict(tick=tick, boxes=boxes, tcps=tcps,
            joints=[r.get_joint_positions().tolist() for r in robots],
            commands=[v.tolist() for v in targets],
            bases=[r.get_world_pose()[0].tolist() for r in robots])

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
        frames = planner.request('move', base=FIXTURE['arm_bases_m'][arm],
            start=targets[arm][joints[arm]].tolist(), target=[float(v) for v in point], yaw=float(yaw), dt=DT)['frames']
        for q in frames:
            targets[arm][joints[arm]] = q
            step()
        hold(120)

    def grip(arm, value):
        start = targets[arm][fingers[arm][0]]
        duration = max(.8, 1.875*abs(value-start)/.4, math.sqrt(5.774*abs(value-start)/.4))
        for u in np.linspace(0., 1., math.ceil(duration/DT)+1)[1:]:
            targets[arm][fingers[arm][0]] = start+(value-start)*u**3*(10+u*(-15+6*u))
            step()
        hold(60)

    for trial_index in range(fixture['trials']):
        trial = dict(seed=args.seed+trial_index, layers=[])
        trials.append(trial)
        rng = np.random.default_rng(trial['seed'])
        for i, box in enumerate(cargo):
            box.set_world_pose(np.array([-.45, .4+i*.065, .016]), np.array([1., 0., 0., 0.]))
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
        try:
            if any(np.max(np.abs(robot.get_joint_positions()[joints[i]]-targets[i][joints[i]])) > .03
                   for i, robot in enumerate(robots)):
                raise ValueError('initial arm tracking exceeds 0.03 rad')
            for index, item in enumerate(plan(cube)):
                arm, box = item['arm'], cargo[index]
                UsdGeom.Imageable(box.prim).MakeVisible()
                yaw = float(rng.uniform(-.01, .01))
                box.set_world_pose(np.array([.16+rng.uniform(-.001, .001), -.09+rng.uniform(-.001, .001), .041]),
                    np.array([math.cos(yaw/2), 0., 0., math.sin(yaw/2)]))
                box.set_linear_velocity(np.zeros(3)); box.set_angular_velocity(np.zeros(3))
                start = box.get_world_pose()[0].copy()
                hold(360)
                p, q = box.get_world_pose()
                trial['belt_displacement_m'] = (p-start).tolist()
                if not .01 < p[1]-start[1] < .06:
                    raise ValueError('belt failed to transport cargo')
                yaw = math.atan2(2*(q[0]*q[3]+q[1]*q[2]), 1-2*(q[2]**2+q[3]**2))
                layer = dict(item=index, arm=arm, source_center_z=float(p[2]),
                    infeed_start=start.tolist(), infeed_settled=p.tolist(), grasp_samples=[], lift_samples=[], settle_samples=[])
                trial['layers'].append(layer)
                move(arm, [p[0], p[1], .145], yaw)
                grip(arm, initial['gripper']['preopen'])
                move(arm, [p[0], p[1], p[2]+.002], yaw)
                layer['grasp_samples'].append(grasp_snapshot(arm))
                grip(arm, initial['gripper']['close'])
                layer['grasp_samples'].append(grasp_snapshot(arm))
                move(arm, [p[0], p[1], .145], yaw)
                layer['lift_samples'] = samples(36)
                if not all(free_lift(s['boxes'][index], arm, float(p[2])) for s in layer['lift_samples']):
                    photo('mapped-grasp-failed.png')
                    raise ValueError('bilateral free lift failed; transport interlock stopped the arm')
                move(arm, [*item['target'][:2], .145])
                if cube:
                    layer['carry_sample'] = snapshot()
                    layer['release_samples'] = []
                    for _ in range(fixture['release_feedback_iterations']):
                        move(arm, cube_release_target(index, snapshot(), float(p[2])))
                        layer['release_samples'].append(snapshot())
                else:
                    move(arm, [*item['target'][:2], item['target'][2]+.003])
                if cube:
                    layer['release_sample'] = snapshot()
                grip(arm, initial['gripper']['release'])
                if cube:
                    layer['opened_sample'] = snapshot()
                move(arm, [*item['target'][:2], .145])
                move(arm, home(arm))
                layer['settle_samples'] = samples(132)
                if not all(stable_box(s['boxes'][j], j, cube) for s in layer['settle_samples'] for j in range(index+1)):
                    raise ValueError('released stack failed stability; next infeed blocked')
                if trial_index == 0:
                    photo('mapped-layer-'+str(index+1)+'.png')
                print('MAPPED_LAYER', trial_index, index+1, flush=True)
        except (ValueError, RuntimeError) as exc:
            trial['error'] = str(exc)[:400]
        trial.update(judge(trial, cube))
        photo('mapped-trial-'+str(trial_index+1)+'.png')
        print('MAPPED_TRIAL', trial_index, trial['task_success'], trial.get('error'), trial['failures'], flush=True)
        if not trial['task_success']:
            break
    stage.GetRootLayer().Export(str(args.report.parent/'mapped-scene.usda'))
    return dict(schema='rosy.omx-map-cube-stack/1' if cube else 'rosy.omx-map-long-stack/1', fixture=fixture, seed=args.seed, trials=trials,
        task_success=len(trials) == fixture['trials'] and all(t['task_success'] for t in trials),
        controller=FIXTURE['controller'], attachment_aid=False, images=images)
