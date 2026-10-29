"""Confluence board layout and contact-only acceptance for three long-bar layers."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from stacking_fixture import DT, PROFILE

ROOT = Path(__file__).resolve().parents[3]
CUBE_REPORT_BYTES = 2*1024*1024
FIXTURE = dict(revision='confluence-map-long-stack-v1',
    confluence_page='8683759', cad_attachment='8585450', photo_attachment='8585456',
    cad_sha256='a0a4be65cabc662c6f93b7a89abb2447e84b07684a277533078616e477ff8cd7',
    photo_sha256='51675e610e1b4d3e1580599b3b4caa31decdc19a6a611dec4be6b83bbc755cbb',
    board_size_m=[1.22, 2.44, .018], board_lower_left_m=[-.61, .20, .001],
    cell_pose_scope='PHOTO_DERIVED_NOMINAL_NOT_CALIBRATED',
    coordinate_scope='CONFLUENCE_CAD_WITH_NOMINAL_PHOTO_CELL',
    arm_bases_m=[[0., -.09, 0.], [0., .09, 0.]],
    bin_origin_m=[.115, -.015, .025], bin_size_m=[.09, .03, .09],
    belt_size_m=[.12, .50, .025], belt_speed_m_s=.02,
    physics_dt_s=DT/2, physics_substeps=2, attachment_aid=False, trials=3,
    drive_gain_units='N_M_PER_RAD_NATIVE_ARTICULATION_API',
    arm_stiffness_si=40., arm_damping_si=2*math.sqrt(40)*.5+.3, arm_max_effort_nm=2.,
    arm_feedforward='MODEL_GRAVITY_COMPENSATION',
    imported_newton_mimic_enabled=False,
    fixed_base=True,
    finger_collision='CALIBRATED_CAPSULE_ONLY',
    robot_contact_offset_m=.0005,
    solver_position_iterations=64, solver_velocity_iterations=16,
    massless_tcp_frame=True,
    minimum_lift_m=.03, xy_tolerance_m=.0015, z_tolerance_m=.0015,
    envelope_tolerance_m=.001, settle_steps=120, seed_effect='INFEED_XY_AND_YAW',
    controller='NOMINAL_IK_REFERENCE_NOT_LEARNED_POLICY')

RL_FIXTURE = dict(FIXTURE, revision='confluence-map-stacking-rl-v1',
    controller='RSL_RL_PPO_DIRECT_JOINT_VELOCITY', control_decimation=4, max_episode_steps=6000,
    iterations=32, steps_per_update=32, num_envs=1, trials=1, evaluation_seed_offset=10000,
    infeed_jitter_m=.003, infeed_yaw_jitter_rad=.03)

CUBE_FIXTURE = dict(FIXTURE, revision='confluence-map-cube-stack-v1', trials=1,
    bin_origin_m=[.115, 0., .025], bin_size_m=[.09, .09, .09],
    release_clearance_m=.035, row_clearance_m=.0002, release_feedback_iterations=4)


def plan(cube=False):
    if cube:
        return [dict(id='bar-'+str(i+1), cells=3, cell=[0, i % 3, i//3], size=[.09, .03, .03],
                     mass=.06, arm=(1 if i % 3 == 2 else 0 if i % 3 == 0 else (i//3) % 2),
                     target=[.16, .015+(i % 3)*.03, .04+(i//3)*.03]) for i in range(9)]
    return [dict(id='bar-'+str(i+1), cells=3, cell=[0, 0, i], size=[.09, .03, .03],
                 mass=.06, arm=i % 2, target=[.16, 0., .04+i*.03]) for i in range(3)]


def home(arm):
    return [.05, FIXTURE['arm_bases_m'][arm][1]+(-.20 if arm == 0 else .20), .13]


def check_massless_tcp(urdf):
    root = ET.parse(urdf).getroot()
    link = root.find("link[@name='end_effector_link']")
    joint = root.find("joint[@name='end_effector_joint']")
    if (link is None or link.find('inertial') is not None or link.find('collision') is not None
            or joint is None or joint.get('type') != 'fixed'
            or joint.find('parent').get('link') != 'link5'
            or joint.find('child').get('link') != 'end_effector_link'):
        raise ValueError('TCP must be the pinned massless visual frame fixed to link5')
    return root


def physical_model(urdf):
    root = check_massless_tcp(urdf)
    root.remove(root.find("link[@name='end_effector_link']"))
    root.remove(root.find("joint[@name='end_effector_joint']"))
    return ET.ElementTree(root)


def tcp_from_wrist(position, quaternion):
    w, x, y, z = quaternion
    matrix = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
              (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
              (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    offset = (.09193, -.0016, 0.)
    return [position[i]+sum(matrix[i][j]*offset[j] for j in range(3)) for i in range(3)]


def contact_names(index, cube=False):
    return ['a-left', 'a-right', 'b-left', 'b-right', 'bin', 'conveyor']+[
        item['id'] for i, item in enumerate(plan(cube)) if i != index]


def norm(values):
    return math.sqrt(sum(v*v for v in values))


def explained_contacts(box):
    return norm([box['net_force'][axis]-sum(f[axis] for f in box['forces']) for axis in range(3)]) <= .001


def free_lift(box, arm, source_z):
    forces = box['forces']
    return (box['position'][2] >= source_z+FIXTURE['minimum_lift_m']
        and all(norm(f) > .005 for f in forces[2*arm:2*arm+2])
        and all(norm(f) <= .001 for n, f in enumerate(forces) if n not in (2*arm, 2*arm+1))
        and explained_contacts(box))


def cube_release_target(index, sample, source_z):
    item = plan(True)[index]
    box, arm = sample['boxes'][index], item['arm']
    if not free_lift(box, arm, source_z):
        raise ValueError('cube carry lost bilateral free lift before release')
    desired = item['target'][:]
    desired[2] += CUBE_FIXTURE['release_clearance_m']
    if index % 3:
        def half_width(body):
            w, x, y, z = body['orientation']
            row = (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w))
            return sum(abs(row[k])*item['size'][k]/2 for k in range(3))
        neighbor = sample['boxes'][index-1]
        desired[1] = max(desired[1], neighbor['position'][1]+half_width(neighbor)+half_width(box)+CUBE_FIXTURE['row_clearance_m'])
    return [sample['tcps'][arm][k]+desired[k]-box['position'][k] for k in range(3)]


def cube_release_ready(index, sample, source_z):
    command = cube_release_target(index, sample, source_z)
    tcp = sample['tcps'][plan(True)[index]['arm']]
    error = [command[k]-tcp[k] for k in range(3)]
    return norm(error) <= .00005 and (index % 3 == 0 or error[1] <= .000001)


def stable_box(box, index, cube=False):
    items = plan(cube)
    fixture = CUBE_FIXTURE if cube else FIXTURE
    item = items[index]
    p, q, forces = box['position'], box['orientation'], box['forces']
    values = [*p, *q, *box['velocity'], *box['angular_velocity'], *(v for row in forces for v in row)]
    if not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in q)-1) > .01:
        return False
    if (any(abs(p[i]-item['target'][i]) > .0015 for i in range(3))
            or norm(box['velocity']) > .01 or norm(box['angular_velocity']) > .1
            or any(norm(f) > .001 for f in forces[:4]) or not explained_contacts(box)):
        return False
    width = 3 if cube else 1
    below = 'bin' if index < width else items[index-width]['id']
    if forces[contact_names(index, cube).index(below)][2] <= .001:
        return False
    w, x, y, z = q
    matrix = ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
              (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
              (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))
    for axis in range(3):
        extent = sum(abs(matrix[axis][j])*item['size'][j]/2 for j in range(3))
        low = fixture['bin_origin_m'][axis]
        if p[axis]-extent < low-.001 or p[axis]+extent > low+fixture['bin_size_m'][axis]+.001:
            return False
    return True


def judge(trial, cube=False):
    failures = []
    layers = trial.get('layers', [])
    if len(layers) != len(plan(cube)):
        return dict(task_success=False, failures=['nine_bars_not_completed' if cube else 'three_layers_not_completed'])
    for i, layer in enumerate(layers):
        if layer.get('item') != i or layer.get('arm') != plan(cube)[i]['arm']:
            failures.append(f'layer_{i+1}:wrong_item_or_arm')
        lifts, settles = layer.get('lift_samples', []), layer.get('settle_samples', [])
        if len(lifts) < 3 or lifts[-1]['tick']-lifts[0]['tick'] < 24:
            failures.append(f'layer_{i+1}:lift_not_observed')
        else:
            for sample in lifts:
                box = sample['boxes'][i]
                forces = box['forces']
                arm = plan(cube)[i]['arm']
                if not free_lift(box, arm, layer['source_center_z']):
                    failures.append(f'layer_{i+1}:no_bilateral_free_lift')
                    break
        if len(settles) < 10 or settles[-1]['tick']-settles[0]['tick'] < FIXTURE['settle_steps']:
            failures.append(f'layer_{i+1}:settle_not_observed')
        else:
            for sample in settles:
                if (not all(stable_box(sample['boxes'][j], j, cube) for j in range(i+1))
                        or any(norm([tcp[k]-sample['boxes'][j]['position'][k] for k in range(3)]) < .04
                               for tcp in sample['tcps'] for j in range(i+1))):
                    failures.append(f'layer_{i+1}:release_support_or_retreat_failed')
                    break
    return dict(task_success=not failures, failures=failures)
