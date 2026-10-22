"""test/browser_scope.py maps changed paths to the browser tests that load them."""

from __future__ import annotations

import browser_scope


def test_fleet_web_change_selects_fleet_browser_tests():
    found = browser_scope.targets(["operations/site_ui/console/maps/site-map.js"])
    assert "test/test_fleet_console_browser.py" in found
    assert "operations/fleet/test/test_start_point_browser.py" in found
    assert "operations/fleet/test/test_site_map_browser.py" in found
    assert "operations/fleet/test/test_cell_app_browser.py" in found
    assert not any(t.startswith("middleware/robot_ui/pilot/") for t in found)


def test_shared_web_change_reaches_every_surface_family():
    found = browser_scope.targets(["shared/web/components.css"])
    for expected in ("shared/web/test/test_theme_browser.py", "test/test_dashboard_browser.py",
                     "test/test_fleet_console_browser.py", "middleware/robot_ui/pilot/test/test_pilot_browser.py"):
        assert expected in found


def test_a_changed_browser_test_selects_itself_and_unrelated_paths_select_nothing():
    assert browser_scope.targets(["test/test_games_board_browser.py"]) == ["test/test_games_board_browser.py"]
    assert browser_scope.targets(["docs/logs.md", "middleware/drive/planning/grid/goals.py"]) == []


def test_windows_separators_are_accepted():
    found = browser_scope.targets(["middleware\\robot_ui\\pilot\\styles.css"])
    assert found and found == browser_scope.targets(["middleware/robot_ui/pilot/styles.css"])


def test_every_scope_target_exists():
    for patterns in browser_scope.SCOPE.values():
        for pattern in patterns:
            assert browser_scope._expand(pattern), pattern


def test_every_scope_prefix_exists():
    """A prefix left behind by a folder move matches nothing and selects no test."""
    for prefix in browser_scope.SCOPE:
        assert (browser_scope.ROOT / prefix).exists(), prefix


def test_a_listed_non_browser_named_test_selects_itself():
    path = "test/learning/perception/test_review_app_smoke.py"
    assert browser_scope.targets([path]) == [path]


def test_shared_web_reaches_review_smoke_and_core_console():
    found = browser_scope.targets(["shared/web/ui.js"])
    assert "test/learning/perception/test_review_app_smoke.py" in found
    assert "middleware/core/api/test/test_d283_console_browser.py" in found
    assert "test/test_surface_shell_browser.py" in found
    assert "test/test_surface_shell_browser.py" in browser_scope.targets(["middleware/robot_ui/robot/web/app.js"])


def test_learning_changes_select_the_screens_that_use_them():
    root = "learning/curation/perception/"
    for source, expected in [("review_app_web/omx-profiles.js", browser_scope.OMX_LEARNING),
                             ("camera_setup_web.py", browser_scope.CAMERA),
                             ("sim_web.py", browser_scope.SIM),
                             ("learning_pipeline.py", browser_scope.PIPELINE),
                             ("learning_rosy_accounts.py", browser_scope.ACCOUNTS)]:
        found = browser_scope.targets([root + source])
        assert set(expected) <= set(found)
        assert not any(path.startswith("operations/fleet/") for path in found)
    for source in (root + "review_app.py", root + "review_app_web/app.css", "shared/web/ui.js"):
        assert set(browser_scope.LEARNING) <= set(browser_scope.targets([source]))


def test_empty_selection_exits_3_without_targets(capsys):
    assert browser_scope.main(["docs/logs.md"]) == 3
    out = capsys.readouterr()
    assert out.out == "" and "no browser tests" in out.err
    assert browser_scope.main(["test/test_games_board_browser.py"]) == 0
    assert capsys.readouterr().out.strip() == "test/test_games_board_browser.py"


def test_common_robot_tasks_select_real_browser_flow():
    expected = 'test/learning/perception/test_learning_tasks_browser.py'
    for source in ('learning_tasks.py', 'learning_tasks_web.py', 'review_app.py',
                   'review_app_web/tasks.js', 'review_app_web/tasks.html', 'review_app_web/learning.html'):
        assert expected in browser_scope.targets(['learning/curation/perception/' + source])
    assert expected in browser_scope.targets(['learning/training/omx/experiment_center.py'])
