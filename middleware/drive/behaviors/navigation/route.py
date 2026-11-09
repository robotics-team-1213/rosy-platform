"""NAV-008 route drive (D-1009): one request, ordered points, each `pass` or `stop`. ROS-free.

A route is cut at its `stop` points. Each cut is one Nav2 action (NavigateThroughPoses when the leg has
pass points, NavigateToPose when it has none): the robot drives through the pass points without
stopping and halts only at the stop that ends the leg. The whole route is ONE native run, one
correlation id and one lease, so Fleet sends it once and never meets 409 NAVIGATION_ACTIVE between points.

Skip rules (pass points only; a stop point is never skipped):
  1. a pass point inside a lethal/inscribed/unknown/off-grid global-costmap cell is dropped before the leg is sent;
  2. a leg that fails with pass points still ahead is resent without the first of them.
A route fails when a leg without pass points fails, or when NAV-006 (no progress) cancels it.
Functions are bound onto `NavigationManager` (manager.py is at its size limit).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

PASS, STOP = "pass", "stop"
MAX_POINTS = 64
#: costmap values from here up are inscribed (253), lethal (254) or unknown (255).
BLOCKED_COST = 253
#: a pass point this close to the pose counts as passed. Display and skip bookkeeping only; Nav2's BT
#: removes passed points from its own list.
PASSED_RADIUS_M = 0.12


@dataclass
class RoutePoint:
    x: float
    y: float
    kind: str = STOP
    yaw: Optional[float] = None
    state: str = "pending"  # pending | reached | skipped | stopped


@dataclass
class RouteRun:
    points: list[RoutePoint]
    run_id: Optional[UUID] = None
    leg_first: int = 0       # first point of the current leg
    leg_end: int = 0         # the stop that ends it
    stops_made: int = 0
    actions: int = 0         # Nav2 actions sent (legs plus resends)
    result: Optional[str] = None  # None while active, then succeeded | failed | canceled
    skipped: list[int] = field(default_factory=list)


def _blocked(grid: Optional[dict], x: float, y: float) -> bool:
    if not grid:
        return False
    origin = grid.get("origin") or {}
    dx, dy = x - float(origin.get("x", 0.0)), y - float(origin.get("y", 0.0))
    yaw = float(origin.get("yaw", 0.0))
    col = math.floor((math.cos(yaw) * dx + math.sin(yaw) * dy) / grid["resolution"])
    row = math.floor((-math.sin(yaw) * dx + math.cos(yaw) * dy) / grid["resolution"])
    if not (0 <= col < grid["width"] and 0 <= row < grid["height"]):
        return True
    return grid["data"][row * grid["width"] + col] >= BLOCKED_COST


def _heading(a, b) -> float:
    return math.atan2(b.y - a.y, b.x - a.x)


def _leg_spec(self, run: RouteRun):
    """The Nav2 goal for the current leg. Marks pass points that sit in an obstacle as skipped."""
    from .manager import NavGoalSpec
    grid = self.costmap_provider()
    pts, end = run.points, run.leg_end
    kept = []
    for i in range(run.leg_first, end):
        if pts[i].state != "pending":
            continue
        if _blocked(grid, pts[i].x, pts[i].y):
            pts[i].state = "skipped"
            run.skipped.append(i)
        else:
            kept.append(pts[i])
    chain = kept + [pts[end]]
    via = tuple(NavGoalSpec(p.x, p.y, _heading(p, chain[n + 1])) for n, p in enumerate(kept))
    stop = pts[end]
    before = kept[-1] if kept else (pts[end - 1] if end > 0 else None)
    yaw = stop.yaw if stop.yaw is not None else (_heading(before, stop) if before is not None else 0.0)
    return NavGoalSpec(stop.x, stop.y, yaw, via=via)


def _next_stop(run: RouteRun, start: int) -> int:
    return next(i for i in range(start, len(run.points)) if run.points[i].kind == STOP)


def _validated(points) -> list[RoutePoint]:
    from .manager import NavigationError
    pts = list(points)
    if not 1 <= len(pts) <= MAX_POINTS:
        raise NavigationError("VALIDATION_ERROR", f"a route takes 1..{MAX_POINTS} points")
    for p in pts:
        if p.kind not in (PASS, STOP) or not (math.isfinite(p.x) and math.isfinite(p.y)):
            raise NavigationError("VALIDATION_ERROR", "route points need finite x, y and kind pass|stop")
        if p.yaw is not None and not math.isfinite(p.yaw):
            raise NavigationError("VALIDATION_ERROR", "route point yaw must be finite")
    if pts[-1].kind != STOP:
        raise NavigationError("VALIDATION_ERROR", "the last route point must be a stop")
    return pts


def route(self, points, source: str = "api", correlation_id: str | None = None,
          lease_ttl_s: float | None = None, *, receipt_sink=None, lease_owner: str | None = None,
          expected_boot_id: UUID | None = None, expected_owner_generation: int | None = None,
          reservation: UUID | None = None) -> RouteRun:
    """Admit a route like a goal (same gates, receipt and lease) and send its first leg."""
    run = RouteRun(_validated(points))
    with self._lock:
        run.leg_end = _next_stop(run, 0)
        self.goal(_leg_spec(self, run), source=source, correlation_id=correlation_id,
                  lease_ttl_s=lease_ttl_s, lease_owner=lease_owner, receipt_sink=receipt_sink,
                  expected_boot_id=expected_boot_id, expected_owner_generation=expected_owner_generation,
                  reservation=reservation)
        current = self.native.current
        run.run_id = current.run_id if current is not None else None
        run.actions = 1
        self._route = run
    return run


def route_continue(self, succeeded: bool, error: str | None, native_run_id: UUID | None) -> bool:
    """A Nav2 action of the route ended. True when the next action is out and the run goes on;
    False hands the end (arrived or failed) to the normal result path."""
    with self._lock:
        run = self._route
        if run is None or run.result is not None:
            return False
        if native_run_id is not None and run.run_id != native_run_id:
            return False
        if succeeded:
            run.points[run.leg_end].state = "stopped"
            run.stops_made += 1
            for i in range(run.leg_first, run.leg_end):
                if run.points[i].state == "pending":
                    run.points[i].state = "reached"
            if run.leg_end + 1 >= len(run.points):
                run.result = "succeeded"
                return False
            run.leg_first = run.leg_end + 1
            run.leg_end = _next_stop(run, run.leg_first)
        else:
            ahead = [i for i in range(run.leg_first, run.leg_end) if run.points[i].state == "pending"]
            if not ahead:
                run.result = "failed"
                return False
            run.points[ahead[0]].state = "skipped"
            run.skipped.append(ahead[0])
        try:
            spec = _leg_spec(self, run)
            send = getattr(self.executor, "send_native_goal", None)
            cid = self._active_correlation_id
            if send is not None:
                send(spec, run.run_id, correlation_id=cid)
            elif cid is None:
                self.executor.send_goal(spec)
            else:
                self.executor.send_goal(spec, correlation_id=cid)
        except Exception:
            run.result = "failed"
            return False
        self._active_spec = spec  # fleet_goal() (SAF-003) follows the leg in progress
        run.actions += 1
        return True


def route_progress(self, x: float, y: float) -> None:
    run = self._route
    if run is None or run.result is not None:
        return
    for i in range(run.leg_first, run.leg_end):
        p = run.points[i]
        if p.state == "pending" and math.hypot(p.x - x, p.y - y) <= PASSED_RADIUS_M:
            p.state = "reached"


def route_closed(self, result: str) -> None:
    run = self._route
    if run is not None and run.result is None:
        run.result = result


def route_status(self) -> Optional[dict]:
    """What navigation/state shows: the current leg, the next stop, the points still ahead."""
    with self._lock:
        run = self._route
        if run is None:
            return None
        active = run.result is None
        stop = run.points[run.leg_end]
        return {
            "correlation_id": self._active_correlation_id if active else None,
            "run_id": str(run.run_id) if run.run_id else None,
            "active": active, "result": run.result,
            "legs": sum(p.kind == STOP for p in run.points), "leg": run.stops_made,
            "stops_made": run.stops_made, "actions": run.actions,
            "next_stop": {"index": run.leg_end, "x": stop.x, "y": stop.y} if active else None,
            "remaining": sum(p.state == "pending" for p in run.points),
            "skipped": list(run.skipped),
            "points": [{"x": p.x, "y": p.y, "kind": p.kind, "state": p.state} for p in run.points],
        }
