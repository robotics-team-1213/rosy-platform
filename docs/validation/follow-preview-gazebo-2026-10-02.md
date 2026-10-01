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
