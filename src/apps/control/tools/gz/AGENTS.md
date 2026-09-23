<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# gz

## Purpose

Gazebo desk-maze rigs for Control: closed-loop drive, calibration/mapping, localization snapshots, obstacle tracks, and run monitors. Operator tools, not CI and not the robot runtime.

## Key Files

| File | Description |
|------|-------------|
| `driver.py` | Closed-loop gz driver: follow `/route`, sim TF glue (`odom→base_link`, lidar static). Rig-only `Logger.warn` shim |
| `gen_maze_world.py` | Generate maze SDF |
| `pinky_maze.sdf` | Maze model used by the rigs |
| `c1_lidar.py` | RPLidar C1 sim helper |
| `calibration_mapping_rig.py` / `run_calibration_spaces.py` / `plot_calibration_spaces.py` | Camera/lidar calibration mapping |
| `run_track260905.sh` | Isolated track run (domain 227): world, gz, bridges, rig components, SLAM, monitor, verdict. `RIG_SINGLE_PROCESS=1`, `RIG_ESTOP_PROBE=1`. Run from an ext4 copy, not `/mnt/f` (D-171) |
| `rig_estop_probe.py` | Presses the sim e-stop at `validating_motion`; the run must end `failed` |
| `rig_decision_probe.py` | `RIG_DECISION_PROBE=1`: records `/safety/decision` arrival gaps to `decision_probe.json` (the 0.25 s trial window) |
| `localization_rig.py` / `localization_snapshot.py` / `analyze_localization_snapshot.py` | Localization capture and report |
| `obstacle_scenario.py` / `observe_obstacle_tracks.py` / `record_obstacle_decisions.py` | Obstacle-track scenarios |
| `track_run_monitor.py` / `report_track_run.py` / `audit_track_footprint.py` | Track-run monitors and footprint audit |
| `rig_command.py` / `rig_health.py` / `rig_rate.py` / `rig_reload_navigation.py` | Shared rig control |
| `goal_sim.yaml` / `slam_sim.yaml` | Sim param overlays |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- These scripts are for a Linux/Gazebo machine. Do not import them from `control` runtime nodes.
- `driver.py`'s `RcutilsLogger.warn` alias is a **sim-box** compat shim. Robot code still uses `.warn` on Jazzy.
- Do not reshape the maze to make a planner look good; change the planner/tests instead.
- Evidence dumps belong under `../../docs/validation/` or `../../test/fixtures/`, not as new defaults in YAML.

### Testing Requirements

Not in host pytest. Package tests stay in `../../test/`. Some scripts have names like `test_map_monitor.py` but they are rigs, not the CI suite.

### Common Patterns

CLI scripts with `sys.path` hacks back to the package. Many write JSON/npz snapshots.

## Dependencies

### Internal

- `control` planning/sensing subjects
- World: `../../map/map_260905.world`

### External

- Gazebo, rclpy (Linux), numpy, OpenCV where a script names them

<!-- MANUAL: -->
