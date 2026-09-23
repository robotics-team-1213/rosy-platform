"""core_features.command.arbitration — CMD-001 소스 레지스트리 + §8.1 우선순위 + 모드 상태머신.

ROS 무의존 순수 로직 (P1-5, CORE-002).
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Optional


class Priority(enum.IntEnum):
    EMERGENCY = 1
    SAFETY = 2
    MANUAL = 3
    DOCKING = 4
    NAVIGATION = 5
    FLEET = 6
    IDLE = 7


DEFAULT_SOURCES: dict[str, Priority] = {
    "manual": Priority.MANUAL,
    "docking": Priority.DOCKING,      # DNC-002 예약 — 기본 비활성
    "navigation": Priority.NAVIGATION,
    "swarm": Priority.NAVIGATION,     # SWM-001: 이동 목표 스트림은 NAVIGATION 동급
    "fleet": Priority.FLEET,
}


class Mode(str, enum.Enum):
    IDLE = "IDLE"
    MANUAL = "MANUAL"
    NAVIGATION = "NAVIGATION"
    DOCKING = "DOCKING"
    EMERGENCY = "EMERGENCY"


_ALLOWED: dict[Mode, set[Mode]] = {
    Mode.IDLE: {Mode.MANUAL, Mode.NAVIGATION, Mode.DOCKING, Mode.EMERGENCY},
    Mode.MANUAL: {Mode.IDLE, Mode.NAVIGATION, Mode.EMERGENCY},
    Mode.NAVIGATION: {Mode.IDLE, Mode.MANUAL, Mode.EMERGENCY},
    # MANUAL(3) outranks DOCKING(4): the operator can always take the robot.
    Mode.DOCKING: {Mode.IDLE, Mode.MANUAL, Mode.EMERGENCY},
    Mode.EMERGENCY: {Mode.IDLE},
}


@dataclass
class SourceEntry:
    name: str
    priority: Priority
    enabled: bool = True


class SourceRegistry:
    """CMD-001: 설정 기반 명령 소스 등록. 미등록 소스 명령은 거부."""

    def __init__(self, sources: Optional[dict[str, int]] = None) -> None:
        self._entries: dict[str, SourceEntry] = {}
        raw = sources or DEFAULT_SOURCES
        for name, prio in raw.items():
            self.register(name, Priority(prio))

    def register(self, name: str, priority: Priority, enabled: bool = True) -> None:
        self._entries[name] = SourceEntry(name, priority, enabled)

    def set_enabled(self, name: str, enabled: bool) -> None:
        if name in self._entries:
            self._entries[name].enabled = enabled

    def is_active_source(self, name: str) -> bool:
        entry = self._entries.get(name)
        return entry is not None and entry.enabled

    def priority_of(self, name: str) -> Optional[Priority]:
        entry = self._entries.get(name)
        return entry.priority if entry else None


class ModeMachine:
    """CORE-001 모드 상태머신. EMERGENCY 진입은 어디서든, 해제는 release만."""

    def __init__(self) -> None:
        self.mode: Mode = Mode.IDLE
        #: `(old, new)` after every change. Whoever owns a mode's motion (the
        #: docking run owns DOCKING) stops it here, so no exit path — API,
        #: line follow, e-stop, the bridge — can leave it running.
        self.change_listeners: list = []
        # Check-and-set only. Listeners run after the lock is released: the
        # docking listener takes the docking lock, and docking calls in here
        # while holding it (docking lock -> mode lock, never the reverse).
        self._lock = threading.Lock()

    def can_transition(self, new: Mode) -> bool:
        return new in _ALLOWED[self.mode]

    def transition(self, new: Mode, expect: Optional[Mode] = None) -> tuple[bool, str]:
        """Change the mode. With `expect`, only from that mode — a caller that
        checked the mode, then did something else, must not commit over a mode
        another thread set meanwhile."""
        with self._lock:
            if expect is not None and self.mode is not expect:
                return False, (f"mode changed ({self.mode.value}, "
                               f"expected {expect.value})")
            if new == self.mode:
                return True, ""
            if not self.can_transition(new):
                return False, f"invalid transition {self.mode.value}->{new.value}"
            old, self.mode = self.mode, new
        for listener in list(self.change_listeners):
            listener(old, new)
        return True, ""

    def release_emergency(self) -> tuple[bool, str]:
        with self._lock:
            if self.mode is not Mode.EMERGENCY:
                return False, "not in EMERGENCY"
            self.mode = Mode.IDLE
            return True, ""

    @property
    def is_emergency(self) -> bool:
        return self.mode is Mode.EMERGENCY
