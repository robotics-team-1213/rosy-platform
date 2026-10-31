"""D-889 addendum 12: the complete FULL tier on main, every browser and simulation suite included, once a night.

Per-landing tiers now skip browser suites a landing's own change does not map to and simulation suites unless a
simulation path changed; this run catches what they let through. A NEW failure (test/known_failures.txt, flaky
quarantine excluded) is recorded as MAIN-RED (land_mainred.red), so the next landings see it as main's, not theirs.
The landing watcher schedules it at night, before the 05:30 test-PC cleanup.

    python tools/land_nightly.py [--plan]      # from the main checkout; --plan prints the invocations only
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path[:0] = [str(TOOLS), str(TOOLS / "remote"), str(ROOT / "test")]

import known_failures  # noqa: E402
import land_checks  # noqa: E402
import land_mainred  # noqa: E402
import remote_pytest  # noqa: E402


def _json(*command: str) -> list | dict:
    result = subprocess.run([sys.executable, *command], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            check=True)
    return json.loads(result.stdout)


def plan() -> list[list[str]]:
    """The canonical FULL tier plus every registered browser suite (the explicit FULL a publish landing runs)."""
    full = _json("tools/harness/rosy_harness.py", "affected", "--base", "main", "--json", "--full")
    return full["full_invocations"] + _json("tools/land_selection.py", "--all-browsers")


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--plan", action="store_true")
    opts = args.parse_args(argv)
    invocations = plan()
    if opts.plan:
        print(json.dumps(invocations))
        return 0
    main_sha = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "main"], capture_output=True, text=True,
                              check=True).stdout.strip()
    logdir = land_checks.tmp_dir(f"nightly-{main_sha[:10]}")
    logs = [logdir / f"nightly-{n}.txt" for n in range(len(invocations))]
    remote_pytest.run(invocations, logs, main_sha, repo=ROOT, label="nightly")
    known = {name: why for path in ("test/known_failures.txt", "test/flaky_quarantine.txt") if (ROOT / path).is_file()
             for name, why in known_failures.load_known((ROOT / path).read_text(encoding="utf-8")).items()}
    new = []
    for log in logs:
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        ids = known_failures.compare(text, known)[0]
        if ids:
            land_mainred.red(ROOT, main_sha, ids, text, [], by="nightly")
            new += ids
    print(f"[nightly] {main_sha[:10]}: {len(invocations)} invocation(s), {len(new)} NEW", flush=True)
    for nodeid in new:
        print(f"NEW       {nodeid}")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
