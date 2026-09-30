"""Web budget verdicts (D-262, UI lane execution).

test_module_structure.py budgets only .py/.cpp/.hpp. This file budgets the
browser surfaces the same way: every file over budget needs a recorded
verdict, and regrowth past the allowance re-opens the judgment.
"""

from pathlib import Path
import shutil
import subprocess

import pytest

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
    "hmi/pilot/screens/drive.js": (
        708,
        "accept for now: the drive screen owns layout, input wiring, auto mode "
        "and the intent strip; pure logic already lives in stick.js, link.js, "
        "input-state.js and autonomy.js. Next split when it grows: the auto "
        "mode block and the zoom/layout block (D-323, D-344, D-363)",
    ),
    "hmi/dashboard/index.html": (
        713,
        "accept: markup is a document, not code; ui-shell grammar is guarded "
        "by test_shared_controls.py, not line counts (D-262)",
    ),
    "runtime/sensing/web/diagnostic.html": (
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


def _web_files() -> list[Path]:
    """예산 후보는 추적 파일과 아직 add하지 않은 파일이다 (D-329 Decision 3).

    파일시스템 `rglob`은 `.gitignore`된 빌드 산출물(지금은
    `site/overhead/android/build/**/problems-report.html`)을 예산 초과 후보로 집는다.
    `-c -o --exclude-standard`는 추적 파일과 add 안 된 새 파일은 모두, ignore된 것은
    잡지 않는다. `.js`까지 보는 것은 이 스캔만의 일이므로(레지스트리 발견 스캔은
    `.html` 한정) 여기에 둔다.
    """
    repo = SRC.parent
    if shutil.which("git") is None or not (repo / ".git").exists():
        pytest.skip("D-262 예산 스캔은 git 체크아웃이 필요하다")
    done = subprocess.run(
        ["git", "ls-files", "-c", "-o", "--exclude-standard", "--", "src"],
        cwd=repo, capture_output=True, text=True, encoding="utf-8", check=False,
    )
    assert done.returncode in (0, 1), done.stderr
    return sorted(
        repo / line for line in done.stdout.splitlines()
        if line.endswith((".js", ".html"))
    )


def test_web_files_over_budget_have_a_recorded_verdict():
    over = {}
    for path in _web_files():
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
    for path in _web_files():
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
