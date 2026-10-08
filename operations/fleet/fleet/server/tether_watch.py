"""D-526: stop a tethered robot through CORE's E-Stop past radius_m + RADIUS_SLACK_M, past TURN_LIMIT_DEG of
turn since the declaration, or after STALE_S without a map pose (an odom-frame pose is none, as on the map).
The trip latches until the tether is set again or cleared; driving back is the operator's (D-526 3).
"""
import asyncio
import logging
import math
import time

PERIOD_S = 0.5
STALE_S = 2.0
#: Backstop slack over the D-512 tool's own limits, so the tool trips and retraces first (D-526 5).
RADIUS_SLACK_M = 0.15
TURN_LIMIT_DEG = 360.0 + 45.0

_LOG = logging.getLogger("fleet.tether_watch")


def map_pose(state) -> tuple[float, float, float] | None:
    """(x, y, yaw) of a CORE state in the map frame, or None (odom frame, missing or not finite)."""
    state = state or {}
    if (state.get("localization") or {}).get("pose_frame") == "odom":
        return None
    pose = state.get("pose") or {}
    try:
        xyyaw = float(pose["x"]), float(pose["y"]), float(pose["yaw"])
    except (KeyError, TypeError, ValueError):
        return None
    return xyyaw if all(map(math.isfinite, xyyaw)) else None


class TetherWatch:
    def __init__(self, tethers: dict, *, pose, stop, clock=time.monotonic) -> None:
        self._tethers, self._pose, self._stop, self._clock = tethers, pose, stop, clock
        self.status: dict[str, dict] = {}

    def reset(self, robot_id: str) -> None:
        self.status.pop(robot_id, None)

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:  # one bad tick must not end the watch
                _LOG.exception("tether watch tick failed")
            await asyncio.sleep(PERIOD_S)

    async def tick(self) -> None:
        for robot_id in [key for key in self.status if key not in self._tethers]:
            del self.status[robot_id]
        await asyncio.gather(*(self._check(rid, row) for rid, row in list(self._tethers.items())))

    async def _check(self, robot_id: str, tether: dict) -> None:
        now = self._clock()
        s = self.status.setdefault(robot_id, {"state": "watching", "trip": None, "distance_m": None,
                                              "turn_deg": 0.0, "pose_age_s": None, "stop_sent": False,
                                              "stop_error": None, "_since": now, "_seen": None, "_yaw": None})
        if s["trip"] is None:
            try:
                pose = await asyncio.wait_for(self._pose(robot_id), PERIOD_S)
            except Exception:  # an unreachable robot is a stale pose
                pose = None
            if pose is not None:
                x, y, yaw = pose
                if s["_yaw"] is not None:
                    s["turn_deg"] += math.degrees(math.remainder(yaw - s["_yaw"], math.tau))
                ax, ay = tether["anchor_xy"]
                s.update(_yaw=yaw, _seen=now, distance_m=round(math.hypot(x - ax, y - ay), 3))
            s["pose_age_s"] = round(now - (s["_seen"] if s["_seen"] is not None else s["_since"]), 2)
            if s["pose_age_s"] > STALE_S:
                s["trip"] = "tether_pose_stale"
            elif s["distance_m"] is not None and s["distance_m"] > tether["radius_m"] + RADIUS_SLACK_M:
                s["trip"] = "tether_radius"
            elif abs(s["turn_deg"]) > TURN_LIMIT_DEG:
                s["trip"] = "tether_turn"
            if s["trip"] is not None:
                s["state"] = "tripped"
                _LOG.warning("tether trip robot=%s trip=%s distance_m=%s turn_deg=%.1f pose_age_s=%s",
                             robot_id, s["trip"], s["distance_m"], s["turn_deg"], s["pose_age_s"])
        if s["trip"] is not None and not s["stop_sent"]:  # retried every tick until CORE answers
            try:
                await self._stop(robot_id)
                s.update(stop_sent=True, stop_error=None)
                _LOG.warning("tether stop sent robot=%s trip=%s", robot_id, s["trip"])
            except Exception as exc:
                s["stop_error"] = getattr(exc, "code", None) or type(exc).__name__
                _LOG.error("tether stop failed robot=%s trip=%s error=%s", robot_id, s["trip"], s["stop_error"])

    def view(self, robot_id: str) -> dict | None:
        s = self.status.get(robot_id)
        return None if s is None else {k: v for k, v in s.items() if not k.startswith("_")}
