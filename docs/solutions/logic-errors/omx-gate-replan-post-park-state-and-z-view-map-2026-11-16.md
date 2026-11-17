---
title: OMX Gate replan must refresh state after slow park and accept z_view destination maps with parallax geometry
date: 2026-11-16
category: logic-errors
module: deploy/robot/omx (cell_transfer, cell_auto_pick_plan, cell_auto_evidence)
modules: [deploy, test]
problem_type: logic_error
component: cell_transfer_and_planning
severity: high
symptoms:
  - "`Gate.act('load <replan>')` wrote `-001` (`replanned`), rotated `Gate.assessment` to the new library, then returned `ok=False` (`held: session_changed`) without sending `load` to `chunk_runner`, making the recovery `park` fail with `checked command targets another library`"
  - "`cell_auto_pick` held `arm_b` (`pallet-l0`) with `held: destination ROI or fine map missing` because real hardware remaps include `\"z_view\"` alongside `\"homography\"`"
root_cause: stale_pre_park_state_and_overbroad_z_view_reject
resolution_type: code_fix
tags: [omx, gate, replan, max_gap_s, z_view, parallax, hardware-verified]
applies_when:
  - "Modifying `Gate.act` replan transitions in `deploy/robot/omx/cell_transfer.py` where `MAX_GAP_S = 0.5` expires pre-park timestamps"
  - "Validating destination map usability in `deploy/robot/omx/cell_auto_pick_plan.py` or `cell_auto_evidence.py`"
---

# OMX Gate replan post-park state refresh and z_view destination map gate

## Root causes

- `Gate.act` sampled `state = self.cell.act("state")` before executing `parked = self.act("park")`. On real `arm_b` hardware, folding home from `above_pick` takes several seconds (`> MAX_GAP_S = 0.5 s` in `guarded_device.py`). After updating `self.assessment = fresh`, `same_session(state, self.assessment)` rejected the stale pre-park `state["t"]`, returning `held: session_changed` before `self.cell.act("checked ... load ...")` ever ran (`cell_transfer.py`). Mock cells whose `park` ran instantaneously hid this bug in unit tests.
- `cell_auto_evidence.py` and `cell_auto_pick_plan.py` rejected any destination record containing `"z_view"`, even though `cell_calibrate.py remap` writes `"z_view"` on real `arm_a`/`arm_b` maps and `cell_object_pose.to_mm` handles 3D height parallax whenever `cameras.top` provides `center_px` and `height_m`.

## Solution

- Refresh `state = self.cell.act("state")` immediately after the replan transition (`self.transitions += 1`) before `same_session(state, self.assessment)` in `deploy/robot/omx/cell_transfer.py`, with a simulated slow-park regression test (`test_commissioning_replan_refreshes_state_after_slow_park`) in `test/test_omx_cell_transfer_holding.py` (kept out of `test/test_omx_cell_auto_pick.py` to respect the 1500-line D-766 test file cap).
- Extract shared `dest_map_usable(config, record)` in `deploy/robot/omx/cell_auto_pick_plan.py` (reused by `deploy/robot/omx/cell_auto_evidence.py`) requiring `cameras.top.center_px` and `height_m` only when `"z_view" in record`, covered by `test_dest_map_usable_accepts_z_view_only_with_parallax_geometry`.

## Verification & open follow-up

- Remote pytest (`294 passed in 6.71s`, `D:\DevTemp\omx-hotfix-stack-16\run-1.txt`), `safety_review.py`, and `size_range.py` passed on `2c56cd7b12` before adding this doc.
- Live `arm_b` verification (`run 20261116T092935Z` on deployed `omx-tools-2c56cd7b12`) confirmed both fixes end-to-end: `pallet-l0` cleared verification (`map_pose_check ok: true`, no `z_view` hold), replan `-001 -> -002` loaded `b73648fa...` cleanly (`ok: true`), and `arm_b` reached and descended at `above_pick`.
- Unresolved hardware issue (not claimed fixed): in `-002` at `[0.050, -0.2029]` (right side of `temp_plate_b-l1`, using the `-17.2, 11.3 mm` left-edge `pivot-near` bias ~80 mm away), `wrist` was skipped for tight finger room (`[50.5, 19.8] mm`) and `descend_pick` hit contact followed by a `wrist_flex >5 deg` following error during `retreat`, opening an incident hold on `arm_b` requiring physical inspection before torque ON.
