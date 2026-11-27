"""D-1082 ladder (user 2026-11-28): each recovery resend changes a condition, and an exhausted recovery says why.

2026-11-27 rosy_45 stopped on lower_east 3 cm toward the wall (RPP "collision ahead"); D-1082 resent the same route
at the same speed three times and failed three times. What changes from one resend to the next:

* every resend recentres from where the robot stands, even inside NAV2_ROUTE_MIN_GAP_M
  (``sample_nav2_route(recentre=True)``, through ``recovery_resend``);
* from attempt SLOW_FROM_ATTEMPT on, the resent route runs under the REALIGN_SLOW_MPS road-speed cap
  (``recovery_slow``, read by ``RoadSpeed.renew``): RPP's lookahead and collision projection scale with speed.

An exhausted episode keeps the last stop (lat_m, wall clearance) and each attempt's conditions in
``detail['recovery']``, and marks ``same_spot`` when SAME_SPOT_COUNT stops with one reason lie within SAME_SPOT_M:
the same request resent from there would fail the same way.
"""
from __future__ import annotations

import math

from fleet.server.trip_lane_realign import REALIGN_SLOW_MPS

SLOW_FROM_ATTEMPT = 2
SAME_SPOT_M = 0.05
SAME_SPOT_COUNT = 3


def recovery_slow(detail: dict) -> bool:
    """The resent route of attempt 2 or later runs slow until the episode closes (D-1082 RESET_M of progress past
    the resume): the cap lasts as long as the robot is still where it failed, and no fixed length guesses that."""
    rec = detail.get("recovery") or {}
    return rec.get("state") == "resumed" and rec.get("attempt", 0) >= SLOW_FROM_ATTEMPT


def recovery_resend(live) -> bool:
    """True until a route sent after a recovery resumed is acknowledged (``resent_at``, set by resume_ready): that
    route recentres with no threshold, also when a first try is refused before it goes out."""
    rec = live.view["detail"].get("recovery") or {}
    return rec.get("state") == "resumed" and rec.get("resent_at") is None


def stop_point(live, reason: str, now: float) -> dict:
    """Where a stop happened: the trip pose and the last camera lane judgement (lat_m, wall clearance)."""
    pose = getattr(live, "road_pose", None)
    lane = live.view["detail"].get("lane_departure") or {}
    xy = (None if pose is None or not all(isinstance(v, (int, float)) for v in (pose.x, pose.y))
          else [round(pose.x, 4), round(pose.y, 4)])
    return {"reason": reason, "at": now, "xy": xy, "lat_m": lane.get("lat_m"),
            "wall_clear_m": lane.get("wall_clear_m"), "lane_kind": lane.get("kind")}


def attempt_entry(live, reason: str, attempt: int, now: float) -> dict:
    return {**stop_point(live, reason, now), "attempt": attempt, "recentre": "forced",
            "speed_cap_mps": REALIGN_SLOW_MPS if attempt >= SLOW_FROM_ATTEMPT else None}


def exhaust(live, rec: dict, now: float, reason: str | None = None) -> None:
    """End the episode; ``reason`` is a new stop (one more failure at its spot), None a wait that ran out."""
    rec["state"] = "exhausted"
    final = stop_point(live, reason or rec.get("reason"), now)
    rec["final"] = final
    stops = [*rec.get("attempts", []), *([final] if reason is not None else [])]
    if final["xy"] is None:
        return
    same = [p for p in stops if p.get("reason") == final["reason"] and p.get("xy") is not None
            and math.hypot(p["xy"][0] - final["xy"][0], p["xy"][1] - final["xy"][1]) <= SAME_SPOT_M]
    if len(same) >= SAME_SPOT_COUNT:
        rec["same_spot"] = {"reason": final["reason"], "count": len(same), "xy": final["xy"],
                            "lat_m": final["lat_m"], "wall_clear_m": final["wall_clear_m"]}
