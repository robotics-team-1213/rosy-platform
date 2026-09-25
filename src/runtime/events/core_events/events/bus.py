"""core_events.events.bus — EVT-001~005 이벤트 버스 (ADR-D-8, P1-17).

seq 단조 증가, 링 버퍼(EVT-004), 구독자 브로드캐스트, since_seq 갭 필(EVT-003).
ROS/프레임워크 무의존 — 발행·소비 모두 스레드 안전.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Callable, Optional

from core_common.protocol.schemas import EventMessage, Severity


class EventBus:
    def __init__(self, robot_id: str, buffer_size: int = 1000) -> None:
        self._robot_id = robot_id
        self._lock = threading.Lock()
        self._seq = 0
        self._buffer: deque[EventMessage] = deque(maxlen=buffer_size)
        self._subscribers: list[Callable[[EventMessage], None]] = []

    def set_robot_id(self, robot_id: str) -> None:
        with self._lock:
            self._robot_id = robot_id

    @property
    def last_seq(self) -> int:
        with self._lock:
            return self._seq

    def publish(
        self,
        type_: str,
        severity: Severity | str = Severity.INFO,
        source: str = "",
        data: Optional[dict[str, Any]] = None,
    ) -> EventMessage:
        with self._lock:
            self._seq += 1
            event = EventMessage(
                seq=self._seq,
                robot_id=self._robot_id,
                type=type_,
                severity=Severity(severity),
                source=source,
                data=data or {},
            )
            self._buffer.append(event)
            subscribers = list(self._subscribers)
        for cb in subscribers:
            try:
                cb(event)
            except Exception:
                pass
        return event

    def subscribe(self, callback: Callable[[EventMessage], None]) -> Callable[[], None]:
        with self._lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return _unsubscribe

    def history(self, since_seq: Optional[int] = None, limit: int = 1000) -> list[EventMessage]:
        with self._lock:
            events = list(self._buffer)
        if since_seq is not None:
            events = [e for e in events if e.seq > since_seq]
        return events[-limit:]
