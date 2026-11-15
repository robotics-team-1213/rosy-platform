# fix/fc-fleet-frame-charge-bundle: D-430 Safety Separation & REST Mirror Review (2026-11-15)

- **Reviewer**: Independent read-only `research` subagent (`af2075f6-c56f-4543-a1de-9d1d1d13f252`)
- **Verdict**: `APPROVE`
- **Target**: `ab02e1f1af` + `ConsoleGoalRequest(GoalRequest)` split in `D:\Temp\wt-fc-bundle` (on `fix/fc-fleet-frame-charge-bundle` / `f630254112` rebased onto `main` `f1868b9b06`)

## Summary of Findings & Fixes
1. **D-430 Safety Boundary Separation (`SAFETY_CAP = 27` preserved)**:
   - `operations/fleet/fleet/server/ledger/berth_parking_routes.py`: scenario and navigation dispatch error handling extracted to `operations/fleet/fleet/server/ledger/berth_parking_scenario.py` (`dispatch_nav_target`, `install_berth_scenario_routes`). `berth_parking_routes.py` stays in `safety_modules` with zero `KNOWN_SAFETY_VIOLATIONS` entries and fails closed with HTTP 503 (`DISPATCH_UNAVAILABLE`) if injected `dispatch_nav` is `None`.
   - `operations/fleet/fleet/server/ledger/task_dispatch_routes.py`: `_site_goal_in_robot_frame` extracted to `operations/fleet/fleet/server/trips/trip_geometry.py` (`site_goal_in_robot_frame`) and injected via `convert_site_goal` (fails closed with HTTP 409 `SITE_POSE_UNKNOWN` if `None` or unlocalized).
   - `operations/fleet/fleet/server/app.py`: wires `convert_site_goal=site_goal_in_robot_frame`, `dispatch_nav=dispatch_nav_target`, and `install_berth_scenario_routes`.
   - Preserved identically: `require_named_operator`, `trip_refusal`, `Idempotency-Key` enforcement, single dispatch path (no simulated fallback), and `_execute_physical_berth_park`.
2. **D-940 REST Request Mirror Alignment (blocking finding fixed)**:
   - Subagent initially returned `REJECT` because adding `frame: Optional[Literal["site"]] = None` directly onto `GoalRequest` broke `test/architecture/test_rest_model_mirror.py`, `test_lane_route.py`, and `test_task_contract_docs.py`.
   - Fixed by keeping `GoalRequest` (`{x, y, yaw}`) as the strict CORE mirror and adding `ConsoleGoalRequest(GoalRequest)` (`frame: Optional[Literal["site"]] = None`) on `POST /api/fleet/robots/{robot_id}/goal` in `task_dispatch_routes.py`, with `test_console_goal_site_frame.py` and `test_server_app.py` updated to `ConsoleGoalRequest`.
   - Subagent re-reviewed the fix and returned `VERDICT: APPROVE`.

## Local Evidence (`D:\Temp\wt-fc-bundle`)
- `pytest test/architecture/test_rest_model_mirror.py test/architecture/test_safety_separation.py test/architecture/test_known_lists_freeze.py test/architecture/test_platform_parts.py operations/fleet/test/test_console_goal_site_frame.py operations/fleet/test/test_task_contract_docs.py -q`: **45 passed**
- `pytest operations/fleet/test/test_server_app.py -k test_goal_openapi_contract_exposes_only_domain_intent_fields -q`: **1 passed** (48 deselected)
- `pytest operations/fleet/test/test_berth_parking_routes.py -q` (prior to `ConsoleGoalRequest`-only edit): **10 passed**
- `tools/harness/rosy_harness.py lint`: **0 error(s), 49 warning(s)**
- Full `test_fleet_route_guards.py` and `test_server_app.py` (remaining cases using `rosy.contracts`) deferred to `tools/land.py` remote pytest host.
