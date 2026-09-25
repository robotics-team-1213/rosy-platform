"""Grid frames for the render path (MAP-003/004): last OccupancyGrid / Path /
Costmap snapshots. Map authoring and persistence are not this module's
concern. ROS-free."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from dataclasses import dataclass
from typing import Any, Optional

_COSTMAP_SCOPES = frozenset({"global", "local"})


@dataclass(frozen=True)
class GridFrame:
    """World-frame occupancy / cost grid. Origin yaw is stored but sampling is axis-aligned."""

    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    origin_yaw: float = 0.0
    data: tuple[int, ...] = ()

    @classmethod
    def from_dict(cls, grid: dict[str, Any]) -> "GridFrame":
        origin = grid.get("origin") or {}
        raw = grid.get("data") or ()
        width = int(grid["width"])
        height = int(grid["height"])
        resolution = float(grid["resolution"])
        data = tuple(int(value) for value in raw)
        if width < 1 or height < 1 or resolution <= 0:
            raise ValueError("grid width, height and resolution must be positive")
        if len(data) != width * height:
            raise ValueError(
                f"grid data length {len(data)} does not match {width}x{height}"
            )
        return cls(
            width=width,
            height=height,
            resolution=resolution,
            origin_x=float(origin.get("x", 0.0)),
            origin_y=float(origin.get("y", 0.0)),
            origin_yaw=float(origin.get("yaw", 0.0)),
            data=data,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "width": self.width,
            "height": self.height,
            "resolution": self.resolution,
            "origin": {
                "x": self.origin_x,
                "y": self.origin_y,
                "yaw": self.origin_yaw,
            },
            "data": list(self.data),
        }

    def world_to_cell(self, x: float, y: float) -> Optional[tuple[int, int]]:
        if self.resolution <= 0 or self.width <= 0 or self.height <= 0:
            return None
        column = math.floor((float(x) - self.origin_x) / self.resolution)
        row = math.floor((float(y) - self.origin_y) / self.resolution)
        if 0 <= column < self.width and 0 <= row < self.height:
            return column, row
        return None

    def sample_world(self, x: float, y: float) -> Optional[int]:
        cell = self.world_to_cell(x, y)
        if cell is None or not self.data:
            return None
        column, row = cell
        index = row * self.width + column
        if index >= len(self.data):
            return None
        return self.data[index]

    def sample_other(self, other: "GridFrame", x: float, y: float) -> Optional[int]:
        return other.sample_world(x, y)


def occupancy_map_id(grid: dict[str, Any]) -> str:
    """Stable id for an occupancy grid so MAP-001 can name an unsaved map."""
    payload = json.dumps(
        {
            "width": grid.get("width"),
            "height": grid.get("height"),
            "resolution": grid.get("resolution"),
            "origin": grid.get("origin") or {},
            "data": list(grid.get("data") or ()),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return f"occupancy:{digest}"


def valid_costmap_scope(scope: str) -> bool:
    return scope in _COSTMAP_SCOPES


class MapSnapshotStore:
    """Bridge writes, REST reads. Missing map/costmap is None, not an empty grid."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._map: Optional[dict[str, Any]] = None
        self._path: list[dict[str, float]] = []
        self._costmaps: dict[str, dict[str, Any]] = {}

    def set_map(self, grid: dict[str, Any]) -> None:
        normalized = GridFrame.from_dict(grid).to_dict()
        with self._lock:
            self._map = normalized

    def get_map(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return None if self._map is None else dict(self._map)

    def set_path(self, poses: list[dict[str, float]]) -> None:
        cleaned: list[dict[str, float]] = []
        for pose in poses:
            x = float(pose["x"])
            y = float(pose["y"])
            if not math.isfinite(x) or not math.isfinite(y):
                raise ValueError("path poses must be finite x,y")
            cleaned.append({"x": x, "y": y})
        with self._lock:
            self._path = cleaned

    def get_path(self) -> list[dict[str, float]]:
        with self._lock:
            return list(self._path)

    def set_costmap(self, scope: str, grid: dict[str, Any]) -> None:
        if not valid_costmap_scope(scope):
            raise ValueError(f"costmap scope must be global or local, got {scope!r}")
        normalized = GridFrame.from_dict(grid).to_dict()
        with self._lock:
            self._costmaps[scope] = normalized

    def get_costmap(self, scope: str) -> Optional[dict[str, Any]]:
        if not valid_costmap_scope(scope):
            raise ValueError(f"costmap scope must be global or local, got {scope!r}")
        with self._lock:
            grid = self._costmaps.get(scope)
            return None if grid is None else dict(grid)
