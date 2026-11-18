# fix/fleet-real-site-pose: D-430 independent review (2026-11-13)

Scope: `berth_parking_routes.py`, `berth_parking_helpers.py`, `task_dispatch_helpers.py` and `map_pose_service.py` on branch `fix/fleet-real-site-pose`, from `main` 8b65ceaa0f to `27d01cb24f`.
`4694d03c21` and `27d01cb24f` tag the route and helper files as safety modules, so every branch commit touching them needs this review. Author: robot-ec (Claude session). Reviewers: Codex (`codex exec -s read-only`) and GLM 5.3 (opencode). Neither reviewer is the author.

## Why

On 2026-11-13, map clicks on the R site drove `rosy_46` to the wrong place. `POST /road-nav2` converted site goals to the robot's SLAM frame using a site pose it should not have used. It came from three sources:
- the `world_261026` preset pins and synthesized odometry;
- the robot's own SLAM pose;
- the constant (-0.411, 0.350).

`slam_toolbox` restarts with its origin wherever the robot booted. robot-b3's panel on `01988565d4` and `973faf9de9` also found that road-nav2 and berth-park failed open.

## Round 1, at 4694d03c21

**Codex: REJECT on all four commits.**
- A queued task was reported as dispatched.
- The console still fell back to a raw `/goal` after other road-nav2 errors.
- The preset pins remained for robots not on the auto-locate list.
- Physical berth-park reported success after a timeout or an emergency, and inserted zero odometry.
- The two helpers were not tagged as safety modules.

**GLM: APPROVE on all four**, with the same physical-park and queued residuals.

## Fix 27d01cb24f

The fix closes each point:
- The preset pins and synthesized odometry are removed for every robot.
- `dispatched` now means `accepted`. A queued task is reported as `queued`, and the console shows it as queued.
- The console never falls back to a raw `/goal`.
- Berth-park succeeds only on `BERTH_SUCCESS_REASONS`. A timeout reports `reverse_timeout`, there is no reverse after an emergency, and the pin no longer inserts odometry.
- `berth_parking_helpers.py` and `task_dispatch_helpers.py` are tagged as safety modules.

## Round 2, at 27d01cb24f

**Codex: APPROVE** `3d9a8ad496`, `a56cd55043`, `394ab97c79`, `4694d03c21` and `27d01cb24f`. All four findings are closed.

## Remote evidence

- **Remote pytest at 27d01cb24f:** fleet route, pose, guide, traffic, site policy, safety review and safety separation suites. 214 passed, 0 new.
- **Local checks:** each new test fails on the commit before its fix.

## Not covered

- The physical berth-park teleop runs outside the task ledger after a single trip check. This is the existing feature from `973faf9de9`.
- The berth console logs a good outcome without checking `accepted`.

Both are follow-up safety work for that feature. Codex judged that they do not block these commits. No device acceptance was done, and R's live hot-patched images are unchanged.
