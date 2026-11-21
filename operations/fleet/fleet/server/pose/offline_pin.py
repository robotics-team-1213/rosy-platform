"""Offline parked-robot operator pin store and site-frame pose helpers for traffic clearance."""

from __future__ import annotations

import math
from typing import Optional

from rosy.world.state.projections.map_pose import LOCALIZED

SitePose = tuple[str, float, float, float]


def _finite_pose(pose: tuple[float, float, float]) -> bool:
    return (
        len(pose) == 3
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in pose)
    )


class OfflinePinStore:
    """In-memory operator pins for powered-off parked robots (cleared on any live state report)."""

    def __init__(self) -> None:
        self._pins: dict[str, SitePose] = {}

    def pin(
        self,
        robot_id: str,
        pose: tuple[float, float, float],
        *,
        knows: bool,
        active_map_id: Optional[str],
        robot_online: bool,
    ) -> tuple[Optional[str], Optional[dict]]:
        if not knows:
            return "UNKNOWN_ROBOT", None
        if not _finite_pose(pose):
            return "POSE_INVALID", None
        if active_map_id is None:
            return "NO_ACTIVE_MAP", None
        if robot_online:
            return "ROBOT_ONLINE", None
        x, y, yaw = float(pose[0]), float(pose[1]), float(pose[2])
        self._pins[robot_id] = (active_map_id, x, y, yaw)
        return None, {
            "robot_id": robot_id,
            "state": "OFFLINE_PARKED",
            "x": x,
            "y": y,
            "yaw": yaw,
            "map_id": active_map_id,
            "anchor_source": "operator_pin_offline",
        }

    def clear(self, robot_id: str) -> None:
        self._pins.pop(robot_id, None)

    def prune(self, roster: set[str]) -> None:
        for gone in set(self._pins) - roster:
            del self._pins[gone]

    def pose_on(self, robot_id: str, active_map_id: Optional[str]) -> Optional[SitePose]:
        if active_map_id is None:
            return None
        row = self._pins.get(robot_id)
        return row if row is not None and row[0] == active_map_id else None


def mover_site_pose(service, robot_id: str) -> Optional[SitePose]:
    """Live LOCALIZED site pose on the active site map; never reads offline pins."""
    active = service.active_map_id()
    if active is None:
        return None
    pose = service.arbitrated_pose(robot_id)
    if pose is None or pose.state != LOCALIZED or pose.map_id != active:
        return None
    vals = (pose.x, pose.y, pose.yaw)
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in vals):
        return None
    return (active, float(pose.x), float(pose.y), float(pose.yaw))


def obstacle_site_pose(service, robot_id: str) -> Optional[SitePose]:
    """Measured site pose (online LOCALIZED or offline-parked pin) on the active site map."""
    live = mover_site_pose(service, robot_id)
    if live is not None:
        return live
    return service._offline_pins.pose_on(robot_id, service.active_map_id())
