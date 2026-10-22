"""test/browser_scope.py maps changed paths to the browser tests that load them."""

from __future__ import annotations

import browser_scope


def test_fleet_development_changes_include_independent_browser_flows():
    for path in ('applications/fleet/dev/sample/engine.py', 'applications/fleet/web/runtime.js'):
        found = browser_scope.targets([path])
        assert 'applications/fleet/test/test_feature_browser_flows.py' in found
        assert 'applications/fleet/test/test_sample_browser.py' in found


def test_fleet_web_change_selects_fleet_browser_tests():
    found = browser_scope.targets(["applications/fleet/web/sitemap/site-map.js"])
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


def test_pilot_and_shared_styles_select_moved_lobby_tests_without_widening_omx():
    lobby = "middleware/robot_ui/pilot/test/test_lobby_browser.py"
    for path in ("middleware/robot_ui/pilot/styles.css", "shared/web/components.css"):
        assert lobby in browser_scope.targets([path])
    assert browser_scope.targets(["middleware/devices/omx/adapter/example.py"]) == [
        "middleware/devices/omx/adapter/test/test_pilot_sim_browser.py"
    ]


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


def test_empty_selection_exits_3_without_targets(capsys):
    assert browser_scope.main(["docs/logs.md"]) == 3
    out = capsys.readouterr()
    assert out.out == "" and "no browser tests" in out.err
    assert browser_scope.main(["test/test_games_board_browser.py"]) == 0
    assert capsys.readouterr().out.strip() == "test/test_games_board_browser.py"


def test_sim_sources_select_sim_browser():
    for path in (
        "learning/curation/perception/review_app_web/sim.js",
        "learning/curation/perception/sim_web.py",
        "shared/web/ui.js",
    ):
        assert "test/learning/perception/test_sim_browser.py" in browser_scope.targets([path])
