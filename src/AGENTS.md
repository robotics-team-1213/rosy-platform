<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# src

## Purpose

ROS 2 colcon workspace. Package names are unchanged. Directories are grouped by role: `core/` (runtime and, for now, sensing in `control/`), `devices/` (buses and chips), `products/` (manipulator profile), `face/` (LCD), `navigation/`, `sim/`, `site/` (fleet and the game host). `apps/` still holds `control` until that directory lock clears. Build with `colcon build --symlink-install` from this directory. ament_python: `core`, `core_common`, `core_events`, `core_features`, `core_api_web`, `control`, `emotion`, `games`, `omx_adapter`, `fleet`, `bringup`, `led`. ament_cmake: `interfaces`, `navigation`, `description`, `gz_sim`, `lamp_control`, `imu_bno055`, `sensor_adc`.

## Key Files

No files at this level. Each package directory has its own `AGENTS.md` (e.g. `core/core/AGENTS.md`, `apps/control/AGENTS.md`, `site/fleet/AGENTS.md`).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | CORE domain: `core` (gateway kernel: bridge + system wiring), `core_common` (protocol schemas, config, identity, profile, rmw), `core_events` (event bus, audit), `core_features` (command/safety/state/navigation/swarm/waypoints/power/docking/diagnostics/fleet_agent/maps), `core_api_web` (FastAPI/WS, dashboard static files, host-agent client), `interfaces` (custom srv: Emotion, SetBrightness, SetLamp, SetLed) |
| `apps/` | Only `control` remains here (sensing, camera, calibration, planning). The directory is locked on this machine, so it has not moved next to `core` yet |
| `devices/` | Device nodes that used to live in `hardware/`: `bringup`, `led`, `lamp_control`, `imu_bno055`, `sensor_adc`. Chip names are still the package names |
| `products/` | `omx_adapter` — manipulator profile (`device_type: manipulator`), disabled. Not a second mobile base |
| `face/` | `emotion` — robot-local LCD |
| `navigation/` | `navigation` — Nav2/SLAM launch, maps, params |
| `sim/` | Simulation: `description` (URDF/xacro, meshes, RViz), `gz_sim` (Gazebo worlds; CMake no-ops on aarch64) |
| `site/` | `fleet` (formation, SiteHub, console) and `games` (laptop match host, no `cmd_vel`) |

## For AI Agents

### Working In This Directory

- Package names are grouped by domain (`core/`, `apps/`, `hardware/`, …). Do not reintroduce `pinky_*` or flat `rosy_*` directory names. The 2026-09 regroup moved `rosy_core` → `core/core`, `rosy_control` → `apps/control`, `rosy_fleet` → `site/fleet`, `rosy_bringup` → `hardware/bringup`, etc.; docs that still say `src/<pkg>/test` mean `src/<domain>/<pkg>/test`.
- After editing `package.xml` / `setup.py` / `CMakeLists.txt`, rebuild with colcon.
- `resource/<pkg>` is an ament index marker — do not delete; no need for AGENTS.md there (`tools/fix_ament_resource.sh` can recreate them).
- Do not check in `src/build`, `src/install`, `src/log`.

### Testing Requirements

```bash
cd src && colcon build --symlink-install --event-handlers console_direct+
python3 -m pytest core/core/test/ core/core_events/test/ core/core_features/test/ core/web_common/test/ apps/control/test/ site/fleet/test products/omx_adapter/test site/games/test -q
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
