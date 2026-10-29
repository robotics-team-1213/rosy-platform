---
title: A shared arm cell must be checked before every autonomous run, because the last user may have moved the camera, the camera port or the caps
date: 2026-10-28
category: workflow-issues
module: deploy/robot/omx (cell_preflight.py, commissioning_view.py, commissioning_limits.py, cell_pivot.py, episode_recorder.py)
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "the viewer's gripper camera answered 503 and the camera log said 'selected camera is unavailable'"
  - "record_session refused: follower caps are not the commissioning baseline"
  - "the scene in the top view sat 20-45 px off and about 7 degrees rotated against this morning's frames"
  - "a pivot beside the Pinky body saved a 6 cm 'bias' (radius 70 mm, rms 13.6 mm)"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: high
tags: [omx, arm-s, shared-cell, camera, calibration, preflight, recording]
applies_when: "arm S (or any arm) runs autonomously after another person or session has used the same cell"
---

# A shared cell: check before an autonomous run

On 2026-10-28 another person used the cell between our runs. Afterwards, every pre-existing assumption was wrong in a different way. None of it showed up as an error until we looked for it.

## What changed, and how it showed

1. **The top camera was re-mounted.** ORB matching against an earlier frame gave a homography of about 7° rotation, about 5 % scale and a 20–45 px shift (351 inliers). Every map and bias measured before that was stale.
   - Fix: remap with the empty jaws (`layout_map_v2.py` grid, 11 marks, LOO mean 6.3 mm).
   - Then re-pivot on plain floor: bias (4.2, −2.5) mm, rms 2.5 mm.
   - The image-space regions (`surface_px`, `auto_roi`, ROIs in scripts) were carried over with the same image homography and checked by drawing them on the frame.
2. **The gripper camera moved to another USB port and channel.** `omx-camera-front.env` points at a `by-path` port that was now empty. The gripper camera served as `/arm_a_wrist_camera` from its `by-id` device, so the viewer's `front` went stale.
   - Fix: a viewer drop-in (`rosy-omx-camera-view.service.d/arm-s-wrist-front.conf`) maps label `front` to `/arm_a_wrist_camera/image_raw`. That keeps `/frame/front.jpg` and the dataset feature `observation.images.front` unchanged. The other services were not touched.
3. **The follower caps were left raised.** `record_session.py` refuses to start in that state.
   - Fix: `commissioning_limits.py --baseline` with torque OFF. It verified PWM 20 on all six motors.
4. **A pivot next to a tall object was garbage, and it was saved.** Marks beside the Pinky body gave radius 70 mm and rms 13.6 mm.
   - Fix: `pivot_calibrate` now refuses a circle outside `pivot.radius_lo_mm`–`radius_hi_mm` (12–40) or above `pivot.max_rms_mm` (5).
   - Run pivots on plain surface. A raised surface next to a tall object borrows the plain-floor bias until place-and-look (`learn_bias`) measures its own.
5. **Raw episodes were saved with no images.** While the other session held the cameras, every frame request answered 503.
   - Fix: an episode missing any camera is not kept (`result.json` `kept: false` with the reason).
6. **The LeRobot conversion had never run for real.** The remote test hosts have no lerobot, so the conversion test is skipped. A dry run on the Fleet PC found a feature-shape bug (`[6]` vs `(6,)`).
   - Fix: the conversion now works. Run that dry run on the arm host after changing `convert`.

## The rule (code, not memory)

Run `cell_preflight.py --config <cell config>` before an autonomous run. It is read only. It fails if:

- a camera label is not fresh,
- the top view moved more than `--max-shift-px` against the map's saved reference frame (`preflight.reference_top`; save one right after mapping),
- or another arm session is running.

Caps are left to `record_session`'s own refusal, and the fix is printed.

## Still open

After the camera moved, the side-face correction (`cell_objects.top_face`, which uses `cameras.top.center_px` and `height_m`) under-corrects. A 1-cell on the tray measured 43.9 mm long against a 44 mm limit.

The field catalogue copy raises that object's length tolerance to 16 mm. The 2-cell's lower bound stays at 46 mm, so the two remain separable.

The camera's principal point and height after the re-mount are not measured. Measure them, rather than widen tolerances further.
