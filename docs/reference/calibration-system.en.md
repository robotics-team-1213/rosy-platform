# Calibration System — Code · Screens · Procedures · History

한국어: [calibration-system.md](calibration-system.md)

Status: reference date 11-20 · 22 code modules · 27 calibration jobs · screens use sample data

## 1. Summary

Core conclusion: the calibration app, engine, and site automation are tied to one path.
The calibration app and Fleet screens handle requests, answers, and approvals. The engine writes measurement, judgment, and records to files.
From 10-19 to 11-18 the team ran 27 calibration jobs. It re-measured the ceiling camera, cell heights, joint gains, and TCP values.
Automatic ceiling track calibration runs every 2 minutes. People only judge and approve.
Remaining work: an authoritative top lens K, arm_a pallet recalibration, and per-tier real-hardware verification.

## 2. Flow

![Figure 1 [screen] Calibration flow: person · engine · screens · timer](../assets/calibration/flow-calibration.png)

The figure shows the roles and order of the person, engine, screens, and timer in the calibration flow. A person-approval item opens as a screen request.

1. (Person) Prepare. Attach printed markers and hold the ChArUco board.
2. (Engine) Measure. cell_depth.py · cell_frame.py · cell_calibrate.py take real measurements.
3. (Engine) Arm motion is supervised testing only. A person checks the switch for every motion.
4. (Engine) Write result files: calibration_path JSON, bias.json, camera model JSON.
5. (Engine) Judge. cell_calibrate.py check lists the remaining work items.
6. (Engine) Open person-confirmation items as requests. cell_requests.py writes a predicted value for each candidate.
7. (Screen) Show the request list and figures. Viewing needs a site login session.
8. (Person) Log in and enter the answer. The answer needs the calibration.operate permission.
9. (Screen) Call only cell_requests.answer. by is the session name. It does not write files directly.
10. (Engine) Apply by re-running the matching step. People do not edit numbers by hand.
11. (Timer) Run automatic ceiling track calibration every 2 minutes. It asks Fleet for an update.

## 3. Safety boundaries

WARNING: The arm-motion steps are D-911 supervised tests. A person confirms being next to the switch for every motion. Without person_at_switch the server refuses with 422.

WARNING: Do not create a general setting that widens guard limits. Planned floor lowering is allowed only in person-approved low_zones rectangles.

CAUTION: Do not edit numbers by hand. To re-measure, re-run the matching step.

CAUTION: The screen write path requires the same origin and the calibration.operate permission. by comes from the session name.

CAUTION: Values on the Fleet calibration screen are display-only. They do not pass into sighting, CameraMap, or driving.

CAUTION: Automatic track calibration changes only calibration and map records. It issues no motion commands.

## 4. Code layout

The 22 modules divide into screens, engine, contracts, and site automation.

### 4.1 Screens (8)

| Module | Location | What it does | Lines |
|---|---|---|---|
| Calibration screen server | applications/calibration/calibration_web.py | Serves the request · profile · job API on loopback | 379 |
| Grid-paper renderer | applications/calibration/web/grid.js | Draws the overhead-camera overlap figure and an arm-relative meter grid | 590 |
| Screen assembly | applications/calibration/web/app.js | Bundles the profile · hygiene · map · bias screens | 561 |
| Request UI | applications/calibration/web/requests.js | Connects the request list and answer input to the Account session | 252 |
| Field view | applications/fleet/web/calibration/field-view.js | D-360 proposal review · field view · layer toggles | 312 |
| Field math | applications/fleet/web/calibration/field-layers.js | Pure layer · homography math. No DOM | 136 |
| Map fit view | applications/fleet/web/calibration/map-fit-view.js | Shows D-375 lane overlap and map plane unwrapping | 531 |
| Measured calibration view | applications/fleet/web/calibration/measured-calibration-view.js | Shows D-775 preview approval and apply confirmation | 195 |

### 4.2 Engine (9)

| Module | Location | What it does | Lines |
|---|---|---|---|
| Cell calibration tool | deploy/robot/omx/cell_calibrate.py | Judges stale items and re-measures only the needed steps | 383 |
| Self calibration | deploy/robot/omx/cell_calibrate_auto.py | Does pivot-point choice, self calibration, and bias learning | 293 |
| Map recording | deploy/robot/omx/cell_calibrate_bound.py | Records a remap and a reference JPEG as a pair | 69 |
| Pixel coordinate transform | deploy/robot/omx/cell_calibration.py | Computes per-surface homographies and LOO error | 204 |
| Snapshot builder | deploy/robot/omx/cell_calibration_view.py | Builds a read-only bundle for the grid paper | 399 |
| Height measurement | deploy/robot/omx/cell_depth.py | Measures surfaces, heights, and FK zeros from depth frames | 399 |
| Camera model | deploy/robot/omx/cell_frame.py | Keeps camera pose and marker locations from markers | 369 |
| Checkerboard geometry | deploy/robot/omx/cell_checkerboard.py | Solves intrinsics, hand-eye, and camera pose | 348 |
| TCP decision | deploy/robot/omx/omx_tcp.py | Sets the gripper TCP length in settings → plan → environment order | 63 |

### 4.3 Contracts (2)

| Module | Location | What it does | Lines |
|---|---|---|---|
| Calibration record store | contracts/foundation/core_common/calibration_store.py | Keeps per-robot immutable records and status events | 455 |
| Measured calibration bundle | contracts/foundation/core_common/protocol/measured_calibration.py | Validates D-775 candidate bundles. No command authority | 155 |

### 4.4 Site automation and agent procedure (3)

| Module | Location | What it does | Lines |
|---|---|---|---|
| Automatic track calibration | deploy/site/rosy-auto-track-calibration | Judges and applies ceiling-camera track calibration | 495 |
| Run timer | deploy/site/host-state/rosy-auto-track-calibration.timer | Schedules the run every 2 minutes | 11 |
| Skill card | .claude/skills/rosy-calibration/SKILL.md | Writes the agent run order and forbidden rules | 54 |

## 5. Screens

CAUTION: Screen data is sample data. It is not a real calibration result.

![Figure 2 [screen] Calibration app measured request (sample)](../assets/calibration/s-calib-requests.png)

The screen for viewing the measured-request list and entering answers.

![Figure 3 [screen] Fleet install › camera calibration (sample)](../assets/calibration/s-fleet-camera.png)

The section of the Fleet install screen that handles camera installation and calibration.

![Figure 4 [screen] Fleet measured camera correction section (sample data)](../assets/calibration/s-fleet-measured.png)

The Fleet section for checking measured camera correction candidate status.

![Figure 5 [screen] Measured request screen at 390 width (sample)](../assets/calibration/s-calib-requests-390.png)

The same measured-request screen at a narrow 390 px width.

### 5.5 Cell camera layout (real observation, 11-20)

The cell console (`/console/cell`) section "OMX dual follower observations" shows the latest raw frames of the six cameras.

| Card | Role | Camera | Used by |
|---|---|---|---|
| Overhead | top | RealSense D435 (8086:0b07) | camera model · map (S3·S6) |
| Arm S top (S3) | arm_s_top | Jieli (4c4a:4a55) | camera model · map (S3·S6) |
| Cell side (A/B) | side | Jieli (4c4a:4a55) | stacking height · side lens |
| Arm A wrist | arm_a_wrist | Innomaker U20CAM-720P (0c45:6367) | grasp check |
| Arm B wrist | arm_b_wrist | Innomaker U20CAM-720P (0c45:6367) | grasp check |
| Arm S wrist | arm_s_wrist | Innomaker U20CAM-720P (0c45:6367) | grasp check |

![Figure 15 [real] Six cell console cameras (11-20 03:00)](../assets/calibration/cam-console.png)

The six console cards show the latest raw frame of each camera.

![Figure 16 [real] Raw top camera frame (D435)](../assets/calibration/cam-top.jpg)

A raw frame of the top camera (D435).

![Figure 17 [real] Raw side camera frame (Jieli)](../assets/calibration/cam-side.jpg)

A raw frame of the side camera (Jieli).

### 5.6 11-20 calibration check results

| Setup | todo | Camera shift | Verdict |
|---|---|---|---|
| arm_a | none | 3.1 px · none | pass |
| arm_b | remap·regions | 2.6 px · none | remap·regions·5 maps remain |
| Cell S | remap·regions | 46.0 px · yes | recalibrate |

CAUTION: The Cell S camera moved 46 px and needs recalibration.

NOTE: The current link on the cell PC is broken.

## 6. Procedures and acceptance criteria by calibration type

### 6.1 Cell six steps (devices · heights · camera model · surfaces · joint gains · check)

- Input: cell setup JSON. D435 Z16 and color frames. Session caps.json. Gripper-marker photos of FK points.
- Output: table surface, depth-to-color alignment, surface heights, arm-plate FK zeros. Camera pose and marker locations. Loaded joint I gains. check result JSON.
- Acceptance criteria (numbers): 0 device problems. Layer check rms 1.5 px or less, max 2.5 px or less. Height error within 1.5 mm. Joint I gain 50. TCP error 12.3 mm without gains, 3.3 mm with gains. 0 remaining check items.
- Owner files: `cell_depth.py` `cell_frame.py` `cell_calibration.py` `cell_calibrate.py` `SKILL.md`

### 6.2 ChArUco lens

- Input: printed board 7×10 squares · 20 mm squares · 15 mm markers · DICT_4X4_50. Measured 50 mm bar length. RGB frames.
- Output: K · distortion · resolution JSON. Raw frame folder and a source receipt.
- Acceptance criteria (numbers): request 30 frames. 25 or more valid images. Reprojection RMS 0.5 px or less. Below that, accepted false and exit code 1.
- Owner files: `cell_checkerboard.py` `applications/calibration/README.md`

### 6.3 Ceiling camera map fit and automatic track calibration

- Input: lane-paint homography proposal. Corner 4-point time series. Fleet current calibration. An auth token.
- Output: approval verdict JSON. Fleet calibration and map update requests. A status file.
- Acceptance criteria (numbers): corner shift over 0.015 m triggers calibration update. Location error over 0.012 m triggers map update. 5 samples. Spread 0.025 m or less. Approval interval 600 s or more.
- Owner files: `deploy/site/rosy-auto-track-calibration` `host-state/rosy-auto-track-calibration.timer` `map-fit-view.js` `field-view.js` `field-layers.js`

### 6.4 Measured calibration records

- Input: lens and floor candidates. 8 or more training frame hashes and 2 or more verification hashes. Survey hash. Capture signature and rotation.
- Output: a rosy.measured-calibration/1 bundle and its sha256 digest. D-47 store records and events.
- Acceptance criteria (numbers): candidates stay unapplied. revision matches the content hash. The bundle digest matches the full content. Size 200000 characters or less. Floor inliers 4–10000. A person accepts.
- Owner files: `measured_calibration.py` `calibration_store.py` `measured-calibration-view.js`

### 6.5 Arm lease calibration jobs (D-1035)

- Input: cells.json (tools · python · work · arms). POST body arm · step · targets · person_at_switch.
- Output: a 202 response and a jobs record JSON · log. assessments.jsonl. Incident release.
- Acceptance criteria (numbers): step allows only 4 kinds. Motion steps require person_at_switch true. Lease expires in 1800 s. Release needs a clear verdict within 600 s. Evidence is a frame · joints hash match.
- Owner files: `calibration_jobs.py` `calibration_web.py` `cell_calibrate.py` `cell_arm_lease.py`

### 6.6 Site procedures (person / tool split)

Cell arm (OMX) calibration. D-951 owns the order. Each step leaves a file.

WARNING: In arm-motion steps a person confirms every motion next to the switch (D-911).

1. (Person) Print the D-933 sheet at 100% matte.
2. (Person) Check the print size with a 50 mm bar.
3. (Person) Attach markers to the gripper and base.
4. (Person) Attach four surface markers each to the belt and pallet.
5. (Tool) Check devices and cameras (omx_devices scan, omx_cameras).
6. (Tool) Fit the table plane (cell_depth).
7. (Tool) Align the depth and color frames.
8. (Tool) Produce plate heights and per-surface surface_z for each arm.
9. (Tool) Build the camera model from markers (cell_frame learn/check).
10. (Person) Approve the floor-lowering rectangles and values (low_zones).
11. (Session) Write I gain 50 to wrists and elbows. Restore afterwards.
12. (Tool) Check the map with leave-one-out (cell_calibrate check).
13. (Tool) Refuse to save when LOO exceeds 15 mm.
14. (Person) Measure verdict targets with a tape and eyes. The tool pre-writes a predicted value per candidate.
15. The verdict criterion is an average of 3 mm or less.

Joint-zero procedure. Panel verdict on 11-18. As of 11-19 the implementation is at branch stage.

1. (Person) Attach 2 base markers at least 90 mm apart.
2. (Person) Tape-measure the marker arm coordinates (error 0.3 mm or less).
3. (Tool) Capture a pose per camera name.
4. (Tool) Seed from base-marker PnP.
5. (Tool) Solve 5 zeros and camera 6-DOF.
6. (Tool) Compare predicted σ against the 0.25° gate.

Ceiling camera calibration.

1. (Person) Place the camera so the whole track is visible.
2. (Tool) Check camera null with the Fleet tracking API.
3. (Tool) Overlay the approved calibration on the frame to see the offset.
4. (Tool) Try console map auto-fit. The tool refuses with 0.50 because the drawing is old.
5. (Tool) Register the current frame to the world_261026 drawing (`rosy_vision.map_register`).
6. (Tool) Remove the parking area (y over 0.20 m) from the drawing.
7. (Person) Check lanes and cells by eye in the overlap figure.
8. (Person) Approve the new fit (D-595). On 11-18 an agent operator account approved on user instruction.
9. (Tool) Upload the calibration (POST /api/fleet/calibrations).
10. (Tool) Confirm Vision adoption and drift checks.
11. (Tool) Do not use --force. It overwrites site map location coordinates.

Rollback: send the same POST with the previous map_to_image.

CAUTION: If the robot stands on the pink line, the seed goes wrong. On 11-18 the seed came from a Vision proposal (5-frame mean).

Side and top lens (ChArUco).

1. (Person) Hold the ChArUco board and vary the pose.
2. (Person) Cover the screen edges down to the bottom row.
3. (Tool) Skip photos with the same pose (cell_checkerboard).
4. (Tool) Guide on empty squares, center shift, and distance change.
5. (Tool) Stop at 25 frames when the criteria are met.
6. (Tool) Refit without tangential distortion.
7. (Tool) Refuse when f changes by more than 3%.
8. (Tool) Read the D435 factory K (cell_device_intrinsics read).
9. (Tool) Record only when the tilted-photo fit matches the factory K (verify).
10. (Person) Place the board on the table and the container tiers 1–3. Take 2–3 photos per tier (cell_focal_heights).
11. (Tool) Measure f separately per height.

NOTE: The 11-13 capture was one pose and was refused. Steps 10·11 have a tool but no real-hardware run.

Map registration (R2S).

1. (Tool) Capture top · side · both wrists, 4 frames.
2. (Tool) Detect camera shift with 4 anchors.
3. (Tool) Correct eye position and rotation.
4. (Tool) Compute plate · belt · base residuals.
5. (Tool) Draw the corrected sim over the real photo.
6. (Person) Check the overlap figure by eye.
7. (Person) Screen candidates with tape-measured values (measured requests).
8. (Tool) Run the policy gate.
9. (Tool) The gate checks camera alignment, cell shape, MuJoCo 9/9, Isaac 9/9, and D-911.
10. (Tool) Issue an approval token.

NOTE: The 11-11 gate pass is sim evidence. It is not real-hardware acceptance.

## 7. Calibration history

| Date | Target | What was done | Result | Evidence |
|---|---|---|---|---|
| 10-19 | top camera | Measured gamma · exposure through the adjustment service | gamma 10→20. One exposure step is 1 µs | real |
| 11-01 | Ceiling camera · map | Enabled world_261026 map v7. Approved paint-be3b1dc1c21f with ICP | corners ±1.22×±0.61 m. Old 2.81×1.26 m was 15% large in scale. ICP mean 1.9 px. Lens k1 -0.02 | real |
| 11-01 | Cell heights (depth) | Measured table plane and surface heights with D435 depth (D-951) | pallet 10–11 mm. 2-tier stack 75–79 mm. belt -29–-35 mm. left-arm plate 20.9 mm. 4.5 s per run | real |
| 11-01 | Gripper position (touch) | Tried measuring a belt container with a closed-gripper touch | failed. The 16 g container was pushed into a gap beside the rail. Do not use touch for light objects | real |
| 11-01 | Joint gains | Gave I gain 50 to wrists and elbows as a session setting | left-arm belt-end TCP error 12.3→3.3 mm | real |
| 11-01 | Left-arm belt map | Built a map from markers and checked with leave-one-out (LOO) | LOO 2.56 mm. Outside the marker range is unmeasured | real |
| 11-03 | arm_b gripper TCP | Measured the v2.1 gripper tip with box touch and STL | 0.0740 m. Replaces stock 0.09193 m (18 mm high when computed). Contact point 16.6 mm | real |
| 11-03 | top · side cameras | top: 25-bump PnP, side: lens survey | top 0.58 px (f 615 assumed). side f 950 (lower bound, replaced on 11-14) | real |
| 11-04 | arm_a pallet | Ran cell_calibrate auto three times | unresolved. LOO max 52 mm · 35.5 mm · 3 flagged items. None of the three saved. Cause: wrist cable loop | real |
| 11-05 | Ceiling camera | Changed calibration to paint-a316b0628833. Removed the parking area from the drawing and registered 2 frames | fit 0.86. Precision 0.88. Rotation 6.0°. Replaced on 11-18 | command-response |
| 11-08 | top · side resurvey | Re-solved both camera poses from the current frame | top rotation 1.04° · 61 points 1.25 px rms. side 4.1° · 8 points 0.9 px rms. Low confidence. Not used in map math | real |
| 11-08 | Table FK height | Re-solved with a container touch inside the base bay and an empty-table descent | -8.3 mm (±2). Replaces the old -19.7 mm. Cause candidates: zeros · sag (unresolved) | real |
| 11-09 | Joint zeros (arm_b) | Tested a zero candidate over 48 live top-camera runs | top error 10.2→2.8 px (limit 3 px). Candidate +4.0/+1.0/+3.2/+2.8/+2.4° | real |
| 11-09 | Calibration health watch | Built drift watch (D-1006) and the measured-request engine | first request: belt tape distance. Candidates 156 · 215 mm. Tolerance 20 mm | document |
| 11-11 | R2S map registration | Corrected overhead camera shift with 4 anchors | error 39.86→2.53 mm. Eye shift (-20.5, 42.0, -3.1) mm. Policy gate pass | real |
| 11-11 | 3-tier stacking verification | Built a code success verdict from side · top target-region ROIs (D-1014) | side 3-point calibration applied. Not real-hardware acceptance | real |
| 11-13 | top K · lens | Compared 60 hand-held ChArUco frames with D435 factory values | 60 frames were one pose. f 1229–2813 unstable. Factory fx 618.53. Depth height 596.6–597.0 mm | command-response |
| 11-13 | side lens | Fit the lens with the moving-2214 bundle | f 898–906. Error 0.2 px. Bottom 3 rows of the frame empty | real |
| 11-14 | ChArUco reuse | Tried calibration from existing captures | refused. side lacked vertical range. top had the board fixed at center | real |
| 11-14 | Pink tape threshold | Changed the threshold with the measured HSV panel | H 145-179 · S≥35 · V≥60. The old value detected 0%. rosy_45 value unconfirmed | real |
| 11-14 | Support plate gap | Reviewed photo reading 189.8 mm and decision 190 mm | fixed at 194 mm on 11-18. 190 · 189.8 mm replaced | document |
| 11-15 | top vanishing center | Measured A · B centers from the vertical vanishing point | A (309,373). B (297,361). Replaces old (320,240) | real |
| 11-15 | Three-arm TCP | Changed the cell PC env to 0.0740 m (with backup) | arm_a has no arm-specific measurement (estimated). arm_s unconfirmed | real |
| 11-15 | arm_b floor map | Tested a 6-point remap option E | LOO mean 1.05 mm · max 1.37 mm. Operating map 3.12 · 5.16 mm. Option E unconfirmed | real |
| 11-18 | Ceiling camera | Approved drift stale (0.361 m · 6.29°) with a mean of the last 5 fits | paint-92036a5c0dbc. drift 0.026 m · 0.53° | command-response |
| 11-18 | Ceiling camera re-aim | The camera had turned back about 4°. Revived the calibration at 21:40 | paint-2ff28bdb06be. rms 2.3–2.8 mm. drift 0.093 m · 0.17° | command-response |
| 11-18 | Joint-zero common procedure | The panel set the zero procedure for all arms | base marker gap 90 mm or more. j1 1σ 0.85°→0.16° (surrogate model) | sim |

![Figure 6 [real] Arm stopped 40 mm above a container (11-01)](../assets/calibration/c-hover-top.jpg)

A real photo of the left arm stopped 40 mm above a container on the belt.

![Figure 7 [screen] Depth frame: arm · stack · table heights separated (11-01)](../assets/calibration/c-depth.jpg)

A depth frame with arm, stack, table, and pallet heights separated.

![Figure 8 [screen] Depth edges aligned with the color frame (11-01)](../assets/calibration/c-edge-align.jpg)

An alignment check where depth-height edges overlap the color frame.

![Figure 9 [screen] Old ceiling calibration: one cell shifted (11-04)](../assets/calibration/c-ceiling-before.png)

The old ceiling calibration projection with one grid cell shifted.

![Figure 10 [screen] New ceiling calibration projection: lane match (11-04)](../assets/calibration/c-ceiling-after.png)

The new ceiling calibration projection matching the lanes.

![Figure 11 [screen] Before calibration: 39.86 mm error (11-11)](../assets/calibration/c-r2s-before.png)

The pre-calibration sim projection offset 39.86 mm from the real top view.

![Figure 12 [screen] After calibration: 2.53 mm error (11-11)](../assets/calibration/c-r2s-after.png)

The post-calibration view with the error reduced to 2.53 mm.

![Figure 13 [screen] top resurvey: old · new poses (11-09)](../assets/calibration/c-resurvey.png)

The top camera old pose (red) overlaid with the new pose (green).

![Figure 14 [real] Side camera ChArUco capture (11-13)](../assets/calibration/c-charuco.jpg)

One frame from the 114-frame side-camera ChArUco capture bundle.

## 8. Current calibration values

Core five:

- arm_b gripper TCP 0.0740 m. Replaces stock 0.09193 m (11-03).
- Wrist and elbow joint I gain 50 (11-01).
- Ceiling camera paint-2ff28bdb06be. drift 0.093 m · 0.17° (11-18).
- Table FK height -8.3 mm. Replaces the old -19.7 mm (11-08).
- Support plate gap 194 mm (fixed 11-18).

## 9. ADRs

| ADR | Title | Decision in one line |
|---|---|---|
| D-951 | ROSY Calibration app and one cell calibration path | Set app · engine · skill boundaries and run calibration as one order |
| D-1004 | Calibration screen and operate permission | Put Account login on the loopback screen and require calibration.operate for answers |
| D-1006 | Calibration health | Notice map and calibration drift early. Automatic recalibration keeps a rule only |
| D-1007 | Robot correspondence-point calibration candidates | Build review candidates from robot frames. Do not apply them |
| D-1035 | Arm lease · calibration jobs · AI verdicts | Give each arm a lease and an evidence-based incident release path |
| D-933 | Arm S cell coordinate markers | Use one camera model and printed markers per surface instead of maps |
| D-633 | Measured camera correction | Record a correction method for heavy distortion and partial views |
| D-595 | Accepted map calibration is fixed | Accepted calibrations stay fixed. Re-fitting uses the fixed tool only |
| D-484 | Field boundary auto calibration | Promote the field_boundary source to the measured acquisition path |
| D-321 | Site calibration · G4 in one session | Collect calibration and G4 in one attended session. Map generation starts after approval |
| D-397 | URDF NOMINAL geometry | The URDF sets reference values; per-robot calibration refines them |
| D-47 | Sensor adapter calibration binding | On startup, verify and apply a calibration record matching device and generation |

## 10. Completeness check and remaining work

### 10.1 Step verdicts (11-19 panel)

Codex and opencode audited in 2 rounds. The completeness bar is main code, tests, wiring, deployment, and one real-hardware pass.

| Step | Verdict | Reason |
|---|---|---|
| S1 devices | complete · site incident | 11-20 USB recovery, 6 cameras confirmed |
| S2 heights | complete | cell_depth · tests · 11-01 measurement |
| S3 camera model | partial | no real-hardware record of top lens K approval or 30/60/90 mm tier checks |
| S4 surface surface_z | partial | table record exists, arm_a pallet recalibration unresolved |
| S5 joint gains | partial | 11-01 TCP 12.3→3.3 mm, current caps applied value unconfirmed |
| S6 check | partial | arm_a todo [] passed (11-20). arm_b · Cell S keep remap·regions |
| S7 measured requests | partial | request→answer→display wired, apply is commit-only (design), no real-hardware full run record |
| S8 jobs · lease | partial | D-1035 code and tests exist, no site active setting or job receipts |
| S9 automatic check | broken | job API · CLI not landed, site engine on unlanded commit 31393b4af6 |
| S10 ceiling auto calibration | partial · owner robot-12 | old R script holds with unstable_series every run, fix branch landing |
| S11 Fleet approval→consumption | partial | 11-18 approval record, no same-revision World comparison |
| S12 dev sample | fixed · awaiting landing | camera list shape matched to {sources}, 13 remote tests passed |

CAUTION: The 11-19 site check did not run because of a cell USB hub disconnect and the old R script. Re-check after reconnection and deployment.

### 10.2 Remaining work and unconfirmed items

- Cell A·B top tilt: the 13.1° and 10.6° records conflict. Re-read the site settings to fix.
- arm_s TCP: setting 0.0885 m. The gripper type is unconfirmed.
- Gripper gap conversion (5 mm/unit): photo reading. unconfirmed.
- rosy_45 floor_paint threshold: far-distance measured value. unconfirmed.
- arm_b option E map: only the LOO 1.05 mm test. Not applied to operations.
- Authoritative top lens K: no photo meets the factory K verification conditions (tilted board · screen edges).
- Per-tier board verification (30 · 60 · 90 mm): the tool exists, no real-hardware run.
- side camera: eye position · roll · f are assumptions. Not used in map math.
- Cause of overhead camera shift: rotation 1° and shift 10 mm are not separated by parallax.
- Cause of table FK height: zero and sag candidates are not separated.
- arm_a pallet calibration: redo after cable tying and wrist camera connection.
- Zero test range: j2–j4 checked only in the park pose. arm_a has no twin.
- Pre-attendance zero values: a person measures base marker arm coordinates and gripper marker id · size · offset.
- A·B camera shared pool and wrist camera calibration: deferred.
- Ceiling auto calibration: the marker sighting path is off. The repository R code lags main.
- Calibration screen (D-1004): main merge confirmed (2026-11-17 378a39c8de). Site R and control PC deployment status unconfirmed.
- R2S 3-tier stacking: no real-hardware acceptance.
- Sample camera list shape mismatch: fixed (`fix/calibration-sample-contract`, awaiting landing).

## 11. Evidence

<details><summary>Change history</summary>

| Date | Commit | One line |
|---|---|---|
| 2026-11-17 | b1b59a5ac3 | Refuse pivot motion before detached markers, short arcs, other height geometry |
| 2026-11-17 | 6cc56e64cc | Put clear-point-first pivot behind pivot.clear_first |
| 2026-11-17 | 2bf67d10ef | Bind lease pid to boot id and check release inside the lock |
| 2026-11-17 | a0938cc067 | Addressed D-1035 independent review points |
| 2026-11-17 | 378a39c8de | Added status board, calibration jobs, AI verdicts, evidence-based release (D-1035) |
| 2026-11-17 | ce83e070b5 | Pivot on an empty point instead of above the box, pass depth to depth-verify |
| 2026-11-16 | 2577003fa4 | 3-sigma rigid drift gate · IDW bias fusion · MSAC consensus |
| 2026-11-16 | 8a1764ac00 | post-eval · depth-verify wiring and IDW blend · XY overlap |
| 2026-11-16 | a0c512494e | Defer auto calibration on busy maps and sync browser calibration |
| 2026-11-16 | 1b54c94dd1 | Reflect side XY verification and visit · dwell area detail on screen |
| 2026-11-16 | 0df5a4d69f | Scope auto track calibration eligibility and adjust spread gate |
| 2026-11-16 | 6e7e79aea5 | Stabilize ceiling_north 10-minute auto calibration and reject 1-bay misreads |
| 2026-11-16 | baa0c1b8f3 | Allow site pivot_yaws overrides for wide-arc over-target calibration |
| 2026-11-16 | 344c53a7d4 | Report over-limit bias in check · eval |
| 2026-11-16 | 87181ab14d | Remove app-only palette tokens from styles.css |

</details>

Same article: team Confluence · Notion
