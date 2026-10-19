"""PR runners take the ROS environment the full tier gives each path (PR #96, 2026-10-18).

The affected tier ran every invocation under ros: overlay while the full tier runs CORE gateway,
Fleet and other suites under ros: none, so tests main skips (gateway rclpy) ran only on PRs,
failed and hung the runner. An invocation that mixes environments becomes one runner per
environment; every selected path still runs exactly once.
"""
from __future__ import annotations


def _under(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def full_tier_ros(path: str, matrix) -> str:
    """The full-tier ROS environment for ``path``; paths outside ``matrix`` keep overlay."""
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
