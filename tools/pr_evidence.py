"""Produce lab evidence for tools/pr_land.py: run its required lab invocations remotely, record land_cache rows (D-1055).

Usage::

    python tools/pr_evidence.py <head-ref> [--base origin/main] [--dry-run] [--solo]

Runs from the worktree that has <head-ref> checked out (pr_land reads the same tree). Same runner and the same clean-pass
rule as tools/publish_evidence.py fill(); nothing in pr_land's checks is relaxed.

After a failed attempt under load, rerun with ``--solo``: the missing invocations run one at a time, each alone on its host
(ROSY_JOB_ALONE=1, as land.py's D-790 rerun alone); ``solo.txt`` in the log dir lists them. Passes are recorded the same way.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
for _extra in (str(TOOLS), str(TOOLS / "remote"), str(TOOLS / "harness"), str(TOOLS.parent / "test")):
    if _extra not in sys.path:
        sys.path.insert(0, _extra)

import land_browser  # noqa: E402
import land_cache  # noqa: E402
import land_checks  # noqa: E402
import pr_land  # noqa: E402


class _Tee:
    """A stream that also appends what is written to a file."""

    def __init__(self, stream, out):
        self._stream, self._out = stream, out

    def write(self, text):
        self._out.write(text)
        return self._stream.write(text)

    def __getattr__(self, name):
        return getattr(self._stream, name)


def main(argv: list[str] | None = None, repo: Path | None = None, run=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("head", help="branch or commit to produce evidence for (must be this worktree's HEAD)")
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--dry-run", action="store_true", help="list the lab invocations only")
    parser.add_argument("--solo", action="store_true", help="run the missing invocations one at a time, each alone on its host")
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
    todo = pr_land.lab_missing(cwd, head, required)  # an intact earlier pass on this tree & env is kept, not rerun
    if not todo:
        print("[pr-evidence] every invocation already has an intact pass; nothing to run")
        return 0
    env = land_cache.env_id(cwd, head)
    if not env:
        raise SystemExit("[pr-evidence] test environment id unavailable; cannot record evidence")
    tree = pr_land._run(["git", "rev-parse", f"{head}^{{tree}}"], cwd)
    # one directory per run: a rerun must not overwrite the logs earlier rows hash (log_sha256)
    logdir = land_checks.tmp_dir(f"pr-evidence-{head[:10]}-{time.strftime('%Y%m%dT%H%M%S')}")
    logs = [logdir / f"lab-{n}.txt" for n in range(len(todo))]
    if run is None:
        import remote_pytest
        run = remote_pytest.run
    run_lab = run

    def run(*a, **k):  # the lab logs do not say why a host was skipped; placement.txt keeps remote_pytest's host and placement lines
        with (logdir / "placement.txt").open("a", encoding="utf-8", buffering=1) as out, \
                contextlib.redirect_stdout(_Tee(sys.stdout, out)), contextlib.redirect_stderr(_Tee(sys.stderr, out)):
            return run_lab(*a, **k)

    # -rA prints the PASSED lines pr_land.passed_ids needs; the row keeps the plain argv pr_land compares (xdist_plan.tail honours -rA)
    if args.solo:  # ROSY_JOB_ALONE=1 takes the whole host (work_queue.host_alone); the recorded row keeps the plain argv
        (logdir / "solo.txt").write_text("".join(" ".join(inv) + "\n" for inv in todo), encoding="utf-8")
        codes = [c for inv, log in zip(todo, logs)
                 for c in run([["ROSY_JOB_ALONE=1", *inv, "-rA"]], [log], head, repo=cwd, label="pr-evidence-solo")]
    else:
        codes = run([[*inv, "-rA"] for inv in todo], logs, head, repo=cwd, label="pr-evidence")
    passed = 0
    for inv, log, code in zip(todo, logs, codes):
        # a clean pass only, exactly publish_evidence.fill's rule
        # exit 5 counts only as land_cache's D-889 20 all-skipped verdict (unusable() demands the pattern)
        ok = (code in (0, 5) and log.is_file() and land_cache.unusable(code, log) is None
              and not land_browser.vacuous(inv, log))
        if ok:
            land_cache.record(cwd, head, tree, env, inv, log)
            passed += 1
        else:
            print(f"[pr-evidence] FAILED exit {code}: {' '.join(inv)} (log {log})")
    print(f"[pr-evidence] {passed}/{len(todo)} recorded, {len(required) - len(todo)} kept (logs {logdir})")
    if passed < len(todo) and not args.solo:
        print("[pr-evidence] load-sensitive failures: rerun with --solo (recorded groups are reused)")
    return 0 if passed == len(todo) and len(codes) == len(todo) else 1


if __name__ == "__main__":
    raise SystemExit(main())
