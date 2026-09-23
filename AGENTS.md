<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-24 -->

# ROSY

## Purpose

ROSY is a robot middleware and fleet-control platform (ROS 2 Jazzy, first hardware Pinky Pro). This repository is the robot-side workspace: `core` (`src/core/core`) is the only external API gateway (FastAPI + rclpy in one process), supported by `core_common` (protocol schemas, config, identity), `core_events`, `core_features` (command/safety/navigation/power/docking/…), and `core_api_web` (REST/WS + dashboard) — plus hardware bringup, Nav2/SLAM, Gazebo, Raspberry Pi 5 deploy/release tooling, and charging-dock ESP32 firmware. `src/apps/control` contains the absorbed Control package; its legacy final publisher must not run beside CORE. `src/site/fleet` contains formation/relay/CLI and the v1 Fleet console seed; the full central Fleet platform remains unimplemented. `src` packages are grouped by domain (`core` / `apps` / `hardware` / `navigation` / `sim` / `site`); upstream was pinky_pro, fully renamed (ADR D-16) and later regrouped out of flat `rosy_*` directories. License: Apache-2.0.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Repo overview, colcon/sim launch, Pi 5 runtime, phase roadmap |
| `LICENSE` | Apache License 2.0 |
| `env.sh` | Dev env: source ROS 2 Jazzy then workspace `install/setup.bash` |
| `CONCEPTS.md` | Shared domain vocabulary — entities, named processes, status concepts with project-specific meaning |
| `STATUS.md` | Generated: per-module gate snapshot (SOURCE…FIELD) linking each module's `progress.md`. Edit progress/logs/ADRs, not this file |
| `tools/fix_ament_resource.sh` | Recreate ament `resource/<pkg>` markers for Python packages under the domain groups |
| `tools/run_fleet_sim.sh` | One-click multi-robot Gazebo + fleet orchestration launcher |
| `data/` | Local teleop checks (`teleop/`) and drive recordings (`drive/`). Session files are not committed |
| `.gitignore` | Ignores colcon `build/` `install/` `log/`, `__pycache__`, `.omc/` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | ROS 2 colcon workspace, domain-grouped (see `src/AGENTS.md`) |
| `docs/` | Governance docs: spec, live API contract, ADR, plans (see `docs/AGENTS.md`) |
| `deploy/` | Image build, signed release, Pi runtime (see `deploy/AGENTS.md`) |
| `tools/` | Developer commands. Not installed on the robot (see `tools/AGENTS.md`) |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |
| `dock/` | Charging-dock firmware and ROSY-DOCK-001 contract (see `dock/AGENTS.md`) |
| `signal/` | Traffic-signal controller: ROSY-SIGNAL-001 contract + ESP32 relay firmware (reference implementation); commanded by the Fleet console, fail-safe flash on lost supervision (see `signal/AGENTS.md`) |
| `test/` | Host pytest for deploy/release/motor contracts (see `test/AGENTS.md`) |
| `docs/assets/` | Architecture and product images (see `docs/assets/AGENTS.md`) |
| `docs/solutions/` | Documented solutions to past problems — bugs, best practices, workflow patterns — by category, with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in a documented area |
| `reference/` | Frozen upstream pinky_pro zip (see `reference/AGENTS.md`) |
| `.github/` | CI workflow (see `.github/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Treat `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, and `docs/reference/ROSY ADR Log.md` as contracts. Do not invent REST paths, modes, or protocol fields that are not in the API ref or `core_common.protocol.schemas` (`src/core/core_common/core_common/protocol/schemas.py`).
- External clients must not speak ROS. `core` is the only gateway (CORE SRS §1.3). Command Manager (`core_features.command`) is the only `cmd_vel` publisher (D-2).
- Single process: main thread rclpy `MultiThreadedExecutor`, worker thread uvicorn+FastAPI (D-1). Entry point is `core=core.main:main` — `ros2 run core core`. Do not split into two processes.
- `slam_toolbox` is optional. `ros_bridge` must import it inside try/except, never at module top (`package.xml` comment). CI boots the node without it.
- Config merge order: `src/core/core/config/rosy_default.yaml` → `~/.rosy/rosy.yaml` → `ROSY_CONFIG`.
- Do not commit colcon `build/`, `install/`, `log/`, or `__pycache__/`.
- Hardware profile is YAML. In-tree Pinky full spec is `src/core/core/config/profile.pinky_pro.yaml`. The robot advertises `deploy/robot/config/{profile,capabilities}.${ROSY_RUNTIME_MODE}.yaml` (`core` / `motor` / `hardware`).
- Package names are grouped by domain: `src/{core,apps,hardware,navigation,sim,site}` (D-147). Do not reintroduce `rosy_*` or `pinky_*` package names. ci.yml was realigned to the domain tree (verified 2026-09-21); the CORE launch file still carries its legacy filename `rosy_core.launch.py` — README matches that file name.
- Dashboard is FastAPI static files under `core_api_web` (`src/core/core_api_web/core_api_web/web/`), not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.

### Testing Requirements

```bash
# ROS 2 overlay (Linux / Pi). On Windows, run Python tests that do not need rclpy.
source env.sh
cd src && colcon build --symlink-install

# core unit tests (no live ROS required for most)
python3 -m pytest src/core/core/test/ src/core/core_events/test/ src/core/core_features/test/ src/core/web_common/test/ -v

# Fleet formation/relay/session/console (no ROS)
python3 -m pytest src/site/fleet/test/ -v

# Deploy, release, motor, Wi-Fi, host-agent contracts (host)
python3 -m pytest test/ -v

# CI also: flake8 (max 120), boot smoke without slam_toolbox
```

CI (`.github/workflows/ci.yml`) on `main` / PRs: colcon build in `ros:jazzy-ros-base`, pytest, boot smoke, SaveMap type guard — all on domain-tree paths. Note: `origin` exists (`github.com/livsbittt/rosy-os.git`) and CI events fire on push and pull requests — check the latest run (`gh run list`) for current status; a local `main` that is ahead of `origin/main` has no CI evidence at all.

### Common Patterns

- Requirement IDs (`CORE-001`, `SAF-005`, `PWR-001`) not section numbers (D-17).
- Python packages: ament_python (`setup.py` + `package.xml`). C++/URDF/Nav2/interfaces: ament_cmake.
- Namespaces + `frame_prefix` for multi-robot (D-4). Robot identity has **no default**:
  `ROS_DOMAIN_ID` = 40 + N and `ROSY_NAMESPACE` = `rosy_%02d` are derived from
  `ROSY_ROBOT_NUMBER` at install, and a missing identity stops the runtime (D-33).
  A default here is what once shipped every unit as 42/`rosy_01`.
- Dashboard is FastAPI static files under `core_api_web/web/`, not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.

## Dependencies

### Internal

- `src/core/core` depends on `src/core/core_common`, `src/core/core_events`, `src/core/core_features`, `src/core/core_api_web`, and `src/core/interfaces` (plus, at runtime, bringup/Nav2 topics).
- `deploy/` consumes `src/` via `deploy/robot/Dockerfile`.
- `test/` imports `deploy/release` via `test/conftest.py` `sys.path`.

### External

- ROS 2 Jazzy, rclpy/rclcpp, Nav2, CycloneDDS
- FastAPI, uvicorn, pydantic, PyYAML, httpx, websockets
- Optional: slam_toolbox, sllidar_ros2, Gazebo (ros_gz), wiringPi I2C, ws2811, Dynamixel SDK

<!-- MANUAL: -->
