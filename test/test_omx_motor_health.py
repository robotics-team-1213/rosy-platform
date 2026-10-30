"""Per-motor monitoring shares the native owner's bus and never writes registers."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).parents[1] / 'deploy/robot/omx'


@pytest.fixture(autouse=True)
def isolate_snapshot_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def monitor_type():
    spec = importlib.util.spec_from_file_location('motor_health_test', DIRECTORY / 'motor_health.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.MotorHealth


NAMES = ('shoulder_pan', 'shoulder_lift', 'elbow_flex', 'wrist_flex', 'wrist_roll')


class Bus:
    def __init__(self, port='/dev/serial/by-id/confirmed-a'):
        self.port = port
        self.motors = {name: SimpleNamespace(id=11 + i) for i, name in enumerate(NAMES)}
        self.values = {name: {'Torque_Enable': 0, 'Temperature_Limit': 70, 'Min_Voltage_Limit': 60,
                              'Max_Voltage_Limit': 140, 'Present_Temperature': 25,
                              'Present_Input_Voltage': 120, 'Hardware_Error_Status': 0} for name in NAMES}
        self.reads = []

    def read(self, register, name, *, normalize=False):
        assert normalize is False
        self.reads.append((register, name))
        return self.values[name][register]

    def write(self, *args):
        pytest.fail('monitor must never write registers')


def motion(label='arm_a', port='/dev/serial/by-id/confirmed-a'):
    return SimpleNamespace(label=label, follower=Bus(port), active=NAMES, clock=lambda: 10.0,
                           pwm_limits=dict.fromkeys(NAMES, 400), command=dict.fromkeys(NAMES, 2028.9))


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_id12_high_pwm_warns_even_when_tracking_error_is_zero(tmp_path, capsys):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path)
    arm = motion()
    monitor.admit(arm)
    monitor.sample(arm, dict.fromkeys(NAMES, 2028), {**dict.fromkeys(NAMES, 0), 'shoulder_lift': -391}, 10.0)
    sample = rows(path)[-1]
    joint = sample['motors'][1]
    assert sample['event'] == 'sample' and sample['arm'] == 'arm_a'
    assert joint['id'] == 12 and joint['joint'] == 'shoulder_lift'
    assert joint['command_raw'] == joint['present_raw'] == 2028 and joint['error_deg'] == 0
    assert joint['pwm'] == -391 and joint['pwm_limit'] == 400 and joint['pwm_utilization'] == 391 / 400
    assert joint['temperature_c'] == 25 and joint['voltage_raw'] == 120 and joint['voltage_v'] == 12
    assert joint['usb_port'] == arm.follower.port and 'high_pwm' in joint['warnings']
    assert '12' in capsys.readouterr().out


def test_native_snapshot_preserves_group_and_measured_fault_torque_fields(tmp_path):
    monitor = monitor_type()(tmp_path / 'health.jsonl')
    arm = motion()
    monitor.admit(arm)
    for value in arm.follower.values.values():
        value['Torque_Enable'] = 1
    monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.)
    snapshot = json.loads(monitor.state_path.read_text())
    assert all(m['group'] == arm.label for m in snapshot['motors'])
    assert all(m['hardware_error'] == 0 and m['torque_enabled'] is True for m in snapshot['motors'])


@pytest.mark.parametrize('cap,admitted', [(600, True), (601, False)])
def test_a_reach_cap_the_guard_admitted_is_admitted_by_the_monitor(tmp_path, cap, admitted):
    monitor, arm = monitor_type()(tmp_path / 'health.jsonl'), motion()
    arm.pwm_limits['shoulder_lift'] = cap
    if admitted:
        monitor.admit(arm)
    else:
        with pytest.raises(ValueError, match='configured limits'):
            monitor.admit(arm)


@pytest.mark.parametrize('register,value,stops', [('Present_Temperature', 65, False),
    ('Present_Temperature', 70, True), ('Present_Input_Voltage', 59, True),
    ('Present_Input_Voltage', 141, True), ('Present_Input_Voltage', 60, False),
    ('Present_Input_Voltage', 140, False)])
def test_actual_configured_thermal_voltage_limits(tmp_path, register, value, stops):
    monitor = monitor_type()(tmp_path / 'health.jsonl')
    arm = motion()
    monitor.admit(arm)
    arm.follower.values['shoulder_lift'][register] = value
    if stops:
        with pytest.raises(ValueError, match='temperature|voltage'):
            monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
    else:
        monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
        if register == 'Present_Temperature':
            assert 'near_temperature_limit' in rows(monitor.path)[-1]['motors'][1]['warnings']


@pytest.mark.parametrize('change', [{'Torque_Enable': 1}, {'Temperature_Limit': float('nan')},
                                   {'Min_Voltage_Limit': 150}, {'Present_Temperature': 70}])
def test_admission_is_off_only_and_rejects_bad_or_unsafe_limits(tmp_path, change):
    monitor = monitor_type()(tmp_path / 'health.jsonl')
    arm = motion()
    arm.follower.values['shoulder_lift'].update(change)
    with pytest.raises(ValueError):
        monitor.admit(arm)


@pytest.mark.parametrize('failure', ['missing', 'nan', 'io', 'stale', 'log'])
def test_missing_bad_stale_or_unrecordable_telemetry_fails_closed(tmp_path, monkeypatch, failure):
    monitor = monitor_type()(tmp_path / 'health.jsonl')
    arm = motion()
    monitor.admit(arm)
    current, pwm = dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0)
    if failure == 'missing':
        pwm.pop('shoulder_lift')
    elif failure == 'nan':
        arm.follower.values['shoulder_lift']['Present_Temperature'] = float('nan')
    elif failure == 'io':
        arm.follower.read = lambda *args, **kwargs: (_ for _ in ()).throw(OSError('read failed'))
    elif failure == 'log':
        monkeypatch.setattr(Path, 'open', lambda *args, **kwargs: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises((ValueError, OSError)):
        monitor.sample(arm, current, pwm, 9.0 if failure == 'stale' else 10.0)


def test_shared_monitor_keeps_arm_identity_and_fault_uses_last_sample_without_reads(tmp_path):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path)
    arms = [motion(), motion('arm_b', '/dev/serial/by-id/confirmed-b')]
    for arm in arms:
        monitor.admit(arm)
        monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
        arm.follower.read = lambda *args: pytest.fail('fault must not read fresh telemetry')
        arm.clock = lambda: 10.4
        monitor.fault(arm, ValueError('hardware alert'))
    faults = [row for row in rows(path) if row['event'] == 'fault']
    assert [row['arm'] for row in faults] == ['arm_a', 'arm_b']
    assert all(row['sample_time'] == 10.0 and row['sample_age_s'] == pytest.approx(.4) for row in faults)
    assert all(row['fault'] == 'hardware alert' and row['telemetry'] == 'last_known' for row in faults)
    assert faults[0]['motors'][0]['usb_port'] != faults[1]['motors'][0]['usb_port']


def test_record_budget_stops_without_overwriting_history(tmp_path):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path, max_records=2)
    arm = motion()
    monitor.admit(arm)
    monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match='budget'):
        monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
    assert path.read_bytes() == before and len(rows(path)) == 2


def test_env_or_unique_default_path_never_truncates_existing_log(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv('ROSY_OMX_MONITOR_LOG', raising=False)
    first, second = monitor_type()(), monitor_type()()
    assert first.path != second.path and first.path.name.startswith('motor-health-')
    env_path = tmp_path / 'requested.jsonl'
    monkeypatch.setenv('ROSY_OMX_MONITOR_LOG', str(env_path))
    assert monitor_type()().path == env_path
    with pytest.raises(FileExistsError):
        monitor_type()()


@pytest.mark.parametrize('full', [False, True])
def test_body_only_monitors_five_and_full_mode_also_monitors_gripper(tmp_path, full):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path)
    arm = motion()
    arm.follower.motors['gripper'] = SimpleNamespace(id=16)
    arm.follower.values['gripper'] = {**arm.follower.values['wrist_roll'], 'PWM_Limit': 300, 'Present_PWM': -280}
    if full:
        arm.active = (*NAMES, 'gripper')
        arm.command['gripper'] = 2028
    monitor.admit(arm)
    monitor.sample(arm, dict.fromkeys((*NAMES, 'gripper'), 2028), dict.fromkeys(NAMES, 0), 10.0)
    sample = rows(path)[-1]
    assert len(sample['motors']) == (6 if full else 5)
    if full:
        gripper = sample['motors'][-1]
        assert gripper['id'] == 16 and gripper['pwm_limit'] == 300 and gripper['pwm'] == -280
        assert 'high_pwm' in gripper['warnings']
    else:
        assert all(name != 'gripper' for _, name in arm.follower.reads)



def test_hard_limit_raises_before_any_logging_and_fault_persists_cached_sample(tmp_path):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path)
    arm = motion()
    monitor.admit(arm)
    arm.follower.values['shoulder_lift']['Present_Temperature'] = 70
    original_emit = monitor.emit
    monitor.emit = lambda row: pytest.fail('known hard limit must stop before log I/O')
    with pytest.raises(ValueError, match='temperature') as error:
        monitor.sample(arm, dict.fromkeys(NAMES, 2028), dict.fromkeys(NAMES, 0), 10.0)
    monitor.emit = original_emit
    arm.follower.read = lambda *args, **kwargs: pytest.fail('fault must use cached sample')
    monitor.fault(arm, error.value)
    fault = rows(path)[-1]
    assert fault['event'] == 'fault' and fault['motors'][1]['temperature_c'] == 70
    assert fault['recorded_at_utc'].endswith('+00:00')
    assert fault['active_motor_ids']['shoulder_lift'] == 12


def test_startup_fault_identifies_active_motors_without_admitted_sample_or_reads(tmp_path):
    path = tmp_path / 'health.jsonl'
    monitor = monitor_type()(path)
    arm = motion()
    arm.follower.read = lambda *args, **kwargs: pytest.fail('fault must not read serial')
    monitor.fault(arm, OSError('shoulder_lift read failed'))
    fault = rows(path)[-1]
    assert fault['active_motor_ids'] == {name: 11 + i for i, name in enumerate(NAMES)}
    assert fault['sample_time'] is None and fault['motors'] == []
    assert fault['recorded_at_utc'].endswith('+00:00')


@pytest.mark.parametrize('error,reason', [
    (OSError('temperature read /dev/serial/private failed'), 'control failure'),
    (OSError('voltage read unavailable'), 'control failure'),
    (ValueError('missing motor health temperature'), 'control failure'),
    (ValueError('wrist_flex: temperature 70 >= configured limit 70'), 'temperature limit'),
    (ValueError('wrist_flex: voltage 59 outside configured limits 60..140 (0.1 V)'), 'voltage limit'),
])
def test_public_fault_reason_distinguishes_read_failure_from_confirmed_limit(tmp_path, error, reason):
    monitor = monitor_type()(tmp_path / 'health.jsonl')
    monitor.fault(motion(), error)
    snapshot = json.loads(monitor.state_path.read_text())
    assert snapshot['stop_reasons'] == [reason]
    assert '/dev/' not in json.dumps(snapshot)
