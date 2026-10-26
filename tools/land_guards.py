"""Quick structural guard round for tools/land.py, before the long round of the same landing.

On 2026-10-15 a ``safety_modules`` tag change failed
``test/architecture/test_safety_separation.py`` only inside a ~25-minute FULL round.
The guards run first (lab PCs, known_failures compare, as every round) and a NEW
failure stops the landing before the long round starts. The same round carries land_isolation's collection
gate and its files run alone (2026-10-26: a folder that passed in one pytest process failed file by file).
Standard library only.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import land_isolation

GUARDS = ("test/architecture", "test/test_harness_contracts.py")


def first(wt: Path, args, invocations: list[list[str]], logdir: Path, round_no: int | str, run_tests) -> list[str]:
    """Run the guards through land's own run_tests; summary lines, or [] when skipped.

    Skipped for explicit --tests; the guards are left out when every selected path already is a guard.
    """
    if args.tests != "auto":
        return []
    guards = [g for g in GUARDS if (wt / g).exists()]
    paths = [p.rstrip("/") for inv in invocations for p in inv]
    batch = [] if not guards or all(any(p == g or p.startswith(g + "/") for g in guards) for p in paths) else [guards]
    if not (batch := batch + land_isolation.invocations(wt, invocations)):
        return []
    quick = argparse.Namespace(**{**vars(args), "node": False})
    # "g<n>" keeps these logs out of land_record's run-<n>-*.txt glob.
    done = run_tests(wt, quick, batch, logdir, f"g{round_no}")
    return [f"round {round_no}: guard round first: {line}" for line in done]
