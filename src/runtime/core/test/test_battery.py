"""SAF-005 배터리 무결성/저배터리 경보 단위 테스트 — 주입 클럭 기반 순수 로직.

설계: docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md
"""

import math

import pytest

from core_features.power.battery import BatteryConfig, BatteryCurve


class FakeClock:
    """단조 시계 대역 — 테스트가 시간을 명시적으로 전진시킨다."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> float:
        self.now += seconds
        return self.now


@pytest.fixture
def clock():
    return FakeClock()


# 설계 §"측정이 틀렸다" — 2S Li-ion OCV 표 (팩 전압, percent).
CURVE_2S = [
    (8.40, 100.0), (8.12, 90.0), (7.96, 80.0), (7.84, 70.0),
    (7.74, 60.0), (7.64, 50.0), (7.58, 40.0), (7.50, 30.0),
    (7.42, 20.0), (7.32, 10.0), (6.60, 5.0), (6.40, 0.0),
]


# --- BatteryCurve: OCV 표 보간 -----------------------------------------------

class TestBatteryCurve:
    def test_breakpoints_map_exactly(self):
        """표에 적힌 지점은 보간 오차 없이 그 값 그대로 나와야 한다."""
        curve = BatteryCurve(CURVE_2S)
        for voltage, percent in CURVE_2S:
            assert curve.percent(voltage) == pytest.approx(percent, abs=1e-9)

    def test_interpolates_between_breakpoints(self):
        """두 지점 사이는 선형 보간이다. 7.79V는 7.84(70%)와 7.74(60%)의 중간."""
        curve = BatteryCurve(CURVE_2S)
        assert curve.percent(7.79) == pytest.approx(65.0, abs=0.01)

    def test_clamps_above_full_and_below_empty(self):
        curve = BatteryCurve(CURVE_2S)
        assert curve.percent(9.20) == 100.0
        assert curve.percent(8.41) == 100.0
        assert curve.percent(6.39) == 0.0
        assert curve.percent(0.0) == 0.0

    def test_monotonic_across_a_descending_sweep(self):
        """전압이 내려가면 percent도 절대 올라가면 안 된다."""
        curve = BatteryCurve(CURVE_2S)
        previous = 101.0
        voltage = 8.60
        while voltage >= 6.20:
            current = curve.percent(voltage)
            assert current <= previous + 1e-9, f"{voltage=} rose to {current} from {previous}"
            previous = current
            voltage -= 0.01

    def test_the_2s_regression_that_motivated_this_work(self):
        """2S 팩 실측 3점 — 3S 상수(12.6/10.0)로는 전부 0%로 클램프되던 값들."""
        curve = BatteryCurve(CURVE_2S)
        assert curve.percent(8.40) == pytest.approx(100.0)
        assert curve.percent(6.40) == pytest.approx(0.0)
        # 공칭 7.4V는 중간대여야 한다 — 0%도 100%도 아니다.
        mid = curve.percent(7.40)
        assert 10.0 < mid < 30.0

    def test_linear_span_fallback_when_no_table(self):
        """표가 없으면 기존 two-point 스팬으로 되돌아간다 (시뮬·3S 변형 보호)."""
        curve = BatteryCurve.from_span(full=8.4, empty=6.4)
        assert curve.percent(8.4) == pytest.approx(100.0)
        assert curve.percent(6.4) == pytest.approx(0.0)
        assert curve.percent(7.4) == pytest.approx(50.0)

    def test_rejects_a_single_point_table(self):
        with pytest.raises(ValueError):
            BatteryCurve([(8.4, 100.0)])

    def test_rejects_a_non_monotonic_table(self):
        """전압 내림차순으로 정렬해도 percent가 뒤집히는 표 — 보간이 무의미해진다."""
        with pytest.raises(ValueError):
            BatteryCurve([(8.40, 100.0), (7.60, 30.0), (7.50, 40.0), (6.40, 0.0)])

    def test_rejects_a_duplicate_voltage(self):
        with pytest.raises(ValueError):
            BatteryCurve([(8.40, 100.0), (7.50, 30.0), (7.50, 20.0), (6.40, 0.0)])

    def test_rejects_an_empty_table(self):
        with pytest.raises(ValueError):
            BatteryCurve([])

    def test_accepts_an_ascending_table_by_normalising_it(self):
        """설정 파일이 낮은 전압부터 쓰는 것도 흔하다 — 순서로 거부하지 않는다."""
        curve = BatteryCurve(list(reversed(CURVE_2S)))
        assert curve.percent(8.40) == pytest.approx(100.0)
        assert curve.percent(7.50) == pytest.approx(30.0)


# --- 전압 저역통과 필터 -------------------------------------------------------

class TestVoltageFilter:
    def _monitor(self, clock, **kwargs):
        from core_features.power.battery import BatteryMonitor
        config = BatteryConfig(curve=BatteryCurve(CURVE_2S), **kwargs)
        return BatteryMonitor(config, clock=clock)

    def test_first_sample_seeds_the_filter(self, clock):
        """첫 표본은 0에서 램프업하지 않고 그 값으로 시작한다."""
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(7.80)
        assert monitor.voltage == pytest.approx(7.80)

    def test_a_step_settles_toward_the_new_value(self, clock):
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(8.00)
        for _ in range(200):
            clock.advance(0.5)
            monitor.on_voltage(7.50)
        assert monitor.voltage == pytest.approx(7.50, abs=0.01)

    def test_a_single_sample_dip_barely_moves_the_filtered_value(self, clock):
        """모터 가속 새그 1발 — 설계가 막으려는 바로 그 입력."""
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(7.80)
        clock.advance(0.2)
        monitor.on_voltage(7.40)          # 400 mV 새그
        # 0.2s / tau 5s → 4% 남짓만 반영되어야 한다.
        assert monitor.voltage > 7.77

    def test_non_finite_samples_leave_the_filter_untouched(self, clock):
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(7.80)
        for bad in (float("nan"), float("inf"), float("-inf")):
            clock.advance(1.0)
            monitor.on_voltage(bad)
            assert monitor.voltage == pytest.approx(7.80)

    def test_no_samples_yet_reports_no_voltage(self, clock):
        monitor = self._monitor(clock)
        assert monitor.voltage is None
        assert monitor.percent is None

    def test_percent_follows_the_filtered_voltage_not_the_raw_sample(self, clock):
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(7.84)                       # 70%
        clock.advance(0.2)
        monitor.on_voltage(6.40)                       # 생표본으로는 0%
        assert monitor.percent > 60.0

    def test_zero_tau_disables_filtering(self, clock):
        """tau=0은 필터 없음 — 시뮬레이션과 결정론적 테스트를 위한 탈출구."""
        monitor = self._monitor(clock, filter_tau_s=0.0)
        monitor.on_voltage(7.84)
        clock.advance(1.0)
        monitor.on_voltage(7.50)
        assert monitor.voltage == pytest.approx(7.50)

    def test_a_sample_with_no_elapsed_time_does_not_divide_by_zero(self, clock):
        monitor = self._monitor(clock, filter_tau_s=5.0)
        monitor.on_voltage(7.80)
        monitor.on_voltage(7.40)                        # 같은 시각
        assert math.isfinite(monitor.voltage)


# --- 단계 머신: 히스테리시스 + dwell -------------------------------------------

class RecordingEvents:
    """EventBus 대역 — 발행된 이벤트를 순서대로 모은다."""

    def __init__(self) -> None:
        self.published: list[tuple] = []

    def publish(self, type_, severity=None, source=None, data=None):
        self.published.append((type_, severity, source, data or {}))

    def types(self) -> list[str]:
        return [entry[0] for entry in self.published]


def make_monitor(clock, events=None, **kwargs):
    from core_features.power.battery import BatteryMonitor
    options = dict(
        curve=BatteryCurve(CURVE_2S),
        filter_tau_s=0.0,          # 단계 로직을 시험할 때는 필터를 끈다
        warning_percent=20.0,
        critical_percent=10.0,
        deep_percent=5.0,
        enter_samples=3,
        exit_samples=5,
        hysteresis_percent=3.0,
        deep_dwell_s=60.0,
    )
    options.update(kwargs)
    return BatteryMonitor(BatteryConfig(**options), clock=clock, events=events)


def feed(monitor, clock, percent_voltage, times, step_s=1.0):
    for _ in range(times):
        clock.advance(step_s)
        monitor.on_voltage(percent_voltage)


class TestLevelMachine:
    def test_starts_ok_with_no_samples(self, clock):
        from core_features.power.battery import BatteryLevel
        assert make_monitor(clock).level is BatteryLevel.OK

    def test_enter_samples_required_to_descend(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.42, 2)          # 20% — 아직 두 표본
        assert monitor.level is BatteryLevel.OK
        feed(monitor, clock, 7.42, 1)
        assert monitor.level is BatteryLevel.WARNING

    def test_exit_needs_more_samples_and_a_hysteresis_margin(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3, exit_samples=5,
                               hysteresis_percent=3.0)
        feed(monitor, clock, 7.42, 3)          # 20% → WARNING
        assert monitor.level is BatteryLevel.WARNING

        # 임계 바로 위(21%)는 히스테리시스 마진(23%) 안이라 복귀시키지 않는다.
        feed(monitor, clock, 7.43, 10)
        assert monitor.level is BatteryLevel.WARNING

        # 마진을 넘긴 뒤에도 exit_samples 만큼은 버텨야 한다.
        feed(monitor, clock, 7.50, 4)          # 30%
        assert monitor.level is BatteryLevel.WARNING
        feed(monitor, clock, 7.50, 1)
        assert monitor.level is BatteryLevel.OK

    def test_oscillating_on_a_threshold_transitions_once(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3, exit_samples=5,
                               hysteresis_percent=3.0)
        feed(monitor, clock, 7.42, 3)
        assert monitor.level is BatteryLevel.WARNING
        for _ in range(20):
            feed(monitor, clock, 7.43, 1)      # 21%
            feed(monitor, clock, 7.41, 1)      # 19%
        assert monitor.level is BatteryLevel.WARNING

    def test_a_sustained_decline_visits_each_level_in_order(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        seen = [monitor.level]
        for voltage in (7.42, 7.32, 6.60):     # 20% → 10% → 5%
            feed(monitor, clock, voltage, 3)
            seen.append(monitor.level)
        assert seen == [BatteryLevel.OK, BatteryLevel.WARNING,
                        BatteryLevel.CRITICAL, BatteryLevel.DEEP]

    def test_a_collapse_still_steps_through_every_level(self, clock):
        """ok에서 곧장 deep 입력이 와도 단계를 건너뛰지 않는다."""
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        seen = []
        for _ in range(9):                      # 3단계 × enter_samples
            clock.advance(1.0)
            monitor.on_voltage(6.40)            # 0%
            seen.append(monitor.level)
        assert seen[2] is BatteryLevel.WARNING
        assert seen[5] is BatteryLevel.CRITICAL
        assert seen[8] is BatteryLevel.DEEP

    def test_recovery_also_steps_one_level_at_a_time(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3, exit_samples=2)
        feed(monitor, clock, 6.40, 9)
        assert monitor.level is BatteryLevel.DEEP
        feed(monitor, clock, 8.40, 2)
        assert monitor.level is BatteryLevel.CRITICAL
        feed(monitor, clock, 8.40, 2)
        assert monitor.level is BatteryLevel.WARNING
        feed(monitor, clock, 8.40, 2)
        assert monitor.level is BatteryLevel.OK

    def test_deep_is_not_armed_until_the_dwell_elapses(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        assert monitor.level is BatteryLevel.DEEP
        assert monitor.shutdown_armed is False
        feed(monitor, clock, 6.40, 1, step_s=59.0)
        assert monitor.shutdown_armed is False      # 경계 바로 앞
        feed(monitor, clock, 6.40, 1, step_s=1.0)
        assert monitor.shutdown_armed is True

    def test_recovery_before_the_dwell_disarms(self, clock):
        monitor = make_monitor(clock, enter_samples=3, exit_samples=2,
                               deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        assert monitor.shutdown_armed is False
        feed(monitor, clock, 8.40, 2, step_s=1.0)
        feed(monitor, clock, 8.40, 1, step_s=120.0)
        assert monitor.shutdown_armed is False

    def test_deep_event_is_emitted_once_on_entry(self, clock):
        """DEEP 진입이 모터가 멈추는 순간이다 — dwell 만료가 아니라 그때 기록된다."""
        events = RecordingEvents()
        monitor = make_monitor(clock, events=events, enter_samples=3,
                               deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9)
        assert events.types().count("battery.deep") == 1
        assert monitor.shutdown_armed is False

        feed(monitor, clock, 6.40, 20, step_s=10.0)   # dwell 통과
        assert monitor.shutdown_armed is True
        assert events.types().count("battery.deep") == 1

    def test_re_entering_deep_after_recovery_emits_again(self, clock):
        events = RecordingEvents()
        monitor = make_monitor(clock, events=events, enter_samples=3,
                               exit_samples=2)
        feed(monitor, clock, 6.40, 9)
        feed(monitor, clock, 8.40, 6)                 # OK 까지 복귀
        feed(monitor, clock, 6.40, 9)
        assert events.types().count("battery.deep") == 2

    def test_level_does_not_move_without_samples(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock)
        clock.advance(10_000.0)
        assert monitor.level is BatteryLevel.OK
        assert monitor.shutdown_armed is False


# --- LED 경보 의도 및 우선순위 -------------------------------------------------

class TestLedAlertIntent:
    def test_ok_declares_no_alert(self, clock):
        monitor = make_monitor(clock)
        feed(monitor, clock, 8.40, 5)
        assert monitor.led_alert is None

    def test_no_samples_declares_no_alert(self, clock):
        assert make_monitor(clock).led_alert is None

    def test_warning_is_solid_amber(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.42, 3)
        alert = monitor.led_alert
        assert alert is not None
        assert alert.level is BatteryLevel.WARNING
        assert alert.blink_hz == 0.0
        assert alert.g > 0 and alert.b == 0 and alert.r > alert.g   # amber

    def test_critical_is_red_at_1_hz(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.32, 6)
        alert = monitor.led_alert
        assert alert.level is BatteryLevel.CRITICAL
        assert (alert.r, alert.g, alert.b) == (60, 0, 0)
        assert alert.blink_hz == pytest.approx(1.0)

    def test_deep_is_red_at_2_hz(self, clock):
        from core_features.power.battery import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 6.40, 9)
        alert = monitor.led_alert
        assert alert.level is BatteryLevel.DEEP
        assert (alert.r, alert.g, alert.b) == (60, 0, 0)
        assert alert.blink_hz == pytest.approx(2.0)

    def test_solid_alert_is_always_lit(self, clock):
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.42, 3)
        alert = monitor.led_alert
        assert all(alert.lit_at(1000.0 + t * 0.05) for t in range(40))

    def test_blink_phase_is_a_pure_function_of_the_clock(self, clock):
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.32, 6)
        alert = monitor.led_alert                      # 1 Hz
        assert alert.lit_at(0.0) is True
        assert alert.lit_at(0.25) is True
        assert alert.lit_at(0.60) is False
        assert alert.lit_at(0.99) is False
        assert alert.lit_at(1.10) is True
        # 같은 시각은 언제 물어도 같은 답이다.
        assert alert.lit_at(0.60) is False

    def test_blink_duty_is_half(self, clock):
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 6.40, 9)
        alert = monitor.led_alert                      # 2 Hz
        lit = sum(1 for t in range(1000) if alert.lit_at(t * 0.001))
        assert 480 <= lit <= 520

    def test_alert_is_independent_of_power_mode(self, clock):
        """STANDBY에서도 경보는 살아 있어야 한다 — 그게 이 기능의 존재 이유다."""
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.32, 6)
        assert monitor.led_alert is not None
        # BatteryMonitor는 전원 모드를 알지도 못한다 — 결합이 없음을 확인한다.
        assert not hasattr(monitor, "power_mode")

    def test_alert_clears_when_the_level_recovers(self, clock):
        monitor = make_monitor(clock, enter_samples=3, exit_samples=2)
        feed(monitor, clock, 7.32, 6)
        assert monitor.led_alert is not None
        feed(monitor, clock, 8.40, 4)
        assert monitor.led_alert is None


# --- 스냅샷 노출 --------------------------------------------------------------

class TestBatteryStatusSchema:
    def test_battery_level_lives_in_protocol_schemas(self):
        """D-18: 스키마 단일 소스는 protocol.schemas 다."""
        from core_common.protocol.schemas import BatteryLevel as SchemaLevel
        from core_features.power.battery import BatteryLevel as PolicyLevel
        assert SchemaLevel is PolicyLevel

    def test_snapshot_carries_battery_status_with_safe_defaults(self):
        from core_common.protocol.schemas import BatteryLevel, StateSnapshot
        snap = StateSnapshot(robot_id="rosy_01")
        assert snap.battery_status.level is BatteryLevel.OK
        assert snap.battery_status.shutdown_armed is False
        assert snap.battery_status.filtered_voltage is None

    def test_existing_battery_shape_is_unchanged(self):
        """대시보드와 /metrics 가 읽는 필드 — 이 작업으로 깨지면 안 된다."""
        from core_common.protocol.schemas import StateSnapshot
        snap = StateSnapshot(robot_id="rosy_01")
        assert snap.battery.percent is None  # no reading is not 0% (D-82 Law 0)
        assert snap.battery.voltage is None

    def test_state_manager_accepts_a_battery_status(self, clock):
        from core_common.protocol.schemas import BatteryLevel, BatteryStatus
        from core_features.state.manager import StateManager
        state = StateManager("rosy_01")
        state.set_battery_status(BatteryStatus(
            level=BatteryLevel.CRITICAL, shutdown_armed=False,
            filtered_voltage=7.31))
        snap = state.snapshot()
        assert snap.battery_status.level is BatteryLevel.CRITICAL
        assert snap.battery_status.filtered_voltage == pytest.approx(7.31)

    def test_monitor_reports_its_own_status(self, clock):
        from core_common.protocol.schemas import BatteryLevel
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, 7.32, 6)
        status = monitor.status()
        assert status.level is BatteryLevel.CRITICAL
        assert status.shutdown_armed is False
        assert status.filtered_voltage == pytest.approx(7.32)


# --- 셧다운 센티넬 ------------------------------------------------------------

class TestShutdownSentinel:
    def _monitor(self, clock, tmp_path, events=None, **kwargs):
        return make_monitor(clock, events=events,
                            sentinel_path=tmp_path / "battery-shutdown-request.json",
                            shutdown_grace_s=120.0, **kwargs)

    def _sentinel(self, tmp_path):
        return tmp_path / "battery-shutdown-request.json"

    def test_nothing_is_written_before_the_dwell(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        assert monitor.level.value == "deep"
        assert not self._sentinel(tmp_path).exists()

    def test_the_file_appears_once_the_dwell_is_held(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        assert self._sentinel(tmp_path).exists()

    def test_the_document_carries_the_agreed_fields(self, clock, tmp_path):
        import json
        monitor = self._monitor(clock, tmp_path, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        document = json.loads(self._sentinel(tmp_path).read_text(encoding="utf-8"))
        assert set(document) >= {
            "requested_at", "reason", "percent", "voltage", "grace_seconds"}
        assert document["reason"] == "battery_deep_discharge"
        assert document["grace_seconds"] == 120.0
        assert document["percent"] == pytest.approx(0.0)
        assert document["voltage"] == pytest.approx(6.40)
        # 호스트 유닛이 신선도를 판정하려면 파싱 가능한 절대 시각이어야 한다.
        from datetime import datetime
        assert datetime.fromisoformat(
            document["requested_at"].replace("Z", "+00:00")).tzinfo is not None

    def test_recovery_before_the_dwell_writes_nothing(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, exit_samples=2,
                                deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 8.40, 2, step_s=1.0)
        feed(monitor, clock, 8.40, 1, step_s=600.0)
        assert not self._sentinel(tmp_path).exists()

    def test_recovery_after_the_dwell_removes_the_file(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, exit_samples=2,
                                deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        assert self._sentinel(tmp_path).exists()
        feed(monitor, clock, 8.40, 2, step_s=1.0)
        assert not self._sentinel(tmp_path).exists()

    def test_a_held_deep_does_not_rewrite_the_file(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        first = self._sentinel(tmp_path).read_text(encoding="utf-8")
        feed(monitor, clock, 6.40, 50, step_s=10.0)
        assert self._sentinel(tmp_path).read_text(encoding="utf-8") == first

    def test_no_temporary_file_is_left_behind(self, clock, tmp_path):
        monitor = self._monitor(clock, tmp_path, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        assert [p.name for p in tmp_path.iterdir()] == [
            "battery-shutdown-request.json"]

    def test_a_write_failure_is_reported_not_raised(self, clock, tmp_path):
        events = RecordingEvents()
        missing = tmp_path / "no-such-dir" / "request.json"
        monitor = make_monitor(clock, events=events, enter_samples=3,
                               deep_dwell_s=60.0, sentinel_path=missing,
                               shutdown_grace_s=120.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)      # 예외가 콜백으로 새면 안 된다
        assert "battery.shutdown_request_failed" in events.types()

    def test_no_sentinel_path_disables_the_writer(self, clock, tmp_path):
        monitor = make_monitor(clock, enter_samples=3, deep_dwell_s=60.0)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        assert monitor.shutdown_armed is True            # 판정은 그대로 살아 있다
        assert list(tmp_path.iterdir()) == []


# --- 설정 배선 ----------------------------------------------------------------

def _shipped_config(name="config/rosy_default.yaml"):
    import pathlib
    import yaml
    root = pathlib.Path(__file__).resolve().parents[1]
    return yaml.safe_load((root / name).read_text(encoding="utf-8"))


def _pi5_config():
    import pathlib
    import yaml
    root = pathlib.Path(__file__).resolve().parents[4]
    path = root / "deploy/robot/config/rosy.pi5.example.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class TestShippedConfiguration:
    def test_default_config_declares_a_2s_span(self):
        """3S 상수(12.6/10.0)가 남아 있으면 실기 percent가 0으로 고정된다."""
        safety = _shipped_config()["safety"]
        assert safety["battery_full_voltage"] == pytest.approx(8.4)
        assert safety["battery_empty_voltage"] == pytest.approx(6.4)

    def test_pi5_example_declares_a_2s_span(self):
        """Pi에 실제로 배포되는 파일 — 여기가 틀리면 기본값 정정이 무의미하다."""
        safety = _pi5_config()["safety"]
        assert safety["battery_full_voltage"] == pytest.approx(8.4)
        assert safety["battery_empty_voltage"] == pytest.approx(6.4)

    def test_default_config_ships_the_2s_curve(self):
        from core.services import _battery_config
        cfg = _battery_config(_shipped_config()["safety"], data_path=None)
        assert cfg.curve.points[0] == (8.40, 100.0)
        assert cfg.curve.points[-1] == (6.40, 0.0)

    def test_the_regression_is_closed_against_the_shipped_defaults(self):
        """7.4V(2S 공칭)가 0%로 클램프되던 것이 이 작업의 출발점이다."""
        from core.services import _battery_config
        cfg = _battery_config(_shipped_config()["safety"], data_path=None)
        percent = cfg.curve.percent(7.40)
        assert percent > 0.0
        assert 10.0 < percent < 30.0

    def test_a_full_2s_pack_reads_full(self):
        from core.services import _battery_config
        cfg = _battery_config(_shipped_config()["safety"], data_path=None)
        assert cfg.curve.percent(8.40) == pytest.approx(100.0)


class TestBatteryConfigParsing:
    def test_missing_keys_keep_defaults(self):
        from core.services import _battery_config
        cfg = _battery_config({}, data_path=None)
        assert cfg.warning_percent == 20.0
        assert cfg.critical_percent == 10.0
        assert cfg.deep_percent == 5.0
        assert cfg.filter_tau_s > 0.0

    def test_a_configured_curve_wins_over_the_span(self):
        from core.services import _battery_config
        cfg = _battery_config({
            "battery_full_voltage": 12.6,
            "battery_empty_voltage": 10.0,
            "battery_curve": [[12.6, 100], [11.1, 50], [10.0, 0]],
        }, data_path=None)
        assert cfg.curve.percent(11.1) == pytest.approx(50.0)

    def test_no_curve_falls_back_to_the_span(self):
        from core.services import _battery_config
        cfg = _battery_config({
            "battery_full_voltage": 12.6, "battery_empty_voltage": 10.0,
        }, data_path=None)
        assert cfg.curve.percent(11.3) == pytest.approx(50.0)

    def test_thresholds_and_dwell_come_from_config(self):
        from core.services import _battery_config
        cfg = _battery_config({
            "battery_warning_percent": 25,
            "battery_critical_percent": 12,
            "battery_deep_percent": 6,
            "battery_deep_dwell_s": 30,
            "battery_shutdown_grace_s": 90,
            "battery_filter_tau_s": 2.5,
            "battery_enter_samples": 4,
            "battery_exit_samples": 7,
            "battery_hysteresis_percent": 5,
        }, data_path=None)
        assert (cfg.warning_percent, cfg.critical_percent, cfg.deep_percent) == (25.0, 12.0, 6.0)
        assert cfg.deep_dwell_s == 30.0
        assert cfg.shutdown_grace_s == 90.0
        assert cfg.filter_tau_s == 2.5
        assert (cfg.enter_samples, cfg.exit_samples) == (4, 7)
        assert cfg.hysteresis_percent == 5.0

    def test_sentinel_path_is_none_without_a_data_path(self):
        """데이터 경로가 없으면 호스트를 끌 수단도 없다 — 조용히 비활성이다."""
        from core.services import _battery_config
        assert _battery_config({}, data_path=None).sentinel_path is None

    def test_sentinel_path_sits_in_the_data_directory(self, tmp_path):
        from core.services import _battery_config
        cfg = _battery_config({}, data_path=tmp_path)
        assert cfg.sentinel_path == tmp_path / "battery-shutdown-request.json"

    def test_a_broken_curve_falls_back_rather_than_refusing_to_boot(self):
        """설정 오타로 로봇이 안 뜨는 것보다 스팬으로 도는 편이 낫다."""
        from core.services import _battery_config
        cfg = _battery_config({
            "battery_full_voltage": 8.4, "battery_empty_voltage": 6.4,
            "battery_curve": [[8.4, 100]],          # 점이 하나뿐 — 무효
        }, data_path=None)
        assert cfg.curve.percent(7.4) == pytest.approx(50.0)


# --- LED 중재 (설계 §"표시 권한" 우선순위 표) ----------------------------------

class TestResolveLed:
    def _alert(self, clock, voltage, samples):
        monitor = make_monitor(clock, enter_samples=3)
        feed(monitor, clock, voltage, samples)
        return monitor.led_alert

    def test_nothing_to_show_clears(self):
        from core_features.power.battery import resolve_led
        assert resolve_led(None, info_visible=False,
                           gauge_percent=80.0, now=0.0).command == "clear"

    def test_gauge_shows_only_inside_the_info_window(self):
        from core_features.power.battery import resolve_led
        closed = resolve_led(None, info_visible=False, gauge_percent=80.0, now=0.0)
        open_ = resolve_led(None, info_visible=True, gauge_percent=80.0, now=0.0)
        assert closed.command == "clear"
        assert open_.command == "fill"
        assert (open_.r, open_.g, open_.b) == (0, 60, 0)          # 60% 이상 녹색

    def test_gauge_bands_at_their_boundaries(self):
        from core_features.power.battery import resolve_led
        def rgb(percent):
            c = resolve_led(None, info_visible=True, gauge_percent=percent, now=0.0)
            return (c.r, c.g, c.b)
        assert rgb(100.0) == (0, 60, 0)
        assert rgb(60.0) == (0, 60, 0)
        assert rgb(59.9) == (60, 40, 0)
        assert rgb(30.0) == (60, 40, 0)
        assert rgb(29.9) == (60, 0, 0)
        assert rgb(0.0) == (60, 0, 0)

    def test_an_unknown_gauge_percent_clears_rather_than_guessing(self):
        from core_features.power.battery import resolve_led
        assert resolve_led(None, info_visible=True,
                           gauge_percent=None, now=0.0).command == "clear"

    def test_a_solid_alert_outranks_the_gauge(self, clock):
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 7.42, 3)                       # WARNING, 상시
        command = resolve_led(alert, info_visible=True, gauge_percent=80.0, now=0.0)
        assert command.command == "fill"
        assert (command.r, command.g, command.b) == (30, 20, 0)   # 게이지 녹색이 아니다

    def test_the_alert_survives_the_info_window_closing(self, clock):
        """이 스펙이 존재하는 이유 — 아무도 앞에 없어도 경보는 계속 보여야 한다."""
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 7.42, 3)
        command = resolve_led(alert, info_visible=False, gauge_percent=80.0, now=0.0)
        assert command.command == "fill"
        assert (command.r, command.g, command.b) == (30, 20, 0)

    def test_a_blinking_alert_alternates_with_the_clock(self, clock):
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 7.32, 6)                       # CRITICAL, 1 Hz
        assert resolve_led(alert, False, None, now=0.0).command == "fill"
        assert resolve_led(alert, False, None, now=0.6).command == "clear"
        assert resolve_led(alert, False, None, now=1.1).command == "fill"

    def test_a_blinking_alert_never_falls_back_to_the_gauge_when_dark(self, clock):
        """어두운 국면에 게이지가 비집고 들어오면 깜빡임이 색 교대로 보인다."""
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 7.32, 6)
        dark = resolve_led(alert, info_visible=True, gauge_percent=80.0, now=0.6)
        assert dark.command == "clear"

    def test_deep_blinks_twice_as_fast(self, clock):
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 6.40, 9)                       # DEEP, 2 Hz
        assert resolve_led(alert, False, None, now=0.0).command == "fill"
        assert resolve_led(alert, False, None, now=0.3).command == "clear"
        assert resolve_led(alert, False, None, now=0.55).command == "fill"

    def test_commands_compare_equal_so_the_bridge_can_skip_repeats(self, clock):
        """2 Hz 깜빡임이 5 Hz 서비스 호출 폭풍이 되지 않게 하는 전제."""
        from core_features.power.battery import resolve_led
        alert = self._alert(clock, 7.42, 3)
        assert (resolve_led(alert, False, None, 0.0)
                == resolve_led(alert, False, None, 9.0))


# --- 충전 중 deep 셧다운 억제 (D-27 인터록, 스펙 C) -----------------------------
#
# 4%에 도크에 도착한 로봇은 수 분간 deep 을 유지한다. 억제가 없으면 충전기 위에서
# 스스로 꺼지고, D-25 가 확인했듯 halt 된 Pi 5 는 전원 버튼과 RTC 알람 말고는
# 깨어날 방법이 없다. 충전에 성공하고 벽돌이 되는 셈이다.

class TestChargingSuppressesShutdown:
    def _armed_monitor(self, clock, tmp_path, **kwargs):
        monitor = make_monitor(
            clock, enter_samples=3, deep_dwell_s=60.0,
            sentinel_path=tmp_path / "battery-shutdown-request.json",
            shutdown_grace_s=120.0, **kwargs)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        return monitor

    def _sentinel(self, tmp_path):
        return tmp_path / "battery-shutdown-request.json"

    def test_charging_prevents_the_shutdown_from_arming(self, clock, tmp_path):
        monitor = make_monitor(
            clock, enter_samples=3, deep_dwell_s=60.0,
            sentinel_path=self._sentinel(tmp_path), shutdown_grace_s=120.0)
        monitor.set_charging(True)
        feed(monitor, clock, 6.40, 9, step_s=1.0)
        feed(monitor, clock, 6.40, 5, step_s=60.0)
        assert monitor.shutdown_armed is False
        assert not self._sentinel(tmp_path).exists()

    def test_charging_withdraws_an_already_written_sentinel(self, clock, tmp_path):
        monitor = self._armed_monitor(clock, tmp_path)
        assert self._sentinel(tmp_path).exists()
        monitor.set_charging(True)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        assert monitor.shutdown_armed is False
        assert not self._sentinel(tmp_path).exists()

    def test_losing_charging_re_arms_only_after_the_full_dwell(self, clock, tmp_path):
        """플러그가 빠졌다고 즉시 꺼지면 안 된다 — dwell 을 처음부터 다시 센다."""
        monitor = self._armed_monitor(clock, tmp_path)
        monitor.set_charging(True)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        assert monitor.shutdown_armed is False

        monitor.set_charging(False)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        assert monitor.shutdown_armed is False          # 아직 dwell 전
        feed(monitor, clock, 6.40, 1, step_s=60.0)
        assert monitor.shutdown_armed is True

    def test_the_level_itself_is_unchanged_while_charging(self, clock, tmp_path):
        """억제하는 것은 셧다운이지 판정이 아니다. 팩은 여전히 비어 있다."""
        from core_common.protocol.schemas import BatteryLevel
        monitor = self._armed_monitor(clock, tmp_path)
        monitor.set_charging(True)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        assert monitor.level is BatteryLevel.DEEP

    def test_the_deep_led_alert_is_unaffected(self, clock, tmp_path):
        """충전 중에도 로봇은 눈에 띄게 비어 있어야 한다."""
        monitor = self._armed_monitor(clock, tmp_path)
        monitor.set_charging(True)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        alert = monitor.led_alert
        assert alert is not None
        assert alert.blink_hz == pytest.approx(2.0)

    def test_status_reports_the_suppression(self, clock, tmp_path):
        monitor = self._armed_monitor(clock, tmp_path)
        monitor.set_charging(True)
        clock.advance(1.0)
        monitor.on_voltage(6.40)
        status = monitor.status()
        assert status.charging is True
        assert status.shutdown_armed is False

    def test_charging_defaults_to_false(self, clock):
        """아무도 말해주지 않으면 충전 중이 아니다 — 억제는 명시적이어야 한다."""
        monitor = make_monitor(clock)
        assert monitor.status().charging is False
