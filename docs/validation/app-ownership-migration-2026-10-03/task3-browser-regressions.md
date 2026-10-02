# Task 3 browser regression inventory

Baseline Console/install source: `51f17c505`; HTTP checkpoint: `ab40eb56`. All other copied web assets and the exclusive HTTP fixture were equal. Baseline: **45 passed, 22 failed**. Candidate with three added session/origin cases: **48 passed, 22 failed**. Exact failing node-ID sets match: **0 new failures**.

The subsequent safety-selector repair ran only the two affected cases: **2 passed**, guard mutation **2 failed**, restored **2 passed**. The remaining **20 preexisting failures** stay open; no clean aggregate run or Task 3/browser acceptance is claimed. Keep this inventory when wiring page/token scopes and moving ownership flows. Do not skip or add known-failure entries to hide these failures. Recheck each case against the actual document and behavior; some installation cases currently open the operating document.

Raw comparison and baseline output: `X:/DevTemp/rosy-ui-ownership/task3-browser-comparison.json`, `task3-browser-baseline/baseline-full.txt`. Candidate IDs: `task3-browser-candidate.json`. Mutations: `task3-mutations/`. Those are temporary evidence; this inventory is the durable follow-up list.

| Exact node ID at HTTP checkpoint | Follow-up |
|---|---|
| `test/test_fleet_console_browser.py::test_goal_is_unavailable_when_safety_is_unknown_or_stopped[None-\uc815\ubcf4 \uc5c6\uc74c-\uc548\uc804 \uc0c1\ud0dc\ub97c \ud655\uc778\ud560 \uc218 \uc5c6\uc5b4]` | FIXED: stable safety fact/translated value; 2 green, guard mutation red |
| `test/test_fleet_console_browser.py::test_goal_is_unavailable_when_safety_is_unknown_or_stopped[safety1-E-STOP-\ube44\uc0c1\uc815\uc9c0\uac00 \ud65c\uc131\ud654\ub418\uc5b4]` | FIXED: stable safety fact/translated value; 2 green, guard mutation red |
| `test/test_fleet_console_browser.py::test_holding_formation_enables_resume_and_warns` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_discovery_read_loss_removes_old_device_addresses_and_recovers` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_expired_scanner_lease_raises_an_alarm_and_clears_on_return` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_console_fits_the_declared_viewport` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_fleet_control_groups_are_semantic_subheadings` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_robot_enrollment_panel_enrolls_by_screen_code` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_enrollment_dialog_leaves_the_fleet_stop_live` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_unenroll_is_a_quiet_row_action_confirmed_by_name` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_rectification_controls_are_accessible_source_scoped_and_reset` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_rectification_direct_manipulation` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_wide_header_keeps_every_item_on_one_line` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_single_column_tier_puts_exceptions_before_the_map_and_formation_last[390-844]` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_single_column_tier_puts_exceptions_before_the_map_and_formation_last[320-568]` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_approval_takes_the_phone_code_and_shows_the_mutual_check` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_reject_and_revoke_are_quiet_row_actions_confirmed_by_name` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_lists_without_actions_for_viewers_and_the_shared_token[vic-viewer]` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_lists_without_actions_for_viewers_and_the_shared_token[site-console-operator]` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_camera_section_is_calm_when_fleet_has_no_pairing` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_offline_robots_say_why_and_each_move_asks_for_the_screen_code` | OPEN: baseline and HTTP checkpoint both fail |
| `test/test_fleet_console_browser.py::test_viewer_sees_reasons_but_no_live_move_buttons` | OPEN: baseline and HTTP checkpoint both fail |
