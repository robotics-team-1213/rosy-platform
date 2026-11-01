---
title: Arm S picks failed on a scene that had changed, a flipped wrist view and a tray rim (2026-10-27)
date: 2026-10-27
updated: 2026-10-28
category: runtime-errors
module: deploy/robot/omx (cell_scene.py, cell_observe.py, cell_calibration.py, touch_survey.py)
problem_type: runtime_error
component: perception
symptoms:
  - "two pick attempts aimed at the old box position; the fingers hit a tray rim and cables"
  - "wrist_roll jumped +61 -> -34 between two wrist views 2 cm apart and the visual servo diverged"
  - "open jaws (56) landed on a yellow tray rim about 2 cm above the box top four times"
  - "wrist centroid servo never converges"
root_cause: stale_scene_and_missing_hand_eye
resolution_type: code_fix
severity: high
tags: [omx, arm-s, top-camera, wrist-camera, calibration, touch-survey]
applies_when: "a pick uses a map or detection made before a session restart, a hub reconnect or a person touching the cell; or a wrist-camera view is planned; or jaws open near a tray"
---

# Stale scene, wrist roll flip, tray rim, missing hand-eye (arm S, 2026-10-27)

## 1. The scene was stale (resolved in code)

After the USB hub reconnect the top camera had been moved and boxes rearranged. Two picks used the old box position. Rule: after a session (re)start, a reconnect or any human intervention, observe again before a target from an older observation is used.

Code: `cell_scene.scene_check`, called by `cell_observe.map_check(config, found, calibration)` in `cell_pipeline.move`. It refuses, with the reason, a detection (`observed`) or a map (`measured`) older than `config["scene_since"]`, and a map whose `camera_id` differs from `config.cameras.<name>.id`. The seat then proposes a re-map; moving still needs a person at the switch. Limit: `scene_since` is written by the operator or session start; nothing sets it automatically yet, and old map files without `camera_id` skip the identity check. Test: `test/test_omx_cell_scene.py`.

## 2. Symmetric jaws flipped the wrist camera (resolved in code, not yet wired)

The IK may pick yaw or yaw+180; the wrist camera rides on the jaws, so the view turned 180 degrees and the servo chased the wrong way. A roll near its limit forced the flip. `cell_scene.view_yaw` picks the equivalent yaw (yaw+180, and yaw+-90 for a square box) nearest the previous roll and prefers ones inside the limit margin. It is a pure helper; the wrist-view planner (the session script) must call it, which is open.

## 3. Touch localization (worked; helper added; one hazard)

Pairing two touched box positions with their top-camera pixels gave a local scale that found a moved box with one touch. `cell_calibration.anchored(h, pairs)` does that (2 or more pairs; keeps the base map's turn, takes scale and offset from the touches). Touch-probing light empty boxes pushes them (two boxes moved); a top-down press on a box top centre does not. A free descent that ends low beside objects is dangerous if the session drops, so `touch_survey` rises right after a descent that touched nothing (already fixed).

## 4. Wrist hand-eye (UNRESOLVED)

The profile's wrist reference (cx 347, cy 204) no longer matches the camera. Closed fingers cover the reference pixel and open fingers hide part of the box, so a centroid servo without hand-eye calibration does not converge. Next step: marker-based hand-eye calibration (a marker on the floor, position confirmed by touch, photographed from several poses). Nothing here is solved.

## 5. Tray rim (partly resolved)

`cell_scene.fixture_clear(data, x, y, z, yaw, open_m)` checks the open fingertips at grasp height against the fixture heights stored in `cell_calibration` surfaces. Not wired into the planner: the jaw opening direction relative to yaw and the opening in metres are unmeasured on the arm, and it only knows touched points. TODO in the plan doc.

## Next time

- Write `scene_since` whenever a person has been in the cell, before the next pick.
- Choose first picks away from fixtures; the tray rim is touched-in, but open jaws are wider than the box.
- Hub failure recovery is in `omx-guard-stale-health-sample-drops-held-arm-2026-10-25.md`.
- Evidence: Fleet PC session records and wrist/top frames of 2026-10-27; plan `Rosy/docs/superpowers/plans/2026-10-27-arm-s-coordinates-first.md`.

## Addendum 2026-10-28: top-camera pixel, refusal reading, misses, moved camera, tray reach

No grasp had succeeded when this was written. Status per item is stated honestly.

### 6. The visible "gripper" is the wrist servo, not the jaws (worked around; not coded)

From the top camera the thing that looks like the gripper is the wrist servo (white label), about 10 cm above the jaw tips. The camera sees it obliquely, so its pixel is 2-3 cm from the jaws' floor position except near the image nadir. Targets estimated from the wrist pixel at hover height put touches 1.5-3 cm off, repeatedly.

Fix that worked: press the closed jaws onto known board points near the image centre (a touch, so the gripper is at board height) and read the gripper pixel there; fit pixel to arm x, y from 4 such points (residual about 4 px). Status: resolved by procedure in the session, not a repo helper yet. Caveat: an automatic detector that took the farthest changed pixel from the base picked cables, not the gripper. The pixel must be the gripper, checked visually or by a proper detector; do not trust the heuristic.

### 7. OUTSIDE_WORKSPACE was misread (resolved: reading rule)

A planner refusal OUTSIDE_WORKSPACE was taken as "behind the base is unreachable". The real cause was a touch bottom of z 0.0, below workspace_min z 0.005. The workspace is x, y in [-0.28, 0.28]; behind-base targets plan (pan up to about 149 degrees, joint1 limit 2.6 rad). Rule: read the coordinates in the refusal, the z first, before concluding anything about reach.

### 8. A miss is not free (unresolved: no code guard)

Every touch that landed beside the light cube pushed it. It moved three times and finally left the board edge. After each miss, re-check the top camera before the next touch. Nothing enforces this; it is session discipline only. A guard (re-observe after a touch whose contact was not on the target) is a TODO.

### 9. The camera was moved without any signal (unresolved)

The top camera was physically moved during the USB hub reconnect. Every earlier map (Pinky local, belt, anchored scale) became invalid and nothing flagged it. This is the gap in section 1: `cell_scene.scene_check` compares `camera_id`, which does not change when the camera is bumped. TODO: make the camera identity include its pose (for example, reference marker or fixed board points re-seen and compared to the map within a tolerance) and refuse maps when it differs. Until then, re-fit the pixel map (section 6) after any hub reconnect or visit to the cell.

### 10. Pinky-tray container is out of top-down reach (unresolved)

Straight-down reach at the tray is limited by the wrist: the maximum top-down z is 0.114-0.118 at r 0.227 and 0.094-0.098 at r 0.242. A container centred near r 0.25 with its top at about 0.11 cannot be reached top-down. It needs repositioning closer to the base or a tilted grasp. Neither is done yet.

### Next time (addendum)

- Calibrate pixel to arm with closed-jaw touches near the image centre, and verify the pixel is the gripper by eye.
- On a planner refusal, quote its coordinates (z first) before diagnosing reach.
- After a miss or any hub reconnect, observe again before the next touch.
- Check top-down reach (z versus r) before placing a container.
