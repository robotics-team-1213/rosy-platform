"""Live local sensor samples drive seating/charging through the real parking owner (SIM)."""
import importlib
from types import SimpleNamespace

from core_common.protocol.native.receipts import BOOT_ID
from core_features.docking.agent import DockReachability, DockStatus
from test_station_docking_owner import setup_owner, frame, align
from test_station_feed import observation


def sensor_owner():
    name = 'core_features.docking.station_sensors'
    module = importlib.import_module(name)
    assert hasattr(module, 'StationSensorReader'), 'measured station collector is not connected'
    owner, manager, now, local, target, session, world = setup_owner()
    signals = dict(contact=True, moving=False, normal=False, missing_motion=False,
                   dock_id='charger-1', load_age_s=0.)
    closed = []

    def cached():
        status = DockStatus(DockReachability.OK, load_present=signals['contact'], charging=not signals['normal'],
                            dock_id=signals['dock_id'],
                            load_sample_at=None if signals['load_age_s'] is None else now[0]-signals['load_age_s'],
                            termination='NORMAL' if signals['normal'] else 'UNKNOWN',
                            termination_source='charger' if signals['normal'] else 'unknown',
                            termination_sample_at=now[0] if signals['normal'] else None,
                            battery_id='pack-1' if signals['normal'] else None)
        return module.DockSample(status, now[0], now[0])

    cache = SimpleNamespace(start=lambda: None, snapshot=cached, close=lambda: closed.append(True))

    def motion():
        if signals['missing_motion']:
            return None
        return dict(odom_epoch='odom-1', captured_at=now[0],
                    measured_linear_m_s=0.02 if signals['moving'] else 0., measured_angular_rad_s=0.)

    owner.sensors = module.StationSensorReader(
        motion_sample=motion, battery_health=lambda: dict(sample_age_s=0., filtered_voltage=8.25),
        clock=lambda: now[0], source_clock=lambda: now[0], poller_factory=lambda *args, **kwargs: cache)
    owner.bind(session, target, observation(boot_id=str(BOOT_ID)))
    return owner, manager, now, signals, closed


def test_local_samples_complete_seating_charging_and_normal_termination_in_tick_order():
    owner, manager, now, signals, closed = sensor_owner()
    align(owner, manager, now)
    for sequence in range(40, 60):
        now[0] += 0.1
        frame(owner, now, sequence)
        owner.tick()
    assert owner.state == 'CHARGING'
    signals['normal'] = True
    now[0] += 0.1
    frame(owner, now, 60)
    owner.tick()
    assert owner.state == 'CHARGED_HOLD'
    assert not owner.charging.confirmed
    owner.close()
    assert closed and not owner.motion_ready('DOCKING')


def test_station_contact_and_zero_commands_cannot_replace_missing_measured_motion():
    owner, manager, now, signals, _ = sensor_owner()
    align(owner, manager, now)
    signals['missing_motion'] = True
    for sequence in range(40, 60):
        now[0] += 0.1
        frame(owner, now, sequence)
        owner.tick()
    assert owner.state == 'SEATING'
    assert not owner.motion_ready('NAVIGATION')
    owner.close()


def test_contact_loss_immediately_removes_charging_confirmation():
    owner, manager, now, signals, _ = sensor_owner()
    align(owner, manager, now)
    for sequence in range(40, 60):
        now[0] += 0.1
        frame(owner, now, sequence)
        owner.tick()
    assert owner.state == 'CHARGING'
    signals['contact'] = False
    now[0] += 0.1
    frame(owner, now, 60)
    owner.tick()
    assert owner.state == 'CHARGE_CONFIRMING'
    assert not owner.charging.confirmed
    owner.close()


def test_wrong_missing_station_or_unmeasured_switch_time_cannot_prove_seating():
    for invalid in (dict(dock_id='other'), dict(dock_id=None), dict(load_age_s=None), dict(load_age_s=1.)):
        owner, manager, now, signals, _ = sensor_owner()
        align(owner, manager, now)
        signals.update(invalid)
        for sequence in range(40, 60):
            now[0] += 0.1
            frame(owner, now, sequence)
            owner.tick()
        assert owner.state == 'SEATING'
        owner.close()
