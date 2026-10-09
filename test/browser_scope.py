"""Which real-Chromium tests a change needs.

Usage (from the repo root):

    python test/browser_scope.py <changed paths...>      # prints pytest targets
    t=$(python test/browser_scope.py $(git diff --name-only main...)) && ROSY_RUN_BROWSER_TESTS=1 python -m pytest $t

SCOPE maps a source path prefix to the browser tests that load those pages
(derived from the pages each test serves or routes). Targets may be globs. A
changed browser test (any file a SCOPE entry lists, or any *_browser.py) selects
itself. Exit 3 with a stderr note when nothing applies, so `&&` never turns an
empty selection into a bare repo-wide pytest.
"""

from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]

FLEET = [
    "test/test_fleet_console_browser.py",
    "test/test_console_lifetime_browser.py",
    "test/test_console_session_browser.py",
    "test/test_fleet_workflows_browser.py",
    "test/test_overhead_tracking_browser.py",
    "test/test_peer_picker_browser.py",
    "operations/fleet/test/*_browser.py",
]
ROBOT = [
    "test/test_dashboard_browser.py",
    "test/test_role_menu_panels_browser.py",
    "test/test_role_surface_states_browser.py",
    "test/test_surface_device_browser.py",
    "test/test_camera_capture_browser.py",
    "middleware/ui/robot/test/*_browser.py",
    "middleware/ui/robot/test/test_surface_bridge.py",
    "middleware/ui/robot/test/test_surface_home_link.py",
]
API_WEB = [
    "middleware/core/api_web/test/test_d283_console_browser.py",
    "middleware/ui/robot/test/test_role_g2_browser.py",
    "middleware/ui/robot/test/test_calibration_chip_browser.py",
    "middleware/ui/robot/test/test_surface_viewport_budget_browser.py",
    "middleware/ui/robot/test/test_dashboard_entry_browser.py",
]
PILOT = [
    "middleware/ui/pilot/test/test_pilot_browser.py",
    "middleware/apps/device/omx/adapter/test/test_pilot_sim_browser.py",
]
GAMES = ["test/test_games_board_browser.py"]
REVIEW = [
    "learning/training/perception/test/test_review_flow_browser.py",
    "learning/training/perception/test/test_pixel_review_browser.py",
    "learning/training/perception/test/test_review_app_smoke.py",
]
GAZEBO = ["integrations/simulation/gazebo/test/test_lane_live_view_browser.py"]
SHARED = ["shared/web/test/*_browser.py"]
EVERYTHING = FLEET + ROBOT + API_WEB + PILOT + GAMES + REVIEW + GAZEBO + SHARED

SCOPE: dict[str, list[str]] = {
    "operations/fleet/fleet/server/": FLEET,
    "middleware/ui/robot/": ROBOT,
    "middleware/core/api_web/": API_WEB,
    "middleware/ui/pilot/": PILOT,
    "middleware/apps/device/omx/adapter/": PILOT[1:],
    "operations/apps/games/": GAMES,
    "learning/training/perception/dataset/": REVIEW,
    "integrations/simulation/gazebo/scripts/": GAZEBO,
    # Every surface loads /common (ui.js, components.css, tokens.css).
    "shared/web/": SHARED + FLEET + ROBOT + API_WEB[:1] + PILOT + GAMES + REVIEW,
    "test/browser_harness.py": EVERYTHING,
}


def _expand(pattern: str) -> list[str]:
    if "*" not in pattern:
        return [pattern] if (ROOT / pattern).is_file() else []
    return sorted(p.relative_to(ROOT).as_posix() for p in ROOT.glob(pattern))


def targets(paths: list[str]) -> list[str]:
    known = {t for pattern in EVERYTHING for t in _expand(pattern)}
    selected: set[str] = set()
    for raw in paths:
        path = raw.replace("\\", "/").removeprefix("./")
        for prefix, patterns in SCOPE.items():
            if path.startswith(prefix):
                for pattern in patterns:
                    selected.update(_expand(pattern))
        if path in known or (path.endswith("_browser.py") and (ROOT / path).is_file()):
            selected.add(path)
    return sorted(selected)


def main(argv: list[str]) -> int:
    found = targets(argv)
    if not found:
        print("browser_scope: no browser tests for these paths", file=sys.stderr)
        return 3
    print(" ".join(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
