"""Browser evidence in the pull_request run (D-1066): which real-Chromium files CI runs, which stay lab evidence.

One rule for both sides: ci_matrix adds the entries below, tools/pr_land.py asks the lab only for split()[1],
and ci.yml's Test step rejects a STRICT run that skipped or passed nothing (vacuous).
"""
from __future__ import annotations

import math
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
for _extra in (_ROOT / "tools", _ROOT / "tools" / "remote", _ROOT / "test"):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

import work_queue  # noqa: E402

ENV = "ROSY_BROWSER_CI"
OPT_IN = "ROSY_RUN_BROWSER_TESTS=1"
STRICT = "ROSY_BROWSER_STRICT=1"
# ci.yml opts these roots in to Chromium by itself.
CI_BROWSER_ROOTS = ("operations/fleet/test", "applications/fleet/test")
# Simulators and OMX adapter hardware suites: GitHub runners cannot run them (same tuple as pr_land.EXCLUDED_PREFIXES).
LAB_PREFIXES = ("integrations/simulation/", "learning/envs/isaac/", "middleware/devices/omx/adapter/")
FILES_PER_JOB, MAX_JOBS = 12, 4


def lab_path(path: str) -> bool:
    return path.startswith(LAB_PREFIXES) or work_queue.lab_only([path], above=False)


def split(paths) -> tuple[list[str], list[str]]:
    """(ci, lab), both sorted."""
    paths = sorted(set(paths))
    return [p for p in paths if not lab_path(p)], [p for p in paths if lab_path(p)]


def vacuous(text: str) -> str | None:
    """Why a STRICT run's pytest output is no verdict (nothing passed, or something skipped); None otherwise.

    The rule of land_browser.vacuous, on text: without the opt-in or Chromium every test skips and pytest exits 0."""
    summary = re.compile(r"\b(passed|failed|skipped|errors?|no tests ran)\b.* in [0-9.]+s")
    runs = [{k: int(n) for n, k in re.findall(r"(\d+) (passed|skipped)", ln)}
            for ln in text.splitlines() if summary.search(ln)]
    passed, skipped = sum(r.get("passed", 0) for r in runs), sum(r.get("skipped", 0) for r in runs)
    if not passed or skipped:
        return f"{passed} passed, {skipped} skipped (the opt-in or Chromium did not reach the job, or a guard skipped)"
    return None


def _selected(path: str, sel) -> bool:
    """Does the run's own selection execute this Fleet-root file? Full mode runs the Fleet suites."""
    if sel.mode == "full":
        return True
    words = (w.split("::")[0] for inv in sel.invocations for w in inv
             if not w.startswith("-") and not re.match(r"^ROSY_[A-Z0-9_]*=", w))
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in words)


def entries(repo, sel) -> list[dict]:
    """Extra matrix entries for the browser files a pull_request's changes need; [] unless ROSY_BROWSER_CI=1."""
    if os.environ.get(ENV) != "1" or not sel.changed:
        return []
    import browser_scope  # noqa: PLC0415  (test/, tools/: a failed import must fail the scope job loudly)
    import land_browser
    import affected_ros
    import affected_tests as at
    ci = [p for p in split(browser_scope.targets(list(sel.changed)))[0]
          if not (p.startswith(tuple(r + "/" for r in CI_BROWSER_ROOTS)) and _selected(p, sel))]
    out = []
    alone = [p for p in ci if p in land_browser.ALONE]
    if alone:
        out.append({"name": "browser-alone", "ros": "overlay", "invocations": [[OPT_IN, STRICT, *alone]]})
    groups: dict[str, list[str]] = {}
    for p in ci:
        if p not in land_browser.ALONE:
            groups.setdefault(affected_ros.full_tier_ros(p, at.CI_FULL_MATRIX), []).append(p)
    for ros, files in sorted(groups.items()):
        files, jobs = sorted(files), min(MAX_JOBS, math.ceil(len(files) / FILES_PER_JOB))
        for i in range(jobs):
            out.append({"name": f"browser-{ros}-{i + 1}of{jobs}", "ros": ros,
                        "invocations": [[OPT_IN, STRICT, *inv] for inv in at.pack(repo, files[i::jobs])]})
    return out
