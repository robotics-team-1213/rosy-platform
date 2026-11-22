"""PR runners take the ROS environment the full tier gives each path (PR #96, 2026-10-18).

The affected tier ran every invocation under ros: overlay while the full tier runs CORE gateway,
Fleet and other suites under ros: none, so tests main skips (gateway rclpy) ran only on PRs,
failed and hung the runner. An invocation that mixes environments becomes one runner per
environment; every selected path still runs exactly once.
"""
from __future__ import annotations


JOB_WEIGHT = 120
DIR_WEIGHT = 8


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def full_tier_ros(path: str, matrix) -> str:
    """The full-tier ROS environment for ``path``; paths outside ``matrix`` keep overlay."""
    from affected_tests import GUARD_SET  # here, not at the top: affected_tests imports affected_ci imports this
    if path in GUARD_SET:
        return "overlay"  # pure text readers (no rclpy): the gateway guard shares the root guards' runner
    if _under(path, "test"):
        return "overlay"  # the full tier's root shards run every root test/ file under overlay
    best = ("", "overlay")
    for entry in matrix:
        for prefix in (p for inv in entry["invocations"] for p in inv if not p.startswith("-")):
            if _under(path, prefix) and len(prefix) > len(best[0]):
                best = (prefix, entry["ros"])
    return best[1]


def entries(invocations, matrix) -> list[dict]:
    by_ros = []
    for inv in invocations:
        flags, groups = [p for p in inv if p.startswith("-")], {}
        for path in (p for p in inv if not p.startswith("-")):
            groups.setdefault(full_tier_ros(path, matrix), []).append(path)
        by_ros += [(ros, [*paths, *flags]) for ros, paths in groups.items()] or [("overlay", inv)]
    return [{"name": f"affected-{i + 1}", "invocations": [inv], "ros": ros} for i, (ros, inv) in enumerate(by_ros)]


def _entry_weight(entry: dict, seconds: dict[str, int]) -> int:
    paths = [p for inv in entry["invocations"] for p in inv if not p.startswith("-")]
    return sum(seconds.get(p.rsplit("/", 1)[-1], 1) if p.endswith(".py") else DIR_WEIGHT for p in paths)


def consolidate(entries: list[dict], seconds: dict[str, int]) -> list[dict]:
    """Merge same-environment ``affected-*`` runners until a job's weight passes JOB_WEIGHT (2026-11-20, ralph).

    A job runs its invocations in order, so the packer's collision-free groups stay separate invocations
    while a small selection stops paying one runner per group. Weight is the measured Fleet seconds per
    file (1 by default) and DIR_WEIGHT per directory. shortcut: coarse weights; tune on CI seconds."""
    # A run is as long as its slowest job, so smaller jobs may fill up to that size at no cost in time and save
    # their own setup (about 100 s a job). 2026-11-21: 754 jobs in 65 runs, 29% of the runner time was job setup,
    # and with 20 concurrent jobs for the organisation the median run waited a minute for a runner.
    cap = max([JOB_WEIGHT, *(_entry_weight(e, seconds) for e in entries if e["name"].startswith("affected-") and e.get("kind") == "pytest")])
    out: list[tuple[dict, int]] = []
    for entry in entries:
        w = _entry_weight(entry, seconds)
        host = next((o for o in out if entry["name"].startswith("affected-") and o[0]["name"].startswith("affected-")
                     and o[0]["ros"] == entry["ros"] and o[0]["kind"] == entry["kind"] == "pytest"
                     and o[0].get("colcon", True) == entry.get("colcon", True)  # a guard-only runner skips colcon
                     and o[1] + w <= cap), None)
        if host:
            host[0]["invocations"] = [*host[0]["invocations"], *entry["invocations"]]
            if entry.get("git_history"):
                host[0]["git_history"] = True
            out[out.index(host)] = (host[0], host[1] + w)
        else:
            out.append((dict(entry), w))
    return [e for e, _ in out]


def pack_to_limit(entries: list[dict], seconds: dict[str, int], limit: int) -> list[dict]:
    """Merge lightest compatible ``affected-*`` jobs when a selection exceeds ``limit``."""
    out = [dict(e) for e in entries]
    while len(out) > limit:
        pairs = [
            (_entry_weight(out[i], seconds) + _entry_weight(out[j], seconds), i, j)
            for i in range(len(out))
            if out[i]["name"].startswith("affected-") and out[i].get("kind") == "pytest"
            for j in range(i + 1, len(out))
            if out[j]["name"].startswith("affected-") and out[j].get("kind") == "pytest"
            and out[i]["ros"] == out[j]["ros"]
            and bool(out[i].get("colcon", True)) == bool(out[j].get("colcon", True))
        ]
        if not pairs:
            break
        _, i, j = min(pairs)
        out[i]["invocations"] = [*out[i]["invocations"], *out[j]["invocations"]]
        if out[j].get("git_history"):
            out[i]["git_history"] = True
        out.pop(j)
    return out
