---
title: Carrying a container from the floor to the Pinky tray hid four blockers outside the grasp itself
date: 2026-10-28
category: logic-errors
module: deploy/robot/omx (cell_objects.py, cell_auto_pick.py, cell_push.py, cell_surface.py, grasp_planner.py)
problem_type: logic_error
component: development_workflow
symptoms:
  - "every floor container refused as one 'no catalogue match' blob though some barely touched"
  - "a pushed-free 1-cell detected as a 3-cell; the plan aimed at bare floor beside it"
  - "the held box touched 23 mm above the measured Pinky surface during the place descent"
  - "the run reported placed while the box was back in the jaws at home"
  - "with two boxes on the floor the arm went to the other one: one library file per site, not per object (2026-10-29)"
root_cause: wrong_assumption
resolution_type: code_fix
severity: high
tags: [omx, arm-s, top-camera, place, pinky, surface, push]
applies_when: "arm S picks from one surface and places on another (floor, belt, Pinky tray) without a person resetting"
---

# Floor → Pinky: four blockers that were not the grasp

The grasp itself had worked many times. The first full carry, with no person helping, failed at four other places. Each one is fixed in code and shown on the real arm (2026-10-28).

1. **A white floor line counted as an object.** The foreground test passes a pixel on lightness alone (`objects.light` 60). The white line next to the containers became foreground and joined every container into one blob, so every pick was refused.
   - Fix: green containers are found by chroma alone; the site parameter file sets `objects.light` to 255.
   - Second fault: `foreground()` used the code defaults when only `params` was passed, so the side-gap mask and the push-path mask ignored the file. It now reads chroma and light from `params` (`test_omx_cell_params.py`).

2. **The edge of the next surface joined the object.** The rectangular ROI included a strip of the orange board along the floor's edge. That strip joined the pushed-free 1-cell, the pair matched a 3-cell (31 × 100 mm), and the dry run planned a grasp on bare floor.
   - Fix: `sites.<site>.surface_px` is a polygon of the surface in the image, and pixels outside it are dropped. Draw its edge where the colour changes (here b* > 140).
   - Always check a new dry-run pick by drawing it on the frame before running it.

3. **One touch point does not give the surface height.** The first touch measured 0.0629 m for the Pinky tray at the old place point. That point was the tray's edge next to the Pinky body. The narrow closed jaws reached it, but the 30 mm box then caught on the frame 23 mm above the tray.
   - Fix: a point inside the tray, chosen so the box's whole footprint stays on it, measures 0.0467 m.
   - Choose a place point from the box footprint on the image first, then touch-measure there (`cell_surface.py`).

4. **The park closes the jaws before it rises.** The pick lift had been lowered to 3 cm to spare the shoulder, and the release lift used the same value. After the release, the fingertips were still around the box top when the park closed them, so the box came home again. The run reported "placed". Opening wider (64) and pressing 2 mm into the tray both failed for the same reason; a 7 cm rise after the release worked (jaws 48.57, the box on the tray in both cameras).
   - Fix: `release_lift_m` is a separate plan value (default 7 cm).
   - The final park's jaw position now decides "placed" or "still holding" (`STILL_HOLDING_UNITS`), so this case can no longer report "placed".

5. **Beyond the surface polygon is not "clear".** The mask is empty beyond `surface_px` by construction. Push path checks therefore counted the raised Pinky tray next to the floor as clear, and the jaws came down on the tray's corner (contact at 0.046 m, the tray's height; FK projected onto the frame).
   - Fix: `path_clear` treats a point beyond the polygon as blocked.
   - The floor polygon's top edge stays below the tray, including the tray's plastic film where it hangs over the floor.

6. **An episode needs frames from every camera.** Another session's recorder stopped the camera services, so every frame request answered 503, and the raw recorder still saved episodes with no images.
   - Fix: a missing camera marks the episode not kept, with the reason.
   - `convert` reads only kept episodes.

7. **The arm's own position error is not in the map bias.** Over a floor 1-cell 0.17 m out, the arm hovered about 8 mm short of the command in y, the same way every time (P-only joints under gravity). The pivot bias is measured against the actual FK pose, so it never contains this error.
   - Fix: `cell_reach.py` feeds the hover's FK error forward into the pick and hovers again. It converged to 1–2 mm on both attempts (2026-10-29).

8. **A failed carry is training data.** Failed episodes used to be deleted.
   - Fix: they are kept as `outcome: failed` with the reason.
   - `convert --outcome failed` builds them into a separate dataset, so successes and misses never mix.

9. **Two candidates planned into one file (2026-10-29).** `plan_pick` saved every candidate's library as `auto-{site}-{offset}.json`. A square box has offset `None`, so with two boxes on the floor the second candidate overwrote the first one's file.
   - What happened: the arm pivoted over one box (pan 64), then `goto above_pick` took it to the other box (pan 53). The reach hook refused, 55/43 mm off.
   - Why it was invisible: the pick and the attempt row named the first box. Only the joint values of the runner's `goto` gave it away.
   - Fix: the file name carries the object's position.
   - Regression test: `test_two_candidates_keep_their_own_libraries` fails under the old name.
   - Verified on the real arm: after the fix, the plan went to the box that had just been pivoted, and the feel search ran four descents without a contact.
   - Check when a pick misses: compare the pan of the `goto` the runner received with the pan of the pivot or the plan. A different pan means the arm went somewhere else.

## Recovery when a box stays in the jaws

From home, run a place again with the same library. Make sure the lift after the release is 7 cm or more before the park.

A runner `grip` command alone did not open the jaws in this session. Use a library whose `grip_open` is wider instead.

## Not yet shown

The fixed `release_lift_m` and the "still holding" check pass their tests. A full run with them on the real arm is still to do.
