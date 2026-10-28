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
    "test/test_integrated_control_backend_browser.py",
    "applications/fleet/test/test_sample_browser.py",
    "applications/fleet/test/test_feature_browser_flows.py",
    "applications/fleet/test/test_browser_adapters.py",
    "test/test_measured_calibration_browser.py",
    "test/test_motor_health_ui_browser.py",
    "test/test_fleet_workcell_observation_browser.py",
    "test/test_fleet_console_browser.py",
    "test/test_console_lifetime_browser.py",
    "test/test_console_session_browser.py",
    "test/test_fleet_workflows_browser.py",
    "test/test_host_recovery_browser.py",
    "test/test_overhead_tracking_browser.py",
    "test/test_peer_picker_browser.py",
    "operations/fleet/test/*_browser.py",
]
ROBOT = [
    "test/test_motor_health_ui_browser.py",
    "test/test_dashboard_browser.py",
    "test/test_role_menu_panels_browser.py",
    "test/test_role_surface_states_browser.py",
    "test/test_surface_device_browser.py",
    "test/test_surface_shell_browser.py",
    "test/test_camera_capture_browser.py",
    "middleware/robot_ui/robot/test/*_browser.py",
    "middleware/robot_ui/robot/test/test_surface_bridge.py",
    "middleware/robot_ui/robot/test/test_surface_home_link.py",
]
API_WEB = [
    "middleware/core/api/test/test_d283_console_browser.py",
    "middleware/robot_ui/robot/test/test_role_g2_browser.py",
    "middleware/robot_ui/robot/test/test_calibration_chip_browser.py",
    "middleware/robot_ui/robot/test/test_surface_viewport_budget_browser.py",
    "middleware/robot_ui/robot/test/test_dashboard_entry_browser.py",
]
PILOT = [
    "middleware/robot_ui/pilot/test/test_pilot_browser.py",
    "middleware/robot_ui/pilot/test/test_lobby_browser.py",
    "middleware/devices/omx/adapter/test/test_pilot_sim_browser.py",
]
GAMES = ["test/test_games_board_browser.py"]
REVIEW = [
    "test/learning/perception/test_sim_browser.py",
    "test/learning/perception/test_vlm_judge_browser.py",
    "test/learning/perception/test_storage_inventory_http.py",
    "test/learning/perception/test_review_flow_browser.py",
    "test/learning/perception/test_learning_pipeline_browser.py",
    "test/learning/perception/test_pixel_review_browser.py",
    "test/learning/perception/test_review_app_smoke.py",
]
OMX_LEARNING = ["test/learning/perception/test_omx_" + name + "_browser.py" for name in
                ("center", "profiles", "review_playback", "arm_scope", "owner_status", "segments", "camera_reference")]
CAMERA = ["test/learning/perception/test_camera_setup_browser.py"]
SIM = ["test/learning/perception/test_sim_browser.py"]
PIPELINE = ["test/learning/perception/test_learning_pipeline_browser.py"]
ACCOUNTS = ["test/learning/perception/test_learning_accounts_browser.py"]
TASKS = ["test/learning/perception/test_learning_tasks_browser.py"]
STAGES = ["test/learning/perception/test_learning_stages_browser.py", "test/learning/perception/test_vlm_judge_browser.py",
          "test/learning/perception/test_promotion_request_browser.py"]
LEARNING = OMX_LEARNING + CAMERA + SIM + PIPELINE + ACCOUNTS + TASKS + STAGES
GAZEBO = ["integrations/simulation/gazebo/test/test_lane_live_view_browser.py"]
SHARED = ["shared/web/test/*_browser.py"]
COMMISSIONING = ["test/test_omx_commissioning_view.py"]
MONITORING = ["test/test_monitoring_browser.py"]
EVERYTHING = FLEET + ROBOT + API_WEB + PILOT + GAMES + REVIEW + LEARNING + GAZEBO + SHARED + COMMISSIONING + MONITORING

SCOPE: dict[str, list[str]] = {
    "applications/monitoring/": MONITORING,
    "operations/monitoring/": MONITORING,
    "applications/fleet/dev/": FLEET,
    "applications/fleet/test/": FLEET,
    "operations/fleet/fleet/server/": FLEET,
    "applications/fleet/web/": FLEET,
    "middleware/robot_ui/robot/": ROBOT,
    "middleware/core/api/": API_WEB,
    "middleware/robot_ui/pilot/": PILOT,
    "middleware/devices/omx/adapter/": PILOT[2:],
    "operations/apps/games/": GAMES,
    "learning/curation/perception/": REVIEW,
    "learning/curation/perception/review_app.py": LEARNING,
    "learning/curation/perception/review_app_web/app.css": LEARNING,
    "learning/curation/perception/review_app_web/commands.js": LEARNING,
    "learning/curation/perception/review_app_web/account-session.js": LEARNING,
    **{f"learning/curation/perception/review_app_web/{name}": OMX_LEARNING for name in
       ("omx.html", "omx.js", "omx-profiles.js", "omx-review.js")},
    # Their rail and sub-menu are walked by the OMX owner-status and stage browser tests.
    **{f"learning/curation/perception/review_app_web/{name}": OMX_LEARNING + STAGES for name in
       ("catalog.html", "camera.html")},
    "learning/curation/perception/omx_web.py": OMX_LEARNING,
    "learning/curation/perception/omx_center_web.py": OMX_LEARNING,
    "learning/training/omx/": OMX_LEARNING + TASKS,
    **{f"learning/curation/perception/{name}": TASKS for name in
       ("learning_tasks.py", "learning_tasks_web.py", "review_app_web/tasks.html", "review_app_web/tasks.js")},
    **{f"learning/curation/perception/{name}": CAMERA for name in
       ("camera_setup.py", "camera_setup_web.py", "review_app_web/camera.html", "review_app_web/camera.js")},
    "contracts/learning/src/rosy/contracts/learning/camera_setup.py": CAMERA,
    **{f"learning/curation/perception/{name}": SIM for name in
       ("sim_web.py", "review_app_web/sim.html", "review_app_web/sim.js")},
    **{f"learning/curation/perception/{name}": PIPELINE for name in
       ("learning_control.py", "learning_pipeline.py")},
    **{f"learning/curation/perception/review_app_web/{name}": PIPELINE + OMX_LEARNING + SIM + ACCOUNTS + TASKS
       for name in ("learning.html", "learning.js")},
    **{f"learning/curation/perception/{name}": STAGES for name in
       ("vlm_judge.py", "vlm_judge_report.py", "vlm_judge_web.py", "learning_domains.py", "promotion_request.py", "review_app_web/vlm.html", "review_app_web/vlm.js",
        "review_app_web/vlm.css", "review_app_web/evaluate.html", "review_app_web/evaluate.js",
        "review_app_web/workspaces.js")},
    "learning/curation/perception/review_app_web/workspaces.html": OMX_LEARNING + STAGES,
    **{f"learning/curation/perception/{name}": ACCOUNTS for name in
       ("learning_accounts.py", "learning_collaboration.py", "learning_oauth.py", "learning_rosy_accounts.py",
        "review_app_web/accounts.html", "review_app_web/accounts.js")},
    "integrations/simulation/gazebo/scripts/": GAZEBO,
    "deploy/robot/omx/commissioning_view.py": COMMISSIONING,
    # Every surface loads /common (ui.js, components.css, tokens.css).
    "shared/web/": SHARED + FLEET + ROBOT + API_WEB[:1] + PILOT + GAMES + REVIEW + LEARNING,
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
        # test_ prefix: tools/land_browser.py is a module, not a test (2026-10-26 landings stopped on it)
        if path in known or (path.rsplit("/", 1)[-1].startswith("test_") and path.endswith("_browser.py")
                             and (ROOT / path).is_file()):
            selected.add(path)
    return sorted(selected)


def all_targets() -> list[str]:
    """Expand every registered browser target in this candidate tree."""
    return sorted({path for pattern in EVERYTHING for path in _expand(pattern)})


def main(argv: list[str]) -> int:
    if argv == ["--all", "--json"]:
        import json
        print(json.dumps(all_targets()))
        return 0
    found = targets(argv)
    if not found:
        print("browser_scope: no browser tests for these paths", file=sys.stderr)
        return 3
    print(" ".join(found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
