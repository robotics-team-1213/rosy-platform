"""Quick structural guard round for tools/land.py, before the long round of the same landing.

On 2026-10-15 a ``safety_modules`` tag change failed
``test/architecture/test_safety_separation.py`` only inside a ~25-minute FULL round.
In the turn the guards run first (lab PCs, known_failures compare, as every round) and a NEW
failure stops the landing before the long round starts; before the turn (land_prepare) they run beside the
selection, since waiting for them held a pretest slot 150-870 s (2026-10-27). The same round carries land_isolation's checks of what a
shared pytest process hides: before the turn (``isolated``, land_prepare) the collection gate and the tests run
alone; in the turn only those alone runs main's delta made stale. Standard library only.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import land_isolation

GUARDS = ("test/architecture", "test/test_harness_contracts.py")


def first(wt: Path, args, invocations: list[list[str]], logdir: Path, round_no: int | str, run_tests,
          isolated: bool = False) -> list[str]:
    """Run the guards (and land_isolation's jobs) through land's own run_tests; summary lines, or [] when skipped.

    Skipped for explicit --tests; the guards are left out when every selected path already is a guard.
    """
    if args.tests != "auto":
        return []
    guards = [g for g in GUARDS if (wt / g).exists()]
    paths = [p.rstrip("/") for inv in invocations for p in inv]
    batch = [] if not guards or all(any(p == g or p.startswith(g + "/") for g in guards) for p in paths) else [guards]
    quick = argparse.Namespace(**{**vars(args), "node": False})
    branch = subprocess.run(["git", "-C", str(wt), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True,
                            text=True).stdout.strip()
    # "g<n>" keeps these logs out of land_record's run-<n>-*.txt glob.
    done = land_isolation.run(wt, branch, invocations, quick, logdir, str(round_no), run_tests, batch, isolated)
    return [f"round {round_no}: guard round first: {line}" for line in done]
