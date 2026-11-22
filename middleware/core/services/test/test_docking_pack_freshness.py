"""A pack-only charge indication requires consecutive source observations."""

import pytest

from core_common.protocol.schemas import DockState
from core_features.docking.charging import PackChargeConfirmation
from core_features.docking.manager import DockPhase
from core_features.power.battery import BatteryConfig, BatteryMonitor
from test_docking_bay import Clock, a_bay, run as run_bay
from test_docking_bay_reseat import _dock as start_reference_bay, run as run_reference_bay
from test_docking_rear import a_rear, run as run_rear


@pytest.mark.parametrize("make,drive,window", [(a_bay, run_bay, 20), (a_rear, run_rear, 10)])
@pytest.mark.parametrize("freeze", [True, False])
def test_voltage_only_contact_needs_live_adc_and_withdraws_when_it_stops(make, drive, window, freeze):
    p = make(max_retries=0)
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=p.clock)
    p.manager._battery = pack
    p.manager.dock()
    drive(p, lambda manager: manager.phase is DockPhase.SETTLING)
    assert p.manager.phase is DockPhase.SETTLING
    start = p.clock.now
    for tick in range(4 * (window + 1)):
        elapsed = tick * 0.25
        p.clock.now = start + elapsed
        if tick % 4 == 0 and (not freeze or elapsed <= 4):
            pack.on_voltage(7.6 if elapsed < 3 else 7.9)
        p.manager.tick()
    if freeze:
        assert p.manager.state not in (DockState.DOCKED, DockState.CHARGING)
    else:
        assert p.manager.state is DockState.CHARGING
        p.clock.now += 5.1
        p.manager.tick()
        assert p.manager.state is DockState.DOCKED
        assert any(kind == "docking.charge_lost" for kind, _ in p.events)
        assert not p.manager.status().charge_unconfirmed   # reserved for a LiDAR-confirmed seat
        for tick in range(2 * window + 3):
            p.clock.now += 1
            pack.on_voltage(7.9 if tick <= window else 8.0)
            p.manager.tick()
            assert p.manager.state is (DockState.DOCKED if tick <= window else DockState.CHARGING)
        assert [kind for kind, _ in p.events].count("docking.charging") == 2
    assert not pack.health()["charging_latched"]


def test_a_cached_read_does_not_advance_the_window_and_a_gap_restarts_it():
    clock = Clock()
    start = clock.now
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=clock)
    confirmation = PackChargeConfirmation(clock=clock, window_s=4)

    def observe(elapsed, volts=None):
        clock.now = start + elapsed
        if volts is not None:
            pack.on_voltage(volts)
        return confirmation.observe(pack, now=clock(), since_settled=elapsed, rise_v=0.05)

    assert not observe(0, 7.6)
    assert not observe(1, 7.7)
    assert not observe(5)                      # last capture is fresh, but only t=0..1 was measured
    assert not observe(7, 7.7)                 # first new capture after a gap the manager never saw
    assert not observe(10, 7.8)
    assert observe(11, 7.8)
    assert observe(16)                        # exactly the ADC freshness boundary
    assert not observe(16.01)


def test_only_a_sample_captured_after_settle_delay_can_set_the_baseline():
    clock = Clock()
    start = clock.now
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=clock)
    confirmation = PackChargeConfirmation(clock=clock, window_s=3)
    pack.on_voltage(7.6)
    clock.now = start + 2
    confirmation.begin_settling(pack)
    clock.now = start + 2.5
    pack.on_voltage(7.6)
    clock.now = start + 4
    assert not confirmation.observe(pack, now=clock(), since_settled=2, baseline_delay_s=1, rise_v=0.05)
    for t, voltage in ((5, 7.8), (8, 7.8), (9, 7.9)):
        clock.now = start + t
        pack.on_voltage(voltage)
        result = confirmation.observe(pack, now=clock(), since_settled=t - 2, baseline_delay_s=1, rise_v=0.05)
        assert result is (t == 9)


def test_qualifying_peak_survives_normal_ripple_until_the_confirm_window_is_full():
    clock = Clock()
    start = clock.now
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=clock)
    tracker = PackChargeConfirmation(clock=clock, window_s=20)
    for t in range(31):
        clock.now = start + t
        pack.on_voltage(7.6 if t < 4 else (7.655 if t == 4 else 7.645))
        verified = tracker.observe(pack, now=clock(), since_settled=t, baseline_delay_s=2, rise_v=0.05)
        assert verified is (t >= 20)


@pytest.mark.parametrize("rate", [0.25, 4.0])
def test_confirm_window_uses_docking_time_and_freshness_uses_pack_time(rate):
    clock = Clock()
    start = clock.now
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=clock)
    confirmation = PackChargeConfirmation(clock=clock, window_s=10)
    for tick in range(41):
        sim_time = tick * 0.25
        clock.now = start + sim_time / rate
        pack.on_voltage(7.6 if sim_time < 3 else 7.9)
        result = confirmation.observe(pack, now=sim_time, since_settled=sim_time,
                                      baseline_delay_s=2, rise_v=0.05)
        assert result is (tick == 40)
    clock.now += 5.01
    assert not confirmation.observe(pack, now=sim_time, since_settled=sim_time, rise_v=0.05)


def test_lidar_seat_with_flat_voltage_waits_for_a_measured_rise_in_one_window():
    p = start_reference_bay(charges=False)
    run_reference_bay(p)
    assert p.manager.status().charge_unconfirmed
    pack = BatteryMonitor(BatteryConfig(filter_tau_s=0), clock=p.clock)
    p.manager._battery = pack
    for t in range(91):
        p.clock.now += 1
        # Flat and a short 10 mV contact, then 60 mV drift over a minute (only 20 mV/window).
        volts = 7.60 + min(t, 60) * 0.001 + (0.01 if t == 4 else 0.0)
        if t >= 65:
            volts = 7.75  # genuine late contact; the ensuing plateau keeps the confirmation
        pack.on_voltage(volts)
        p.manager.tick()
        assert p.manager.state is (DockState.DOCKED if t < 65 else DockState.CHARGING)
        assert p.manager.status().charge_unconfirmed is (t < 65)
    assert [kind for kind, _ in p.events].count("docking.charging") == 1
    assert not pack.health()["charging_latched"]
