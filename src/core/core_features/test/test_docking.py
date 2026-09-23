"""DNC-001~003 도킹 단위 테스트 — 주입 클럭 기반 순수 로직.

설계: docs/plans/2026-09-02-docking-station-design.md
"""

import json
import math

import pytest

from core_features.docking.database import (
    DockDatabase,
    DockError,
    DockInstance,
    DockType,
)


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


def a_dock(**kwargs) -> DockInstance:
    options = dict(
        id="dock_1",
        type="rosy_v1",
        x=2.5, y=1.8, yaw=0.0,
        map_id="warehouse_a",
        agent_url="http://10.0.0.50",
    )
    options.update(kwargs)
    return DockInstance(**options)


# --- DockType: 기종 (인스턴스와 분리) -----------------------------------------

class TestDockType:
    def test_a_type_carries_the_detector_and_approach_configuration(self):
        dock_type = DockType(name="rosy_v1", detector="simulated",
                             staging_offset_m=0.7, docking_threshold_m=0.05,
                             max_retries=3)
        assert dock_type.detector == "simulated"
        assert dock_type.staging_offset_m == pytest.approx(0.7)
        assert dock_type.max_retries == 3

    def test_the_staging_offset_must_be_positive(self):
        """스테이징은 도크 *앞* 이다. 0이나 음수면 도크 안이나 뒤를 가리킨다."""
        with pytest.raises(ValueError):
            DockType(name="bad", detector="simulated", staging_offset_m=0.0)
        with pytest.raises(ValueError):
            DockType(name="bad", detector="simulated", staging_offset_m=-0.5)

    def test_two_instances_share_one_type(self):
        """설계 §"1:1 구현, 스키마는 풀" — 기종 하나에 도크 여럿."""
        db = DockDatabase.empty()
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock(id="dock_1"))
        db.add(a_dock(id="dock_2", x=9.0))
        assert db.type_of("dock_1") is db.type_of("dock_2")

    def test_a_type_without_tag_spec_cannot_drive_vision(self):
        """DNC-007: 태그 제원 없는 기종은 태그 검출기를 고를 수 없다."""
        dock_type = DockType(name="rosy_v1", detector="aruco")
        assert dock_type.tag_id is None
        assert dock_type.tag_size_m is None

    def test_a_type_carries_the_tag_contract(self):
        dock_type = DockType(name="rosy_v1", detector="aruco",
                             tag_family="DICT_4X4_50", tag_id=7, tag_size_m=0.10)
        assert dock_type.tag_family == "DICT_4X4_50"
        assert dock_type.tag_id == 7
        assert dock_type.tag_size_m == pytest.approx(0.10)

    def test_a_tag_size_must_be_positive_when_set(self):
        with pytest.raises(ValueError):
            DockType(name="bad", detector="aruco", tag_id=7, tag_size_m=0.0)
        with pytest.raises(ValueError):
            DockType(name="bad", detector="aruco", tag_id=-1, tag_size_m=0.10)


# --- DockInstance: 개체 --------------------------------------------------------

class TestDockInstance:
    def test_an_instance_carries_pose_map_and_agent_address(self):
        dock = a_dock()
        assert (dock.x, dock.y, dock.yaw) == (2.5, 1.8, 0.0)
        assert dock.map_id == "warehouse_a"
        assert dock.agent_url == "http://10.0.0.50"

    def test_the_staging_pose_is_derived_not_stored(self):
        """가르친 도크 포즈가 낡은 스테이징 포즈를 남기면 안 된다."""
        dock = a_dock(x=2.0, y=0.0, yaw=0.0)
        staging = dock.staging_pose(offset_m=0.7)
        # yaw=0 이면 도크는 +X를 향하고, 스테이징은 그 앞(−X 쪽 0.7 m)이다.
        assert staging.x == pytest.approx(1.3)
        assert staging.y == pytest.approx(0.0)
        # 스테이징에서 도크를 바라봐야 하므로 yaw 는 도크와 같다.
        assert staging.yaw == pytest.approx(0.0)

    def test_the_staging_pose_follows_the_dock_orientation(self):
        dock = a_dock(x=0.0, y=0.0, yaw=math.pi / 2)      # 도크가 +Y를 향한다
        staging = dock.staging_pose(offset_m=1.0)
        assert staging.x == pytest.approx(0.0, abs=1e-9)
        assert staging.y == pytest.approx(-1.0)

    def test_teaching_replaces_the_pose_and_the_staging_follows(self):
        dock = a_dock(x=2.0, y=0.0, yaw=0.0)
        assert dock.staging_pose(0.5).x == pytest.approx(1.5)
        dock = dock.taught_at(x=5.0, y=1.0, yaw=0.0, map_id="warehouse_a")
        assert dock.staging_pose(0.5).x == pytest.approx(4.5)
        assert dock.y == pytest.approx(1.0)

    def test_teaching_records_the_map_it_was_taught_on(self):
        dock = a_dock(map_id="warehouse_a").taught_at(
            x=1.0, y=1.0, yaw=0.0, map_id="warehouse_b")
        assert dock.map_id == "warehouse_b"

    def test_an_id_is_required(self):
        with pytest.raises(ValueError):
            a_dock(id="")


# --- 맵 일치 (MAP-002) ---------------------------------------------------------

class TestMapGuard:
    def test_a_dock_on_another_map_is_rejected(self):
        """resolve_goal 이 waypoint 를 거부하는 방식과 같아야 한다."""
        dock = a_dock(map_id="warehouse_a")
        with pytest.raises(DockError) as excinfo:
            dock.require_map("warehouse_b")
        assert excinfo.value.code == "MAP_MISMATCH"

    def test_a_matching_map_passes(self):
        a_dock(map_id="warehouse_a").require_map("warehouse_a")

    def test_a_dock_with_no_map_is_not_map_checked(self):
        """맵 없이 운용하는 구성(teleop 전용)을 막지 않는다."""
        a_dock(map_id=None).require_map("warehouse_a")

    def test_an_unknown_current_map_does_not_block(self):
        a_dock(map_id="warehouse_a").require_map(None)


# --- DockDatabase --------------------------------------------------------------

class TestDockDatabase:
    def test_it_is_keyed_by_id(self, tmp_path):
        db = DockDatabase.empty()
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock(id="dock_1"))
        assert db.get("dock_1").id == "dock_1"

    def test_an_unknown_id_raises_not_found(self):
        db = DockDatabase.empty()
        with pytest.raises(DockError) as excinfo:
            db.get("nope")
        assert excinfo.value.code == "NOT_FOUND"

    def test_a_duplicate_id_is_refused(self):
        db = DockDatabase.empty()
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock(id="dock_1"))
        with pytest.raises(DockError) as excinfo:
            db.add(a_dock(id="dock_1"))
        assert excinfo.value.code == "DOCK_EXISTS"

    def test_a_dock_of_an_unregistered_type_is_refused(self):
        """기종 없이 개체만 있으면 검출기를 고를 수 없다."""
        db = DockDatabase.empty()
        with pytest.raises(DockError) as excinfo:
            db.add(a_dock(type="ghost"))
        assert excinfo.value.code == "UNKNOWN_DOCK_TYPE"

    def test_it_round_trips_through_json(self, tmp_path):
        path = tmp_path / "docks.json"
        db = DockDatabase(path)
        db.add_type(DockType(name="rosy_v1", detector="simulated",
                             staging_offset_m=0.65))
        db.add(a_dock(id="dock_1"))
        db.add(a_dock(id="dock_2", x=9.0, agent_url="http://10.0.0.51"))

        reloaded = DockDatabase(path)
        assert {d.id for d in reloaded.list()} == {"dock_1", "dock_2"}
        assert reloaded.get("dock_2").agent_url == "http://10.0.0.51"
        assert reloaded.type_of("dock_1").staging_offset_m == pytest.approx(0.65)

    def test_the_file_is_human_readable_beside_waypoints(self, tmp_path):
        path = tmp_path / "docks.json"
        db = DockDatabase(path)
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock())
        document = json.loads(path.read_text(encoding="utf-8"))
        assert set(document) == {"dock_types", "docks"}

    def test_teaching_persists(self, tmp_path):
        path = tmp_path / "docks.json"
        db = DockDatabase(path)
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock(id="dock_1", x=2.0))
        db.teach("dock_1", x=7.0, y=3.0, yaw=1.57, map_id="warehouse_a")
        assert DockDatabase(path).get("dock_1").x == pytest.approx(7.0)

    def test_teaching_an_unknown_dock_raises(self, tmp_path):
        db = DockDatabase(tmp_path / "docks.json")
        with pytest.raises(DockError):
            db.teach("nope", x=0.0, y=0.0, yaw=0.0, map_id=None)

    def test_removing_a_dock_persists(self, tmp_path):
        path = tmp_path / "docks.json"
        db = DockDatabase(path)
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        db.add(a_dock(id="dock_1"))
        db.remove("dock_1")
        assert DockDatabase(path).list() == []

    def test_an_empty_store_loads_without_a_file(self, tmp_path):
        assert DockDatabase(tmp_path / "missing.json").list() == []

    def test_the_single_dock_shortcut_for_the_one_to_one_deployment(self, tmp_path):
        """구현은 1:1 이다 — "그 도크"를 이름 없이 물을 수 있어야 한다."""
        db = DockDatabase.empty()
        db.add_type(DockType(name="rosy_v1", detector="simulated"))
        assert db.only() is None
        db.add(a_dock(id="dock_1"))
        assert db.only().id == "dock_1"
        db.add(a_dock(id="dock_2"))
        assert db.only() is None            # 둘 이상이면 골라줄 수 없다


# --- 검출기 경계 (감지 방식은 스펙 B 뒤로 유보) --------------------------------

class TestDockObservation:
    def test_it_carries_a_relative_pose_and_a_timestamp(self):
        from core_features.docking.detector import DockObservation
        obs = DockObservation(x=0.42, y=-0.03, yaw=0.01, confidence=0.9, at=1000.0)
        assert (obs.x, obs.y) == (0.42, -0.03)
        assert obs.confidence == pytest.approx(0.9)
        assert obs.at == 1000.0

    def test_the_range_is_the_planar_distance_to_the_dock(self):
        from core_features.docking.detector import DockObservation
        obs = DockObservation(x=0.3, y=0.4, yaw=0.0, confidence=1.0, at=0.0)
        assert obs.range_m == pytest.approx(0.5)

    def test_confidence_is_bounded(self):
        from core_features.docking.detector import DockObservation
        with pytest.raises(ValueError):
            DockObservation(x=0.0, y=0.0, yaw=0.0, confidence=1.5, at=0.0)
        with pytest.raises(ValueError):
            DockObservation(x=0.0, y=0.0, yaw=0.0, confidence=-0.1, at=0.0)


class TestSimulatedDetector:
    def _detector(self, clock, **kwargs):
        from core_features.docking.detector import SimulatedDetector
        return SimulatedDetector(clock=clock, **kwargs)

    def test_it_reports_nothing_before_start(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0)])
        assert detector.relative_pose() is None

    def test_it_replays_the_script_after_start(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0), (0.3, 0.01, 0.0)])
        detector.start(a_dock())
        first = detector.relative_pose()
        assert first.x == pytest.approx(0.5)
        clock.advance(0.2)
        assert detector.relative_pose().x == pytest.approx(0.3)

    def test_the_last_scripted_pose_is_held(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0), (0.05, 0.0, 0.0)])
        detector.start(a_dock())
        for _ in range(5):
            clock.advance(0.2)
            observation = detector.relative_pose()
        assert observation.x == pytest.approx(0.05)

    def test_it_reports_nothing_after_stop(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0)])
        detector.start(a_dock())
        assert detector.relative_pose() is not None
        detector.stop()
        assert detector.relative_pose() is None

    def test_it_can_be_told_to_lose_the_dock(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0)])
        detector.start(a_dock())
        assert detector.relative_pose() is not None
        detector.lose()
        assert detector.relative_pose() is None

    def test_it_never_acquires_when_the_script_is_empty(self, clock):
        detector = self._detector(clock, script=[])
        detector.start(a_dock())
        assert detector.relative_pose() is None

    def test_a_stale_observation_is_not_returned_as_current(self, clock):
        """마지막 목격을 계속 돌려주는 검출기는 잃어버린 도크를 확신 있는
        오답으로 바꾼다."""
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0)],
                                  staleness_s=0.5)
        detector.start(a_dock())
        assert detector.relative_pose() is not None
        detector.freeze()                    # 새 표본이 끊긴 상황
        clock.advance(0.4)
        assert detector.relative_pose() is not None
        clock.advance(0.2)                   # 총 0.6s > staleness
        assert detector.relative_pose() is None

    def test_restarting_clears_the_previous_run(self, clock):
        detector = self._detector(clock, script=[(0.5, 0.0, 0.0), (0.3, 0.0, 0.0)])
        detector.start(a_dock())
        clock.advance(0.2)
        detector.relative_pose()
        detector.stop()
        detector.start(a_dock())
        assert detector.relative_pose().x == pytest.approx(0.5)

    def test_it_satisfies_the_detector_protocol(self, clock):
        from core_features.docking.detector import DockDetector
        assert isinstance(self._detector(clock, script=[]), DockDetector)


class TestSelectDetector:
    """DNC-007/D-138: `detector="aruco"` + 태그 제원 + provider + 프레임이 다
    있어야 실검출기로 간다. 하나라도 없으면 시뮬레이션(무관측)으로 떨어진다."""

    def _select(self, dock_type=None, **kwargs):
        from core_features.docking.detector import (
            SimulatedDetector,
            select_detector,
        )
        dock_type = dock_type or DockType(name="rosy_v1", detector="aruco",
                                          tag_id=7, tag_size_m=0.10)
        detector = select_detector(a_dock(), dock_type, **kwargs)
        return detector, SimulatedDetector

    def test_simulated_by_default(self):
        detector, SimulatedDetector = self._select()
        assert isinstance(detector, SimulatedDetector)

    def test_named_detector_without_tag_spec_stays_simulated(self):
        from control.sensor_provider import PROVIDER
        dock_type = DockType(name="rosy_v1", detector="aruco")
        detector, SimulatedDetector = self._select(
            dock_type, provider=PROVIDER, frame_source=lambda: None)
        assert isinstance(detector, SimulatedDetector)

    def test_simulated_name_ignores_a_full_aruco_stack(self):
        from control.sensor_provider import PROVIDER
        dock_type = DockType(name="rosy_v1", detector="simulated",
                             tag_id=7, tag_size_m=0.10)
        detector, SimulatedDetector = self._select(
            dock_type, provider=PROVIDER, frame_source=lambda: None)
        assert isinstance(detector, SimulatedDetector)

    def test_no_frames_means_no_vision_detector(self):
        from control.sensor_provider import PROVIDER
        detector, SimulatedDetector = self._select(provider=PROVIDER)
        assert isinstance(detector, SimulatedDetector)

    def test_a_broken_provider_falls_back_without_raising(self):
        from types import SimpleNamespace

        def broken(**kwargs):
            raise ImportError("no cv2 on this image")

        provider = SimpleNamespace(make_dock_detector=broken)
        detector, SimulatedDetector = self._select(
            provider=provider, frame_source=lambda: None)
        assert isinstance(detector, SimulatedDetector)

    def test_full_stack_selects_the_aruco_detector(self):
        cv2 = pytest.importorskip("cv2")
        import numpy as np
        from control.sensor_provider import PROVIDER

        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
        marker = (getattr(cv2.aruco, "generateImageMarker", None) or cv2.aruco.drawMarker)(dictionary, 7, 200)
        frame = np.full((480, 640, 3), 255, dtype=np.uint8)
        frame[140:340, 220:420] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
        camera = np.array([[600.0, 0.0, 320.0],
                           [0.0, 600.0, 240.0],
                           [0.0, 0.0, 1.0]])
        detector, SimulatedDetector = self._select(
            provider=PROVIDER, frame_source=lambda: frame,
            camera_matrix=camera, dist_coeffs=np.zeros(5))
        assert not isinstance(detector, SimulatedDetector)
        detector.start(a_dock())
        obs = detector.relative_pose()
        assert obs is not None
        assert obs.range_m == pytest.approx(0.30, abs=0.02)
        detector.stop()


# --- 도크 에이전트 클라이언트 --------------------------------------------------
#
# 도크가 밀어넣지 않고 로봇이 폴링한다. 도크는 어느 로봇이 오는지 모르고,
# 로봇은 자기가 갈 도크를 안다. 그리고 Fleet 이 죽어도 충전은 되어야 한다.

import json as _json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _StubDock:
    """도크 에이전트 대역. body/status/delay 를 테스트가 지정한다."""

    def __init__(self, body=None, status=200, delay_s=0.0, raw=None):
        self.body = body
        self.status = status
        self.delay_s = delay_s
        self.raw = raw
        self.requests = 0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                outer.requests += 1
                if outer.delay_s:
                    import time as _t
                    _t.sleep(outer.delay_s)
                payload = (outer.raw if outer.raw is not None
                           else _json.dumps(outer.body).encode())
                self.send_response(outer.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_port}"

    def __enter__(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._server.shutdown()
        self._server.server_close()


HEALTHY = {
    "dock_id": "dock_1",
    "firmware": "1.0.0",
    "output_enabled": True,
    "load_present": True,
    "charging": True,
    "current_a": 1.42,
    "output_voltage_v": 8.31,
    "faults": [],
}


def an_agent(url, **kwargs):
    from core_features.docking.agent import DockAgent
    return DockAgent(url, timeout_s=kwargs.pop("timeout_s", 1.0), **kwargs)


class TestDockAgentHappyPath:
    def test_it_reads_the_documented_fields(self):
        from core_features.docking.agent import DockReachability
        with _StubDock(HEALTHY) as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.OK
        assert status.answered is True
        assert status.charging is True
        assert status.load_present is True
        assert status.current_a == pytest.approx(1.42)
        assert status.output_voltage_v == pytest.approx(8.31)
        assert status.dock_id == "dock_1"
        assert status.faults == ()

    def test_a_fault_list_comes_through(self):
        body = dict(HEALTHY, charging=False, current_a=0.0,
                    faults=["overtemp", "contact_open"])
        with _StubDock(body) as dock:
            status = an_agent(dock.url).poll()
        assert status.answered is True
        assert status.faults == ("overtemp", "contact_open")
        assert status.charging is False

    def test_load_present_and_charging_are_independent(self):
        """접점이 물렸는데 전류가 안 흐르는 상황은 접촉 실패와 다른 고장이다 —
        산화된 접점, 만충, 래치된 보호회로."""
        body = dict(HEALTHY, load_present=True, charging=False, current_a=0.0)
        with _StubDock(body) as dock:
            status = an_agent(dock.url).poll()
        assert status.load_present is True
        assert status.charging is False


class TestDockAgentFailures:
    """어느 경우에도 예외가 콜백으로 새면 안 되고, 각각이 서로 구분되어야 한다.
    상태머신이 "도크가 전류 없다고 답했다"와 "도크가 답을 안 했다"를 가르지
    못하면 재시도 전략을 세울 수 없다."""

    def test_a_dead_dock_is_not_an_exception(self):
        """거부냐 지연이냐는 OS 마다 다르고 상태머신도 구분할 필요가 없다.
        중요한 것은 답을 못 받았고, 그때 충전 중이 아니라는 것이다."""
        from core_features.docking.agent import DockReachability
        with _StubDock(HEALTHY) as dock:
            url = dock.url                      # 서버를 닫고 그 포트를 쓴다
        status = an_agent(url, timeout_s=0.3).poll()
        assert status.reachability in (DockReachability.UNREACHABLE,
                                       DockReachability.TIMEOUT)
        assert status.answered is False
        assert status.charging is False         # 모를 때는 충전 중이 아니다
        assert status.error is not None         # 왜 실패했는지는 남아야 한다

    def test_a_slow_dock_times_out_rather_than_hanging(self):
        from core_features.docking.agent import DockReachability
        with _StubDock(HEALTHY, delay_s=2.0) as dock:
            status = an_agent(dock.url, timeout_s=0.3).poll()
        assert status.reachability is DockReachability.TIMEOUT
        assert status.answered is False

    def test_the_client_never_blocks_longer_than_its_timeout(self):
        """이 폴링은 틱 안에서 돈다. 멎은 도크가 틱을 멈춰 세우면 안 된다."""
        import time as _t
        with _StubDock(HEALTHY, delay_s=3.0) as dock:
            started = _t.monotonic()
            an_agent(dock.url, timeout_s=0.3).poll()
            elapsed = _t.monotonic() - started
        assert elapsed < 1.5

    def test_a_non_200_is_a_bad_response(self):
        from core_features.docking.agent import DockReachability
        with _StubDock(HEALTHY, status=503) as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.BAD_RESPONSE
        assert status.answered is False

    def test_malformed_json_is_a_bad_response(self):
        from core_features.docking.agent import DockReachability
        with _StubDock(None, raw=b"{not json at all") as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.BAD_RESPONSE

    def test_a_non_object_body_is_a_bad_response(self):
        from core_features.docking.agent import DockReachability
        with _StubDock([1, 2, 3]) as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.BAD_RESPONSE

    def test_missing_charging_field_is_a_bad_response(self):
        """없는 필드를 False 로 채우면 "충전 안 됨"과 "말을 안 함"이 섞인다."""
        from core_features.docking.agent import DockReachability
        body = {k: v for k, v in HEALTHY.items() if k != "charging"}
        with _StubDock(body) as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.BAD_RESPONSE

    def test_optional_fields_may_be_absent(self):
        from core_features.docking.agent import DockReachability
        body = {"load_present": True, "charging": True}
        with _StubDock(body) as dock:
            status = an_agent(dock.url).poll()
        assert status.reachability is DockReachability.OK
        assert status.current_a is None
        assert status.faults == ()

    def test_no_url_means_no_dock_agent(self):
        from core_features.docking.agent import DockReachability
        status = an_agent(None).poll()
        assert status.reachability is DockReachability.UNREACHABLE
        assert status.answered is False


# --- 충전 확인: 독립된 두 소스 -------------------------------------------------
#
# LAN 의 어떤 장치가 charging:true 라고 우겨도 그것만으로 안전 경로를 끄지
# 못하게 한다. 이 판정이 D-27 deep 셧다운 억제의 입력이기 때문이다.

def a_status(**kwargs):
    from core_features.docking.agent import DockReachability, DockStatus
    options = dict(reachability=DockReachability.OK, load_present=True,
                   charging=True, current_a=1.4)
    options.update(kwargs)
    return DockStatus(**options)


def unreachable_status():
    from core_features.docking.agent import DockReachability, DockStatus
    return DockStatus(reachability=DockReachability.UNREACHABLE)


def a_confirmation(clock, **kwargs):
    from core_features.docking.charging import ChargingConfirmation
    options = dict(window_s=10.0, fall_tolerance_v=0.02)
    options.update(kwargs)
    return ChargingConfirmation(clock=clock, **options)


class TestChargingConfirmation:
    def test_nothing_is_confirmed_before_any_sample(self, clock):
        assert a_confirmation(clock).confirmed is False

    def test_a_dock_reporting_current_with_steady_voltage_confirms(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=7.60)
        assert confirmation.confirmed is True

    def test_a_dock_reporting_current_with_rising_voltage_confirms(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        voltage = 7.40
        for _ in range(12):
            clock.advance(1.0)
            voltage += 0.01
            confirmation.update(a_status(), voltage=voltage)
        assert confirmation.confirmed is True

    def test_a_dock_claiming_current_while_voltage_falls_is_rejected(self, clock):
        """도크가 거짓말을 하거나, 전류가 팩까지 도달하지 못하고 있다.
        어느 쪽이든 충전으로 인정하면 안 된다."""
        confirmation = a_confirmation(clock, window_s=10.0)
        voltage = 7.60
        for _ in range(12):
            clock.advance(1.0)
            voltage -= 0.02
            confirmation.update(a_status(), voltage=voltage)
        assert confirmation.confirmed is False

    def test_a_spoofed_dock_cannot_disable_a_safety_path_alone(self, clock):
        """설계의 핵심 방어 — 이 판정이 D-27 셧다운 억제의 입력이다."""
        confirmation = a_confirmation(clock, window_s=10.0)
        voltage = 6.60
        for _ in range(20):
            clock.advance(1.0)
            voltage -= 0.01                      # 팩은 계속 죽어간다
            confirmation.update(a_status(charging=True, current_a=99.0),
                                voltage=voltage)
        assert confirmation.confirmed is False

    def test_a_dock_reporting_no_current_is_not_confirmed(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(a_status(charging=False, current_a=0.0),
                                voltage=7.60)
        assert confirmation.confirmed is False

    def test_an_unreachable_dock_is_not_confirmed_and_not_an_error(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(unreachable_status(), voltage=7.60)
        assert confirmation.confirmed is False

    def test_confirmation_needs_the_whole_window(self, clock):
        """한두 표본으로 확정하면 접점이 스치기만 해도 충전으로 읽힌다."""
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(5):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=7.60)
        assert confirmation.confirmed is False
        for _ in range(6):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=7.60)
        assert confirmation.confirmed is True

    def test_it_survives_a_single_noisy_voltage_sample(self, clock):
        """전압 표본 한 발이 튀었다고 충전 판정이 무너지면 안 된다."""
        confirmation = a_confirmation(clock, window_s=10.0, fall_tolerance_v=0.05)
        for index in range(14):
            clock.advance(1.0)
            voltage = 7.60 - (0.03 if index == 6 else 0.0)
            confirmation.update(a_status(), voltage=voltage)
        assert confirmation.confirmed is True

    def test_losing_the_dock_drops_confirmation_at_once(self, clock):
        """확정은 창을 요구하지만 해제는 즉시다 — 안전한 방향으로 비대칭."""
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=7.60)
        assert confirmation.confirmed is True
        clock.advance(1.0)
        confirmation.update(a_status(charging=False, current_a=0.0), voltage=7.60)
        assert confirmation.confirmed is False

    def test_a_missing_voltage_does_not_confirm(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=None)
        assert confirmation.confirmed is False

    def test_reset_clears_the_window(self, clock):
        confirmation = a_confirmation(clock, window_s=10.0)
        for _ in range(12):
            clock.advance(1.0)
            confirmation.update(a_status(), voltage=7.60)
        assert confirmation.confirmed is True
        confirmation.reset()
        assert confirmation.confirmed is False


# --- 도킹 상태머신 -------------------------------------------------------------

class SpyExecutor:
    """모션 실행부 대역. 무엇을 시켰는지만 기록한다."""

    def __init__(self):
        self.goals = []
        self.drives = []
        self.stops = 0
        self.cancels = 0
        self.exemption = False
        self.exemption_history = []
        self._travelled = 0.0

    def navigate_to(self, pose):
        self.goals.append(pose)

    def cancel_navigation(self):
        self.cancels += 1

    def drive(self, linear, angular):
        self.drives.append((linear, angular))

    def stop(self):
        self.stops += 1

    def set_collision_exemption(self, enabled):
        self.exemption = bool(enabled)
        self.exemption_history.append(bool(enabled))

    def travelled_m(self):
        return self._travelled

    def reset_odometry_mark(self):
        self._travelled = 0.0

    def advance_odometry(self, metres):
        self._travelled += metres


class StubSafety:
    def __init__(self, estop=False):
        self.estop = estop


class StubBattery:
    """BatteryMonitor 대역 — 필터된 전압과 충전 억제 신호만 흉내낸다."""

    def __init__(self, voltage=7.60):
        self.voltage = voltage
        self.charging = False

    def set_charging(self, confirmed):
        self.charging = bool(confirmed)


class StubAgent:
    """도크 에이전트 대역 — 네트워크 없이 상태를 지정한다."""

    def __init__(self, status=None):
        self.status = status if status is not None else a_status()
        self.polls = 0

    def poll(self):
        self.polls += 1
        return self.status


def a_manager(clock, *, detector=None, agent=None, estop=False,
              supported=True, docks=("dock_1",), max_retries=3, **config_kwargs):
    from core_features.docking.manager import DockingConfig, DockingManager
    from core_features.docking.detector import SimulatedDetector

    db = DockDatabase.empty()
    db.add_type(DockType(name="rosy_v1", detector="simulated",
                         staging_offset_m=0.7, docking_threshold_m=0.05,
                         max_retries=max_retries, undock_distance_m=0.35))
    for dock_id in docks:
        db.add(a_dock(id=dock_id))

    detector = detector if detector is not None else SimulatedDetector(
        script=[(0.60, 0.0, 0.0), (0.30, 0.0, 0.0), (0.04, 0.0, 0.0)],
        clock=clock, step_s=1.0)
    agent = agent if agent is not None else StubAgent()
    battery = config_kwargs.pop('battery', None) or StubBattery()
    events = config_kwargs.pop('events', None)

    manager = DockingManager(
        database=db,
        safety=StubSafety(estop=estop),
        config=DockingConfig(**config_kwargs),
        clock=clock,
        detector_factory=lambda dock, dock_type: detector,
        agent_factory=lambda dock: agent,
        capability_provider=lambda: supported,
        map_id_provider=lambda: "warehouse_a",
        battery=battery,
        events=events,
    )
    manager.executor = SpyExecutor()
    manager.detector = detector
    manager.agent = agent
    manager.battery = battery
    return manager


def arrive(manager):
    """스테이징 도착을 알린다."""
    from core_common.protocol.schemas import NavigationState
    manager.on_navigation_state(NavigationState.ARRIVED)


def run_to_docked(manager, clock, ticks=40, step_s=0.5):
    for _ in range(ticks):
        clock.advance(step_s)
        manager.tick()


class TestDockingAcceptance:
    def test_a_dock_command_enters_docking(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock)
        manager.dock("dock_1")
        assert manager.state is DockState.DOCKING
        assert manager.executor.goals, "staging goal must be sent"

    def test_the_staging_goal_is_in_front_of_the_dock(self, clock):
        manager = a_manager(clock)
        manager.dock("dock_1")
        goal = manager.executor.goals[0]
        # dock_1 은 (2.5, 1.8, yaw=0), 오프셋 0.7 → 앞쪽 0.7 m
        assert goal.x == pytest.approx(1.8)
        assert goal.y == pytest.approx(1.8)

    def test_an_unsupported_robot_is_refused(self, clock):
        """DNC-003 — capability 가 꺼진 로봇은 도킹하지 않는다."""
        manager = a_manager(clock, supported=False)
        with pytest.raises(DockError) as excinfo:
            manager.dock("dock_1")
        assert excinfo.value.code == "CAPABILITY_NOT_SUPPORTED"

    def test_an_unknown_dock_is_refused(self, clock):
        manager = a_manager(clock)
        with pytest.raises(DockError) as excinfo:
            manager.dock("nope")
        assert excinfo.value.code == "NOT_FOUND"

    def test_a_dock_on_another_map_is_refused(self, clock):
        manager = a_manager(clock)
        manager._map_id_provider = lambda: "warehouse_b"
        with pytest.raises(DockError) as excinfo:
            manager.dock("dock_1")
        assert excinfo.value.code == "MAP_MISMATCH"

    def test_estop_refuses_a_dock_command(self, clock):
        manager = a_manager(clock, estop=True)
        with pytest.raises(DockError) as excinfo:
            manager.dock("dock_1")
        assert excinfo.value.code == "EMERGENCY_ACTIVE"

    def test_docking_twice_is_refused(self, clock):
        manager = a_manager(clock)
        manager.dock("dock_1")
        with pytest.raises(DockError) as excinfo:
            manager.dock("dock_1")
        assert excinfo.value.code == "DOCKING_ACTIVE"

    def test_the_single_dock_needs_no_id(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock)
        manager.dock()                              # 1:1 배치
        assert manager.state is DockState.DOCKING

    def test_with_two_docks_an_id_is_required(self, clock):
        manager = a_manager(clock, docks=("dock_1", "dock_2"))
        with pytest.raises(DockError) as excinfo:
            manager.dock()
        assert excinfo.value.code == "DOCK_REQUIRED"


class TestDockingSequence:
    def test_the_happy_path_reaches_charging(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock)
        assert manager.state in (DockState.DOCKED, DockState.CHARGING)

    def test_the_phases_run_in_order(self, clock):
        from core_features.docking.manager import DockPhase
        manager = a_manager(clock)
        seen = []
        manager.dock("dock_1")
        seen.append(manager.phase)
        arrive(manager)
        for _ in range(40):
            clock.advance(0.5)
            manager.tick()
            if manager.phase not in seen:
                seen.append(manager.phase)
        order = [p for p in seen if p is not None]
        assert order[0] is DockPhase.STAGING
        assert DockPhase.ACQUIRING in order
        assert DockPhase.APPROACHING in order
        assert order.index(DockPhase.ACQUIRING) < order.index(DockPhase.APPROACHING)

    def test_the_approach_drives_forward(self, clock):
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        for _ in range(10):
            clock.advance(0.5)
            manager.tick()
        assert any(linear > 0 for linear, _ in manager.executor.drives)

    def test_a_lateral_error_produces_a_correcting_turn(self, clock):
        from core_features.docking.detector import SimulatedDetector
        detector = SimulatedDetector(script=[(0.5, 0.10, 0.0)], clock=clock)
        manager = a_manager(clock, detector=detector)
        manager.dock("dock_1")
        arrive(manager)
        for _ in range(8):
            clock.advance(0.5)
            manager.tick()
        turns = [angular for _, angular in manager.executor.drives if angular != 0.0]
        assert turns and turns[0] > 0        # 도크가 왼쪽에 있으면 왼쪽으로 돈다

    def test_charging_is_reported_once_confirmed(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock, charge_confirm_s=2.0)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock, ticks=60)
        assert manager.state is DockState.CHARGING

    def test_contact_without_current_stays_docked_not_charging(self, clock):
        from core_common.protocol.schemas import DockState
        agent = StubAgent(a_status(load_present=True, charging=False, current_a=0.0))
        manager = a_manager(clock, agent=agent, settle_timeout_s=1e9)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock, ticks=60)
        assert manager.state is DockState.DOCKED


class TestDockingFailures:
    def test_a_detector_that_never_acquires_retries_then_fails(self, clock):
        from core_features.docking.detector import SimulatedDetector
        from core_common.protocol.schemas import DockState
        blind = SimulatedDetector(script=[], clock=clock)
        manager = a_manager(clock, detector=blind, max_retries=2,
                            acquire_timeout_s=2.0, backoff_s=0.5)
        manager.dock("dock_1")
        for _ in range(200):
            clock.advance(0.5)
            arrive(manager)          # Nav2 는 목표 완료를 계속 보고한다
            manager.tick()
            if manager.state is DockState.DOCK_FAILED:
                break
        assert manager.state is DockState.DOCK_FAILED
        assert manager.retries == 2

    def test_a_staging_timeout_fails(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock, max_retries=0, staging_timeout_s=5.0)
        manager.dock("dock_1")                      # 도착을 알리지 않는다
        for _ in range(40):
            clock.advance(1.0)
            manager.tick()
        assert manager.state is DockState.DOCK_FAILED

    def test_dock_failed_is_terminal_and_does_not_retry_itself(self, clock):
        """무인 상태로 스무 번 실패한 로봇은 물리적 문제가 있다. 루프는 그것을
        숨기면서 지키려던 팩을 마저 비운다."""
        from core_features.docking.detector import SimulatedDetector
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock, detector=SimulatedDetector(script=[], clock=clock),
                            max_retries=0, acquire_timeout_s=1.0)
        manager.dock("dock_1")
        for _ in range(50):
            clock.advance(0.5)
            arrive(manager)
            manager.tick()
        assert manager.state is DockState.DOCK_FAILED
        goals_before = len(manager.executor.goals)
        for _ in range(50):
            clock.advance(0.5)
            arrive(manager)
            manager.tick()
        assert manager.state is DockState.DOCK_FAILED
        assert len(manager.executor.goals) == goals_before

    def test_a_settle_failure_reseats_without_re_staging(self, clock):
        """접점에 닿았는데 전류가 없는 것은 도착 실패와 다른 고장이다 —
        스테이징까지 되돌아갈 이유가 없다."""
        agent = StubAgent(a_status(load_present=False, charging=False, current_a=0.0))
        manager = a_manager(clock, agent=agent, settle_timeout_s=2.0,
                            max_retries=2, backoff_s=0.5)
        manager.dock("dock_1")
        arrive(manager)
        goals_after_staging = len(manager.executor.goals)
        for _ in range(120):
            clock.advance(0.5)
            manager.tick()
        assert manager.reseats >= 1
        assert len(manager.executor.goals) == goals_after_staging


class TestDockingInterlocks:
    def test_estop_during_the_approach_aborts(self, clock):
        from core_features.docking.detector import SimulatedDetector
        from core_common.protocol.schemas import DockState
        # 접점에 닿지 않는 대본 — 접근 구간에 머무른다.
        far = SimulatedDetector(script=[(0.5, 0.0, 0.0)], clock=clock)
        manager = a_manager(clock, detector=far)
        manager.dock("dock_1")
        arrive(manager)
        for _ in range(6):
            clock.advance(0.5)
            manager.tick()
        manager._safety.estop = True
        clock.advance(0.5)
        manager.tick()
        assert manager.state is DockState.DOCK_FAILED
        assert manager.executor.exemption is False

    def test_the_collision_exemption_is_only_for_the_approach(self, clock):
        manager = a_manager(clock)
        manager.dock("dock_1")
        assert manager.executor.exemption is False   # 스테이징 중에는 아니다
        arrive(manager)
        run_to_docked(manager, clock)
        assert manager.executor.exemption is False   # 끝나면 반드시 풀린다
        assert True in manager.executor.exemption_history

    def test_cancel_releases_everything(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        for _ in range(5):
            clock.advance(0.5)
            manager.tick()
        manager.cancel()
        assert manager.state is DockState.UNDOCKED
        assert manager.executor.exemption is False
        assert manager.executor.stops >= 1


class TestUndocking:
    def test_it_reverses_on_odometry_and_finishes(self, clock):
        from core_common.protocol.schemas import DockState
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock)
        manager.undock()
        assert manager.state is DockState.UNDOCKING
        for _ in range(20):
            clock.advance(0.5)
            manager.executor.advance_odometry(0.05)
            manager.tick()
        assert manager.state is DockState.UNDOCKED

    def test_it_drives_backward(self, clock):
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock)
        before = len(manager.executor.drives)
        manager.undock()
        clock.advance(0.5)
        manager.tick()
        reverse = manager.executor.drives[before:]
        assert reverse and all(linear < 0 for linear, _ in reverse)

    def test_it_does_not_consult_the_detector(self, clock):
        """도크에 반쯤 물린 상태에서는 LiDAR 도 카메라도 믿을 게 없다."""
        manager = a_manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock)
        manager.undock()
        assert manager.detector.relative_pose() is None   # stop 되어 있어야 한다

    def test_undocking_when_not_docked_is_refused(self, clock):
        manager = a_manager(clock)
        with pytest.raises(DockError) as excinfo:
            manager.undock()
        assert excinfo.value.code == "NOT_DOCKED"


# --- 20% 자동 복귀 (설계 §"20%에서, 10%가 아니라") ------------------------------
#
# 크리티컬 10%는 2S 팩의 절벽 구간이라 거기서 출발하면 도크까지 못 갈 수 있고,
# 전류 센싱이 없어 에너지 예산을 세울 수도 없다. 로봇은 임무를 더 일찍 포기한다.

class TestReturnToDock:
    def _manager(self, clock, **kwargs):
        return a_manager(clock, **kwargs)

    def test_the_warning_level_starts_a_return(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state is DockState.DOCKING
        assert manager.executor.goals

    def test_the_ok_level_does_not(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.on_battery_level(BatteryLevel.OK)
        assert manager.state is DockState.UNDOCKED

    def test_critical_also_returns(self, clock):
        """20%를 놓친 채 10%에 도달했다면 그때라도 가야 한다."""
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.on_battery_level(BatteryLevel.CRITICAL)
        assert manager.state is DockState.DOCKING

    def test_no_dock_configured_does_nothing(self, clock):
        """도크가 없는 로봇에서는 SAF-005 의 기존 폴백이 그대로 남는다."""
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock, docks=())
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state is DockState.UNDOCKED

    def test_it_does_not_restart_while_already_docking(self, clock):
        from core_common.protocol.schemas import BatteryLevel
        manager = self._manager(clock)
        manager.on_battery_level(BatteryLevel.WARNING)
        goals = len(manager.executor.goals)
        manager.on_battery_level(BatteryLevel.WARNING)
        manager.on_battery_level(BatteryLevel.CRITICAL)
        assert len(manager.executor.goals) == goals

    def test_it_does_not_fire_when_already_docked(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.dock("dock_1")
        arrive(manager)
        run_to_docked(manager, clock)
        goals = len(manager.executor.goals)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state in (DockState.DOCKED, DockState.CHARGING)
        assert len(manager.executor.goals) == goals

    def test_estop_blocks_the_return(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock, estop=True)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state is DockState.UNDOCKED

    def test_an_unsupported_robot_does_not_try(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock, supported=False)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state is DockState.UNDOCKED

    def test_a_manual_session_defers_the_return(self, clock):
        """수동 조작(우선순위 3)이 도킹(4)보다 위다. 운영자에게서 빼앗지 않는다."""
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.set_manual_active(True)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.state is DockState.UNDOCKED
        assert manager.return_pending is True

    def test_the_deferred_return_runs_when_manual_ends(self, clock):
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock)
        manager.set_manual_active(True)
        manager.on_battery_level(BatteryLevel.WARNING)
        manager.set_manual_active(False)
        clock.advance(0.5)
        manager.tick()
        assert manager.state is DockState.DOCKING
        assert manager.return_pending is False

    def test_recovering_above_warning_cancels_a_pending_return(self, clock):
        from core_common.protocol.schemas import BatteryLevel
        manager = self._manager(clock)
        manager.set_manual_active(True)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.return_pending is True
        manager.on_battery_level(BatteryLevel.OK)
        assert manager.return_pending is False

    def test_the_return_cancels_an_active_navigation_goal(self, clock):
        from core_common.protocol.schemas import BatteryLevel
        manager = self._manager(clock)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert manager.executor.cancels >= 1

    def test_a_failed_return_does_not_loop(self, clock):
        """DOCK_FAILED 뒤에 경고 레벨이 계속 와도 다시 시도하지 않는다."""
        from core_features.docking.detector import SimulatedDetector
        from core_common.protocol.schemas import BatteryLevel, DockState
        manager = self._manager(clock, detector=SimulatedDetector(script=[], clock=clock),
                                max_retries=0, acquire_timeout_s=1.0)
        manager.on_battery_level(BatteryLevel.WARNING)
        for _ in range(50):
            clock.advance(0.5)
            arrive(manager)
            manager.tick()
        assert manager.state is DockState.DOCK_FAILED
        goals = len(manager.executor.goals)
        manager.on_battery_level(BatteryLevel.CRITICAL)
        assert len(manager.executor.goals) == goals

    def test_an_event_records_why_the_robot_left(self, clock):
        from core_common.protocol.schemas import BatteryLevel
        events = RecordingDockEvents()
        manager = self._manager(clock, events=events)
        manager.on_battery_level(BatteryLevel.WARNING)
        assert "docking.return_started" in events.types()


class RecordingDockEvents:
    def __init__(self):
        self.published = []

    def publish(self, type_, severity=None, source=None, data=None):
        self.published.append((type_, severity, source, data or {}))

    def types(self):
        return [entry[0] for entry in self.published]
