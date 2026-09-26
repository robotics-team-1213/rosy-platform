<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# navigation

## Purpose

Nav2 and SLAM Toolbox launch/config/maps for real robot and Gazebo. ament_cmake. The leftover Flask UI (`scripts/`) was deleted — it had been superseded by `core` FastAPI since D-3 and was never launched or installed.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Depends on navigation2, nav2_bringup, and slam_toolbox |
| `CMakeLists.txt` | Installs the Python policy package, launch, params, maps, rviz. |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `navigation/` | Importable D-4 helpers (`frame_prefix`, `params_rewrite`, `profile_limits`) |
| `launch/` | `hardware.launch.py` plus XML launches: bringup, localization, slam, gz_*, web_* (see `launch/AGENTS.md`) |
| `params/` | `nav2_params.yaml`, `mapper_params.yaml` (see `params/AGENTS.md`) |
| `map/` | Occupancy maps (`my_map`, `pinklab`) (see `map/AGENTS.md`) |
| `rviz/` | map_building / nav2_view configs (see `rviz/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- D-3: the web UI is `core` FastAPI at `/api/v1/*`. The Flask original is gone.
- Nav2 velocity_smoother output must be remappable to `nav_cmd_vel` so CommandManager owns `cmd_vel`.
- Launch files compose. TF/param policy lives in `navigation.*`, not under `launch/`.
- `profile_limits` is the launch-time guard for Device motion ceilings; do not
  bypass it with a higher hardware launch override.
- `gz_bringup_launch.xml` includes `bringup_launch.xml`; do not fork the robot Nav2 XML.
- Watch absolute vs namespaced `scan_topic` in mapper params (noted in `gz_multi.launch.py`).
- D-144 selects localization or SLAM through `ROSY_NAVIGATION_BACKEND` while retaining `ROSY_RUNTIME_MODE=hardware`; mapping must not require a pre-existing map.

### Testing Requirements

No dedicated pytest here. Integration is launch + `core` navigation tests. ament_lint via CMake.

### Common Patterns

XML launches included from `gz_sim` with per-robot namespace.

## Dependencies

### Internal

- Used by `gz_sim/launch/gz_multi.launch.py`

### External

- Nav2, slam_toolbox, rviz2

<!-- MANUAL: -->
