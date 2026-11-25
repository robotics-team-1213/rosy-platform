"""test/browser_scope.py maps changed paths to the browser tests that load them."""

from __future__ import annotations

import browser_scope


def test_monitoring_backend_and_app_share_the_real_browser_contract():
    expected = ['test/test_monitoring_browser.py']
    assert browser_scope.targets(['applications/monitoring/web/monitoring.js']) == expected
    assert browser_scope.targets(['operations/monitoring/src/rosy/monitoring/service.py']) == expected


def test_calibration_screen_sources_select_header_and_job_browser_tests():
    expected = {"test/test_calibration_header_browser.py", "test/test_calibration_job_controls_browser.py"}
    for path in ("applications/calibration/web/styles.css", "applications/calibration/calibration_web.py"):
        assert set(browser_scope.targets([path])) == expected
    assert expected <= set(browser_scope.targets(["shared/web/components.css"]))
    assert expected <= set(browser_scope.all_targets())


def test_fleet_development_changes_include_independent_browser_flows():
    for path in ('applications/fleet/dev/sample/engine.py', 'applications/fleet/web/runtime.js'):
        found = browser_scope.targets([path])
        assert 'applications/fleet/test/test_feature_browser_flows.py' in found
        assert 'applications/fleet/test/test_sample_browser.py' in found


SAMPLE_CONSUMERS = {
    'applications/fleet/test/test_sample_browser.py',
    'applications/fleet/test/test_feature_browser_flows.py',
    'applications/fleet/test/test_browser_adapters.py',
    'applications/fleet/test/test_integrated_sample_browser.py',
}


def test_development_runtime_selects_sample_and_connected_host_consumers_only():
    expected = SAMPLE_CONSUMERS | {'operations/fleet/test/test_app_connected_browser.py'}
    for path in ('applications/fleet/dev/http_host.py', 'applications/fleet/dev/serve.py',
                 'applications/fleet/dev/connected.py', 'applications/fleet/dev/sample/engine.py',
                 'applications/fleet/dev/web/controls.js'):
        assert set(browser_scope.targets([path])) == expected, path


def test_sample_engine_and_shared_fixture_select_all_sample_consumers_only():
    for path in ('applications/fleet/test/test_sample_server.py',
                 'applications/fleet/test/test_sample_browser.py'):
        assert set(browser_scope.targets([path])) == SAMPLE_CONSUMERS, path


def test_development_markdown_does_not_select_browser_tests():
    for path in ('applications/fleet/dev/logs.md', 'applications/fleet/dev/index.md',
                 'applications/fleet/dev/progress.md', 'applications/fleet/dev/AGENTS.md',
                 'shared/web/index.md', 'shared/web/logs.md', 'shared/web/logs/2026/11/21-x.md',
                 'operations/fleet/logs.md', 'applications/fleet/web/AGENTS.md',
                 'applications/monitoring/README.md'):
        assert browser_scope.targets([path]) == [], path


def test_production_sources_and_unproven_app_tests_keep_fleet_coverage():
    for path in ('applications/fleet/web/runtime.js', 'shared/web/ui.js',
                 'operations/fleet/fleet/server/app.py', 'applications/fleet/test/test_connected_proxy.py'):
        found = set(browser_scope.targets([path]))
        assert set(browser_scope._expand('operations/fleet/test/*_browser.py')) <= found, path
        assert SAMPLE_CONSUMERS <= found, path


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
                     "test/test_fleet_console_browser.py", "middleware/robot_ui/pilot/test/test_pilot_browser.py",
                     "test/test_monitoring_browser.py", "integrations/simulation/gazebo/test/test_lane_live_view_browser.py"):
        assert expected in found


def test_a_changed_browser_test_selects_itself_and_unrelated_paths_select_nothing():
    assert browser_scope.targets(["test/test_games_board_browser.py"]) == ["test/test_games_board_browser.py"]
    assert browser_scope.targets(["docs/logs.md", "middleware/drive/planning/grid/goals.py"]) == []
    assert browser_scope.targets(["tools/land_browser.py"]) == []  # a module named *_browser.py is not a test


def test_windows_separators_are_accepted():
    found = browser_scope.targets(["middleware\\robot_ui\\pilot\\styles.css"])
    assert found and found == browser_scope.targets(["middleware/robot_ui/pilot/styles.css"])


def test_pilot_and_shared_styles_select_moved_lobby_tests_without_widening_omx():
    lobby = "middleware/robot_ui/pilot/test/test_lobby_browser.py"
    for path in ("middleware/robot_ui/pilot/styles.css", "shared/web/components.css"):
        assert lobby in browser_scope.targets([path])
        assert "middleware/robot_ui/pilot/test/test_recordings_browser.py" in browser_scope.targets([path])
    assert browser_scope.targets(["middleware/devices/omx/adapter/example.py"]) == [
        "middleware/devices/omx/adapter/test/test_pilot_sim_browser.py"
    ]


def test_every_scope_target_exists():
    for patterns in browser_scope.SCOPE.values():
        for pattern in patterns:
            assert browser_scope._expand(pattern), pattern


def test_learning_browser_tier_keeps_operator_training_separate():
    selected=set(browser_scope.targets(['learning/curation/perception/review_app_web/imitate.js']))
    assert 'test/learning/perception/test_imitation_browser.py' in selected
    assert not any('/operator_' in path or '_live_browser.py' in path for path in selected)
    assert browser_scope.targets(['test/learning/perception/operator_lerobot_study.py']) == []


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


def test_auth_entry_regression_is_selected_by_its_sources_and_the_full_registry():
    target = "test/learning/perception/test_learning_auth_surface_browser.py"
    for source in ("learning/curation/perception/review_app_web/accounts.js",
                   "learning/curation/perception/learning_rosy_accounts.py", "shared/web/component-controls.css"):
        assert target in browser_scope.targets([source])
    assert target in browser_scope.all_targets()


def test_empty_selection_exits_3_without_targets(capsys):
    assert browser_scope.main(["docs/logs.md"]) == 3
    out = capsys.readouterr()
    assert out.out == "" and "no browser tests" in out.err
    assert browser_scope.main(["test/test_games_board_browser.py"]) == 0
    assert capsys.readouterr().out.strip() == "test/test_games_board_browser.py"


def test_full_registry_keeps_browser_files_after_splitting_them():
    import subprocess
    from pathlib import PurePosixPath

    tracked = subprocess.check_output(
        ["git", "-C", str(browser_scope.ROOT), "ls-files", "*.py"], text=True).splitlines()
    # This file tests the selector/chunker itself, rather than a rendered page.
    unit_only = {"test/test_land_browser.py"}
    expected = {path for path in tracked if PurePosixPath(path).name.startswith("test_")
                and path.endswith("_browser.py") and path not in unit_only}
    everything = browser_scope.all_targets()
    assert not (expected - set(everything)), sorted(expected - set(everything))
    # D-1066: the CI share plus the lab share is the registry, and the lab share survives pr_land's splitting.
    import affected_browser
    import pr_land
    ci, lab = affected_browser.split(everything)
    assert sorted(ci + lab) == everything
    kept = [w for part in pr_land.split_by_ci_entry(["ROSY_RUN_BROWSER_TESTS=1", *lab])
            for w in part if w.endswith(".py")]
    assert sorted(set(kept)) == lab


def test_recovery_page_and_shared_styles_select_the_offline_browser_flow():
    for source in ("deploy/robot/pinky_pro/native/network_recovery_http.py",
                   "deploy/robot/pinky_pro/native/install-native-runtime.sh", "shared/web/components.css"):
        assert "test/test_network_recovery_browser.py" in browser_scope.targets([source])


def test_sim_sources_select_sim_browser():
    for path in (
        "learning/curation/perception/review_app_web/sim.js",
        "learning/curation/perception/sim_web.py",
        "shared/web/ui.js",
    ):
        assert "test/learning/perception/test_sim_browser.py" in browser_scope.targets([path])


def test_canonical_sources_select_canonical_browser():
    for path in (
        "learning/curation/perception/canonical_web.py",
        "learning/curation/perception/review_app_web/canonical.html",
        "learning/curation/perception/review_app_web/canonical.js",
        "learning/curation/perception/review_app_web/canonical.css",
        "contracts/learning/src/rosy/contracts/learning/omx_canonical.py",
    ):
        assert "test/learning/perception/test_canonical_browser.py" in browser_scope.targets([path]), path


def test_common_robot_tasks_select_real_browser_flow():
    expected = 'test/learning/perception/test_learning_tasks_browser.py'
    recovery = 'test/learning/perception/test_learning_task_recovery_browser.py'
    for source in ('learning_tasks.py', 'learning_tasks_web.py', 'review_app.py',
                   'review_app_web/tasks.js', 'review_app_web/tasks.html', 'review_app_web/learning.html'):
        assert expected in browser_scope.targets(['learning/curation/perception/' + source])
        assert recovery in browser_scope.targets(['learning/curation/perception/' + source])
    assert expected in browser_scope.targets(['learning/training/omx/experiment_center.py'])


def test_omx_archive_handoff_selects_http_named_browser_suites():
    expected = {'test/learning/perception/test_storage_omx_http.py',
                'test/learning/perception/test_storage_setup_http.py'}
    root = 'learning/curation/perception/'
    for source in ('storage_omx.py', 'storage_prepare.py', 'storage_web.py',
                   'review_app_web/storage-settings.js', 'review_app_web/omx-export.js',
                   'review_app_web/learning.html', 'review_app.py'):
        assert expected <= set(browser_scope.targets([root + source])), source
    assert expected <= set(browser_scope.targets(['learning/training/omx/experiment_catalog.py']))
    for target in expected:
        assert browser_scope.targets([target]) == [target]


def test_all_json_expands_the_actual_browser_registry_without_fake_changed_paths(capsys):
    import json
    assert browser_scope.main(["--all", "--json"]) == 0
    found = json.loads(capsys.readouterr().out)
    assert found == sorted({path for pattern in browser_scope.EVERYTHING for path in browser_scope._expand(pattern)})
    assert found and "tools/land_browser.py" not in found


def test_server_cell_file_maps_to_its_two_pages_and_other_server_files_keep_fleet():
    cell = ["operations/fleet/test/test_cell_app_browser.py", "operations/fleet/test/test_work_overview_browser.py"]
    assert browser_scope.targets(["operations/fleet/fleet/server/cell/cell_arm_jobs.py"]) == cell
    whole = set(browser_scope._expand("operations/fleet/test/*_browser.py"))
    for path in ("operations/fleet/fleet/server/sitemap/pipeline_routes.py",
                 "operations/fleet/fleet/server/work/work_routes.py"):
        assert whole <= set(browser_scope.targets([path])), path
    assert set(cell) < set(browser_scope.targets(["operations/fleet/fleet/server/cell/a.py",
                                                  "operations/fleet/fleet/server/app.py"]))


def test_fleet_sample_has_no_duplicates():
    assert len(browser_scope.FLEET_SAMPLE) == len(set(browser_scope.FLEET_SAMPLE))


def test_leaf_server_and_web_subprefixes_narrow_while_shared_and_root_assets_keep_fleet():
    assistant = set(browser_scope.targets(["operations/fleet/fleet/server/assistant/routes.py"]))
    assert assistant == set(browser_scope.FLEET_SAMPLE) | {"operations/fleet/test/test_assistant_browser.py"}

    cell = set(browser_scope.targets(["applications/fleet/web/cell/cell.js"]))
    assert set(browser_scope.FLEET_SAMPLE) <= cell
    assert {
        "operations/fleet/test/test_cell_app_browser.py",
        "test/test_fleet_workcell_observation_browser.py",
        "test/test_motor_health_ui_browser.py",
        "shared/web/test/test_component_kit_browser.py",
    } <= cell
    assert "test/test_site_map_browser.py" not in cell and "operations/fleet/test/test_assistant_browser.py" not in cell

    maint = set(browser_scope.targets(["applications/fleet/web/maintenance/host-services.js"]))
    assert set(browser_scope.FLEET_SAMPLE) <= maint
    assert {
        "operations/fleet/test/test_development_console_browser.py",
        "operations/fleet/test/test_task_page_compositions_browser.py",
        "test/test_host_recovery_browser.py",
    } <= maint
    assert "test/test_fleet_console_browser.py" not in maint

    whole_fleet = {p for pat in browser_scope.FLEET for p in browser_scope._expand(pat)}
    for full_path in (
        "applications/fleet/web/runtime.js",
        "applications/fleet/web/installation/install.js",
        "applications/fleet/web/devices/device-discovery.js",
        "applications/fleet/web/calibration/measured-calibration-view.js",
        "applications/fleet/web/shared/styles.css",
        "applications/fleet/web/sitemap/site-map.js",
        "operations/fleet/fleet/server/app.py",
        "operations/fleet/fleet/server/work/work_routes.py",
    ):
        assert whole_fleet <= set(browser_scope.targets([full_path])), full_path


def test_unit_test_modules_and_contract_version_do_not_trigger_unrelated_browsers(monkeypatch):
    assert browser_scope.targets(["middleware/core/api/core_api_web/api/contract_version.py"]) == []
    monkeypatch.setattr(browser_scope, "_is_contract_version_pin", lambda p: False)
    assert set(browser_scope.API_WEB) <= set(
        browser_scope.targets(["middleware/core/api/core_api_web/api/contract_version.py"])
    )
    monkeypatch.undo()

    assert browser_scope.targets(["shared/web/test/test_shared_dedupe.py"]) == []
    assert browser_scope.targets(["learning/training/omx/test/test_cell_bundle.py"]) == []

    theme_targets = set(browser_scope.targets(["shared/web/test/test_theme_browser.py"]))
    assert {"shared/web/test/test_theme_browser.py", "operations/fleet/test/test_fleet_header_browser.py"} <= theme_targets
    assert len(theme_targets) < 15

    g2_targets = set(browser_scope.targets(["middleware/robot_ui/robot/test/test_role_g2_browser.py"]))
    assert {
        "middleware/robot_ui/robot/test/test_list_row_confirm_browser.py",
        "middleware/robot_ui/robot/test/test_dashboard_entry_browser.py",
    } <= g2_targets

    assert "middleware/robot_ui/robot/test/test_remaining_workflows_browser.py" in browser_scope.targets(
        ["middleware/robot_ui/robot/test/test_panel_copy_evidence_browser.py"]
    )
    shared_expanded = {p for pat in browser_scope.SHARED for p in browser_scope._expand(pat)}
    assert shared_expanded <= set(browser_scope.targets(["shared/web/test/surface_registry.py"]))
