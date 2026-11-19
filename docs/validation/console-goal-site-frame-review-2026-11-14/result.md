# fix/console-goal-site-frame: D-430 independent review (2026-11-14)

Scope: the console site-map view sent site-frame x, y to `POST /api/fleet/robots/{id}/goal`, which forwarded them raw into the robot's own SLAM frame (the 2026-11-13 rosy_46 wrong-place bug; D-1003 had fixed only trips). Now the console adds `frame: "site"` in site view and the route converts with `robot_frame_goal`, or answers 409.

Reviewer: Claude subagent (read-only). Verdict: PASS.

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | LOW | `!view.map` is the right site-view test; a view switch during confirm cancels via `mapSnapshot`. Old cached clients still send raw (as before). | Accepted |
| 2 | PASS | Every failure path (no map, unreadable robot, DEGRADED/other-map site pose, not localized) is a 409; nothing falls back to raw. | — |
| 3 | MEDIUM | Converted at submit: a QUEUED goal keeps the frame of that moment; a robot reboot before dispatch would use the old frame. | Known limit, `shortcut:` comment in `_site_goal_in_robot_frame`; strict improvement over always-raw |
| 4 | LOW | A retried Idempotency-Key from a moved robot may yield `IDEMPOTENCY_CONFLICT` (fails safe). | Accepted |
| 5 | PASS | Other callers unchanged (`frame` defaults to None, only `"site"` allowed). | — |
| 6 | PASS | Yaw rotation correct. | Yaw assertion added to the test |

Host evidence (remote, committed HEAD): `test_console_goal_site_frame.py`, `test_server_app.py`, `test_task_api.py` 78 passed. Browser `test_console_card_trips_browser.py`, `test_fleet_console_browser.py`, `test_site_map_browser.py`: run cut by the local time limit after about 180 tests with no failure; the landing runs the full browser set. No device acceptance.
