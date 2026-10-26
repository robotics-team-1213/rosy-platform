"""Land a topic branch on local main: merge main, test, fast-forward, repeat.

Run from a topic worktree (never the shared main checkout)::

    python tools/land.py [--main-checkout PATH] [--tests auto|none|"<pytest args>"]
                         [--node] [--max-rounds N] [--dry-run] [--prune | --no-prune] [--no-cache]
                         [--queue-timeout MIN | --no-queue]

Landings of one clone take turns (``land_queue.py``): the run waits in a FIFO queue under the git
common dir until no live ticket is ahead, so it merges ``main`` once, after the one ahead landed.
Each round merges the current local ``main`` into the branch, auto-resolves the
append-only/generated conflicts (ADR Log, logs.md, adr_gaps.txt, index.md,
STATUS.md; ``tools/harness/adr_gaps.txt`` arrives with the ADR-reservation
branch and the rule is inert until then), runs the selected tests, compares them with
``test/known_failures.py``, and fast-forwards main only if main is still the
commit that was tested. A failing step stops the tool: landing is never chained
after a failure. Any other conflict aborts the merge and lists the paths.
pytest runs through ``tools/remote/remote_pytest.py`` (model PC, AI PC or site PC by
measured headroom, D-568; an unavailable host stops landing); an auto selection adds the
real-Chromium tests ``test/browser_scope.py`` maps the changed paths to. Lint, node and the
known_failures comparison stay here. A branch on the pre-rewrite history is refused, and NEW failures
that each pass when rerun alone land as LOAD-FLAKY (D-790, ``land_checks.py``). Never pushes,
stashes, resets or cleans. A pytest invocation that passed on the same tree (or, when the selector
vouches for the delta, an ancestor) is reused from ``land_cache.py`` unless --no-cache. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent / "remote"))
import remote_pytest  # noqa: E402  (tools/remote: pytest on the model/AI/site PC, D-568)
import browser_scope  # noqa: E402  (test/, on sys.path through remote_pytest)
sys.path.insert(0, str(Path(__file__).resolve().parent / "hooks"))
import land_record  # noqa: E402  (D-553 addendum 3: pre-push reuses these results)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktrees  # noqa: E402  (D-761: every landing reports finished worktrees)
from land_logs import append_blocks  # noqa: E402,F401  (logs.md: whole entries, date order; tests call it here)
import land_guards  # noqa: E402  (structural guards before the long round)
import land_queue  # noqa: E402  (one lander per clone at a time, FIFO)
import land_full  # noqa: E402  (a green tier outlives the run that passed it)
import land_prepare  # noqa: E402  (D-889 A': tests outside the lock, then main's delta at the turn)
import land_checks  # noqa: E402  (D-790: load-flaky rerun; scratch folder, origin distance)
import land_cache  # noqa: E402  (passed invocations reused across land.py runs)
import land_events  # noqa: E402  (rosy-land-events.jsonl: what each landing did)
from land_checks import ahead_of_origin, tmp_dir  # noqa: E402
from land_merge import (ADR_GAPS, ADR_LOG, conflict_stages, landed_gaps, plan,  # noqa: E402,F401  (auto-resolve)
                        generate_records, resolver)
import worktree_rules  # noqa: E402  (D-790: stale-history refusal)

HARNESS = "tools/harness/rosy_harness.py"
HARNESS_TRIGGER = ": harness configuration or the selector itself"  # affected_tests.FULL_TRIGGERS
SIZE_RANGE = "tools/harness/size_range.py"  # D-766: git-only, seconds; the FULL tier would only find it after the remote round trip
SAFETY = "tools/harness/safety_review.py"  # D-430 5: the rule CI's scope job enforces
# Every child gets UTF-8 stdio (Korean paths and log text on a cp949 console).
ENV = {**os.environ, "PYTHONUTF8": "1"}


TURN_CAP_S = 600  # D-889: a turn's delta tests past this move outside the lock (land_prepare.again)


class Stop(Exception):
    """A step failed; the message says why. Exit 1."""


class Overtime(Stop): """The turn's tests ran past TURN_CAP_S, the rest cancelled: land() prepares them outside."""


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(cwd), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
    if check and result.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed:\n{result.stdout}{result.stderr}".rstrip())
    return result


def out(cwd: Path, *args: str) -> str:
    return git(cwd, *args).stdout.strip()


def lines(cwd: Path, *args: str) -> list[str]:
    return [line for line in out(cwd, *args).splitlines() if line]


# --- merging (conflict auto-resolution itself: land_merge.py) --------------------

def merge(wt: Path, main_sha: str, branch: str, python: str, dry_run: bool) -> list[str]:
    """Merge main_sha into HEAD; return the auto-resolved paths. Stop on anything else."""
    if dry_run:
        tree = git(wt, "merge-tree", "--write-tree", "--no-messages", "HEAD", main_sha, check=False)
        conflicts = conflict_stages(tree.stdout) if tree.returncode == 1 else {}
        resolved, manual = plan(wt, conflicts)
        print(f"[plan] merge main {main_sha[:10]}: "
              + (f"auto-resolve {sorted(resolved)}, needs a human: {manual}" if conflicts else "no conflicts"))
        if manual:
            raise Stop("merge would conflict outside the auto-resolvable set:\n  " + "\n  ".join(manual))
        return sorted(resolved)
    result = git(wt, "merge", "--no-edit", "--no-commit", "-m",
                 f"Merge branch 'main' into {branch}", main_sha, check=False)
    if result.returncode == 0 and git(wt, "rev-parse", "--verify", "MERGE_HEAD", check=False).returncode != 0:
        return []
    resolved = {}
    if result.returncode != 0:
        try:
            conflicts = conflict_stages(out(wt, "ls-files", "-u"))
            resolved, manual = plan(wt, conflicts)
        except (Stop, OSError, subprocess.CalledProcessError) as exc:
            git(wt, "merge", "--abort", check=False)
            raise Stop(f"reading the conflict stages failed, merge aborted:\n{exc}") from exc
        if not conflicts or manual:
            git(wt, "merge", "--abort", check=False)
            raise Stop("merge aborted; resolve by hand in the worktree:\n  "
                       + "\n  ".join(manual or [result.stdout + result.stderr]))
    try:
        for path, data in resolved.items():
            (wt / path).write_bytes(data)
            git(wt, "add", "--", path)
        if (wt / HARNESS).is_file():
            existing_untracked = set(lines(wt, "ls-files", "--others", "--exclude-standard"))
            written = generate_records(wt, python, HARNESS)
            changed = set(lines(wt, "diff", "--name-only")) | set(
                lines(wt, "ls-files", "--others", "--exclude-standard")) - existing_untracked
            unexpected = changed - set(written)
            if unexpected:
                raise Stop(f"changes outside canonical generation targets: {sorted(unexpected)}")
            if written:
                git(wt, "add", "--", *written)
        gaps, dropped = landed_gaps(wt)
        if dropped:  # in the merge commit, so the pretest's merge drops them too and land_full keeps its FULL pass
            (wt / ADR_GAPS).write_bytes(gaps)
            git(wt, "add", "--", ADR_GAPS)
            print(f"[merge] {ADR_GAPS}: dropped {dropped}, their ADR now exists")
            resolved[ADR_GAPS] = gaps
        git(wt, "commit", "--no-edit")
    except (Stop, ValueError, KeyError, OSError, subprocess.CalledProcessError) as exc:
        abort = git(wt, "merge", "--abort", check=False)
        # `merge --abort` leaves files generate created; list them, never delete them.
        left = lines(wt, "ls-files", "--others", "--exclude-standard")
        recovery = ("merge aborted" if abort.returncode == 0 else
                    "abort failed; merge, index and worktree preserved for manual recovery:\n"
                    + abort.stdout + abort.stderr)
        raise Stop(f"auto-resolve of {sorted(resolved)} failed, {recovery}:\n{exc}"
                   + (f"\nuntracked files left in the worktree (not deleted): {left}" if left else "")) from exc
    print(f"[merge] auto-resolved {sorted(resolved)}")
    return sorted(resolved)


# --- test selection -------------------------------------------------------------

def _test_dir(path: str) -> str | None:
    parts = PurePosixPath(path).parts
    return "/".join(parts[: parts.index("test") + 1]) if "test" in parts else None


def fallback_targets(wt: Path, changed: list[str]) -> list[str]:
    """Nearest ancestor ``test/`` dir per changed file; test files map to themselves."""
    targets: list[str] = []
    for path in changed:
        name = PurePosixPath(path).name
        own = _test_dir(path)
        if own:
            target = path if name.startswith("test_") and name.endswith(".py") else own
        else:
            target = next((f"{p}/test".lstrip("./") for p in map(str, PurePosixPath(path).parents)
                           if (wt / p / "test").is_dir()), None)
        if target and (wt / target).exists() and target not in targets:
            targets.append(target)
    return targets


def pack(wt: Path, paths: list[str]) -> list[list[str]]:
    """Split paths into pytest invocations so no two test files share a basename."""
    groups: list[tuple[list[str], set[str]]] = []
    for path in paths:
        root = wt / path
        names = {root.name} if root.is_file() else {p.name for p in root.rglob("test_*.py")}
        for members, seen in groups:
            if not names & seen:
                members.append(path)
                seen |= names
                break
        else:
            groups.append(([path], set(names)))
    return [members for members, _ in groups]


def select(wt: Path, base: str, python: str, head: str | None = None,
           landed: bool = False) -> tuple[list[list[str]], str | None]:
    """pytest invocations for base...HEAD (or base...head), and a FULL note owed to the summary.

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
    ``landed``: base...head is main's delta, already on main with its own FULL tier when it escalated.
    """
    if (wt / "tools/harness/affected_tests.py").is_file():
        # Strict UTF-8: the JSON must parse whole; PYTHONUTF8 makes the child write UTF-8.
        result = subprocess.run([python, HARNESS, "affected", "--base", base, *(["--head", head] if head else []),
                                 "--json"], cwd=wt,
                                capture_output=True, text=True, encoding="utf-8", env=ENV)
        if result.returncode != 0:
            raise Stop(f"affected selector failed (exit {result.returncode}); not guessing tests:\n"
                       f"{result.stdout}{result.stderr}".rstrip())
        try:
            sel = json.loads(result.stdout)
            if landed and sel["escalations"] and all(e.endswith(HARNESS_TRIGGER) for e in sel["escalations"]):
                # A harness edit on main passed its own FULL tier when it landed; a FULL tier for every lander
                # behind it held the queue an hour each (2026-10-25). Its guards and mapped suites still run.
                print("[tests] main's delta escalated only for harness files that landed with their own FULL"
                      " tier: the guards and its mapped suites")
                return sel["local_invocations"] + browser_tier(wt, base, head), None
            if sel["mode"] == "full":
                # D-762 stage 0: a FULL-class landing runs the whole tier on the lab PCs, never
                # guards alone; not via GitHub, which would publish unpushed main commits.
                note = "selector escalated to FULL (" + "; ".join(sel["escalations"][:3]) + "): full tier on the lab PCs"
                print(f"[tests] {note}")
                return sel["full_invocations"] + browser_tier(wt, base, head), note
            return sel["invocations"] + browser_tier(wt, base, head), None
        except (ValueError, KeyError, TypeError) as exc:
            raise Stop(f"affected selector printed unusable JSON ({exc!r}); not guessing tests") from exc
    changed = lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")  # main's delta when head is given
    return pack(wt, fallback_targets(wt, changed)) + browser_tier(wt, base, head), None


def browser_tier(wt: Path, base: str, head: str | None = None) -> list[list[str]]:
    """The real-Chromium tests for the paths base...head changes, opted in on the test host only."""
    changed = lines(wt, "diff", "--name-only", f"{base}...{head or 'HEAD'}")
    return [[remote_pytest.BROWSER_ENV, *chunk] for group in pack(wt, browser_scope.targets(changed))
            for chunk in balanced(wt, group, BROWSER_CHUNKS)]


# remote_pytest.run's hosts take invocations from one queue, but one browser invocation still ran
# ~30 min on one host after the rest; 4 chunks let both hosts share that tail.
BROWSER_CHUNKS = 4


def balanced(wt: Path, paths: list[str], n: int) -> list[list[str]]:
    """paths in at most n lists of near-equal total size: largest first, each into the lightest list.

    A sub-list of one pack() group keeps its basenames apart."""
    # ponytail: file size stands in for run time; use recorded pytest --durations if chunks skew.
    size = {p: (wt / p).stat().st_size if (wt / p).is_file() else 0 for p in paths}
    bins: list[tuple[list[int], list[str]]] = [([0], []) for _ in range(min(n, len(paths)))]
    for path in sorted(paths, key=lambda p: -size[p]):
        total, members = min(bins, key=lambda b: b[0][0])
        total[0] += size[path]
        members.append(path)
    return [sorted(members) for _, members in bins]


def safety_review(wt: Path, base: str, head: str, python: str) -> None:
    """D-762 stage 0: the commits this landing adds to main (base..head) pass CI's D-430 5 rule first."""
    if not (wt / SAFETY).is_file():
        return
    code, text = step(wt, [python, SAFETY, base, head], None, "safety-review", allow_fail=True)
    if code and "without a `Safety-Review:" not in text:  # a crash or missing history: no trailer advice
        raise Stop(f"{text.strip()}\nsafety_review.py failed (exit {code}); not landing")
    if code:
        raise Stop(f"{text.strip()}\nnot landing: each commit listed needs a `Safety-Review: <reviewer/lane>"
                   " <evidence>` trailer in its own message; a later trailer-only commit does not cover it, and"
                   " --amend/rebase are not used here. Re-create the change on a new branch from main with the"
                   " trailer (git cherry-pick -n <sha>, then git commit), or add the full SHA to"
                   " tools/harness/safety_review_exempt.json with an independent review (D-430 5)")


def size_check(wt: Path, base: str, head: str, python: str) -> None:
    """D-766: every commit base..head passes the size ratchet, before any test host is touched."""
    if (wt / SIZE_RANGE).is_file():
        code, text = step(wt, [python, SIZE_RANGE, base, head], None, "size-range", allow_fail=True)
        if code:  # D-766: the row is the measured count and never rises; split instead (size_ratchet.txt header)
            raise Stop(f"{text.strip()}\nsize ratchet fails locally; not landing. Fix on the branch: bring each file"
                       f" named above under its limit (move code to a new module) or back to its ratchet row; never"
                       f" raise a row. Check with: python {SIZE_RANGE} main HEAD")


def record_only(path: str) -> bool:
    """Records no module test reads. Root test/ guards do read docs, so they rerun anyway."""
    name = PurePosixPath(path).name
    return (name in ("logs.md", "index.md", "progress.md") or path in (ADR_LOG, ADR_GAPS)
            or path.startswith("docs/adr/"))


# --- running --------------------------------------------------------------------

def step(wt: Path, command: list[str], log: Path | None, label: str, env: dict = ENV,
         allow_fail: bool = False) -> tuple[int, str]:
    print(f"[{label}] {' '.join(command)}", flush=True)
    began = time.monotonic()
    result = subprocess.run(command, cwd=wt, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", env=env)
    print(f"[{label}] {time.monotonic() - began:.0f}s", flush=True)
    text = result.stdout + result.stderr
    if log:
        log.write_text(text, encoding="utf-8")
    if result.returncode != 0 and not allow_fail:
        raise Stop(f"{label} failed (exit {result.returncode}):\n{text[-3000:]}")
    return result.returncode, text


def run_tests(wt: Path, args, invocations: list[list[str]], logdir: Path, round_no: int) -> list[str]:
    """Run lint + pytest (+ node); return a summary line per step. Stop on any NEW failure."""
    python = sys.executable
    done = []
    if (wt / HARNESS).is_file():
        step(wt, [python, HARNESS, "lint"], logdir / f"lint-{round_no}.txt", "lint")
        done.append("lint ok")
    # HEAD is the candidate (merge commit included); the runner ships it to a test host (D-584:
    # no host means it waits, then fails, and nothing lands).
    head = out(wt, "rev-parse", "HEAD")
    reused, todo, keep = land_cache.split(wt, args, invocations, head, python, select)
    done += reused

    def batch(part: list[tuple[int, list[str]]]) -> list[str]:
        todo = [inv for _, inv in part]
        logs = [logdir / f"run-{round_no}-{n}.txt" for n, _ in part]
        began, seen = time.monotonic(), {}

        def on_done(inv, log):  # D-889: a confirmed NEW failure, or the turn's time cap, cancels the rest
            seen[str(log)] = v = land_checks.verdict(wt, inv, Path(log), logdir, f"{round_no}-{Path(log).stem[4:]}",
                                                     python, remote_pytest.run, head)
            return bool(v[0] and not v[1]) or (isinstance(round_no, int) and time.monotonic() - began > TURN_CAP_S)
        codes = remote_pytest.run(todo, logs, head, repo=wt, label=f"land-{round_no}", on_done=on_done)
        if out(wt, "rev-parse", "HEAD") != head:
            raise Stop(f"HEAD changed during remote checks; {head[:10]} was tested; retry the landing")
        if len(codes) != len(todo):
            raise Stop("incomplete remote results; not landing")
        print(f"[pytest] {(secs := round(time.monotonic() - began))}s", flush=True)
        # Every invocation is judged and each clean pass kept before a stop, so a retry reruns only what failed
        # or lost its host (2026-10-25: one fixed failure reran 27 passed invocations).
        stops, cancelled = [], []
        for (n, _), inv, log, code in zip(part, todo, logs, codes):
            if out(wt, "rev-parse", "HEAD") != head:
                raise Stop(f"HEAD changed before verdict; {head[:10]} was tested; retry the landing")
            if code == remote_pytest.CANCELLED:  # never ran to a verdict: not kept, not a failure of its own
                cancelled.append(inv)
                land_events.emit("tests", round=round_no, argv=inv, verdict="cancelled", seconds=secs)
                continue
            if why := land_cache.unusable(code, log):
                stops.append(f"pytest {' '.join(inv)} {why} (log {log}); not landing")
                land_events.emit("tests", round=round_no, argv=inv, verdict="unusable", seconds=secs)
                continue
            failed, flaky, why = seen.get(str(log)) or land_checks.verdict(
                wt, inv, log, logdir, f"{round_no}-{n}", python, remote_pytest.run, head)
            if out(wt, "rev-parse", "HEAD") != head:
                raise Stop(f"HEAD changed during verdict; {head[:10]} was tested; retry the landing")
            if failed and not flaky:
                stops.append(f"NEW failure in {' '.join(inv)} (log {log}); {why}; not landing")
                land_cache.failed(wt, inv, True)
                land_events.emit("tests", round=round_no, argv=inv, verdict="new", seconds=secs)
                continue
            land_cache.failed(wt, inv, False)
            land_events.emit("tests", round=round_no, argv=inv, verdict="flaky" if flaky else "pass", seconds=secs)
            if not failed:
                keep(inv, log)
            done.append(f"pytest {' '.join(inv)} ok ({log.name})" + (f", LOAD-FLAKY {flaky}" if flaky else ""))
        if cancelled and not stops:
            raise Overtime(f"{len(cancelled)} invocation(s) past the turn's {TURN_CAP_S // 60} min: tested outside the lock")
        return stops + ([f"{len(cancelled)} invocation(s) not run: cancelled after the failure above"] if cancelled else [])

    # What failed last time runs alone first: failing again stops before the rest spends the test PCs.
    numbered = list(enumerate(todo, 1))
    first = land_cache.failed_first(wt, todo)
    parts = ([[x for x in numbered if x[1] in first], [x for x in numbered if x[1] not in first]]
             if first and len(first) < len(todo) else [numbered])
    for i, part in enumerate(parts):
        if stops := batch(part):
            rest = sum(map(len, parts[i + 1:]))
            raise Stop("\n".join(stops) + (f"\n(failed last run too; {rest} other invocation(s) not run)"
                                           if rest else ""))
    if args.node:
        mjs = sorted(str(p.relative_to(wt).as_posix()) for inv in invocations for t in inv
                     if _test_dir(t) for p in (wt / _test_dir(t) / "web").glob("**/*.mjs"))
        mjs = list(dict.fromkeys(mjs))
        if mjs:
            # D-518: console modules import /console/assets/<name>; Node resolves those through
            # the suite's register hook, as test_site_map_api.py does.
            hooks = sorted({f"./{h.relative_to(wt).as_posix()}" for inv in invocations for t in inv
                            if _test_dir(t) for h in (wt / _test_dir(t) / "web").glob("register-*.mjs")})
            step(wt, ["node", *[a for h in hooks for a in ("--import", h)], "--test", *mjs],
                 logdir / f"node-{round_no}.txt", "node")
            done.append(f"node --test {len(mjs)} file(s) ok")
        else:
            done.append("node skipped: no web/*.mjs under the selected test dirs")
    if out(wt, "rev-parse", "HEAD") != head:
        raise Stop(f"HEAD changed during checks; {head[:10]} was tested; retry the landing")
    return done


def main_checkout(wt: Path) -> Path:
    path = None
    for line in out(wt, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = line[len("worktree "):]
        elif line == "branch refs/heads/main" and path:
            return Path(path)
    raise Stop("no worktree has main checked out; pass --main-checkout")


def on_main(main_co: Path) -> None:
    head = git(main_co, "symbolic-ref", "-q", "HEAD", check=False).stdout.strip()
    if head != "refs/heads/main":
        raise Stop(f"{main_co} has {head or 'a detached HEAD'} checked out, not refs/heads/main")


def land(args) -> int:
    wt = Path(out(Path.cwd(), "rev-parse", "--show-toplevel"))
    branch = out(wt, "rev-parse", "--abbrev-ref", "HEAD")
    if branch in ("main", "HEAD"):
        raise Stop(f"run from a topic worktree, not on {branch!r}")
    main_co = Path(args.main_checkout) if args.main_checkout else main_checkout(wt)
    on_main(main_co)
    if main_co.resolve() == wt.resolve():
        raise Stop("this is the shared main checkout; run from .worktrees/<topic>")
    dirty = git(wt, "status", "--porcelain").stdout.strip()
    if dirty:
        raise Stop(f"worktree is dirty; commit or remove first:\n{dirty}")
    stale = worktree_rules.stale_history(wt, "HEAD")
    if stale:
        raise Stop(f"{branch}: {stale}; landing it would bring that history back. Rebuild on a new branch from"
                   " main (python tools/worktrees.py new ..., D-172)")
    if not (args.no_prune or args.dry_run):
        try:  # one report line; --prune applies the lossless sweep. A failure must not stop a landing
            worktrees.sweep(wt, apply=args.prune)
        except Exception as exc:
            print(f"[land] warning: worktree prune failed, landing continues: {exc}")
    python = sys.executable
    qdir = ticket = None
    if args.no_queue and not args.dry_run:
        holders = land_queue.ahead(land_queue.queue_dir(wt), Path("~"))  # every live ticket: the first holds its turn
        if holders:  # a landing outside the queue mid-turn gave that turn another round (2026-10-25, 22:52)
            raise Stop(f"--no-queue refused: {land_queue.describe(holders[:1])} holds its turn. Wait, or stop it"
                       " first during an incident")
    if not (args.no_queue or args.dry_run):
        before = out(wt, "rev-parse", "main")
        safety_review(wt, before, "HEAD", python)  # seconds each: fail before a long wait, not after it
        size_check(wt, before, "HEAD", python)
        qdir, ticket = land_queue.enter(wt, branch, "preparing")  # main() releases the ticket on every exit
        if args.tests == "auto" and land_full.restore(wt, branch) is None:
            land_prepare.prepare(sys.modules[__name__], wt, branch, args, python, qdir, ticket)
        land_queue.wait(qdir, ticket, args.queue_timeout * 60, check=land_prepare.watch(sys.modules[__name__], wt))
    logdir = tmp_dir(branch)
    summary: list[str] = []
    tested_main: str | None = None
    # main under this branch's last green FULL tier, also from an earlier run (host lost, Ctrl-C, round cap)
    full_main = land_full.restore(wt, branch) if args.tests == "auto" else None
    if full_main:
        summary.append(f"an earlier run's FULL tier passed over main {full_main[:10]} with this branch's change")
    start = out(wt, "rev-parse", "main")

    for round_no in range(1, args.max_rounds + 1):
        land_queue.touch()  # a held ticket stays fresh through long rounds
        reusable, prepared = args.tests == "auto", None  # a green affected tier pre-push may reuse
        main_sha = out(wt, "rev-parse", "main")
        print(f"== round {round_no}: main {main_sha[:10]}, branch {branch}")
        land_events.emit("round", round=round_no, main=main_sha)
        if git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
            resolved = merge(wt, main_sha, branch, python, args.dry_run)
            summary.append(f"round {round_no}: merged main {main_sha[:10]}"
                           + (f", auto-resolved {resolved}" if resolved else ""))
        candidate = out(wt, "rev-parse", "HEAD")  # the commit the checks below vouch for
        safety_review(wt, main_sha, candidate, python)
        size_check(wt, main_sha, candidate, python)
        note = None
        if args.tests == "none":
            invocations: list[list[str]] = []
        elif args.tests == "auto":
            # A peer's edit to a path the branch moved or removed: the selector skips paths that no longer
            # exist, so the delta tier would test nothing of it; run this branch's FULL selection again.
            gone = [p for p in lines(wt, "diff", "--name-only", "--diff-filter=d", full_main, main_sha)
                    if not (wt / p).exists()] if full_main else []
            if gone:
                summary.append(f"round {round_no}: main delta edits {len(gone)} path(s) gone here"
                               f" ({gone[0]}): FULL again")
                invocations, note = select(wt, main_sha, python)
            elif full_main:
                # D-762 stage 0: the FULL tier passed over full_main; main's delta since then gets its own
                # selection (affected + guards, or FULL again) on this candidate, so peers cannot starve us.
                invocations, note = select(wt, full_main, python, head=main_sha, landed=True)
                reusable = reusable and (prepared := land_full.prepared(wt, branch, full_main)) is not None
                summary.append(f"round {round_no}: FULL tier passed over main {full_main[:10]}; main delta"
                               f" {full_main[:10]}..{main_sha[:10]} runs its {'FULL' if note else 'affected'} tier")
            else:
                invocations, note = select(wt, main_sha, python)
            if note and note not in summary:
                summary.append(note)
            if note and ticket is not None:  # a FULL tier never runs in the lock: prepare it, then wait again
                full_main = land_prepare.again(sys.modules[__name__], wt, branch, args, python, qdir, ticket, invocations, note)
                continue
        else:
            invocations = [shlex.split(args.tests)]
        if args.dry_run:
            print("[plan] lint, then pytest invocations:")
            print("\n".join("  " + " ".join(inv) for inv in invocations) or "  (none)")
            print(f"[plan] then git -C {main_co} merge --ff-only {candidate}  ({branch})")
            return 0

        delta = lines(wt, "diff", "--name-only", tested_main, main_sha) if tested_main else []
        if tested_main and all(map(record_only, delta)):
            # Only module-scoped suites may skip; root test/ guards read the records themselves.
            invocations = [kept for kept in ([p for p in inv if p.startswith("test/") or p == "test"]
                                             for inv in invocations) if kept]
            reusable = False  # module suites ran on an earlier candidate, not this one
            summary.append(f"round {round_no}: main delta ({len(delta)} file(s)) is records only"
                           " (logs/index/progress/ADR), module suites skipped, root test/ rerun")
        elif args.tests == "none":
            summary.append(f"round {round_no}: tests skipped (--tests none)")
        summary += (guarded := land_guards.first(wt, args, invocations, logdir, round_no, run_tests))  # NEW stops
        if out(wt, "rev-parse", "HEAD") != candidate:
            raise Stop(f"HEAD changed during guards; {candidate[:10]} was tested; retry the landing")
        if guarded and out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved during the guard round; merging again")
            continue
        began = time.monotonic()
        try:
            tested = run_tests(wt, args, invocations, logdir, round_no)
        except Overtime if ticket is not None else ():  # without a ticket (--no-queue) it stops like any Stop
            full_main = land_prepare.again(sys.modules[__name__], wt, branch, args, python, qdir, ticket, invocations, "")
            continue
        if out(wt, "rev-parse", "HEAD") != candidate:
            raise Stop(f"HEAD changed during checks; {candidate[:10]} was tested; retry the landing")
        # pre-push reruns its gate after a LOAD-FLAKY or a pass taken from another tree
        reusable = reusable and not any("LOAD-FLAKY" in line or land_cache.NARROW in line for line in tested)
        summary += [f"round {round_no}: {s}" for s in tested]
        if note:
            full_main = main_sha
            land_full.save(wt, branch, candidate, main_sha, "full", invocations)
            summary.append(f"round {round_no}: FULL tier took {time.monotonic() - began:.0f} s wall clock")
        if invocations or tested_main is None:
            tested_main = main_sha

        if out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved during the round; merging again")
            continue
        tip = out(wt, "rev-parse", f"refs/heads/{branch}")
        if tip != candidate or out(wt, "rev-parse", "HEAD") != candidate:
            raise Stop(f"{branch} moved to {tip[:10]} during the checks; {candidate[:10]} was tested, not that")
        on_main(main_co)
        ff = git(main_co, "merge", "--ff-only", candidate, check=False)
        if ff.returncode == 0:
            land_full.forget(wt, branch)
            landed = out(main_co, "rev-parse", "HEAD")
            if reusable and landed == candidate:
                record = land_record.write(wt, candidate, main_sha, invocations,
                                           [str(p) for p in sorted(logdir.glob(f"run-{round_no}-*.txt"))], prepared=prepared,
                                           tier="full" if note else "records" if delta and all(map(record_only, delta)) else "affected")
                summary.append(f"land record for pre-push: {record}")
            count = out(wt, "rev-list", "--count", f"{start}..{landed}")
            print("\n".join(["== landed (not pushed)", *summary,
                             f"rounds: {round_no}", f"commits merged onto main: {count}",
                             f"main is now {landed}", ahead_of_origin(wt, landed)]))
            print(f"[land] this worktree is now removable. After leaving it, from the main checkout {main_co}:\n"
                  f"  {worktrees.SWEEP}")
            return 0
        if out(wt, "rev-parse", "main") != main_sha:
            print("[land] main moved before the fast-forward; merging again")
            continue
        raise Stop(f"git merge --ff-only refused in {main_co} (left as is):\n{ff.stdout}{ff.stderr}")
    raise Stop(f"main kept moving: gave up after {args.max_rounds} rounds")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--main-checkout", help="path of the worktree that has main checked out")
    parser.add_argument("--tests", default="auto", help='auto | none | "<pytest args>"')
    parser.add_argument("--node", action="store_true", help="also node --test the selected test dirs' web/*.mjs")
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--prune", action="store_true", help="remove finished worktrees (lossless prune) first")
    parser.add_argument("--no-prune", action="store_true", help="do not report finished worktrees either")
    parser.add_argument("--no-cache", action="store_true", help="rerun every invocation (no land_cache.py reuse)")
    parser.add_argument("--queue-timeout", type=float, default=0, help="minutes to wait in the queue (0: no limit)")
    parser.add_argument("--no-queue", action="store_true", help="incident only: land without waiting in the queue")
    args = parser.parse_args(argv)
    try:
        wt = Path(out(Path.cwd(), "rev-parse", "--show-toplevel"))
        code = land_checks.landed_copy(Path(args.main_checkout) if args.main_checkout else main_checkout(wt),
                                       sys.argv[1:] if argv is None else argv)
        if code is not None:
            return code
        land_events.bind(wt, out(wt, "rev-parse", "--abbrev-ref", "HEAD"))
        if (code := land(args)) == 0 and not args.dry_run:
            land_events.emit("landed", sha=out(wt, "rev-parse", "HEAD"))
        return code
    except (Stop, land_queue.QueueError) as exc:
        print(f"[land] STOP: {exc}", file=sys.stderr)
        land_events.emit("stop", reason=str(exc).splitlines()[0][:300])
        return 1
    finally:
        land_queue.leave()  # also on Ctrl-C; a killed process's ticket is reclaimed by PID


if __name__ == "__main__":
    sys.exit(main())
