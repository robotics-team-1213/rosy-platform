"""Stable stack window sampling, offline SIM planner, servo control, and CAD board context helpers."""
import hashlib
import json
import math
from pathlib import Path
import subprocess

from mapped_stack_fixture import (
    DT,
    FIXTURE,
    PROFILE,
    ROOT,
    PackingFootprintUnavailable,
    cube_release_target,
    measured_motion,
    norm,
    prefix_held,
    stable_box,
)


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
    def __init__(self, directory, *, scene=None, tcp_x_m=None):
        self.directory, self.count = Path(directory), 0
        self.scene, self.tcp_x_m = scene, tcp_x_m  # tcp_x_m only for an opt-in jaw with another TCP

    def request(self, operation, **fields):
        from stacking_report import read_regular
        self.count += 1
        request = self.directory/f'plan-request-{self.count}.json'
        output = self.directory/f'plan-frames-{self.count}.json'
        if self.scene is not None:
            fields = dict(fields,scene=self.scene)
        if self.tcp_x_m is not None:
            fields = dict(fields,tcp_x_m=self.tcp_x_m)
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
    if fixture.get('leveling_protocol') and not (fixture.get('demo_recording') or fixture.get('policy')):  # D-969: no aids in policy frames
        size = fixture['leveling_size_m']
        for spot, center in enumerate(fixture.get('leveling_centers_m') or [fixture['leveling_center_m']]):
            for axis in (0,1):
                for side,sign in enumerate((-1,1)):
                    position=np.array([*center[:2],center[2]+.0004])
                    position[1-axis]+=sign*size[1-axis]/2
                    scale=np.array([.0006,.0006,.0006]);scale[axis]=size[axis]
                    name=f'LevelingBoundary{axis}_{side}'+(f'_{spot}' if spot else '')
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


def configure_mapped_robots(robots, joints, fingers, fixture):
    """Apply SI gains, fixed-base check, max efforts, and solver iteration counts to mapped OMX robots."""
    import numpy as np
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
