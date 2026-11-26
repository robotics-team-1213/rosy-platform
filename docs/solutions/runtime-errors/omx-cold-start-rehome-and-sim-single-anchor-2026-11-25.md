---
title: Cold-start auto_pick held on rehome_stopped (unbound FifoCell profile) and MuJoCo single-anchor 6-DoF camera drift
date: 2026-11-25
category: runtime-errors
module: deploy/robot/omx (cell_auto_setup.py, cell_area_pick_cli.py), tools/sim/omx_real2sim_comp.py
problem_type: runtime_error
component: omx-cell-and-sim
symptoms:
  - "Cold-start auto_pick on arm_s exited 1 with 'held: rehome_stopped' ('elbow_flex: live state refused after jog' / 'runner session changed or could not be confirmed') whenever torque-OFF droop exceeded SETTLE_TOL (3.0 deg)"
  - "Subsequent auto_pick exited 1 with 'held: audit_unavailable' until attempts.pending.json from the held rehome attempt was reconciled to receipts/"
  - "MuJoCo stack --pick-vision --belt-skew --choice container_colours=multi passed 1/9 with camera_comp reporting anchors_used=1 and injecting +15.6 mm eye_shift_mm on a nominal camera"
root_cause: unbound_profile_and_underdetermined_6dof_fit
resolution_type: code_fix
severity: medium
tags: [omx, rehome, session_id, operating_profile, attempts-pending, mujoco, real2sim, anchors]
applies_when: "FifoCell callers omit operating_profile binding during pre-work jogs, or 6-DoF extrinsic optimization runs with fewer than two anchors"
---

# Cold-start `rehome_stopped` (`FifoCell` missing `operating_profile`) and single-anchor 6-DoF camera drift

## Symptoms
1. On cold start of `arm_s` (`POST /jobs/auto_pick`), gravity drooped `elbow_flex` to `54.73 deg` vs `home[2] = 50.0 deg` (`> SETTLE_TOL = 3.0 deg`). `rehome_before_work()` sent an unchecked `jog elbow_flex.pos -4.0`.
2. `chunk_runner_commands.py` (`verb not in ("checked", "state", "stop")`) rotated `operating_context.session_id`, causing `cell_unwedge._home_state()` to refuse the post-jog status (`held: rehome_stopped`).
3. Because `gate.blocked` became `True`, `ReplanLedger.record_open_hold()` kept `attempts.pending.json` on disk; the next `auto_pick` failed at `cell_attempts.begin()` (`open("x") -> FileExistsError`) with `held: audit_unavailable`.
4. Separately, running Stage 1 MuJoCo `omx_two_arm_teacher.py run stack --pick-vision --belt-skew --choice container_colours=multi` passed only `1/9` steps (`final poses ok 2/9`): `omx_real2sim_comp.calibrate_top_camera()` solved 6-DoF camera extrinsics from `anchors_used = 1` (belt only, 3 scalar equations), adding a spurious `+15.6 mm` shift on top of `0.49..0.87 mm` raw contour accuracy.

## Root Cause
- **`deploy/robot/omx/cell_auto_setup.py` & `cell_area_pick_cli.py`:** Unlike `cell_pipeline.py` (`bind_pipeline` + `FifoCell(..., operating_profile=...)`), both entrypoints constructed `FifoCell(io, cameras)` without `operating_profile`, so pre-work `rehome_before_work` jogs were sent unchecked and rotated `session_id`.
- **`tools/sim/omx_real2sim_comp.py`:** `calibrate_top_camera()` returned nominal only when `n_anchors < 1`, allowing an underdetermined 1-anchor (`3`-equation) 6-DoF fit to hallucinate `eye_shift_mm = [9.4, -1.0, 0.9] mm`.

## Fix
- Extracted `cell_auto_setup.fifo_cell(config, cameras)` so both `cell_auto_setup.open_cell()` and `cell_area_pick_cli.main()` call `cell_robot_profile.bind_pipeline(config)` and pass `operating_profile` to `FifoCell` whenever `operating_profile_path` is configured (preserving 2-arg mocks when unset).
- Updated `omx_real2sim_comp.calibrate_top_camera()` to require `n_anchors >= 2` before running the 6-DoF extrinsic optimizer (`n_anchors < 2` returns `cam_nom` with `moved=False`).
- Added unit tests in `test/test_omx_cell_auto_pick.py`, `test/test_omx_area_pick_job.py`, and `test/test_omx_real2sim.py`.

## Verification & Recovery
- Hardware workaround verified prior to deploy: running `POST /jobs/home` (which uses `cell_pipeline.py` with `operating_profile`) settled `elbow_flex` within `3.0 deg` and eliminated `rehome_stopped`; reconciling verified terminal `attempts.pending.json` (`20261124T151234Z-001` already recorded in `attempts.jsonl`) to `receipts/` cleared `audit_unavailable`.
- Remote test-PC pytest (`tools/remote/remote_pytest.py`) and Model PC MuJoCo re-run record post-fix test pass counts.
