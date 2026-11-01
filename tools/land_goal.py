"""The landing goal (user /goal 2026-10-31): 90% of landings reach main within 2 h, the queue never stalls > 30 min.

``python tools/land_stats.py --goal [--hours 24]`` prints lead time p50/p90 (a topic's first ``queue`` event to its
``landed``; ``land/`` prefix, ``-batch..-kN`` and UTC stamps collapsed, so restarts and resubmits count against it),
the longest stretch in which main did not move while a ticket was live, stop reasons by class, per-invocation
timing, and PASS/FAIL. Exit 1 on FAIL so a scheduled check can alert.
"""

from __future__ import annotations

import re

INFRA = ("3221225786", "1073807364", "unusable", "exited 124", "timed out", "lost contact")


def topic(branch: str) -> str:
    branch = re.sub(r"-batch\d+-k\d+$", "", branch.removeprefix("land/"))
    return re.sub(r"-\d{14}$", "", branch)


def percentile(values: list[float], q: float) -> float | None:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))] if ordered else None


def lead_times(rows: list[dict], t0: float, t1: float) -> list[float]:
    """Minutes from a topic's first queue event to its landing, for landings inside [t0, t1)."""
    first, out = {}, []
    for r in sorted(rows, key=lambda r: r["t"]):
        key = topic(r.get("branch", ""))
        if r["event"] == "queue":
            first.setdefault(key, r["t"])
        elif r["event"] == "landed" and key in first:
            start = first.pop(key)  # a later landing of the same topic starts its own clock
            if t0 <= r["t"] < t1:
                out.append((r["t"] - start) / 60)
    return out


def live(rows: list[dict], t1: float, alive_pids: set[int]) -> list[tuple[float, float]]:
    """(start, end) of each lander's ticket: queue -> landed/stop. A lander killed without a stop event ends at
    its last event; one still holding a ticket (``alive_pids``) runs to t1."""
    spans: dict[tuple, list[float]] = {}
    for r in sorted(rows, key=lambda r: r["t"]):
        key = (r.get("branch"), r.get("pid"))
        if r["event"] == "queue":
            spans[key] = [r["t"], r["t"], 0]
        elif key in spans and not spans[key][2]:
            spans[key][1] = r["t"]
            if r["event"] in ("landed", "stop"):
                spans[key][2] = 1
    return [(a, t1 if not done and pid in alive_pids else b) for (_, pid), (a, b, done) in spans.items()]


def longest_stall(moves: list[float], spans: list[tuple[float, float]], t0: float, t1: float) -> float:
    """Minutes of the longest stretch without a main move during which some ticket was live."""
    marks = sorted({t0, t1, *(m for m in moves if t0 < m < t1)})
    best = 0.0
    for a, b in zip(marks, marks[1:]):
        covered = sorted((max(a, s), min(b, e)) for s, e in spans if s < b and e > a)
        run_start = run_end = None
        for s, e in covered:
            if run_end is None or s > run_end:
                run_start, run_end = s, e
            else:
                run_end = max(run_end, e)
            best = max(best, run_end - run_start)
    return best / 60


def stop_class(reason: str) -> str:
    if any(k in reason for k in INFRA):
        return "infra"
    if "conflict" in reason or "merge aborted" in reason:
        return "conflict"
    if "size-range" in reason or "size rule" in reason:
        return "size"
    return "own failure"


def report(rows: list[dict], moves: list[float], alive_pids: set[int], t0: float, t1: float,
           goal_p90: float, goal_stall: float) -> tuple[list[str], bool]:
    lead = lead_times(rows, t0, t1)
    stall = longest_stall(moves, live(rows, t1, alive_pids), t0, t1)
    p50, p90 = percentile(lead, .5), percentile(lead, .9)
    stops: dict[str, int] = {}
    for r in rows:
        if r["event"] == "stop" and t0 <= r["t"] < t1:
            stops[stop_class(str(r.get("reason", "")))] = stops.get(stop_class(str(r.get("reason", ""))), 0) + 1
    ok = p90 is not None and p90 <= goal_p90 and stall <= goal_stall
    fmt = lambda v: "-" if v is None else f"{v:.0f}"  # noqa: E731
    lines = [f"window {(t1 - t0) / 3600:.0f} h: landed {len(lead)}, lead time p50 {fmt(p50)} / p90 {fmt(p90)} min"
             f" (goal <= {goal_p90:.0f}), longest stall {stall:.0f} min (goal <= {goal_stall:.0f})",
             "stops: " + (", ".join(f"{k} {v}" for k, v in sorted(stops.items())) or "none")]
    tests = [r for r in rows if r["event"] == "tests" and t0 <= r["t"] < t1]
    for key in ("queued_s", "wait_s", "run_s"):
        vals = [r[key] / 60 for r in tests if isinstance(r.get(key), (int, float))]
        if vals:
            lines.append(f"{key} min p50 {fmt(percentile(vals, .5))} / p90 {fmt(percentile(vals, .9))} (n={len(vals)})")
    lines.append(("PASS" if ok else "FAIL") + ": 90% within the lead-time goal and no stall past the stall goal")
    return lines, ok
