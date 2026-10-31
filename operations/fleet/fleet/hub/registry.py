"""로봇 기록. 전송·ROS 없음."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Optional

from core_common.protocol.schemas import EventMessage, StateSnapshot

#: /registry 표시·events_since 공급용 최근 창. 로봇당 고정 폭이다(2026-10-28 자원 경계).
EVENT_FEED_MAX = 500
#: stuck 복구 판정이 읽는 이벤트 형. 그 밖 형식은 stuck 인덱스에 넣지 않는다.
STUCK_EVENT_TYPES = ("nav.line_stuck_opened", "nav.line_stuck_closed")


def event_content_hash(event: EventMessage) -> str:
    """CoreEventStore 정규화 JSON과 같은 본문 비교용 해시.

    직렬화 불가능한 값은 그대로 TypeError/ValueError를 내보낸다(호출자가 감사 거부).
    """
    encode = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode
    return hashlib.sha256(encode(event.model_dump(mode="json")).encode("utf-8")).hexdigest()


@dataclass
class RobotRecord:
    robot_id: str
    online: bool = False
    device_uid: str = ""
    device_name: str = ""
    model: str = ""
    hardware_serial: str = ""
    snapshot: Optional[StateSnapshot] = None
    #: D-447: 마지막 heartbeat 도착 시각(time.monotonic). gather 신선도 판정만 쓴다.
    last_heartbeat_monotonic: Optional[float] = None
    last_event_seq: int = 0
    #: /registry 최근 창 — deque(maxlen)이라 오래된 행은 저절로 밀려난다.
    events: deque = field(default_factory=lambda: deque(maxlen=EVENT_FEED_MAX))
    #: (type, stuck_id) → 최근 stuck 이벤트. 퇴출 없음: 막힘 복구 판정이 재접속 뒤에도
    #: 과거 opened/closed 사건을 다시 읽는다. 로봇당 막힘 건수만큼만 자란다.
    stuck_events: dict = field(default_factory=dict)
    #: event_id → 본문 해시. 개발 경로(event_store 없음) 중복 제거 전용.
    seen_event_hashes: dict = field(default_factory=dict)

    def note_event(self, event: EventMessage) -> None:
        """새 이벤트 기록: 최근 창에 넣고, stuck 형식은 인덱스를 갱신한다."""
        self.events.append(event)
        self.seen_event_hashes[event.event_id] = event_content_hash(event)
        if event.type in STUCK_EVENT_TYPES:
            stuck_id = (event.data or {}).get("stuck_id")
            if stuck_id:
                self.stuck_events[(event.type, str(stuck_id))] = event

    def seen_event_hash(self, event: EventMessage) -> Optional[str]:
        """같은 event_id로 본 적이 있으면 그 본문 해시, 처음이면 None."""
        return self.seen_event_hashes.get(event.event_id)

    def stuck_event(self, event_type: str, stuck_id: str) -> Optional[EventMessage]:
        """그 로봇의 (형식, stuck_id) 최근 이벤트. 없으면 None."""
        return self.stuck_events.get((event_type, str(stuck_id)))



class RobotRegistry:
    def __init__(self) -> None:
        self._robots: dict[str, RobotRecord] = {}

    def record(self, robot_id: str) -> RobotRecord:
        row = self._robots.get(robot_id)
        if row is None:
            row = RobotRecord(robot_id=robot_id)
            self._robots[robot_id] = row
        return row

    def find(self, robot_id: str) -> Optional[RobotRecord]:
        """읽기 전용 조회 — gather 가 기록을 새로 만들지 않게 한다 (D-447)."""
        return self._robots.get(robot_id)

    def mark_offline(self, robot_id: str) -> RobotRecord:
        """연결 끊김. 최근 창은 그대로 둔다 — 운영자의 /registry 피드는 링크 재접속으로
        비어서는 안 된다(test_console_hub_integration). 창은 deque(maxlen)으로 이미
        폭이 고정이고, 재접속 뒤 재생 사건은 event_store/seen_event_hashes가 중복으로
        걸러 다시 쌓이지도 않는다(2026-10-28 3분리)."""
        row = self.record(robot_id)
        row.online = False
        return row

    def stuck_event(self, robot_id: str, event_type: str, stuck_id: str) -> Optional[EventMessage]:
        """그 로봇의 (형식, stuck_id) 최근 stuck 이벤트. 없으면 None."""
        row = self._robots.get(robot_id)
        return None if row is None else row.stuck_event(event_type, stuck_id)

    def online_ids(self) -> list[str]:
        return sorted(r.robot_id for r in self._robots.values() if r.online)

    def snapshot(self) -> dict:
        """읽기 전용 전체 조회 — 서버가 private `_robots` 를 직접 건드리지
        않는다. 모양은 hub `/registry` 응답 그대로다."""
        return {
            rid: {
                "online": row.online,
                "snapshot": (row.snapshot.model_dump(mode="json")
                             if row.snapshot else None),
                "events": [e.model_dump(mode="json") for e in row.events],
            }
            for rid, row in self._robots.items()
        }

    def identity_snapshot(self) -> dict[str, dict]:
        """Authenticated HELLO identity, with credentials and serials omitted."""
        return {rid: {"online": row.online, "device_uid": row.device_uid,
                      "device_name": row.device_name}
                for rid, row in self._robots.items()}

    def events_since(self, robot_id: str, since_seq: int) -> list[EventMessage]:
        row = self._robots.get(robot_id)
        if row is None:
            return []
        return [e for e in row.events if e.seq > since_seq]
