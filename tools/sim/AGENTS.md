<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# sim

## Purpose

Developer-side simulation helpers that compose several packages: ROS-free host simulations, the D-395 S1 Gazebo bench, the D-131 live sim check, and a pile of small shell probes used while debugging the multi-robot Gazebo plus Fleet console setup. Not a second product tree and not installed on the robot. Everything here is LOCAL evidence (D-91), never DEVICE or FIELD.

## Key Files

| File | Description |
|------|-------------|
| `simulate_line_follow.py` | Deterministic closed-loop IR/camera line-follow host simulation; `--output` required. Composes control with core packages, which is why it lives here |
| `simulate_semantic_road.py` | Semantic camera to policy to command path without ROS imports |
| `d395_s1_bench.py` | D-395 S1 bench driver, run inside WSL with ROS 2 Jazzy: launches `gz_multi.launch.py` and the Fleet console in their own process groups, waits for both robots to localise, then runs the pickup (`d`) and forced-mirror (`c`) phases judged against Gazebo ground truth. Stops only processes it started. Writes `run.json`, `launch.log`, `fleet.log` |
| `d395_truth.py` | Judges a reported map pose against the Gazebo model pose; `test/test_d395_s1_truth.py` covers it |
| `d395_s1_summary.py` | Markdown rows from `run.json` files of the bench |
| `sim_verify.sh` | D-131 live check in one session: cleanup, start sim, T6 optional formation, leader drive, evidence collection (Korean comments) |
| `relaunch.sh`, `manual_drive.sh`, `observe.sh` | Restart helpers and Fleet-state drive/observation loops against the console on localhost |
| `probe_*.sh`, `probe2.sh`, `find_map.sh` | Throwaway state probes (CORE processes and ports, Gazebo log, generated robots/nav2 YAML, map references, Fleet state, ROS graph). Some read fixed `/tmp/rosy_gz_*` paths of one past run |
| `check_merge_logs.sh` | One-off check of a past `logs.md` merge: hard-coded commit and the old `docs/logs.md`, `control/logs.md` paths, so it no longer applies as is |

## For AI Agents

### Working In This Directory

- Placement: a script that imports several packages belongs here (or another root group), not inside one package, to avoid an undeclared cross-package import (see `../AGENTS.md`).
- The `.sh` probes and bench need WSL Ubuntu with ROS 2 Jazzy and a built workspace; they do not run on plain Windows. Write their output under `X:\DevTemp` or `/tmp`, never into the repo.
- Treat the probes as disposable: do not extend them; fold any lasting check into a pytest or `sim_verify.sh`.
- Shell scripts compute the repo root from their own path; keep it that way.
- A passing sim run is LOCAL evidence only; do not cite it as device or field acceptance.

### Testing Requirements

```bash
python -m pytest src/runtime/sensing/test/test_line_follow_simulation.py src/runtime/sensing/test/test_semantic_road_simulation.py test/test_d395_s1_truth.py -q
```

Host-only. The Gazebo bench and `sim_verify.sh` are run by hand in WSL.

### Common Patterns

- Simulations are deterministic and write results to a path given by flag.
- The bench kills only its own process groups and anything carrying its own `GZ_PARTITION`, so other sessions' sims survive.

## Dependencies

### Internal

- `src/runtime/sensing`, `src/runtime/gateway`, `src/runtime/events`, `src/runtime/services/core_features`, `src/sim/gz_sim` (`gz_multi.launch.py`), `operations/fleet` (console on port 8090)

### External

- WSL Ubuntu with ROS 2 Jazzy, Gazebo, `curl`; numpy for the host simulations

<!-- MANUAL: -->
