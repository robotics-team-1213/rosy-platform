"""What a shared pytest process can hide, checked by tools/land.py before its turn (land_prepare, land_guards).

2026-10-26: learning/training/omx/test/test_native_cycle.py landed 26 ERRORs (ModuleNotFoundError) on main. Its
folder passed in one pytest process because sibling modules had put the missing module on sys.path or into
sys.modules; alone it failed. The module was loaded with spec_from_file_location inside a fixture, so a
collect-only pass of the file alone was green: only running the file alone caught it
(docs/solutions/workflow-issues/shared-pytest-process-masks-path-dependent-import-2026-10-26.md).

Both jobs run ``tools/collect_alone.py`` on a test host, each file in its own process, ``GATE_CORES`` at a time,
within ``BUDGET_S``:
- ``gate`` (prepare only): ``pytest --collect-only`` per selected test file.
- ``alone_files`` (prepare only): every test on the D-436 selector's ``references X`` edge of this branch's changed
  files, those of safety-tagged files first, then spec_from_file_location loaders. No count cap: the budget cuts.
  Files the budget did not reach are never dropped silently: ``record`` appends them to
  ``<git-common-dir>/rosy-land-isolation.jsonl`` (``incomplete``) and the turn's summary prints
  ``isolation incomplete: <files>``. A safety one unreached stops the landing. A job without its report line (it
  died) is a failed gate: once more without the cache, then the landing stops; the files are recorded either way.
- the turn: ``--no-queue`` (no prepare) records ``skipped`` with the files and says ``isolation gate skipped``;
  otherwise, when main moved since prepare and its delta touches a file an alone-run test references, those tests
  join the turn's own round, under its time cap and Overtime path.
Records still open after a night (landed, files never run alone since) are a FAIL in ``tools/doctor.py`` and a
line in the turn's summary; a later alone run on a descendant closes them (``python tools/land_isolation.py
close <files> --reason ...`` until a nightly consumer exists). This record and land_events have no backup: a
known single point of loss until a copy mechanism lands. Off when the tree has no ``tools/collect_alone.py``. Standard
library at import; the selector loads lazily.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GATE = "tools/collect_alone.py"
# The jobs are serial under xdist_plan (tools/ is in serial_suites.txt); the pool takes this budget instead.
# Collecting a FULL selection's 2,123 files took 347 s with 2 workers, 150 s with 6 (2026-10-26).
GATE_CORES = 6
BUDGET_S = 600
RECORD = "rosy-land-isolation.jsonl"
OPEN_AFTER_S = 24 * 3600  # doctor and the turn flag records still open after a night
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")  # = affected_tests.TEST_FILE
ENV_WORD = re.compile(r"^ROSY_[A-Z0-9_]*=")
REPORT = re.compile(r"^\[isolation\] (complete|incomplete): ?(.*)$", re.MULTILINE)
# An option word keeps land_cache from narrow reuse (its delta mapping cannot see the files in job words).
NO_NARROW = "-pno:cacheprovider"
# remote_pytest.PYTEST_TAIL's options for one file; xdist off: each file already has its own process.
TAIL = ["-q", "-rfE", "-p", "no:cacheprovider", "-p", "no:xdist", "--rootdir=.", "-pno:launch_testing",
        "-pno:launch_ros"]
COLLECT = ["--collect-only", *TAIL]


def selected_paths(invocations: list[list[str]]) -> list[str]:
    """The paths the invocations name (no options, job words or node ids)."""
    words = (w for inv in invocations for w in inv)
    return list(dict.fromkeys(w.replace("\\", "/").rstrip("/") for w in words
                              if not w.startswith("-") and not ENV_WORD.match(w) and "::" not in w))


def tracked_tests(root: Path, paths: list[str]) -> list[str]:
    """Tracked test files under ``paths`` (a test file names itself), as the selector counts them."""
    if not paths:
        return []  # ls-files with no pathspec lists the whole tree
    listed = subprocess.run(["git", "ls-files", "-z", "--", *paths], cwd=root, capture_output=True, check=True,
                            text=True, encoding="utf-8").stdout
    return sorted({p for p in listed.split("\0") if TEST_FILE.search(p)})


def each_alone(root: Path, files: list[str], options: list[str], workers: int = 2, budget_s: float = BUDGET_S,
               serial: tuple[str, ...] = ()) -> dict[str, tuple[int | None, str]]:
    """``{file: (exit code, output tail)}`` of ``pytest <options> <file>``, one process per file, in list order.

    Capped by time, not file count: a file not started within ``budget_s`` is left out, one still running at the
    end is stopped and gets ``None``. Files under a ``serial`` prefix never run at the same time as each other."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT"))}
    deadline, one_at_a_time = time.monotonic() + budget_s, threading.Lock()

    def one(path: str):
        held = any(path == s or path.startswith(s + "/") for s in serial) and one_at_a_time.acquire()
        try:
            if (left := deadline - time.monotonic()) <= 0:
                return path, None
            with tempfile.TemporaryDirectory() as tmp:
                r = subprocess.run([sys.executable, "-m", "pytest", *options, "--basetemp", f"{tmp}/p", path],
                                   cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                   env=env, timeout=left)
            return path, (r.returncode, (r.stdout + r.stderr)[-3000:])
        except subprocess.TimeoutExpired:
            return path, (None, f"stopped at the {budget_s:.0f} s budget")
        finally:
            if held:
                one_at_a_time.release()

    with ThreadPoolExecutor(max(1, workers)) as pool:
        return {path: res for path, res in pool.map(one, files) if res is not None}


def new_failures(report: str) -> list[str]:
    """Failures in one file's run that test/known_failures.txt does not list."""
    test_dir = str(Path(__file__).resolve().parents[1] / "test")
    if test_dir not in sys.path:
        sys.path.insert(0, test_dir)
    import known_failures
    return known_failures.compare(report, known_failures.load_known(known_failures.LIST.read_text(encoding="utf-8")))[0]


def report_line(files: list[str], done: dict) -> str:
    missing = [f for f in files if done.get(f, (None,))[0] is None]
    return f"[isolation] incomplete: {','.join(missing)}" if missing else f"[isolation] complete: {len(files)}"


def gate(wt: Path, selection: list[list[str]]) -> list[list[str]]:
    paths = selected_paths(selection)
    return ([[f"ROSY_JOB_CORES={GATE_CORES}", f"ROSY_COLLECT_PATHS={','.join(paths)}", GATE, NO_NARROW]]
            if paths and (wt / GATE).is_file() else [])


def job(files: list[str]) -> list[list[str]]:
    return [[f"ROSY_JOB_CORES={GATE_CORES}", f"ROSY_ALONE_FILES={','.join(files)}", GATE, NO_NARROW]] if files else []


def _selector(wt: Path):
    harness = str(Path(__file__).resolve().parent / "harness")
    if harness not in sys.path:
        sys.path.insert(0, harness)
    import affected_narrow
    import affected_tests
    import safety_review
    repo = affected_tests.Repo.load(wt)
    return repo, affected_tests, lambda p: repo.referencing_tests(p) + affected_narrow.registry_readers(repo, p), \
        lambda p: safety_review.is_safety(p, repo.safety_roots, repo.safety_modules)


def alone_files(wt: Path, selection: list[list[str]], base: str = "main") -> tuple[list[str], set[str]]:
    """(selected tests referencing this branch's changes, safety-tagged sources' first, then spec loaders;
    the safety ones)."""
    if not (wt / GATE).is_file() or not (selected := set(tracked_tests(wt, selected_paths(selection)))):
        return [], set()
    repo, at, refs, safety = _selector(wt)
    changed = at.changed_files(wt, base, "HEAD")
    first = {t for p in changed if safety(p) for t in refs(p)} & selected
    rest = {t for p in changed for t in refs(p)} & selected - first
    rank = lambda t: (t not in first, "spec_from_file_location" not in repo.text(t), t)  # noqa: E731
    return sorted(first | rest, key=rank), first


def _common(wt: Path) -> Path:
    return Path(subprocess.run(["git", "-C", str(wt), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                               capture_output=True, text=True, check=True).stdout.strip())


def _git(wt: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(wt), *args], capture_output=True, text=True, encoding="utf-8").stdout.strip()


def unreached(wt: Path, inv: list[str], logs: list[Path]) -> list[str] | None:
    """Files of an alone job the budget did not reach, from its report line; ``None`` without a report (the job
    died, or a reused pass whose log is gone): a failed job, not overflow."""
    cached = [Path(e["log"]) for e in _cache_entries(wt) if e.get("argv") == inv and e.get("log")]
    for log in [*logs, *reversed(cached)]:
        text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
        if m := REPORT.search(text):
            return [] if m[1] == "complete" else [f for f in m[2].split(",") if f]
    return None


def _cache_entries(wt: Path) -> list[dict]:
    import land_cache
    return land_cache.entries(wt)


def _fresh(logdir: Path, round_no: str, since: float) -> list[Path]:
    return [p for p in sorted(logdir.glob(f"run-g{round_no}-*.txt")) if p.stat().st_mtime >= since]


def record(wt: Path, branch: str, kind: str, files: list[str], incomplete: list[str], **extra) -> list[str]:
    """Append one line to the shared record (and land_events); summary lines when files were not run alone.

    kind: ``prepare`` (this branch's alone job), ``skipped`` (--no-queue: nothing ran alone), ``done`` (a later
    alone job, ``python tools/land_isolation.py close``)."""
    line = {"t": round(time.time()), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "branch": branch, "kind": kind,
            "candidate": _git(wt, "rev-parse", "HEAD"), "main": _git(wt, "rev-parse", "main"),
            "alone": files, "incomplete": incomplete, **extra}
    with open(_common(wt) / RECORD, "a", encoding="utf-8") as out:
        out.write(json.dumps(line) + "\n")
    import land_events
    land_events.emit("isolation", **{k: v for k, v in line.items() if k not in ("t", "branch")})
    return [f"isolation incomplete: {', '.join(incomplete)}"] if incomplete and kind != "skipped" else []


def rows(wt: Path) -> list[dict]:
    try:
        text = (_common(wt) / RECORD).read_text(encoding="utf-8")
    except OSError:
        return []
    found = []
    for row in text.splitlines():
        try:
            rec = json.loads(row)
        except ValueError:
            continue
        if isinstance(rec, dict) and isinstance(rec.get("candidate"), str):
            found.append(rec)
    return found


def _ancestor(wt: Path, a: str, b: str) -> bool:
    return subprocess.run(["git", "-C", str(wt), "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


def last(wt: Path, branch: str) -> dict | None:
    """This branch's newest prepare record whose candidate HEAD still contains."""
    for rec in reversed(rows(wt)):
        if rec.get("branch") == branch and rec.get("kind") == "prepare":
            return rec if _ancestor(wt, rec["candidate"], "HEAD") else None
    return None


def open_entries(wt: Path, now: float, age_s: float = OPEN_AFTER_S) -> list[tuple[dict, list[str]]]:
    """Landed records (candidate in main) older than ``age_s`` with files never run alone since.

    A file closes when a later ``prepare`` or ``done`` line on a descendant commit ran it alone to a verdict, so
    closing needs no edit of old lines: the next landing that runs it, or ``close``, appends the evidence."""
    found, all_rows = [], rows(wt)
    for i, rec in enumerate(all_rows):
        left = list(rec.get("incomplete") or [])
        if not left or now - rec.get("t", now) < age_s or not _ancestor(wt, rec["candidate"], "main"):
            continue
        for later in all_rows[i + 1:]:
            if later.get("kind") in ("prepare", "done") and _ancestor(wt, rec["candidate"], later["candidate"]):
                left = [f for f in left if f not in later.get("alone", []) or f in later.get("incomplete", [])]
        if left:
            found.append((rec, left))
    return found


def stale(wt: Path, rec: dict | None) -> list[str]:
    """Alone-run tests that reference a file main changed since the prepare record's main."""
    if not rec or not rec.get("alone") or rec["main"] == (main := _git(wt, "rev-parse", "main")):
        return []
    delta = _git(wt, "diff", "--name-only", "--no-renames", rec["main"], main).splitlines()
    if not delta:
        return []
    _, _, refs, _ = _selector(wt)
    hit = {t for p in delta for t in refs(p)}
    return [t for t in rec["alone"] if t in hit]


class IsolationStop(RuntimeError):
    """Raised when the caller's run_tests carries no ``Stop`` (tests); land.py's own Stop otherwise."""


def _prepare(wt, branch, selection, args, logdir, round_no, run_tests, guards, stop) -> list[str]:
    files, safety = alone_files(wt, selection)
    since = time.time() - 1
    try:
        batch = guards + gate(wt, selection) + job(files)
        done = run_tests(wt, args, batch, logdir, f"g{round_no}") if batch else []
    except BaseException:
        if files:  # a NEW failure or a dead job stops the landing; the files still never ran alone to a pass
            record(wt, branch, "prepare", files, files, error="the round stopped")
        raise
    cut = unreached(wt, job(files)[0], _fresh(logdir, round_no, since)) if files else []
    if cut is None:  # a job without its report failed; once more without the cache, then stop
        retry = argparse.Namespace(**{**vars(args), "no_cache": True})
        done += run_tests(wt, retry, job(files), logdir, f"g{round_no}r")
        cut = unreached(wt, job(files)[0], _fresh(logdir, f"{round_no}r", since))
        if cut is None:
            record(wt, branch, "prepare", files, files, error="no [isolation] report twice")
            raise stop("isolation: the alone job ended twice without its [isolation] report; not landing")
    notes = record(wt, branch, "prepare", files, cut)  # an empty one still ends the previous record
    if unsafe := [f for f in cut if f in safety]:
        raise stop(f"isolation: {len(unsafe)} test(s) of safety-tagged sources not run alone within {BUDGET_S} s"
                   f" ({', '.join(unsafe)}); safety never lands as isolation incomplete")
    return done + notes


def _turn(wt, branch, selection, args, logdir, round_no, run_tests, guards) -> list[str]:
    notes = []
    if getattr(args, "no_queue", False):
        notes.append("isolation gate skipped (--no-queue)")
        head = _git(wt, "rev-parse", "HEAD")
        if not any(r.get("kind") == "skipped" and r["candidate"] == head for r in rows(wt)):
            files = alone_files(wt, selection)[0]
            record(wt, branch, "skipped", files, files)
    else:
        rec = last(wt, branch)
        if rec and rec.get("incomplete"):
            notes.append(f"isolation incomplete: {', '.join(rec['incomplete'])}")
        # In the turn's own round, not here: TURN_CAP_S and Overtime -> land_prepare.again apply to them as to
        # the delta selection. ``selection`` is land.py's list, extended in place.
        selection.extend([t] for t in stale(wt, rec) if [t] not in selection)
    if found := open_entries(wt, time.time()):
        notes.append(f"isolation open: {len(found)} record(s) older than a night with files never run alone"
                     " (python tools/doctor.py)")
    done = run_tests(wt, args, guards, logdir, f"g{round_no}") if guards else []
    for note in notes:
        print(f"[land] {note}", flush=True)
    return done + notes


def run(wt: Path, branch: str, selection: list[list[str]], args, logdir: Path, round_no: str, run_tests,
        guards: list[list[str]], prepare: bool) -> list[str]:
    """One guard-round batch: the guards, plus the gate and the alone job (prepare) or the turn's checks."""
    if not (wt / GATE).is_file():
        return run_tests(wt, args, guards, logdir, f"g{round_no}") if guards else []
    if prepare:  # land.py's Stop: the class its main catches (run_tests is land.run_tests)
        return _prepare(wt, branch, selection, args, logdir, round_no, run_tests, guards,
                        run_tests.__globals__.get("Stop", IsolationStop))
    return _turn(wt, branch, selection, args, logdir, round_no, run_tests, guards)


def main(argv: list[str] | None = None) -> int:
    """``close <files> --reason TEXT``: run them alone (one remote job on HEAD) and append a ``done`` line with
    the reason, who (git user.email, else the OS user) and when."""
    parser = argparse.ArgumentParser(description="Run test files alone on a test host and record them done.")
    parser.add_argument("command", choices=["close"])
    parser.add_argument("files", nargs="+")
    parser.add_argument("--reason", required=True, help="why these files are closed by hand")
    ns = parser.parse_args(argv)
    if not ns.reason.strip():
        parser.error("--reason must say why")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "remote"))
    import remote_pytest
    wt, inv = Path.cwd(), job(ns.files)[0]
    log = Path(tempfile.mkdtemp(prefix="rosy-isolation-")) / "alone.txt"
    code = remote_pytest.run([inv], [log], _git(wt, "rev-parse", "HEAD"), repo=wt, label="isolation")[0]
    cut = unreached(wt, inv, [log])
    if code != 0 or cut is None:
        print(f"[isolation] alone job failed (exit {code}, log {log}); nothing recorded")
        return 1
    who = _git(wt, "config", "user.email") or getpass.getuser()
    record(wt, _git(wt, "rev-parse", "--abbrev-ref", "HEAD"), "done", ns.files, cut, reason=ns.reason.strip(), by=who)
    print(f"[isolation] done: {len(ns.files) - len(cut)} file(s) ran alone" + (f"; still not run: {cut}" if cut else ""))
    return 0 if not cut else 1


if __name__ == "__main__":
    raise SystemExit(main())
