# OMX two-arm cell survey from the real cameras: plate, cameras and arm bases against the Isaac fixture

**Status (2026-11-03):** the top and side cameras are located against the ship plate studs, and the arm_b base is
located from its own joint states. The plate, stud grid, container cells and belt line of the Isaac container fixture
(`learning/envs/isaac/mapped_stack_fixture.py`, `container_fixture(case='gap')`) match the real cell. The arm bases
do not: the real bases sit 24-36 mm further toward the stern (+x) than `arm_bases_m` and up to 12 mm closer to the
centre line. The fixture is not changed by this record (D-947: the fixture says `CAD_ASSEMBLY_DATUM_NOT_SURVEYED_MOTOR_AXIS`;
measured and CAD values are candidates to compare, not a silent overwrite). Geometry only: no physics, no training.

## Inputs

- Frames: `/run/user/<uid>/rosy-observations/*.snapshot` on the OMX control PC (`rosy.local-observation.v1`, 640x480
  JPEG), 2026-11-03 00:55 and 02:26 KST. Top = RealSense D435 colour, side = the Jieli USB camera.
- Joint states: the running arm_b recording session's `chunk-io-b/live.json` (read only; no observer started, no arm
  command sent). 90 samples at 1 Hz with the four camera snapshots copied in the same second; two still poses used:
  reach (`[8.47, -1.59, -7.69, 59.51, 45.93]`) and park (`[0.76, -62.3, 53.06, 51.65, 45.1]`), normalised units.
- FK: `middleware/devices/omx/adapter/config/omx_f_kinematics.yaml` with `grasp_planner.norm_to_rad`, as
  `deploy/robot/omx/cell_reach.py` does on the real arm.
- Scripts and overlay images: workspace research folder `Rosy/docs/research/2026-11-03-omx-cell-survey/` (outside Git).

## Frame conversion

Stud (i, j) as seen by the top camera (i = column left to right, j = row from the stern; row 1 is the fixture's first
stud row at x 0.134) maps to the fixture frame as x = 0.170 - 0.036 j, y = 0.09 - 0.036 i, z = 0.077 (plate top 0.074 +
3 mm stud). The image's left arm is arm_b (fixture arm index 1, y +0.165).

## Results

| Item | Real (fixture frame, m) | Fixture | How measured | Residual |
|---|---|---|---|---|
| Top camera | (-0.041, 0.037, 0.662), looks at (0.096, 0.041, 0.074); 13.1 deg from vertical toward the stern, image x 0.5 deg off the stud columns | none (800x600 observer views only) | solvePnP on 25 studs, f 615 px (D435 nominal at 640x480) | 0.58 px |
| Side camera | (-0.51, 0.00, 0.15), looks along +x (0.999, -0.037, -0.005); horizontal, 7 cm above the plate top | none | solvePnP on 21 studs, f swept 500-1300 px, best 950 | 2.8 px |
| arm_b base (joint-1 datum) | (0.104, 0.153, 0.072 assumed), yaw -94.3 deg | (0.080, 0.165, 0.072), -90 deg | FK of two still poses, elbow and wrist-pitch joints picked in the top frame | 3.1 px |
| arm_b base plate centre | (0.107, 0.164) | - | base plate centre picked in the top frame, mapped by the stud homography | - |
| arm_a base plate centre | (0.116, -0.164) | (0.080, -0.165) | as above; no FK (arm_a has no live state and stays excluded) | - |
| Stud grid, plate sides, CAD stern 50.6 mm behind row 1 | match | same | fixture projected into both frames | about 1 px |
| Container cells (3 stern cells) | match | `bin_origin_m` (0.035, -0.0485), 0.09 x 0.097 | projected | by eye |
| Belt centre line (top view) | about 5 mm toward -y of the fixture's y 0.007 | y 0.007, 85 mm wide | projected | by eye |

Pick-by-eye inputs are good to about 5 px, which is about 5 mm on the plate in the top frame.

## What this does not settle

- **Belt height (corrected the same day).** The first version of this record read the belt container's top-face width in
  the top frame and guessed the belt sat near the plate top. That was wrong. The arm_b stacking configuration on the
  control PC (2026-11-03 05:32, `beltend` site) has the container top at the belt end 25.8 mm *below* the table (D435
  depth, median of 6 readings), and that session picks containers there with this height. So the belt surface is about
  56 mm below the table and 64 mm below the plate top. The fixture's belt at the same spot (x about 0.22) is 36 mm below
  the plate top: about 28 mm too high. One face width in a near-vertical view is not a height measure; use depth or touch.
- **Joint zero offsets.** The FK fit assumes `norm_to_rad` gives URDF angles. A calibration offset in joint 1 turns the
  fitted yaw (-94.3 deg); offsets in joints 2-4 move the fitted base along the arm. The base plate centre (0.107, 0.164)
  is an independent check that agrees within 3 mm in x.
- **Side camera focal length.** The reprojection minimum is flat (2.8 px at 950, 3.4 px at 800); the camera x is good to
  about 5 cm. The 30 mm container faces in the side frame suggest f near 1000 px.
- **Wrist camera mounts** are not derived.
- The 2026-11-01 top-camera cell maps (`cell-arm-b/calibration.json` and others on the control PC) put the arm_b origin at
  pixel (158, 158), outside the current base plate: they predate the plate layout and are not reused here.

## Step 2: the same cameras in Isaac (D-947 3, 2026-11-03)

The container fixture now carries `real_cameras` (top and side): eye, focus and up taken from the PnP rotations above
(up is the image -y axis, so the 1.5 deg side roll is kept), 640x480, focal length in pixels. Each run's first trial
renders `real-top.png` and `real-side.png` next to the observer pictures.

| Check | Result |
|---|---|
| Fixture pinhole against the real PnP, 36 studs | top 0.03 px, side 0.11 px (mean) |
| Isaac `real-top.png` against the real top frame: both frames fitted by the same stud detector, 36 studs | mean 1.13 px, max 1.85 px |
| Isaac `real-side.png` against the real side frame | overlaid by eye: stud rows match, the cropped bow differs as known. Not measured per stud; bounded by the side PnP residual 2.8 px |

Both are inside the limit D-947 proposes (top and side reference points, mean 3 px). Runs: case
`nominal-palletizing-v21-ship`, seed 42. Run `d53cfe92f3475a6da6c1f50aa6633d56` (first camera encoding without roll,
top 2.04 px mean; 9/9 placed). Run `82e147c7e04f5711834ee96395f01aa3` (final encoding): the camera pictures were written,
then the run unit was stopped from outside together with an unrelated test job on the model PC during layer 7, so its
stacking result is not a claim. Run `00544b84f0685933bf0ce7bb5c2c173c` (final encoding, same case and seed) placed 9/9
and wrote both camera pictures. The arm bases in the renders are still the CAD values, so the base plates draw toward
the bow of the real ones, as measured above.

## The real top-camera parallax centre is 143 px off

The deployed object measurement (`cell_objects.top_face`, `cell_calibration.parallax`) moves a box top down to the map
plane by scaling its pixel about `camera.center_px`, which assumes a camera looking straight down; the live arm_b configs
use the image centre `[320, 240]` with `height_m 0.596`. The surveyed camera is tilted 13.1 deg toward the stern, so
vertical lines converge on the nadir vanishing point K R (0, 0, 1) = **pixel (322, 383)**, 143 px lower in the image.
The resulting error is a constant shift along the stern-bow image axis, proportional to the top's height:

| Top above the map plane | Error |
|---|---|
| 30 mm (one layer) | 7 px, about 7 mm |
| 60 mm | 14 mm |
| 90 mm (three layers) | 22 mm |

This fits the earlier note in `deploy/robot/omx/cell_look.py` (picks near the board about 1 cm off, map bias changing with
position). Fix to try: `center_px: [322, 383]` in the arm configs' `cameras.top`, then compare pick offsets with the
current value. Applied 2026-11-03 16:05 (user decision) to the active arm_b stacking config only
(`cell-arm-b-stack.json` on the control PC; no arm session was running; backup `cell-arm-b-stack.json.before-nadir-20261103`,
reason in `cameras.top.center_px_note`). Older configs keep `[320, 240]`. Pick accuracy with the new value is not yet
measured on the real arm.

## Step 3: surveyed bases and belt as candidates (D-947 2, 2026-11-03)

Cases `nominal-palletizing-v21-ship-surveyed-bases` (measured arm bases, arm_b yaw -94.3 deg) and
`nominal-palletizing-v21-ship-surveyed` (also the belt 28 mm lower) sit beside the CAD case, with their own planner scenes
(`isaac_stack_plan.SCENES`: base/yaw pairs and the low belt-corridor band). The host planner (same IK the Isaac runs use)
gives:

| Target | CAD bases | Surveyed bases |
|---|---|---|
| Belt pickup hover (CAD belt and 28 mm lower) | reachable | reachable |
| All 9 stack targets at carry height | reachable | reachable |
| Leveling spot past the bow, x -0.12 (`leveling_center_m`) | reachable (arm_a 0.259 m) | **arm_a unreachable** (planar wrist distance 0.287 m) |

So the bow leveling spot works in simulation only because the CAD bases sit 24-36 mm closer to the bow. The real arm_a
cannot level there. The Isaac runs of both surveyed cases were not completed: the first attempt stopped at argument
parsing (case not registered with `stacking_task.py`, now covered by a test), the second at the planner's CAD base check
(now named scenes). A full Isaac run needs a leveling place both real arms reach: the user's temporary slot in front of
each arm (about 170 mm from the base, away from the belt, off the plate; plan 2026-10-31, "각 팔 앞 작업대의 임시 칸")
means one leveling place per arm, which the leveling code (one shared `leveling_center_m`) does not support yet.

## Step 4: the whole 3-layer stack in MuJoCo, and the measured layout (2026-11-03 night)

`tools/sim/ship_stack_sequence.py` releases all nine containers in the Isaac order (centre row, then outer rows packed
against the measured centre box, layer by layer) with the floating jaw of `ship_release_scene`, a random release error
per box, and every earlier box left in place. 1,728 cases: 2 orders x 2 openings (33, 31.5 mm) x friction (0.5, 1.0) x
release error sigma (0-0.6 mm per axis) x yaw sigma (0-0.5 deg) x 12 seeds. MuJoCo picks candidates only (D-947 1).

| Release position error (sigma, per axis) | Whole stack seated |
|---|---|
| 0, 0.1 mm | 288/288 |
| 0.2 mm | 284/288 |
| 0.3 mm | 244/288 |
| 0.4 mm | 214/288 |
| 0.6 mm | 50/288 |

First failures sit mostly in layer 2 (no studs guide it): xy drift 141, a release disturbing an earlier box 75; layer 1
`not-seated` 72. Friction 1.0 fails more than 0.5; the row order (centre first or not) makes no difference. So the
real arm needs release error near 0.2 mm, or a guide for layers 2-3 (D-956 relief foot, interlocking container
tops), or a seat check with regrasp. Isaac checks the 0.3 mm boundary next.

The ruler measurements of 2026-11-03 (work table top = 0: arm_b base plate 12 mm, plate top 8, stud top 11, belt end
-55, container 30; leveling spot table 0 assumed) are stored as `layout` in `learning/envs/isaac/cell_model_inventory.yaml`,
and `tools/sim/ship_stack_sites.py` reads them: arm_b plate top -0.004 m, layers -0.004 / 0.026 / 0.056 m, leveling spot
-0.012 m in its frame. The belt end comes to -0.067 m against -0.072 in the live arm_b config (D435 depth): 5 mm apart,
to settle by a touch.

## Step 5: what makes the 3-layer stack tolerate release error (MuJoCo, 2026-11-04)

Same whole-stack sequence (`ship_stack_sequence.py`), order (1, 0, 2), opening 31.5 mm, yaw sigma 0.25 deg, 24 cases per cell
(friction 0.5 and 1.0, 12 seeds). Stages `fix` (container shape x release height) and `retry` (D-956 seat check and re-place).

| Set-up | 0.3 mm | 0.4 mm | 0.6 mm | 0.8 mm |
|---|---|---|---|---|
| plain container, release 5 mm (today) | 20 | 18 | 5 | 1 |
| plain, release 2 mm | 24 | 23 | 15 | 2 |
| relief foot r290, release 5 mm | 24 | 24 | 18 | 4 |
| rail (tongue/groove), release 2 mm | 24 | 23 | 17 | 4 |
| chamfers c10 / a10 | no better than plain | | | |
| **plain, release 2 mm, seat check + 1 re-place** | | 24 | 24 | 24 |
| **r290, release 2 mm, seat check + 1 re-place** | | 24 | 24 | 24 |

- The seat check with one corrected re-place recovers every stack up to 0.8 mm. A second re-place was never used.
  Re-places used: 60 of 648 releases for plain, 43 for r290.
- The rail's groove sits badly on the layer-1 studs (first failures `not-seated@L1`), so it adds little.
- Limits:
  - The regrasp is idealised (the box returns to the jaw where it lies).
  - The re-place error is an assumed 0.1 mm.
  - The real gain therefore depends on measuring the miss: height within 0.3 mm, tilt within 0.5 deg, xy within about 0.1 mm.
  - MuJoCo picks candidates only (D-947 1).
- Next:
  - Isaac checks "release 2 mm + seat check + 1 re-place" at 0.4 to 0.6 mm.
  - On the real cell, the seat measurement method decides it: wrist camera, touch, or both.

## Step 6: Isaac answer to step 5, and the snap-together ship v11 (2026-11-04)

### Seat check + re-place in Isaac (stud plate, seed 42)

| Case | Run | Result |
|---|---|---|
| 0.6 mm across, release 2 mm, no seat check | 2cd8968c | 1/9: box 0 never settles |
| 0.6 mm, seat check + 1 re-place | 48dcb6a4 | box 0: 1.07 mm high, 4.27 deg -> after re-place 1.45 mm, 5.85 deg -> HOLD |
| 0.8 mm, no seat check | c79373ba | 1/9: box 0 has no stable window |
| 0.8 mm, seat check + 1 re-place | 3b55bb62 | box 0: 1.11 mm, 4.41 deg -> after re-place 1.45 mm, 5.83 deg -> HOLD |

- Isaac does not reproduce step 5. Box 0 rests with one long side on a stud, and the re-place makes it worse.
- Likely cause (not yet confirmed): MuJoCo's re-place returned the box level in the jaw; Isaac regrasps the tilted box
  and releases it tilted. The tilt after the regrasp was not recorded.
- Not pursued on the stud plate: the v11 ship below has no stud to ride on.

### MuJoCo twin of the v11 ship hold with container v2 (896 cases)

`tools/sim/ship_v11_scene.py`, geometry `learning/envs/isaac/ship_v11.py`:

- The hold has three rows 38 mm apart and pockets 0.8/0.6 mm wider than the box. Each pocket has a 0.6 mm vertical wall,
  then a slope that catches +-3.5/3.3 mm.
- 12 pins per slot: 45 degree cones on the pocket floor.
- Container v2: 12 bottom sockets (0.3 mm radial gap on a pin) and 4 top cones at the ends; stacking height 32.4 mm.
- The v2.1 jaw and the wrist camera holder B (box proxy) are on the floating jaw.
- Cases: `ship_stack_sequence.py run --stage v11`: release error 0.5-3.5 mm per axis, yaw 0.25/1 deg, friction 0.5/1.0,
  release 2/5 mm, re-place 0/1, 8 seeds.

| Release error per axis | All 9 seated, no re-place | All 9 seated, seat check + 1 re-place |
|---|---|---|
| 0.5 mm | 60/64 | 64/64 |
| 1.0 mm | 34/64 | 64/64 |
| 1.5 mm | 5/64 | 64/64 |
| 2.0 mm | 5/64 | 64/64 |
| 2.5 mm | 0/64 | 64/64 |
| 3.0 mm | 0/64 | 64/64 |
| 3.5 mm | 0/64 | 60/64 |

- The deck layer holds: unseated layer-0 boxes are 0/192 at 0.5 mm and 1/192 at 1 mm, and 28/192 at 2 mm.
- The upper layers fail. Their only guide is the 4 top cones, which catch about 2.3 mm (socket mouth r 2.8 less cone tip
  r 0.5). A missed box sits flat on the cone tips, 2.0 mm high and 2.3-3.5 mm off.
- The "disturbed an earlier box by more than 0.3 mm" rule fails some stacks where everything is seated: an upper box
  landing shifts the one below within its pin play. The 0.3 mm limit came from the stud plate and needs a v11 value.
- Friction and release height change little with a re-place (222/224 seated at either friction).
- The camera holder touched a box only at 3.5 mm error (6 of 128 cases). It was then 4.3 mm lower than the rated holder
  B 16/16.
- MuJoCo 3.3.7 (lab PCs) threw a seated top-layer box off a lid at rest when the pieces were boxes; the scene builds
  them as convex meshes (seeds 1 and 2 error-free stacks seat, same speed).
- Limits:
  - The re-place is idealised as in step 5, and Isaac just showed that this idealisation does not hold on the stud plate.
  - MuJoCo picks candidates only (D-947 1).

### Wrist camera B in the Isaac demonstrations

- Case `nominal-palletizing-v21-ship-surveyed-bases-wrist-demo` records `arm_a_wrist` and `arm_b_wrist` (640x360) next to
  top and side, from `palletizing_gripper.WRIST_CAMERA_B`. That is the rated holder `b16-u16-span-B`: lens
  (33.8, 0, 51.1) mm on link5, axis 30.4 deg below the jaw axis.
- The stock link5 mesh carries the ROBOTIS camera frame F9 2.6 mm from the lens and covered a third of the image (run
  f3c208d1). The case draws the team link5 (gripper body, plate F6, holder B) instead (`assets/omx_wrist_camera_b`).
  With it, both jaw tips, the container and the plate are visible (run a5e03df9).
- Four views at 300 kbps reached 237 MB of the 256 MiB run limit; they are now recorded at 180 kbps.
- The image orientation (up toward the wrist) is ASSUMED until compared with a real wrist frame.

## Next

1. Run the D-947 MuJoCo sweep with the surveyed bases as a second candidate next to the CAD ones; adopt them in
   `arm_bases_m` only if they change reach or collision results, with the run evidence.
2. Done: see step 2 above.
3. Lower the fixture belt by the measured 28 mm (a fixture change with a rerun, not done here); arm_a by FK when arm_a is
   back in scope; wrist camera intrinsics by checkerboard (person places the board), then the wrist mounts.
