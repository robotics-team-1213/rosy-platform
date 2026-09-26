"""Web budget verdicts (D-262, UI lane execution).

test_module_structure.py budgets only .py/.cpp/.hpp. This file budgets the
browser surfaces the same way: every file over budget needs a recorded
verdict, and regrowth past the allowance re-opens the judgment.
"""

from pathlib import Path

SRC = Path(__file__).resolve().parents[3]

FILE_BUDGET = 600
REGROWTH_ALLOWANCE = 150

#: path (relative to src/) -> (lines at verdict, verdict).
VERDICTS = {
    "hmi/dashboard/app.js": (
        1289,
        "split: shell core stays (auth, session, sockets, refresh); "
        "vision, ros-network, host-cards extracted; further splits only on "
        "D-130.2 qualification (D-262)",
    ),
    "hmi/dashboard/index.html": (
        713,
        "accept: markup is a document, not code; ui-shell grammar is guarded "
        "by test_shared_controls.py, not line counts (D-262)",
    ),
    "runtime/sensing/web/dashboard.html": (
        1857,
        "accept: D-150 pins one file and one IIFE with no build step; "
        "PARKED surface (D-153, D-253)",
    ),
    "sim/gz_sim/scripts/lane_live_view.html": (
        833,
        "accept: sim-only viewer, sim lane owns it; mirrors the Python "
        "verdict for lane_live_view.py in test_module_structure.py",
    ),
}


def _lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def test_web_files_over_budget_have_a_recorded_verdict():
    over = {}
    for path in sorted(SRC.rglob("*.js")) + sorted(SRC.rglob("*.html")):
        if ".pytest_cache" in path.parts or "__pycache__" in path.parts:
            continue
        count = _lines(path)
        if count > FILE_BUDGET:
            over[path.relative_to(SRC).as_posix()] = count
    assert set(over) == set(VERDICTS), (
        f"needs a verdict: {sorted(set(over) - set(VERDICTS))}, "
        f"stale: {sorted(set(VERDICTS) - set(over))}"
    )


def test_web_verdicts_are_current():
    over = {}
    for path in sorted(SRC.rglob("*.js")) + sorted(SRC.rglob("*.html")):
        if ".pytest_cache" in path.parts or "__pycache__" in path.parts:
            continue
        count = _lines(path)
        if count > FILE_BUDGET:
            over[path.relative_to(SRC).as_posix()] = count
    bad = []
    for key, (at_verdict, verdict) in VERDICTS.items():
        if not verdict:
            bad.append(f"{key}: verdict must say split or accept with a reason")
        if key in over and over[key] > at_verdict + REGROWTH_ALLOWANCE:
            bad.append(f"{key}: {over[key]} lines, grew past "
                       f"{at_verdict}+{REGROWTH_ALLOWANCE}; re-judge")
    assert bad == [], bad
