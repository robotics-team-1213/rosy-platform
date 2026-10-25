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
import land_full  # noqa: E402  (a green FULL tier outlives the run that passed it)
import land_checks  # noqa: E402  (D-790: load-flaky rerun; scratch folder, origin distance)
import land_cache  # noqa: E402  (passed invocations reused across land.py runs)
from land_checks import ahead_of_origin, tmp_dir  # noqa: E402
from land_merge import (ADR_GAPS, ADR_LOG, conflict_stages, landed_gaps, plan,  # noqa: E402,F401  (auto-resolve)
                        generate_records, resolver)
import worktree_rules  # noqa: E402  (D-790: stale-history refusal)

HARNESS = "tools/harness/rosy_harness.py"
SIZE_RANGE = "tools/harness/size_range.py"  # D-766: git-only, seconds; the FULL tier would only find it after the remote round trip
SAFETY = "tools/harness/safety_review.py"  # D-430 5: the rule CI's scope job enforces
# Every child gets UTF-8 stdio (Korean paths and log text on a cp949 console).
ENV = {**os.environ, "PYTHONUTF8": "1"}


class Stop(Exception):
    """A step failed; the message says why. Exit 1."""


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


def select(wt: Path, base: str, python: str, head: str | None = None) -> tuple[list[list[str]], str | None]:
    """pytest invocations for base...HEAD (or base...head), and a FULL note owed to the summary.

    The D-436 selector (`rosy_harness.py affected`) when the harness is present —
    it adds the guard set and reverse dependents — otherwise the nearest test/ dir.
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
            if sel["mode"] == "full":
                # D-762 stage 0: a FULL-class landing runs the whole tier on the lab PCs, never
                # guards alone; not via GitHub, which would publish unpushed main commits.
                note = "selector escalated to FULL (" + "; ".join(sel["escalations"][:3]) + "): full tier on the lab PCs"
                print(f"[tests] {note}")
                return sel["full_invocations"] + browser_tier(wt, base, head), note
            return sel["invocations"] + browser_tier(wt, base, head), None
        except (ValueError, KeyError, TypeError) as exc:
            raise Stop(f"affected selector printed unusable JSON ({exc!r}); not guessing tests") from exc
    changed = lines(wt, "diff", "--name-only", f"{base}...HEAD")
    return pack(wt, fallback_targets(wt, changed)) + browser_tier(wt, base), None


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
    logs = [logdir / f"run-{round_no}-{i}.txt" for i in range(1, len(todo) + 1)]
    began = time.monotonic()
    codes = remote_pytest.run(todo, logs, head, repo=wt, label=f"land-{round_no}")
    if out(wt, "rev-parse", "HEAD") != head:
        raise Stop(f"HEAD changed during remote checks; {head[:10]} was tested; retry the landing")
    if len(codes) != len(todo):
        raise Stop("incomplete remote results; not landing")
    print(f"[pytest] {time.monotonic() - began:.0f}s", flush=True)
    whole = len(codes) == len(todo) and not any(map(land_cache.unusable, codes, logs))  # else cache nothing
    for inv, log, code in zip(todo, logs, codes):
        if out(wt, "rev-parse", "HEAD") != head:
            raise Stop(f"HEAD changed before verdict; {head[:10]} was tested; retry the landing")
        if why := land_cache.unusable(code, log):
            raise Stop(f"pytest {' '.join(inv)} {why} (log {log}); not landing")
        check = subprocess.run([python, "test/known_failures.py", str(log)], cwd=wt,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", env=ENV)
        print(check.stdout, end="")
        flaky, why = ([], "") if check.returncode == 0 else land_checks.load_flaky(
            wt, inv, log, check.stdout, logdir, f"{round_no}-{len(done)}", python, remote_pytest.run,
            tested_sha=head)
        if out(wt, "rev-parse", "HEAD") != head:
            raise Stop(f"HEAD changed during verdict; {head[:10]} was tested; retry the landing")
        if check.returncode != 0 and not flaky:
            raise Stop(f"NEW failure in {' '.join(inv)} (log {log}); {why}; not landing")
        if check.returncode == 0 and whole:
            keep(inv, log)
        done.append(f"pytest {' '.join(inv)} ok ({log.name})" + (f", LOAD-FLAKY {flaky}" if flaky else ""))
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


def pretest(wt: Path, branch: str, args, python: str) -> None:
    """A FULL tier while waiting in the queue (v2 lap 2026-10-19: 5 landers ahead, each with its FULL tier
    inside the queue, held a landing 100+ min). Green, it is recorded as the turn's ``land_full`` (D-762
    stage 0): the turn then runs main's delta only. An affected tier is short and runs at the turn."""
    main_sha = out(wt, "rev-parse", "main")
    if git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
        merge(wt, main_sha, branch, python, False)
    candidate = out(wt, "rev-parse", "HEAD")
    invocations, note = select(wt, main_sha, python)
    if not note:
        return
    print(f"[land] FULL tier while waiting in the queue (main {main_sha[:10]})", flush=True)
    logdir = tmp_dir(branch)
    land_guards.first(wt, args, invocations, logdir, "pre", run_tests)
    if out(wt, "rev-parse", "HEAD") != candidate:
        raise Stop(f"HEAD changed during pretest guards; retry the landing from {candidate[:10]}")
    run_tests(wt, args, invocations, logdir, "pre")   # a NEW failure stops here, before the wait
    if out(wt, "rev-parse", "HEAD") != candidate:
        raise Stop(f"HEAD changed during pretest; {candidate[:10]} was tested; retry the landing")
    land_full.save(wt, branch, candidate, main_sha)


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
    if not (args.no_queue or args.dry_run):
        before = out(wt, "rev-parse", "main")
        safety_review(wt, before, "HEAD", python)  # seconds each: fail before a long wait, not after it
        size_check(wt, before, "HEAD", python)
        qdir, ticket = land_queue.enter(wt, branch)  # main() releases the ticket on every exit
        if args.tests == "auto" and land_queue.ahead(qdir, ticket) and land_full.restore(wt, branch) is None:
            pretest(wt, branch, args, python)   # keeps its place: the FULL tier runs while the others land
        land_queue.wait(qdir, ticket, args.queue_timeout * 60)
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
        reusable = args.tests == "auto"  # a green affected tier pre-push may reuse
        main_sha = out(wt, "rev-parse", "main")
        print(f"== round {round_no}: main {main_sha[:10]}, branch {branch}")
        if git(wt, "merge-base", "--is-ancestor", main_sha, "HEAD", check=False).returncode != 0:
            resolved = merge(wt, main_sha, branch, python, args.dry_run)
            summary.append(f"round {round_no}: merged main {main_sha[:10]}"
                           + (f", auto-resolved {resolved}" if resolved else ""))
            gaps, dropped = landed_gaps(wt) if not args.dry_run else (b"", [])
            if dropped:  # merge=union brought back lines main removed when those ADRs landed
                (wt / ADR_GAPS).write_bytes(gaps)
                git(wt, "add", "--", ADR_GAPS)
                git(wt, "commit", "-m", f"chore(adr): drop adr_gaps lines of landed {', '.join(dropped)}")
                print(f"[merge] {ADR_GAPS}: dropped {dropped}, their ADR now exists")
                summary.append(f"round {round_no}: dropped landed ADR gap(s) {dropped} from {ADR_GAPS}")
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
                invocations, note = select(wt, full_main, python, head=main_sha)
                reusable = False  # the FULL tier ran on an earlier candidate
                summary.append(f"round {round_no}: FULL tier passed over main {full_main[:10]}; main delta"
                               f" {full_main[:10]}..{main_sha[:10]} runs its {'FULL' if note else 'affected'} tier")
            else:
                invocations, note = select(wt, main_sha, python)
            if note and note not in summary:
                summary.append(note)
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
        tested = run_tests(wt, args, invocations, logdir, round_no)
        if out(wt, "rev-parse", "HEAD") != candidate:
            raise Stop(f"HEAD changed during checks; {candidate[:10]} was tested; retry the landing")
        # pre-push reruns its gate after a LOAD-FLAKY or a pass taken from another tree
        reusable = reusable and not any("LOAD-FLAKY" in line or land_cache.NARROW in line for line in tested)
        summary += [f"round {round_no}: {s}" for s in tested]
        if note:
            full_main = main_sha
            land_full.save(wt, branch, candidate, main_sha)
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
                                           [str(p) for p in sorted(logdir.glob(f"run-{round_no}-*.txt"))])
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
    parser.add_argument("--queue-timeout", type=float, default=180, help="minutes to wait in the landing queue")
    parser.add_argument("--no-queue", action="store_true", help="incident only: land without waiting in the queue")
    args = parser.parse_args(argv)
    try:
        return land(args)
    except (Stop, land_queue.QueueError) as exc:
        print(f"[land] STOP: {exc}", file=sys.stderr)
        return 1
    finally:
        land_queue.leave()  # also on Ctrl-C; a killed process's ticket is reclaimed by PID


if __name__ == "__main__":
    sys.exit(main())
