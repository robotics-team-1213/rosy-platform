"""test/browser_scope.py maps changed paths to the browser tests that load them."""

from __future__ import annotations

import browser_scope


def test_fleet_web_change_selects_fleet_browser_tests():
    found = browser_scope.targets(["operations/fleet/fleet/server/web/site-map.js"])
    assert "test/test_fleet_console_browser.py" in found
    assert "operations/fleet/test/test_start_point_browser.py" in found
    assert "operations/fleet/test/test_site_map_browser.py" in found
    assert "operations/fleet/test/test_cell_app_browser.py" in found
    assert not any(t.startswith("middleware/ui/pilot/") for t in found)


def test_shared_web_change_reaches_every_surface_family():
    found = browser_scope.targets(["shared/web/components.css"])
    for expected in ("shared/web/test/test_theme_browser.py", "test/test_dashboard_browser.py",
                     "test/test_fleet_console_browser.py", "middleware/ui/pilot/test/test_pilot_browser.py"):
        assert expected in found


def test_a_changed_browser_test_selects_itself_and_unrelated_paths_select_nothing():
    assert browser_scope.targets(["test/test_games_board_browser.py"]) == ["test/test_games_board_browser.py"]
    assert browser_scope.targets(["docs/logs.md", "middleware/perception/control/goals.py"]) == []


def test_windows_separators_are_accepted():
    assert browser_scope.targets(["middleware\\ui\\pilot\\styles.css"]) == browser_scope.targets(
        ["middleware/ui/pilot/styles.css"])


def test_every_scope_target_exists():
    for patterns in browser_scope.SCOPE.values():
        for pattern in patterns:
            assert browser_scope._expand(pattern), pattern


def test_a_listed_non_browser_named_test_selects_itself():
    path = "learning/training/perception/test/test_review_app_smoke.py"
    assert browser_scope.targets([path]) == [path]


def test_shared_web_reaches_review_smoke_and_core_console():
    found = browser_scope.targets(["shared/web/ui.js"])
    assert "learning/training/perception/test/test_review_app_smoke.py" in found
    assert "middleware/core/api_web/test/test_d283_console_browser.py" in found


def test_empty_selection_exits_3_without_targets(capsys):
    assert browser_scope.main(["docs/logs.md"]) == 3
    out = capsys.readouterr()
    assert out.out == "" and "no browser tests" in out.err
    assert browser_scope.main(["test/test_games_board_browser.py"]) == 0
    assert capsys.readouterr().out.strip() == "test/test_games_board_browser.py"
