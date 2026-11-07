#!/usr/bin/env python3
"""Arm assignment and schedule for the two-arm cell: Harbor's ordered moves in, one-arm or two-arm (L1 zone split) timeline out. No MuJoCo.

Harbor gives an ordered move list per request (재취급 -> 반출 -> 복귀, or 장치 from the conveyor) and names the arms that reach both ends;
it does not say when each arm moves. This module does, the same way for simulation and the real cell:

- able arms: the arms that can do the move in the state it runs in (validator: tool-down chain and wrist clearance, `validator_can`).
- order: a move waits for every earlier move that touches the same stack, lane or stand (support and cover stay legal), and the conveyor
  hands over one container at a time, the next one arriving `belt_gap_s` after the previous pick.
- zones (D-778 L1): a / b (each arm's side), mid (conveyor end, middle row, stern stand). The pick holds the source zone, the place holds
  the target zone; reaching into the other arm's side, or carrying from one side to the other, also holds mid. Different zones may overlap in time, one zone holds one arm.
- arm choice: among the able arms, the one that can start first; Harbor's primary arm on a tie. One-arm mode has a single arm; a move
  it cannot do is not moved by it but counted as an extra transport (Pinky round trip or a person, SR-29) and done outside the cell.

Durations are the teacher's segment times (TIMING), the same yardstick for every mode; the MuJoCo run measures the real ones.

    python tools/sim/omx_two_arm_plan.py compare --scenario stack|outbound|both
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import omx_two_arm_sites as sites_mod  # noqa: E402

HARBOR_ARMS = {"A": "arm_a", "B": "arm_b"}
# The teacher's own segment times (omx_two_arm_teacher.run_step): pick = approach 2.5 + grasp, close, lift 1.5 each; carry at CARRY_SPEED;
# place = lower, release, retreat 1.5 each; park 2.5 + 0.7 back to the waiting pose (no zone held). belt_gap_s: conveyor spacing (ASSUMED).
TIMING = dict(speed=.05, pick=7., place=4.5, park=3.2, belt_gap_s=6.)
SIDE = {"arm_a": "a", "arm_b": "b"}


def zone(layout, site):
    s = layout.sites[site]
    if s["kind"] == "temp":
        return s["plate"]
    if s["kind"] == "ship":
        return "a" if s["row"] == 0 else "b" if s["row"] == 2 else "mid"
    return "mid"  # conveyor end, stern stand


def planning_sites(layout):
    """Sites the plans use: all but ship hold 2, which the arms reach at grasp height but not on the validated carry from the conveyor
    (omx_two_arm_tasks refuses it with the stern at the table edge)."""
    return [s for s, v in layout.sites.items() if v["kind"] != "ship" or v["stack"].startswith("h1")]


def validator_can(layout):
    """can(src, dst, here) -> the arms that can do that move in that state: omx_two_arm_tasks' tool-down chain inside the joint limits and
    the wrist (link3/4) clearance to every standing container. Reach alone is not enough: the near arm's wrist hits the middle row when it
    takes the bottom of its own row (MuJoCo, stud plate and r08). Cached per occupied-site set."""
    import omx_two_arm_tasks as tasks
    cache = {}

    def can(src, dst, here):
        key = (src, dst, frozenset(here.values()))
        if key not in cache:
            cache[key] = set()
            for name, arm in layout.arms.items():
                problems, path, _ = tasks.check_reach(layout, dict(id="plan", container="?", to=dst, arm=name, **{"from": src}), here, arm)
                if not problems and tasks.link_clearance(layout, arm, path, here) >= tasks.LINK_MARGIN:
                    cache[key].add(name)
        return cache[key]
    return can


def table_can(table):
    """can() from a fixed {site: arms} table (both ends reached), for tests and quick looks: no carry or wrist check."""
    return lambda src, dst, here: table.get(src, set()) & table.get(dst, set())


def stack_key(layout, site):
    s = layout.sites[site]
    return s.get("stack", site)


def harbor_moves(layout, state, request, can, avoid=()):
    """Harbor-shaped moves for one outbound request on `state` (cargo -> site): every container above the target, top first, to a free
    temporary lane or free supported ship site, the target to a free stand, then the blockers back into the target's stack from its bottom,
    in their old order; the first complete plan wins (depth first, as harbor/spatial.plan_spatial searches complete plans). Each move
    carries `arms`, every arm that can do it in the state it runs in. Returns (moves, None) or (None, HOLD reason)."""
    target = request["cargo_id"]
    if target not in state:
        return None, "OUTBOUND_NOT_OBSERVED"
    site = state[target]
    key, base = stack_key(layout, site), layout.sites[site].get("layer", 0)
    blockers = sorted((c for c, s in state.items() if stack_key(layout, s) == key and layout.sites[s].get("layer", 0) > base),
                      key=lambda c: -layout.sites[state[c]]["layer"])
    stand = next((s for s, v in layout.sites.items() if v["kind"] == "outbound" and s not in state.values()), None)
    if stand is None:
        return None, "NO_FREE_STAND"
    failures = []

    def step(cur, cargo, b, phase):
        a, here = cur[cargo], {c: s for c, s in cur.items() if c != cargo}
        found = [h for h, name in HARBOR_ARMS.items() if name in can(a, b, here)]
        if not found:
            return None
        return dict(cargo_id=cargo, source=a, destination=b, primary_arm=found[0], alternate_arms=found[1:], phase_label=phase,
                    arms=[HARBOR_ARMS[h] for h in found])

    def finish(cur, moves):
        """Outbound, then the blockers back, lowest first into the target's freed level; None when an arm is missing on the way."""
        for k, (cargo, b, phase) in enumerate([(target, stand, "반출")] + [
                (c, next(s for s, v in layout.sites.items() if v.get("stack") == key and v["layer"] == base + i), "복귀")
                for i, c in enumerate(reversed(blockers))]):
            m = step(cur, cargo, b, phase)
            if m is None:
                failures.append("NO_STAND_IN_REACH" if phase == "반출" else "NO_ARM_FOR_RESTORE")
                return None
            moves, cur = moves + [m], {**cur, cargo: b}
        return moves

    def search(i, cur, moves):
        """Blockers top first, each to a temporary place (same zone first); back up and try the next place when a later move has no arm
        (a blocker left where only the near arm reaches cannot come back under its wrist)."""
        if i == len(blockers):
            return finish(cur, moves)
        cargo = blockers[i]
        occupied = set(cur.values()) - {cur[cargo]}  # it does not hold itself up
        options = sorted((t for t in temp_spots(layout, occupied, set(avoid) | {stand}) if stack_key(layout, t) != key),
                         key=lambda t: zone(layout, t) != zone(layout, cur[cargo]))
        for t in options:
            m = step(cur, cargo, t, "재취급")
            if m is not None and (found := search(i + 1, {**cur, cargo: t}, moves + [m])):
                return found
        failures.append("NO_TEMPORARY_SPACE_IN_REACH")
        return None

    moves = search(0, dict(state), [])
    return (moves, None) if moves else (None, failures[0] if failures else "NO_LEGAL_PLAN")


def temp_spots(layout, occupied, avoid=frozenset()):
    """Temporary places in Harbor's order: the free temporary lanes, then free ship sites standing on an occupied one (another 장치 칸)."""
    used = occupied | avoid
    names = planning_sites(layout)
    lanes = sorted(s for s in names if layout.sites[s]["kind"] == "temp" and s not in used)
    ship = sorted((s for s in names for v in [layout.sites[s]] if v["kind"] == "ship" and s not in used
                   and (v["layer"] == 0 or f"ship-{v['stack']}-l{v['layer'] - 1}" in occupied)), key=lambda s: (layout.sites[s]["layer"], s))
    return lanes + ship


def duration(layout, a, b):
    xy = lambda s: np.array(layout.sites[s]["xy"])  # noqa: E731
    return TIMING["pick"], float(np.linalg.norm(xy(a) - xy(b))) / TIMING["speed"] + TIMING["place"]


def schedule(layout, moves, arms, belt_arrivals=None):
    """List-schedule `moves` (Harbor order) on `arms`. Returns rows (move, arm, start, pick_end, end, zones) and the extra transports."""
    free = {a: 0. for a in arms}
    busy = {}  # zone -> [(start, end)]
    done, rows, extra = {}, [], []
    last_pick = 0.
    for k, m in enumerate(moves):
        a, b = m["source"], m["destination"]
        keys = {stack_key(layout, a), stack_key(layout, b), m["cargo_id"]} - {"belt"}
        ready = max([done[j] for j in range(k) if j in done and keys & done_keys(layout, moves[j])] + [0.])
        if a == "belt":
            ready = max(ready, last_pick + TIMING["belt_gap_s"] if k else 0., (belt_arrivals or {}).get(m["cargo_id"], 0.))
        able = [arm for arm in arms if arm in m["arms"]]
        if not able:
            extra.append(dict(move=k, cargo_id=m["cargo_id"], source=a, destination=b, why="no arm of this mode can do it"))
            done[k] = ready
            continue
        t_pick, t_place = duration(layout, a, b)
        best = None
        for arm in able:
            za, zb = zone(layout, a), zone(layout, b)
            hold_a = {za} | ({"mid"} if za not in ("mid", SIDE[arm]) else set())
            cross = za in ("a", "b") and zb in ("a", "b") and za != zb  # side to side passes over the middle
            hold_b = {zb} | ({"mid"} if zb not in ("mid", SIDE[arm]) or cross else set())
            t = max(ready, free[arm])
            while True:
                clash = [e for z in hold_a for s, e in busy.get(z, []) if s < t + t_pick and t < e] + \
                        [e for z in hold_b for s, e in busy.get(z, []) if s < t + t_pick + t_place and t + t_pick < e]
                if not clash:
                    break
                t = min(clash)
            primary = HARBOR_ARMS.get(m.get("primary_arm")) == arm
            if best is None or (t, not primary) < (best[1], not best[4]):
                best = (arm, t, hold_a, hold_b, primary)
        arm, t, hold_a, hold_b, _ = best
        for z in hold_a:
            busy.setdefault(z, []).append((t, t + t_pick))
        for z in hold_b:
            busy.setdefault(z, []).append((t + t_pick, t + t_pick + t_place))
        done[k] = t + t_pick + t_place
        free[arm] = done[k] + TIMING["park"]
        if a == "belt":
            last_pick = t + t_pick
        rows.append(dict(move=k, cargo_id=m["cargo_id"], source=a, destination=b, phase=m.get("phase_label", "장치"), arm=arm, request=m.get("request"),
                         start=round(t, 2), pick_end=round(t + t_pick, 2), end=round(t + t_pick + t_place, 2),
                         zones=[sorted(hold_a), sorted(hold_b)]))
    return rows, extra


def done_keys(layout, m):
    return {stack_key(layout, m["source"]), stack_key(layout, m["destination"]), m["cargo_id"]} - {"belt"}


def metrics(rows, extra, arms):
    end = max([r["end"] for r in rows] + [0.])
    spans = {a: [(r["start"], r["end"]) for r in rows if r["arm"] == a] for a in arms}
    overlap = 0.
    if len(arms) == 2:
        overlap = sum(max(0., min(e1, e2) - max(s1, s2)) for s1, e1 in spans[arms[0]] for s2, e2 in spans[arms[1]])
    return dict(makespan_s=round(end, 1), moves=len(rows), moves_per_arm={a: len(v) for a, v in spans.items()},
                busy_s={a: round(sum(e - s for s, e in v), 1) for a, v in spans.items()}, overlap_s=round(overlap, 1),
                extra_transports=len(extra))


def stack_moves(layout, can):
    """장치: the stack plan's containers come one by one on the conveyor, each to its site (Harbor's 장치 order), arm left open."""
    moves, here = [], {}
    for c, s, _ in layout.plan_order():
        moves.append(dict(cargo_id=c, source="belt", destination=s, primary_arm=None, alternate_arms=[], phase_label="장치",
                          arms=sorted(can("belt", s, here))))
        here[c] = s
    return moves


def outbound_requests(layout):
    """Two outbound requests after the full stack: the bottom of each outer row (two blockers each), arm_a side first."""
    full = {c: s for c, s, _ in layout.plan_order()}
    return [dict(cargo_id=c) for c, s in full.items() if layout.sites[s]["layer"] == 0 and layout.sites[s]["row"] in (0, 2)]


MODES = {"one-arm A": ("arm_a",), "one-arm B": ("arm_b",), "two-arm": ("arm_a", "arm_b")}


def plan_outbound(layout, arms, can):
    """Harbor plans each request on the state the previous one leaves, with the arms this mode has; a request with no legal plan is a
    HOLD (a person or an extra transport). Requests after the first avoid the first one's temporary places so they can overlap."""
    state = {c: s for c, s, _ in layout.plan_order()}
    mode_can = lambda a, b, here: can(a, b, here) & set(arms)  # noqa: E731
    moves, holds, avoid = [], [], set()
    for request in outbound_requests(layout):
        found, why = harbor_moves(layout, state, request, mode_can, avoid)
        if found is None:
            holds.append(dict(request=request["cargo_id"], reason=why))
            continue
        avoid |= {m["destination"] for m in found if m["phase_label"] == "재취급"}  # the stand is shared in turn (same-site order)
        for m in found:
            m["request"] = request["cargo_id"]
            state[m["cargo_id"]] = m["destination"]
        state.pop(request["cargo_id"])  # the stand is cleared by Pinky
        moves += found
    return moves, holds


def compare(layout, scenario, can=None):
    can = can or validator_can(layout)
    out = {}
    for mode, arms in MODES.items():
        result = {}
        if scenario in ("stack", "both"):
            rows, extra = schedule(layout, stack_moves(layout, can), arms)
            result["stack"] = dict(metrics(rows, extra, arms), timeline=rows, extra=extra)
        if scenario in ("outbound", "both"):
            moves, holds = plan_outbound(layout, arms, can)
            rows, extra = schedule(layout, moves, arms)
            result["outbound"] = dict(metrics(rows, extra, arms), holds=holds, timeline=rows, extra=extra)
        out[mode] = result
    return out


def as_steps(rows):
    """Timeline rows in start order as teacher steps (the sequential MuJoCo replay of an assignment)."""
    return [dict(id=f"m{r['move']}", container=r["cargo_id"], **{"from": r["source"]}, to=r["destination"], arm=r["arm"])
            for r in sorted(rows, key=lambda r: (r["start"], r["move"]))]


def replay_tasks(layout, result):
    """Teacher tasks that replay each mode's assignment in start order. Extra transports and HOLDs are not cell moves and are left out:
    the replay checks that every assigned arm can do its move in that state (sequentially; the overlap is the schedule's claim)."""
    out = {}
    for mode, r in result.items():
        tag = mode.replace(" ", "-")
        if "stack" in r:
            out[f"stack-{tag}"] = dict(name=f"stack {mode}", supply=[c for c, _, _ in layout.plan_order()], start={}, steps=as_steps(r["stack"]["timeline"]))
        if "outbound" in r:  # one task per request: Pinky clears the stand between them, which is not a cell move
            state = {c: s for c, s, _ in layout.plan_order()}
            for request in dict.fromkeys(row["request"] for row in r["outbound"]["timeline"]):
                rows = [row for row in r["outbound"]["timeline"] if row["request"] == request]
                out[f"outbound-{tag}-{request}"] = dict(name=f"outbound {request} {mode}", supply=[], start=dict(state), steps=as_steps(rows))
                for row in sorted(rows, key=lambda row: row["end"]):
                    state[row["cargo_id"]] = row["destination"]
                state.pop(request)
    return out


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("command", choices=["compare"])
    p.add_argument("--scenario", default="both", choices=["stack", "outbound", "both"])
    p.add_argument("--out")
    p.add_argument("--replay-dir", help="write one teacher task JSON per scenario and mode here (omx_two_arm_teacher.py run plan --plan FILE)")
    a = p.parse_args(argv)
    layout = sites_mod.Layout()
    result = compare(layout, a.scenario)
    if a.replay_dir:
        Path(a.replay_dir).mkdir(parents=True, exist_ok=True)
        for name, task in replay_tasks(layout, result).items():
            Path(a.replay_dir, f"{name}.json").write_text(json.dumps(task, ensure_ascii=False, indent=1), encoding="utf-8")
    for mode, r in result.items():
        for name, v in r.items():
            print(f"{mode:10s} {name:9s} makespan {v['makespan_s']:6.1f} s  moves {v['moves_per_arm']}  overlap {v['overlap_s']:5.1f} s"
                  f"  extra transports {v['extra_transports']}  holds {v.get('holds', [])}")
    if a.out:
        Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
