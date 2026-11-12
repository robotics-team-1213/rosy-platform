"""Confluence board layout, CAD container fixtures, plan/home geometry, and URDF/contact primitives."""
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import ship_plate
from pad_sweep import pad_sweep_bottom_relative_tcp, rotation_matrix  # noqa: F401
from stacking_fixture import DT, PROFILE  # noqa: F401
from release_cases import EVALUATION_CASES, FIXTURE_OVERRIDES, RL_RESIDUALS

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


def container_fixture(*, layers, case):
    if case in FIXTURE_OVERRIDES and case not in EVALUATION_CASES:  # nominal IK geometry variants
        value = container_fixture(layers=layers, case='nominal')
        value.update(FIXTURE_OVERRIDES[case], revision=value['revision']+'-'+case, case=case)
        gap = value['row_gap_m']  # the envelope grows by the two row gaps, as in the D-929 branch below
        value.update(bin_origin_m=[.035, -.045-gap, .074], bin_size_m=[.09, .09+2*gap, .03*layers])
        if value.get('belt_drop_m'):  # surveyed belt below the CAD face: the belt and its feed points move down together
            for key in ('belt_center_m', 'belt_stop_m', 'pickup_center_m', 'infeed_start_m'):
                value[key] = [*value[key][:2], value[key][2]-value['belt_drop_m']]
        return ship_plate.place(value) if 'ship_plate' in value else value
    if case in EVALUATION_CASES:
        value = container_fixture(layers=layers, case='nominal')
        value.update(revision=value['revision']+'-'+case, case=case, release_estimate_noise_m=[.002, .005],
                     release_convergence_m=.0015)
        value.update(FIXTURE_OVERRIDES.get(case, {}))
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
    # D-947 3: the real top and side cameras, surveyed by stud-grid PnP (docs/validation/omx-cell-survey-2026-11-03); up is the
    # image -y axis from the PnP rotation, so the camera roll is kept (side 1.5 deg).
    value['real_cameras'] = dict(
        top=dict(eye=[-.0411,.0374,.6652], focus=[.0722,.0401,.1783], up=[.974,.0071,.2266], f_px=615., width=640, height=480),  # D435 nominal f
        side=dict(eye=[-.5078,.0019,.1471], focus=[-.0082,-.0166,.1445], up=[.0061,.0257,.9997], f_px=950., width=640, height=480))  # f by reprojection
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
                     mass=(fixture.get('cargo_mass_kg') or [0, 0, .06])[2], arm=i%2 if width==1 else 0 if rows[i % width] == 0 else 1,
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


def tcp_from_wrist(position, quaternion, offset=(.09193, -.0016, 0.)):
    matrix = rotation_matrix(quaternion)
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


def half_extent(box, size, axis):
    row = rotation_matrix(box['orientation'])[axis]
    return sum(abs(row[k])*size[k]/2 for k in range(3))
