"""D-594: Fleet records where each robot went, in map coordinates only. Display and replay only.

Every tick (1 s) one point per roster robot, the first that applies:
1. the robot's own pose when it reports LOCALIZED in the map frame (D-395 ``trust.TRUSTED``):
   state LOCALIZED, source ``robot``;
2. Fleet's map pose (D-494 3 ``MapPoseService.arbitrated_pose``) when LOCALIZED or DEGRADED:
   its state, source ``sighting`` / ``bridged``;
3. the ceiling-camera track (D-457, display-only): a MARKER row, or a MATCHED row whose pose
   is a verified map pose: state CAMERA_ONLY, source ``tracking``.
Anything else (a ``localization: null`` pose, which may be odom; UNKNOWN) is not a map point.

A point is written when the robot moved ``MIN_STEP_M`` from the last written one, its state,
source, map, trip or formation changed, or ``HEARTBEAT_S`` passed. A tick without a point ends
the segment: the next point opens a new ``seg``. Traffic, routes, trips and stops never read it.
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Mapping, Optional

from fastapi import HTTPException, Query

from fleet.localization.map_pose import DEGRADED, LOCALIZED
from fleet.localization.trust import trusted_xy
from fleet.server.sqlite_policy import configure_connection, enable_wal

CAMERA_ONLY = "CAMERA_ONLY"
PERIOD_S = 1.0
MIN_STEP_M = 0.02
HEARTBEAT_S = 30.0
RETENTION_S = 24 * 3600.0
MAX_POINTS_PER_ROBOT = 86_400
MAX_RESPONSE_POINTS = 5_000
PRUNE_EVERY_S = 60.0
#: Fields whose change writes a point even when the robot stood still.
_TAGS = ("state", "source", "map_id", "trip_id", "formation_id")
_COLUMNS = ("t", "x", "y", "state", "source", "seg", "map_id", "trip_id", "formation_id")

_LOG = logging.getLogger("fleet.path_history")


class PathStore:
    """``fleet_robot_path`` in the site SQLite file (``--tasks-db``), or in memory without one."""

    def __init__(self, path: Optional[Path | str] = None) -> None:
        self.path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._memory = (sqlite3.connect(":memory:", check_same_thread=False)
                        if self.path is None else None)
        with self._db() as db:
            if self.path is not None:
                enable_wal(db)
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS fleet_robot_path (
                    robot_id TEXT NOT NULL, t REAL NOT NULL, x REAL NOT NULL, y REAL NOT NULL,
                    state TEXT NOT NULL, source TEXT NOT NULL, seg INTEGER NOT NULL,
                    map_id TEXT, trip_id TEXT, formation_id TEXT);
                CREATE INDEX IF NOT EXISTS fleet_robot_path_robot_t ON fleet_robot_path(robot_id, t);
                CREATE INDEX IF NOT EXISTS fleet_robot_path_trip ON fleet_robot_path(trip_id, t)
                    WHERE trip_id IS NOT NULL;
                """)

    @contextmanager
    def _db(self):
        if self._memory is not None:
            with self._lock, self._memory:
                yield self._memory
            return
        connection = configure_connection(sqlite3.connect(self.path, timeout=5.0))
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def append(self, rows: Iterable[Mapping]) -> None:
        with self._db() as db:
            db.executemany(
                f"INSERT INTO fleet_robot_path(robot_id, {', '.join(_COLUMNS)}) "
                f"VALUES (?, {', '.join('?' * len(_COLUMNS))})",
                [(row["robot_id"], *(row[key] for key in _COLUMNS)) for row in rows])

    def prune(self, now: float) -> None:
        """Drop points older than ``RETENTION_S`` and beyond ``MAX_POINTS_PER_ROBOT`` per robot."""
        with self._db() as db:
            db.execute("DELETE FROM fleet_robot_path WHERE t < ?", (now - RETENTION_S,))
            for (robot_id,) in db.execute("SELECT DISTINCT robot_id FROM fleet_robot_path").fetchall():
                db.execute(
                    """DELETE FROM fleet_robot_path WHERE robot_id = ? AND t < (
                         SELECT t FROM fleet_robot_path WHERE robot_id = ?
                         ORDER BY t DESC LIMIT 1 OFFSET ?)""",
                    (robot_id, robot_id, MAX_POINTS_PER_ROBOT - 1))

    def query(self, robot_id: str, *, since: float, until: float, trip_id: Optional[str] = None,
              limit: Optional[int] = None) -> tuple[list[dict], bool]:
        """Points in ``[since, until]`` oldest first; the newest ``limit`` when there are more."""
        limit = MAX_RESPONSE_POINTS if limit is None else limit
        sql = (f"SELECT {', '.join(_COLUMNS)} FROM fleet_robot_path "
               "WHERE robot_id = ? AND t >= ? AND t <= ?")
        args: list = [robot_id, since, until]
        if trip_id is not None:
            sql += " AND trip_id = ?"
            args.append(trip_id)
        with self._db() as db:
            rows = db.execute(sql + " ORDER BY t DESC LIMIT ?", (*args, limit + 1)).fetchall()
        points = [dict(zip(_COLUMNS, row)) for row in rows[:limit]]
        points.reverse()
        return points, len(rows) > limit


class PathRecorder:
    def __init__(self, store: PathStore, *, roster: Callable[[], Iterable[str]],
                 gather: Callable[[str], Awaitable[Optional[Mapping]]], map_pose=None, tracking=None,
                 trips: Callable[[], Iterable[Mapping]] = tuple,
                 formation: Callable[[], Optional[Mapping]] = lambda: None,
                 wall: Callable[[], float] = time.time) -> None:
        self.store = store
        self._roster = roster
        self._gather = gather            # the robot's state: hub snapshot when fresh, else REST
        self._map_pose = map_pose        # MapPoseService (arbitrated_pose)
        self._tracking = tracking        # TrackingService when enabled, else None
        self._trips = trips              # TripRunner.open_trips
        self._formation = formation      # FleetConsole.formation_status
        self.wall = wall
        self._last: dict[str, dict] = {}
        self._formation_id: Optional[str] = None
        self._pruned_at = -math.inf

    def knows(self, robot_id: str) -> bool:
        return robot_id in set(self._roster())

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:           # one bad tick must not end the record
                _LOG.exception("path history tick failed")
            await asyncio.sleep(PERIOD_S)

    async def tick(self) -> None:
        now = self.wall()
        roster = list(self._roster())
        states = await asyncio.gather(*(self._read(robot_id) for robot_id in roster))
        rows = self.sample(now, dict(zip(roster, states)))
        if rows:
            await asyncio.to_thread(self.store.append, rows)
        if now - self._pruned_at >= PRUNE_EVERY_S:
            self._pruned_at = now
            await asyncio.to_thread(self.store.prune, now)

    async def _read(self, robot_id: str) -> Optional[Mapping]:
        try:
            return await asyncio.wait_for(self._gather(robot_id), PERIOD_S)
        except Exception:               # an unreachable robot has no robot-reported point
            return None

    def sample(self, now: float, states: Mapping[str, Optional[Mapping]]) -> list[dict]:
        """The rows to write for this tick (pure apart from the downsample memory)."""
        for gone in set(self._last) - set(states):
            del self._last[gone]
        camera = self._camera()
        trips = {view.get("robot_id"): view.get("trip_id") for view in self._trips()}
        formations = self._formation_tags(now)
        rows = []
        for robot_id, state in states.items():
            point = self._point(robot_id, state, camera.get(robot_id))
            if point is None:
                self._last.pop(robot_id, None)    # the next point opens a new segment
                continue
            row = {"robot_id": robot_id, "t": now, **point, "trip_id": trips.get(robot_id),
                   "formation_id": formations.get(robot_id)}
            last = self._last.get(robot_id)
            row["seg"] = int(now * 1000) if last is None else last["seg"]
            if (last is None or math.dist((row["x"], row["y"]), (last["x"], last["y"])) >= MIN_STEP_M
                    or any(row[key] != last[key] for key in _TAGS) or now - last["t"] >= HEARTBEAT_S):
                self._last[robot_id] = row
                rows.append(row)
        return rows

    def _point(self, robot_id: str, state: Optional[Mapping], camera: Optional[dict]) -> Optional[dict]:
        xy = trusted_xy(state)
        if xy is not None and all(math.isfinite(v) for v in xy):
            return {"x": xy[0], "y": xy[1], "state": LOCALIZED, "source": "robot",
                    "map_id": (state or {}).get("map_id")}
        pose = self._map_pose.arbitrated_pose(robot_id) if self._map_pose is not None else None
        if pose is not None and pose.state in (LOCALIZED, DEGRADED) and pose.x is not None:
            return {"x": pose.x, "y": pose.y, "state": pose.state, "source": pose.source or "sighting",
                    "map_id": pose.map_id}
        return camera

    def _camera(self) -> dict[str, dict]:
        """D-457 display-only positions: a marker, or a blob matched to a verified map pose."""
        if self._tracking is None:
            return {}
        snapshot = self._tracking.snapshot()
        maps = {source["source_id"]: source.get("map_id") for source in snapshot.get("sources", ())}
        out = {}
        for row in snapshot.get("robots", ()):
            seen = row.get("camera")
            if seen is None or not (row.get("status") == "MARKER" or (
                    row.get("status") == "MATCHED" and row.get("pose_frame_verified") is True)):
                continue
            out[row["robot_id"]] = {"x": seen["x"], "y": seen["y"], "state": CAMERA_ONLY,
                                    "source": "tracking", "map_id": maps.get(row.get("source_id"))}
        return out

    def _formation_tags(self, now: float) -> dict[str, str]:
        status = self._formation() or {}
        if not status.get("active"):
            self._formation_id = None
            return {}
        if self._formation_id is None:
            self._formation_id = f"formation-{int(now * 1000)}"
        members = {status.get("leader"), *(status.get("assignment") or {})} - {None}
        return {robot_id: self._formation_id for robot_id in members}


def install_path_routes(app, *, paths: PathRecorder, read_guard) -> None:
    def bad(message: str) -> HTTPException:
        return HTTPException(status_code=422, detail={"code": "BAD_PATH_RANGE", "message": message})

    @app.get("/api/fleet/robots/{robot_id}/path", dependencies=read_guard, tags=["fleet"])
    async def robot_path(robot_id: str,
                         since: Optional[float] = Query(None, ge=0),
                         until: Optional[float] = Query(None, ge=0),
                         last_s: Optional[float] = Query(None, gt=0, le=RETENTION_S),
                         trip_id: Optional[str] = Query(None, min_length=1, max_length=128)) -> dict:
        if not paths.knows(robot_id):
            raise HTTPException(status_code=404, detail={"code": "UNKNOWN_ROBOT",
                                                         "message": "robot is not on the roster"})
        if any(v is not None and not math.isfinite(v) for v in (since, until, last_s)):
            raise bad("since, until and last_s must be finite")
        if since is not None and last_s is not None:
            raise bad("give since or last_s, not both")
        now = paths.wall()
        start = now - last_s if last_s is not None else since if since is not None else now - RETENTION_S
        end = until if until is not None else now
        if end < start:
            raise bad("until is before since")
        points, truncated = await asyncio.to_thread(
            paths.store.query, robot_id, since=start, until=end, trip_id=trip_id)
        for point in points:
            point["x"], point["y"] = round(point["x"], 4), round(point["y"], 4)
        return {"robot_id": robot_id, "now": now, "retention_s": RETENTION_S,
                "use": "display-only", "truncated": truncated, "points": points}
