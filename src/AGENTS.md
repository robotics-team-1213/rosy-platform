<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# src

## Purpose

ROS 2 colcon workspace, grouped by domain: `core/`, `apps/`, `hardware/`, `robots/`, `navigation/`, `sim/`, `site/`. Build with `colcon build --symlink-install` from this directory (or `source env.sh && colcon build --base-paths src` from repo root). ament_python: `core`, `core_common`, `core_events`, `core_features`, `core_api_web`, `control`, `emotion`, `games`, `omx_adapter`, `fleet`, `bringup`, `led`. ament_cmake: `interfaces`, `pinky_pro`, `navigation`, `description`, `gz_sim`, `lamp_control`, `imu_bno055`, `sensor_adc`.

## Key Files

No files at this level. Each package directory has its own `AGENTS.md` (e.g. `core/core/AGENTS.md`, `apps/control/AGENTS.md`, `site/fleet/AGENTS.md`).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | CORE domain: `core` (gateway kernel: bridge + system wiring), `core_common` (protocol schemas, config, identity, profile, rmw), `core_events` (event bus, audit), `core_features` (command/safety/state/navigation/swarm/waypoints/power/docking/diagnostics/fleet_agent/maps), `core_api_web` (FastAPI/WS, dashboard static files, host-agent client), `interfaces` (custom srv: Emotion, SetBrightness, SetLamp, SetLed) |
| `apps/` | Application layer: `control` (absorbed Control: sensing, camera/OpenCV, calibration, planning, safety-policy), `emotion` (LCD GIF emotions + info screen), `games` (laptop game host, D-90 — no ROS, no cmd_vel), `omx_adapter` (ROS-native ros2_control/MoveIt contract boundary, disabled by default) |
| `hardware/` | Physical device layer: `bringup` (motors, odometry, LiDAR, battery publisher, cmd_vel deadman), `led` (Python LED service), `lamp_control` (C++ WS2811, aarch64 only), `imu_bno055` (C++ BNO055, aarch64 only), `sensor_adc` (C++ I2C ADC: IR, ultrasonic, battery — aarch64 only) |
| `robots/` | One robot = one config-only package, selected by `robot.model` / `ROSY_ROBOT` (D-196): `pinky_pro` (HWA-001 profile + CAP-001 capabilities CORE loads) (see `robots/AGENTS.md`) |
| `navigation/` | `navigation` — Nav2/SLAM launch, maps, params; hardware navigation graph |
| `sim/` | Simulation: `description` (URDF/xacro, meshes, RViz), `gz_sim` (Gazebo worlds, multi-robot launch, lamp plugin; CMake no-ops on aarch64) |
| `site/` | `fleet` — formation geometry, slot assignment, reference-stream relay, FOR-004 session, CLI, and the Fleet console v1 (D-59 SiteHub gather/scatter) |

## For AI Agents

### Working In This Directory

- Package names are grouped by domain (`core/`, `apps/`, `hardware/`, …). Do not reintroduce `pinky_*` or flat `rosy_*` directory names. The 2026-09 regroup moved `rosy_core` → `core/core`, `rosy_control` → `apps/control`, `rosy_fleet` → `site/fleet`, `rosy_bringup` → `hardware/bringup`, etc.; docs that still say `src/<pkg>/test` mean `src/<domain>/<pkg>/test`.
- After editing `package.xml` / `setup.py` / `CMakeLists.txt`, rebuild with colcon.
- `resource/<pkg>` is an ament index marker — do not delete; no need for AGENTS.md there (`tools/fix_ament_resource.sh` can recreate them).
- Do not check in `src/build`, `src/install`, `src/log`.

### Testing Requirements

```bash
cd src && colcon build --symlink-install --event-handlers console_direct+
python3 -m pytest core/core/test/ core/core_events/test/ core/core_features/test/ core/web_common/test/ apps/control/test/ site/fleet/test apps/omx_adapter/test apps/games/test -q
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
