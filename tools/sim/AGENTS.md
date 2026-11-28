
# sim

**Parent context:** `../AGENTS.md`

## Purpose

Developer-side simulation helpers that compose several packages: ROS-free host simulations, the D-395 S1 Gazebo bench, the D-131 live sim check, OMX MuJoCo twins and two-arm tools, and throwaway shell probes. Not installed on a robot. Everything here is LOCAL evidence (D-91), never DEVICE or FIELD.

## For AI Agents

### Working In This Directory

- Placement: a script that imports several packages belongs here (or another root group), not inside one package (see `../AGENTS.md`).
- A passing sim run is LOCAL evidence only; do not cite it as device or field acceptance. Contact numbers from the two-arm MuJoCo world are geometry only (D-947).
- Gazebo benches (`fleet_trips.py`, `route_drive.py`, `formation_lane.py`) run only through `remote_sim.py ... <name>`, never on this laptop. Each kills only processes carrying its own run mark or `GZ_PARTITION`, so other sessions' sims survive.
- `fleet_trips.py` owns its D-426 reservations (domain 20-29, ports) and lock; tokens stay in a temp run root. D-725: `native_gazebo_map_pose.py` is built only by a developer SIM bootstrap.
- The D-395 bench and `sim_verify.sh` need WSL Ubuntu with ROS 2 Jazzy and a built workspace and are run by hand. Write output under `$ROSY_SCRATCH` or `/tmp`, never into the repo. Shell scripts compute the repo root from their own path.
- The `probe_*.sh`, `probe2.sh`, `find_map.sh` and `check_merge_logs.sh` files are disposable: do not extend them; fold lasting checks into a pytest or `sim_verify.sh`.
- Run MuJoCo two-arm tools (`omx_two_arm_teacher.py run TASK --out DIR --video`) on the AI PC only. `omx_two_arm_tasks.py` and `omx_two_arm_kin.py` need no MuJoCo; the validator refuses a plan with the reason.
- `omx_real2sim.py` reads the real cell read only (`capture` over ssh). `measure --prev` refuses when the top camera moved (over 3 px, 0.3 deg or 0.5 % scale); `--camera-moved-ok` overrides. `sim` needs the snapshot committed at the sha.
- `omx_load.py check` reviews every new real-arm pose, path or recovery before it runs: joint torque share of the session caps, flagged at 50 %. Near the limit means slower or shorter, never clearance. Limits in `docs/validation/omx-load-2026-11-09/result.md`.
- Real-cell values come from a private cell file (form: `deploy/robot/omx/sim/ladder-cell.example.json`); `omx_physics.py` candidates live in `learning/envs/isaac/cell_physics.yaml` (D-947 2).
- D-877/D-866: `--gripper palletizing-v2.1` selects the jaw v2.1 in the OMX backends; the Isaac adapter does not take it yet.
- `run_sim_reach_pipeline.py` has `--dry-run` and `--from-stage`; use `--dry-run` first on a sim host.
- Simulations are deterministic and write results to a path given by flag (`--output` required for `simulate_line_follow.py`).

### Testing Requirements

```bash
python -m pytest middleware/perception/test/test_line_follow_simulation.py middleware/perception/test/test_semantic_road_simulation.py test/test_d395_s1_truth.py -q
```

Host-only; benches need WSL Ubuntu with ROS 2 Jazzy. Bench scripts run through `remote_sim.py` or by hand in WSL.

`gazebo/` holds the absorbed Perception host rigs (D-751); their package/map source root stays `middleware/perception`. Device measurement tools stay under `middleware/perception/tools/device`.
