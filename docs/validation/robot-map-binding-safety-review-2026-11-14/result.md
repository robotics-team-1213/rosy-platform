# feat/robot-map-binding (D-1022): D-430 independent review (2026-11-14)

Scope: the whole branch from `main` 8b65ceaa0f. The safety-tagged files are `middleware/core/gateway/core/bridge/map_observation.py` and `middleware/core/services/core_features/state/manager.py`. They only add `map_grid_id` reporting. The review also covered the Fleet goal path (`trip_geometry.py`, `trip_steps.py`), because that path decides which frame a goal is sent in.

Author: robot-ec (Claude session). Reviewers were a Claude subagent, Codex (`codex exec -s read-only`) and GLM 5.3 (opencode). None of them is the author.

## Round 1

**Claude: PASS.** Findings:
- A holdout could repeat a fit point.
- `map()` returning None gave a 500.
- `compute_road_plan` is not covered; this is already listed as a limit in the ADR.

**GLM: PASS.** Low findings:
- An unreachable robot read as `GRID_CHANGED`.
- `save_map` cleared the grid id.
- In a square arena, the holdout is the only guard against a 90° error.

**Codex: BLOCK.**
- After a goal was sent, revoking the binding did not stop the trip.
- A port that only declared one frame bypassed the binding.
- The wall proposal ignored `origin.yaw`.
- A repeated holdout was accepted.

## Fixes

| Change | Test |
|---|---|
| A holdout that repeats a fit point is refused | `test_a_holdout_that_repeats_a_fit_point_is_refused` |
| An empty map gives 409 `NO_WALLS` | — |
| `origin.yaw` is applied to the occupied cells | `test_occupied_cells_follow_a_rotated_grid_origin` |
| Under `map_binding_required`, a port without robot state stops | `test_a_required_binding_stops_a_port_that_only_declares_one_frame` |
| A revoked or superseded binding stops the trip and cancels the goal | `test_revoking_the_binding_under_a_running_goal_stops_and_cancels_it` |
| `matching_fit` checks LOCALIZED first | — |
| `set_map_id` keeps the grid id when none is given | — |

## Round 2

**Codex: BLOCK.**
- (a) A grid swap during a running goal was not seen, because only the binding id was compared.
- (b) The binding branch did not check `site_pose.map_id`.

Fixes and replies:
- **(a) Fixed.** `_recheck_binding` reruns `matching_fit` on fresh robot state every period. Test: `test_a_robot_that_loads_another_grid_under_a_running_goal_is_stopped`.
- **(b) Rebutted.** With a binding, `site_pose` does not enter the goal. The goal is a point of the plan segment, version-checked against the active site map.
- **D-989 allowlist.** The full fleet suite also found that the binding read used `driving_pose`, which is outside the D-989 allowlist. It now uses `arbitrated_pose`.

## Round 3

**Codex: PASS.** Finding (b) is withdrawn ("no path from `site_pose.map_id` to the bound goal value"). Finding (a) is resolved.

## Evidence

The remote host tests are listed in the ADR's verification section. In the full fleet and CORE suites, every NEW id was already in `rosy-main-red.jsonl` on main 8b65ceaa0f. The exception was the D-989 allowlist failure above, which is now fixed.

The physical robot was not tested, because it is tethered by its cable.
