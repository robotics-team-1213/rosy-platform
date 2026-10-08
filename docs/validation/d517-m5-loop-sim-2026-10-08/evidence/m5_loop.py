"""D-517 M5 stand-in: the real Fleet trip loop (TripRunner, block table, M2 authority, M3 convoy, M4
resolver) against N kinematic robots on the demo loop (test_routing.demo_site), in sim time.

Not Gazebo and not CORE: each robot is the test fake CORE junction (test_trip_runner.FakeCore) plus a
point that drives its own trip route at ``speed`` m/s, gated like CORE line_follow/authority.py (odom
path log, ``pose_stamp`` base, never shrinks, ttl expiry, HOLDING at derived_stop_gap_m(max_linear)).
Fleet reads poses ``--pose-lag`` s old with that odom stamp. Junctions: CORE sights a place 0.35 m
ahead, waits at it without an instruction, pivots ``TURN_S`` for a turn. Perception, lane keeping and
the body stop are NOT modelled; the gap metric below is what the body stop would have had to catch.

    python m5_loop.py --robots a:start_n:0.10 b:start_s:0.09 --minutes 30 --out runs/two
    python m5_loop.py --robots a:start_n:0.08 b:follow_a:0.10 --minutes 10 --out runs/convoy
    python m5_loop.py ... --freeze a:120:60 --pose-loss b:300:40   # M4: stuck robot, UNKNOWN pose
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import itertools
import json
import logging
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
for sub in ("operations/fleet", "operations/fleet/test", "contracts/foundation", "middleware/core/services"):
    sys.path.insert(0, str(ROOT / sub))

from core_common.robot_body import PINKY_PRO  # noqa: E402
from core_features.line_follow.model import LineFollowConfig  # noqa: E402
from fleet.localization.map_pose import MapPose  # noqa: E402
from fleet.routing.execute import arc_id, plan_body  # noqa: E402
from fleet.routing.trip import PlanRequest, plan_trip  # noqa: E402
from fleet.server.site_map_store import SiteMapStore  # noqa: E402
from fleet.server.trip_ports import TripConfig, bend_geometry  # noqa: E402
from fleet.server.trip_runner import TripRunner  # noqa: E402
from test_lane_traffic import START_N, START_S, Fleet  # noqa: E402
from test_routing import demo_site  # noqa: E402
from test_trip_authority import AUTH  # noqa: E402

BODY = PINKY_PRO.front_x_m - PINKY_PRO.rear_x_m
CORE = LineFollowConfig()
STOP_GAP = CORE.derived_stop_gap_m(CORE.max_linear)
SIGHT_M, WAIT_LINE_M, TURN_S, REACQ_M, DT = 0.35, 0.05, 1.5, 0.10, 0.05
STARTS = {"start_n": ("east:fwd", START_N), "start_s": ("west:fwd", START_S)}


class Robot:
    def __init__(self, rid, speed):
        self.id, self.speed = rid, speed
        self.arc, self.s, self.xy, self.yaw = None, 0.0, (0.0, 0.0), 0.0
        self.path, self.odom = 0.0, []          # (t, path) CORE odom log
        self.poses = []                         # (t, x, y, yaw)
        self.auth, self.held = None, False
        self.sighted, self.turn_until, self.reacq_from = None, None, None
        self.frozen, self.lost = (), ()
        self.moving, self.why = False, None
        self.stops = 0


class SimFleet(Fleet):
    def __init__(self, robots, lag):
        super().__init__(tuple(robots))
        self.r, self.lag = robots, lag
        self.authority_refusals = 0

    def caps_for(self, robot_id):
        return AUTH

    def place(self, rid, arc, s):
        r = self.r[rid]
        r.arc, r.s = arc.id if hasattr(arc, "id") else r.arc, s
        x, y, yaw = arc.point_at(s)
        r.xy, r.yaw = (x, y), yaw
        r.odom.append((self.now, r.path))
        r.poses.append((self.now, x, y, yaw))
        self.p[rid].pose = MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, odom_stamp=self.now)

    async def arbitrated_pose(self, rid):
        r = self.r[rid]
        if any(a <= self.now < b for a, b in r.lost):
            return MapPose(None, None, None, "LOST", None, 0.0, None, None)
        t, x, y, yaw = next((p for p in reversed(r.poses) if p[0] <= self.now - self.lag), r.poses[0])
        return MapPose(x, y, yaw, "LOCALIZED", "sighting", 0.0, 0.1, 0.1, odom_stamp=t)

    async def junction_state(self, rid):
        state = await super().junction_state(rid)
        return {**state, "authority": self.status(rid)}

    async def send_authority(self, rid, body):  # CORE line_follow/authority.py set_authority
        r, now = self.r[rid], self.now
        base = next((e for e in reversed(r.odom) if e[0] <= body["pose_stamp"]), None)
        if base is None or body["pose_stamp"] > r.odom[-1][0] + 0.05:
            r.auth = None
            self.authority_refusals += 1
            return {"accepted": False, "authority": self.status(rid)}
        end, a = base[1] + body["until_m"], r.auth
        if a is not None and a["leg"] == body["leg_id"] and now <= a["exp"]:
            if end < a["end"] - 0.02:
                return {"accepted": False, "reason": "shrink", "authority": self.status(rid)}
            end = max(end, a["end"])
        r.auth = {"leg": body["leg_id"], "end": end, "exp": now + body["ttl_s"]}
        return {"accepted": True, "authority": self.status(rid)}

    def status(self, rid):
        r = self.r[rid]
        a = r.auth
        if a is None or self.now > a["exp"]:
            r.held = False
            return {"state": "NONE" if a is None else "EXPIRED", "remaining_m": None}
        remaining = a["end"] - r.path
        r.held = remaining <= STOP_GAP + (CORE.obstacle_resume_hysteresis_m if r.held else 0.0)
        return {"state": "HOLDING" if r.held else "FREE", "remaining_m": round(remaining, 3),
                "reason": "authority_end" if r.held else None}


def locate(live, r):
    """The robot's segment index on its (possibly trimmed / extended) plan, from segment_index on."""
    for i in range(live.view["segment_index"], len(live.segments)):
        seg = live.segments[i]
        if arc_id(seg) == r.arc and seg["s_from"] - 1e-6 <= r.s <= seg["s_to"] + 1e-6:
            return i
    return None


def drive(fleet, runner, rid, dt):
    """One CORE tick of robot ``rid``: the gates, its junction slot, then motion along its route."""
    r, core, now = fleet.r[rid], fleet.p[rid].core, fleet.now
    live = runner._live.get(rid)
    r.moving, r.why = False, "closed"
    if live is None or not live.open or core.mode != "CAMERA_LINE":
        return
    if any(a <= now < b for a, b in r.frozen):  # a stuck robot (D-407): CORE commands nothing
        r.why = "frozen"
        return
    i = locate(live, r)
    if i is None:
        r.why = "unlocated"
        return
    seg, j = live.segments[i], core.j
    rem = seg["s_to"] - r.s
    place = live.place(i)
    junction = place is not None and getattr(live.graph.places.get(place), "kind", None) == "junction"
    if j is not None and j["state"] == "turning":
        if r.turn_until is None:
            r.turn_until = now + TURN_S
        if now < r.turn_until:
            r.why = "turning"
            return
        core.phase("advancing")
        r.turn_until = None
    if j is not None and j["action"] == "bend" and j["state"] == "armed":
        g = bend_geometry(live.graph.places[j["place_id"]], live.arc(i))
        if g is not None and r.s >= g[0]:
            core.phase("bending")
    if j is not None and j["state"] == "bending":
        g = bend_geometry(live.graph.places[j["place_id"]], live.arc(i))
        if g is None or r.s >= g[1]:
            core.done()
    if r.reacq_from is not None and r.path - r.reacq_from >= REACQ_M:
        if core.j is not None and core.j["state"] == "reacquiring":
            core.done()
        r.reacq_from = None
    if junction and rem <= SIGHT_M and r.sighted != (i, place):
        r.sighted = (i, place)
        core.see_junction()
    elif junction and r.sighted == (i, place) and core.j is not None and core.j["state"] == "armed":
        core.see_junction()  # an instruction that came while CORE waited at the line
    j = core.j
    if j is not None and j["state"] == "turning":
        r.why = "turning"
        return
    if j is not None and j["action"] == "stop" and j["state"] == "executing" and core.status() and j["held"]:
        r.why = "stop_held"
        return
    if fleet.status(rid)["state"] != "FREE":
        r.why = "authority"
        return
    ds = r.speed * dt
    if junction and r.sighted == (i, place) and (j is None or j["state"] in ("waiting", "armed")):
        ds = min(ds, max(0.0, rem - WAIT_LINE_M))  # waits at the junction line
    auth = r.auth["end"] - STOP_GAP - r.path
    ds = min(ds, max(0.0, auth))
    if ds <= 1e-9:
        r.why = "junction_line" if auth > 0 else "authority_end"
        return
    r.moving, r.why = True, None
    r.path += ds
    s = r.s + ds
    while s > seg["s_to"] + 1e-9 and i + 1 < len(live.segments):  # into the next segment
        over = s - seg["s_to"]
        if core.j is not None and core.j["state"] in ("executing", "advancing") and core.j["action"] != "stop":
            if core.j["state"] == "advancing":
                core.phase("reacquiring")
                r.reacq_from = r.path
            else:
                core.done()
        i += 1
        seg = live.segments[i]
        r.arc, s = arc_id(seg), seg["s_from"] + over
    r.s = min(s, seg["s_to"])
    fleet.place(rid, live.graph.arcs[r.arc], r.s)


def start(runner, store, fleet, rid, spec, ids=itertools.count()):
    graph = store.active()[2]
    where, _ = spec
    leader = where[len("follow_"):] if where.startswith("follow_") else None
    if leader:  # behind the leader on its lane: 3 block lengths back
        la = fleet.r[leader]
        arc, s = graph.arcs[la.arc], max(0.05, la.s - 3 * runner.traffic.view()["block_length_m"][la.arc.split(":")[0]])
        to, via = ("start_n", ("start_s",)) if la.arc == "east:fwd" else ("start_s", ("start_n",))
    elif where.startswith("east@") or where.startswith("west@"):
        name, at = where.split("@")
        arc, s = graph.arcs[f"{name}:fwd"], float(at)
        to, via = ("start_n", ("start_s",)) if name == "east" else ("start_s", ("start_n",))
    else:
        arc_name, xy = STARTS[where]
        arc = graph.arcs[arc_name]
        s = arc.project(*xy)[1]
        to, via = (where, ("start_s" if where == "start_n" else "start_n",))
    fleet.r[rid].arc = arc.id if hasattr(arc, "id") else arc_name_of(graph, arc)
    fleet.place(rid, arc, s)
    plan = plan_trip(graph, PlanRequest(store.active()[0], arc.point_at(s), to, via=via), store.routing_config)
    request = {"to": to, "via": list(via), "repeat": True, **({"convoy": {"leader": leader}} if leader else {})}
    plan_id = f"{rid}-{next(ids)}"
    store.record_plan(plan_id=plan_id, robot_id=rid, principal_id="m5", map_version=plan.map_version,
                      request=request, result={"plan": plan_body(plan)})
    return asyncio.get_event_loop().run_until_complete(runner.start(plan_id, "m5"))


def arc_name_of(graph, arc):
    return next(k for k, v in graph.arcs.items() if v is arc)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--robots", nargs="+", required=True, help="id:start_n|start_s|east@s|follow_<id>:speed")
    ap.add_argument("--minutes", type=float, default=30)
    ap.add_argument("--pose-lag", type=float, default=0.2)
    ap.add_argument("--freeze", nargs="*", default=[], help="id:t0:seconds")
    ap.add_argument("--pose-loss", nargs="*", default=[], help="id:t0:seconds")
    ap.add_argument("--authority", type=int, default=1)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    specs = [tuple(x.split(":")) for x in args.robots]
    robots = {rid: Robot(rid, float(v)) for rid, _w, v in specs}
    for spec in args.freeze:
        rid, t0, d = spec.split(":")
        robots[rid].frozen += ((float(t0), float(t0) + float(d)),)
    for spec in args.pose_loss:
        rid, t0, d = spec.split(":")
        robots[rid].lost += ((float(t0), float(t0) + float(d)),)
    fleet = SimFleet(robots, args.pose_lag)
    t0 = fleet.now
    for r in robots.values():
        r.frozen = tuple((t0 + a, t0 + b) for a, b in r.frozen)
        r.lost = tuple((t0 + a, t0 + b) for a, b in r.lost)
    store = SiteMapStore(None, clock=lambda: fleet.now)
    store.import_if_empty(demo_site(), source="m5")
    runner = TripRunner(store=store, routing_config=store.routing_config, caps=fleet.caps_for, poses=fleet,
                        junction=fleet, goal=fleet.goal, cancel_goal=fleet.cancel_goal,
                        blocked=lambda: fleet.blocked, clock=lambda: fleet.now, config=TripConfig(),
                        authority=bool(args.authority))
    runner.traffic._clock = lambda: fleet.now  # the table keeps its own (wall) clock: sim time here
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    for rid, where, _v in specs:
        view = start(runner, store, fleet, rid, (where, None))
        print("start", rid, view["state"], view.get("convoy"), flush=True)
        loop.run_until_complete(runner.tick())  # located before the next one starts (convoy needs it)

    ids = list(robots)
    m = {"min_gap_m": math.inf, "min_gap_at": None, "contacts": 0, "overlap_periods": 0, "grant_conflicts": 0, "grants": 0,
         "authority_stops": {r: 0 for r in ids}, "laps": {r: [] for r in ids}, "ends": {}, "holds": [],
         "resolver": [], "max_tick_ms": 0.0, "authority_refusals": 0, "dist_m": {r: 0.0 for r in ids},
         "waiting_periods": {r: 0 for r in ids}, "min_convoy_gap_m": None}
    granted, lap_seen, was_held, hold_seen, res_seen = set(), {r: 1 for r in ids}, {r: False for r in ids}, {}, set()
    events = (out / "events.jsonl").open("w")
    trace = (out / "trace.jsonl").open("w")

    def ev(kind, **kw):
        events.write(json.dumps({"t": round(fleet.now - t0, 2), "kind": kind, **kw}) + "\n")

    steps = int(args.minutes * 60 / 0.5)
    import time as _t
    for k in range(steps):
        for _ in range(int(0.5 / DT)):
            fleet.advance(DT)
            for rid in ids:
                before = robots[rid].path
                drive(fleet, runner, rid, DT)
                m["dist_m"][rid] += robots[rid].path - before
            for a, b in itertools.combinations(ids, 2):
                gap = math.dist(robots[a].xy, robots[b].xy) - BODY
                if gap < m["min_gap_m"]:
                    m["min_gap_m"], m["min_gap_at"] = gap, (round(fleet.now - t0, 2), a, b)
                if gap <= 0:
                    m["contacts"] += 1
        w0 = _t.perf_counter()
        loop.run_until_complete(runner.tick())
        loop.run_until_complete(asyncio.sleep(0))
        pending = [f for f in runner.authority._inflight.values() if not f.done()]
        if pending:
            loop.run_until_complete(asyncio.gather(*pending))
        m["max_tick_ms"] = max(m["max_tick_ms"], (_t.perf_counter() - w0) * 1000)
        view, state = runner.traffic.view(), runner.traffic._state
        cap = {u["id"]: u["capacity"] for u in view.get("units", [])}
        occ, held_units = {}, {}
        for rid, units in state.last_occupied.items():
            for unit in units:
                occ.setdefault(unit, set()).add(rid)
        for rid, held in state.held.items():
            for unit, _fwd in held.values():
                held_units.setdefault(unit, set()).add(rid)
                if (unit, rid) not in granted:
                    m["grants"] += 1
        granted = {(u, rid) for u, rids in held_units.items() for rid in rids}
        over = {u: sorted(r) for u, r in occ.items() if len(r) > cap.get(u, 1)}
        if over:
            m["overlap_periods"] += 1
            ev("overlap", units=over)
        over = {u: sorted(r) for u, r in held_units.items() if len(r) > cap.get(u, 1)}
        if over:
            m["grant_conflicts"] += 1
            ev("grant_conflict", units=over)
        for row in view.get("robots") or []:
            gap = (row.get("convoy") or {}).get("gap_m")
            if gap is not None and (m["min_convoy_gap_m"] is None or gap < m["min_convoy_gap_m"]):
                m["min_convoy_gap_m"] = gap
        for row in view.get("resolver") or []:
            key = (row["robot_id"], row["decision"])
            if key not in res_seen:
                res_seen.add(key)
                m["resolver"].append({"t": round(fleet.now - t0, 1), **row})
                ev("resolver", **row)
        snap = {"t": round(fleet.now - t0, 1)}
        for rid in ids:
            live, r = runner._live[rid], robots[rid]
            held = r.held
            if held and not was_held[rid]:
                m["authority_stops"][rid] += 1
            was_held[rid] = held
            if (live.traffic or {}).get("waiting_for"):
                m["waiting_periods"][rid] += 1
            lap = live.view.get("lap") or 1
            if lap != lap_seen[rid]:
                m["laps"][rid].append(round(fleet.now - t0, 1))
                ev("lap", robot=rid, lap=lap)
                lap_seen[rid] = lap
            hold = live.view.get("hold")
            if hold is not None and hold_seen.get(rid) != hold.get("reason"):
                m["holds"].append({"t": round(fleet.now - t0, 1), "robot": rid, "reason": hold.get("reason"),
                                   "code": hold.get("code")})
                ev("hold", robot=rid, hold={k: hold.get(k) for k in ("reason", "code")})
            hold_seen[rid] = hold and hold.get("reason")
            if not live.open and rid not in m["ends"]:
                m["ends"][rid] = {"t": round(fleet.now - t0, 1), "state": live.view["state"],
                                  "reason": live.view["reason"], "detail": live.view.get("detail")}
                ev("end", robot=rid, **{k: live.view[k] for k in ("state", "reason")})
            snap[rid] = {"x": round(r.xy[0], 3), "y": round(r.xy[1], 3), "arc": r.arc, "moving": r.moving, "why": r.why,
                         "j": (fleet.p[rid].core.j or {}).get("state"), "auth": fleet.status(rid)["state"],
                         "wait": (live.traffic or {}).get("waiting_for")}
        trace.write(json.dumps(snap) + "\n")
        if not any(runner._live[r].open for r in ids):
            break
    m["authority_refusals"] = fleet.authority_refusals
    m["sim_s"] = round(fleet.now - t0, 1)
    m["lap_times_s"] = {r: [round(b - a, 1) for a, b in zip(v, v[1:])] for r, v in m["laps"].items()}
    m["block_length_m"] = runner.traffic.view()["block_length_m"]
    m["stop_gap_m"] = STOP_GAP
    m["min_gap_m"] = round(m["min_gap_m"], 4)
    m["dist_m"] = {r: round(v, 2) for r, v in m["dist_m"].items()}
    (out / "summary.json").write_text(json.dumps(m, indent=1, default=str))
    print(json.dumps({k: m[k] for k in ("sim_s", "min_gap_m", "min_gap_at", "contacts", "overlap_periods", "grant_conflicts", "grants", "min_convoy_gap_m", "resolver",
                                        "authority_stops", "ends", "lap_times_s", "max_tick_ms")}, default=str))


if __name__ == "__main__":
    main()
