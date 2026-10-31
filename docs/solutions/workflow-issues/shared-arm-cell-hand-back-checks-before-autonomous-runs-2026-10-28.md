---
title: A shared arm cell must be checked before every autonomous run, because the last user may have moved the camera, the camera port or the caps
date: 2026-10-28
category: workflow-issues
module: deploy/robot/omx (cell_preflight.py, commissioning_view.py, commissioning_limits.py, cell_pivot.py, episode_recorder.py, cell_pinch.py)
problem_type: workflow_issue
component: development_workflow
symptoms:
  - "the viewer's gripper camera answered 503 and the camera log said 'selected camera is unavailable'"
  - "record_session refused: follower caps are not the commissioning baseline"
  - "the scene in the top view sat 20-45 px off and about 7 degrees rotated against this morning's frames"
  - "a pivot beside the Pinky body saved a 6 cm 'bias' (radius 70 mm, rms 13.6 mm)"
  - "the wrist reference servo moved 55-58 mm and refused: the wrist camera faced the arm base, no finger in view (2026-10-29)"
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

7. **The wrist camera was turned to face the arm's base (2026-10-29).** In frames from 10-27 and 10-28, both finger pads were at the bottom of the image with the box between them. On 10-29 neither finger was in view, and the camera looked back at the board and the arm base.
   - What went wrong:
     - The reference servo "aligned" on the long containers on the board. It moved 55–58 mm and was refused.
     - `cell_wrist.finger_pads` also found two "pads" in the turned view (the base plate and cables), so it cannot judge the mount by itself.
     - Preflight checks only the top camera, so it passed.
   - How it was found: a probe hover over the target at two heights and three yaws, with the wrist frames compared against 10-28 frames.
   - Fix in code:
     - `cell_pinch` stores the pad pixels of the last passing check as a mount signature (`pinch-mount-<arm>.json`).
     - Pads more than `pinch.mount_tol_px` from it refuse with "wrist camera moved".
     - Until the first pass on a correctly mounted camera, only a person can confirm the mount.
   - Rule: after another person or session has used the cell, look at one wrist frame before turning on any wrist-based alignment (`wrist.ref_servo`, `pinch.enabled`). Both fingers must be visible at the bottom of the image. If they are not, turn those off and fix the mount first.

8. **The room lights were off (2026-10-30, 00:40).** Every top frame was black. Raising the exposure to 200 ms and the gain to 7 changed nothing (mean 1.4), and the wrist camera read 0.1. So it was the room, not the camera.
   - It looked like a camera fault: the top camera had also been left in manual exposure. Setting it back to auto changed nothing either.
   - Fix in code: `cell_preflight.lights` checks each frame's mean against `preflight.min_mean` (15; a lit cell reads about 140). `cell_auto_pick` runs it before observing and refuses with "the room lights are off or the lens is covered".
   - Verified on the real cell: in the dark, a board → belt dry run was refused with that reason, before any motion.
   - To tell a dark room from a stuck exposure: set manual exposure high (`v4l2-ctl -c auto_exposure=1 -c exposure_time_absolute=2000 -c gain=7`) and grab a frame. A dark room stays black. Set it back to `auto_exposure=3` afterwards.
9. **A dim room, and the top camera's own auto exposure stopped short (2026-10-30, 12:20).** The top frame read mean 21 with the camera in auto at exposure 3000, while the wrist camera read 145. So the room was lit enough and the top camera was not using it.
   - The camera's exposure is near linear in its own units: manual 10000, 20000 and 33000 at gain 7 gave 61, 105 and 148. Its auto mode did not go past 3000. Switching to manual and back to auto once un-stuck it (33000, mean 156), so auto is not reliable either way.
   - Mean 21 passed the lights check (15), and detection on it was not trustworthy. A wide band is not enough either: at mean 106 the board box split in two and matched nothing; detection was tuned near 140.
   - Fix in code: `cell_preflight.expose` sets manual exposure for a camera that names its `device` in the config (use the `/dev/v4l/by-id/` path: `/dev/videoN` numbers change). Each step scales exposure by `preflight.target_mean / mean` (140 ± `preflight.mean_band` 15), up to `preflight.max_exposure`. Then the lights check runs. `cell_auto_pick` calls `cell_preflight.ready`.
   - Verified on the real cell: from manual 3000 (mean 28), one step reached mean 104 with the first band and 129 with the second (exposure 18180), about 1 s.
   - A box the catalogue matched at one brightness and not at another is a sign it is not a catalogue object. The square board box (about 45 × 50 px) read as `container-2` at mean 156 and as nothing at 106 and 129.

## The rule (code, not memory)

Run `cell_preflight.py --config <cell config>` before an autonomous run. It is read only. It fails if:

- a camera label is not fresh,
- the top view moved more than `--max-shift-px` against the map's saved reference frame (`preflight.reference_top`; save one right after mapping),
- or another arm session is running,
- or a frame is darker than `preflight.min_mean`.

`cell_auto_pick` first sets the exposure of each camera with a `device` (`cell_preflight.ready`), then runs the lights check.

Caps are left to `record_session`'s own refusal, and the fix is printed.

## Still open

After the camera moved, the side-face correction (`cell_objects.top_face`, which uses `cameras.top.center_px` and `height_m`) under-corrects. A 1-cell on the tray measured 43.9 mm long against a 44 mm limit.

The field catalogue copy raises that object's length tolerance to 16 mm. The 2-cell's lower bound stays at 46 mm, so the two remain separable.

The camera's principal point and height after the re-mount are not measured. Measure them, rather than widen tolerances further.
