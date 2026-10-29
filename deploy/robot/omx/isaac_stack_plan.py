"""Offline SIM-only OMX IK producer; consumes a pose case and emits joint frames."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'middleware/devices/omx/adapter'))
from omx_adapter.kinematics import OmxKinematics, TopDownPose
from omx_adapter.contracts.transfer_motion import ArmPlanningProfile

PROFILE = ROOT/'deploy/robot/omx/sim/cell_profile.yaml'
SCHEMA = 'rosy.omx-sim-stack-plan/1'


def vector(value, count):
    if (not isinstance(value, list) or len(value) != count
            or not all(type(v) in (int, float) and math.isfinite(v) for v in value)):
        raise ValueError('Finite planning vector required')
    return value


def build(case):
    if not isinstance(case, dict) or case.get('schema') != SCHEMA:
        raise ValueError('Unexpected SIM planning case')
    kin, profile = OmxKinematics.load(), ArmPlanningProfile.load(PROFILE)
    control = yaml.safe_load(PROFILE.read_text(encoding='utf-8'))
    if control['profile'] != 'simulation':
        raise ValueError('Only the simulation planning profile is allowed')

    def solve(base, point, yaw, reference=0., base_yaw=0.):
        dx, dy = point[0]-base[0], point[1]-base[1]
        c, s = math.cos(base_yaw), math.sin(base_yaw)
        pose = TopDownPose(c*dx+s*dy, -s*dx+c*dy, point[2]-base[2], yaw-base_yaw)
        result = kin.solve_top_down(pose, profile.ik_limits(), reference_q5=reference)
        if not result.ok:
            raise ValueError(f'Unreachable SIM target: {result.reason} {result.detail}')
        return list(result.joints)

    result = dict(schema=SCHEMA, joints=['joint'+str(i) for i in range(1, 6)],
                  profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest())
    if case.get('operation') == 'homes':
        if set(case)-{'base_yaws'} != {'schema', 'operation', 'bases', 'points'} or len(case['bases']) != 2 or len(case['points']) != 2:
            raise ValueError('Two simulation homes required')
        yaws = vector(case.get('base_yaws', [0., 0.]), 2)
        result['homes'] = [solve(vector(b, 3), vector(p, 3), 0., base_yaw=y)
                           for b, p, y in zip(case['bases'], case['points'], yaws)]
        result['gripper'] = dict(preopen=profile.gripper_contact_for_width(.036),
            close=profile.gripper_close_for_width(.03), release=profile.gripper_contact_for_width(.04))
        return result
    if case.get('operation') != 'move' or set(case)-{'base_yaw'} != {'schema', 'operation', 'base', 'start', 'target', 'yaw', 'dt'}:
        raise ValueError('Unexpected SIM planning operation')
    base, start, target = vector(case['base'], 3), vector(case['start'], 5), vector(case['target'], 3)
    yaw, dt = vector([case['yaw'], case['dt']], 2)
    base_yaw = vector([case.get('base_yaw', 0.)], 1)[0]
    if not math.isclose(dt, 1/120, rel_tol=1e-9):
        raise ValueError('Only the pinned simulation timestep is supported')
    initial = kin.fk(start)
    c, s = math.cos(base_yaw), math.sin(base_yaw)
    point = [c*initial.x-s*initial.y+base[0], s*initial.x+c*initial.y+base[1], initial.z+base[2]]
    initial_yaw = initial.yaw+base_yaw
    # Parallel jaws have pi symmetry; retain the nearest equivalent grasp direction.
    yaw += round((initial_yaw-yaw)/math.pi)*math.pi
    q5 = start[-1]

    def curve(u):
        nonlocal q5
        s = u**3*(10+u*(-15+6*u))
        q = solve(base, [point[i]+(target[i]-point[i])*s for i in range(3)],
                  initial_yaw+(yaw-initial_yaw)*s, q5, base_yaw)
        q5 = q[-1]
        return q

    coarse = [curve(i/100) for i in range(101)]
    limits = [control['joints']['joint'+str(i)] for i in range(1, 6)]
    vmax = max(abs(coarse[i+1][j]-coarse[i][j])*100/(.8*limits[j]['velocity']) for i in range(100) for j in range(5))
    amax = max(abs(coarse[i+2][j]-2*coarse[i+1][j]+coarse[i][j])*10000/(.8*limits[j]['acceleration']) for i in range(99) for j in range(5))
    duration = max(.8, vmax, math.sqrt(amax))
    steps = math.ceil(duration/dt)
    if steps > 60000:
        raise ValueError('SIM trajectory exceeds the planning budget')
    # The coarse sweep ends at another wrist branch; the executed sweep must start from the original branch.
    q5 = start[-1]
    frames = [curve(i/steps) for i in range(1, steps+1)]
    previous, velocity = start, [0.]*5
    for q in frames+[frames[-1]]:
        next_velocity = [(q[j]-previous[j])/dt for j in range(5)]
        if any(abs(next_velocity[j]) > limits[j]['velocity']+1e-7
               or abs(next_velocity[j]-velocity[j])/dt > limits[j]['acceleration']+1e-7 for j in range(5)):
            raise ValueError('SIM trajectory exceeds joint motion limits')
        previous, velocity = q, next_velocity
    result.update(dt=dt, frames=frames)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.case.stat().st_size > 16384:
        raise ValueError('SIM planning case too large')
    value = build(json.loads(args.case.read_text(encoding='utf-8')))
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, allow_nan=False)


if __name__ == '__main__':
    main()
