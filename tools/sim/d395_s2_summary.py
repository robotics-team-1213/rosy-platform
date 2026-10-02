#!/usr/bin/env python3
"""Markdown rows and the S2 pass bar from D-395 S2 bench runs (`d395_s2_bench.py` run.json).

Every run is an (s2a) power-on; (s2d) traffic, (s2c) mirror and (s2b) simultaneous pickup
appear when the run had them. Times are bench wall seconds since launch with sim seconds in
parentheses. Collisions are judged from the Gazebo truth trail (closest pair < 0.22 m); the
gz_multi robots carry no contact sensor, so there is no contact count.

  python tools/sim/d395_s2_summary.py RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d395_s1_summary import decisions, fmt, rtf_range, to_sim, verdict  # noqa: E402
from d395_s2_bench import COLLISION_M, min_pairwise  # noqa: E402

#: Rev. 6: a mirror lock must be flagged within 15 sim s of the injection.
DETECT_LIMIT_SIM_S = 15.0
#: A leg counts as driven when the truth ends this close to its goal (sim goal tolerance 0.10).
LEG_DONE_M = 0.25

LADDER = re.compile(r"localization: (rosy_\d+) ladder (\S+): (\S+) sent \(held (\[.*?\])\)")
SUSPECT = re.compile(r"localization: (rosy_\d+) observed > .*?; suspect")
JUMPED = re.compile(r"localization: (rosy_\d+) pose jumped while LOCALIZED")


def fleet_log(path):
    """Ladder missions with the robots Fleet held, suspects Fleet posted, anchor drops."""
    log = Path(path) / "fleet.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    return {"ladder": [(r, rung, kind, held) for r, rung, kind, held in LADDER.findall(text)],
            "suspects": SUSPECT.findall(text), "jumped": JUMPED.findall(text)}


def human_results(run):
    return [e["event"]["data"] for e in run.get("events", ())
            if e["event"].get("type") == "localization.result"
            and (e["event"].get("data") or {}).get("source") == "human"]


def ok_pose(v):
    return bool(v) and v.get("ok") is True and not v.get("mirror")


def bar(run, posted):
    """{scenario: (passed, [reasons it failed])} against the S2 pass bar."""
    phases, clock = run.get("phases", {}), run.get("clock", [])
    robots = sorted(k for k in phases.get("power_on", {}) if k.startswith("rosy_"))
    common = []
    if human_results(run):
        common.append(f"{len(human_results(run))} human decisions")
    mirrors = [d for d in posted if d[3] is not None and d[3]["mirror"]]
    if mirrors:
        common.append(f"{len(mirrors)} mirror decisions")
    hit = min_pairwise(run.get("trail", ()))
    if hit["min_m"] is None:
        common.append("no truth trail")
    elif hit["below"]:
        common.append(f"collision: {hit['pair']} {hit['min_m']} m at {hit['t']}")
    out = {}
    p = phases.get("power_on")
    if p:
        why = list(common)
        if not p.get("done"):
            why.append("not all LOCALIZED")
        why += [f"{rid} {verdict(p.get(rid))}" for rid in robots if not ok_pose(p.get(rid))]
        out["s2a"] = (not why, why)
    p = phases.get("traffic")
    if p:
        why = list(common)
        if not p.get("started"):
            why.append("traffic never started")
        elif (p.get("homer_at_start") or {}).get("state") == "LOCALIZED":
            why.append("homer already LOCALIZED when the traffic started: no homing in traffic")
        legs = p.get("legs") or {}
        planned = p.get("planned") or {}
        short = {rid: len(done) for rid, done in legs.items() if len(done) < planned.get(rid, 1)}
        if short:
            why.append(f"legs not finished {short}")
        off = [(rid, leg.get("off_goal_m")) for rid, done in legs.items() for leg in done
               if leg.get("off_goal_m") is None or leg["off_goal_m"] > LEG_DONE_M]
        if off:
            why.append(f"legs counted away from their goal {off}")
        out["s2d"] = (not why, why)
    elif (run.get("args") or {}).get("traffic"):
        out["s2d"] = (False, ["traffic requested, phase not recorded"])
    p = phases.get("mirror")
    if p:
        why = list(common)
        left = p.get("target_left")
        latency = None
        if left:
            # From the publish (after the ros2 CLI started), not from the call: under load the
            # CLI alone took 20-60 s wall in S1.
            t0 = to_sim(clock, p.get("t_injected"))
            t1 = to_sim(clock, left[0])
            latency = None if t0 is None or t1 is None else round(t1 - t0, 1)
        if not left:
            why.append("not detected")
        elif latency is None or latency > DETECT_LIMIT_SIM_S:
            why.append(f"detected after {latency} sim s (> {DETECT_LIMIT_SIM_S})")
        if p.get("accused"):
            why.append(f"accused {sorted({a[1] for a in p['accused']})}")
        if not p.get("done"):
            why.append("not all re-LOCALIZED")
        why += [f"{rid} {verdict(p.get(rid))}" for rid in robots if p.get("done") and not ok_pose(p.get(rid))]
        out["s2c"] = (not why, why)
    p = phases.get("pickup2")
    if p:
        why = list(common)
        if p.get("layout_problems"):
            why.append(f"drop layout {p['layout_problems']}")
        if not p.get("done"):
            why.append("lifted robots not re-LOCALIZED")
        if p.get("others_left_localized"):
            why.append(f"others left LOCALIZED {sorted({a[1] for a in p['others_left_localized']})}")
        why += [f"{rid} {verdict(p.get(rid))}" for rid in robots if p.get("done") and not ok_pose(p.get(rid))]
        out["s2b"] = (not why, why)
    return out


def main(argv):
    for path in argv:
        run = json.loads((Path(path) / "run.json").read_text(encoding="utf-8"))
        clock, phases = run.get("clock", []), run.get("phases", {})
        loads = [run.get("load_before")] + [p.get("load") for p in phases.values() if isinstance(p, dict)]
        print(f"### {Path(path).name} (layout {run['scenario']}) RTF {rtf_range(run)}, load {loads}")
        if run.get("layout_problems"):
            print(f"- layout problems: {run['layout_problems']}")
        posted = decisions(run, path)
        logs = fleet_log(path)
        print(f"- Fleet decisions: {len(posted)} ({sum(1 for d in posted if d[3] and d[3]['ok'])} at the truth, "
              f"{sum(1 for d in posted if d[3] is None)} unjudged), MIRROR: "
              f"{[d[:3] for d in posted if d[3] and d[3]['mirror']] or 0}, human: {len(human_results(run))}")
        hit = min_pairwise(run.get("trail", ()))
        print(f"- closest pair (truth): {hit['min_m']} m {hit['pair']} at {fmt(hit['t'], clock)}, "
              f"{hit['below']} of {hit['rounds']} rounds under {COLLISION_M} m; contact: not instrumented")
        print(f"- Fleet: ladder {[(r, k, h) for r, _, k, h in logs['ladder']] or '-'}, suspects "
              f"{logs['suspects'] or '-'}, anchor drops {logs['jumped'] or '-'}")
        p = phases.get("power_on")
        if p:
            for rid in sorted(k for k in p if k.startswith("rosy_")):
                r = p.get(rid, {})
                print(f"- power-on {rid}: candidates {fmt(r.get('t_candidates'), clock)}, LOCALIZED "
                      f"{fmt(r.get('t_localized'), clock)}, {verdict(r)}")
        p = phases.get("traffic")
        if p:
            window = min_pairwise(run.get("trail", ()), p.get("started"), p.get("finished"))
            near = None
            if p.get("started") is not None:
                keep = {p["homer"], *(p.get("legs") or {})}
                near = min_pairwise([row for row in run.get("trail", ()) if row[1] in keep],
                                    p["started"], p.get("finished"))
            replies = [(q["robot"], q["leg"], q["code"], (q.get("body") or {}).get("reason")
                        or ("accepted" if (q.get("body") or {}).get("accepted") else (q.get("body") or {})))
                       for q in p.get("posts", ())]
            print(f"- traffic: started {fmt(p.get('started'), clock)} with homer {p['homer']} "
                  f"{(p.get('homer_at_start') or {}).get('state')} mission "
                  f"{((p.get('homer_at_start') or {}).get('mission') or {}).get('kind')}, homer LOCALIZED "
                  f"{fmt(p.get('homer_localized'), clock)}, legs {({r: len(v) for r, v in (p.get('legs') or {}).items()})}")
            print(f"  - goal posts (robot, leg, http, Fleet): {replies}")
            print(f"  - closest pair in the window: {window['min_m']} m {window['pair']}; homer and drivers: "
                  f"{near['min_m'] if near else '-'} m")
        p = phases.get("mirror")
        if p:
            left = p.get("target_left")
            print(f"- mirror on {p['target']}: injected {fmt(p.get('t_pub_start'), clock)}, after injection "
                  f"{verdict(p.get('target_after_injection'))}, left LOCALIZED "
                  f"{fmt(left[0], clock) if left else '-'} {left[2:] if left else ''}, accused "
                  f"{p.get('accused') or '-'}, re-LOCALIZED {fmt(p.get('t_target_localized'), clock)}, "
                  f"end {[verdict(p.get(r)) for r in sorted(k for k in p if k.startswith('rosy_'))]}")
        p = phases.get("pickup2")
        if p:
            print(f"- pickup of {p['lifted']}: held {p.get('state_while_held')}, set down "
                  f"{fmt(p.get('t_set_down'), clock)}, LOCALIZED "
                  f"{ {r: fmt(t, clock) for r, t in (p.get('t_localized') or {}).items()} }, others left "
                  f"LOCALIZED {p.get('others_left_localized') or '-'}, stale trap {p.get('stale_trap')}, end "
                  f"{[verdict(p.get(r)) for r in sorted(k for k in p if k.startswith('rosy_'))]}")
        for name, (passed, why) in sorted(bar(run, posted).items()):
            print(f"- **{name}: {'PASS' if passed else 'FAIL'}**{'' if passed else ' - ' + '; '.join(why)}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
