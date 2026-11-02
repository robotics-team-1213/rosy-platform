"""The landing goal (user /goal 2026-11-02): 90% of landings reach main within 60 min, the queue never stalls > 30 min.

``python tools/land_stats.py --goal [--hours 24]`` prints lead time p50/p90 (a topic's first ``queue`` event to its
``landed``; ``land/`` prefix, ``-batch..-kN`` and UTC stamps collapsed, so restarts and resubmits count against it),
the longest stretch in which main did not move while a ticket was live, stop reasons by class, per-invocation
timing, and PASS/FAIL. Exit 1 on FAIL so a scheduled check can alert.
"""

from __future__ import annotations

import re
import json
import subprocess
from pathlib import Path

INFRA = ("3221225786", "1073807364", "unusable", "exited 124", "timed out", "lost contact")


def topic(branch: str) -> str:
    branch = re.sub(r"-batch\d+-k\d+$", "", branch.removeprefix("land/"))
    return re.sub(r"-\d{14}$", "", branch)


def percentile(values: list[float], q: float) -> float | None:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))] if ordered else None


def train_origins(rows: list[dict], train: dict) -> list[dict]:
    """Old trains name branches only: resolve their queue origins, rejecting competing requests."""
    if "members" in train:
        members = train["members"]
        if not isinstance(members, list) or not members or any(
                not isinstance(m, dict) or not m.get("branch") or not m.get("ticket") for m in members):
            raise ValueError("invalid batch origins")
        return members
    formed = [r["t"] for r in rows if r["event"] == "train" and r.get("result") == "formed"
              and r.get("pid") == train.get("pid") and r.get("branches") == train.get("branches")
              and r["t"] <= train["t"]]
    bound, members = max(formed, default=train["t"]), []
    for name in train.get("branches", []):
        previous = max((r["t"] for r in rows if r["t"] < bound and (
            r["event"] == "landed" and r.get("branch") == name or r["event"] == "train"
            and r.get("result") == "landed" and name in r.get("branches", []))), default=-1)
        queues = [r for r in rows if r["event"] == "queue" and r.get("branch") == name
                  and previous < r["t"] <= bound]
        exits = [r for r in rows if r["event"] == "landed" and r.get("branch") == name and r["t"] >= train["t"]]
        pid = train.get("pid") if name == train.get("branch") else min(exits, key=lambda r: r["t"]).get("pid") if exits else None
        if pid is not None:
            queues = [q for q in queues if q.get("pid") == pid]
        origins = {(q.get("ticket") or (q.get("pid"), q["t"])): q for q in queues}
        if len(origins) != 1:
            raise ValueError(f"ambiguous batch origin: {name}")
        origin = next(iter(origins.values()))
        members.append(dict(branch=name, ticket=origin.get("ticket"), queued=origin["t"]))
    if not members:
        raise ValueError("missing batch origins")
    return members


def lead_times(rows: list[dict], t0: float, t1: float) -> list[float]:
    """Minutes from a topic's first queue event to its landing, for landings inside [t0, t1)."""
    pending, out, completed, exits = {}, [], set(), set()
    for r in sorted(rows, key=lambda r: r["t"]):
        key = topic(r.get("branch", ""))
        if r["event"] == "queue":
            pending.setdefault(key, []).append(r)
            continue
        train = r["event"] == "train" and r.get("result") == "landed"
        if r["event"] != "landed" and not train:
            continue
        members = r.get("members")
        if train and members is None:
            members = [{"branch": b} for b in r.get("branches", [])]
        for member in members if members is not None else [r]:
            name = member.get("branch", "")
            queues = pending.get(topic(name), [])
            choices = [i for i, q in enumerate(queues) if
                       (q.get("branch") == name if members is not None else topic(q.get("branch", "")) == topic(name))
                       and (q.get("ticket") == member["ticket"] if member.get("ticket") else
                            q["t"] == member["queued"] if member.get("queued") is not None else
                            members is not None or q.get("pid") == r.get("pid"))]
            if not choices:
                continue
            end = choices[-1]
            origin = (name, queues[end].get("ticket"), queues[end]["t"])
            if members is None and (name, r.get("pid"), queues[end]["t"]) in exits:
                continue
            if members is not None and origin in completed:
                continue
            start = queues[0]["t"]  # retries before this origin remain part of the topic's lead
            if members is not None:
                completed.add(origin)
                if train:
                    exits.add((name, queues[end].get("pid"), queues[end]["t"]))
            pending[topic(name)] = [q for q in queues[end + 1:] if not
                                    (q.get("branch") == name and q.get("ticket") in member.get("retries", []))]
            if t0 <= r["t"] < t1:
                out.append((r["t"] - start) / 60)
    return out


def normalize(rows: list[dict], common: Path) -> tuple[list[dict], list[str]]:
    """Attach proven member origins to actual FF events; never rewrite the append-only log.

    Old sidecars lack pinned candidates: the member's historical prepare and its preceding queue identify
    the origin, only when that candidate is an ancestor of this exact landed SHA (not today's main).
    """
    result, warnings = [], []
    for row in rows:
        r = dict(row)
        result.append(r)
        if r["event"] == "train" and r.get("result") == "landed":
            try:
                r["members"] = train_origins(rows, r)
            except ValueError as exc:
                r["members"] = []
                warnings.append(f"INCOMPLETE: {r.get('branch', '')}: {exc}")
        if r["event"] != "landed":
            continue
        branch = r.get("branch", "")
        origin = max((q["t"] for q in rows if q["event"] == "queue" and q.get("branch") == branch
                      and q.get("pid") == r.get("pid") and q["t"] <= r["t"]), default=r["t"])
        if any(q["event"] == "train" and q.get("result") == "landed" and q.get("branch") != branch
               and branch in q.get("branches", []) and origin <= q["t"] <= r["t"] for q in rows):
            r["main_move"] = False  # a carried member observes the leader's FF
        path = common / "rosy-land-wt" / (branch.replace("/", "-") + ".members")
        known = re.fullmatch(r"land/fix/land-rollup-\d{14}-\d{14}", branch)
        try:
            if "members" not in r and not path.exists() and not known and not r.get("members_error"):
                continue
            members = r.get("members") if "members" in r else json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(members, list) or not members:
                raise ValueError("missing members")
            verified = []
            for m in members:
                if not isinstance(m, dict) or not isinstance(m.get("branch"), str):
                    raise ValueError("invalid member")
                origins = [q for q in rows if q["event"] == "queue" and q.get("branch") == m["branch"]
                           and q["t"] <= r["t"]]
                candidates = [m] if m.get("candidate") else sorted(
                    (q for q in rows if q["event"] == "isolation" and q.get("kind") == "prepare"
                     and q.get("branch") == m["branch"] and q["t"] <= r["t"]), key=lambda q: q["t"], reverse=True)[:1]
                found = None
                for candidate in candidates:
                    oid = candidate.get("candidate", "")
                    if not re.fullmatch(r"[0-9a-f]{40,64}", oid) or not r.get("sha"):
                        continue
                    proof = subprocess.run(["git", "--git-dir", str(common), "merge-base", "--is-ancestor",
                                            oid, r["sha"]], capture_output=True)
                    eligible = [q for q in origins if q.get("ticket") == m["ticket"]] if m.get("ticket") else [
                        q for q in origins if q["t"] <= candidate.get("t", r["t"])]
                    if proof.returncode == 0 and eligible:
                        origin = max(eligible, key=lambda q: q["t"])
                        if origin.get("ticket"):
                            found = dict(branch=m["branch"], ticket=origin["ticket"], candidate=oid)
                            # A frozen snapshot's later resumes are covered too; other snapshots of this topic
                            # may already queue new work before this FF and must retain their own clock.
                            if m["branch"].startswith("land/") and re.search(r"-\d{14}$", m["branch"]):
                                found["retries"] = [q["ticket"] for q in origins if q["t"] > origin["t"]
                                                    and q.get("ticket")]
                            break
                if found is None:
                    raise ValueError("unproven member origin")
                verified.append(found)
            r["members"] = verified
        except (OSError, ValueError, TypeError, KeyError) as exc:
            r["members"] = []  # an incomplete carrier is never substituted for its logical members
            warnings.append(f"INCOMPLETE: {branch}: member completion unavailable ({exc})")
    return result, warnings


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
