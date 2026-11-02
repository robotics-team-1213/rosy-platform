# OMX palletizing simulation, step 1: jaw v2.1 and the real container mass (simulation)

**Status (2026-11-01):** step 1 of the rebuild plan passes in simulation. The team's palletizing jaw v2.1 and a 16 g
3-cell container are an opt-in condition; one nominal grasp lifted the container 158 mm and held it 2 s with 0.0 mm slip.
Steps 2 and later are not started. Simulation only (Isaac SDK 6.2.0.0, seed 42); not hardware or field acceptance.

## What was modelled

- **Opt-in key:** fixture `gripper='palletizing-v2.1'`, set by the cases `nominal-palletizing-v21` (full flow) and
  `nominal-palletizing-v21-hold` (lift, hold 2 s, stop). Every other case keeps the stock OMX-F jaw and 60 g.
- **Jaw:** `assets/omx_f_palletizing_description/` (Apache-2.0, team zip of 2026-10-31): URDF, the two jaw STL files,
  `manifest.json` with SHA-256. The arm meshes are byte-identical to the vendored ROBOTIS 5.1.2 ones and are not copied.
- **TCP:** `end_effector_joint` x 0.0740 m (stock 0.09193), y -0.0016. The IK planner takes `tcp_x_m` in its request
  (`deploy/robot/omx/isaac_stack_plan.py`); without it the stock kinematics are unchanged. The TCP frame stays a
  massless child of link5.
- **Pads:** one box per finger on the mesh's raised pad face (not guessed; `palletizing_gripper.pad()` reads the STL).
  Finger hull collision is switched off; each finger has exactly this one collider.
- **Finger angles** come from the pad geometry: pre-open at a 36 mm gap, close at 27 mm (30 mm container less the 3 mm
  squeeze of `cell_profile.yaml`), release at 40 mm.
- **Container mass:** 7.2 / 11.79 / 16 g for 1 / 2 / 3 cells (user, 2026-11-01), only under the opt-in key.
- **Pad sweep below the TCP** (`pad_sweep.py`) uses the new pad corners for the opt-in jaw.

## Measured geometry (jaw6 mesh, link6 frame; jaw7 is the mirror in y)

| Quantity | Value |
|---|---|
| Pad face normal (into the jaw) | 69.946 deg from +x |
| Pad face offset n.p | 6.3385 mm (plate behind it 7.239 mm, plate back face about 8.2-8.3 mm) |
| Pad extent along the finger | 26.5 to 43.5 mm (17.0 mm), z -9 to +9 mm (18 mm wide) |
| Plate (behind the pad) | z +-20 mm (40 mm wide), x 26.5-44.2 mm along the face |
| Pivots in link5 | link6 (0.0295, 0.0075), link7 (0.0295, -0.0108) |
| Pad box (collider) | 1.5 mm x 17.0 mm x 18.0 mm, inner face on the mesh pad plane |
| Pad gap at 0.35 rad | 30.977 mm |
| Close angle for the 30 mm container (27 mm gap) | 0.3047 rad; contact (30 mm) at 0.3388 rad |
| Pad bottom against the TCP (top-down wrist, full-circle sweep) | -0.46 mm, so the TCP is the pad's lower end |

**Differences from the hand-over notes.** The 40 mm wide, 1.1-2.0 mm thick plate is correct, but the face n.p = 8.2-8.3 mm
is its back; the box-facing surfaces are the plate at 7.24 mm and a raised 18 mm wide pad at 6.34 mm. The README quotes
29.977 mm between pads at 0.35 rad; the mesh gives 30.977 mm, exactly 1.000 mm more. Half a millimetre of tape per side
would explain it, and the mesh does not contain it. The sim uses the mesh. Resolve this with a caliper on the real jaw.

## Grasp-and-hold check

Case `nominal-palletizing-v21-hold`, seed 42, layers 3, commit d65acb82f1: run `3614198ae7d750418daf633fc3900763`
(report verified, video verified). The run ends on purpose after the hold (`error: grasp-hold check complete`), so
`task_success` is false by construction. Summary (`mapped_stack_report.py summary`):

| Measure (2 s hold, 21 samples) | Value |
|---|---|
| Container | first of nine, 90 x 30 x 30 mm, 16 g, infeed from the belt |
| Finger angle | 0.3379 rad (command 0.3047; the 0.2 N m finger effort cap stops it at contact) |
| Pad gap from the finger angle | 29.925-29.926 mm |
| Slip, box against TCP | 0.0 mm over the hold |
| Box rotation during the hold | 0.0 deg |
| Box rise above the belt | 158 mm |
| Box position against TCP at hold start | (-0.01, -0.06, -2.01) mm |
| Held | yes |

Tests (remote host, committed revision): `learning/envs/isaac/test` 628 passed, 1 skipped, 1 failed (the new test's own
Linux file-URI bug, fixed in d65acb82f1); then `test_palletizing_gripper.py` (9 cases) with `test_container_stack.py`: 40 passed. One earlier launch of this run (commit 78332b1978) ended with "Isaac operation failed" before any artifact
existed, while another chain held the GPU; the same request on the next commit ran cleanly.

## Not modelled

- The ship-shaped navy stud plate and its studs are absent from every CAD file received (step 2).
- Real friction and the tape/plate surface (sim uses the shared friction 1.0, restitution 0).
- Container ribs, the lid and any flex; the container is a rigid 16 g box.
- The 1.000 mm pad-gap difference to the README (above) and the jaw's real stiffness and finger backlash.
- Placement with the new jaw: lowering into a 3.5-6 mm row gap, finger snags and leveling are untested (step 4).
- The release corrector models (BC v0, rl3) were trained with the stock jaw at 60 g and are not valid here (step 5).

## Step 2: the ship-shaped stud plate (2026-11-01, simulation)

**Status:** opt-in case `nominal-palletizing-v21-ship` (jaw v2.1, 16 g containers, nominal IK) places **9/9 on seeds 42, 43, 44 and
45** on the stud plate. Commit for the runs: f0d8c10dc9 (later commits only regenerate `index.md` and add docs). Simulation only
(Isaac SDK 6.2.0.0); the plate is built from photo measurements, not CAD, and several values are assumptions (below).

### The plate (`ship_plate.py`, built from the plan's photo measurements)

| Item | Value | Source |
|---|---|---|
| Stud pitch / diameter / height | 35.1 / 4.7 / 3.0 mm | side camera (plan, 2026-11-01) |
| Grid | 6 x 6 studs = 5 x 5 cells, at lane intersections; the photo may show a 7th row | plan |
| Stack | the centre three of the five cells across (user), the three stern-side cells along the length | user, coordinator |
| Plate thickness | **3 mm, ASSUMED** (thin plate of a few mm, no caliper value) | side-camera look |
| Margins | stern 16, sides 12, bow shoulder 5 mm, **ASSUMED** (RealSense crop, about 0.47 mm per pixel) | photo |
| Bow | points away from the belt, flat stern faces the belt (coordinator correction). Length **20 mm ASSUMED**: a longer bow reaches the leveling spot (below) | photo, reach |
| Stud top | hemispherical cap, **ASSUMED** (round tops in the wrist-camera view). A 1.2 mm flat cap let a box 0.5 mm off-centre ride up the stud (42 deg slope, friction 1.0 holds it; run s42n) | photo, run |
| Collider | one kinematic body `/World/Bin` (plate box + one sphere per stud), so cargo contact views see it as 'bin'. A static triangle mesh gave inconsistent vertical contact forces (run s42p: z 0.09 N of 0.31 N) | runs |
| Rows | row pitch 35.1 mm, lane 5.1 mm, band 4.5-5.7 mm; a box has 0.2 mm each side to the studs (30.4 mm clear width) | plan |

Plate top 75 mm (table 72 mm + 3 mm); the stack envelope and targets use it as the container floor. Studs reach 78 mm.

### Release

- Release 5 mm over the plate (`stack_release_clearance_m`), above the 3 mm studs. `ship_plate.release_floor_z` enforces the floor on layer 0:
  box bottom and finger bottom stay at least plate top + 3 mm + 1 mm margin (the finger plate is wider than the 35.1 mm pitch, so it always overlaps a stud).
- The jaw opens to **33 mm** (`release_gap_m`, opt-in) instead of 40 mm. With 40 mm the neighbour-side pad swung 5 mm outward into the neighbouring container:
  layer-1 row gap -0.68 mm, box 5 unstable (run s42o). With 33 mm no placed container moved more than 0.3 mm on opening in any of the 36 placements.
- Finger bottom over the stud tops at release: **18.5 mm** on layer 0 (the pad lower end sits about 16.5 mm above the box bottom), so the pad never comes near a stud;
  48.5 / 78.5 mm on layers 1 / 2. The box bottom (5 mm over the plate) binds before the finger does.
- Leveling (set the box flat on bare table, regrasp) cannot stay at x -0.04 m: the plate now covers it. The spot moves to x -0.12 m, past the bow, with a 0.13 m carry
  (0.212 m is out of reach there; planner scan: both arms reach x -0.13 m up to 0.13 m height) and a waypoint (-0.07, 0, 0.212) for climbing and descending
  (`leveling_via_m`, `leveling_carry_height_m`, opt-in). The table area in front of each arm (away from the belt, outside the plate) stays free for the later slot blocks.

### Results (commit f0d8c10dc9, layers 3, nominal IK)

| Seed | Run | Placed | Row gaps (mm) | Settled xy error vs target | Failures |
|---|---|---|---|---|---|
| 42 | b18a95620f6f5d80b4644bae6c413e0e | 9/9 | 4.93 to 5.18 | 0.18 mm or less | none |
| 43 | b1051ad6ca555409ace9f8827b8d4703 | 9/9 | 4.80 to 5.24 | 0.18 mm or less | none |
| 44 | 94c4884f409b55eda3f8413feb26378e | 9/9 | 4.85 to 5.11 | 0.20 mm or less | none |
| 45 | 982ab546f1395d0c958cd5bd203cc6cc | 9/9 | 4.89 to 5.17 | 0.20 mm or less, except box 8 (top layer, no studs): 0.8 mm | none |

All four: release 5.0 mm over the plate (box bottom), settled z error 0.0 mm, no landing drift after opening except seed 45 box 8
(0.67 mm slide on the top layer, no studs involved), no finger-stud contact (finger bottom at least 18.5 mm over the stud tops) and no placed neighbour moved
more than 0.3 mm on opening. Seed 42's boxes 3 and 6 were flagged by the summary's speed gate on the last sample only (0.017 and 0.022 m/s); the run succeeded.

Tests (remote host, committed revision): `test_ship_plate.py`, `test_palletizing_gripper.py`, `test_release_corrector.py`, `test_container_stack.py`,
`test_container_leveling.py`: 88 passed. Harness lint: 0 errors.

### Off-centre evidence (how far off can a first-layer release be)

Nominal IK releases land within 0.0 mm of the channel centre, so the final runs hold no off-centre sample. Earlier runs give two data points:
- Flat 1.2 mm cap, box 0 off by +0.50 mm in y (and a small yaw): the box rode up the stud flank, sat 0.65 mm high with a lateral contact force, and did not slide in.
- Hemispherical cap: settled errors up to 0.2 mm in xy (the box sat against a stud) and 0.0 mm in z, so boxes within the 0.2 mm side clearance land in the channel.
No run released deliberately 0.3-1.0 mm off-centre; the corrector-noise cases of step 5 will provide that. The clear width is 30.4 mm for a 30 mm container, so the
channel tolerates +-0.2 mm before a box touches a stud; whether it slides in beyond that depends on the stud top shape and the friction, both assumed.

### Free channels (user decision: stack in the centre three cells)

`ship_plate.free_channels` gives them, per arm (arm 0 stands at -y, arm 1 at +y). They are clear of the stack rows (y 0, -0.0351, +0.0351) and of the finger positions of all nine placements:

| Arm | Channel centre y (m) | Cell centres along x (m) | Clear width |
|---|---|---|---|
| 0 | -0.0702 | -0.0253, 0.0098, 0.0449, 0.0800, 0.1151 | 30.4 mm |
| 1 | +0.0702 | same | 30.4 mm |

The stack cells along x are 0.0449, 0.0800 and 0.1151; the two cells at -0.0253 and 0.0098 are the spare ones. No staging or realign step is built.

### Not done / assumptions

- Plate thickness, margins, bow length, stud cap shape and real friction are assumptions; a caliper on the plate and a friction tilt test would replace them.
- No parameter randomisation yet (next step). The release corrector models are not used.
- `mapped-top.png` of the final runs shows the flat stern at the belt side, the bow away from it, the 6 x 6 studs and the stack at the stern, matching the ceiling image; the bow is shorter than the photo's.

## Step 3a: MuJoCo sweep of deliberate off-centre release (2026-11-01, candidates only)

**Status:** D-947 order (user, 2026-11-01): new conditions run in MuJoCo first to find failure-boundary candidates, then Isaac confirms around them.
Everything below is MuJoCo contact physics. **It only chooses Isaac cases; none of these numbers is a result** (D-947 section 5). Nothing was run in Isaac.

### Scene (`tools/sim/ship_release_scene.py`, sweep `tools/sim/ship_release_sweep.py`)

- Plate, studs, channel, container size, 16 g, pad boxes, jaw angles, TCP, release gap and opening acceleration all come from the Isaac-side modules (`ship_plate`, `palletizing_gripper`, `mapped_stack_fixture`); no value is retyped.
- **No arm, IK or controller.** The jaw is a mocap body placed by the TCP (link5 frame, top-down wrist) with the two finger hinges, the one pad box per finger that Isaac collides, a mimic equality (q1 = -q0) and one lead actuator capped at 0.2 N m. This answers release-and-settle only, not reach or placement.
- Studs are capsules (cylinder plus hemispherical cap, 4.7 mm, 3 mm high, **cap shape assumed**), the plate a box over its outline. The held box sits 2.01 mm under the TCP (the Isaac hold check). Contacts: stiff solref 0.002, elliptic cone, timestep 0.5 ms, one friction value for every geom (Isaac uses one material too), no restitution.
- A case: squeeze 0.35 s, open with the Isaac profile (`grip_duration`, 0.025 rad/s^2), settle 0.5 s, lift the jaw 25 mm, settle 0.5 s; about 0.2-0.4 s of compute. Layer 1: studs, a seated neighbour in the centre row. Layer 2: three seated boxes below (no studs), neighbour on top.
- The MuJoCo wheel needs `msvcp140.dll`, which this laptop lacked: `pip install --user msvc-runtime`; the scene preloads it from `%APPDATA%\Python\Scripts`.

### Does MuJoCo agree with Isaac at nominal?

| Check | Isaac (seeds 42-45) | MuJoCo |
|---|---|---|
| Nominal release, 33 mm opening: z error | 0.0 mm | 0.00 mm (layers 1 and 2) |
| xy error against the target | 0.18-0.20 mm | 0.05 mm across, 0.0 along |
| Neighbour moved on opening | 0.3 mm or less | 0.0 mm |
| 40 mm opening | neighbour pushed, row gap -0.68 mm (run s42o) | neighbour displaced 2.2-4.1 mm on layer 1, 3.9-4.8 mm on layer 2 at every offset (back to 0.2 mm once the jaw lifts: the pad sits against it while open) |
| Flat 1.2 mm cap, 0.5 mm off: rode up (run s42n) | rode up | not simulated (cap hemispherical, as the final Isaac plate) |

They agree on every point Isaac measured. The Isaac xy figure includes arm control noise that this scene lacks.

### Sweep and boundary

7,056 cases: layer 1/2 x row +1/-1 (each pad faces the neighbour in turn) x opening 33/40 mm x friction 0.5/1.0/1.2 x release height 3/5/8 mm x yaw 0/0.25/0.5/1/2/3 deg x across offset -1.5..+1.5 mm in 0.25 mm steps; plus an along-offset stage (0-1.5 mm x height 4/5/6 x yaw 0/1/3 x across 0, +/-0.5, +/-1) and fine scans (0.05 mm across, 0.25 deg yaw, 0-5 mm along). Results are symmetric between toward and away from the neighbour and between rows. Pass rules (from the Isaac runs): z within 0.3 mm of the seat; neighbour moved 0.3 mm or less; layer 1 also within 0.25 mm across (clear width 30.4 mm); layer 2 within 1.5 mm xy (`xy_tolerance_m`).

| Axis | Layer 1 (on studs), 33 mm opening, friction 1.0 | Layer 2 (on boxes) |
|---|---|---|
| Across-channel offset | seats up to **0.5 mm**; fails from **0.55-0.6 mm** (box edge rides a stud cap, tilted, centre 0.9-1.3 mm high). Friction moves it: 0.4 mm at 1.2, 0.6 at 0.8, 0.75-1.0 at 0.5. At 0.5 mm the outcome flips with drop height (5.5-6.5 mm fail, 3-5 and 7-8 pass) | no guide: the box stays where released (error = offset), only the 1.5 mm tolerance matters |
| Along offset (0-5 mm) | no effect (studs guide only across) | none until the 1.5 mm total |
| Yaw, no offset | seats up to **1.5 deg**, one sign to 1.75 (the studs turn it in although a 90 mm box at 1.5 deg is 2.4 mm wider across); **fails from 2 deg** (rides on the studs, centre 1.9 mm high). 2 deg plus any offset fails | seats; 2-3 deg plus 1.25-1.5 mm toward the neighbour touches it (0.3-0.5 mm) |
| Release height 3-8 mm | no trend beyond the 0.5 mm flip (3 mm is below the Isaac floor of 4 mm) | none |
| Friction 0.5-1.2 | **main driver of the across boundary**: more friction holds the box on the cap (slope about 41 deg) | none |
| Opening 33 vs 40 mm | 40 mm disturbs the neighbour in every case (Isaac saw the same); 33 mm only at yaw 2-3 deg with 1.5 mm toward | same |

### Isaac confirmation cases (not run)

Isaac had no way to release deliberately off-centre, so this commit adds `release_offset_m` = [along x, across y] metres (`mapped_stack_fixture.cube_release_target`, added after the neighbour clamp, applied to every placement; test in `test_container_stack.py`) and these cases (`release_cases.py`, selectable as `--container-case`, base `nominal-palletizing-v21-ship`, layers 3, seed 42 first):

| Case | Offset | MuJoCo expects | What Isaac settles |
|---|---|---|---|
| `nominal-palletizing-v21-ship-y040` | 0.4 mm across | seats | lower side of the boundary |
| `nominal-palletizing-v21-ship-y050` | 0.5 mm across | at the boundary, flips with drop height | where Isaac's boundary really is |
| `nominal-palletizing-v21-ship-y060` | 0.6 mm across | layer-1 boxes ride up a stud | upper side |
| `nominal-palletizing-v21-ship-y-060` | 0.6 mm the other way | same as +0.6 | sign and pad asymmetry (the jaw is not symmetric) |
| `nominal-palletizing-v21-ship-x150` | 1.5 mm along | seats, no effect | along tolerance |

The layer-1 outcomes come from the first three boxes (studs; neighbour present for the outer rows); the same offset on layers 2 and 3 is only judged by the 1.5 mm rule. Read the layer-1 rows of the report, not the 9/9 total.

**Not wirable yet (needs planner or material work):** yaw (the sharpest boundary, 1.5 vs 2 deg; needs a wrist-yaw offset in the IK request), friction (Isaac has one global grip material in `run_omx_backend`), and the layer-2 neighbour touch at 2-3 deg plus 1.5 mm. Yaw is the most informative next case.

### Assumptions and limits

- Stud cap shape, friction 1.0 and plate thickness are the plan's assumptions; the across boundary depends mostly on the first two (friction 0.5-1.2 moves it 0.4-1.0 mm). A tilt test and a caliper on the real plate would pin them.
- Floating jaw: arm compliance, corrector noise, the lowering motion and the wrist angle at release are not modelled. The flip at 0.5 mm with drop height shows impact dynamics matter at the boundary, and MuJoCo soft contacts are not PhysX.
- The 0.25 mm across rule on layer 1 is the clear-width rule, not an Isaac pass criterion (Isaac's `xy_tolerance_m` is 1.5 mm). A box that rides a stud is the finding, not the exact threshold.

## Step 3b — Isaac confirmation of the off-centre cases (2026-11-01)

Seed 42, three layers, `nominal-palletizing-v21-ship-*`. First batch on `ab049f0b98`, second on `de414c8795` (stricter seat height, below).

| Case | Offset | Placed | What happened (first-layer box that failed) |
|---|---|---|---|
| nominal (de414c8795) | 0 | 9/9 | all boxes z 90.0 mm, y within 0.14 mm of the row centre |
| y020 | 0.2 mm across, toward the centre row | 2 | box 1 pushed 0.6 mm outward when the jaw opened (y -35.47), now 0.9 mm high on the outer stud |
| y030 | 0.3 mm | 2 | same, y -35.48, 0.9 mm high |
| y040 / y050 / y060 | 0.4–0.6 mm | 2 | same, 0.9–1.2 mm high |
| y-060 | 0.6 mm outward | 3* | box 0 and 1 1.1 mm high on studs; counted as placed under the old 1.5 mm band (*), box 2 failed |
| x100 | 1.0 mm along | 3 | all seated at z 90.0; box 2 failed the 90 mm bin-length check (x +1.07 mm) — a judging limit, not a physical failure |
| x150 | 1.5 mm along | 1 | seated at z 90.0; fails the 1.5 mm target band by construction (test-design error) |

Findings:

- **Isaac is stricter than MuJoCo.** MuJoCo seated across offsets up to 0.5 mm; Isaac fails from 0.2 mm, the smallest tried. The across-channel side clearance in the model is about 0.2 mm, so an outward offset meets the outer stud directly.
- **The mechanism for an offset toward the neighbour is the jaw opening, not the drop.** The box was released where commanded, then moved about 0.6 mm *outward* while the 33 mm opening ran, and came to rest on the outer stud. The floating-jaw MuJoCo scene does not have arm compliance and did not show this.
- **The settle check had a hole.** A box resting on a stud sits 0.9–1.2 mm high, inside the 1.5 mm per-axis band, so y-060 counted two such boxes as placed. The ship case now judges height to 0.5 mm (`stable_box`, test `test_a_box_resting_on_a_stud_is_not_seated_on_the_plate_only`); the nominal case still places 9/9 under it. The earlier 9/9 runs (seeds 42–45) had z error 0.0 mm and are unaffected.
- **Along the channel** a 1.0 mm offset seats physically; the limit there is the judging band, not the studs.

Consequence for the real cell: with the assumed hemispherical studs and friction 1.0, the across-channel release must be within about ±0.1–0.2 mm, which the current top camera (424×240) cannot deliver. Next to try in simulation: open while lifting, or a smaller release opening, to remove the 0.6 mm outward push; then re-run y020/y030. The stud cap shape and friction remain assumptions and decide this boundary.

## Step 3c — smaller release opening, 31.5 mm (2026-11-01)

Commits 51685f9fd5 / 207dd9afa7. Case suffix `-g315` sets `release_gap_m` 0.0315 (each pad 0.75 mm off the box instead of 1.5 mm).

| Case | Seed | 33 mm opening | 31.5 mm opening |
|---|---|---|---|
| nominal | 42 / 43 / 44 / 45 | 9/9 each | 9/9 each |
| y020 (0.2 mm toward neighbour) | 42 | 2 (pushed outward onto a stud) | 9/9 |
| y030 | 42 | 2 (pushed outward onto a stud) | 2 — box at the row centre (y -35.06) but 1.34 mm high, a pad still touching it (0.04 N) |
| y040 | 42 | 2 | 9/9 |
| y-020 (0.2 mm outward) | 42 | — | 1 — box 0 at the row centre, 1.36 mm high, a pad still touching it |

- The 31.5 mm opening removes the outward push that failed every 33 mm offset case.
- It brings a different failure: a pad stays in contact after opening and holds a first-layer box 1.3 mm up. It is not monotonic in the offset (y030 fails, y040 passes), so the boundary is noisy around 0.2–0.4 mm.
- Nominal placement is unaffected: 9/9 on seeds 42–45 with 31.5 mm.
- Next: 32.25 mm (`-g3225`) on the same five seed-42 cases; then open-while-lifting if the pad contact remains.

**Correction (same day):** the 31.5 mm failures are not a pad holding the box. After the arm left, the failing box was still static and high, and its orientation shows a roll of 1.8–3.5° about the long axis (y030-g315 1.81°, y-020-g315 1.88°, y020 at 33 mm 3.48°): one long bottom edge sits on a stud top and the box rests tilted. The 0.04 N pad contact was only during opening. Open-while-lifting is therefore not the expected fix; the side clearance (about 0.2 mm each way) is.

## Step 3d — 32.25 mm release opening (2026-11-01, commit 169bedae7e, seed 42, photo-estimate plate)

| Case | 31.5 mm | 32.25 mm |
|---|---|---|
| nominal | 9/9 | 9/9 |
| y020 | 9/9 | 9/9 |
| y030 | 2 | 2 |
| y040 | 9/9 | 2 |
| y-020 (outward) | 1 | 1 |

Same edge-on-dot tilt in every failure. Opening width only moves the noisy 0.2–0.4 mm band; it does not widen it. These runs use the photo-estimate plate (0.2 mm side clearance); the team CAD (Jira KAN-108: pitch 36, dot Ø5.2 with a chamfered flat top, 0.41 mm side clearance) supersedes it and the boundary is being re-run on that geometry.

## Step 4 — release strategy and container variants on the KAN-108 plate (2026-11-01)

Order (D-947): MuJoCo sweep first, **candidates only**; Isaac confirms the boundary. User decisions today: the release becomes "lower until contact, then open, small lateral search, seat check, re-place on failure"; the containers may be redesigned and reprinted (mass may change).

### The plate is now the team CAD (Jira KAN-108)

`ship_plate.py` (read by Isaac and MuJoCo) builds from the drawing and `container_ship_hull_deck.stl` (sha256 `d545ae5109608774e56430248edfc456d8ba189ae9d3f5047d95417290f88ad5`; bridge STL `07c4f35cc5a3d8ab555e71bf55783bcf7fe5643da89c6095a016b7ebc87931c0`; both are in `ship_plate.SHIP_PLATE['source']`): pitch 36 mm (cell 30 + gap 6), dots 5.2 mm with a 45 degree 0.8 mm chamfer to a flat top (read off the STL: radius 2.6 mm up to 2.2 mm over the deck, 1.8 mm at 3 mm), height 3 mm, plate 8 mm. Clearance around a 30 mm box: **0.40 mm per side** (drawing 0.41; the photo model had 0.2). The stack row pitch is 36 mm, the lane 6 mm (`row_gap_m` .006, `finger_gap_width_m` .005 as in `nominal-gap6-release3`). Isaac dot colliders are convex-hull meshes of `ship_plate.stud_solid`; MuJoCo uses the same solid.

Not taken from the CAD: the stern is cropped to 16 mm behind the first dot row (the real stern is 50.6 mm, with the 58 mm bridge) and the bow to the bulwark at 198 mm (tip to 244.6). A first Isaac run with the full stern failed at the first free lift (run 7913, `bilateral free lift failed`); the stern covering the belt feed spot is the likely cause, not verified. The bow tip would cover the leveling spot (x -0.12), which cannot move because the arms reach only to x -0.13. **Open layout question for the team:** where the real stern, the removable bridge and the belt end meet. **Isaac nominal on this plate (seed 42, `a9d31a94aa`, run fb168d3d, `nominal-palletizing-v21-ship`): 9/9 placed**, row gaps 5.57-5.99 mm (band 4.5-7.5), two containers still moving at 0.017-0.020 m/s at the stability check but within 0.14 mm of target; seeds 43-45 not run. Neither crop touches a dot. The bridge is not on any modelled arm path (carry height 0.212 m against a 66 mm top).

### What was built

- `tools/sim/ship_release_strategies.py`: `drop` (open 5 mm above the seat), `guarded` (lower at 5 mm/s until the box bottom meets a dot or the plate, contact force over 0.05 N, then open), `search` (guarded; if the contact height is more than 0.5 mm above the seat: light pinch 0.02 N m, 0.6 mm preload, lateral steps +-0.25/0.5/0.75/1.0 mm until the box height is back at the seat, then open). Seated = height within 0.5 mm and roll/pitch within 0.5 degree (layer 2 also xy within 1.5 mm). A failed release gets one re-grasp, a 6 mm lift and a re-place with the command off by -0.2 or +0.2 mm.
- The MuJoCo jaw is now a free body welded to a mocap target (`build(..., weld=True)`). **A mocap jaw has no velocity, so its pads slid over a held box without friction**: lowering or lifting a held box did nothing. The Step 3a sweep never moved a held box, so its results stand.
- `learning/envs/isaac/container_variants.py` (stdlib, used by both simulators): variants, hull faces, `MASS_RATIO`. `tools/sim/ship_release_strategy_sweep.py`: sweep and table. Isaac: `guarded_release.py` (stall detection on the held box height, wired in `mapped_stack_task.py` behind `fixture['guarded_descent']`) and convex piece colliders for a variant (`stacking_scene.variant_colliders`, behind `fixture['container_variant']`).
- Variants (outer 90 x 30 x 30, the two 30 mm grip faces untouched): `c05/c10/c15` 0.5/1.0/1.5 mm 45 degree chamfer on the two long bottom edges; `a10` the same on all four bottom edges (a05/a15 also exist); `r294/r290` the lowest 3 mm narrowed to 29.4/29.0 mm; `rail` a stacking tongue and groove (top tongue along the full length, 10 mm wide at the base, 6 mm at the top, 2 mm high; bottom groove 12 mm mouth, 8 mm at the roof, 2.4 mm deep; one layer is then 28 mm high); `c10rail` both. **The pads touch the box only 18.1 mm or more above its bottom (measured in the squeezed scene), so chamfer, relief and groove (all within 3 mm of the bottom) never reach the pad band: the grip width stays 30 mm and the jaw is unchanged.**
- Mass: same effective density as today's printed 16 g 3-cell container (593 kg/m3: 16 g over 27 cm3, a hollow or low-infill print; an assumption, not measured). Chamfers 15.95-16.0 g, r294 15.97 g, r290 15.95 g (7.18 / 11.75 / 15.95 g for 1/2/3 cells), rail 14.79 g. Each variant ran at its own mass.

### MuJoCo results (layer 1 on the dots, friction 1.0, yaw 0, 31.5 mm opening unless noted; both signs of the offset)

3,942 cases: strategy x opening 33/31.5 mm x 9 variants; layer 1 yaw 0/3 degrees, friction 0.5/1.0, 17 offsets 0-1.5 mm; layer 2 offsets 0/1.0/1.5 mm. Seated on the first try, out of 2 (one per sign):

| Variant, strategy | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 | 0.8 | 1.0 | 1.5 mm | band mm |
|---|---|---|---|---|---|---|---|---|---|
| plain, drop | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0.6 |
| plain, guarded | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0.6 |
| plain, search | 2 | 2 | 2 | 2 | 1 | 0 | 0 | 0 | 0.5 |
| plain, drop, 33 mm opening | 2 | 2 | 2 | 1 | 0 | 0 | 0 | 0 | 0.4 |
| c05, guarded | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 0.8 |
| c10, guarded | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 0 | 0.6 |
| c15, guarded | 2 | 2 | 2 | 0 | 1 | 0 | 0 | 0 | 0.4 |
| a10, guarded | 2 | 2 | 2 | 2 | 2 | 1 | 0 | 0 | 0.6 |
| r294, guarded | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 1.0 |
| **r290, guarded** | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | **1.0** |
| r290, drop | 2 | 2 | 2 | 2 | 2 | 2 | 2 | 0 | 1.0 |
| rail, guarded | 2 | 2 | 2 | 2 | 2 | 0 | 0 | 0 | 0.6 |

(band = largest offset up to which every grid offset seats on both sides; the zero offset seats everywhere.) At friction 0.5 the plain box seats to 1.0 mm and r290 to 1.5 mm. **Yaw 3 degrees seats 3 of 54 cases at zero offset for every variant and strategy: none of this fixes yaw** (as in Step 3a, the box is 4.7 mm wider across at 3 degrees than the 30.8 mm gap). Layer 2 seats every variant at offsets up to 1.0 mm; at 1.5 mm it fails the 1.5 mm xy rule (plain 2 of 12, r290 and chamfers 6 of 12, rail 5 of 12). Re-place: at yaw 0, 89 % of first failures seat on the second try (drop 81 %, guarded 93 %, search 93 %) **assuming the re-placed command is within 0.2 mm of the channel centre, the accuracy the first try lacked**; without better centring the re-place does not help.

### Findings

1. **A relief foot is the cheapest large win.** Narrowing only the lowest 3 mm (the dot height) to 29.0 mm widens the first-try band from 0.6 to 1.0 mm at the CAD clearance, with no change to grip faces, pads, plan, plate or controller. 29.4 mm gives most of it. A 0.5 mm chamfer adds at most 0.2 mm; 1.5 mm hurts (the box edge slides on the chamfer and tilts).
2. **Strategy matters little.** Guarded descent over drop adds 0 to 0.25 mm; the lateral search is slightly worse (the 0.6 mm preload under a light pinch tilts the box on the dot). The chamfered dot top already pushes an edge-on-dot box into the channel when the jaw opens. The 31.5 mm opening beats 33 mm (0.6 against 0.4 mm).
3. **The tongue and groove does not help layer 1** (the groove sits above the dots) and costs 2 mm per layer (28 mm pitch: plan and tolerances change). In layer 2 it centres the box (1.5 mm offset: 5 of 12 against 2 of 12) but layer 2 already seats to 1.0 mm.
4. **Clearance sensitivity** (first-try band in mm, friction 1.0, yaw 0, 31.5 mm opening, clearance per side 0.2 / 0.5 / 1.0 mm): plain drop 0.25 / 0.5 / 1.0; plain guarded 0.25 / 0.75 / 1.25; c05 guarded 0.5 / 0.75 / 1.25; **r290 guarded 1.0 / 1.25 / 1.75**; r290 drop 0.75 / 1.25 / 1.75; rail guarded 0.25 / 0.75 / 1.25. The plain band follows the clearance, the relief foot adds 0.5-0.75 mm, guarded 0-0.25 mm. MuJoCo was optimistic against Isaac in Step 3b (Isaac failed at 0.2 mm where MuJoCo seated to 0.5 mm), so every band is an upper bound.

### Isaac confirmation (seed 42, three layers, `e51d9f1a62`, 31.5 mm opening, KAN-108 plate)

Offsets are across the channel; the first-layer boxes decide. Five runs (about 2 min when the first box fails, 30 min for 9 boxes):

| Case | Container, release | MuJoCo said | Isaac |
|---|---|---|---|
| nominal (`a9d31a94aa`, run fb168d3d) | plain, drop, 33 mm | seats | 9/9 |
| `y060-g315` (run 652ddd9e) | plain, drop, 0.6 mm | band edge (0.6) | **1 placed**: box 0 left 1.10 mm high on a dot (tilted), fails the 0.5 mm seat check |
| `y060-guard-g315` (run abb1bfce) | plain, guarded, 0.6 mm | band edge (0.6) | **1 placed**: the guard stopped the box 2.3 mm up on a dot edge after 6 steps (contact at box z 97.31 mm against the 95.0 mm seat), then it rested 1.08 mm high after opening |
| `r290-g315` (run on the same SHA) | relief foot 29.0, drop, 0 | seats | **9/9**, row gaps 5.72-6.14 mm, nothing unstable: the foot does not disturb the grip, carry or stack |
| `y080-r290-g315` | relief foot, drop, 0.8 mm | seats (plain fails) | **9/9**, row gaps 5.74-6.00 mm, nothing unstable |
| `y100-r290-guard-g315` | relief foot, guarded, 1.0 mm | seats | boxes 0 and 1 seated (the guard met a dot edge at 2.3 mm in both, then the box dropped in on opening); stopped at box 2 by `cube release correction did not converge; opening blocked`, the planner's 1.5 mm convergence check, not a seating failure. Inconclusive for 1.0 mm. |

So in Isaac, as in MuJoCo, a plain container fails by 0.6 mm (clearance 0.4 mm) whether it is dropped or lowered to contact; the guard does not rescue it, because the edge lands on a dot and the box stays tilted when the jaw opens. The relief foot seats a 0.8 mm offset at 9/9 where the plain container already failed at 0.6 mm (Isaac plain was not re-run below 0.6 mm on this plate). Not run: plain at 0.4/0.5 mm on the CAD plate (the boundary), seeds 43-45, layers 2-3 off-centre (judged only by the 1.5 mm rule), yaw.

The guarded descent code in Isaac stops on box height (a stall of less than 0.2 mm in a 0.5 mm step), not on force, and presses the box one step (0.5 mm) into what it met before lifting a step; that preload was not examined.

### Recommendation

- **Container (Isaac-confirmed at 0.8 mm):** a relief foot, the lowest 3 mm of every container narrowed from 30.0 to 29.0 mm (29.4 mm if 29.0 weakens the print), full length, equal to the 3 mm dot height. The 27 mm above stays 30.0 mm, so the jaw grips the same faces. Optional and cheap: a 0.5 mm 45 degree chamfer on the lower edge of the foot step. Skip the stacking tongue unless the real cell shows lateral drift on layers 2 and 3.
- **Printable spec (r290):** outer 90.0 x 30.0 x 30.0 mm (30 and 60 mm containers: same section); foot: 3.0 mm tall from the underside, 29.0 mm wide (fallback 29.4), full length, step to the body sharp or a 0.5 mm chamfer; body above 3.0 mm: 30.0 mm wide as today; the two 30.0 mm gripping faces stay at least 12 mm tall from the top edge down (the pads touch from 18.1 mm above the bottom up). Print with the underside on the bed so the foot is the first layers, no supports.
- **Release:** keep the open-at-the-seat release with the 31.5 mm opening. Add the guarded descent only as the contact check (it yields the height-at-contact signal for the seat check and costs nothing at nominal). Do not use the lateral search. Seat check plus one re-place stay as the safety net; the re-place must be centred on the measured box position, not the original command.
- If the real clearance is 0.5 mm per side the plain container tolerates 0.5-0.75 mm and the relief foot makes it 1.25 mm; at 1.0 mm nothing is needed for the 0.3-0.5 mm the top camera can give. Measure the dot diameter and pitch with a caliper: the result moves one for one with the clearance.

### Assumptions

Dot geometry from the KAN-108 CAD; friction 1.0 (0.5-1.2 swept); container density from today's 16 g; floating welded jaw, no arm compliance or controller noise; contact threshold 0.05 N at 5 mm/s, rigid hold while lowering; real contact sensing (motor load or jaw height) is not designed. The MuJoCo strategy tests are skipped on the remote hosts (no MuJoCo there); their logic was run by script on the laptop.


## Step 4b — Isaac boundary on the CAD plate (2026-11-01, commit 1129a9da04)

31.5 mm opening, drop release, seed 42 unless noted. "dy" is the across-channel offset from the target, positive toward the centre row for box 1.

| Case | Result | Failing box after opening |
|---|---|---|
| plain y040 | 2 placed | box 1 released at +0.40, ends +0.11 / 1.84 mm high / roll 1.70 deg on the dot between rows |
| plain y050 | 2 placed | box 1 ends +0.14 / 1.89 mm high / roll 1.42 deg |
| r290 nominal, seeds 43, 44, 45 | 9/9 each | none |
| r290 y100 | 2 placed | box 1 released at +1.00, ends +0.78 / 1.93 mm high / roll 1.94 deg |
| r290 y-080 | 1 placed | box 0 released at -0.80, ends -1.07 / 0.01 mm high / roll 0.36 deg, not settled in the window |

- The Isaac seat band tracks the geometry, not the MuJoCo band. The plain container fails at 0.40 mm, which is the CAD side clearance (0.40 mm per side). MuJoCo said 0.6.
- The relief foot adds its 0.5 mm per side: r290 seated +0.8 (Step 4) and failed +1.0, whose foot margin is 0.9 mm. Toward the neighbouring row the box at -0.8 slid another 0.27 mm onto the foot margin and did not settle, so the r290 band is about ±0.7 mm, not 1.0.
- The failures are the box edge resting on a dot (1.8-1.9 mm high, 1.4-1.9 deg roll), the same mode as Step 3b.
- r290 nominal is 9/9 on four seeds (42-45).

## Step 4c — seeds, finer offsets and yaw on the CAD plate (2026-11-02, commit 3921d2aa65)

Same scene as Step 4b (31.5 mm opening, drop release, three layers). Offsets are across the channel in mm; "2 placed" means box 1 rested on the dot between rows and the first layer stopped. Runs went through `tools/remote/isaac_batch.py` on the model PC and the AI PC (D-958 stage 1).

Plain container:

| Offset | seed 42 | seed 43 | seed 44 |
|---|---|---|---|
| 0 | 9/9 (Step 4b, seeds 42-45) | 9/9 | 9/9 |
| +0.2 | 9/9 | 2 placed, box 1 off 1.06 | 9/9 |
| -0.2 / -0.3 | 9/9 / 9/9 | not run | not run |
| +0.3 | 2 placed, box 1 off 1.12 | 2 placed, 1.10 | 2 placed, 1.07 |

Relief foot r290:

| Offset | seed 42 | seed 43 | seed 44 |
|---|---|---|---|
| +0.6 / +0.7 | 9/9 / 9/9 | 9/9 / 9/9 | 9/9 / 9/9 |
| +0.8 | 9/9 (Step 4) | 9/9 | 9/9 |
| -0.6 | 9/9 (rerun on the model PC) | 9/9 | 9/9 |
| -0.7 | 9/9 (box 8 settled 0.79 off) | not judged: tabletop leveling failed before the place | not run |

Yaw at release (seed 42, zero offset; row gap band 4.5-7.5 mm):

| Container | 0.5 deg | 1.0 deg |
|---|---|---|
| plain | 9/9, row gaps 4.9-5.5 mm | 2 placed, box 1 off 1.08 |
| r290 | 9/9, row gaps 4.9-5.2 mm | 9/9 seated, row gaps 4.1-4.6 mm: fails the gap band |

- Plain: the one-try band is about 0.2 mm and not reliable there (seed 43 failed at +0.2); +0.3 fails on every seed. That is half the 0.40 mm side clearance.
- r290: +0.8 seats on three seeds, -0.6 and -0.7 seat where judged, +1.0 and -0.8 fail (Step 4b). The band is about -0.7..+0.8 mm; plan with ±0.7 mm.
- Yaw must stay within 0.5 deg. At 1 deg the plain box rests on a dot, and r290 seats but the rotated boxes push the row gaps below the band.
- One AI PC run (y-060 r290 seed 42, run 4fe8) ended without a confirmed result (cleanup unobserved, status UNKNOWN) and was rerun on the model PC. The batch tool polled it for 11 h; it now sets such a run aside and retries it.
