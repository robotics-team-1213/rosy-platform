<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# sim

**Parent context:** `../AGENTS.md`
**Updated:** 2026-11-07

## Purpose

Developer-side simulation helpers that compose several packages: ROS-free host simulations, the D-395 S1 Gazebo bench, the D-131 live sim check, and a pile of small shell probes used while debugging the multi-robot Gazebo plus Fleet console setup. Not a second product tree and not installed on the robot. Everything here is LOCAL evidence (D-91), never DEVICE or FIELD.

## Key Files

| File | Description |
|------|-------------|
| `simulate_line_follow.py` | Deterministic closed-loop IR/camera line-follow host simulation; `--output` required. Composes control with core packages, which is why it lives here |
| `simulate_semantic_road.py` | Semantic camera to policy to command path without ROS imports |
| `d395_s1_bench.py` | D-395 S1 bench driver, run inside WSL with ROS 2 Jazzy: launches `gz_multi.launch.py` and the Fleet console in their own process groups, waits for both robots to localise, then runs the pickup (`d`) and forced-mirror (`c`) phases judged against Gazebo ground truth. Stops only processes it started. Writes `run.json`, `launch.log`, `fleet.log` |
| `fleet_trips.py` | Committed two-robot Fleet + Gazebo lane trip bench (`remote_sim.py ... fleet_trips`, never this laptop): owns its D-426 reservations (domain 20-29, ports) and lock, launches `map_v2_fleet_multi_real` with the regulated SIM CORE/Fleet settings (line authority, trip lease, IR guard), runs Fleet with the D-725 `native_gazebo_map_pose` port, sends one coordinate lane trip per robot on a straight lane-graph stretch and exits 0 only when both arrive. `result.json` + logs in `--out`; tokens stay in a temp run root. Kills only processes carrying its `FLEET_TRIPS_RUN` mark. Test `test/test_fleet_trips.py` |
| `native_gazebo_map_pose.py` | D-725 SIM-only Fleet pose port (actual Gazebo odom + /clock + CORE snapshots); built only by a developer SIM bootstrap such as `fleet_trips.py fleet` |
| `omx_ladder.py`, `omx_cell_sim.py` | OMX learning ladder: arm_b's real cell in MuJoCo (v2.1 jaws, measured sites and PnP cameras; values from a private cell file, form in `deploy/robot/omx/sim/ladder-cell.example.json`), scripted teacher, ACT training and strict evaluation on new, wider seeds; failed seeds return as demonstrations. Rounds are recorded as `rosy.omx-ladder-round.v1` for Rosy Learning `/learning/ladder`; a person replaces the best round. Geometry evidence only (D-947). Test `test/test_omx_ladder.py` |
| `omx_two_arm_world.py`, `omx_two_arm_sites.py`, `omx_two_arm_kin.py`, `omx_two_arm_tasks.py`, `omx_two_arm_teacher.py` | Two-arm OMX cell for the ladder: MuJoCo world (both arms with v2.1 jaws and the printed D wrist-camera holder, the rated r08 ship v15 on its berth kit with container v3 and its doors (meshes and slot map in `learning/envs/isaac/assets/ship_r08_berth`, made by the ship research folder's `sim_assets.py`; only hold 1 is in reach, stacked three tiers), white jaws, two SCAD-v11 temporary 3x1 plates, three tiers per lane (`tmp-a-1`, `tmp-a-1-l1`, `-l2`; `Layout.stack_at` is what stands on what, ship and plates), where their bridge v7 seats them (200 mm from each arm toward -x, Confluence 23233175; the 11-07 photo positions stay a choice), belt end, the cell's four cameras: measured top/side, wrist on both arms where arm_b's real frame puts it (`photo-20261108`; the D r06 CAD is `v21-b`); `ship_source=fixture-studs` keeps the old stud plate) and a scripted teacher for `stack` and `rehandle` (steps are data in `deploy/robot/omx/sim/two_arm_tasks.json`). `omx_two_arm_sites.CHOICES` holds the named CAD-vs-measured parameters (arm bases, base z, belt height, plate radius, TCP per arm, roll floor); results report them. `omx_two_arm_tasks.py` and `omx_two_arm_kin.py` need no MuJoCo: the validator refuses a plan with the reason (order, support, capacity, joint-limit reach, arm clearance). Run MuJoCo on the AI PC only (`omx_two_arm_teacher.py run TASK --out DIR --video`). Geometry only (D-947): contact numbers are not results. `omx_two_arm_matrix.py` runs the all-pairs feasibility matrix (container x arm x jaw branch, extract and restore) in MuJoCo; `omx_two_arm_teacher.py --isolated/--seed/--video-skip` give per-step truth, belt/start jitter seeds and a short video. The validator also refuses a step whose link3/link4 meshes (FK + URDF STL vertices) come within `LINK_MARGIN` of a standing container. World note: `mjENBL_MULTICCD` is on because a convex mesh against a box gives one contact point and resting boxes crept in yaw. Test `test/test_omx_two_arm_tasks.py` |
| `omx_two_arm_plan.py` | Arm assignment and schedule for Harbor's ordered moves (재취급 -> 반출 -> 복귀, or 장치 from the conveyor): which arm can do each move in the state it runs in (validator: tool-down chain and wrist clearance), the order (same stack, lane or stand in turn; the conveyor one at a time), D-778 L1 zones (a / b / mid, one arm per zone, different zones overlap) and the first-free able arm. `compare` runs the same input in one-arm A, one-arm B and two-arm mode (makespan, overlap, extra transports and HOLDs for what one arm cannot do, SR-29) and `--replay-dir` writes teacher tasks (`omx_two_arm_teacher.py run plan --plan FILE`) that check each assignment in MuJoCo. The outbound place is a lane of a temporary plate (Harbor names it per job; the step carries `outbound` and Pinky clears it); the low empty stern bay is one more ship place, `ship-stern-l0`. Times are the teacher's segment times, not measurements. Test `test/test_omx_two_arm_plan.py` |
| `omx_two_arm_policy.py` | One ACT model for both arms: the four cameras and 12 joints in, 12 joint targets out, one plan step at a time with the step as a goal vector (`observation.environment_state`). `round` collects teacher steps in parallel, merges, trains on the GPU and evaluates each step alone and each whole task under the teacher's judgement; records `<root>/two_arm_rounds/<id>/round.json` (rosy.omx-two-arm-round.v1). Geometry only (D-947), no real-arm path (D-793). Test `test/test_omx_two_arm_policy.py` |
| `run_sim_reach_pipeline.py` | OMX SIM reach loop on the sim host: teacher -> `docker cp` recordings -> batch export -> `act_job.py` (CPU, `--steps`) -> restart -> closed loop -> eval (the last two skipped when not landed); `--dry-run`, `--from-stage`. Test `test/test_sim_reach_pipeline.py` |
| `omx_topic_backend.py` | D-877 shared OMX layer: vendor xacro on `topic_based_ros2_control` with the vendor controllers. `--gripper palletizing-v2.1` (jaw v2.1, D-947) runs the repo's `omx_f_palletizing.urdf` with the vendor ros2_control blocks grafted on; default `omx-f` is the vendor xacro unchanged. Test `test/test_omx_sim_backends.py` |
| `omx_mujoco_backend.py` | D-877 MuJoCo adapter on the shared layer's topics. `--gripper palletizing-v2.1` resolves the URDF's meshes from both vendored packages (`learning/envs/isaac/assets`) and collides each finger through its Isaac pad box (`palletizing_gripper.pad_box`, as `ship_release_scene.add_jaw`); the vendor jaw keeps its calibrated capsules |
| `run_omx_backend_conformance.sh` | D-866 P2 conformance driver: shared layer + one adapter + `omx_backend_conformance.py` (or `omx_grasp_probe.py` with `grasp`). `OMX_GRIPPER=palletizing-v2.1` passes the jaw option to the layer and the MuJoCo adapter; the Isaac adapter does not take it yet |
| `d395_truth.py` | Judges a reported map pose against the Gazebo model pose; `test/test_d395_s1_truth.py` covers it |
| `d395_s1_summary.py` | Markdown rows from `run.json` files of the bench |
| `sim_verify.sh` | D-131 live check in one session: cleanup, start sim, T6 optional formation, leader drive, evidence collection (Korean comments) |
| `relaunch.sh`, `manual_drive.sh`, `observe.sh` | Restart helpers and Fleet-state drive/observation loops against the console on localhost |
| `probe_*.sh`, `probe2.sh`, `find_map.sh` | Throwaway state probes (CORE processes and ports, Gazebo log, generated robots/nav2 YAML, map references, Fleet state, ROS graph). Some read fixed `/tmp/rosy_gz_*` paths of one past run |
| `check_merge_logs.sh` | One-off check of a past `logs.md` merge: hard-coded commit and the old `docs/logs.md`, `control/logs.md` paths, so it no longer applies as is |

## For AI Agents

### Working In This Directory

- Placement: a script that imports several packages belongs here (or another root group), not inside one package, to avoid an undeclared cross-package import (see `../AGENTS.md`).
- The `.sh` probes and bench need WSL Ubuntu with ROS 2 Jazzy and a built workspace; they do not run on plain Windows. Write their output under `$ROSY_SCRATCH` or `/tmp`, never into the repo.
- Treat the probes as disposable: do not extend them; fold any lasting check into a pytest or `sim_verify.sh`.
- Shell scripts compute the repo root from their own path; keep it that way.
- A passing sim run is LOCAL evidence only; do not cite it as device or field acceptance.

### Testing Requirements

```bash
python -m pytest middleware/perception/test/test_line_follow_simulation.py middleware/perception/test/test_semantic_road_simulation.py test/test_d395_s1_truth.py -q
```

Host-only. The Gazebo bench and `sim_verify.sh` are run by hand in WSL.

### Common Patterns

- Simulations are deterministic and write results to a path given by flag.
- The bench kills only its own process groups and anything carrying its own `GZ_PARTITION`, so other sessions' sims survive.

## Dependencies

### Internal

- `middleware/perception`, `middleware/core/gateway`, `middleware/core/events`, `middleware/core/services/core_features`, `integrations/simulation/gazebo` (`gz_multi.launch.py`), `operations/fleet` (console on port 8090)

### External

- WSL Ubuntu with ROS 2 Jazzy, Gazebo, `curl`; numpy for the host simulations

<!-- MANUAL: -->

`gazebo/` holds the absorbed Perception host rigs (D-751); their explicit package/map source root remains `middleware/perception`. Device measurement tools stay under `middleware/perception/tools/device`.
