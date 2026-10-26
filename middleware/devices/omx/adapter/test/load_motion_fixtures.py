"""Synthetic load domains; no value here is an accepted device setting."""
from copy import deepcopy


def characteristics():
    names = ['joint2', 'joint3']
    return {
        'schema': 'rosy.omx-motion-characteristics.v1', 'revision': 'fixture-v1', 'status': 'measured',
        'binding': {'device_id': 'fixture-arm', 'owner_id': 'fixture-owner', 'motor_group': 'fixture-owner',
                    'hardware_profile_revision': 'hardware-fixture', 'calibration_revision': 'cal-fixture',
                    'robot_model_sha256': 'a' * 64, 'installation_revision': 'mount-fixture',
                    'tool_revision': 'tool-fixture', 'assist_mechanism_revision': 'none'},
        'measured_at': '2026-10-27', 'evidence_ref': 'fixture-only-not-acceptance',
        'joints': {n: {'motor_id': i + 12, 'motor_model': 'fixture-only',
                       'raw_zero': 2048., 'rad_per_raw': .001,
                       'position_rad': [-1., 1.], 'velocity_rad_s': 2., 'acceleration_rad_s2': 10.}
                   for i, n in enumerate(names)},
        'monitor': {'max_age_s': .2, 'max_gap_s': .1, 'tracking_duration_s': .2,
                    'oscillation_window_s': 1., 'oscillation_cycles': 2,
                    'joints': {n: {'error_rad': .05, 'clear_error_rad': .02,
                                   'oscillation_amplitude_rad': .04} for n in names}},
        'envelopes': [{
            'id': 'fixture-domain', 'evidence_ref': 'fixture-domain-not-acceptance',
            'position_rad': {n: [-.6, .6] for n in names},
            'max_velocity_rad_s': {n: 1. for n in names},
            'max_acceleration_rad_s2': {n: 5. for n in names},
            'payload_mass_kg': [0., .1], 'payload_com_min_m': [-.01, -.01, -.01],
            'payload_com_max_m': [.01, .01, .01], 'temperature_c': [10., 45.], 'voltage_v': [11., 13.],
            'max_motion_s': 5., 'max_hold_s': 2., 'max_cycles': 3, 'min_cycle_interval_s': 1.,
            'measured_tracking_error_rad': .02,
        }],
    }


def request(profile=None):
    p = profile or characteristics()
    names = list(p['joints'])
    return {
        'schema': 'rosy.omx-load-request.v1', 'context': deepcopy(p['binding']),
        'task_id': 'fixture-task', 'scene_revision': 'fixture-scene',
        'source_sequence': 7, 'source_age_s': .01, 'start_at_rest': True,
        'start_positions_rad': {n: 0. for n in names},
        'goal_positions_rad': {n: .2 for n in names}, 'goal_tolerance_rad': .001,
        'payload_mass_kg': [.04, .05], 'payload_com_min_m': [0., 0., 0.],
        'payload_com_max_m': [.001, .001, .001],
        'temperatures_c': {n: 25. for n in names}, 'voltages_v': {n: 12. for n in names},
        'hold_s': .5, 'cycle_count': 1, 'cycle_interval_s': 1.,
        'candidates': [{'id': 'direct', 'joint_names': names,
                        'points': [{'time_from_start_s': 2., 'positions': [.2] * len(names),
                                    'velocities': [0.] * len(names), 'accelerations': [0.] * len(names)}]}],
    }


def health(profile=None, *, age=0., error_rad=0., fault=False, session=None):
    from core_common.protocol.motor_health import MotorHealthResponse, MotorHealthSample
    p = profile or characteristics()
    return MotorHealthResponse(
        evidence='fresh', status='active', owner_id=p['binding']['owner_id'],
        session_id=session or '00000000-0000-4000-8000-000000000001', sample_age_s=age,
        motors=[MotorHealthSample(
            group=p['binding']['owner_id'], joint=n, id=j['motor_id'], sample_age_s=age,
            command_raw=j['raw_zero'], present_raw=j['raw_zero'] + error_rad / j['rad_per_raw'],
            error_deg=0., pwm=10., pwm_limit=100., pwm_utilization=.1,
            temperature_c=25., temperature_limit_c=70., voltage_v=12., min_voltage_v=10., max_voltage_v=14.,
            hardware_error=32 if fault else 0, fault=fault, torque_enabled=True)
                for n, j in p['joints'].items()])
