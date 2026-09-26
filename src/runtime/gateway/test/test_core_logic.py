"""순수 로직 단위 테스트 — 중재/워치독/안전/웨이포인트/이벤트/네비 (ROS 무의존)."""

import time
from pathlib import Path

import pytest

from core_features.command.arbitration import Mode, ModeMachine, Priority, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_events.events.bus import EventBus
from core_features.navigation.manager import NavigationManager, NavGoalSpec
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits
from core_features.state.manager import StateManager
from core_features.waypoints.manager import Waypoint, WaypointManager

#: src/ 트리 루트 — 이 파일은 <root>/src/runtime/gateway/test/ 에 있다.
SRC_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def bus():
    return EventBus("rosy_01", buffer_size=8)


@pytest.fixture
def safety(bus):
    return SafetyManager(
        SpeedLimits(max_linear=0.20, max_angular=0.80, manual_linear=0.15, manual_angular=0.60),
        BatteryPolicy(), events=bus,
    )


def test_speed_limits_from_config_prefer_profile_then_yaml():
    class Profile:
        max_linear_velocity = 0.21
        max_angular_velocity = 0.81

    limits = SpeedLimits.from_config(
        profile=Profile(),
        nav_cfg={"max_linear_velocity": 0.10, "max_angular_velocity": 0.20},
        safety_cfg={
            "manual_linear": 0.05,
            "manual_angular": 0.07,
            "fleet_linear": 0.09,
            "fleet_angular": 0.11,
        },
    )
    assert limits.max_linear == 0.21
    assert limits.max_angular == 0.81
    assert limits.manual_linear == 0.05
    assert limits.fleet_linear == 0.09

    class Empty:
        max_linear_velocity = None
        max_angular_velocity = None

    fallback = SpeedLimits.from_config(
        profile=Empty(),
        nav_cfg={"max_linear_velocity": 0.20, "max_angular_velocity": 0.80},
        safety_cfg={},
    )
    assert fallback.max_linear == 0.20
    assert fallback.fleet_linear == 0.20


class TestArbitration:
    def test_registry_rejects_unknown_source(self):
        reg = SourceRegistry()
        assert reg.is_active_source("manual")
        assert not reg.is_active_source("evil")

    def test_mode_transitions(self):
        m = ModeMachine()
        assert m.transition(Mode.MANUAL)[0]
        assert m.transition(Mode.NAVIGATION)[0]
        assert m.transition(Mode.EMERGENCY)[0]
        assert not m.transition(Mode.NAVIGATION)[0]      # EMERGENCY에서 NAV 불가
        assert m.release_emergency()[0]
        assert m.mode is Mode.IDLE

    def test_docking_reserved_disabled(self):
        reg = SourceRegistry({"manual": 3, "navigation": 5})
        assert reg.priority_of("docking") is None


class TestCommandManager:
    def _make(self, bus, safety):
        reg = SourceRegistry()
        modes = ModeMachine()
        modes.transition(Mode.MANUAL)
        return CommandManager(reg, modes, safety, events=bus), modes

    def test_manual_blocks_nav_and_vice_versa(self, bus, safety):
        cmd, _ = self._make(bus, safety)
        cmd.set_nav_twist(Twist(0.2, 0.0))
        assert cmd.select_output(now=time.monotonic()).linear == 0.0   # MANUAL 중 Nav 차단 (§8.1)

    def test_watchdog_zero_after_timeout(self, bus, safety):
        cmd, _ = self._make(bus, safety)
        ok, _ = cmd.teleop(0.1, 0.0)
        assert ok
        t0 = time.monotonic()
        assert cmd.select_output(now=t0).linear == pytest.approx(0.1)
        assert cmd.select_output(now=t0 + 0.6).linear == 0.0          # SAF-002 만료

    def test_navigation_twist_expires_instead_of_replaying_stale_motion(self, bus, safety):
        reg = SourceRegistry()
        modes = ModeMachine()
        modes.transition(Mode.NAVIGATION)
        cmd = CommandManager(reg, modes, safety, events=bus)
        t0 = time.monotonic()

        cmd.set_nav_twist(Twist(0.2, 0.0), now=t0)

        assert cmd.select_output(now=t0 + 0.1).linear == pytest.approx(0.2)
        assert cmd.select_output(now=t0 + 0.6).linear == 0.0

    def test_teleop_rejected_outside_manual(self, bus, safety):
        reg = SourceRegistry()
        modes = ModeMachine()
        cmd = CommandManager(reg, modes, safety, events=bus)
        ok, code = cmd.teleop(0.1, 0.0)
        assert not ok and code == "MODE_CONFLICT"

    def test_estop_blocks_everything(self, bus, safety):
        cmd, modes = self._make(bus, safety)
        safety.trigger_estop("test")
        ok, code = cmd.teleop(0.1, 0.0)
        assert not ok and code == "EMERGENCY_ACTIVE"
        cmd.set_nav_twist(Twist(0.2, 0.0))
        assert cmd.select_output(now=time.monotonic()).linear == 0.0

    def test_speed_clipping(self, bus, safety):
        cmd, _ = self._make(bus, safety)
        cmd.teleop(5.0, 99.0)
        assert cmd.select_output(now=time.monotonic()).linear == pytest.approx(0.15)
        assert cmd.select_output(now=time.monotonic()).angular == pytest.approx(0.60)


class TestSafety:
    def test_estop_events(self, bus, safety):
        assert safety.trigger_estop("web")
        assert not safety.trigger_estop("web")          # 중복 무시
        events = bus.history()
        assert events[-1].type == "safety.estop" and events[-1].severity.value == "critical"
        safety.release(by="admin")
        assert bus.history()[-1].type == "safety.estop_released"

    def test_battery_policy_crossing(self, bus, safety):
        assert safety.on_battery_percent(50) is None
        assert safety.on_battery_percent(15) == "warn"  # 임계 통과 시 1회
        assert safety.on_battery_percent(12) is None
        assert safety.on_battery_percent(9) == "RETURN_HOME"
        types = [e.type for e in bus.history()]
        assert "battery.low" in types and "battery.critical" in types


class TestPersonAdvisory:
    """SAF-006: 사람은 metric 정지의 확대 사유다. YOLO advisory는 속도 상한만
    낮추고, 못 보면 기존 정지가 그대로이며, 사라지면 프로필로 복귀한다."""

    def _advisory(self, safety, now, **kwargs):
        from core_features.safety.manager import PersonAdvisory
        options = dict(present=True, confidence=0.9, observed_at=now, max_age_s=1.0)
        options.update(kwargs)
        advisory = PersonAdvisory(**options)
        safety.set_person_advisory(advisory)
        return advisory

    def test_no_advisory_leaves_clip_unchanged(self, safety):
        assert safety.clip(0.20, 0.50) == (pytest.approx(0.20), pytest.approx(0.50))

    def test_fresh_person_caps_linear_only(self, safety):
        now = time.monotonic()
        self._advisory(safety, now)
        linear, angular = safety.clip(0.20, 0.50, now=now)
        assert linear == pytest.approx(0.05)
        assert angular == pytest.approx(0.50)   # 선회율은 손대지 않는다

    def test_below_cap_passes_through(self, safety):
        now = time.monotonic()
        self._advisory(safety, now)
        assert safety.clip(0.03, 0.10, now=now)[0] == pytest.approx(0.03)

    def test_stale_advisory_is_ignored(self, safety):
        now = time.monotonic()
        self._advisory(safety, now - 2.0)       # max_age 1.0 s 초과
        assert safety.clip(0.20, 0.50, now=now)[0] == pytest.approx(0.20)

    def test_absent_person_is_ignored(self, safety):
        now = time.monotonic()
        self._advisory(safety, now, present=False)
        assert safety.clip(0.20, 0.50, now=now)[0] == pytest.approx(0.20)

    def test_cleared_advisory_restores_profile(self, safety):
        now = time.monotonic()
        self._advisory(safety, now)
        assert safety.clip(0.20, 0.50, now=now)[0] == pytest.approx(0.05)
        safety.set_person_advisory(None)        # 사람 소멸 → 자동 복귀
        assert safety.clip(0.20, 0.50, now=now)[0] == pytest.approx(0.20)

    def test_advisory_never_raises_the_cap(self, safety):
        """낮추기만 한다 — session cap과 같은 규칙. min() 구조라 위로 못 간다."""
        now = time.monotonic()
        self._advisory(safety, now)
        assert safety.clip(0.20, 0.50, now=now)[0] <= 0.20

    def test_bad_advisory_is_rejected(self, safety):
        from core_features.safety.manager import PersonAdvisory
        with pytest.raises(ValueError):
            safety.set_person_advisory(PersonAdvisory(
                present=True, confidence=1.5, observed_at=0.0, max_age_s=1.0))
        with pytest.raises(ValueError):
            safety.set_person_advisory(PersonAdvisory(
                present=True, confidence=0.9, observed_at=0.0, max_age_s=0.0))
        with pytest.raises(ValueError):
            safety.set_person_advisory("person!")


class TestPersonAdvisoryFromEvidence:
    """D-137 T2→SAF-006 주입 고리: 신선한 person 검출만 자문이 된다.
    revision 게이트(known-model registry)는 vision 슬라이스 몫 — 여기 없음."""

    def _evidence(self, **kwargs):
        from core_common.protocol.detections import Detection, DetectionEvidence
        detections = kwargs.pop("detections", [
            Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4, confidence=0.8)])
        options = dict(model_revision="yolo11n-r1", observed_at=1000.0, seq=41,
                       input_width=640, input_height=640, input_fps=10.0,
                       detections=detections)
        options.update(kwargs)
        return DetectionEvidence(**options)

    def test_fresh_person_becomes_advisory(self, safety):
        from core_features.safety.manager import person_advisory_from
        advisory = person_advisory_from(self._evidence(), now=1000.1)
        assert advisory is not None and advisory.present
        safety.set_person_advisory(advisory)
        assert safety.clip(0.20, 0.0, now=1000.1)[0] == pytest.approx(0.05)

    def test_stale_evidence_becomes_nothing(self, safety):
        from core_features.safety.manager import person_advisory_from
        assert person_advisory_from(self._evidence(), now=1001.0) is None

    def test_absence_becomes_nothing(self, safety):
        from core_features.safety.manager import person_advisory_from
        assert person_advisory_from(self._evidence(detections=[]), now=1000.1) is None

    def test_low_confidence_person_becomes_nothing(self, safety):
        from core_common.protocol.detections import Detection
        from core_features.safety.manager import person_advisory_from
        ev = self._evidence(detections=[
            Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4, confidence=0.2)])
        assert person_advisory_from(ev, now=1000.1) is None


class TestModelRegistry:
    """D-137 T3: 아는 revision만 통과. 모르는 revision·어긋난 입력 제원은
    fail-closed — 모르는 모델이 봤다는 것이 증거가 될 수 없다."""

    def _registry(self, revision="yolo11n-r1"):
        from core_features.safety.manager import ModelRegistry
        registry = ModelRegistry()
        registry.register(revision, input_width=640, input_height=640, input_fps=10.0)
        return registry

    def _evidence(self, **kwargs):
        from core_common.protocol.detections import Detection, DetectionEvidence
        detections = kwargs.pop("detections", [
            Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4, confidence=0.8)])
        options = dict(model_revision="yolo11n-r1", observed_at=1000.0, seq=41,
                       input_width=640, input_height=640, input_fps=10.0,
                       detections=detections)
        options.update(kwargs)
        return DetectionEvidence(**options)

    def test_known_revision_with_matching_geometry_passes(self, safety):
        from core_features.safety.manager import person_advisory_from
        advisory = person_advisory_from(
            self._evidence(), now=1000.1, registry=self._registry())
        assert advisory is not None and advisory.present

    def test_unknown_revision_is_rejected(self, safety):
        from core_features.safety.manager import person_advisory_from
        assert person_advisory_from(
            self._evidence(model_revision="evil-v9"), now=1000.1,
            registry=self._registry()) is None

    def test_geometry_mismatch_is_rejected(self, safety):
        from core_features.safety.manager import person_advisory_from
        assert person_advisory_from(
            self._evidence(input_width=320), now=1000.1,
            registry=self._registry()) is None

    def test_no_registry_means_no_gate(self, safety):
        """게이트 없이 부르면 옛 동작 — 게이트 자체는 vision 슬라이스가 건다."""
        from core_features.safety.manager import person_advisory_from
        assert person_advisory_from(
            self._evidence(model_revision="anything"), now=1000.1) is not None

    def test_bad_registration_is_rejected(self):
        from core_features.safety.manager import ModelRegistry
        registry = ModelRegistry()
        with pytest.raises(ValueError):
            registry.register("", input_width=640, input_height=640, input_fps=10.0)
        with pytest.raises(ValueError):
            registry.register("r1", input_width=0, input_height=640, input_fps=10.0)


class TestD137SequenceContract:
    """D-137 T1 서열 계약 — LiDAR/IR metric > YOLO advisory, 호스트 pytest 4건.

    (1) 자문은 상한만 낮춘다 — 단독 정지 경로 없음.
    (2) 자문은 e-stop 플래그를 만지지 못한다.
    (3) e-stop 해금 경로에 vision 없음 — 연산자 action만.
    (4) `vision/detections` 발행자는 트리에 아직 없다 — rosy-vision 단일 예정.
    """

    NOW = 1000.0

    def _fresh_advisory(self, safety):
        from core_common.protocol.detections import Detection, DetectionEvidence
        from core_features.safety.manager import person_advisory_from
        evidence = DetectionEvidence(
            model_revision="yolo11n-r1", observed_at=self.NOW, seq=41,
            input_width=640, input_height=640, input_fps=10.0,
            detections=[Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4,
                                  confidence=0.8)])
        advisory = person_advisory_from(evidence, now=self.NOW + 0.1)
        assert advisory is not None and advisory.present
        safety.set_person_advisory(advisory)
        return advisory

    def test_advisory_only_caps_and_never_stops(self, safety):
        """(1) 자문이 있어도 움직임은 남는다 — (0,0)으로 바꾸지 못한다."""
        self._fresh_advisory(safety)
        now = self.NOW + 0.1
        l, a = safety.clip(0.20, 0.50, now=now)
        assert 0.0 < l <= 0.05 and a == pytest.approx(0.50)
        for linear, angular in ((0.20, 0.0), (0.10, 0.60), (0.20, 0.80),
                                (-0.20, 0.0), (0.15, -0.60)):
            assert safety.clip(linear, angular, now=now) != (0.0, 0.0), \
                (linear, angular)
        # 자문을 떼면(없음·stale 포함) 프로필로 돌아갈 뿐, 새 정지도 없다.
        safety.set_person_advisory(None)
        assert safety.clip(0.20, 0.50, now=now) == (pytest.approx(0.20),
                                                    pytest.approx(0.50))

    def test_advisory_cannot_create_or_clear_estop(self, safety):
        """(2) estop은 trigger_estop/release만이 만진다 — vision 입력은
        set_person_advisory 하나뿐이고 양쪽 다 플래그를 못 바꾼다."""
        assert safety.estop is False and safety.estop_source == ""
        self._fresh_advisory(safety)
        assert safety.estop is False
        safety.trigger_estop("operator")
        assert safety.estop is True
        self._fresh_advisory(safety)        # 자문을 다시 건다 — 해금 아님
        assert safety.estop is True
        safety.set_person_advisory(None)    # 자문을 떼는 것도 해금 아님
        assert safety.estop is True
        assert safety.release("operator") is True
        assert safety.estop is False

    def test_estop_release_path_has_no_vision(self, safety):
        """(3) 해금은 fresh LiDAR/IR + operator action이다(D-137 §5).

        release()는 person 자문을 읽지 않는다 — 자문이 살아 있어도 연산자는
        해금할 수 있고, 사람이 사라졌다는 vision "clear"는 해금을 못 만든다.
        소스 스캔은 e-stop 진입·해금 두 함수 몸통에 vision 토큰이 없음을 핀다.
        """
        self._fresh_advisory(safety)
        safety.trigger_estop("lidar")
        assert safety.release("operator") is True   # 자문이 막지 못한다
        import core_features.safety.manager as safety_module
        text = Path(safety_module.__file__).read_text(encoding="utf-8")
        for name in ("trigger_estop", "release"):
            body = _function_body(text, name)
            for token in ("person", "advisory", "Detection", "vision"):
                assert token not in body, (name, token)

    def test_vision_detections_has_no_publisher_yet(self):
        """(4) 단일 발행자 고정(D-137 §Consequences): 지금은 발행자 0.

        rosy-vision 노드가 착지하면(T5, Hailo 실측 뒤) 이 스캔은 실패하고,
        그때 아래 화이트리스트에 그 파일 하나를 유일 항목으로 넣는다 — CORE는
        구독만 하고 발행 없음(vision-accelerator 설계 OQ4, must-be-1).
        """
        allowed = {}   # 상대 경로 -> 사유. 착지 전에는 비어 있어야 한다.
        offenders = {}
        for path in SRC_ROOT.rglob("*.py"):
            parts = {p.lower() for p in path.parts}
            if "test" in parts or "__pycache__" in parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "vision/detections" in text:
                offenders[str(path.relative_to(SRC_ROOT))] = text
        unexpected = sorted(set(offenders) - set(allowed))
        assert not unexpected, f"vision/detections 발행 후보 발견: {unexpected}"


def _function_body(text: str, name: str) -> str:
    """한 함수(메서드) 몸통: `def <name>(` 줄부터 다음 동일 들여쓰기 정의까지."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if f"def {name}(" in line)
    indent = len(lines[start]) - len(lines[start].lstrip())
    body = [lines[start]]
    for line in lines[start + 1:]:
        if line.strip() and (len(line) - len(line.lstrip())) <= indent \
                and line.lstrip().startswith(("def ", "class ", "@")):
            break
        body.append(line)
    return "\n".join(body)


class TestPersonAdvisoryFeed:
    """D-137 T4 주입 시임: 와이어 패킷 1건이 자문 좌석에 닿는 유일한 길.

    broken·stale·gap 패킷은 전부 자문 해제다 — "못 본 것"으로 상한을 유지하는
    쪽이 자문의 방향이 아니고, e-stop은 어느 경로로도 안 건드린다."""

    def _packet(self, observed_at=1000.0, detections=None):
        from core_common.protocol.detections import Detection
        return {
            "model_revision": "yolo11n-r1", "observed_at": observed_at,
            "seq": 41, "input_width": 640, "input_height": 640,
            "input_fps": 10.0, "inference_ms": 12.0,
            "detections": [
                Detection(label="person", x=0.4, y=0.3, w=0.2, h=0.4,
                          confidence=0.8)] if detections is None else detections,
        }

    def _feed(self, safety):
        """패킷 시계(1000.x, ROS epoch 대응물)와 좌석 시계(10.x, monotonic
        대응물)를 분리해 둔다 — 실제 배선이 그렇다(브리지가 노드 시계를
        꽂고, clip은 monotonic으로 판정한다)."""
        from core_features.safety.manager import PersonAdvisoryFeed
        return PersonAdvisoryFeed(safety, clock=lambda: 1000.1,
                                  seat_clock=lambda: 10.0)

    def test_fresh_person_packet_sets_the_advisory(self, safety):
        feed = self._feed(safety)
        verdict = feed.ingest(self._packet())
        assert verdict == {'advisory': True, 'reason': 'person_advisory_set'}
        assert safety.clip(0.20, 0.50, now=10.01)[0] == pytest.approx(0.05)

    def test_broken_stale_and_gap_packets_clear_the_advisory(self, safety):
        feed = self._feed(safety)
        assert feed.ingest(self._packet())['advisory'] is True
        assert feed.ingest("not a packet") == {'advisory': False,
                                               'reason': 'invalid_packet'}
        # 검증 실패: confidence 1.5, 필드 누락 — 와이어(dict) 진실이 거절하는 패킷.
        bad_confidence = self._packet()
        bad_confidence["detections"] = [
            {"label": "person", "x": 0.4, "y": 0.3, "w": 0.2, "h": 0.4,
             "confidence": 1.5}]
        assert feed.ingest(bad_confidence)['reason'] == 'invalid_packet'
        missing_seq = self._packet()
        missing_seq.pop("seq")
        assert feed.ingest(missing_seq)['reason'] == 'invalid_packet'
        # 깨진 영상 + metric 장애물 시나리오의 자문 절반: 못 본 것은 해제다.
        assert feed.ingest(self._packet(observed_at=999.0)) == \
            {'advisory': False, 'reason': 'no_fresh_advisory'}
        assert feed.ingest(self._packet(detections=[]))['reason'] == 'no_fresh_advisory'
        assert safety.clip(0.20, 0.50, now=10.01) == (pytest.approx(0.20),
                                                      pytest.approx(0.50))

    def test_unknown_revision_through_registry_clears(self, safety):
        from core_features.safety.manager import ModelRegistry, PersonAdvisoryFeed
        registry = ModelRegistry()
        registry.register("yolo11n-r1", input_width=640, input_height=640,
                          input_fps=10.0)
        feed = PersonAdvisoryFeed(safety, registry=registry, clock=lambda: 1000.1)
        evil = self._packet()
        evil["model_revision"] = "evil-v9"
        assert feed.ingest(evil) == {'advisory': False,
                                     'reason': 'no_fresh_advisory'}

    def test_feed_never_touches_estop(self, safety):
        feed = self._feed(safety)
        safety.trigger_estop("lidar")
        feed.ingest(self._packet())
        assert safety.estop is True
        feed.ingest(self._packet(detections=[]))
        assert safety.estop is True


class TestAdvisoryFeedServices:
    """D-137 T4: CoreServices가 피드를 소유하고 ros_bridge가 부른다 — DI 확인."""

    def _packet(self, observed_at):
        return {
            "model_revision": "yolo11n-r1", "observed_at": observed_at,
            "seq": 41, "input_width": 640, "input_height": 640,
            "input_fps": 10.0, "inference_ms": 12.0,
            "detections": [{"label": "person", "x": 0.4, "y": 0.3, "w": 0.2,
                            "h": 0.4, "confidence": 0.8, "track_id": 3}],
        }

    def test_services_feed_sets_and_clears_the_seat(self, core_client):
        client, services = core_client()
        verdict = services.advisory_feed.ingest(self._packet(time.monotonic()))
        assert verdict == {'advisory': True, 'reason': 'person_advisory_set'}
        assert services.safety.clip(0.20, 0.50)[0] == pytest.approx(0.05)
        broken = self._packet(time.monotonic())
        broken["detections"] = [{"label": "person", "x": 0.4, "y": 0.3,
                                 "w": 0.2, "h": 0.4, "confidence": 2.0}]
        services.advisory_feed.ingest(broken)
        assert services.safety.clip(0.20, 0.50) == (pytest.approx(0.20),
                                                    pytest.approx(0.50))


class TestD137MetricStopComposition:
    """D-137 T4 fault-injection 구성: 깨진 영상 + LiDAR 장애물 → 정지 유지.

    metric 정지는 Control 정책(obstacle)이 내고, vision 자문은 clip 상한만
    건드린다. 자문이 살아 있어도 정지는 유지되고, 깨진 영상이 와도 정지가
    풀리지 않는다 — vision에는 정책 입력 경로가 아예 없다(구조적 분리).
    Gazebo 종단 실측 전 단계의 순수 합성 증명이다."""

    def _packet(self, observed_at=1000.0):
        return {
            "model_revision": "yolo11n-r1", "observed_at": observed_at,
            "seq": 41, "input_width": 640, "input_height": 640,
            "input_fps": 10.0, "inference_ms": 12.0,
            "detections": [{"label": "person", "x": 0.4, "y": 0.3, "w": 0.2,
                            "h": 0.4, "confidence": 0.8, "track_id": 3}],
        }

    def test_metric_stop_holds_while_and_after_broken_vision(self):
        from control.control.command_gate import CommandPolicy, GateInputs, GateSnapshot
        from core_features.safety.manager import PersonAdvisoryFeed
        safety = SafetyManager(SpeedLimits(), BatteryPolicy(), policy_required=True)
        policy = CommandPolicy('applied-revision')
        safety.bind_control_policy(policy)
        now = time.monotonic()
        assert policy.update(GateSnapshot(
            policy.session, 1, policy.revision, now, now + .5,
            GateInputs(obstacle=True, bounded_motion=False, can_rotate=True),
            None, None))
        feed = PersonAdvisoryFeed(safety, clock=lambda: 1000.1,
                                  seat_clock=lambda: now)

        # 사람 자문이 좌석에 앉아 있어도(상한 발동 — 영향력 증명) metric 정지는 유지된다.
        assert feed.ingest(self._packet()) == {'advisory': True,
                                               'reason': 'person_advisory_set'}
        assert safety.clip(0.10, 0.0, now=now)[0] == pytest.approx(0.05)
        # 장애물 정지는 limit 경로(상한 0)로 온다 — 출력은 0이다.
        assert safety.evaluate_candidate(1, 'nav', 0.10, 0.0, now + 0.01) == (0., 0.)

        # 깨진 영상이 와도 정지는 그대로고, vision이 만든 정지·해제도 없었다.
        assert feed.ingest("broken") == {'advisory': False,
                                         'reason': 'invalid_packet'}
        assert safety.clip(0.10, 0.0, now=now + 0.02) == (pytest.approx(0.10),
                                                          pytest.approx(0.0))
        assert safety.evaluate_candidate(1, 'nav', 0.10, 0.0, now + 0.02) == (0., 0.)
        assert safety.estop is False


class TestEventBus:
    def test_seq_monotone_and_history(self, bus):
        bus.publish("nav.completed")
        bus.publish("safety.estop", severity="critical")
        assert bus.last_seq == 2
        assert [e.seq for e in bus.history(since_seq=1)] == [2]

    def test_ring_buffer(self, bus):
        for i in range(12):
            bus.publish(f"e{i}")
        assert len(bus.history()) == 8                   # EVT-004 링 버퍼


class TestWaypoints:
    def test_crud_and_home(self, bus, tmp_path):
        wm = WaypointManager(tmp_path / "wp.json", events=bus)
        wm.create(Waypoint(name="zone_a", x=1.0, y=2.0, map_id="m1"))
        wm.create(Waypoint(name="__home__", x=0.0, y=0.0))
        with pytest.raises(Exception):
            wm.create(Waypoint(name="zone_a", x=3.0, y=0.0))        # WAYPOINT_EXISTS
        reloaded = WaypointManager(tmp_path / "wp.json")
        assert reloaded.get("zone_a").x == 1.0                        # 영속화 (D-9)
        wm.delete("zone_a")
        with pytest.raises(Exception):
            reloaded_after = WaypointManager(tmp_path / "wp.json")
            reloaded_after.get("zone_a")


class FakeExecutor:
    def __init__(self):
        self.sent, self.canceled = [], 0

    def send_goal(self, spec):
        self.sent.append(spec)

    def cancel_goal(self):
        self.canceled += 1

    def send_initial_pose(self, x, y, yaw):
        pass


class TestNavigation:
    def _make(self, bus, safety, tmp_path):
        from core_features.waypoints.manager import WaypointManager
        wm = WaypointManager(tmp_path / "wp.json")
        wm.create(Waypoint(name="dock_1", x=2.5, y=1.8, yaw=1.57, map_id="m1"))
        state = StateManager("rosy_01")
        nav = NavigationManager(bus, state, wm, safety)
        nav.executor = FakeExecutor()
        return nav, state, wm

    def test_goal_via_waypoint_and_map_mismatch(self, bus, safety, tmp_path):
        nav, state, _ = self._make(bus, safety, tmp_path)
        state.set_map_id("m1")
        nav.goal(nav.resolve_goal(waypoint="dock_1"))
        assert nav.nav_state.value == "PLANNING"
        state.set_map_id("other_map")
        with pytest.raises(Exception) as e:
            nav.goal(nav.resolve_goal(waypoint="dock_1"))
        assert e.value.code == "MAP_MISMATCH"                          # MAP-002

    def test_lifecycle_and_events(self, bus, safety, tmp_path):
        nav, _, _ = self._make(bus, safety, tmp_path)
        nav.goal(nav.resolve_goal(x=1.0, y=1.0))
        nav.on_goal_accepted()
        assert nav.nav_state.value == "NAVIGATING"
        with pytest.raises(Exception) as e:
            nav.goal(nav.resolve_goal(x=2.0, y=2.0))
        assert e.value.code == "NAVIGATION_ACTIVE"
        nav.on_result(True)
        assert nav.nav_state.value == "ARRIVED"
        types = [ev.type for ev in bus.history()]
        assert "nav.started" in types and "nav.completed" in types

    def test_stuck_detection(self, bus, safety, tmp_path):
        nav, _, _ = self._make(bus, safety, tmp_path)
        nav._stuck_timeout = 0.05
        # NAV-006 의 시계는 주입된다(브리지가 ROS 시계를 끼운다). 모듈의 `time.monotonic`
        # 을 몽키패치해도 이제 매니저는 그것을 보지 않는다.
        now = [0.0]
        nav.clock = lambda: now[0]
        nav.goal(nav.resolve_goal(x=1.0, y=1.0))
        nav.on_goal_accepted()
        nav.on_pose_progress(0.0, 0.0)
        now[0] = 1.0                                                   # 진척 없이 시간 경과
        nav.on_pose_progress(0.0, 0.0)
        assert nav.nav_state.value == "CANCELED"                       # NAV-006
        assert "nav.stuck" in [ev.type for ev in bus.history()]


def test_manual_active_reports_a_live_teleop_session():
    """도킹 복귀는 수동 조작 중이면 미뤄야 한다 (MANUAL 3 > DOCKING 4).
    그 판정에 쓸 신호가 CommandManager 에 있어야 한다."""
    from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
    from core_features.command.manager import CommandManager
    from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits

    safety = SafetyManager(SpeedLimits(), BatteryPolicy())
    modes = ModeMachine()
    command = CommandManager(SourceRegistry(), modes, safety)

    assert command.manual_active is False
    modes.transition(Mode.MANUAL)
    accepted, reason = command.teleop(0.1, 0.0)
    assert accepted, reason
    assert command.manual_active is True
    command.clear_manual()
    assert command.manual_active is False
