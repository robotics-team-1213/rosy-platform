"""Produce lab evidence for tools/pr_land.py: run its required lab invocations remotely, record land_cache rows (D-1055).

Usage::

    python tools/pr_evidence.py <head-ref> [--base origin/main] [--dry-run]

Runs from the worktree that has <head-ref> checked out (pr_land reads the same tree). Same runner and the same clean-pass
rule as tools/publish_evidence.py fill(); nothing in pr_land's checks is relaxed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
for _extra in (str(TOOLS), str(TOOLS / "remote"), str(TOOLS / "harness"), str(TOOLS.parent / "test")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import land_browser  # noqa: E402
import land_cache  # noqa: E402
import land_checks  # noqa: E402
import pr_land  # noqa: E402


def main(argv: list[str] | None = None, repo: Path | None = None, run=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("head", help="branch or commit to produce evidence for (must be this worktree's HEAD)")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--dry-run", action="store_true", help="list the lab invocations only")
    args = parser.parse_args(argv)
    cwd = (repo or Path.cwd()).resolve()
    head = pr_land._run(["git", "rev-parse", f"{args.head}^{{commit}}"], cwd)
    if head != pr_land._run(["git", "rev-parse", "HEAD"], cwd):
        raise SystemExit(f"[pr-evidence] {args.head} is not this worktree's HEAD; run from its worktree")
    required = pr_land.required_lab_invocations(cwd, args.base, head)
    print(f"[pr-evidence] {head[:10]}: {len(required)} lab invocation(s)")
    for inv in required:
        print("  " + " ".join(inv))
    if args.dry_run or not required:
        return 0
    env = land_cache.env_id(cwd, head)
    if not env:
        raise SystemExit("[pr-evidence] test environment id unavailable; cannot record evidence")
    tree = pr_land._run(["git", "rev-parse", f"{head}^{{tree}}"], cwd)
    logdir = land_checks.tmp_dir(f"pr-evidence-{head[:10]}")
    logs = [logdir / f"lab-{n}.txt" for n in range(len(required))]
    if run is None:
        import remote_pytest
        run = remote_pytest.run
    # -rA prints the PASSED lines pr_land.passed_ids needs; the row keeps the plain argv pr_land compares (xdist_plan.tail honours -rA)
    codes = run([[*inv, "-rA"] for inv in required], logs, head, repo=cwd, label="pr-evidence")
    passed = 0
    for inv, log, code in zip(required, logs, codes):
        # a clean pass only, exactly publish_evidence.fill's rule
        # exit 5 counts only as land_cache's D-889 20 all-skipped verdict (unusable() demands the pattern)
        ok = (code in (0, 5) and log.is_file() and land_cache.unusable(code, log) is None
              and not land_browser.vacuous(inv, log))
        if ok:
            land_cache.record(cwd, head, tree, env, inv, log)
            passed += 1
        else:
            print(f"[pr-evidence] FAILED exit {code}: {' '.join(inv)} (log {log})")
    print(f"[pr-evidence] {passed}/{len(required)} recorded (logs {logdir})")
    return 0 if passed == len(required) and len(codes) == len(required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
