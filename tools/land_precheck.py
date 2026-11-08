"""The cheap landing gates, run by land_async.py before it creates a snapshot or a ticket (2026-11-09 bottleneck report).

safety review, size ratchet, lint (ADR gaps included) and the secret scan took 67 + 18 stops that only showed up
inside the queued supervisor, after the owner had left. Here they fail fast in the owner's own terminal. The branch is
not touched: when main is not yet in it lint is advisory (the supervisor re-lints after merging main).
"""

from __future__ import annotations

from pathlib import Path


def precheck(land, wt: Path, python: str) -> None:
    """``land`` is tools/land.py (its Stop, gates and git helpers); raises land.Stop on the first failing gate."""
    before = land.out(wt, "rev-parse", "main")
    land.safety_review(wt, before, "HEAD", python)
    land.size_check(wt, before, "HEAD", python)
    merged = land.git(wt, "merge-base", "--is-ancestor", before, "HEAD", check=False).returncode == 0
    if (wt / land.HARNESS).is_file():
        try:
            land.step(wt, [python, land.HARNESS, "lint"], None, "lint")
        except land.Stop as exc:
            if merged:
                raise
            print(f"[precheck] lint fails before main is merged (the supervisor re-lints after the merge): {exc}")
    land.secret_scan(wt, before)
    print("[precheck] safety review, size ratchet, lint and secret scan passed", flush=True)
