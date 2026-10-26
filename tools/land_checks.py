"""tools/land.py helpers: the load-flaky rerun (D-790), scratch folder and origin distance.

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

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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
    reruns below then found no file. A path the tree lacks takes the one tracked test file of that name.
    """
    ids = []
    for line in verdict.splitlines():
        if not (m := NEW_LINE.match(line.strip())):
            continue
        nodeid = m.group(1).strip()
        path, sep, rest = nodeid.partition("::")
        if not (wt / path).is_file():
            found = [p for p in _git(wt, "ls-files", "--", f"*{Path(path).name}").stdout.splitlines()
                     if Path(p).name == Path(path).name]
            if len(found) == 1:
                nodeid = found[0] + sep + rest
        ids.append(nodeid)
    return ids


def verdict(wt: Path, inv: list[str], log: Path, logdir: Path, tag: str, python: str, run,
            tested_sha: str) -> tuple[int, list[str], str]:
    """test/known_failures.py on ``log``, then the rerun alone for its NEW ids: (exit, load-flaky ids, why).

    A NEW failure is confirmed (exit non-zero, no load-flaky ids) only after the rerun, so land.py's early stop
    never cancels a round for a failure that passes alone."""
    check = subprocess.run([python, "test/known_failures.py", str(log)], cwd=wt, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env={**os.environ, "PYTHONUTF8": "1"})
    print(check.stdout, end="")
    if check.returncode == 0:
        return 0, [], ""
    return (check.returncode, *load_flaky(wt, inv, log, check.stdout, logdir, tag, python, run, tested_sha=tested_sha))


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
    main = _git(wt, "rev-parse", "main").stdout.strip()
    env = [token for token in inv if ENV_TOKEN.match(token)]
    log = logdir / f"main-{tag}.txt"
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
    if not red:
        return f"the NEW id(s) pass on main {main[:10]}: this branch caused them"
    return (f"MAIN-RED: {len(red)} of {len(ids)} NEW id(s) also fail on main {main[:10]} (log {log}). Main is"
            " broken, not this branch: fix main first in a small fix/ branch that changes only that, land it,"
            " then rerun land.py here (check that no peer is already fixing it)")


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
