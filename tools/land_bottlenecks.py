"""Daily landing bottleneck audit and automatic remediation (D-889).

Checks once a day (scheduled task ``RosyLandBottlenecks`` or manual CLI) for the concrete causes that slow the
landing queue—lead-time/stall goal breaches, cold main cache, oversized ``rosy-pytest-memory.jsonl``, worktree
and hidden snapshot bloat, stalled queue tickets, slow or overhead-heavy invocations, and unowned ``MAIN-RED``
ids—and with ``--apply`` safely remediates what automation can fix without losing work: trims memory history,
warms main's land cache from landed logs, prunes lossless/idle worktrees (branch kept), and records the report.

    python tools/land_bottlenecks.py [--apply] [--hours 24] [--idle-hours 6] [--out PATH] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
sys.path[:0] = [str(TOOLS), str(TOOLS / "remote")]

import land_cache  # noqa: E402
import land_events  # noqa: E402
import land_gc  # noqa: E402
import land_goal  # noqa: E402
import land_mainred  # noqa: E402
import land_queue  # noqa: E402
import land_stats  # noqa: E402
import land_tick  # noqa: E402
import memory_history  # noqa: E402
import worktrees  # noqa: E402

MAX_MEMORY_ROWS, KEEP_MEMORY_ROWS = 20000, 15000
MIN_MAIN_CACHE = 8
SLOW_PYTEST_S, OVERHEAD_S, WAIT_WARN_S = 120, 45, 60
STALLED_TICKET_S = 7200
TOP_LIMIT = 5
GOAL_P90_MIN, GOAL_STALL_MIN = 60.0, 30.0


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", check=True).stdout.strip()


def _common_dir(repo: Path) -> Path:
    return Path(_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir"))


def _exact_main_cache_count(repo: Path, common: Path) -> int:
    tree = _git(repo, "rev-parse", "main^{tree}")
    cache_file = common / land_cache.CACHE
    if not cache_file.is_file():
        return 0
    hits = 0
    with cache_file.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if tree not in line:
                continue
            try:
                if json.loads(line).get("tree") == tree:
                    hits += 1
            except (ValueError, TypeError):
                continue
    return hits


def _parse_iso_ts(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except ValueError:
        return None


def _memory_summary(mem_file: Path | None, since: float) -> dict:
    if mem_file is None or not mem_file.is_file():
        return {"rows": 0, "slow_pytest": [], "high_overhead": []}
    total, slow, overhead = 0, [], []
    with mem_file.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if not line.strip():
                continue
            total += 1
            try:
                row = json.loads(line)
            except ValueError:
                continue
            ts = _parse_iso_ts(row.get("time"))
            if ts is not None and ts < since:
                continue
            pytest_s = int(row.get("pytest_s") or 0)
            job_s = int(row.get("job_s") or 0)
            wait_s = int(row.get("wait_s") or 0)
            queued_s = int(row.get("queued_s") or 0)
            overhead_s = max(0, job_s - pytest_s) if job_s and "pytest_s" in row else 0
            key = str(row.get("key") or "")[:96]
            host = str(row.get("host") or "")
            if pytest_s >= SLOW_PYTEST_S:
                slow.append({"pytest_s": pytest_s, "wait_s": wait_s, "queued_s": queued_s, "host": host, "key": key})
            if overhead_s >= OVERHEAD_S or wait_s >= WAIT_WARN_S:
                overhead.append({"overhead_s": overhead_s, "wait_s": wait_s, "pytest_s": pytest_s,
                                 "host": host, "key": key})
    slow.sort(key=lambda r: (-r["pytest_s"], -r["wait_s"]))
    overhead.sort(key=lambda r: (-(r["overhead_s"] + r["wait_s"]), -r["pytest_s"]))
    return {"rows": total, "slow_pytest": slow[:TOP_LIMIT], "high_overhead": overhead[:TOP_LIMIT]}


def _trim_memory_history(mem_file: Path | None, max_rows: int | None = None,
                         keep_rows: int | None = None) -> int:
    if mem_file is None or not mem_file.is_file():
        return 0
    max_rows = MAX_MEMORY_ROWS if max_rows is None else max_rows
    keep_rows = KEEP_MEMORY_ROWS if keep_rows is None else keep_rows
    lines = [line for line in mem_file.read_text(encoding="utf-8", errors="replace").splitlines() if line.strip()]
    if len(lines) <= max_rows:
        return 0
    kept = lines[-keep_rows:]
    tmp = mem_file.with_name(f".{mem_file.name}.{os.getpid()}.tmp")
    tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
    os.replace(tmp, mem_file)
    return len(lines) - len(kept)


def scan(repo: Path, *, hours: float = 24.0, idle_hours: float = 6.0, now: float | None = None) -> dict:
    """Inspect queue, goal, cache, memory history, worktrees, gc backlog, and main-red state."""
    now = time.time() if now is None else now
    t0 = now - hours * 3600
    common = _common_dir(repo)
    rows = land_events.read(common / land_events.EVENTS)
    recent = [r for r in rows if r["t"] >= t0]
    goal_norm, incomplete = land_goal.normalize(rows, common, t0, now)
    queue_rows = land_queue.ahead(land_queue.queue_dir(repo), Path("~"))
    alive = {int(r.get("pid") or 0) for r in queue_rows}
    moves = [r["t"] for r in goal_norm if r["event"] == "landed" and r.get("main_move", True)]
    goal_lines, goal_ok = land_goal.report(goal_norm, moves, {p for p in alive if land_queue.pid_alive(p)},
                                           t0, now, GOAL_P90_MIN, GOAL_STALL_MIN)
    day_stats = land_stats.daily(recent)
    wt_rows = worktrees.scan(repo)[1]
    wt_removable = worktrees.prune(repo, snapshot=True, everyone=True, idle_hours=idle_hours,
                                   quiet=True, now=now, say=lambda *_: None)
    gc_rows = land_gc.plan(repo, now, 7)
    gc_removable = sum(1 for r in gc_rows if r[0] != "keep")
    cache_hits = _exact_main_cache_count(repo, common)
    mem = _memory_summary(common / memory_history.FILE, t0)
    stalled = [r.get("branch", "?") for r in queue_rows if now - float(r.get("start") or now) > STALLED_TICKET_S]
    unowned_red = [k for k, s in land_mainred.state(repo).items()
                   if now - (s.get("since") or now) > land_tick.ALERT_S and not s.get("owner")]
    findings = []
    if not goal_ok:
        findings.append(f"goal_breach: {goal_lines[0] if goal_lines else 'goal failed'}")
    if cache_hits < MIN_MAIN_CACHE:
        findings.append(f"cache_cold: exact_main={cache_hits} (< {MIN_MAIN_CACHE})")
    if mem["rows"] > MAX_MEMORY_ROWS:
        findings.append(f"memory_bloat: {mem['rows']} rows (> {MAX_MEMORY_ROWS})")
    if len(wt_rows) > worktrees.CAP:
        findings.append(f"worktrees_over_cap: {len(wt_rows)}/{worktrees.CAP} (removable={wt_removable})")
    if gc_removable:
        findings.append(f"gc_backlog: {gc_removable} removable hidden snapshot/log item(s)")
    if mem["slow_pytest"]:
        findings.append(f"slow_invocations: {len(mem['slow_pytest'])} >= {SLOW_PYTEST_S}s")
    if mem["high_overhead"]:
        findings.append(f"high_overhead: {len(mem['high_overhead'])} with wait>={WAIT_WARN_S}s or overhead>={OVERHEAD_S}s")
    if stalled:
        findings.append(f"queue_stalled: {len(stalled)} ticket(s) > {STALLED_TICKET_S // 60} min")
    if unowned_red:
        findings.append(f"mainred_unowned: {len(unowned_red)} id(s) > {land_tick.ALERT_S // 60} min")
    return {
        "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "main": _git(repo, "rev-parse", "--short=10", "main"),
        "goal_ok": bool(goal_ok and not incomplete),
        "goal_lines": [*incomplete, *goal_lines],
        "daily": day_stats,
        "cache_exact_main": cache_hits,
        "memory_rows": mem["rows"],
        "slow_pytest": mem["slow_pytest"],
        "high_overhead": mem["high_overhead"],
        "worktrees": len(wt_rows),
        "worktrees_cap": worktrees.CAP,
        "worktrees_removable": wt_removable,
        "gc_removable": gc_removable,
        "queue_count": len(queue_rows),
        "queue_stalled": stalled,
        "mainred_unowned": unowned_red,
        "findings": findings,
    }


def remediate(repo: Path, before: dict, *, warm_limit: int = 16, idle_hours: float = 6.0) -> list[str]:
    """Run safe automatic bottleneck remediations (trim memory log, warm cache, gc + worktree prune)."""
    common = _common_dir(repo)
    actions = []
    if trimmed := _trim_memory_history(common / memory_history.FILE):
        actions.append(f"trimmed {trimmed} old row(s) from {memory_history.FILE}")
    if before["cache_exact_main"] < MIN_MAIN_CACHE and warm_limit > 0:
        res = subprocess.run([sys.executable, "-X", "utf8", str(TOOLS / "land_cache.py"),
                              "--warm", "--limit", str(warm_limit)], cwd=repo, capture_output=True, text=True,
                             encoding="utf-8", errors="replace", timeout=180)
        actions.append(f"cache_warm exit={res.returncode} limit={warm_limit}")
    cleanup_summary = land_tick.cleanup(repo)
    actions.append(cleanup_summary)
    if len(worktrees.scan(repo)[1]) > worktrees.CAP:
        quiet = lambda *_: None  # noqa: E731
        extra = worktrees.prune(repo, apply=True, snapshot=True, everyone=True,
                                idle_hours=idle_hours, quiet=True, say=quiet)
        actions.append(f"worktrees_cap_prune idle>={idle_hours}h removed={extra}")
    return actions


def format_report(before: dict, actions: list[str] | None = None, after: dict | None = None) -> str:
    """Format a compact plain/Markdown report for stdout or docs/workspace-records."""
    lines = [
        f"## Landing Bottlenecks ({before['time']} | main {before['main']})",
        f"- worktrees: {before['worktrees']}/{before['worktrees_cap']} | cache_exact_main: {before['cache_exact_main']} "
        f"| memory_rows: {before['memory_rows']} | queue: {before['queue_count']}",
        *[f"- goal: {line}" for line in before["goal_lines"][:6]],
        "- findings: " + ("; ".join(before["findings"]) if before["findings"] else "none"),
    ]
    if before["slow_pytest"]:
        lines.append("- slowest pytest: " + "; ".join(
            f"{r['pytest_s']}s (wait {r['wait_s']}s, {r['host']}) {r['key']}" for r in before["slow_pytest"][:3]))
    if actions is not None:
        lines.append("- actions: " + "; ".join(actions))
    if after is not None:
        lines.append(f"- after: worktrees={after['worktrees']}/{after['worktrees_cap']}, "
                     f"cache_exact_main={after['cache_exact_main']}, memory_rows={after['memory_rows']}, "
                     f"gc_removable={after['gc_removable']}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="run safe automatic remediations")
    parser.add_argument("--hours", type=float, default=24.0)
    parser.add_argument("--idle-hours", type=float, default=6.0)
    parser.add_argument("--warm-limit", type=int, default=16)
    parser.add_argument("--out", type=Path, default=None, help="write latest report to this file")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--strict", action="store_true", help="exit 1 if goal failed or unowned main-red exists")
    args = parser.parse_args(argv)
    repo = Path.cwd()
    before = scan(repo, hours=args.hours, idle_hours=args.idle_hours)
    actions, after = None, None
    if args.apply:
        actions = remediate(repo, before, warm_limit=args.warm_limit, idle_hours=args.idle_hours)
        after = scan(repo, hours=args.hours, idle_hours=args.idle_hours)
    text = format_report(before, actions, after)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    if args.json:
        print(json.dumps({"before": before, "actions": actions, "after": after}, indent=2))
    else:
        print(text, end="")
    unresolved = bool(before["mainred_unowned"] or not before["goal_ok"])
    return 1 if (args.strict and unresolved) else 0


if __name__ == "__main__":
    sys.exit(main())
