"""D-889 addendum 12: the complete FULL tier on main, every browser and simulation suite included, once a night.

Per-landing tiers now skip browser suites a landing's own change does not map to and simulation suites unless a
simulation path changed; this run catches what they let through. A NEW failure (test/known_failures.txt, flaky
quarantine excluded) is recorded as MAIN-RED (land_mainred.red), so the next landings see it as main's, not theirs.
The landing watcher schedules it at night, before the 05:30 test-PC cleanup.
D-1036 addendum (2026-11-19): an invocation with NEW or only quarantined failures reruns once on the same sha; a clean
rerun counts (its row and log are recorded) and the ids it cleared go to the LOAD-FLAKY candidates file.

    python tools/land_nightly.py [--plan]      # from the main checkout; --plan prints the invocations only
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
ROOT = TOOLS.parent
sys.path[:0] = [str(TOOLS), str(TOOLS / "remote"), str(TOOLS / "hooks"), str(ROOT / "test")]

import known_failures  # noqa: E402
import land_browser  # noqa: E402
import land_cache  # noqa: E402
import land_checks  # noqa: E402
import land_mainred  # noqa: E402
import land_record  # noqa: E402
import remote_pytest  # noqa: E402
from harness import affected_exclusive  # noqa: E402

MAX_RERUNS = 8  # invocations rerun per night; more red than this is a real break, not load
SUMMARY = re.compile(r"(?m)^=*\s*\d+ (passed|failed|skipped|errors?|xfailed|xpassed)\b.* in [0-9.]+s\b")


def _json(*command: str) -> list | dict:
    result = subprocess.run([sys.executable, *command], cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                            check=True)
    return json.loads(result.stdout)


def _main_sha() -> str:
    return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "main"], capture_output=True, text=True,
                          check=True).stdout.strip()


def _common() -> Path:
    return Path(subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                               capture_output=True, text=True, check=True).stdout.strip())


def _green_marker() -> Path:
    """Where the last main sha whose night ran with 0 NEW is kept (shared by every worktree)."""
    return _common() / "rosy-nightly-green"


def _candidates() -> Path:
    """land_checks' LOAD-FLAKY candidates file (git common dir), which land_stats and owners read."""
    return _common() / land_checks.CANDIDATES


def _clean(inv: list[str], log: Path, code, text: str) -> bool:
    """A verdict: summary present, usable exit, exclusive evidence or a non-vacuous browser run."""
    return bool(SUMMARY.search(text) and land_cache.unusable(code, log) is None
                and (affected_exclusive.evidence(log, code) is None if affected_exclusive.dedicated(inv)
                     else not land_browser.vacuous(inv, log)))


def _text(log: Path) -> str:
    return log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""


def plan(sha: str | None = None) -> list[list[str]]:
    """The canonical FULL tier plus every registered browser suite (the explicit FULL a publish landing runs).
    ``sha`` pins base and head to the commit the night tests, so main moving meanwhile cannot change the plan."""
    base = ["--base", sha, "--head", sha] if sha else ["--base", "main"]
    full = _json("tools/harness/rosy_harness.py", "affected", *base, "--json", "--full")
    return full["full_invocations"] + _json("tools/land_selection.py", "--all-browsers")


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--plan", action="store_true")
    opts = args.parse_args(argv)
    main_sha = _main_sha()  # read once: the plan and the run must be about the same commit
    invocations = plan(main_sha)
    if opts.plan:
        print(json.dumps(invocations))
        return 0
    logdir = land_checks.tmp_dir(f"nightly-{main_sha[:10]}")
    # Before the tier, so an id that fails tonight is recorded and not closed by its own rerun.
    land_mainred.recheck(ROOT, main_sha, lambda invs, runs: remote_pytest.run(
        invs, runs, main_sha, repo=ROOT, label="nightly"), logdir)
    marker = _green_marker()
    # 2026-11-08: a night with no new main commit re-ran the same complete tier for nothing.
    if marker.is_file() and marker.read_text(encoding="utf-8").strip() == main_sha:
        print(f"[nightly] {main_sha[:10]}: unchanged since the last green night, tier skipped", flush=True)
        return 0
    logs = [logdir / f"nightly-{n}.txt" for n in range(len(invocations))]
    codes = remote_pytest.run(invocations, logs, main_sha, repo=ROOT, label="nightly")
    env = land_cache.env_id(ROOT, main_sha)
    tree = (land_cache._git(ROOT, "rev-parse", f"{main_sha}^{{tree}}").stdout.strip() if env else "")
    lists = {path: known_failures.load_known((ROOT / path).read_text(encoding="utf-8"))
             for path in ("test/known_failures.txt", "test/flaky_quarantine.txt") if (ROOT / path).is_file()}
    known = {name: why for found in lists.values() for name, why in found.items()}
    quarantined = set(lists.get("test/flaky_quarantine.txt", ()))
    rows, clean, reds, wanted = list(logs), set(), {}, []
    for n, (inv, log, code) in enumerate(zip(invocations, logs, codes or [0] * len(invocations))):
        text = _text(log)
        ids, seen, _ = known_failures.compare(text, known)
        if ids:
            reds[n] = (ids, text)
        elif _clean(inv, log, code, text):
            clean.add(n)
        # 11-18: every NEW of a red night passed on the next main, and quarantined-only invocations never got a row.
        if ids and not land_checks._safety(ROOT, sys.executable, ids) or not ids and quarantined & set(seen):
            wanted.append(n)  # D-762: a safety id is never retried
    chosen, flaky = wanted[:MAX_RERUNS], []
    if chosen:
        again = [logdir / f"nightly-{n}-rerun.txt" for n in chosen]
        rerun_codes = remote_pytest.run([invocations[n] for n in chosen], again, main_sha, repo=ROOT,
                                        label="nightly-rerun") or []
        for n, log, code in zip(chosen, again, rerun_codes):
            text = _text(log)
            if code == 0 and not known_failures.compare(text, known)[0] and _clean(invocations[n], log, code, text):
                rows[n] = log
                clean.add(n)
                flaky += [(nodeid, logs[n], log) for nodeid in reds.pop(n, ([], ""))[0]]
        print(f"[nightly] rerun: {len(chosen)} of {len(wanted)} invocation(s) (cap {MAX_RERUNS}),"
              f" {sum(n in clean for n in chosen)} clean, {len(flaky)} LOAD-FLAKY id(s)", flush=True)
    if flaky:
        day = time.strftime("%Y-%m-%d")
        with open(_candidates(), "a", encoding="utf-8") as out:
            for nodeid, first, second in flaky:
                out.write(f"{nodeid}  # LOAD-FLAKY {day}: failed in {first} on {main_sha[:10]}, passed on the nightly"
                          f" rerun in {second}; review for test/flaky_quarantine.txt (D-762 evidence rules)\n")
                print(f"LOAD-FLAKY {nodeid}")
    new = []
    for n, (ids, text) in reds.items():
        # The env makes recheck and later selections run a browser id instead of skipping it forever.
        env_tokens = [token for token in invocations[n] if land_checks.ENV_TOKEN.match(token)]
        land_mainred.red(ROOT, main_sha, ids, text, env_tokens, by="nightly")
        new += ids
    for n in sorted(clean) if env and tree else ():  # G1 too: publish_evidence.clean() demands its strict receipt
        land_cache.record(ROOT, main_sha, tree, env, invocations[n], rows[n])
    recorded = len(clean) if env and tree else 0
    print(f"[nightly] {main_sha[:10]}: {len(invocations)} invocation(s), {len(new)} NEW", flush=True)
    for nodeid in new:
        print(f"NEW       {nodeid}")
    # a missing or cut log compares as 0 NEW: only a night whose every log reached pytest's summary is green
    if not new and all(SUMMARY.search(_text(log)) for log in rows):
        marker.write_text(main_sha + "\n", encoding="utf-8")
        # Every invocation has a clean exact row: this night is the explicit FULL tools/publish_main.py looks for.
        if recorded == len(invocations):
            land_record.write(ROOT, main_sha, main_sha, invocations, [str(log) for log in rows], tier="full")
    return 1 if new else 0


if __name__ == "__main__":
    sys.exit(main())
