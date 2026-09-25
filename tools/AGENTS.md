<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# tools

## Purpose

Commands a developer runs from the workspace. These are not installed on the robot and they are not a ROS package.

## Key Files

| File | Description |
|------|-------------|
| `fix_ament_resource.sh` | Recreate `resource/<pkg>` markers under the domain groups |
| `run_fleet_sim.sh` | Start multi-robot Gazebo and the Fleet console from the repo root |
| `run_data.py` | Create `data/teleop` and `data/drive` sessions |
| `dashboard_drive.py` | Headless Playwright driver for the CORE dashboard: `status`, `mode`, `teleop` (stop latency), `screenshot` (skill `rosy-dashboard-drive`) |
| `harness/` | Module index generator (`rosy_harness.py`) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `harness/` | Reads each module's `progress.md` and `logs.md` |
| `sim/` | Local sim probes and `sim_verify.sh`. Not a second product tree |
| `perception/prototype/` | Unreviewed camera-estimation and real-video replay prototypes (D-205). Replaced by the reviewed P2 replay tool |

## For AI Agents

### Working In This Directory

- A script that one module installs or that its own test launches stays in that module. `bringup/scripts/rosy_env.sh` and `control/tools/gz/run_track260905.sh` are examples.
- Robot install and image build stay in `deploy/`.
- Do not put teleop notes or drive bags here. Session files go under `data/teleop` and `data/drive` and stay untracked. Learning clips stay in `data/teleop/learning/`.

### Testing Requirements

```bash
python -m pytest test/architecture/test_folder_layout.py test/test_run_data.py -q
```

### Common Patterns

Shell scripts compute the repo root from their own path. They do not embed a machine-specific absolute path.

## Dependencies

### Internal

- `src/sim/gz_sim` for `run_fleet_sim.sh`
- `data/` for `run_data.py`

### External

- ROS 2 Jazzy when running the fleet sim

<!-- MANUAL: -->
