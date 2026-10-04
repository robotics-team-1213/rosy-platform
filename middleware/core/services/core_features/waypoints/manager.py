"""core_features.waypoints.manager — WPT-001~005 (P1-16, ADR-D-9).

JSON 로컬 저장소(~/.rosy/waypoints.json), CRUD, 이름 충돌 거부, __home__ 예약(WPT-004).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class Waypoint(BaseModel):
    name: str
    x: float
    y: float
    yaw: float = 0.0
    map_id: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


HOME_NAME = "__home__"


class WaypointError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WaypointManager:
    def __init__(self, path: Path, events=None) -> None:
        self._path = path
        self._events = events
        self._items: dict[str, Waypoint] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            for item in raw.get("waypoints", []):
                wp = Waypoint.model_validate(item)
                self._items[wp.name] = wp

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"waypoints": [w.model_dump() for w in self._items.values()]}
        self._path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def list(self) -> list[Waypoint]:
        return list(self._items.values())

    def get(self, name: str) -> Waypoint:
        if name not in self._items:
            raise WaypointError("NOT_FOUND", f"waypoint '{name}' not found")
        return self._items[name]

    def create(self, wp: Waypoint) -> Waypoint:
        if not wp.name or wp.name.strip() == "":
            raise WaypointError("VALIDATION_ERROR", "waypoint name required")
        if wp.name in self._items:
            raise WaypointError("WAYPOINT_EXISTS", f"waypoint '{wp.name}' already exists")
        self._items[wp.name] = wp
        self._save()
        if self._events:
            self._events.publish("waypoint.created", source="waypoint_manager", data={"name": wp.name})
        return wp

    def update(self, name: str, fields: dict) -> Waypoint:
        current = self.get(name)
        updated = current.model_copy(update={k: v for k, v in fields.items() if k != "name"})
        self._items[name] = updated
        self._save()
        if self._events:
            self._events.publish("waypoint.updated", source="waypoint_manager", data={"name": name})
        return updated

    def delete(self, name: str) -> None:
        self.get(name)
        del self._items[name]
        self._save()
        if self._events:
            self._events.publish("waypoint.deleted", source="waypoint_manager", data={"name": name})
