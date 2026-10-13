"""D-577 (d) deadlock, livelock and stall analyzer over Fleet's traffic table and robot states (shadow).

Facts only (D-577 3), deterministic over the polled snapshot sequence (``observed_at``, ``state``,
``traffic``, ``line_stuck``). It cross-checks Fleet's own M4 resolver (D-517 5): Fleet's ``wait_cycle`` is
"any holder waits", so this side looks at what the robots actually do over time.

- ``wait_cycle_confirmed``: a wait cycle (Fleet's, or one in the table's own waits) seen ``CYCLE_SNAPSHOTS``
  snapshots in a row with every member still. ``value.fleet_agrees`` is false when Fleet's ``wait_cycle``
  and the table's waits name different robots (e.g. Fleet sees no cycle).
- ``wait_cycle_stale_input``: a cycle member's input is not fresh (offline, state older than 2 s, not placed
  on its route, or it holds an UNKNOWN unit): the cycle may come from a stale pose.
- ``waiting_but_moving``: a robot the table holds (cycle member, Fleet resolver row, or at its authority end
  with a refused unit) whose odom moved more than ``MOVED_M`` within ``WAIT_MOVE_S``.
- ``livelock``: the same cycle formed ``REFORM_N`` times within ``REFORM_WINDOW_S``, or a trip robot moving
  (odom path) or commanded for ``LIVELOCK_S`` without ``MOVED_M`` of route progress.
- ``stalled``: a running trip robot with authority ahead, no refused unit and no open stuck that has not
  moved ``MOVED_M`` for ``STALL_S``; ``value`` names the units (and zones) it holds and who waits on them.
- ``unknown_occupancy_long``: a unit UNKNOWN for longer than ``UNKNOWN_S`` (Fleet's M4 says the same).

Route progress is Fleet's ``front_d_m`` from its map pose; a stale map pose Fleet still reports as placed
can read as no progress (ponytail: no map pose age in the snapshot; add it to /traffic if livelock misfires).
"""

from __future__ import annotations

import math
from collections import deque
from typing import Optional

VERSION = "1"
SOURCE = f"analyzer:traffic_watch@{VERSION}"
TTL_S = 3.0
MOVED_M = 0.05             # D-577 (d): stalled / waiting_but_moving / livelock progress
CYCLE_SNAPSHOTS = 3        # D-577 (d) wait_cycle_confirmed
STATE_STALE_S = 2.0        # D-577 (d) wait_cycle_stale_input
WAIT_MOVE_S = 2.0          # D-577 (d) waiting_but_moving
REFORM_N, REFORM_WINDOW_S = 3, 60.0
LIVELOCK_S, LIVELOCK_PATH_M, STEP_M = 20.0, 0.10, 0.02
REFORM_GAP = 2             # snapshots a cycle must be gone before it counts as re-formed (not a flicker)
#: Fleet refuses a whole facts post over one command word or > 16 robot ids (ai_facts.py); a bad traffic fact
#: must never take a stuck_scene acting fact down with it, so such a fact is dropped here.
COMMAND_WORDS = frozenset({"WAIT", "RESUME", "BACK_AND_RETRY", "YIELD", "ABORT", "MANUAL", "STOP", "GO"})
MAX_IDS = 16
STALL_S = 20.0             # same as the trip stall rule
UNKNOWN_S = 30.0           # same as M4 UNKNOWN_LIMIT_S


def _xy(row: Optional[dict]) -> Optional[tuple[float, float]]:
    pose = ((row or {}).get("state") or {}).get("pose") or {}
    try:
        return float(pose["x"]), float(pose["y"])
    except (KeyError, TypeError, ValueError):
        return None


def _words(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _words(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _words(item)


def _sendable(fact: dict) -> bool:
    return len(fact["robot_ids"]) <= MAX_IDS and not any(
        w.strip().upper() in COMMAND_WORDS for w in _words([fact["value"], fact["evidence"]]))


def _cycle(waits: dict[str, set]) -> Optional[frozenset]:
    """One cycle in "robot waits for robot" (sorted walk, so the same table gives the same cycle)."""
    colour: dict[str, int] = {}
    for start in sorted(waits):
        if colour.get(start):
            continue
        colour[start], path, stack = 1, [start], [iter(sorted(waits.get(start, ())))]
        while stack:
            nxt = next(stack[-1], None)
            if nxt is None:
                colour[path.pop()] = 2
                stack.pop()
            elif colour.get(nxt) == 1:
                return frozenset(path[path.index(nxt):])
            elif not colour.get(nxt):
                colour[nxt] = 1
                path.append(nxt)
                stack.append(iter(sorted(waits.get(nxt, ()))))
    return None


class TrafficWatch:
    def __init__(self) -> None:
        self._track: dict[str, deque] = {}          # robot -> (t, xy) for the last WAIT_MOVE_S
        self._cycle: tuple = (frozenset(), 0, 0.0, {})   # members, snapshots in a row, since, xy at since
        self._formed: dict[frozenset, deque] = {}
        self._gone = REFORM_GAP                     # snapshots since the last cycle was seen
        self._wait_since: dict[str, float] = {}
        self._progress: dict[str, list] = {}        # robot -> [since, d0, path_m, last xy, always commanded]
        self._still: dict[str, tuple] = {}
        self._unknown: dict[str, float] = {}

    def __call__(self, snapshot: dict) -> list[dict]:
        now = float(snapshot.get("observed_at") or 0.0)
        rows = {str(r["robot_id"]): r for r in (snapshot.get("state") or {}).get("robots") or [] if r.get("robot_id")}
        traffic = snapshot.get("traffic") or {}
        trips = {str(r["robot_id"]): r for r in traffic.get("robots") or [] if r.get("robot_id")}
        units = traffic.get("units") or []
        stuck = {str(p.get("robot_id")) for p in (snapshot.get("line_stuck") or {}).get("pending") or []}
        resolver = {str(r.get("robot_id")): r for r in traffic.get("resolver") or []}
        facts: list[dict] = []

        def fact(kind, robot_ids, value, confidence, evidence):
            facts.append({"kind": kind, "robot_ids": list(robot_ids), "value": value, "confidence": confidence,
                          "evidence": evidence, "source": SOURCE, "observed_at": now, "ttl_s": TTL_S})

        xy = {rid: _xy(row) for rid, row in rows.items()}
        for rid, here in xy.items():
            track = self._track.setdefault(rid, deque())
            if here is not None:
                track.append((now, here))
            while track and now - track[0][0] > WAIT_MOVE_S + 1e-6:
                track.popleft()

        def moved(rid, since_xy) -> float:
            return math.dist(xy[rid], since_xy) if xy.get(rid) and since_xy else math.inf  # unknown: not still

        def refused(rid) -> list:
            return [w for w in trips.get(rid, {}).get("waiting_for") or [] if not str(w).startswith("signal:")]

        waits: dict[str, set] = {rid: set(refused(rid)) for rid in trips}
        for unit in units:
            for rid in unit.get("waiting") or []:
                waits.setdefault(rid, set()).update(h for h in unit.get("holders") or [] if h != rid)
        held_unknown = {h for u in units if u.get("state") == "UNKNOWN" for h in u.get("holders") or []}

        def stale(rid) -> list[str]:
            row, why = rows.get(rid), []
            if row is None or not row.get("online"):
                why.append("offline")
            elif (row.get("state_age_s") or 0.0) > STATE_STALE_S:
                why.append("state_age")
            if rid in trips and trips[rid].get("front_d_m") is None:
                why.append("not_placed")
            if rid in held_unknown:
                why.append("unknown_unit")
            return why

        # wait cycles: Fleet's and the table's own
        fleet_cycle = frozenset(str(r) for r in traffic.get("wait_cycle") or [] if not str(r).startswith("signal:"))
        table_cycle = _cycle(waits) or frozenset()
        members = fleet_cycle | table_cycle         # one group while Fleet and the table name the same robots
        last, count, since, at = self._cycle
        if members and members == last:
            count += 1
        else:
            count, since, at = (1, now, {r: xy.get(r) for r in members}) if members else (0, now, {})
            if members and self._gone >= REFORM_GAP:
                self._formed.setdefault(members, deque()).append(now)
        self._gone = 0 if members else self._gone + 1
        self._cycle = (members, count, since, at)
        for key in list(self._formed):
            formed = self._formed[key]
            while formed and now - formed[0] > REFORM_WINDOW_S:
                formed.popleft()
            if not formed:
                del self._formed[key]
        evidence = {"fleet_wait_cycle": sorted(fleet_cycle) or None, "table_cycle": sorted(table_cycle) or None}
        if members:
            bad = {r: why for r in sorted(members) if (why := stale(r))}
            if bad:
                fact("wait_cycle_stale_input", sorted(members), {"stale": bad}, 0.8, evidence)
            elif count >= CYCLE_SNAPSHOTS and all(moved(r, at.get(r)) <= MOVED_M for r in members):
                agrees = fleet_cycle == table_cycle
                fact("wait_cycle_confirmed", sorted(members),
                     {"held_s": round(now - since, 1), "snapshots": count, "fleet_agrees": agrees},
                     0.9 if agrees else 0.7, evidence)
        for key, formed in self._formed.items():
            if len(formed) >= REFORM_N:
                fact("livelock", sorted(key), {"reformed": len(formed), "window_s": REFORM_WINDOW_S}, 0.7,
                     {"cycle": sorted(key), "formed_at": list(formed)})

        # waiting robots that move
        held = set(members) | {r for r, row in resolver.items() if row.get("trigger") == "wait_cycle"}
        for rid, trip in trips.items():
            front, end = trip.get("front_d_m"), trip.get("authority_end_m")
            follows = (trip.get("convoy") or {}).get("follows")
            if refused(rid) and refused(rid) != [follows] and front is not None and end is not None \
                    and front >= end - MOVED_M:
                held.add(rid)
        self._wait_since = {r: self._wait_since.get(r, now) for r in held if r in rows}
        for rid, start in sorted(self._wait_since.items()):
            window = [p for t, p in self._track.get(rid, ()) if t >= max(start, now - WAIT_MOVE_S) - 1e-6]
            if now - start >= WAIT_MOVE_S - 1e-6 and window and xy.get(rid) and moved(rid, window[0]) > MOVED_M:
                fact("waiting_but_moving", [rid], {"moved_m": round(moved(rid, window[0]), 3),
                                                   "window_s": WAIT_MOVE_S},
                     0.8, {"waiting_for": sorted(waits.get(rid, ())), "in_cycle": rid in members})

        # route livelock and stalled trips
        for rid in set(self._progress) - set(trips):
            del self._progress[rid]
        for rid in set(self._still) - set(trips):
            del self._still[rid]
        for rid, trip in sorted(trips.items()):
            front, here = trip.get("front_d_m"), xy.get(rid)
            if front is None or here is None or stale(rid) or rid in stuck:
                self._progress.pop(rid, None)
                self._still.pop(rid, None)
                continue
            lf = (rows[rid].get("state") or {}).get("line_follow") or {}
            commanded = abs(float(lf.get("linear") or 0.0)) > 1e-6
            track = self._progress.get(rid)
            if track is None or abs(front - track[1]) > MOVED_M:
                track = self._progress[rid] = [now, front, 0.0, here, commanded]
            step = math.dist(here, track[3])
            if step > STEP_M:
                track[2], track[3] = track[2] + step, here
            track[4] = track[4] and commanded
            if now - track[0] >= LIVELOCK_S and (track[2] >= LIVELOCK_PATH_M or track[4]) and rid not in held:
                fact("livelock", [rid], {"path_m": round(track[2], 3), "progress_m": round(front - track[1], 3),
                                         "for_s": round(now - track[0], 1), "commanded": track[4]},
                     0.7, {"route_progress": "front_d_m"})
            end = trip.get("authority_end_m")
            if trip.get("trip_state") != "running" or trip.get("waiting_for") or end is None or end - front <= MOVED_M:
                self._still.pop(rid, None)
                continue
            start, where = self._still.setdefault(rid, (now, here))
            if math.dist(here, where) > MOVED_M:
                self._still[rid] = (now, here)
            elif now - start >= STALL_S:
                mine = [u for u in units if rid in (u.get("holders") or [])]
                fact("stalled", [rid], {
                    "still_s": round(now - start, 1), "authority_ahead_m": round(end - front, 3),
                    "held_units": sorted(str(u.get("id")) for u in mine),
                    "zones": sorted({str(u["zone"]) for u in mine if u.get("zone")}),
                    "waited_by": sorted({w for u in mine for w in u.get("waiting") or [] if w != rid})},
                    0.8, {"trip_state": "running", "authority_end_m": end, "front_d_m": front})

        # UNKNOWN units (cross-check of M4's 30 s)
        unknown = {str(u.get("id")): u for u in units if u.get("state") == "UNKNOWN" and u.get("holders")}
        self._unknown = {uid: self._unknown.get(uid, now) for uid in unknown}
        for uid, start in sorted(self._unknown.items()):
            if now - start > UNKNOWN_S:
                unit = unknown[uid]
                fact("unknown_occupancy_long", sorted(unit["holders"]),
                     {"unit": uid, "zone": unit.get("zone"), "unknown_s": round(now - start, 1)}, 0.9,
                     {"fleet_resolver_unknown": sorted(r for r in unit["holders"]
                                                       if resolver.get(r, {}).get("trigger") == "unknown")})
        return [f for f in facts if _sendable(f)]
