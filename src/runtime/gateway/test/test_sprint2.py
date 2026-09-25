"""P1 2차 스프린트 단위 테스트 — 센서 스토어·진단 수집기·SLAM 세션·메트릭 API."""

import time

import pytest

from core_api_web.api.app import create_app
from core_features.diagnostics.collector import (
    DiagnosticsCollector,
    disk_provider,
    topic_freshness_provider,
    worst,
)
from core_features.navigation.manager import NavigationManager
from core_common.profile import RobotProfile, robot_config_dir
from core_common.protocol.schemas import HealthState
from core.services import CoreServices
from core_features.state.manager import StateManager
from core_features.waypoints.manager import WaypointManager

from core_events.events.bus import EventBus
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits

import yaml
from pathlib import Path
from fastapi.testclient import TestClient


CONFIG_DIR = Path(__file__).parent.parent / "config"


@pytest.fixture
def bus():
    return EventBus("rosy_01", buffer_size=8)


@pytest.fixture
def safety(bus):
    return SafetyManager(
        SpeedLimits(max_linear=0.20, max_angular=0.80, manual_linear=0.15, manual_angular=0.60),
        BatteryPolicy(), events=bus,
    )


class TestSensorStore:
    def test_set_get_sensors(self):
        sm = StateManager("rosy_01")
        assert sm.get_sensor("lidar") is None
        sm.set_sensor("lidar", {"num_ranges": 360, "ranges": [1.0]})
        assert sm.get_sensor("lidar")["num_ranges"] == 360
        all_sensors = sm.get_sensors()
        assert "lidar" in all_sensors


class TestDiagnostics:
    def test_collector_ok_and_exception(self):
        dc = DiagnosticsCollector()
        dc.register("ok", lambda: HealthState.OK)
        dc.register("boom", lambda: 1 / 0)
        results = dc.collect()
        assert results["ok"] == HealthState.OK
        assert results["boom"] == HealthState.ERROR          # provider 예외 → ERROR
        assert dc.summary_health() == HealthState.ERROR

    def test_worst_ordering(self):
        assert worst([HealthState.OK, HealthState.WARNING]) == HealthState.WARNING
        assert worst([]) == HealthState.UNKNOWN

    def test_freshness_provider(self):
        last = time.monotonic()
        fresh = topic_freshness_provider(lambda: last, stale_s=60.0)
        assert fresh() == HealthState.OK
        stale = topic_freshness_provider(lambda: last - 10.0, stale_s=2.0)
        assert stale() == HealthState.ERROR
        unknown = topic_freshness_provider(lambda: 0.0)
        assert unknown() == HealthState.UNKNOWN

    def test_disk_provider_real(self):
        assert disk_provider("/")() in list(HealthState)      # 실 / 동작


class TestSlamSession:
    def _nav(self, tmp_path, bus, safety):
        state = StateManager("rosy_01")
        wm = WaypointManager(tmp_path / "wp.json")
        nav = NavigationManager(bus, state, wm, safety)
        nav.executor = FakeExecutor()
        return nav, state

    def test_session_lifecycle(self, tmp_path, bus, safety):
        nav, state = self._nav(tmp_path, bus, safety)
        nav.start_mapping()
        assert nav.mapping_active
        with pytest.raises(Exception) as e:                    # 세션 중 Goal 거부 (NAV-005)
            nav.goal(nav.resolve_goal(x=1.0, y=1.0))
        assert e.value.code == "MAPPING_ACTIVE"
        map_id = nav.save_map("warehouse")
        assert map_id == "warehouse:deadbeef"                  # FakeExecutor 발급 map_id
        assert state.map_id == map_id                           # MAP-001 보고 갱신
        assert "map.saved" in [ev.type for ev in bus.history()]
        nav.stop_mapping()
        assert not nav.mapping_active
        with pytest.raises(Exception) as e:                     # 세션 없는 save 거부
            nav.save_map("again")
        assert e.value.code == "VALIDATION_ERROR"

    def test_nav_active_blocks_mapping(self, tmp_path, bus, safety):
        nav, _ = self._nav(tmp_path, bus, safety)
        nav.goal(nav.resolve_goal(x=1.0, y=1.0))
        nav.on_goal_accepted()
        with pytest.raises(Exception) as e:
            nav.start_mapping()
        assert e.value.code == "NAVIGATION_ACTIVE"


class FakeExecutor:
    def send_goal(self, spec):
        pass

    def cancel_goal(self):
        pass

    def send_initial_pose(self, *a):
        pass

    def save_map(self, name):
        return f"{name}:deadbeef"


@pytest.fixture
def client(tmp_path):
    config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
    # D-193 7: the dev tokens left the defaults; tests opt in like ROSY_DEV_AUTH=1.
    config.update(yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
    robot_dir = robot_config_dir("pinky_pro")
    profile = RobotProfile.load(robot_dir / "profile.yaml")
    caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
    services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
    services.nav.executor = FakeExecutor()
    return TestClient(create_app(config, services)), services


OPERATOR = {"Authorization": "Bearer rosy-dev-operator"}
VIEWER = {"Authorization": "Bearer rosy-dev-viewer"}


class TestNewApi:
    def test_sensors_endpoints(self, client):
        tc, svc = client
        svc.state.set_sensor("lidar", {"num_ranges": 10})
        assert tc.get("/api/v1/sensors", headers=VIEWER).json()["sensors"]["lidar"]["num_ranges"] == 10
        assert tc.get("/api/v1/sensors/lidar", headers=VIEWER).status_code == 200
        missing = tc.get("/api/v1/sensors/ghost", headers=VIEWER)
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "NOT_FOUND"

    def test_slam_flow(self, client):
        tc, svc = client
        assert tc.post("/api/v1/slam/start", headers=OPERATOR).json()["mapping"] is True
        goal = tc.post("/api/v1/navigation/goal", json={"x": 1, "y": 1}, headers=OPERATOR)
        assert goal.status_code == 409 and goal.json()["error"]["code"] == "MAPPING_ACTIVE"
        saved = tc.post("/api/v1/slam/save", json={"name": "wh"}, headers=OPERATOR).json()
        assert saved["map_id"] == "wh:deadbeef"
        assert svc.state.map_id == "wh:deadbeef"
        assert tc.post("/api/v1/slam/stop", headers=OPERATOR).json()["mapping"] is False

    @pytest.mark.parametrize("name", ["../escape", "nested/map", r"nested\\map"])
    def test_slam_save_rejects_path_like_names(self, client, name):
        tc, _svc = client
        assert tc.post("/api/v1/slam/start", headers=OPERATOR).status_code == 200

        response = tc.post(
            "/api/v1/slam/save", json={"name": name}, headers=OPERATOR
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "VALIDATION_ERROR"

    def test_metrics_prometheus(self, client):
        tc, _ = client
        r = tc.get("/metrics")
        assert r.status_code == 200
        assert "rosy_uptime_seconds" in r.text
        assert "rosy_events_published_total" in r.text
        assert "text/plain" in r.headers["content-type"]


class TestSlamCapabilityGate:
    """CAP-003: capabilities 가 slam: false 면 ROS 작업 전에 501 로 거절한다.

    pi5-lite 배포는 slam: false 를 마운트하는데, 게이트가 없으면 API 가
    slam 을 지원한다고 광고해 놓고 저장 시점에야 실패한다.
    """

    @pytest.fixture
    def no_slam(self, tmp_path):
        config = yaml.safe_load((CONFIG_DIR / "rosy_default.yaml").read_text(encoding="utf-8"))
        # D-193 7: the dev tokens left the defaults; tests opt in like ROSY_DEV_AUTH=1.
        config.update(yaml.safe_load((CONFIG_DIR / "rosy_dev_auth.yaml").read_text(encoding="utf-8")))
        robot_dir = robot_config_dir("pinky_pro")
        profile = RobotProfile.load(robot_dir / "profile.yaml")
        caps = yaml.safe_load((robot_dir / "capabilities.yaml").read_text(encoding="utf-8"))
        caps["slam"] = False                      # hardware overlay (and the pi5-lite alias)
        services = CoreServices.build(config, profile, caps, tmp_path / "wp.json")
        services.nav.executor = FakeExecutor()
        return TestClient(create_app(config, services)), services

    @pytest.mark.parametrize("path,body", [
        ("/api/v1/slam/start", None),
        ("/api/v1/slam/stop", None),
        ("/api/v1/slam/save", {"name": "m"}),
        ("/api/v1/slam/reset", None),
    ])
    def test_route_rejected_without_capability(self, no_slam, path, body):
        tc, _ = no_slam
        response = tc.post(path, json=body, headers=OPERATOR)
        assert response.status_code == 501
        assert response.json()["error"]["code"] == "CAPABILITY_NOT_SUPPORTED"

    def test_rejection_precedes_any_mapping_work(self, no_slam):
        """게이트가 앞단이어야 한다 — 매핑 세션이 열리지 않는다."""
        tc, svc = no_slam
        tc.post("/api/v1/slam/start", headers=OPERATOR)
        assert svc.nav.mapping_active is False

    def test_capability_declaration_matches_behavior(self, no_slam):
        """광고와 동작이 일치해야 한다 — 이번 불일치의 핵심."""
        tc, _ = no_slam
        caps = tc.get("/api/v1/system/capabilities", headers=OPERATOR).json()
        assert caps["slam"] is False
        assert tc.post("/api/v1/slam/start", headers=OPERATOR).status_code == 501

    def test_enabled_capability_still_works(self, client):
        """slam: true 인 기본 구성은 종전대로 동작한다 (회귀 방지)."""
        tc, svc = client
        assert tc.post("/api/v1/slam/start", headers=OPERATOR).status_code == 200
        assert svc.nav.mapping_active is True
