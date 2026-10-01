# Camera follow evidence: Gazebo validation, 2026-10-02

Evidence tier: **ROS-SIM**, not device or field acceptance. Robot power was turned off by the operator; no payload was installed.

## Source and runtime

- Feature commit: `c521acdf`; integrated source: `67c442cc2472c5df60d09b65ed570d8ed0d26cb9`.
- WSL Ubuntu, ROS 2 Jazzy, Gazebo Harmonic, existing `/rosy_realprof_ws/install` simulation assets and CORE. The sensing Python package was explicitly overridden with `.worktrees/follow-preview/src/runtime/sensing` through `PYTHONPATH`; the probe records the imported road observer path.
- World: `map_v2_fleet_real.world`, current source `map_v2_fleet_real.launch.py`, camera `320x240`, 8 Hz requested, pitch 8 degrees, nominal height 0.06343 m and hfov 1.0334 rad. Geometry is declared **GAZEBO**, not measured device calibration.
- Isolated `ROS_DOMAIN_ID=76`, `GZ_PARTITION=rosy_follow_preview_20261002`; CORE port 8096. CORE owns final motion. Observers and the probe never publish motion.
- Added observation-only `RoadObserverNode` and `RoadStateNode` in the test process. The probe applies the product `classify_frame` and `observation_payload` to Gazebo images, publishing foreground-region evidence. This adapter substitutes for a physical capture device; it does not add object classification or tracking.
- Scratch, logs and pictures: `X:\DevTemp\rosy-follow-gazebo`. Browser evidence: `X:\DevTemp\rosy-follow-release\live\*gazebo*`.

## Observed results

Run 1: 228 raw frames, 57 preview messages. 56 previews had same-stamp follow evidence in the probe; the first arrived before its matching evidence callback. Keep strategies: both 114, right_only 33, corner_ahead 12, corner_left 69. The renderer shows selected boundaries, rejected transverse candidates, selected target, direction/error/confidence and frame-local foreground regions. Unranged regions remain explicitly unranged.

Two bounded CORE follow runs, 40 seconds wall time each, returned CAMERA_LINE TRACKING with confidence 0.6 or 0.9 and nonzero speed/steering, then accepted OFF with zero linear/angular command. These runs exercise the preview during actual simulated motion; they do not establish a full lap or lane-keeping accuracy. The second run is recorded in `run1/drive.json`.

The CORE vision status reported source GAZEBO, overlay `follow-road-v2`, available true, stale false, 320x240. The rendered console image was 320x240 with no browser page errors. `evidence-gazebo.json` records the sequence and status; `rendered-camera-gazebo.png` is the visible image.

The road shadow estimator remained STOP in 210 observations in run 1. Preview correctly suppressed the road prediction and displayed `PRED STOP`. **A valid predicted-road inset was not demonstrated by this Gazebo run.** Positive prediction geometry, STOP suppression, invalid numeric data and frame matching are covered by the focused host tests; this is a separate evidence tier.

Run 2 teleported the stationary simulated robot outside the lane to (2.0, 2.0, 0 rad): 76 raw frames, 19 previews, 18 same-stamp matches, all 76 keep observations reported strategy none / no_boundary. The rendered preview showed HOLD / no_boundary without a target guide, and PRED STOP. Foreground regions stayed available; absence of a lane was not presented as absence of surrounding regions.

The focused preview and observer-wiring tests were rerun after integration: **25 passed**.

The first probe incorrectly requested reliable preview QoS from a best-effort publisher. It received no JPEG; the probe was corrected to sensor-data QoS before the recorded run. That failed attempt is not a pass.

## Remaining gates

- Device installation/readback and live physical-camera acceptance: pending robot power-on. Native ARM64 payload build run `36878292415` succeeded for release `2026.10.01-022` at `67c442cc`; download completed, but ABI verification could not resolve the powered-off robot, so signing/activation did not proceed.
- Full CI is not green: run `36883251253` at `65c2bfa6` reports eight failures in deployment/architecture contracts. The initial C6 failure also reproduced on pre-feature main; subsequent main fixes are separate work. Host focused perception checks and successful ARM64 compilation are not a full CI pass.
- Product camera preview launch does not start road_state by itself. Prediction is available only with a valid same-frame road_state publisher. The Gazebo probe starts it explicitly.
- Foreground boxes are frame-local regions. Semantic object identity, object motion prediction, collision-path prediction and motor-path rendering remain unavailable.

## Multi-lane and object annotation extension

The 2026-10-02 extension explicitly labels selected LEFT LANE/RIGHT LANE, CURRENT LANE, FOLLOW PATH, adjacent lane candidates, UNKNOWN/DARK foreground regions and visible ArUco IDs. The console adds native fullscreen with focus return and a Korean explanation legend. Design: `docs/plans/2026-10-02-lane-object-preview-design.md`.

The additional Gazebo fixture is stationary and observation-only, with no CORE/motion process. Four parallel paint boundaries at lateral ±0.0925 and ±0.2775 m form three 0.185 m lanes. It includes a red box and a textured TAG 7. Camera: 640x360, hfov 1.6 rad, pitch 25 degrees, declared height 0.160691 m, requested 6 Hz. This deliberately wider/taller test camera is **not** the physical robot camera. Paint emissive material makes its brightness compatible with the unchanged production 180 threshold. Domain 79 / partition `rosy_follow_v3_clean` isolates the final scene.

First completed isolated run: **29 raw frames, 23 JPEG previews, 10 same-stamp keep/line matches** in the probe, including startup before the separate line observer finished loading. All 16 received keep observations selected strategy both. `wide-run1/preview-0020.jpg` visibly showed LEFT/RIGHT boundaries, FOLLOW STRAIGHT 90%, CURRENT LANE, three visible lane candidates and TAG 7. Source Python override was recorded in summary.json. The raw camera supplied the marker pixels; no marker identity was injected by the probe.

The product foreground classifier also reported lane paint as UNKNOWN regions (five components in this fixture); some regions include both paint and the red box. This is not successful semantic red-box detection. The renderer and legend explicitly preserve uncertainty rather than labelling these components as robots, people or confirmed obstacles. Tag ID recognition does not imply dock/robot identity. The shadow state stayed STOP, so predicted-road success remains unproven.

Failed preliminary attempts are excluded: the first uncovered an unsupported GAZEBO ground value in the motion observation serializer; that value was removed and provenance kept solely in keep_debug. Three executable serializer regression cases cover NOMINAL, GAZEBO and HOMOGRAPHY. An orphaned earlier simulator shared a partition, and a subsequent probe received zero frames after its termination; only this task's exact owned processes were terminated, then the fixture was restarted in a fresh partition. Artifacts are under `X:\DevTemp\rosy-follow-v3`.

Host extension checks: **113 focused perception/observer tests passed**, **33 architecture P6 tests passed**, **95 quick gate tests passed** (24 existing warnings), harness lint **0 errors / 24 warnings**. Camera fullscreen/focus, waiting copy and legend browser checks: **3 passed**. Broader viewport/layout browser checks: **10 passed**. Existing camera capture tests: **5 passed**. These host/browser results do not prove physical camera acceptance.

After label placement was adjusted to keep LEFT/RIGHT titles and overlapping object captions readable, a second isolated run recorded **30 raw frames, 24 previews, 21 same-stamp matches**, all 30 keep observations strategy both, and 29 road-state STOP observations. The live JPEG displayed the current lane, three candidates and TAG 7. The final small box-number placement adjustment was verified by replaying the saved same-stamp Gazebo pixels/evidence through the host renderer, not by inventing detections.

Integration initially tripped the P6 package growth gate (40958 vs 40803+150 lines). The added pure lane-topology/tag modules remain with the existing perception split and add no writer authority; after caption placement was finalized the required split verdict was explicitly re-judged at 40961 without widening the allowance.

Post-merge focused preview plus quick gate: **116 passed / 23 warnings**. Final caption-placement and P6 rerun: **54 passed**. Saved same-stamp final rendering: `X:\DevTemp\rosy-follow-v3\camera-final.png`, with source evidence in `replay-evidence.json`; this is HOST_REPLAY_OF_GAZEBO, not a live physical camera.
