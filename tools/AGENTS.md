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
| `sim/` | Local sim probes, `sim_verify.sh`, and host simulations that compose several packages (`simulate_line_follow.py`, `simulate_semantic_road.py`). Not a second product tree |
| `perception/prototype/` | Unreviewed camera-estimation and real-video replay prototypes (D-205). Replaced by the reviewed P2 replay tool |

## For AI Agents

### Working In This Directory

- Placement rule: a script that serves one module and imports no other package (its own test launches it, or it only measures that module) lives in that module's `tools/`, e.g. `src/site/fleet/tools/fleet_gather_bench.py`. A script that composes several packages lives in a root group even if one module's test launches it — putting it inside a package would add an undeclared cross-package import (`test_every_cross_package_use_is_declared`); e.g. `tools/sim/simulate_line_follow.py` and `simulate_semantic_road.py` compose control with core, core_events and core_features. Root `tools/` keeps workspace entry points (`fix_ament_resource.sh`, `run_fleet_sim.sh`, `run_data.py`, `dashboard_drive.py`, `fleet_console.ps1`) and cross-module groups (`harness/`, `perception/`, `sim/`).
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
