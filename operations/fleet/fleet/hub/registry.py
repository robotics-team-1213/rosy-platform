"""로봇 기록. 전송·ROS 없음."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from core_common.protocol.schemas import EventMessage, StateSnapshot


@dataclass
class RobotRecord:
    robot_id: str
    online: bool = False
    device_uid: str = ""
    device_name: str = ""
    model: str = ""
    hardware_serial: str = ""
    snapshot: Optional[StateSnapshot] = None
    last_event_seq: int = 0
    events: list[EventMessage] = field(default_factory=list)


class RobotRegistry:
    def __init__(self) -> None:
        self._robots: dict[str, RobotRecord] = {}

    def record(self, robot_id: str) -> RobotRecord:
        row = self._robots.get(robot_id)
        if row is None:
            row = RobotRecord(robot_id=robot_id)
            self._robots[robot_id] = row
        return row

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
