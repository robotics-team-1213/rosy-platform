"""Offline SIM-only OMX IK producer; consumes a pose case and emits joint frames."""
import argparse
from dataclasses import replace
import hashlib
import json
import math
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'middleware/devices/omx/adapter'))
from omx_adapter.kinematics import DEFAULT_KINEMATICS_PATH, OmxKinematics, TopDownPose
from omx_adapter.contracts.transfer_motion import ArmPlanningProfile

PROFILE = ROOT/'deploy/robot/omx/sim/cell_profile.yaml'
SCHEMA = 'rosy.omx-sim-stack-plan/1'


# Named SIM planning scenes: the arm base/yaw pairs each scene was built for, and the z band of its low belt corridor.
# The surveyed scenes (cell survey 2026-11-03, D-947 2) are candidates beside the CAD one, not a replacement.
_CAD_BASES = (([.08,-.165,.072], math.pi/2), ([.08,.165,.072], -math.pi/2))
_SURVEYED_BASES = (([.116,-.164,.072], math.pi/2), ([.104,.153,.072], math.radians(-94.3)))
_SURVEYED_SKEW_BASES = (([.116,-.164,.072], math.pi/2), ([.107,.164,.072], -math.pi/2))
SCENES = {'cad-stage1-lower-belt-v1': (_CAD_BASES, (.040, .077)),
          'surveyed-bases-20261103': (_SURVEYED_BASES, (.040, .077)),
          # belt 28 mm below the CAD face: only the corridor floor drops; its top stays where a TCP counts as low
          'surveyed-cell-20261103': (_SURVEYED_BASES, (.040-.028, .077)),
          'surveyed-cell-20261110-skew-vision': (_SURVEYED_SKEW_BASES, (.040-.028, .077))}


def vector(value, count):
    if (not isinstance(value, list) or len(value) != count
            or not all(type(v) in (int, float) and math.isfinite(v) for v in value)):
        raise ValueError('Finite planning vector required')
    return value


def build(case):
    if not isinstance(case, dict) or case.get('schema') != SCHEMA:
        raise ValueError('Unexpected SIM planning case')
    kin, profile = OmxKinematics.load(), ArmPlanningProfile.load(PROFILE)
    if 'tcp_x_m' in case:  # opt-in jaw with another TCP (the palletizing jaw v2.1 ends at 0.0740); stock stays 0.09193
        tcp_x = vector([case['tcp_x_m']], 1)[0]
        if not .05 <= tcp_x <= .12:
            raise ValueError('TCP x outside the OMX-F jaw range')
        document = yaml.safe_load(DEFAULT_KINEMATICS_PATH.read_text(encoding='utf-8'))
        next(j for j in document['joints'] if j['name'] == 'end_effector_joint')['origin']['xyz'][0] = tcp_x
        kin = OmxKinematics(document)
    control = yaml.safe_load(PROFILE.read_text(encoding='utf-8'))
    if control['profile'] != 'simulation':
        raise ValueError('Only the simulation planning profile is allowed')
    scene = case.get('scene')
    if 'scene' in case and scene not in SCENES:
        raise ValueError('Unknown SIM planning scene')

    def solve(base, point, yaw, reference=0., base_yaw=0.):
        dx, dy = point[0]-base[0], point[1]-base[1]
        c, s = math.cos(base_yaw), math.sin(base_yaw)
        pose = TopDownPose(c*dx+s*dy, -s*dx+c*dy, point[2]-base[2], yaw-base_yaw)
        limits = profile.ik_limits()
        if scene:
            approved, (z_low, z_high) = SCENES[scene]
            if not any(all(abs(base[k]-b[k]) <= 1e-9 for k in range(3)) and abs(base_yaw-a) <= 1e-9 for b,a in approved):
                raise ValueError('CAD scene base/yaw pair differs')
            if pose.z < limits.workspace_min_m[2]:
                # This scene alone reaches below the raised plate, in the external belt corridor.
                if not (.201 <= point[0] <= .270 and -.013 <= point[1] <= .027 and z_low <= point[2] <= z_high):
                    raise ValueError('Low TCP must remain outside the Stage1 footprint in its belt corridor')
                limits = replace(limits,workspace_min_m=(*limits.workspace_min_m[:2],-.04-(.040-z_low)))  # CAD scene: -0.04
        result = kin.solve_top_down(pose, limits, reference_q5=reference)
        if not result.ok:
            raise ValueError(f'Unreachable SIM target: {result.reason} {result.detail}')
        return list(result.joints)

    result = dict(schema=SCHEMA, joints=['joint'+str(i) for i in range(1, 6)],
                  profile_sha256=hashlib.sha256(PROFILE.read_bytes()).hexdigest())
    if scene:
        result['planning_scene'] = scene
    if case.get('operation') == 'homes':
        if set(case)-{'base_yaws','scene','tcp_x_m'} != {'schema', 'operation', 'bases', 'points'} or len(case['bases']) != 2 or len(case['points']) != 2:
            raise ValueError('Two simulation homes required')
        yaws = vector(case.get('base_yaws', [0., 0.]), 2)
        result['homes'] = [solve(vector(b, 3), vector(p, 3), 0., base_yaw=y)
                           for b, p, y in zip(case['bases'], case['points'], yaws)]
        result['gripper'] = dict(preopen=profile.gripper_contact_for_width(.036),
            close=profile.gripper_close_for_width(.03), release=profile.gripper_contact_for_width(.04))
        return result
    if case.get('operation') != 'move' or set(case)-{'base_yaw','scene','tcp_x_m'} != {'schema', 'operation', 'base', 'start', 'target', 'yaw', 'dt'}:
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
    # A nearest-angle tie can cross a wrist limit; try equivalent endpoints without relaxing limits.
    preferred = yaw+round((initial_yaw-yaw)/math.pi)*math.pi
    alternatives = sorted((preferred-math.pi,preferred+math.pi),key=lambda value:abs(value-initial_yaw))
    q5 = start[-1]

    def curve(u):
        nonlocal q5
        s = u**3*(10+u*(-15+6*u))
        q = solve(base, [point[i]+(target[i]-point[i])*s for i in range(3)],
                  initial_yaw+(yaw-initial_yaw)*s, q5, base_yaw)
        q5 = q[-1]
        return q

    limits = [control['joints']['joint'+str(i)] for i in range(1, 6)]
    failure = None
    for yaw in (preferred,*alternatives):
        try:
            q5 = start[-1]
            coarse = [curve(i/100) for i in range(101)]
            vmax = max(abs(coarse[i+1][j]-coarse[i][j])*100/(.8*limits[j]['velocity']) for i in range(100) for j in range(5))
            amax = max(abs(coarse[i+2][j]-2*coarse[i+1][j]+coarse[i][j])*10000/(.8*limits[j]['acceleration']) for i in range(99) for j in range(5))
            steps = math.ceil(max(.8,vmax,math.sqrt(amax))/dt)
            if steps > 60000:
                raise ValueError('SIM trajectory exceeds the planning budget')
            # Reset the wrist branch after each coarse sweep.
            q5 = start[-1]
            frames = [curve(i/steps) for i in range(1,steps+1)]
            previous, velocity = start,[0.]*5
            for q in frames+[frames[-1]]:
                next_velocity = [(q[j]-previous[j])/dt for j in range(5)]
                if any(abs(next_velocity[j]) > limits[j]['velocity']+1e-7
                       or abs(next_velocity[j]-velocity[j])/dt > limits[j]['acceleration']+1e-7 for j in range(5)):
                    raise ValueError('SIM trajectory exceeds joint motion limits')
                previous, velocity = q,next_velocity
            break
        except ValueError as exc:
            failure = failure or exc
    else:
        raise failure
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
