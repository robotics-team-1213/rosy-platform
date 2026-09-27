<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# src

## Purpose

ROS 2 colcon workspace. Package names are unchanged. Directories are grouped by role: `contracts/` (messages and shared schemas), `runtime/` (gateway, sensing, navigation), `products/` (Pinky and OMX specific packages and profiles), `drivers/` (product-independent chip drivers), `hmi/` (LCD, shared browser assets, and operator screens), `sim/`, `site/` (fleet and game host). Build with `colcon build --symlink-install` from this directory. ament_python: `core`, `core_common`, `core_events`, `core_features`, `core_api_web`, `control`, `emotion`, `games`, `omx_adapter`, `fleet`, `bringup`, `led`. ament_cmake: `interfaces`, `pinky_pro`, `omx`, `navigation`, `description`, `gz_sim`, `lamp_control`, `imu_bno055`, `sensor_adc`, `dashboard`.

## Key Files

No files at this level. Each package directory has its own `AGENTS.md` (e.g. `runtime/gateway/AGENTS.md`, `runtime/sensing/AGENTS.md`, `site/fleet/AGENTS.md`).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `contracts/` | `interfaces` (custom srv) and `foundation/` (package `core_common`: protocol schemas, config, identity, profile) |
| `runtime/` | `gateway/` (package `core`), `events/` (`core_events`), `services/` (`core_features`, managers plus `decision/`), `api_web/` (`core_api_web`), `sensing/` (package `control`), `navigation`. Judgment does not publish `cmd_vel` |
| `products/` | `pinky_pro/` (`profile/` package `pinky_pro`, `bringup`, `adc`, `lamp`, `led`) and `omx/` (`profile/` package `omx`, `adapter/` package `omx_adapter`) |
| `drivers/` | `imu_bno055` chip driver; product reuse is verified separately |
| `hmi/` | `face/` (package `emotion`, robot LCD), `web/` (package `web_common`, shared browser assets), `dashboard/` (operator screens served by `core_api_web`) |
| `sim/` | Simulation: `description` (URDF/xacro, meshes, RViz), `gz_sim` (Gazebo worlds; CMake no-ops on aarch64) |
| `site/` | `fleet` (formation, SiteHub, console) and `games` (laptop match host, no `cmd_vel`) |

## For AI Agents

### Working In This Directory

- Package names stay `control`, `bringup`, and the rest. Directories are `contracts/`, `runtime/`, `products/`, `drivers/`, `hmi/`, `sim/`, and `site/`. Do not reintroduce `pinky_*` or flat `rosy_*` package names. `rosy_control` lives at `runtime/sensing`, `rosy_bringup` at `products/pinky_pro/bringup`, `rosy_fleet` at `site/fleet`. Product folders are source ownership, not command authority or image closure.
- After editing `package.xml` / `setup.py` / `CMakeLists.txt`, rebuild with colcon.
- `resource/<pkg>` is an ament index marker — do not delete; no need for AGENTS.md there (`tools/fix_ament_resource.sh` can recreate them).
- Do not check in `src/build`, `src/install`, `src/log`.

### Testing Requirements

```bash
cd src && colcon build --symlink-install --event-handlers console_direct+
python3 -m pytest contracts/foundation/test/ runtime/gateway/test/ runtime/events/test/ runtime/services/test/ hmi/web/test/ hmi/dashboard/test/ runtime/sensing/test/ site/fleet/test products/omx/adapter/test site/games/test -q
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
