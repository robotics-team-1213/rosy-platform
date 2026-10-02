#!/usr/bin/env python3
"""Markdown rows from D-395 S1 bench runs (`d395_s1_bench.py` run.json files).

Wall times are bench seconds since launch; `sim` converts them through the
bench's (wall, sim time) samples, because the shared host may run Gazebo far
below real time.

  python tools/sim/d395_s1_summary.py RUN_DIR [RUN_DIR ...]
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from d395_truth import judge  # noqa: E402


def to_sim(clock, t):
    """Sim seconds at bench wall time `t` by linear interpolation (None outside the samples)."""
    if t is None or len(clock) < 2:
        return None
    for (t0, s0, _), (t1, s1, _) in zip(clock, clock[1:]):
        if t0 <= t <= t1:
            return round(s0 + (s1 - s0) * (t - t0) / (t1 - t0 or 1.0), 1)
    return None


def results(run):
    rows = [e["event"]["data"] for e in run.get("events", ()) if e["event"].get("type") == "localization.result"]
    return [(r.get("accepted"), r.get("reason"), tuple(r.get("cues") or ())) for r in rows]


DECISION = re.compile(r"localization: (rosy_\d+) decision (\S+) candidate (\d+) cues (\[.*?\])")


def decisions(run, path):
    """Every decision Fleet posted (fleet.log), judged at the decided candidate against the
    Gazebo truth sampled nearest the bench's last read of that report: (robot, request id,
    cues, judge dict or None when the report or truth was not captured)."""
    log = Path(path) / "fleet.log"
    text = log.read_text(encoding="utf-8", errors="replace") if log.exists() else ""
    reports = {}
    for row in run.get("scores", ()):
        reports[(row["robot"], row["request_id"])] = row
    out = []
    for rid, request_id, index, cues in DECISION.findall(text):
        row = reports.get((rid, request_id))
        verdict = None
        if row is not None and int(index) < len(row["candidates"]):
            c = row["candidates"][int(index)]
            trail = [(abs(t - row["t"]), (x, y, yaw)) for t, r, x, y, yaw in run.get("trail", ()) if r == rid]
            if trail:
                verdict = judge((c["x"], c["y"], c["yaw"]), min(trail)[1])
        out.append((rid, request_id, cues, verdict))
    return out


def rtf_range(run):
    vals = [r for _, _, r in run.get("clock", ()) if r is not None]
    return f"{min(vals):.3f}-{max(vals):.3f}" if vals else "-"


def fmt(t, clock):
    s = to_sim(clock, t)
    return "-" if t is None else f"{t:.0f} ({s if s is not None else '?'})"


def verdict(v):
    if not v or v.get("err_xy_m") is None:
        return "no pose"
    flag = "MIRROR" if v.get("mirror") else ("ok" if v.get("ok") else "off")
    return f"{flag} {v['err_xy_m'] * 100:.1f} cm / {v['err_yaw_deg']:.1f} deg"


def main(argv):
    for path in argv:
        run = json.loads((Path(path) / "run.json").read_text(encoding="utf-8"))
        clock, phases = run.get("clock", []), run.get("phases", {})
        name = Path(path).name
        loads = [run.get("load_before")] + [p.get("load") for p in phases.values() if isinstance(p, dict)]
        print(f"### {name} (scenario {run['scenario']}) RTF {rtf_range(run)}, load {loads}")
        searches = ", ".join(f"{s['robot'][-2:]}:{s['s']:.1f}s/{s['n']}" for s in run.get("search_s", ()))
        print(f"- searches (wall s / candidates): {searches or '-'}")
        res = results(run)
        print(f"- results: {sum(1 for a, _, _ in res if a)} accepted, rejects "
              f"{[r for a, r, _ in res if not a]}, cues {sorted({c for _, _, cs in res for c in cs})}")
        posted = decisions(run, path)
        mirrors = [d[:3] for d in posted if d[3] is not None and d[3]["mirror"]]
        print(f"- Fleet decisions: {len(posted)} ({sum(1 for d in posted if d[3] and d[3]['ok'])} at the "
              f"truth, {sum(1 for d in posted if d[3] is None)} unjudged), MIRROR decisions: {mirrors or 0}")
        stale = sum(1 for row in run.get("timeline", ()) if row.get("what") == "state"
                    and (row.get("loc") or {}).get("reason") == "state_stale")
        print(f"- CORE state_stale transitions: {stale}")
        missions = [(row["t"], row.get("robot"), (row.get("mission") or {}).get("kind"),
                     (row.get("mission") or {}).get("state")) for row in run.get("timeline", ())
                    if row.get("what") == "mission" and row.get("mission")]
        # The bench notes every changed body (elapsed_s ticks); keep each robot's state changes.
        last = {}
        missions = [m for m in missions if last.get(m[1]) != m[2:] and not last.update({m[1]: m[2:]})]
        if missions:
            print(f"- ladder missions (t, robot, kind, state): {missions}")
        p = phases.get("power_on")
        if p:
            for rid in sorted(k for k in p if k.startswith("rosy_")):
                r = p.get(rid, {})
                print(f"- power-on {rid}: candidates {fmt(r.get('t_candidates'), clock)}, LOCALIZED "
                      f"{fmt(r.get('t_localized'), clock)}, {verdict(r)}")
        p = phases.get("pickup")
        if p:
            print(f"- pickup: moved {p.get('moved')}, goal codes {p.get('goal_code')}, drift while held "
                  f"{p.get('drift_while_held_m')} m, state while held {p.get('state_while_held')}, SUSPECT "
                  f"{fmt(p.get('t_suspect'), clock)}, set down {fmt(p.get('t_set_down'), clock)}, LOCALIZED "
                  f"{fmt(p.get('t_localized'), clock)}, r1 {verdict(p.get('rosy_01'))}, r2 {verdict(p.get('rosy_02'))}")
        p = phases.get("mirror")
        if p:
            print(f"- mirror: detected alone {p.get('detected_without_peer_report')}, r2 after injection "
                  f"{verdict(p.get('r2_after_injection'))}, r2 SUSPECT {fmt(p.get('t_r2_suspect'), clock)}, "
                  f"r1 LOCALIZED {fmt(p.get('t_r1_localized'), clock)}, r2 LOCALIZED "
                  f"{fmt(p.get('t_r2_localized'), clock)}, end r1 {verdict(p.get('rosy_01'))}, "
                  f"r2 {verdict(p.get('rosy_02'))}")
        print()


if __name__ == "__main__":
    main(sys.argv[1:])
