"""Directly owned, bounded read projections from existing Fleet producers."""

import asyncio
from collections.abc import Mapping
from contextlib import closing
from datetime import datetime, timezone
import math
from pathlib import Path
import re
import sqlite3
import time

from core_common.protocol.integrated_control import (
    ControlDispatchFence, ControlMapLane, ControlMapPlace, ControlMapPoint,
    ControlMapRef, ControlMapSnapshot, ControlRobotInfo, ControlRobotPose,
    ControlTaskInfo, ControlUnitDetail, ControlUnitSummary,
)


_CHANNELS = ("pose", "battery", "safety")
_EVIDENCE = {"fresh", "delayed", "disconnected", "unavailable", "unknown"}
_USABLE = {"fresh", "delayed"}
_MAP_ID = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_STALE_AFTER_S = 5.0  # Same observation bound as existing control-unit delegation reads.


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _number(value):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _robot(robot_id, row, now):
    row = _mapping(row)
    online = row.get("online") is True
    state = _mapping(row.get("state"))
    evidence = {}
    for channel in _CHANNELS:
        value = _mapping(_mapping(state.get("evidence")).get(channel)).get("evidence")
        evidence[channel] = value if isinstance(value, str) and value in _EVIDENCE else "unknown"
    observed = row.get("_state_mono")
    age = now - observed if _number(observed) and 0 <= observed <= now else None
    mode = state.get("mode")
    if not online or not isinstance(mode, str) or not 1 <= len(mode) <= 32:
        mode = None
    battery = _mapping(state.get("battery")).get("percent")
    if not online or evidence["battery"] not in _USABLE or not _number(battery) or not 0 <= battery <= 100:
        battery = None
    estop = _mapping(state.get("safety")).get("estop")
    if not online or evidence["safety"] not in _USABLE or type(estop) is not bool:
        estop = None
    pose = None
    localization, raw_pose = _mapping(state.get("localization")), _mapping(state.get("pose"))
    map_id = state.get("map_id")
    if (online and evidence["pose"] in _USABLE
            and localization.get("state") == "LOCALIZED" and localization.get("pose_frame") == "map"
            and isinstance(map_id, str) and _MAP_ID.fullmatch(map_id)
            and all(_number(raw_pose.get(key)) for key in ("x", "y", "yaw"))):
        pose = ControlRobotPose(x=raw_pose["x"], y=raw_pose["y"], yaw=raw_pose["yaw"],
                                map_id=map_id, source="core", frame="map")
    return ControlRobotInfo(robot_id=robot_id, online=online, state_age_s=age, mode=mode,
                            battery_percent=battery, estop=estop, pose=pose, evidence=evidence)


def _task_projection(store, robot_ids):
    if store is None:
        return [], False, 0, None
    # A separate read-only connection neither configures nor migrates the shared ledger.
    uri = Path(store.path).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True, timeout=1.0)) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        fence = connection.execute(
            "SELECT authority_epoch,generation FROM fleet_dispatch_control WHERE control_id=1").fetchone()
        if fence is None:
            raise ValueError("CONTROL_UNIT_DISPATCH_UNAVAILABLE")
        dispatch = ControlDispatchFence(**dict(fence))
        rows, active = [], 0
        if robot_ids:
            placeholders = ",".join("?" for _ in robot_ids)
            ownership = f"robot_id IN ({placeholders})"
            active = connection.execute(
                "SELECT COUNT(*) FROM fleet_tasks WHERE " + ownership
                + " AND status IN ('REQUESTED','QUEUED','ACCEPTED','RUNNING','UNKNOWN','HOLD')",
                robot_ids).fetchone()[0]
            rows = connection.execute(
                "SELECT task_id,robot_id,status,updated_at FROM fleet_tasks WHERE " + ownership
                + " ORDER BY updated_at DESC,task_id DESC LIMIT 101", robot_ids).fetchall()
    return [ControlTaskInfo(**dict(row)) for row in rows[:100]], len(rows) > 100, active, dispatch


def _map_reference(active):
    if active is None:
        return None
    version, model, _, _ = active
    return ControlMapRef(map_id=model.map_id, version=version, frame="unit_local")


class LocalControlInformation:
    """Callbacks bind late to SharedGather and SiteMapStore.active; errors stay explicit.

    ``sampled_at`` returns SharedGather.gathered_at, in wall epoch seconds. ``clock``
    is the console's monotonic clock used by its _state_mono values.
    """

    def __init__(self, config, *, gather, tasks, map_snapshot, clock, sampled_at,
                 wall_clock=time.time, pending_stops=None):
        self.config, self.gather, self.tasks = config, gather, tasks
        self.map_snapshot, self.clock = map_snapshot, clock
        self.sampled_at, self.wall_clock = sampled_at, wall_clock
        self.pending_stops = pending_stops
        self.unit = config.topology.unit(config.unit_id)
        self.robot_ids = tuple(sorted(resource[6:] for resource in self.unit.resources
                                      if resource.startswith("robot:")))

    async def read(self):
        """One SharedGather read returns the local summary and detail canonical models."""
        snapshot = await self.gather()
        stamp, wall_now, mono_now = self.sampled_at(), self.wall_clock(), self.clock()
        if (not _number(stamp) or not _number(wall_now) or not 0 < stamp <= wall_now
                or not _number(mono_now)):
            raise ValueError("CONTROL_UNIT_INVALID_SAMPLE_TIME")
        sampled_at = datetime.fromtimestamp(stamp, timezone.utc)
        if not isinstance(snapshot, Mapping) or not isinstance(snapshot.get("robots"), list):
            raise ValueError("CONTROL_UNIT_INVALID_GATHER")
        rows = {}
        for row in snapshot["robots"]:
            if isinstance(row, Mapping) and row.get("robot_id") in self.robot_ids:
                if row["robot_id"] in rows:
                    raise ValueError("CONTROL_UNIT_DUPLICATE_ROBOT")
                rows[row["robot_id"]] = row
        tasks, truncated, active, dispatch = await asyncio.to_thread(_task_projection, self.tasks, self.robot_ids)
        pending = await asyncio.to_thread(self.pending_stops) if self.pending_stops is not None else 0
        robots = [_robot(identity, rows.get(identity), self.clock()) for identity in self.robot_ids]
        reference = _map_reference(self.map_snapshot())
        age = max(0.0, self.wall_clock() - stamp)
        availability = "AVAILABLE" if age <= _STALE_AFTER_S else "STALE"
        if availability != "AVAILABLE":
            dispatch = None
        common = dict(unit_id=self.unit.unit_id, availability=availability,
                      sampled_at=sampled_at, age_s=age, map=reference, dispatch=dispatch)
        summary = ControlUnitSummary(**common, parent=self.unit.parent, robots_total=len(robots),
                                     robots_online=sum(robot.online for robot in robots),
                                     tasks_active=active, error=None, stop_pending=pending)
        detail = ControlUnitDetail(**common, config_revision=self.config.topology.revision,
                                   robots=robots, tasks=tasks, tasks_truncated=truncated)
        return summary, detail

    def map(self):
        """Project only active unit-local places and lane polylines, without metadata."""
        active = self.map_snapshot()
        if active is None:
            return None
        _, model, _, _ = active
        if (len(model.places) > 500 or len(model.edges) > 1000
                or sum(len(edge.polyline) for edge in model.edges) > 20_000):
            raise ValueError("CONTROL_UNIT_MAP_TOO_LARGE")
        places = [ControlMapPlace(id=place.id, label=place.name, x=place.x, y=place.y) for place in model.places]
        lanes = [ControlMapLane(id=edge.id, points=[ControlMapPoint(x=x, y=y) for x, y in edge.polyline])
                 for edge in model.edges]
        return ControlMapSnapshot(unit_id=self.unit.unit_id, config_revision=self.config.topology.revision,
                                  map=_map_reference(active), places=places, lanes=lanes)
