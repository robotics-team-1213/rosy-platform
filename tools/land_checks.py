"""Landing test execution, load-flaky reruns (D-790), scratch folder and origin distance.

On 2026-10-17 three timing/UDS tests (test_deliberation_free_probe, test_platform_g1_timing,
test_platform_g1_sim) each failed once inside a FULL round and passed when run alone; each stopped
the landing as NEW. ``load_flaky`` reruns such NEW ids once, each alone, in a separate remote
invocation. Every id passing alone is ``LOAD-FLAKY``: the landing continues and the ids go to a
candidates file for a person to review for ``test/flaky_quarantine.txt`` (never added there by
this tool). One id that fails again, more than ``MAX_RERUN`` NEW ids, or an id under a safety
root (D-762: a safety test is never retried) stops the landing as before.

On 2026-10-18 a landed change left shared/web contract tests red on main and every later branch was
refused for them as NEW. ``main_red`` reruns a stopping round's NEW ids once on ``main`` itself: ids
that fail there too are ``MAIN-RED``. The landing still stops, but the message says main is broken
and how to fix it. Standard library only.
"""

from __future__ import annotations

from concurrent.futures import CancelledError
import json
import os
import re
import subprocess
import sys
import threading
import tempfile
import time
from pathlib import Path

import land_events
import land_mainred

MAX_RERUN = 5  # more NEW ids than this is a real break, not load
MAX_MAIN_CHECK = 30  # NEW ids rerun on main in one invocation (bounds the command line)
NEW_LINE = re.compile(r"^NEW\s+(\S.*)$")
ENV_TOKEN = re.compile(r"^[A-Z_][A-Z0-9_]*=")  # remote_pytest's opt-in tokens (ROSY_RUN_BROWSER_TESTS=1)
CANDIDATES = "rosy-flaky-candidates.txt"  # in the git common dir: every worktree of this clone sees it
SAFETY = "tools/harness/safety_review.py"
# Prints the given node ids whose file is under a safety root (platform_parts.yaml), as safety_review.py reads it.
PROBE = ("import sys; sys.path.insert(0, 'tools/harness'); import safety_review as s, yaml\n"
         "m = yaml.safe_load(open(s.MANIFEST, encoding='utf-8')) or {}\n"
         "r, mods = m.get('roots') or [], set(m.get('safety_modules') or ())\n"
         "print('\\n'.join(i for i in sys.argv[1:] if s.is_safety(i.partition('::')[0], r, mods)))")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, encoding="utf-8",
                          errors="replace")


def tmp_dir(branch: str) -> Path:
    base = os.environ.get("ROSY_LAND_TMP") or Path(os.environ.get("ROSY_SCRATCH") or tempfile.gettempdir()) / "rosy-land"
    path = Path(base) / branch.replace("/", "-")
    path.mkdir(parents=True, exist_ok=True)
    return path


def ahead_of_origin(wt: Path, landed: str) -> str:
    """D-762 open item 4 (cap not decided, reported only): unpushed commits and the oldest one's age.

    Local refs only, no fetch."""
    stamps = _git(wt, "log", "--format=%ct", f"origin/main..{landed}")
    if stamps.returncode:
        return "local main vs origin/main: no origin/main ref here"
    times = [int(t) for t in stamps.stdout.split()]
    hours = (time.time() - min(times)) / 3600 if times else 0.0
    return f"local main is {len(times)} commits / {hours:.1f} hours ahead of origin/main"


def _safety(wt: Path, python: str, ids: list[str]) -> list[str]:
    """The ids under a safety root; all of them when the manifest cannot be read (never retried then)."""
    if not (wt / SAFETY).is_file():  # a tree without the D-430 manifest has no safety roots (as land.py)
        return []
    done = subprocess.run([python, "-c", PROBE, *ids], cwd=wt, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    return [line for line in done.stdout.splitlines() if line] if done.returncode == 0 else list(ids)


def _ids(wt: Path, verdict: str) -> list[str]:
    """The NEW node ids of a known_failures verdict, each path checked against the tree.

    A run over several paths can print ids from another pytest rootdir (2026-10-26, feat/update-view:
    ``middleware/robot_execution/local/test_feature_matrix.py`` for ``applications/fleet/test/...``), and the
    reruns below then found no file. A path the tree lacks takes the one tracked test file of that name. A
    directory printed in place of the file (2026-10-27: ``middleware/robot_execution/local::test_x`` for
    ``shared/web/test/...``) takes the one tracked test file that defines the test.
    """
    ids = []
    for line in verdict.splitlines():
        if not (m := NEW_LINE.match(line.strip())):
            continue
        nodeid = m.group(1).strip()
        path, sep, rest = nodeid.partition("::")
        if not (wt / path).is_file():
            if path.endswith(".py"):
                found = [p for p in _git(wt, "ls-files", "--", f"*{Path(path).name}").stdout.splitlines()
                         if Path(p).name == Path(path).name]
            else:
                name = re.escape(rest.split("::")[0].split("[")[0])
                found = _git(wt, "grep", "-lE", rf"^\s*(async\s+)?(def|class)\s+{name}\b", "--",
                             "*test_*.py").stdout.splitlines()
            if len(found) == 1:
                nodeid = found[0] + sep + rest
        ids.append(nodeid)
    return ids


def added_known(wt: Path, inv: list[str]) -> list[str]:
    """Ids this landing adds to test/known_failures.txt (vs local main) whose test file `inv` runs."""
    base = subprocess.run(["git", "-C", str(wt), "show", "main:test/known_failures.txt"], capture_output=True,
                          text=True, encoding="utf-8", errors="replace")
    if base.returncode != 0:
        return []

    sys.path.append(str(Path(__file__).resolve().parents[1] / "test"))
    from known_failures import load_known  # one parser, so the two cannot drift

    def ids(text: str) -> set[str]:
        return set(load_known(text))
    head = (wt / "test/known_failures.txt").read_text(encoding="utf-8") if (wt / "test/known_failures.txt").is_file() else ""
    return sorted(i for i in ids(head) - ids(base.stdout)
                  if any(i.split("::")[0] == p or i.startswith(p.rstrip("/") + "/") for p in inv))


def verdict(wt: Path, inv: list[str], log: Path, logdir: Path, tag: str, python: str, run,
            tested_sha: str) -> tuple[int, list[str], str]:
    """test/known_failures.py on ``log``, then the rerun alone for its NEW ids: (exit, load-flaky ids, why).

    A NEW failure is confirmed (exit non-zero, no load-flaky ids) only after the rerun, so land.py's early stop
    never cancels a round for a failure that passes alone."""
    must = [arg for nodeid in added_known(wt, inv) for arg in ("--must-fail", nodeid)]
    check = subprocess.run([python, "test/known_failures.py", str(log), *must], cwd=wt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
    print(check.stdout, end="")
    if check.returncode == 0:
        return 0, [], ""
    passing = [line.split()[1] for line in check.stdout.splitlines() if line.startswith("MUST-FAIL ")]
    if passing:  # not a failure to rerun: the listed test passes, so the new line hides nothing
        return check.returncode, [], f"known_failures.txt adds id(s) that pass here: {', '.join(passing)}"
    result = (check.returncode, *load_flaky(wt, inv, log, check.stdout, logdir, tag, python, run, tested_sha=tested_sha))
    failure(wt, inv, log, tested_sha, result[1])
    return result


def failure(wt: Path, inv: list[str], log: Path, sha: str, flaky: list[str]) -> None:
    """A ``failure`` event: the failed ids and the host's user name (never its address), so land_stats can split
    the new-failure share into one id failing for several branches, one host, or one branch (D-889 addendum 3).
    The host comes from the laptop's memory history row of this argv and commit, not from the remote job."""
    sys.path.append(str(Path(__file__).resolve().parents[1] / "test"))
    sys.path.append(str(Path(__file__).resolve().parent / "remote"))
    import known_failures
    import memory_history
    try:
        failed = known_failures.failed_ids(log.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        failed = []
    rows = [r for r in memory_history._rows(memory_history.path(wt), inv) if r.get("sha") == sha]
    host = str(rows[-1].get("host", "")).split("@")[0] or None if rows else None
    land_events.emit("failure", argv=inv, failed=failed[:20], host=host, flaky=flaky[:20], confirmed=not flaky)


def load_flaky(wt: Path, inv: list[str], log: Path, verdict: str, logdir: Path, tag: str, python: str,
               run, *, tested_sha: str) -> tuple[list[str], str]:
    """Rerun the NEW ids of one invocation alone; ``(load-flaky ids, "")`` or ``([], why it stops)``.

    ``verdict`` is test/known_failures.py's output for ``log``; ``run`` is ``remote_pytest.run``.
    A stop also says whether the ids fail on main too (``main_red``).
    """
    ids, why = _rerun_alone(wt, inv, log, verdict, logdir, tag, python, run, tested_sha=tested_sha)
    if ids or why.startswith("HEAD changed"):
        return ids, why
    where = main_red(wt, inv, verdict, logdir, tag, python, run)
    return [], f"{why}; {where}" if where else why


def _rerun_alone(wt: Path, inv: list[str], log: Path, verdict: str, logdir: Path, tag: str, python: str,
                 run, *, tested_sha: str) -> tuple[list[str], str]:
    ids = _ids(wt, verdict)
    if not ids or len(ids) > MAX_RERUN:
        return [], f"{len(ids)} NEW id(s); a rerun alone is tried only for 1 to {MAX_RERUN}"
    safety = _safety(wt, python, ids)
    if safety:
        return [], f"under a safety root, never retried (D-762): {', '.join(safety)}"
    env = [token for token in inv if ENV_TOKEN.match(token)]
    logs = [logdir / f"alone-{tag}-{i}.txt" for i in range(1, len(ids) + 1)]
    print(f"[land] {len(ids)} NEW failure(s) in {log.name}: rerunning each alone once (D-790)", flush=True)
    codes = run([[*env, nodeid] for nodeid in ids], logs, tested_sha, repo=wt, label=f"land-alone-{tag}")
    if len(codes) != len(ids):
        return [], "incomplete isolated rerun results"
    if _git(wt, "rev-parse", "HEAD").stdout.strip() != tested_sha:
        return [], "HEAD changed during isolated checks; retry the landing"
    lost = [f"{nodeid} (exit {code}, {alone})" for nodeid, code, alone in zip(ids, codes, logs) if code not in (0, 1)]
    if lost:  # 4: no such file, 5: nothing collected, 255: host lost: no verdict, not a second failure
        return [], "the rerun alone gave no verdict: " + "; ".join(lost)
    again = [f"{nodeid} (exit {code}, {alone})" for nodeid, code, alone in zip(ids, codes, logs) if code != 0]
    if again:
        return [], "failed again when run alone: " + "; ".join(again)
    sha = tested_sha
    common = Path(_git(wt, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    day = time.strftime("%Y-%m-%d")
    with open(common / CANDIDATES, "a", encoding="utf-8") as out:
        for nodeid, alone in zip(ids, logs):
            out.write(f"{nodeid}  # LOAD-FLAKY {day}: failed in {log} on {sha[:10]}, passed alone in {alone};"
                      " review for test/flaky_quarantine.txt (D-762 evidence rules)\n")
    for nodeid in ids:
        print(f"LOAD-FLAKY {nodeid}")
    print(f"[land] candidates for review: {common / CANDIDATES}")
    return ids, ""


def main_red(wt: Path, inv: list[str], verdict: str, logdir: Path, tag: str, python: str, run) -> str:
    """Rerun up to ``MAX_MAIN_CHECK`` NEW ids of ``verdict`` once on ``main``; one line for the stop message.

    Never lets a landing through: it only says whether the failure is main's or the branch's.
    """
    ids = _ids(wt, verdict)
    if not ids:
        return ""
    main = land_mainred.merged_main(wt)  # the main this candidate merged, not main's tip (D-889 addendum 2, 1)
    env = [token for token in inv if ENV_TOKEN.match(token)]
    log = logdir / f"main-{tag}.txt"
    if land_mainred.known(wt, main, ids):
        return f"MAIN-RED: every NEW id already failed on main {main[:10]} (rosy-main-red.jsonl); not rerun"
    print(f"[land] rerunning {min(len(ids), MAX_MAIN_CHECK)} NEW id(s) on main {main[:10]} (MAIN-RED check)",
          flush=True)
    try:
        code = run([[*env, *ids[:MAX_MAIN_CHECK]]], [log], main, repo=wt, label=f"land-main-{tag}")[0]
    except SystemExit as exc:  # no test host (D-584): unknown, not main's
        return f"main check not run ({exc})"
    if code == 0:
        return f"the NEW id(s) pass on main {main[:10]}: this branch caused them"
    if code != 1 or not log.is_file():
        return f"main check gave no verdict (exit {code}, log {log}); new tests may not exist on main"
    again = subprocess.run([python, "test/known_failures.py", str(log)], cwd=wt, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
    red = [m.group(1).strip() for line in again.stdout.splitlines() if (m := NEW_LINE.match(line.strip()))]
    for nodeid in red:
        print(f"MAIN-RED {nodeid}")
    branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    land_mainred.red(wt, main, red, log.read_text(encoding="utf-8", errors="replace"), env, branch)
    if not red:
        return f"the NEW id(s) pass on main {main[:10]}: this branch caused them"
    return (f"MAIN-RED: {len(red)} of {len(ids)} NEW id(s) also fail on main {main[:10]} (log {log}). Main is"
            " broken, not this branch: fix main first in a small fix/ branch that changes only that, land it,"
            " then rerun land.py here (check that no peer is already fixing it)")


def carry(wt: Path, log: Path, head: str, python: str, inv: list[str]) -> tuple[list[str], str]:
    """land_mainred.carry for one invocation's log: its NEW ids, the safety probe and the selector."""
    text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
    check = subprocess.run([python, "test/known_failures.py", str(log)], cwd=wt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")

    def select(base: str, tip: str) -> dict:
        done = subprocess.run([python, "tools/harness/rosy_harness.py", "affected", "--base", base, "--head", tip,
                               "--json"], cwd=wt, capture_output=True, text=True, encoding="utf-8", errors="replace")
        return json.loads(done.stdout) if done.returncode == 0 else {"mode": "full"}  # unknown: never carry

    branch = _git(wt, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    return land_mainred.carry(wt, _ids(wt, check.stdout), text, head, branch,
                              safety=lambda ids: _safety(wt, python, ids), select=select, inv=inv)


OWN_COPY = "ROSY_LAND_OWN_COPY"  # set by the re-run below: the landed copy runs, never re-runs itself


def landed_copy(main_co: Path, argv: list[str]) -> int | None:
    """Run main's tools/land.py when this checkout's tools/land*.py differ from main's; its exit code, or None.

    land.py ran from the landing branch's own copy, so a branch made before a land.py fix landed with the old
    rules: a log merge main already accepted stopped "a side changed existing lines" (2026-10-26). The working
    directory stays the branch's worktree; only the landing code is main's.
    """
    here, there = Path(__file__).resolve().parent, (main_co / "tools").resolve()
    if os.environ.get(OWN_COPY) or there == here or not (there / "land.py").is_file():
        return None
    names = sorted({p.name for d in (here, there) for p in d.glob("land*.py")})
    if all((here / n).is_file() and (there / n).is_file() and (here / n).read_bytes() == (there / n).read_bytes()
           for n in names):
        return None
    print(f"[land] this branch's tools/land*.py differ from main's: landing with {there / 'land.py'}", flush=True)
    return subprocess.run([sys.executable, str(there / "land.py"), *argv], env={**os.environ, OWN_COPY: "1"}).returncode


def run_tests(land, wt: Path, args, invocations: list[list[str]], logdir: Path, round_no: int) -> list[str]:
    """Run lint + pytest (+ node); return a summary line per step. Stop on any NEW failure."""
    deadline = land.time.monotonic() + land.TURN_CAP_S if isinstance(round_no, int) else None
    python = land.sys.executable
    done = []
    if (wt / land.HARNESS).is_file():
        land.step(wt, [python, land.HARNESS, "lint"], logdir / f"lint-{round_no}.txt", "lint")
        done.append("lint ok")
    # HEAD is the candidate (merge commit included); the runner ships it to a test host (D-584:
    # no host means it waits, then fails, and nothing lands).
    head = land.out(wt, "rev-parse", "HEAD")
    reused, todo, keep = land.land_cache.split(wt, args, invocations, head, python, land.select)
    done += reused

    def batch(part: list[tuple[int, list[str]]]) -> list[str]:
        todo = [inv for _, inv in part]
        logs = [logdir / f"run-{round_no}-{n}.txt" for n, _ in part]
        began, seen = land.time.monotonic(), {}

        def diagnostic_run(*positional, **kwargs):
            if stop.is_set():
                raise CancelledError("turn deadline expired before diagnostic checks")
            codes = land.remote_pytest.run(*positional, **kwargs, stop=stop)
            if stop.is_set():
                raise CancelledError("turn deadline expired during diagnostic checks")
            return codes

        def judge(inv, log, tag):  # a NEW that main-red carry-over takes (land_mainred) neither stops nor is kept
            run = diagnostic_run if stop is not None else land.remote_pytest.run
            v = land.land_checks.verdict(wt, inv, land.Path(log), logdir, tag, python, run, head)
            taken = land.land_checks.carry(wt, land.Path(log), head, python, inv) if v[0] and not v[1] else ([], "")
            return (v[0], taken[0], f"main-red carried: {taken[1]}") if taken[0] else v

        def on_done(inv, log):  # D-889: a confirmed NEW failure, or the turn's time cap, cancels the rest
            seen[str(log)] = v = judge(inv, log, f"{round_no}-{land.Path(log).stem[4:]}")
            return bool(v[0] and not v[1]) or (deadline is not None and land.time.monotonic() >= deadline)
        stop = threading.Event() if deadline is not None else None
        timer = threading.Timer(max(0, deadline - land.time.monotonic()), stop.set) if stop is not None else None
        if timer is not None:
            timer.daemon = True
            timer.start()
        try:
            codes = land.remote_pytest.run(todo, logs, head, repo=wt, label=f"land-{round_no}", on_done=on_done,
                                          **({"stop": stop} if stop is not None else {}))
        finally:
            if timer is not None:
                timer.cancel()
        if land.out(wt, "rev-parse", "HEAD") != head:
            raise land.Stop(f"HEAD changed during remote checks; {head[:10]} was tested; retry the landing")
        if len(codes) != len(todo):
            raise land.Stop("incomplete remote results; not landing")
        print(f"[pytest] {(secs := round(land.time.monotonic() - began))}s", flush=True)
        # Every invocation is judged and each clean pass kept before a stop, so a retry reruns only what failed
        # or lost its host (2026-10-25: one fixed failure reran 27 passed invocations).
        stops, cancelled = [], []
        for (n, _), inv, log, code in zip(part, todo, logs, codes):
            if land.out(wt, "rev-parse", "HEAD") != head:
                raise land.Stop(f"HEAD changed before verdict; {head[:10]} was tested; retry the landing")
            if code == land.remote_pytest.CANCELLED:  # never ran to a verdict: not kept, not a failure of its own
                cancelled.append(inv)
                land.land_events.emit("tests", round=round_no, argv=inv, verdict="cancelled", seconds=secs)
                continue
            if why := land.land_cache.unusable(code, log) or land.land_browser.vacuous(inv, log):
                stops.append(f"pytest {' '.join(inv)} {why} (log {log}); not landing")
                land.land_events.emit("tests", round=round_no, argv=inv, verdict="unusable", seconds=secs)
                continue
            failed, flaky, why = seen.get(str(log)) or judge(inv, log, f"{round_no}-{n}")
            if land.out(wt, "rev-parse", "HEAD") != head:
                raise land.Stop(f"HEAD changed during verdict; {head[:10]} was tested; retry the landing")
            if failed and not flaky:
                stops.append(f"NEW failure in {' '.join(inv)} (log {log}); {why}; not landing")
                land.land_cache.failed(wt, inv, True)
                land.land_events.emit("tests", round=round_no, argv=inv, verdict="new", seconds=secs)
                continue
            land.land_cache.failed(wt, inv, False)
            carried = why.startswith("main-red")
            land.land_events.emit("tests", round=round_no, argv=inv, seconds=secs,
                                  verdict="carried" if carried else "flaky" if flaky else "pass")
            if not failed:
                keep(inv, log)
                land.land_mainred.passed(inv)  # this round passed it: an earlier round's carry of it is void
                land.land_mainred.close(wt, log.read_text(encoding="utf-8", errors="replace"), head)
            done.append(f"pytest {' '.join(inv)} ok ({log.name})"
                        + (f", {why}" if carried else f", LOAD-FLAKY {flaky}" if flaky else ""))
        if cancelled and not stops:
            raise land.Overtime(
                f"{len(cancelled)} invocation(s) past the turn's {land.TURN_CAP_S // 60} min: tested outside the lock")
        return stops + (
            [f"{len(cancelled)} invocation(s) not run: cancelled after the failure above"] if cancelled else [])

    # What failed last time runs alone first: failing again stops before the rest spends the test PCs.
    numbered = list(enumerate(todo, 1))
    first = land.land_cache.failed_first(wt, todo)
    parts = ([[x for x in numbered if x[1] in first], [x for x in numbered if x[1] not in first]]
             if first and len(first) < len(todo) else [numbered])
    for i, part in enumerate(parts):
        try:
            stops = batch(part)
        except CancelledError as error:
            if deadline is not None and land.time.monotonic() >= deadline:
                raise land.Overtime(
                    f"turn's {land.TURN_CAP_S // 60} min expired during diagnostic checks: tested outside the lock") from error
            raise land.Stop("remote diagnostic cancelled without a verdict") from error
        if stops:
            rest = sum(map(len, parts[i + 1:]))
            raise land.Stop("\n".join(stops) + (f"\n(failed last run too; {rest} other invocation(s) not run)"
                                                if rest else ""))
    if args.node:
        mjs = sorted(str(p.relative_to(wt).as_posix()) for inv in invocations for t in inv
                     if land._test_dir(t) for p in (wt / land._test_dir(t) / "web").glob("**/*.mjs"))
        mjs = list(dict.fromkeys(mjs))
        if mjs:
            # D-518: console modules import /console/assets/<name>; Node resolves those through
            # the suite's register hook, as test_site_map_api.py does.
            hooks = sorted({f"./{h.relative_to(wt).as_posix()}" for inv in invocations for t in inv
                            if land._test_dir(t) for h in (wt / land._test_dir(t) / "web").glob("register-*.mjs")})
            land.step(wt, ["node", *[a for h in hooks for a in ("--import", h)], "--test", *mjs],
                      logdir / f"node-{round_no}.txt", "node")
            done.append(f"node --test {len(mjs)} file(s) ok")
        else:
            done.append("node skipped: no web/*.mjs under the selected test dirs")
    if land.out(wt, "rev-parse", "HEAD") != head:
        raise land.Stop(f"HEAD changed during checks; {head[:10]} was tested; retry the landing")
    return done
