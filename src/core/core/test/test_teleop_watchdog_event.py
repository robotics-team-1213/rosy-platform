"""SAF-002 만료를 알리는 것 (계약은 v1.0 부터 약속했고 코드는 낸 적이 없다).

만료되면 출력이 조용히 0 이 된다. 조종하던 사람에게는 로봇이 그냥 멈춘 것이고,
링크가 끊겼는지 명령이 거부됐는지 자기가 손을 뗀 것인지 구분되지 않는다.

테스트는 브리지의 한 주기를 그대로 흉내낸다 — `select_output` 으로 값을 얻어
바퀴로 내보낸 **뒤** `announce_pending` 을 부른다. 순서가 이 기능의 절반이다.
"""

from __future__ import annotations

from core.bridge.cmd_vel import cmd_vel_cycle
from core_features.command.arbitration import Mode, ModeMachine, SourceRegistry
from core_features.command.manager import CommandManager, Twist
from core_features.safety.manager import BatteryPolicy, SafetyManager, SpeedLimits


class FakeEvents:
    def __init__(self) -> None:
        self.published: list[tuple[str, str, dict]] = []

    def publish(self, type_, severity="info", source="", data=None):
        self.published.append((type_, str(severity), data or {}))

    def types(self) -> list[str]:
        return [t for t, _s, _d in self.published]


def build(mode=Mode.MANUAL):
    events = FakeEvents()
    modes = ModeMachine()
    modes.transition(mode)
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=events)
    # E-Stop 배선은 CommandManager 가 스스로 건다 (`_clear_for_stop`).
    command = CommandManager(SourceRegistry(), modes, safety, events=events)
    return command, events, safety


class _AtTime:
    """`cmd_vel_cycle` 은 `select_output()` 을 인자 없이 부른다. 시각만 끼운다."""

    def __init__(self, command, now):
        self._command, self._now = command, now

    def select_output(self):
        return self._command.select_output(now=self._now)

    def announce_pending(self):
        self._command.announce_pending()


class _NoPower:
    def on_activity(self, source):
        pass


def cycle(command, now, log=None):
    """브리지의 `_publish_cmd_vel` 한 번.

    순서를 여기서 다시 적지 않는다 — 그러면 이 파일과 `cmd_vel.py` 가 조용히
    갈라지고, 순서를 한 군데로 모으려고 떼어낸 의미가 없어진다.
    """
    seen = []

    def send(out):
        if log is not None:
            log.append("wheels")
        seen.append(out)

    cmd_vel_cycle(_AtTime(command, now), _NoPower(), send)
    return seen[0]


def drive(command, at):
    assert command.teleop(0.1, 0.0)[0] is True
    command.watchdog.refresh(at)


def test_an_expiry_says_so_with_the_timeout():
    command, events, _safety = build()
    drive(command, 100.0)

    cycle(command, 100.0 + command.watchdog.timeout_ms / 1000.0 + 0.01)

    watchdog = [d for t, _s, d in events.published if t == "safety.watchdog"]
    assert watchdog == [{"timeout_ms": command.watchdog.timeout_ms}]


def test_it_is_a_warning_because_the_robot_stopped_on_its_own():
    command, events, _safety = build()
    drive(command, 100.0)

    cycle(command, 101.0)

    severity = next(s for t, s, _d in events.published if t == "safety.watchdog")
    assert "warning" in severity.lower()


def test_the_stop_reaches_the_wheels_before_the_announcement():
    """이벤트 발행은 구독자를 동기로 부르고, 운용 구성에서 그중 하나가 30 일치
    감사 로그를 통째로 다시 쓴다. 알림이 앞에 오면 정지가 그만큼 늦게 나간다."""
    command, _events, _safety = build()
    drive(command, 100.0)
    order: list[str] = []

    class Ordered(FakeEvents):
        def publish(self, type_, severity="info", source="", data=None):
            order.append(f"event:{type_}")
            super().publish(type_, severity, source, data)

    command._events = Ordered()

    cycle(command, 101.0, log=order)

    assert order == ["wheels", "event:safety.watchdog"], order


def test_it_is_announced_once_not_once_per_cycle():
    """cmd_vel 은 50 Hz 다. 상태가 아니라 전이에서 말해야 한다."""
    command, events, _safety = build()
    drive(command, 100.0)

    for step in range(50):
        cycle(command, 101.0 + step * 0.02)

    assert events.types().count("safety.watchdog") == 1


def test_a_new_command_re_arms_it():
    command, events, _safety = build()
    drive(command, 100.0)
    cycle(command, 101.0)

    drive(command, 102.0)
    cycle(command, 103.0)

    assert events.types().count("safety.watchdog") == 2


def test_an_expiry_with_nothing_in_hand_announces_nothing():
    """쥐고 있던 조종이 없으면 끊긴 조종도 없다."""
    command, events, _safety = build()

    for step in range(10):
        cycle(command, 1000.0 + step)

    assert "safety.watchdog" not in events.types()


def test_the_announcement_does_not_change_what_reaches_the_wheels():
    command, _events, _safety = build()
    drive(command, 100.0)

    assert cycle(command, 100.1) == Twist(0.1, 0.0)
    assert cycle(command, 101.0) == Twist(0.0, 0.0)
    assert cycle(command, 102.0) == Twist(0.0, 0.0)


def test_an_estop_stops_the_robot_without_blaming_the_watchdog():
    """E-Stop 은 그 자체로 알려진 원인이다. 워치독 탓으로 적으면 안 된다."""
    command, events, safety = build()
    drive(command, 100.0)
    safety.trigger_estop("operator")

    cycle(command, 101.0)

    assert "safety.watchdog" not in events.types()
    assert "safety.estop" in events.types()


def test_releasing_an_estop_does_not_invent_a_lapsed_link():
    """해제 뒤 첫 틱이 만료를 발견하면, 멀쩡했던 링크를 끊겼다고 적는다."""
    command, events, safety = build()
    drive(command, 100.0)
    safety.trigger_estop("operator")
    cycle(command, 101.0)

    safety.release("admin")
    for step in range(5):
        cycle(command, 102.0 + step)

    assert "safety.watchdog" not in events.types()
    assert "safety.estop_released" in events.types()


def test_a_navigation_run_is_not_a_lapsed_teleop():
    command, events, _safety = build(mode=Mode.NAVIGATION)
    command.set_nav_twist(Twist(0.1, 0.0), now=100.0)

    cycle(command, 200.0)

    assert "safety.watchdog" not in events.types()


def test_a_late_write_cannot_swallow_a_fresh_session():
    """불리언 래치는 경합에서 사라진다.

    타이머가 만료를 기록하고 멈춘 사이 새 명령이 들어오면, 뒤늦게 도착한
    알림이 그 새 세션을 "이미 알림"으로 덮어써 그 세션의 끊김은 영영
    조용해진다. 세션 번호를 비교하면 옛 값을 실은 쓰기는 무해하다.
    """
    command, events, _safety = build()
    drive(command, 100.0)
    command.select_output(now=101.0)      # 만료를 기록만 한다

    drive(command, 102.0)                 # 그 사이 새 세션이 시작되고
    command.announce_pending()            # 뒤늦은 알림이 도착한다

    cycle(command, 103.0)

    # 두 번이다: 뒤늦게 도착한 첫 세션의 알림 하나, 새 세션 자신의 끊김 하나.
    # `>= 1` 로 적으면 불리언 래치 회귀(첫 알림 하나만 나고 새 세션은 영영
    # 조용한 상태)도 통과한다 — 이 테스트가 막으려던 바로 그것이다.
    assert events.types().count("safety.watchdog") == 2, (
        "the new session's own lapse must still be announced"
    )


def test_the_expiry_reaches_the_audit_log(tmp_path):
    """운영자가 나중에 왜 멈췄는지 볼 수 있어야 한다 (LOG-001)."""
    from core_events.events.audit import FileAuditLog
    from core_events.events.bus import EventBus

    bus = EventBus("rosy_01")
    audit = FileAuditLog(tmp_path / "audit.jsonl")
    bus.subscribe(audit.record)

    modes = ModeMachine()
    modes.transition(Mode.MANUAL)
    safety = SafetyManager(SpeedLimits(), BatteryPolicy(), events=bus)
    command = CommandManager(SourceRegistry(), modes, safety, events=bus)
    command.teleop(0.1, 0.0)
    command.watchdog.refresh(100.0)

    cycle(command, 101.0)

    recorded = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
    assert "safety.watchdog" in recorded
