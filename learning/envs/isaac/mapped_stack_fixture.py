"""Confluence board layout and contact-only acceptance for three long-bar layers."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from stacking_fixture import DT, PROFILE

ROOT = Path(__file__).resolve().parents[3]
CUBE_REPORT_BYTES = 2*1024*1024
CONTAINER_REPORT_BYTES = 16*1024*1024
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

CUBE_FIXTURE = dict(FIXTURE, revision='rosycam-edge-container-first-layer-v4', trials=1,
    target_stage='FIRST_LAYER_ONLY', target_cells=[3, 3, 1],
    cargo_colors_rgb=[[.025, .25, .05], [.80, .15, .015], [.025, .25, .05]],
    cargo_visual='CORRUGATED_CONTAINER_VISUAL_BOX_COLLIDER',
    cell_pose_scope='USER_CONFIRMED_TOPOLOGY_NOMINAL_DIMENSIONS_NOT_SURVEYED',
    camera_reference='2026-10-29T03:43:11Z_ceiling_north',
    board_lower_left_m=[-.61, -.25, .001],
    workplate_center_m=[0., 0., .02], workplate_size_m=[.40, .42, .02],
    arm_bases_m=[[.08, -.13, .03], [.08, .13, .03]],
    arm_base_yaws_rad=[math.pi/2, -math.pi/2],
    belt_center_m=[.376, 0., .0125], belt_size_m=[.35, .12, .025],
    belt_velocity_m_s=[-.02, 0., 0.], belt_stop_m=[.203, 0., .027], belt_stop_size_m=[.004, .12, .004],
    upstream_belt_center_m=[.491, .235, .0125], upstream_belt_size_m=[.12, .35, .025],
    upstream_velocity_m_s=[0., -.02, 0.], upstream_scope='LAYOUT_ONLY_TURN_TRANSFER_NOT_EVALUATED',
    infeed_start_m=[.295, 0., .041], pickup_center_m=[.25, 0., .04], carry_height_m=.135,
    bin_origin_m=[.085, -.045, .032], bin_size_m=[.09, .09, .03],
    release_clearance_m=.015, finger_max_efforts_nm=[.2, 2.],
    release_gripper_acceleration_rad_s2=.1,
    row_clearance_m=.0001, first_row_release_bias_m=-.0006,
    release_feedback_iterations=4)


def grip_duration(start, value, acceleration=.4):
    if not all(math.isfinite(x) for x in (start, value, acceleration)) or acceleration <= 0:
        raise ValueError('gripper positions must be finite and acceleration positive')
    delta = abs(value-start)
    return max(.8, 1.875*delta/.4, math.sqrt(5.774*delta/acceleration))


from release_cases import EVALUATION_CASES, RL_RESIDUALS  # noqa: E402  (pinned model and residual files)


def container_fixture(*, layers, case):
    if case in EVALUATION_CASES:
        value = container_fixture(layers=layers, case='nominal')
        value.update(revision=value['revision']+'-'+case, case=case, release_estimate_noise_m=[.002, .005],
                     release_convergence_m=.0015)
        if EVALUATION_CASES[case]:
            value['release_corrector'] = dict(EVALUATION_CASES[case])
        if case in RL_RESIDUALS:
            spec = dict(RL_RESIDUALS[case])
            value['release_exploration_sigma_m'] = spec.pop('sigma_m')
            value['release_residual'] = spec
        if case.startswith('release-episodes'):
            value['release_episodes'] = 40  # short single-placement episodes for RL; see release_episodes.py
        return value
    if (type(layers) is not int or layers not in (1, 3) or case not in ('nominal', 'offset', 'reverse','column')
            or case=='column' and layers!=3):
        raise ValueError('container settings require layers1/3 and nominal/offset/reverse, or layers3/column')
    value = dict(CUBE_FIXTURE, revision='final-map-cad-container-stack-v11', target_stage='CONTAINER_STACK',
        layers=layers, case=case, target_cells=[3, 3, layers], bin_size_m=[.09, .09, .03*layers],
        row_order=[1, 2, 0] if case == 'reverse' else [1, 0, 2], carry_height_m=.17,
        packing_strategy='CENTER_THEN_INDEPENDENT_OUTER_ROWS',
        neighbor_vertical_clearance_m=.002,
        infeed_jitter_xy_m=[.001, .001] if case in ('nominal','column') else [.005, .008],
        infeed_yaw_jitter_rad=.01 if case in ('nominal','column') else .08,
        opening_sample_ticks=6,
        release_gripper_acceleration_rad_s2=.025,
        recording=dict(file='mapped-video.mp4', fps=10, width=800, height=600,
            every_control_ticks=12, max_render_updates=8, render_clock='REFERENCE_TIME_SECONDS', eye=[.69, -.72, .62], focus=[.17, 0., .08]))
    value.pop('first_row_release_bias_m')
    # STEP13205531: Xsim=(Zcad+355)/1000,Ysim=(Xcad-793)/1000,Zsim=(Ycad-19)/1000.
    pitch = math.atan2(34.467331, 431.475521)
    plane = [(-329.307196+102.168325)/2000+.355, .007,
             (41.663959+76.131290)/2000-.019]
    thickness = .004
    value.update(confluence_page='13205531', cad_attachment='12583007',
        cad_sha256='c455f11ab450cfcb9633a58387b0c0ec56f56727d23b4736ba5853334708f891',
        cad_stl_attachment='12681256', photo_confluence_page='8683759',
        cell_pose_scope='CAD_ASSEMBLY_DATUM_NOT_SURVEYED_MOTOR_AXIS',
        coordinate_scope='STEP_MM_TO_SIM_Z_X_Y_WITH_TRANSLATION',
        cad_frame_transform_m=[[0.,0.,.001,.355],[.001,0.,0.,-.793],[0.,.001,0.,-.019]],
        controlled_cad_instances=['NAUO8','NAUO7'],
        planning_scene='cad-stage1-lower-belt-v1',
        excluded_cad_instances=['NAUO6_ON_STAGE2_NOT_PART_OF_TWO_ARM_TASK'],
        road_markup='UNMODELED_IN_NEW_CAD_WORKCELL',
        board_lower_left_m=[-.255,-2.013,0.], board_size_m=[1.220,2.440,.019],
        workplate_center_m=[-.225,-.0245,.063], workplate_size_m=[.760,.603,.018],
        arm_bases_m=[[.08,-.165,.072],[.08,.165,.072]],
        bin_origin_m=[.035,-.045,.074], carry_height_m=.212,
        stack_region_scope='USER_TASK_ENVELOPE_ON_STAGE1_NOT_A_CAD_LABEL',
        belt_pitch_rad=pitch,
        belt_center_m=[plane[0]+math.sin(pitch)*thickness/2,plane[1],plane[2]-math.cos(pitch)*thickness/2],
        belt_size_m=[math.hypot(431.475521,34.467331)/1000,.085,thickness],
        belt_velocity_m_s=[-.02*math.cos(pitch),0.,-.02*math.sin(pitch)],
        belt_geometry_scope='CAD_PLANAR_FACE_PROXY_NOT_FULL_MECHANICAL_BELT',
        belt_stop_m=[.158,.007,(41.663959-19)/1000+(.158-.025692804)*math.tan(pitch)+.002],
        belt_stop_size_m=[.004,.085,.004],
        belt_stop_scope='TASK_STOP_BEFORE_PLATE_NOT_A_CAD_ENDSTOP',
        pickup_center_m=[.207,.007,(41.663959-19)/1000+(.207-.025692804)*math.tan(pitch)+.015/math.cos(pitch)],
        infeed_start_m=[.252,.007,(41.663959-19)/1000+(.252-.025692804)*math.tan(pitch)+.015/math.cos(pitch)+.001])
    value.update(parking_origin_m=[.65,-1.8,.016],parking_step_y_m=.10)
    value.update(leveling_protocol='TABLE_SUPPORT_THEN_REGRASP',leveling_center_m=[-.04,0.,.072],
        leveling_size_m=[.12,.10],leveling_flat_tolerance_rad=.01,leveling_yaws_rad=[math.pi,math.pi])
    for key in ('upstream_belt_center_m','upstream_belt_size_m','upstream_velocity_m_s','upstream_scope'):
        value.pop(key)
    value['recording'] = dict(value['recording'], eye=[.69,-.78,.69], focus=[.08,0.,.12])
    if case=='column':
        value.update(revision='final-map-cad-container-column-v1',target_cells=[3,1,3],
            row_order=[0],center_row=0,bin_origin_m=[.035,-.015,.074],bin_size_m=[.09,.03,.09])
    else:
        # D-929: rows keep a measured 2-5mm gap instead of touching; the envelope grows by the two gaps.
        value.update(revision='final-map-cad-container-gap-v1',row_gap_m=.0035,row_gap_band_m=[.002,.005],
            row_clearance_m=.002,bin_origin_m=[.035,-.0485,.074],bin_size_m=[.09,.097,.03*layers],
            transient_tilt_overhang_m=.0005)
    return value


def plan(cube=False, *, fixture=None):
    if cube:
        fixture = CUBE_FIXTURE if fixture is None else fixture
        rows = fixture.get('row_order', [0, 1, 2])
        width=len(rows)
        pitch=.03+fixture.get('row_gap_m',0.)
        return [dict(id='bar-'+str(i+1), cells=3, cell=[0, rows[i % width], i//width], size=[.09, .03, .03],
                     mass=.06, arm=i%2 if width==1 else 0 if rows[i % width] == 0 else 1,
                     color_rgb=fixture['cargo_colors_rgb'][i % 3],
                     target=[fixture['bin_origin_m'][0]+.045, fixture['bin_origin_m'][1]+.015+rows[i % width]*pitch,
                             fixture['bin_origin_m'][2]+.015+(i//width)*.03])
                for i in range(width*fixture.get('layers', 1))]
    return [dict(id='bar-'+str(i+1), cells=3, cell=[0, 0, i], size=[.09, .03, .03],
                 mass=.06, arm=i % 2, target=[.16, 0., .04+i*.03]) for i in range(3)]


def home(arm, cube=False, *, fixture=None):
    if cube:
        fixture = CUBE_FIXTURE if fixture is None else fixture
        base, yaw = fixture['arm_bases_m'][arm], fixture['arm_base_yaws_rad'][arm]
        lateral = -.12 if arm == 0 else .12
        return [base[0]+.06*math.cos(yaw)-lateral*math.sin(yaw),
                base[1]+.06*math.sin(yaw)+lateral*math.cos(yaw), base[2]+.13]
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


def rotation_matrix(quaternion):
    w, x, y, z = quaternion
    return ((1-2*(y*y+z*z), 2*(x*y-z*w), 2*(x*z+y*w)),
              (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w)),
              (2*(x*z-y*w), 2*(y*z+x*w), 1-2*(x*x+y*y)))


def tcp_from_wrist(position, quaternion):
    matrix = rotation_matrix(quaternion)
    offset = (.09193, -.0016, 0.)
    return [position[i]+sum(matrix[i][j]*offset[j] for j in range(3)) for i in range(3)]


def contact_names(index, cube=False, *, fixture=None):
    names = ['a-left', 'a-right', 'b-left', 'b-right', 'bin', 'conveyor']+[
        item['id'] for i, item in enumerate(plan(cube, fixture=fixture)) if i != index]
    return names+(['table'] if fixture and fixture.get('leveling_protocol') else [])


def norm(values):
    return math.sqrt(sum(v*v for v in values))


def belt_transport_observed(start, end, cube=False, *, fixture=None):
    fixture = (CUBE_FIXTURE if cube else FIXTURE) if fixture is None else fixture
    velocity = fixture.get('belt_velocity_m_s', [0., fixture['belt_speed_m_s'], 0.])
    direction = [v/norm(velocity) for v in velocity]
    delta = [end[k]-start[k] for k in range(3)]
    travel = sum(delta[k]*direction[k] for k in range(3))
    return (.01 < travel < .06
            and norm([delta[k]-travel*direction[k] for k in range(3)]) < .005)


def source_height_observed(position, fixture):
    if not all(math.isfinite(v) for v in position):
        return False
    if 'belt_pitch_rad' not in fixture:
        return .035 <= position[2] <= .05
    pitch, size, center = fixture['belt_pitch_rad'],fixture['belt_size_m'],fixture['belt_center_m']
    x = center[0]-math.sin(pitch)*size[2]/2
    z = center[2]+math.cos(pitch)*size[2]/2
    expected = z+(position[0]-x)*math.tan(pitch)+.015/math.cos(pitch)
    return abs(position[2]-expected) <= .0015


def explained_contacts(box):
    return norm([box['net_force'][axis]-sum(f[axis] for f in box['forces']) for axis in range(3)]) <= .001


def unsupported_hold(box, arm):
    forces = box['forces']
    return (all(norm(f) > .005 for f in forces[2*arm:2*arm+2])
        and all(norm(f) <= .001 for n, f in enumerate(forces) if n not in (2*arm, 2*arm+1))
        and explained_contacts(box))


def free_lift(box, arm, source_z):
    return box['position'][2] >= source_z+FIXTURE['minimum_lift_m'] and unsupported_hold(box, arm)


def prefix_held(sample, index, fixture):
    """Placed boxes keep position, support and contacts; their speed is gated by prefix_window_observed."""
    return all(stable_box(sample['boxes'][j],j,True,fixture=fixture,speed=False) for j in range(index))


def measured_motion(samples):
    """Each box's velocity is its pose change since the previous sample over the elapsed ticks.
    Isaac's instantaneous cargo velocity is contact-solver chatter here: run b326 reported .18 rad/s while poses
    moved at most 6 um per 0.1 s, and run ce56 kept .014 m/s for 26 s at a fixed pose. samples[0] is the reference."""
    result = samples[:1]
    for prev, sample in zip(samples, samples[1:]):
        dt = (sample['tick']-prev['tick'])*DT
        boxes = []
        for a, b in zip(prev['boxes'], sample['boxes']):
            dot = min(1., abs(sum(x*y for x, y in zip(a['orientation'], b['orientation']))))
            boxes.append(dict(b, velocity=[(y-x)/dt for x, y in zip(a['position'], b['position'])],
                              angular_velocity=[2*math.acos(dot)/dt, 0., 0.]))
        result.append(dict(sample, boxes=boxes))
    return result


def window_observed(window, ok):
    """A reference sample, then twelve consecutive samples (the original 1.1s window) that pass `ok`."""
    try:
        return (len(window) == 13 and all(b['tick']-a['tick'] == 12 for a, b in zip(window, window[1:]))
            and all(ok(s) for s in measured_motion(window)[1:]))
    except (KeyError,TypeError,IndexError):
        return False


def prefix_window_observed(window, index, fixture, before_tick):
    """The prior stack holds the original stable window before the next release."""
    if not index:
        return window == []
    return (bool(window) and window[-1].get('tick', before_tick+1) <= before_tick
        and window_observed(window, lambda s: all(stable_box(s['boxes'][j],j,True,fixture=fixture) for j in range(index))))


def row_gaps(sample, fixture, placed=None):
    """Measured Y gap between each placed outer row and its center row on the same level."""
    items = plan(True,fixture=fixture)[:placed]
    centers = {item['cell'][2]: j for j, item in enumerate(items) if item['cell'][1] == fixture.get('center_row',1)}
    gaps = []
    for j, item in enumerate(items):
        c = centers.get(item['cell'][2])
        if c is None or j == c:
            continue
        direction = item['cell'][1]-fixture.get('center_row',1)
        outer, center = sample['boxes'][j], sample['boxes'][c]
        gaps.append(direction*(outer['position'][1]-center['position'][1])
            - half_extent(outer,item['size'],1) - half_extent(center,items[c]['size'],1))
    return gaps


def half_extent(box, size, axis):
    row = rotation_matrix(box['orientation'])[axis]
    return sum(abs(row[k])*size[k]/2 for k in range(3))


def leveling_release_target(index, sample, fixture, commanded_tcp=None):
    arm = plan(True,fixture=fixture)[index]['arm']
    box = sample['boxes'][index]
    if not unsupported_hold(box,arm):
        raise ValueError('Leveling carry is not an unsupported bilateral hold')
    if not prefix_held(sample,index,fixture):
        raise ValueError('Previous pallet prefix moved before leveling release')
    center = fixture['leveling_center_m']
    desired = [*center[:2],center[2]+.015+fixture['release_clearance_m']]
    anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
    return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]


def leveling_box_stable(box,index,fixture):
    size = plan(True,fixture=fixture)[index]['size']
    values = [*box['position'],*box['orientation'],*box['velocity'],*box['angular_velocity'],
              *box['net_force'],*(v for force in box['forces'] for v in force)]
    if not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in box['orientation'])-1) > .01:
        return False
    table = contact_names(index,True,fixture=fixture).index('table')
    if (box['forces'][table][2] <= .001 or not explained_contacts(box)
            or any(norm(force) > .001 for j,force in enumerate(box['forces']) if j != table)
            or norm(box['velocity']) > .01 or norm(box['angular_velocity']) > .1
            or rotation_matrix(box['orientation'])[2][2] < math.cos(fixture['leveling_flat_tolerance_rad'])):
        return False
    center = fixture['leveling_center_m']
    return (abs(box['position'][2]-center[2]-.015) <= .0015
        and all(abs(box['position'][axis]-center[axis])+half_extent(box,size,axis)
                <= fixture['leveling_size_m'][axis]/2 for axis in (0,1)))


def leveling_observed(stage,index,fixture):
    try:
        arm = plan(True,fixture=fixture)[index]['arm']
        settles,lifts,grasps = stage['settle_samples'],stage['lift_samples'],stage['grasp_samples']
        released = stage['release_sample']
        target = leveling_release_target(index,released,fixture)
        if (stage['arm'] != arm or norm([target[k]-released['tcps'][arm][k] for k in range(3)]) > .00005
                or not 10 <= len(settles) <= 30 or settles[-1]['tick']-settles[0]['tick'] < fixture['settle_steps']
                or not 3 <= len(lifts) <= 30 or lifts[-1]['tick']-lifts[0]['tick'] < 24 or len(grasps) != 2
                or not released['tick'] < stage['opened_sample']['tick'] <= settles[0]['tick']
                or not settles[-1]['tick'] <= grasps[0]['tick'] < grasps[1]['tick'] < lifts[0]['tick']
                or abs(stage['source_center_z']-settles[-1]['boxes'][index]['position'][2]) > .0015):
            return False
        for sample in settles:
            if (not leveling_box_stable(sample['boxes'][index],index,fixture)
                    or any(norm([tcp[k]-sample['boxes'][index]['position'][k] for k in range(3)]) < .04
                           for tcp in sample['tcps'])):
                return False
        return (all(free_lift(sample['boxes'][index],arm,stage['source_center_z']) for sample in lifts)
            and prefix_window_observed(stage['prefix_window'],index,fixture,released['tick'])
            and all(prefix_held(sample,index,fixture) for sample in [*settles,*lifts]))
    except (KeyError,TypeError,IndexError,ValueError):
        return False


def leveling_sequence_observed(layer,index,fixture):
    stage = layer.get('leveling')
    if not leveling_observed(stage,index,fixture):
        return False
    try:
        if not layer['lift_samples'][-1]['tick'] < stage['release_sample']['tick']:
            return False
        if 'release_sample' in layer and not stage['lift_samples'][-1]['tick'] < layer['release_sample']['tick']:
            return False
        if 'opened_sample' in layer and not layer['release_sample']['tick'] < layer['opened_sample']['tick']:
            return False
        return (not layer['settle_samples']
            or layer['opened_sample']['tick'] <= layer['settle_samples'][0]['tick'])
    except (KeyError,TypeError,IndexError):
        return False


def pad_sweep_bottom_relative_tcp(quaternion):
    from run_omx_backend import PAD_HALF_LENGTH, PAD_RADIUS, PAD_CONTACT_OFFSET_M, jaw_contact_point
    if (len(quaternion) != 4 or not all(math.isfinite(v) for v in quaternion)
            or abs(sum(v*v for v in quaternion)-1) > .01):
        raise ValueError('A measured wrist quaternion is required')
    root = ET.parse(ROOT/'learning/envs/isaac/assets/open_manipulator_description/urdf/omx_f/omx_f.urdf').getroot()
    tcp = [float(v) for v in root.find("joint[@name='end_effector_joint']/origin").get('xyz').split()]
    row = rotation_matrix(quaternion)[2]
    x, y = jaw_contact_point()
    radius = math.hypot(x, y+PAD_RADIUS)
    sweep = math.hypot(row[0], row[1])*radius
    vertical = PAD_HALF_LENGTH*abs(row[2])+PAD_RADIUS+PAD_CONTACT_OFFSET_M
    bottoms = []
    for name in ('gripper_joint_1', 'gripper_joint_2'):
        joint = root.find(f"joint[@name='{name}']")
        if (joint.find('axis').get('xyz') != '0 0 1' or joint.find('origin').get('rpy') != '0 0 0'
                or joint.find('parent').get('link') != 'link5'):
            raise ValueError('Calibrated swept finger geometry changed')
        pivot = [float(v) for v in joint.find('origin').get('xyz').split()]
        bottoms.append(sum(row[k]*(pivot[k]-tcp[k]) for k in range(3))-sweep-vertical)
    return min(bottoms)


def center_neighbor(index, sample, fixture):
    items = plan(True, fixture=fixture)
    level = items[index]['cell'][2]
    peers = [(sample['boxes'][j], item['size']) for j, item in enumerate(items[:index])
             if item['cell'][2] == level and item['cell'][1] == 1]
    if len(peers) != 1:
        raise ValueError('Outer placement requires its settled center row')
    body, size = peers[0]
    direction = items[index]['cell'][1]-1
    face = body['position'][1]+direction*half_extent(body, size, 1)
    return direction, face, body['position'][2]+half_extent(body, size, 2)


class PackingFootprintUnavailable(ValueError):
    """The measured held orientation cannot fit the original target envelope."""


def release_footprint_fits(box,size,y,fixture):
    extent=half_extent(box,size,1)
    overhang=fixture.get('transient_tilt_overhang_m',0.)
    flat=extent
    if overhang:
        w,x,qy,z=box['orientation']
        yaw=math.atan2(2*(w*z+x*qy),1-2*(qy*qy+z*z))
        flat=(abs(math.sin(yaw))*size[0]+abs(math.cos(yaw))*size[1])/2
    low=fixture['bin_origin_m'][1]-.001
    high=fixture['bin_origin_m'][1]+fixture['bin_size_m'][1]+.001
    return (y-flat>=low and y+flat<=high
        and y-extent>=low-overhang and y+extent<=high+overhang)


def packed_release_position(index, sample, fixture):
    item = plan(True, fixture=fixture)[index]
    box = sample['boxes'][index]
    desired = item['target'][:]
    desired[2] += fixture['release_clearance_m']
    if item['cell'][1] == fixture.get('center_row',1):
        return desired
    direction, face, top = center_neighbor(index, sample, fixture)
    extent = half_extent(box, item['size'], 1)
    edge = face+direction*(extent+fixture['row_clearance_m'])
    desired[1] = min(desired[1], edge) if direction < 0 else max(desired[1], edge)
    if not release_footprint_fits(box,item['size'],desired[1],fixture):
        raise PackingFootprintUnavailable('Outer held footprint cannot fit the original envelope')
    clearance = fixture['neighbor_vertical_clearance_m']
    arm = item['arm']
    pad_offset = sample['tcps'][arm][2]-box['position'][2]+pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][arm])
    # Measured lateral separation excludes body overlap; only swept fingers may need a higher release.
    desired[2] = max(desired[2], top+clearance-pad_offset)
    return desired


def cube_release_target(index, sample, source_z, commanded_tcp=None, *, fixture=None):
    fixture = CUBE_FIXTURE if fixture is None else fixture
    items = plan(True, fixture=fixture)
    item = items[index]
    box, arm = sample['boxes'][index], item['arm']
    # Lift height was proved during carry; lowering for placement still requires an unsupported bilateral hold.
    if not unsupported_hold(box, arm):
        raise ValueError('cube carry lost bilateral free lift before release')
    if fixture.get('packing_strategy'):
        desired = packed_release_position(index, sample, fixture)
        anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
        return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]
    desired = item['target'][:]
    desired[2] += fixture['release_clearance_m']
    if item['cell'][1] == 0:
        # Measured positive opening drift accumulates across tightly packed rows; center the released footprint.
        desired[1] += fixture['first_row_release_bias_m']
    if index % 3:
        def half_width(body):
            w, x, y, z = body['orientation']
            row = (2*(x*y+z*w), 1-2*(x*x+z*z), 2*(y*z-x*w))
            return sum(abs(row[k])*item['size'][k]/2 for k in range(3))
        neighbor = sample['boxes'][index-1]
        separation = half_width(neighbor)+half_width(box)+fixture['row_clearance_m']
        if items[index-1]['cell'][1] < item['cell'][1]:
            desired[1] = max(desired[1], neighbor['position'][1]+separation)
        else:
            desired[1] = min(desired[1], neighbor['position'][1]-separation)
    anchor = sample['tcps'][arm] if commanded_tcp is None else commanded_tcp
    return [anchor[k]+desired[k]-box['position'][k] for k in range(3)]


def cube_release_ready(index, sample, source_z, *, fixture=None):
    command = cube_release_target(index, sample, source_z, fixture=fixture)
    items = plan(True, fixture=fixture)
    tcp = sample['tcps'][items[index]['arm']]
    error = [command[k]-tcp[k] for k in range(3)]
    if fixture and fixture.get('packing_strategy'):
        clear = True
        if items[index]['cell'][1] != fixture.get('center_row',1):
            direction, face, top = center_neighbor(index, sample, fixture)
            box = sample['boxes'][index]
            y_extent = half_extent(box, items[index]['size'], 1)
            margin = fixture['row_clearance_m']-.000001
            vertical = fixture['neighbor_vertical_clearance_m']-.000001
            clear = (direction*(box['position'][1]-face)-y_extent >= margin
                and release_footprint_fits(box,items[index]['size'],box['position'][1],fixture)
                and tcp[2]+pad_sweep_bottom_relative_tcp(sample['wrist_orientations'][items[index]['arm']]) >= top+vertical)
        # Estimate-only control converges to its estimate, not the true pose: estimate cases accept the final
        # position tolerance here; clearance, footprint and prior-stack checks stay on the measured pose.
        return norm(error) <= fixture.get('release_convergence_m', .00005) and clear and prefix_held(sample, index, fixture)
    direction = 1 if index % 3 == 0 or items[index-1]['cell'][1] < items[index]['cell'][1] else -1
    return (norm(error) <= .00005 and (index % 3 == 0 or direction*error[1] <= .000001)
            and all(stable_box(sample['boxes'][j], j, True, fixture=fixture) for j in range(index)))


def stable_box(box, index, cube=False, *, fixture=None, speed=True):
    items = plan(cube, fixture=fixture)
    fixture = (CUBE_FIXTURE if cube else FIXTURE) if fixture is None else fixture
    item = items[index]
    p, q, forces = box['position'], box['orientation'], box['forces']
    values = [*p, *q, *box['velocity'], *box['angular_velocity'], *(v for row in forces for v in row)]
    if not all(math.isfinite(v) for v in values) or abs(sum(v*v for v in q)-1) > .01:
        return False
    if (any(abs(p[i]-item['target'][i]) > .0015 for i in range(3))
            or speed and (norm(box['velocity']) > .01 or norm(box['angular_velocity']) > .1)
            or any(norm(f) > .001 for f in forces[:4]) or not explained_contacts(box)):
        return False
    width = len(fixture.get('row_order',[0,1,2])) if cube else 1
    below = 'bin' if index < width else items[index-width]['id']
    if forces[contact_names(index, cube, fixture=fixture).index(below)][2] <= .001:
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


def judge(trial, cube=False, *, fixture=None):
    failures = []
    layers = trial.get('layers', [])
    if len(layers) != len(plan(cube, fixture=fixture)):
        return dict(task_success=False, failures=['first_layer_not_completed' if cube else 'three_layers_not_completed'])
    for i, layer in enumerate(layers):
        if fixture and fixture.get('leveling_protocol') and not leveling_sequence_observed(layer,i,fixture):
            failures.append(f'layer_{i+1}:leveling_or_regrasp_not_observed')
        if layer.get('item') != i or layer.get('arm') != plan(cube, fixture=fixture)[i]['arm']:
            failures.append(f'layer_{i+1}:wrong_item_or_arm')
        lifts, settles = layer.get('lift_samples', []), layer.get('settle_samples', [])
        if len(lifts) < 3 or lifts[-1]['tick']-lifts[0]['tick'] < 24:
            failures.append(f'layer_{i+1}:lift_not_observed')
        else:
            for sample in lifts:
                box = sample['boxes'][i]
                forces = box['forces']
                arm = plan(cube, fixture=fixture)[i]['arm']
                if not free_lift(box, arm, layer['source_center_z']):
                    failures.append(f'layer_{i+1}:no_bilateral_free_lift')
                    break
        if len(settles) < 10 or settles[-1]['tick']-settles[0]['tick'] < FIXTURE['settle_steps']:
            failures.append(f'layer_{i+1}:settle_not_observed')
        else:
            # Packed releases record a reference sample first; see measured_motion.
            packed = bool(fixture and fixture.get('packing_strategy'))
            for sample in (measured_motion(settles)[1:] if packed else settles):
                if (not all(stable_box(sample['boxes'][j], j, cube, fixture=fixture) for j in range(i+1))
                        or any(norm([tcp[k]-sample['boxes'][j]['position'][k] for k in range(3)]) < .04
                               for tcp in sample['tcps'] for j in range(i+1))):
                    failures.append(f'layer_{i+1}:release_support_or_retreat_failed')
                    break
        if (fixture and fixture.get('leveling_protocol') and fixture.get('packing_strategy')
                and not prefix_window_observed(layer.get('prefix_window'),i,fixture,
                                               layer.get('release_sample',{}).get('tick',-1))):
            failures.append(f'layer_{i+1}:prior_stack_window_not_observed')
    band = fixture.get('row_gap_band_m') if fixture else None
    if band and not failures:
        final = layers[-1]['settle_samples'][-1]
        if not all(band[0]-1e-6 <= gap <= band[1]+1e-6 for gap in row_gaps(final, fixture)):
            failures.append('row_gap_outside_band')
    return dict(task_success=not failures, failures=failures)
