"""Two OMX pairs share one native recording and fail together, without hardware."""
import importlib.util
from abc import ABC, abstractmethod
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

DIRECTORY = Path(__file__).parents[1] / "deploy/robot/omx"
spec = importlib.util.spec_from_file_location("guard_fakes", Path(__file__).with_name("test_omx_guarded_native.py"))
fakes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fakes)


@pytest.fixture
def module(monkeypatch):
    sys.path.insert(0, str(DIRECTORY))
    try:
        spec = importlib.util.spec_from_file_location("omx_bimanual_test", DIRECTORY / "bimanual_native.py")
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        monkeypatch.setattr(value, "MotorHealth", lambda: None)
        return value
    finally:
        sys.path.remove(str(DIRECTORY))


def pairs(module):
    clock = [10.0]
    motions = {name: module.NativeJointMotion(fakes.Bus(), fakes.Bus(leader=True), clock=lambda: clock[0])
               for name in ("arm_a", "arm_b")}
    action = {name + "." + key: value for name, motion in motions.items()
              for key, value in fakes.action(motion.leader).items()}
    return module.BimanualMotion(motions), motions, action, clock


def test_both_are_seeded_before_either_enables_and_actual_twelve_actions_return(module):
    together, motions, action, _ = pairs(module)
    for motion in motions.values():
        enable = motion.follower.enable_torque
        def checked_enable(enable=enable):
            assert all(m.follower.goals == m.follower.raw for m in motions.values())
            enable()
        motion.follower.enable_torque = checked_enable
    sent = together.send(action)
    assert set(sent) == set(action) and len(sent) == 12
    assert all(any(m.follower.torque.values()) for m in motions.values())


@pytest.mark.parametrize("failure", ["initial_gap", "ongoing_jump", "write", "missing"])
def test_either_arm_failure_stops_every_follower_and_leader(module, failure):
    together, motions, action, clock = pairs(module)
    if failure in ("ongoing_jump", "write"):
        together.send(action)
        clock[0] += 0.1
    if failure in ("initial_gap", "ongoing_jump"):
        motions["arm_b"].leader.raw["wrist_roll"] += 1200
    elif failure == "write":
        motions["arm_b"].follower.fail_write = True
    else:
        action.pop("arm_b.gripper.pos")
    with pytest.raises((ValueError, OSError)):
        together.send(action)
    for motion in motions.values():
        assert not any(motion.follower.torque.values()) and not any(motion.leader.torque.values())
    if failure in ("initial_gap", "missing"):
        assert all(("on",) not in m.follower.events for m in motions.values())


def test_pair_offsets_and_rate_limits_stay_independent(module):
    together, motions, action, clock = pairs(module)
    motions["arm_a"].leader.raw["wrist_roll"] += 4096
    motions["arm_b"].leader.raw["wrist_roll"] -= 4096
    together.send(action)
    motions["arm_a"].leader.raw["wrist_roll"] += 100
    motions["arm_b"].leader.raw["wrist_roll"] -= 100
    clock[0] += 0.1
    sent = together.send(action)
    assert sent["arm_a.wrist_roll.pos"] > action["arm_a.wrist_roll.pos"]
    assert sent["arm_b.wrist_roll.pos"] < action["arm_b.wrist_roll.pos"]
    assert abs(motions["arm_a"].follower.goals["wrist_roll"] - 2028) <= 2
    assert abs(motions["arm_b"].follower.goals["wrist_roll"] - 2028) <= 2


def test_one_arm_sustained_effort_stops_both_followers_and_passive_leaders(module):
    clock = [10.0]
    motions = {name: module.NativeJointMotion(fakes.Bus(), fakes.Bus(leader=True),
                                         clock=lambda: clock[0]) for name in ('arm_a', 'arm_b')}
    together = module.BimanualMotion(motions)
    action = {name + '.' + key: value for name, motion in motions.items()
              for key, value in fakes.action(motion.leader).items()}
    together.send(action)
    fakes.effort_read(motions['arm_b'].follower)
    with pytest.raises(ValueError, match='overload risk'):
        for _ in range(40):
            clock[0] += 0.05
            motions['arm_b'].follower.raw['shoulder_lift'] = 2003
            together.send(action)
    assert all(not any(bus.torque.values()) for m in motions.values() for bus in (m.follower, m.leader))


@pytest.mark.parametrize('scenario,expected', [
    ('normal', None), ('sustained_load', 'overload risk'),
    ('transient_load', None),
    ('mapping_jump', '100 degrees'),
])
def test_two_arm_sensor_simulation_at_thirty_hz(module, scenario, expected):
    """Synthetic sensor replay, not a model of motor physics or firmware heating."""
    import json
    import math

    clock = [10.0]
    motions = {name: module.NativeJointMotion(fakes.Bus(), fakes.Bus(leader=True),
                                         clock=lambda: clock[0], label=name)
               for name in ('arm_a', 'arm_b')}
    together = module.BimanualMotion(motions)
    load = {'pwm': 0}
    read = motions['arm_a'].follower.read
    def simulated_read(register, motor, **kwargs):
        if register == 'PWM_Limit':
            return 400
        if register == 'Present_PWM':
            return load['pwm'] if motor == 'shoulder_lift' else 0
        return read(register, motor, **kwargs)
    motions['arm_a'].follower.read = simulated_read
    reason, stopped_at = None, None
    for frame in range(241):
        elapsed = frame / 30
        clock[0] = 10.0 + elapsed
        loaded = (scenario == 'sustained_load' and elapsed >= 2
                  or scenario == 'transient_load' and 2 <= elapsed < 2.4)
        load['pwm'] = -391 if loaded else 0  # recorded magnitude 391 / limit 400
        for name, motion in motions.items():
            for joint in motion.active:
                if joint in motion.follower.goals:
                    goal = motion.follower.goals[joint]
                    actual = motion.follower.raw[joint]
                    motion.follower.raw[joint] = round(actual + 0.5 * (goal - actual))
            if name == 'arm_a' and frame:
                if loaded:
                    motion.follower.raw['shoulder_lift'] = motion.follower.goals['shoulder_lift'] - 25
            direction = 1 if name == 'arm_a' else -1
            motion.leader.raw['wrist_roll'] = 2028 + round(direction * 40 * math.sin(max(0, elapsed - 1)))
        if scenario == 'mapping_jump' and elapsed >= 2:
            motions['arm_a'].leader.raw['wrist_roll'] += 1200
        action = {name + '.' + key: value for name, motion in motions.items()
                  for key, value in fakes.action(motion.leader).items()}
        try:
            together.send(action)
        except ValueError as exc:
            reason, stopped_at = str(exc), elapsed
            break
    if expected:
        assert reason is not None and expected in reason
        assert all(not any(bus.torque.values()) for m in motions.values()
                   for bus in (m.follower, m.leader))
        if scenario == 'sustained_load':
            assert 3 <= stopped_at <= 3.3
        else:
            assert stopped_at == 2
    else:
        assert reason is None and all(not m.failed for m in motions.values())
        assert all(all(m.follower.torque.values()) and not any(m.leader.torque.values())
                   for m in motions.values())
    for motion in motions.values():
        for bus in (motion.follower, motion.leader):
            module.torque_off(bus)
    assert all(not any(bus.torque.values()) for m in motions.values()
               for bus in (m.follower, m.leader))
    print('sensor_simulation=' + json.dumps({'scenario': scenario, 'hz': 30,
          'stopped_at_s': stopped_at, 'reason': reason,
          'all_off_after_cleanup': True}))


class Device:
    def __init__(self, leader=False):
        self.bus, self.cameras = fakes.Bus(leader=leader), {}
        self.action_features = {n + ".pos": float for n in fakes.NAMES}
        self.observation_features = self.action_features

    def get_action(self):
        return fakes.action(self.bus)

    def get_observation(self):
        return fakes.action(self.bus)


class Base(ABC):
    def __init__(self, config):
        self.config = config

    @abstractmethod
    def calibrate(self):
        pass

    @abstractmethod
    def configure(self):
        pass


def adapters(module):
    followers = {name: Device() for name in ("arm_a", "arm_b")}
    leaders = {name: Device(leader=True) for name in followers}
    camera = SimpleNamespace(height=480, width=640, is_connected=False, opens=0, reads=0)
    def connect():
        camera.opens += 1
        camera.is_connected = True
    camera.connect = connect
    camera.disconnect = lambda: setattr(camera, "is_connected", False)
    camera.read_latest = lambda: "top_frame"
    Robot, Leader = module.make_adapters(Base, Base, lambda cfg: followers[cfg.name],
                                         lambda cfg: leaders[cfg.name], lambda cfg: {"top": camera})
    cfg = SimpleNamespace(**{name: SimpleNamespace(name=name, type='omx_follower', use_degrees=False, cameras={})
                             for name in followers}, cameras={})
    leader_cfg = SimpleNamespace(**{name: SimpleNamespace(name=name, type='omx_leader') for name in leaders})
    return Robot(cfg), Leader(leader_cfg), followers, leaders, camera


def test_native_adapters_expose_twelve_features_and_open_top_camera_once(module):
    robot, leader, followers, leaders, camera = adapters(module)
    robot.leader = leader
    robot.connect()
    leader.connect()
    assert len(robot.action_features) == len(leader.action_features) == 12
    assert set(robot.observation_features) == {*robot.action_features, "top"}
    observation = robot.get_observation()
    assert observation["top"] == "top_frame" and camera.opens == 1
    sent = robot.send_action(leader.get_action())
    assert set(sent) == set(robot.action_features)
    robot.disconnect()
    leader.disconnect()
    assert not camera.is_connected
    assert all(not d.bus.is_connected for d in (*followers.values(), *leaders.values()))


def test_second_arm_calibration_failure_closes_all_without_enabling(module):
    robot, leader, followers, leaders, camera = adapters(module)
    robot.leader = leader
    followers["arm_b"].bus.is_calibrated = False
    with pytest.raises(ValueError, match="calibration"):
        robot.connect()
    assert all(not d.bus.is_connected for d in followers.values())
    assert all(("on",) not in d.bus.events for d in followers.values())
    assert not camera.is_connected


@pytest.mark.parametrize('mode', ['record', 'teleoperate'])
def test_native_entrypoint_records_actual_twelve_actions_and_cleans_interrupt(module, mode):
    robot, leader, followers, leaders, camera = adapters(module)
    leaders['arm_b'].bus.raw['wrist_roll'] += 100
    native = SimpleNamespace(make_robot_from_config=lambda cfg: None,
                             make_teleoperator_from_config=lambda cfg: None, ACTION='action',
                             build_dataset_frame=lambda features, values, prefix: values)
    def main():
        r = native.make_robot_from_config(robot.config)
        l = native.make_teleoperator_from_config(leader.config)
        for device in ((r, l) if mode == 'record' else (l, r)):
            device.connect()
        desired = l.get_action()
        sent = r.send_action(desired)
        assert len(sent) == 12 and sent != desired
        assert native.build_dataset_frame({}, desired, prefix='action') == sent
        raise KeyboardInterrupt
    native.main = main
    with pytest.raises(KeyboardInterrupt):
        module.run_native(native, type(robot), type(leader))
    assert camera.opens == 1 and not camera.is_connected
    assert all(not any(d.bus.torque.values()) and not d.bus.is_connected
               for d in (*followers.values(), *leaders.values()))


def test_failed_stop_of_one_bus_still_attempts_every_other_bus(module):
    together, motions, action, _ = pairs(module)
    together.send(action)
    def broken_stop(*args, **kwargs):
        raise OSError('unreachable arm_a')
    motions['arm_a'].follower.disable_torque = broken_stop
    action.pop('arm_b.gripper.pos')
    with pytest.raises(RuntimeError, match='torque OFF'):
        together.send(action)
    assert not any(motions['arm_b'].follower.torque.values())
    assert all(not any(m.leader.torque.values()) for m in motions.values())


def test_interarm_preparation_delay_cannot_hide_previous_sample_staleness(module):
    together, motions, action, clock = pairs(module)
    together.send(action)
    motions['arm_b'].last_time = 10.3
    clock[0] = 10.4
    read = motions['arm_b'].leader.sync_read
    def slow_read(*args, **kwargs):
        clock[0] += 0.2
        return read(*args, **kwargs)
    motions['arm_b'].leader.sync_read = slow_read
    before = len([e for e in motions['arm_a'].follower.events if e[0] == 'goal'])
    with pytest.raises(ValueError, match='stale'):
        together.send(action)
    assert len([e for e in motions['arm_a'].follower.events if e[0] == 'goal']) == before
    assert all(not any(m.follower.torque.values()) for m in motions.values())


@pytest.mark.parametrize('mode', ['record', 'teleoperate'])
def test_cli_enters_native_typed_function_without_recursive_argument_discovery(module, monkeypatch, tmp_path, mode):
    import json
    calls = []
    cfg = tmp_path / 'native.json'
    cfg.write_text(json.dumps({'sentinel': 'typed_config'}))
    def native_cli_must_not_run():
        pytest.fail('recursive native argument discovery must not run')
    entry = SimpleNamespace(__wrapped__=lambda config: calls.append(config))
    native = SimpleNamespace(main=native_cli_must_not_run, RecordConfig=dict, TeleoperateConfig=dict,
                             record=entry, teleoperate=entry)
    monkeypatch.setattr(module, 'register_types', lambda: (SimpleNamespace(), SimpleNamespace()))
    monkeypatch.setattr(module.importlib, 'import_module', lambda name: native)
    monkeypatch.setitem(sys.modules, 'draccus', SimpleNamespace(decode=lambda cls, value: value))
    monkeypatch.setattr(module, 'run_native', lambda mod, f, l, invoke=None: invoke())
    monkeypatch.setattr(sys, 'argv', ['bimanual_native.py', mode, '--config_path=' + str(cfg)])
    module.main()
    assert calls == [{'sentinel': 'typed_config'}]


def test_bimanual_fault_monitor_runs_only_after_every_bus_off_and_preserves_cause(module):
    together, motions, action, _ = pairs(module)
    calls = []
    def fault(motion, exc):
        assert all(not any(bus.torque.values()) for m in motions.values() for bus in (m.follower, m.leader))
        calls.append(motion.label)
        raise OSError('log failed')
    for name, motion in motions.items():
        motion.label = name
        motion.monitor = SimpleNamespace(fault=fault)
        for bus in (motion.follower, motion.leader):
            bus.torque = dict.fromkeys(bus.torque, 1)
    action.pop('arm_b.gripper.pos')
    with pytest.raises(ValueError, match='missing'):
        together.send(action)
    assert calls == ['arm_a', 'arm_b']


def test_bimanual_runtime_shares_one_monitor_and_reports_external_interrupt_after_off(module, monkeypatch):
    robot, leader, followers, leaders, camera = adapters(module)
    calls, created = [], []
    class Monitor:
        def __init__(self):
            created.append(self)
        def admit(self, motion):
            calls.append(('admit', motion.label))
        def sample(self, *args):
            pass
        def fault(self, motion, exc):
            assert all(not any(d.bus.torque.values()) for d in (*followers.values(), *leaders.values()))
            assert isinstance(exc, KeyboardInterrupt)
            calls.append(('fault', motion.label))
    monkeypatch.setattr(module, 'MotorHealth', Monitor)
    native = SimpleNamespace(make_robot_from_config=lambda cfg: None, make_teleoperator_from_config=lambda cfg: None)
    def main():
        r = native.make_robot_from_config(robot.config)
        l = native.make_teleoperator_from_config(leader.config)
        r.connect()
        l.connect()
        r.send_action(l.get_action())
        assert r.motion.motions['arm_a'].monitor is r.motion.motions['arm_b'].monitor
        raise KeyboardInterrupt
    native.main = main
    with pytest.raises(KeyboardInterrupt):
        module.run_native(native, type(robot), type(leader))
    assert len(created) == 1
    assert calls == [('admit', 'arm_a'), ('admit', 'arm_b'), ('fault', 'arm_a'), ('fault', 'arm_b')]



def test_known_thermal_violation_persists_only_after_all_buses_off(module, tmp_path):
    sys.path.insert(0, str(DIRECTORY))
    try:
        from motor_health import MotorHealth
    finally:
        sys.path.remove(str(DIRECTORY))
    together, motions, action, clock = pairs(module)
    monitor = MotorHealth(tmp_path / 'health.jsonl')
    temperature = [25]
    for label, motion in motions.items():
        motion.label, motion.monitor = label, monitor
        read = motion.follower.read
        def health_read(register, name, read=read, label=label, **kwargs):
            values = {'Temperature_Limit': 70, 'Min_Voltage_Limit': 60, 'Max_Voltage_Limit': 140,
                      'Present_Temperature': temperature[0] if label == 'arm_a' else 25,
                      'Present_Input_Voltage': 120}
            return values[register] if register in values else read(register, name, **kwargs)
        motion.follower.read = health_read
    together.send(action)
    logged = []
    original_emit = monitor.emit
    def checked_emit(row):
        if row['event'] == 'fault' or row.get('stop_reasons'):
            assert all(not any(bus.torque.values()) for motion in motions.values()
                       for bus in (motion.follower, motion.leader))
            logged.append(row)
        original_emit(row)
    monitor.emit = checked_emit
    temperature[0] = 70
    clock[0] += .2
    with pytest.raises(ValueError, match='temperature'):
        together.send(action)
    assert len(logged) == 2 and all(row['event'] == 'fault' for row in logged)
    assert logged[0]['motors'][0]['temperature_c'] == 70
