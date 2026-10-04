"""Power health: stale telemetry is unknown; repeated battery alarms do not defeat sleep."""
from core_common.protocol.schemas import PowerMode, RobotMode
from core_features.power.battery import BatteryConfig, BatteryMonitor
from core_features.power.manager import PowerConfig, PowerManager


def test_repeated_warning_allows_idle_and_standby_without_hiding_escalation():
    now = [100.0]
    power = PowerManager(PowerConfig(), clock=lambda: now[0])
    power.on_battery_alert('warning')
    for second in range(1, 302):
        now[0] = 100.0 + second
        power.on_battery_alert('warning')
        power.tick()
    assert power.mode == PowerMode.STANDBY
    power.on_battery_alert('critical')
    assert power.mode == PowerMode.ACTIVE
    power.on_battery_alert('ok')
    power.request_mode(PowerMode.STANDBY)
    power.on_battery_alert('warning')
    assert power.mode == PowerMode.ACTIVE


def test_battery_health_reports_unknown_stale_and_charging_confirmation():
    now = [10.0]
    battery = BatteryMonitor(BatteryConfig(), clock=lambda: now[0])
    assert battery.health()['evidence'] == 'missing'
    battery.on_voltage(7.6)
    assert battery.health()['evidence'] == 'fresh'
    assert battery.health()['charging_state'] == 'unconfirmed'
    now[0] += 6
    assert battery.health()['evidence'] == 'stale'
    assert battery.health()['sample_age_s'] == 6
    battery.set_charging(True)
    assert battery.health()['evidence'] == 'stale'
    assert battery.health()['charging_state'] == 'unconfirmed'
    assert battery.health()['charging_latched'] is True
    battery.on_voltage(7.6)
    assert battery.health()['charging_state'] == 'confirmed'
    now[0] += 6
    battery.on_voltage(7.6)
    assert battery.health()['charging_state'] == 'unconfirmed'
    battery.set_charging(True)
    assert battery.health()['charging_state'] == 'confirmed'


def test_power_health_explains_moving_robot_sleep_interlock():
    power = PowerManager(PowerConfig())
    power.on_robot_mode(RobotMode.MANUAL)
    health = power.health()
    assert health['sleep_blockers'] == ['robot_mode_not_idle']
    assert health['deepest_available_mode'] == 'ACTIVE'
    assert health['os_halt_remote_wake'] == 'not_verified'


def test_long_testing_dwell_shortens_only_for_low_battery_and_keeps_motion_interlock():
    now = [0.0]
    power = PowerManager(PowerConfig(), clock=lambda: now[0])
    now[0] = 300
    power.tick()
    assert power.mode == PowerMode.ACTIVE
    now[0] = 600
    power.tick()
    assert power.mode == PowerMode.IDLE
    now[0] = 1800
    power.tick()
    assert power.mode == PowerMode.STANDBY
    power.on_battery_alert('critical')
    health = power.health()
    assert health['effective_idle_after_s'] == 30
    assert health['effective_standby_after_s'] == 120
    now[0] += 120
    power.tick()
    assert power.mode == PowerMode.STANDBY
    power.on_robot_mode(RobotMode.MANUAL)
    assert power.mode == PowerMode.ACTIVE


def test_warning_dwell_and_explicit_standby_use_effective_limits():
    power = PowerManager(PowerConfig(warning_idle_after_s=45, warning_standby_after_s=240))
    power.on_battery_alert('warning')
    assert power.health()['effective_idle_after_s'] == 45
    power.request_mode(PowerMode.STANDBY)
    assert power.mode == PowerMode.STANDBY
    power.on_battery_alert('ok')
    assert power.health()['effective_standby_after_s'] == 1800
