---
name: rosy-calibration
description: Use when an OMX cell needs calibrating or re-checking after a camera, arm, belt or pallet change — device and camera roles, surface and object heights from the depth camera, the top camera model from D-933 printed markers, per-arm surface_z, loaded-joint I gains, a planning floor below the table (low_zones), or running two arms at once (per-arm session lock, corridor reservation); also when tempted to measure by hand, touch a light object, or pick calibration points by eye.
---

# ROSY Calibration

The application and its order are in `applications/calibration/README.md` (D-951). This card is how an agent
runs it. Measure with the engine tools; do not pick numbers by hand or write one-off scripts for a step that has
a tool. If a step lacks a tool, add it to the engine (`deploy/robot/omx/cell_*`) with a test, then run it.

## Before anything moves

- Site runs use landed main only (D-932). Read-only analysis of recorded data may run from a branch.
- Every arm motion is a D-911 supervised trial: ask "is a person at the power switch?" for each motion.
- Never widen a guard. A floor below the table only through a `limits.low_zones` rectangle the user approved.
- One arm per session lock: `record_session --arm <arm>`; the other arm's observer keeps running.
- Stopping a background sampler over ssh: kill its PID, never `pkill -f <name>` (it matches the ssh shell).

## Order

1. **Devices**: `omx_devices.py scan --session-config <record-config>` exits 0; `omx_cameras.py inventory`.
2. **Heights** (no motion): capture one Z16 frame from the RealSense depth node and one colour frame, then
   `cell_depth.py --depth d.raw --colour c.jpg --px x,y ... --base x,y`. It gives the table plane, the
   depth↔colour alignment, each surface's height over the table and each arm's plate (its FK zero).
   - FK height of a surface = (surface mm − plate mm) / 1000.
   - Alignment: scene edges, not object masks alone. Objects in one row leave the alignment loose.
3. **Camera model** (D-933/D-954): the lens first. The D435 top camera's K is in the device
   (`cell_device_intrinsics.py read`, no streaming; it was 618.5 px, never the assumed 615) and is accepted only
   when tilted board frames reproduce it (`verify`); other cameras fit K with `cell_checkerboard.py intrinsics`.
   Then the pose: use Fleet Cell's printed markers. Get slot IDs from
   `operations/fleet/fleet/server/cell/cell_print_sheets.py:arm_ids`, matching `cell_frame.slot_ids` and the cell's `markers.slot`.
   `cell_frame.py learn` with gripper-marker views at FK points (supervised), then `cell_frame.py check`.
   - Before trusting it for stacking, check it without the arm: the printed board on the table and on 30/60/90 mm
     stacks in the arm's zone, `cell_tier_check.py` (per tier rms <= 1.5, max <= 2.5, height within 1.5 mm). The
     arm's own map points lie on one plane and carry its FK error; a one-height map is 6-11 mm off per 30 mm.
   - Do not locate the jaws from depth or from an open/close colour difference. Both failed on this cell
     (2026-11-01: LOO 62-355 px from depth; 1 of 4 and 6 of 10 colour marks over the dark belt and pallet).
4. **Surfaces**: write each site's `surface_z` from step 2. A touch (`cell_surface`) only confirms a hard,
   heavy surface. Never touch a light object to measure it: a 16 g container slid away without a contact.
5. **Joint gains**: loaded joints (wrist, elbow) get I gain 50 through the session caps (`"i"`). Without it
   the left arm's TCP was 12.3 mm off at the belt end; with it 3.3 mm.
6. **Check**: `cell_calibrate.py check` has an empty todo.

## Before each move

- `cell_corridor` on the live frame: refused if anything but the pick object is on the low path, an unknown
  blob is under high travel, or the corridor leaves the seen surface.
- `cell_space.reserve(arm, corridor)`: refused while it overlaps the other arm's live reservation; release after.

## Records

Problems and results go to the workspace record and Confluence. Lessons go to `docs/solutions/` only when
verified. Background and numbers: D-951, D-933.
