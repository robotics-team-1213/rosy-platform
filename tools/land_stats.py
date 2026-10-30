#!/usr/bin/env python3
"""Daily landing numbers from tools/land.py's event log (``land_events.py``).

  python tools/land_stats.py [--days 7] [--json]

Per day (local time): landings and stops, queue wait p50/p90 (minutes from entering the queue to the turn),
turn p50/p90 (minutes from the turn to landed or stop), and per judged invocation the share that were new
failures, load-flaky, or gave no usable verdict (lost host, interrupted). The batch-landing decision waits
for the new-failure share to stay at or under 10 %. Confirmed failed ids (``failure`` events) split by cause:
``shared`` (the same id failed for two or more branches within WINDOW: main or a host, tooling's to fix),
``host`` (otherwise every failure of that id on one host, at least twice), ``branch`` (the rest: one branch's
own bug). Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import land_events  # noqa: E402

WINDOW = 6 * 3600  # seconds within which one id failing for two branches counts as shared
REPEAT_ROWS = 10


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def causes(rows: list[dict]) -> list[tuple[float, str]]:
    """(time, cause) per confirmed failed id: shared, host or branch (see the module docstring)."""
    seen = [(r["t"], r.get("branch"), r.get("host"), i) for r in rows
            if r["event"] == "failure" and r.get("confirmed") for i in r.get("failed", [])]
    out = []
    for t, _, _, nodeid in seen:
        same = [s for s in seen if s[3] == nodeid]
        if len({s[1] for s in same if abs(s[0] - t) <= WINDOW}) > 1:
            out.append((t, "shared"))
        elif len(same) > 1 and len({s[2] for s in same}) == 1:
            out.append((t, "host"))
        else:
            out.append((t, "branch"))
    return out


def repeat(rows: list[dict], candidates: str, quarantine: str) -> list[dict]:
    """Confirmed failed ids that stopped two or more branches, most branches first: the decisions (fix main, own
    it, or move a reviewed LOAD-FLAKY candidate into test/flaky_quarantine.txt) nobody took. 10-28..30 one id
    stopped 14 branches over 45 h while its flaky candidates piled up unread."""
    seen: dict[str, dict] = {}
    for r in rows:
        if r["event"] == "failure" and r.get("confirmed"):
            branch = re.sub(r"^land/|-\d{14}.*$", "", r.get("branch") or "")
            for nodeid in r.get("failed", []):
                s = seen.setdefault(nodeid, {"id": nodeid, "branches": set(), "hosts": set(), "last": 0})
                s["branches"].add(branch)
                s["hosts"].add(r.get("host"))
                s["last"] = max(s["last"], r["t"])
    flaky = [line.split("  #")[0].strip() for line in candidates.splitlines()]
    held = {line.split("  #")[0].strip() for line in quarantine.splitlines()}
    out = [{**s, "branches": len(s["branches"]), "hosts": sorted(h for h in s["hosts"] if h),
            "flaky_candidates": flaky.count(s["id"]), "quarantined": s["id"] in held}
           for s in seen.values() if len(s["branches"]) > 1]
    return sorted(out, key=lambda s: (-s["branches"], -s["last"]))


def daily(rows: list[dict]) -> dict[str, dict]:
    days: dict[str, dict] = defaultdict(lambda: {"landed": 0, "stopped": 0, "waits": [], "turns": [],
                                                 "tests": defaultdict(int), "prepares": [],
                                                 "causes": defaultdict(int)})
    turn_at: dict[int, float] = {}
    for row in rows:
        day = days[time.strftime("%Y-%m-%d", time.localtime(row["t"]))]
        event, pid = row["event"], row.get("pid")
        if event == "turn":
            turn_at[pid] = row["t"]
            day["waits"].append(row.get("waited_s", 0) / 60)
        elif event in ("landed", "stop"):
            day["landed" if event == "landed" else "stopped"] += 1
            if pid in turn_at:
                day["turns"].append((row["t"] - turn_at.pop(pid)) / 60)
        elif event == "prepared":
            day["prepares"].append(row.get("seconds", 0) / 60)
        elif event == "tests":
            day["tests"][row.get("verdict", "?")] += 1
    for t, cause in causes(rows):
        days[time.strftime("%Y-%m-%d", time.localtime(t))]["causes"][cause] += 1
    out = {}
    for name, day in sorted(days.items()):
        judged = sum(day["tests"].values())
        share = (lambda key: round(day["tests"][key] / judged, 3) if judged else None)
        out[name] = {"landed": day["landed"], "stopped": day["stopped"],
                     "wait_p50_min": percentile(day["waits"], .5), "wait_p90_min": percentile(day["waits"], .9),
                     "turn_p50_min": percentile(day["turns"], .5), "turn_p90_min": percentile(day["turns"], .9),
                     "prepare_p50_min": percentile(day["prepares"], .5),
                     "prepare_p90_min": percentile(day["prepares"], .9),
                     "invocations": judged, "new_share": share("new"), "flaky_share": share("flaky"),
                     "unusable_share": share("unusable"),
                     **{f"failed_{c}": day["causes"][c] for c in ("shared", "host", "branch")}}
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    common = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, check=True).stdout.strip()
    since = time.time() - args.days * 86400
    rows = [r for r in land_events.read(Path(common) / land_events.EVENTS) if r["t"] >= since]
    stats = daily(rows)
    if args.json:
        print(json.dumps(stats, indent=1))
        return 0
    fmt = lambda v: "-" if v is None else f"{v:.0f}" if isinstance(v, float) and v >= 10 else str(v)  # noqa: E731
    print("day         landed stopped  wait p50/p90 min  turn p50/p90 min  inv  new   flaky unusable"
          "  failed ids shared/host/branch")
    for name, d in stats.items():
        print(f"{name}  {d['landed']:6} {d['stopped']:7}  {fmt(d['wait_p50_min']):>6}/{fmt(d['wait_p90_min']):<8}"
              f"  {fmt(d['turn_p50_min']):>6}/{fmt(d['turn_p90_min']):<8}  {d['invocations']:3}  {fmt(d['new_share']):5}"
              f" {fmt(d['flaky_share']):5} {fmt(d['unusable_share']):8}"
              f"  {d['failed_shared']}/{d['failed_host']}/{d['failed_branch']}")
    read = lambda path: path.read_text(encoding="utf-8") if path.is_file() else ""  # noqa: E731
    top = repeat(rows, read(Path(common) / "rosy-flaky-candidates.txt"), read(Path(common).parent / "test/flaky_quarantine.txt"))
    if top:
        print("\nids that stopped 2+ branches (fix main, own it: tools/land_mainred.py own, or review the"
              " LOAD-FLAKY candidates into test/flaky_quarantine.txt)")
        print("branches  flaky-cand  quarantined  last         hosts      id")
        for s in top[:REPEAT_ROWS]:
            print(f"{s['branches']:8}  {s['flaky_candidates']:10}  {'yes' if s['quarantined'] else 'no':11}"
                  f"  {time.strftime('%m-%d %H:%M', time.localtime(s['last']))}  {','.join(s['hosts']):9}  {s['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
