<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# src

## Purpose

ROS 2 colcon workspace. Package names are unchanged. Directories are grouped by role: `core/` (runtime and sensing in `control/`), `devices/` (buses and chips), `products/` (manipulator profile), `face/` (LCD), `navigation/`, `sim/`, `site/` (fleet and the game host). `apps/` no longer holds a package. Build with `colcon build --symlink-install` from this directory. ament_python: `core`, `core_common`, `core_events`, `core_features`, `core_api_web`, `control`, `emotion`, `games`, `omx_adapter`, `fleet`, `bringup`, `led`. ament_cmake: `interfaces`, `navigation`, `description`, `gz_sim`, `lamp_control`, `imu_bno055`, `sensor_adc`.

## Key Files

No files at this level. Each package directory has its own `AGENTS.md` (e.g. `core/core/AGENTS.md`, `core/control/AGENTS.md`, `site/fleet/AGENTS.md`).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | CORE domain: `core` (gateway kernel: bridge + system wiring), `core_common`, `core_events`, `core_features` (managers plus shared `decision/`), `core_api_web`, `web_common`, `interfaces`, and `control` (sensing geometry, `sensing/perception` camera and lane evidence, calibration, planning). Judgment does not publish `cmd_vel`. Legacy final publisher must not run beside `core` |
| `devices/` | Device nodes that used to live in `hardware/`: `bringup`, `led`, `lamp_control`, `imu_bno055`, `sensor_adc`. Chip names are still the package names |
| `products/` | `omx_adapter` — manipulator profile (`device_type: manipulator`), disabled. Not a second mobile base |
| `face/` | `emotion` — robot-local LCD |
| `navigation/` | `navigation` — Nav2/SLAM launch, maps, params |
| `sim/` | Simulation: `description` (URDF/xacro, meshes, RViz), `gz_sim` (Gazebo worlds; CMake no-ops on aarch64) |
| `site/` | `fleet` (formation, SiteHub, console) and `games` (laptop match host, no `cmd_vel`) |

## For AI Agents

### Working In This Directory

- Package names stay `control`, `bringup`, and the rest. Directories are `core/`, `devices/`, `products/`, `face/`, `navigation/`, `sim/`, and `site/`. Do not reintroduce `pinky_*` or flat `rosy_*` directory names. `rosy_control` lives at `core/control`, `rosy_bringup` at `devices/bringup`, `rosy_fleet` at `site/fleet`. Docs that still say `src/<pkg>/test` mean `src/<domain>/<pkg>/test`.
- After editing `package.xml` / `setup.py` / `CMakeLists.txt`, rebuild with colcon.
- `resource/<pkg>` is an ament index marker — do not delete; no need for AGENTS.md there (`tools/fix_ament_resource.sh` can recreate them).
- Do not check in `src/build`, `src/install`, `src/log`.

### Testing Requirements

```bash
cd src && colcon build --symlink-install --event-handlers console_direct+
python3 -m pytest core/core/test/ core/core_events/test/ core/core_features/test/ core/web_common/test/ core/control/test/ site/fleet/test products/omx_adapter/test site/games/test -q
# ament linters live in each Python package's test/ (copyright, flake8, pep257)
```

### Common Patterns

- Relative topics + namespace/`frame_prefix` (D-4). Avoid hardcoded `/cmd_vel`.
- Python drivers that must run without ROS in unit tests keep kinematics/policy ROS-free.

## Dependencies

### Internal

- Almost every hardware/UI package depends on `interfaces`.
- `bringup` launch includes `description`.
- `gz_sim` includes `description` and `navigation` launches.

### External

- ROS 2 Jazzy overlay (`/opt/ros/jazzy`)
- colcon, ament_cmake / ament_python

<!-- MANUAL: -->
