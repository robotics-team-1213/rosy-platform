---
title: A new arm's pallet remap took its own swinging cable for the jaws, and the bad map was saved
date: 2026-11-04
category: runtime-errors
module: deploy/robot/omx (cell_calibrate.py, cell_pivot.mark_jaws, cell_upkeep.py)
problem_type: runtime_error
component: deployment
symptoms:
  - "cell_calibrate auto on arm_a did nothing: no camera move, so no remap, although arm_a had no pallet map"
  - "remap LOO error max 52.3 mm (mean 26.8) and the map was saved"
  - "marks at x >= 0.11 m 50-80 px off or None; only the x = 0.09 column agreed"
root_cause: wrong_blob_and_unchecked_fit
resolution_type: code_fix
---

# A new arm's pallet remap took its own swinging cable for the jaws, and the bad map was saved

## Problem

arm_a joined the two-arm pallet cell on 2026-11-03/04. There were three faults, one after another.

1. `cell_calibrate auto` remapped only after a camera move. An arm with no map for its sites was never remapped.
2. The remap fit whatever marks it got and saved the map. One map had a leave-one-out error of max 52.3 mm.
3. `mark_jaws` takes the largest blob that changes between the closed and open frames. On arm_a that blob was
   often not the jaws.

## Cause of the wrong blobs

- **Not jitter.** A 30 Hz trace held at (0.11, 0.10) while the jaws opened and closed twice. Every joint showed a
  standstill std of at most 0.03 units and 0 sign changes per second (`jitter_replay.py`).
- **The top view.** The jaws sit under the wrist servo body. arm_a's wrist cable hangs in a loop across the pallet
  and swings when the jaws move (`cell-arm-a/hover-62-top.jpg`). The swinging cable is the largest change in the
  frame. arm_b's cable is routed differently and its remap was fine.
- **Reach.** At (0.18, 0.10) arm_a's wrist_flex wound up to 285 of 300 PWM, and `joint_push` held the arm. Keep
  map points within 0.18 m.

## Correction (2026-11-04 03:00, tested)

At (0.13, 0.10) arm_a was tested on a long-exposure frame of mean brightness 142. Its jaws really moved from 49.7
to 61.1, yet `jaw_blobs` found no changed blob at tool yaw 0, 45 or -45 degrees, and no cable blob either. The black
v2.1 jaws over the dark navy pallet give too little contrast for `pivot.diff_px` (30). The only marks that held were
the x = 0.09 column, which lies off the pallet over the yellow table. So the main cause is low contrast between jaw
and background. The dim room makes it worse but is not the cause on its own, and the cable explanation above is not
supported. Fix: a white mark on the jaw tips, or map points chosen over bright background.

## Fix

- `cell_calibrate.check` lists `missing_map`, and `stale()` turns it into a remap.
- `map_agrees`: a map whose leave-one-out max is above `calibrate.max_loo_mm` (15 mm) is not saved. The value is
  measured: the kept maps were 5.2 mm and 13.6 mm. On the real arm this refused a 35.5 mm fit.
- The remap visits the least stretched points first. Once three marks that are not on one line exist, it accepts
  only blobs near where an affine fit of them puts the jaws (`predicted`, `pivot.follow_px`). Three marks on one
  column predict nothing.
- `cell_upkeep.py` reports a missing or stale map as a supervised motion step. It runs every 30 minutes on the
  field PC.

## Not resolved

arm_a still has no pallet map. The swinging cable needs routing by a person: tie it along the upper arm so it no
longer hangs over the pallet. Then rerun:

```
cell_calibrate.py --config cell-arm-a-stack.json auto --commissioning --person-at-switch
```

Record: `Rosy/docs/workspace-records/2026-11-04/arm-a-pallet-map.md`.

## Next time

- A new arm has no map, and nothing changed on the camera: check for `missing_map`, not only `camera_moved`.
- A remap's marks must agree before the map is used. A large leave-one-out error means wrong blobs, not a hard
  camera.
- Run `jitter_replay` before blaming shake. It separates joint oscillation from cable or link motion that the
  encoders cannot see.
