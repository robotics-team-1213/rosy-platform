<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# sim

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `omx_two_arm_world.py`, `omx_two_arm_sites.py`, `omx_two_arm_kin.py`, `omx_two_arm_tasks.py`, `omx_two_arm_teacher.py` | Two-arm OMX cell for the ladder: MuJoCo world (both arms with v2.1 jaws, stud ship plate, two SCAD-v7 temporary 3x1 plates, belt end, measured top/side cameras, optional wrist cameras) and a scripted teacher for `stack` and `rehandle` (steps are data in `deploy/robot/omx/sim/two_arm_tasks.json`). `omx_two_arm_sites.CHOICES` holds the named CAD-vs-measured parameters (arm bases, base z, belt height, plate radius, TCP per arm, roll floor); results report them. `omx_two_arm_tasks.py` and `omx_two_arm_kin.py` need no MuJoCo: the validator refuses a plan with the reason (order, support, capacity, joint-limit reach, arm clearance). Run MuJoCo on the AI PC only (`omx_two_arm_teacher.py run TASK --out DIR --video`). Geometry only (D-947): contact numbers are not results. Test `test/test_omx_two_arm_tasks.py` |
| `run_sim_reach_pipeline.py` | OMX SIM reach loop on the sim host: teacher -> `docker cp` recordings -> batch export -> `act_job.py` (CPU, `--steps`) -> restart -> closed loop -> eval (the last two skipped when not landed); `--dry-run`, `--from-stage`. Test `test/test_sim_reach_pipeline.py` |
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
