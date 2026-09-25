"""PWR-001~004 절전/근접 웨이크 단위 테스트 — 주입 클럭 기반 순수 로직."""

import math
import tempfile
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from core_api_web.api.app import create_app
from core_common.profile import RobotProfile, robot_config_dir
from core.services import CoreServices, _power_config

from core_features.power.manager import (
    LidarPolicy,
    PowerConfig,
    PowerManager,
    PresenceConfig,
    PresenceDetector,
)
from core_events.events.bus import EventBus
from core_common.protocol.schemas import PowerMode, PresenceState, RobotMode
from core_features.state.manager import StateManager


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


@pytest.fixture
def config():
    return PowerConfig(
        idle_after_s=60.0,
        standby_after_s=300.0,
        info_hold_s=15.0,
        presence=PresenceConfig(
            near_m=0.25, contact_m=0.05, hysteresis_m=0.10,
            detect_samples=2, release_samples=3,
            min_valid_m=0.02, max_valid_m=3.0,
        ),
    )


@pytest.fixture
def manager(config, clock):
    return PowerManager(config, clock=clock)


class TestPresenceDetector:
    def test_requires_consecutive_samples_to_detect(self, config):
        det = PresenceDetector(config.presence)
        assert det.update(0.20) == PresenceState.NONE      # 1 표본 — 아직 아님
        assert det.update(0.20) == PresenceState.NEAR      # 2 표본 — 검출

    def test_single_stray_echo_does_not_detect(self, config):
        det = PresenceDetector(config.presence)
        det.update(0.20)
        det.update(1.50)                                   # 멀어짐 — 카운터 리셋
        assert det.update(0.20) == PresenceState.NONE

    def test_contact_requires_its_own_debounce(self, config):
        det = PresenceDetector(config.presence)
        det.update(0.04)
        assert det.update(0.04) == PresenceState.CONTACT

    def test_near_escalates_to_contact(self, config):
        det = PresenceDetector(config.presence)
        det.update(0.20)
        assert det.update(0.20) == PresenceState.NEAR
        det.update(0.03)
        assert det.update(0.03) == PresenceState.CONTACT

    def test_release_needs_hysteresis_and_samples(self, config):
        det = PresenceDetector(config.presence)
        det.update(0.20)
        assert det.update(0.20) == PresenceState.NEAR
        # 히스테리시스 대역(0.25~0.35) 안에서는 유지된다
        for _ in range(5):
            assert det.update(0.30) == PresenceState.NEAR
        # 대역 밖 표본이 release_samples 만큼 연속되어야 해제된다
        assert det.update(0.40) == PresenceState.NEAR
        assert det.update(0.40) == PresenceState.NEAR
        assert det.update(0.40) == PresenceState.NONE

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1.0, 0.0, 5.0])
    def test_invalid_samples_are_discarded(self, config, bad):
        det = PresenceDetector(config.presence)
        det.update(0.20)
        det.update(bad)                                    # 무시 — 카운터 보존
        assert det.update(0.20) == PresenceState.NEAR

    def test_invalid_sample_does_not_release(self, config):
        det = PresenceDetector(config.presence)
        det.update(0.20)
        det.update(0.20)
        for _ in range(5):
            det.update(float("nan"))
        assert det.state == PresenceState.NEAR


class TestPowerModeMachine:
    def test_starts_active(self, manager):
        assert manager.mode == PowerMode.ACTIVE
        assert manager.sample_rate_hz == 20.0

    def test_idle_then_standby_by_dwell(self, manager, clock):
        clock.advance(59.0)
        manager.tick()
        assert manager.mode == PowerMode.ACTIVE

        clock.advance(2.0)                                 # 61 s
        manager.tick()
        assert manager.mode == PowerMode.IDLE
        assert manager.sample_rate_hz == 5.0

        clock.advance(240.0)                               # 301 s
        manager.tick()
        assert manager.mode == PowerMode.STANDBY
        assert manager.sample_rate_hz == 2.0

    def test_activity_returns_to_active(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        assert manager.mode == PowerMode.STANDBY

        manager.on_activity("cmd_vel")
        assert manager.mode == PowerMode.ACTIVE
        assert manager.sample_rate_hz == 20.0

    def test_activity_does_not_open_info_window(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_activity("cmd_vel")
        assert manager.info_visible() is False

    def test_disabled_config_pins_active(self, clock):
        mgr = PowerManager(PowerConfig(enabled=False), clock=clock)
        clock.advance(10_000.0)
        mgr.tick()
        assert mgr.mode == PowerMode.ACTIVE
        assert mgr.sample_rate_hz == 20.0


class TestWake:
    def test_proximity_wakes_and_opens_info_window(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        assert manager.mode == PowerMode.STANDBY

        manager.on_range(0.20)
        manager.on_range(0.20)
        assert manager.mode == PowerMode.ACTIVE
        assert manager.presence == PresenceState.NEAR
        assert manager.last_wake_reason == "proximity"
        assert manager.info_visible() is True

    def test_contact_reports_its_own_reason(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.03)
        manager.on_range(0.03)
        assert manager.last_wake_reason == "contact"

    def test_info_window_expires_and_idle_timer_resumes(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.20)
        manager.on_range(0.20)
        assert manager.info_visible() is True

        clock.advance(16.0)
        manager.on_range(1.50)                             # 사람이 떠남
        manager.on_range(1.50)
        manager.on_range(1.50)
        manager.tick()
        assert manager.info_visible() is False
        assert manager.presence == PresenceState.NONE

    def test_sustained_presence_extends_info_window(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.20)
        manager.on_range(0.20)

        clock.advance(10.0)
        manager.on_range(0.20)                             # 계속 앞에 있음
        clock.advance(10.0)
        assert manager.info_visible() is True              # 연장되어 아직 열림

    def test_api_wake(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.wake("api")
        assert manager.mode == PowerMode.ACTIVE
        assert manager.last_wake_reason == "api"
        assert manager.info_visible() is True

    def test_battery_alert_wakes(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_battery_alert("critical")
        assert manager.mode == PowerMode.ACTIVE
        assert manager.last_wake_reason == "battery"

    def test_battery_ok_does_not_wake(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_battery_alert("ok")
        assert manager.mode == PowerMode.STANDBY

    def test_range_out_of_band_never_wakes(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        for _ in range(10):
            manager.on_range(1.20)
        assert manager.mode == PowerMode.STANDBY
        assert manager.info_visible() is False


class TestSampleRateMapping:
    @pytest.mark.parametrize("dwell,expected", [(0.0, 20.0), (61.0, 5.0), (301.0, 2.0)])
    def test_rate_follows_mode(self, manager, clock, dwell, expected):
        clock.advance(dwell)
        manager.tick()
        assert manager.sample_rate_hz == expected

    def test_rate_is_finite_and_positive_in_every_mode(self, manager, clock):
        for dwell in (0.0, 61.0, 301.0):
            clock.advance(dwell)
            manager.tick()
            assert math.isfinite(manager.sample_rate_hz)
            assert manager.sample_rate_hz > 0.0


class TestEvents:
    @pytest.fixture
    def bus(self):
        return EventBus("rosy_01", buffer_size=64)

    @pytest.fixture
    def manager(self, config, clock, bus):
        return PowerManager(config, events=bus, clock=clock)

    @staticmethod
    def _types(bus):
        return [e.type for e in bus.history(limit=100)]

    def test_mode_change_emits_once(self, manager, clock, bus):
        clock.advance(61.0)
        manager.tick()
        manager.tick()
        manager.tick()
        assert self._types(bus).count("power.mode_changed") == 1

    def test_mode_change_carries_from_to_and_rate(self, manager, clock, bus):
        clock.advance(61.0)
        manager.tick()
        event = bus.history(limit=100)[-1]
        assert event.data["from"] == "ACTIVE"
        assert event.data["to"] == "IDLE"
        assert event.data["sample_rate_hz"] == 5.0

    def test_presence_detected_and_cleared(self, manager, clock, bus):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.20)
        manager.on_range(0.20)
        assert "presence.detected" in self._types(bus)
        assert "power.wake" in self._types(bus)

        for _ in range(3):
            manager.on_range(1.50)
        assert "presence.cleared" in self._types(bus)

    def test_presence_does_not_repeat_while_held(self, manager, clock, bus):
        clock.advance(400.0)
        manager.tick()
        for _ in range(10):
            manager.on_range(0.20)
        assert self._types(bus).count("presence.detected") == 1

    def test_escalation_emits_second_detection(self, manager, clock, bus):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.20)
        manager.on_range(0.20)
        manager.on_range(0.03)
        manager.on_range(0.03)
        assert self._types(bus).count("presence.detected") == 2


class TestSafetyInterlocks:
    def test_non_idle_robot_mode_blocks_standby(self, manager, clock):
        manager.on_robot_mode(RobotMode.NAVIGATION)
        clock.advance(1000.0)
        manager.tick()
        assert manager.mode == PowerMode.ACTIVE

    def test_returning_to_idle_releases_the_hold(self, manager, clock):
        manager.on_robot_mode(RobotMode.NAVIGATION)
        clock.advance(1000.0)
        manager.tick()
        manager.on_robot_mode(RobotMode.IDLE)
        clock.advance(400.0)
        manager.tick()
        assert manager.mode == PowerMode.STANDBY

    def test_emergency_mode_keeps_display_active(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        assert manager.mode == PowerMode.STANDBY
        manager.on_robot_mode(RobotMode.EMERGENCY)
        assert manager.mode == PowerMode.ACTIVE

    def test_forced_standby_via_request_mode(self, manager, clock):
        manager.request_mode(PowerMode.STANDBY, source="api")
        assert manager.mode == PowerMode.STANDBY

    def test_forced_standby_is_overridden_by_activity(self, manager):
        manager.request_mode(PowerMode.STANDBY, source="api")
        manager.on_activity("cmd_vel")
        assert manager.mode == PowerMode.ACTIVE

    def test_forced_active_via_request_mode(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.request_mode(PowerMode.ACTIVE, source="api")
        assert manager.mode == PowerMode.ACTIVE
        assert manager.info_visible() is True


class TestStatusSnapshot:
    def test_status_reports_full_shape(self, manager, clock):
        clock.advance(400.0)
        manager.tick()
        manager.on_range(0.20)
        manager.on_range(0.20)
        status = manager.status()
        assert status.mode == PowerMode.ACTIVE
        assert status.presence == PresenceState.NEAR
        assert status.info_visible is True
        assert status.sample_rate_hz == 20.0
        assert status.last_wake_reason == "proximity"
        assert status.idle_seconds == pytest.approx(0.0)

    def test_state_manager_carries_power_status(self, manager, clock):
        sm = StateManager("rosy_01")
        assert sm.snapshot().power.mode == PowerMode.ACTIVE

        clock.advance(400.0)
        manager.tick()
        sm.set_power(manager.status())
        snapshot = sm.snapshot()
        assert snapshot.power.mode == PowerMode.STANDBY
        assert snapshot.power.sample_rate_hz == 2.0


class TestLidarStandby:
    """PWR-005 STANDBY LiDAR 모터 정지 — 정책 계층은 의도만 선언한다."""

    @pytest.fixture
    def bus(self):
        return EventBus("rosy_01", buffer_size=64)

    @pytest.fixture
    def lidar_config(self, config):
        config.lidar = LidarPolicy(standby_stop=True, spinup_s=2.0)
        return config

    @pytest.fixture
    def lidar_manager(self, lidar_config, clock, bus):
        return PowerManager(lidar_config, events=bus, clock=clock)

    @staticmethod
    def _to_standby(manager, clock):
        clock.advance(400.0)
        manager.tick()

    # --- 기본값: 비활성 ---------------------------------------------------

    def test_default_policy_leaves_lidar_spinning(self, manager, clock):
        """standby_stop 기본값은 false — 기존 동작을 그대로 보존한다."""
        self._to_standby(manager, clock)
        assert manager.mode == PowerMode.STANDBY
        assert manager.lidar_spinning is True
        assert manager.lidar_ready() is True

    def test_disabled_power_keeps_lidar_spinning(self, lidar_config, clock):
        lidar_config.enabled = False
        manager = PowerManager(lidar_config, clock=clock)
        self._to_standby(manager, clock)
        assert manager.lidar_spinning is True

    # --- 모드별 의도 ------------------------------------------------------

    def test_standby_stops_lidar(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        assert lidar_manager.lidar_spinning is False

    def test_idle_keeps_lidar_spinning(self, lidar_manager, clock):
        clock.advance(61.0)
        lidar_manager.tick()
        assert lidar_manager.mode == PowerMode.IDLE
        assert lidar_manager.lidar_spinning is True

    def test_stopped_lidar_is_never_ready(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        assert lidar_manager.lidar_ready() is False

    # --- 복귀와 스핀업 ----------------------------------------------------

    def test_wake_restarts_lidar_after_spinup(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        lidar_manager.wake("api")
        assert lidar_manager.lidar_spinning is True
        assert lidar_manager.lidar_ready() is False        # 아직 스핀업 중

        clock.advance(1.9)
        assert lidar_manager.lidar_ready() is False
        clock.advance(0.2)
        assert lidar_manager.lidar_ready() is True

    def test_activity_restarts_lidar(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        lidar_manager.on_activity("cmd_vel")
        assert lidar_manager.lidar_spinning is True

    def test_proximity_restarts_lidar(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        lidar_manager.on_range(0.20)
        lidar_manager.on_range(0.20)
        assert lidar_manager.lidar_spinning is True

    def test_non_idle_robot_mode_restarts_lidar(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        lidar_manager.on_robot_mode(RobotMode.NAVIGATION)
        assert lidar_manager.lidar_spinning is True

    def test_battery_alert_restarts_lidar(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        lidar_manager.on_battery_alert("critical")
        assert lidar_manager.lidar_spinning is True

    def test_spinup_clock_does_not_restart_while_already_spinning(
            self, lidar_manager, clock):
        """이미 회전 중이면 재기동 취급하지 않는다 — ready가 되돌아가지 않는다."""
        self._to_standby(lidar_manager, clock)
        lidar_manager.wake("api")
        clock.advance(3.0)
        assert lidar_manager.lidar_ready() is True

        lidar_manager.on_activity("cmd_vel")
        assert lidar_manager.lidar_ready() is True

    def test_startup_lidar_is_ready_without_spinup(self, lidar_manager):
        """core 기동 시점에 드라이버는 이미 돌고 있다 — 스핀업 페널티 없음."""
        assert lidar_manager.lidar_spinning is True
        assert lidar_manager.lidar_ready() is True

    # --- 이벤트와 상태 ----------------------------------------------------

    def test_lidar_change_emits_once_per_transition(self, lidar_manager, clock, bus):
        self._to_standby(lidar_manager, clock)
        lidar_manager.tick()
        lidar_manager.tick()
        types = [e.type for e in bus.history(limit=100)]
        assert types.count("power.lidar_changed") == 1

        event = [e for e in bus.history(limit=100) if e.type == "power.lidar_changed"][-1]
        assert event.data["spinning"] is False

    def test_lidar_restart_emits_change(self, lidar_manager, clock, bus):
        self._to_standby(lidar_manager, clock)
        lidar_manager.wake("api")
        events = [e for e in bus.history(limit=100) if e.type == "power.lidar_changed"]
        assert [e.data["spinning"] for e in events] == [False, True]

    def test_default_policy_emits_no_lidar_events(self, manager, clock, config):
        bus = EventBus("rosy_01", buffer_size=64)
        quiet = PowerManager(config, events=bus, clock=clock)
        self._to_standby(quiet, clock)
        assert "power.lidar_changed" not in [e.type for e in bus.history(limit=100)]

    def test_status_carries_lidar_fields(self, lidar_manager, clock):
        self._to_standby(lidar_manager, clock)
        status = lidar_manager.status()
        assert status.lidar_spinning is False
        assert status.lidar_ready is False

        lidar_manager.wake("api")
        clock.advance(2.5)
        status = lidar_manager.status()
        assert status.lidar_spinning is True
        assert status.lidar_ready is True

    def test_state_manager_carries_lidar_status(self, lidar_manager, clock):
        sm = StateManager("rosy_01")
        self._to_standby(lidar_manager, clock)
        sm.set_power(lidar_manager.status())
        assert sm.snapshot().power.lidar_spinning is False


CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture
def client():
    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    # D-193 7: the dev tokens left the defaults; tests opt in like ROSY_DEV_AUTH=1.
    config.update(yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    svc = CoreServices.build(config, profile, caps, Path(tempfile.mkdtemp()) / "waypoints.json")
    return TestClient(create_app(config, svc)), svc


class TestLidarConfigPlumbing:
    """rosy_default.yaml의 power.lidar 블록이 PowerConfig까지 도달하는가."""

    def test_yaml_block_maps_to_policy(self):
        raw = {"lidar": {"standby_stop": True, "spinup_s": 3.5}}
        cfg = _power_config(raw)
        assert cfg.lidar.standby_stop is True
        assert cfg.lidar.spinup_s == 3.5

    def test_missing_block_keeps_safe_defaults(self):
        cfg = _power_config({})
        assert cfg.lidar.standby_stop is False
        assert cfg.lidar.spinup_s == 2.0

    def test_shipped_default_config_disables_standby_stop(self):
        raw = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
        cfg = _power_config(raw.get("power", {}))
        assert cfg.lidar.standby_stop is False       # 벤치 승인 전까지 비활성
        assert cfg.lidar.spinup_s > 0.0


ADMIN = {"Authorization": "Bearer rosy-dev-admin"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


class TestPowerApi:
    def test_get_power_requires_auth(self, client):
        api, _ = client
        assert api.get("/api/v1/power").status_code == 401

    def test_get_power_reports_status(self, client):
        api, _ = client
        body = api.get("/api/v1/power", headers=VIEWER).json()
        assert body["mode"] == "ACTIVE"
        assert body["presence"] == "none"
        assert body["sample_rate_hz"] == 20.0

    def test_viewer_cannot_wake(self, client):
        api, _ = client
        assert api.post("/api/v1/power/wake", headers=VIEWER).status_code == 403

    def test_operator_can_wake(self, client):
        api, svc = client
        svc.power.request_mode(PowerMode.STANDBY, source="test")
        assert svc.power.mode == PowerMode.STANDBY

        body = api.post("/api/v1/power/wake", headers=ADMIN).json()
        assert body["mode"] == "ACTIVE"
        assert body["info_visible"] is True
        assert svc.power.last_wake_reason == "api"

    def test_force_standby(self, client):
        api, svc = client
        body = api.post("/api/v1/power/mode", json={"mode": "STANDBY"}, headers=ADMIN).json()
        assert body["mode"] == "STANDBY"
        assert svc.power.sample_rate_hz == 2.0

    def test_unknown_mode_is_rejected(self, client):
        api, _ = client
        response = api.post("/api/v1/power/mode", json={"mode": "HIBERNATE"}, headers=ADMIN)
        assert response.status_code == 400          # API Ref §5 VALIDATION_ERROR
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_state_snapshot_carries_power(self, client):
        api, _ = client
        body = api.get("/api/v1/robot/state", headers=VIEWER).json()
        assert body["power"]["mode"] == "ACTIVE"
