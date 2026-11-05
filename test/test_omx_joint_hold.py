"""Hold-only commissioning never enters move/sweep or leaves configuration changes."""
import pytest

from test_omx_joint_tune import Motor, m


def hold(bus, grab=lambda label: None):
    args = m.parse(['--device', 'unused', 'hold', '--hold', '.5', '--sag', '3'])
    return m.Run(bus, 16, log=lambda **row: None, grab=grab,
                 clock=lambda: bus.t, sleep=bus.sleep).execute(args)


def configured_motor():
    bus = Motor()
    bus.reg.update(profile_acc=7, profile_vel=9, goal_current=12, goal_pos=2600)
    return bus


def test_hold_has_no_second_goal_or_camera_io_at_torque_on_and_restores_configuration():
    bus = configured_motor()
    before = dict(bus.reg)
    frames, writes = [], []
    write = bus.write

    def trace(name, value):
        writes.append((name, value, bus.reg['torque']))
        write(name, value)

    def grab(label):
        assert bus.reg['torque'] == 0
        frames.append(label)

    bus.write = trace
    result = hold(bus, grab)
    assert result['target'] == result['reached'] == before['present_pos']
    assert result['error_ticks'] == 0
    assert .5 <= bus.t <= .6
    assert frames == ['before', 'after']
    assert [(value, torque) for name, value, torque in writes if name == 'goal_pos'] == [
        (before['present_pos'], 0), (before['goal_pos'], 0)]
    assert not any(name in m.EEPROM for name, *_ in writes)
    assert not any(torque and name != 'torque' for name, _, torque in writes)
    assert bus.reg == before


@pytest.mark.parametrize('fault', ['drift', 'hardware', 'feedback_gap', 'frozen_clock'])
def test_hold_fault_ends_torque_off_and_restores_every_changed_setting(fault):
    bus = configured_motor()
    before = dict(bus.reg)
    if fault == 'drift':
        bus.sag, bus.holds_at = 10, 21
    elif fault == 'hardware':
        bus.fail_at = .2
    elif fault == 'feedback_gap':
        sleep = bus.sleep
        bus.sleep = lambda seconds: sleep(.3)
    else:
        bus.sleep = lambda seconds: None
    with pytest.raises(RuntimeError, match='sagged|hardware error|feedback sample gap|clock did not advance'):
        hold(bus)
    assert bus.reg['torque'] == 0
    for name in ('profile_acc', 'profile_vel', 'goal_current', 'goal_pos', 'pwm_limit', 'current_limit'):
        assert bus.reg[name] == before[name]
    assert not any(name in m.EEPROM for name, _ in bus.writes)


@pytest.mark.parametrize('argv', [
    ['--id', '15', 'hold'], ['--id', '5', 'hold'], ['hold', '--delta', '0'],
    ['hold', '--to', '2028'], ['hold', '--pwm', '21'], ['hold', '--current-limit', '51'],
    ['hold', '--p-gain', '250'], ['hold', '--i-gain', '0'],
    ['hold', '--velocity', '2'], ['hold', '--acceleration', '2'],
])
def test_hold_refuses_motion_gain_or_nonbaseline_configuration_before_device_access(argv):
    with pytest.raises(SystemExit):
        m.parse(['--device', 'unused', *argv])


def test_hold_restore_failure_still_attempts_remaining_registers_and_reports_unsafe_end():
    bus = configured_motor()
    write = bus.write

    def fail_restore(name, value):
        if name == 'profile_acc' and value == 7:
            raise RuntimeError('restore failed')
        write(name, value)

    bus.write = fail_restore
    with pytest.raises(RuntimeError, match='did not end safely'):
        hold(bus)
    assert bus.reg['torque'] == 0
    assert bus.reg['profile_acc'] == 1
    assert (bus.reg['profile_vel'], bus.reg['goal_current'], bus.reg['goal_pos']) == (9, 12, 2600)


def test_unconfirmed_torque_off_skips_restore_and_camera_io():
    bus = configured_motor()
    write = bus.write
    frames = []

    def fail_off(name, value):
        if name == 'torque' and value == 0 and bus.reg['torque']:
            raise RuntimeError('torque off unavailable')
        write(name, value)

    def grab(label):
        assert bus.reg['torque'] == 0
        frames.append(label)

    bus.write = fail_off
    with pytest.raises(RuntimeError, match='did not end safely'):
        hold(bus, grab)
    assert frames == ['before']
    assert bus.reg['torque'] == 1
    assert (bus.reg['profile_acc'], bus.reg['profile_vel'], bus.reg['goal_current']) == (1, 1, 50)
    assert bus.reg['goal_pos'] == bus.reg['present_pos']


def test_after_frame_failure_cannot_skip_register_restoration():
    bus = configured_motor()
    before = dict(bus.reg)

    def grab(label):
        if label == 'after':
            raise RuntimeError('frame output failed')

    with pytest.raises(RuntimeError, match='frame output failed'):
        hold(bus, grab)
    assert bus.reg == before
