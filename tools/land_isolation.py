"""What a shared pytest process can hide, checked in tools/land.py's guard round (land_guards.first).

2026-10-26: learning/training/omx/test/test_native_cycle.py landed 26 ERRORs (ModuleNotFoundError) on main. Its
folder passed in one pytest process because sibling modules put the missing module on sys.path or into
sys.modules while pytest collected them; alone the file did not import
(docs/solutions/workflow-issues/shared-pytest-process-masks-path-dependent-import-2026-10-26.md).

- ``gate``: one invocation of ``tools/collect_alone.py`` that runs ``pytest --collect-only`` for every selected
  test file in its own process, so such an import fails under the file's own id before the long round.
- ``alone`` (land_prepare only, outside the lock: the turn has a 10 min cap): test files that reference a changed file (the D-436 selector's ``references X`` edge), at most
  ``CAP`` (past that only those that load modules with ``spec_from_file_location``), plus every selected test
  under a safety root, each as its own invocation.

Both are off when the tree has no ``tools/collect_alone.py``. Standard library at import; the selector loads
only in ``alone``.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

GATE = "tools/collect_alone.py"
CAP = 10
# The gate is serial under xdist_plan (tools/ in serial_suites.txt); its pool takes this budget instead. 2 workers
# took 347 s for a FULL selection's 2,123 files (2026-10-26); a collect-only process peaked under 200 MiB.
GATE_CORES = 6
TEST_FILE = re.compile(r"(^|/)(test_[^/]*|[^/]*_test)\.py$")  # = affected_tests.TEST_FILE
ENV_WORD = re.compile(r"^ROSY_[A-Z0-9_]*=")
# remote_pytest.PYTEST_TAIL's options for one file; xdist off: each file already has its own process.
COLLECT = ["-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "-p", "no:xdist", "--rootdir=.",
           "-pno:launch_testing", "-pno:launch_ros"]


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


def collect_alone(root: Path, files: list[str], workers: int = 2, budget_s: float = 600.0,
                  file_timeout_s: float = 120.0) -> dict[str, tuple[int | None, str]]:
    """``{file: (exit code, output tail)}`` of ``pytest --collect-only <file>``, one process per file.

    Capped by time, not file count: a file not started within ``budget_s`` is left out; a timeout is ``None``."""
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTEST_XDIST", "PYTEST_CURRENT"))}
    deadline = time.monotonic() + budget_s

    def one(path: str):
        if time.monotonic() > deadline:
            return path, None
        try:
            r = subprocess.run([sys.executable, *COLLECT, path], cwd=root, capture_output=True, text=True,
                               encoding="utf-8", errors="replace", env=env, timeout=file_timeout_s)
        except subprocess.TimeoutExpired:
            return path, (None, f"timed out after {file_timeout_s:.0f} s")
        return path, (r.returncode, (r.stdout + r.stderr)[-3000:])

    with ThreadPoolExecutor(max(1, workers)) as pool:
        return {path: res for path, res in pool.map(one, files) if res is not None}


def gate(wt: Path, invocations: list[list[str]]) -> list[list[str]]:
    paths = selected_paths(invocations)
    return ([[f"ROSY_JOB_CORES={GATE_CORES}", f"ROSY_COLLECT_PATHS={','.join(paths)}", GATE]]
            if paths and (wt / GATE).is_file() else [])


def alone(wt: Path, invocations: list[list[str]], base: str = "main") -> list[list[str]]:
    if not (wt / GATE).is_file():
        return []
    selected = set(tracked_tests(wt, selected_paths(invocations)))
    if not selected:
        return []
    harness = str(Path(__file__).resolve().parent / "harness")
    if harness not in sys.path:
        sys.path.insert(0, harness)
    import affected_narrow
    import affected_tests
    import safety_review

    repo = affected_tests.Repo.load(wt)
    refs = sorted({t for p in affected_tests.changed_files(wt, base, "HEAD")
                   for t in repo.referencing_tests(p) + affected_narrow.registry_readers(repo, p)} & selected)
    if len(refs) > CAP:
        refs = [t for t in refs if "spec_from_file_location" in repo.text(t)]
    safety = {t for t in selected if safety_review.is_safety(t, repo.safety_roots, repo.safety_modules)}
    return [[t] for t in sorted(set(refs) | safety) if [t] not in invocations]


def invocations(wt: Path, selection: list[list[str]], isolated: bool) -> list[list[str]]:
    """The gate, and with ``isolated`` the files to run alone, for this selection; [] when the tree has no gate."""
    return gate(wt, selection) + (alone(wt, selection) if isolated else [])
