<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-10-01 -->

# ROSY

## Purpose

ROSY is a robot middleware and fleet-control platform (ROS 2 Jazzy, first hardware Pinky Pro). This repository is the robot-side workspace: CORE (src/runtime/gateway) is the external API gateway, supported by shared contracts, events, services, web API, hardware bringup, Nav2/SLAM, Gazebo, Raspberry Pi deploy/robot/pinky_pro/release tooling, and charging-dock ESP32 firmware. src/runtime/sensing contains the absorbed Control package; its legacy final publisher must not run beside CORE. src/site/fleet contains formation/relay/CLI and the v1 Fleet console seed; the full central Fleet platform remains unimplemented. Current source roles are contracts, runtime, products, drivers, site, hmi, and sim. Folder role does not establish writer authority, host placement, or image closure (D-315). License: Apache-2.0.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Repo overview, colcon/sim launch, Pi 5 runtime, phase roadmap |
| `LICENSE` | Apache License 2.0 |
| `env.sh` | Dev env: source ROS 2 Jazzy then workspace `install/setup.bash` |
| `CONCEPTS.md` | Shared domain vocabulary — entities, named processes, status concepts with project-specific meaning |
| `PRODUCT.md` | Product schema (`impeccable:product-schema`): platform, users, purpose, positioning — the top-level "who is this for" the UI lanes read |
| `DESIGN.md` | Visual design guide (DESIGN.md format, D-359 §8): tokens, themes, typography, layout tiers, shared components, do/don't. ADRs and contract tests own the contract; sidecar `.impeccable/design.json` is local-only |
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
| `learning/` | D-427 learning part: `training/perception/` (D-356 learned-loop tooling), `envs/isaac/` (ROS package `isaac_sim`, a `colcon_roots` entry), `curation/omx/` (LeRobot export); see each `AGENTS.md`. Only `isaac_sim` reaches a device (native payload, D-427 Q8) |
| `operations/` | D-427 operations part (a `colcon_roots` entry): `world/` (wheel `rosy-world`), `processes/palletizing/` (wheel `rosy-palletizing`, harness module `palletizing`), `execution/` (wheel `rosy-execution`: `rosy.execution.api`, `rosy.execution.site`), `apps/fleet/` (wheel `rosy-app-gateway`, import `rosy_gateway`, console script `rosy-site-gateway`). Wheel folders carry `COLCON_IGNORE`; see `tools/harness/platform_parts.yaml` |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |
| `firmware/` | Dock and signal firmware outside colcon (see `firmware/AGENTS.md`) |
| `test/` | Host pytest for deploy/robot/pinky_pro/release/motor contracts (see `test/AGENTS.md`) |
| `docs/assets/` | Architecture and product images (see `docs/assets/AGENTS.md`) |
| `docs/solutions/` | Documented solutions to past problems — bugs, best practices, workflow patterns — by category, with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in a documented area |
| `reference/` | Frozen upstream pinky_pro zip (see `reference/AGENTS.md`) |
| `.github/` | CI workflow (see `.github/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Treat `docs/spec/ROSY CORE SRS.md`, `docs/reference/ROSY API & Protocol Reference.md`, and `docs/reference/ROSY ADR Log.md` as contracts. Do not invent REST paths, modes, or protocol fields that are not in the API ref or `core_common.protocol.schemas` (`src/contracts/foundation/core_common/protocol/schemas.py`).
- External clients must not speak ROS. `core` is the only gateway (CORE SRS §1.3). Command Manager (`core_features.command`) is the only `cmd_vel` publisher (D-2).
- Single process: main thread rclpy `MultiThreadedExecutor`, worker thread uvicorn+FastAPI (D-1). Entry point is `core=core.main:main` — `ros2 run core core`. Do not split into two processes.
- `slam_toolbox` is optional. `ros_bridge` must import it inside try/except, never at module top (`package.xml` comment). CI boots the node without it.
- Config merge order: `src/contracts/foundation/config/rosy_default.yaml` → `~/.rosy/rosy.yaml` → `ROSY_CONFIG`.
- Do not commit colcon `build/`, `install/`, `log/`, or `__pycache__/`.
- This repo is PUBLIC. Place every new file by D-226: internal material, real device addresses/accounts and filled device config go in the gitignored `private/` (write `<robot-ip>` in public docs); data code or tests read stays beside the reader; dated evidence goes in `docs/validation/<topic>-<YYYY-MM-DD>/`; module how-to goes in the module's one `docs/`. A new secret kind needs its ignore rule and its tracked template added to `test/architecture/test_document_placement.py` in the same change.
- Hardware profile is YAML. In-tree Pinky full spec is `src/products/pinky_pro/profile/config/profile.yaml`. The robot advertises `deploy/robot/pinky_pro/config/{profile,capabilities}.${ROSY_RUNTIME_MODE}.yaml` (`core` / `motor` / `hardware`).
- Package names are grouped by source role under `src/{contracts,runtime,products,drivers,hmi,sim,site}`. Do not reintroduce `rosy_*` or `pinky_*` package names. The CORE launch file still carries its legacy filename `rosy_core.launch.py`.
- Dashboard screens are static files in `src/hmi/dashboard`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.
- Project skills in `.claude/skills/`: `rosy-device-access` (SSH to a robot), `rosy-hw-bringup` (board devices), `rosy-land-on-main` (shared checkout, ADR numbers, `test/known_failures.txt`), `rosy-dashboard-drive` (Playwright, `tools/dashboard_drive.py`), `rosy-release-push` (payload release to an existing robot).

### Testing Requirements

```bash
# Quick tier (D-346): the pre-commit/push gate (~3 min).
# Same suite as the pre-push hook (tools/hooks/install.sh). 2026-10-01: dashboard
# contract + root contract suites added after the D-362 split and secret-scan/
# scorecard classes landed red through the old tier.
python3 -m pytest test/test_harness_contracts.py test/architecture/test_module_structure.py \
  test/test_io_image_closure.py test/test_line_follow_contract_docs.py \
  test/test_behavior_test_ownership.py test/test_module_scorecard.py \
  test/test_release_boundary_guards.py test/test_robot_literals.py \
  src/runtime/gateway/test/test_protocol_version_alignment.py \
  src/runtime/gateway/test/test_event_catalogue.py \
  src/runtime/gateway/test/test_console_layout.py \
  src/runtime/gateway/test/test_host_cards.py \
  src/runtime/gateway/test/test_host_hardware.py \
  src/runtime/gateway/test/test_triage_contract.py \
  src/runtime/gateway/test/test_host_status_summary.py -q
python3 tools/harness/rosy_harness.py lint   # ADR duplicates, mojibake, append-only

# Full tier: before a release, a field push, or when the touched suite is not
# in the quick tier above.
# ROS 2 overlay (Linux / Pi). On Windows, run Python tests that do not need rclpy.
source env.sh
colcon --log-base log build --symlink-install --base-paths $(python3 tools/harness/colcon_roots.py) --build-base build --install-base install

# core unit tests (no live ROS required for most)
python3 -m pytest src/runtime/gateway/test/ src/runtime/events/test/ src/runtime/services/test/ src/hmi/web_common/test/ -v

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
- Dashboard screens are static files in `src/hmi/dashboard`, served in-process by FastAPI (`core_api_web`). Not a Node server (D-23). D-7 (React+Vite) is not the current dashboard.

## Dependencies

### Internal

- `src/runtime/gateway` depends on `src/contracts/foundation`, `src/runtime/events`, `src/runtime/services`, `src/runtime/api_web`, and `src/contracts/interfaces` (plus, at runtime, bringup/Nav2 topics).
- `deploy/` consumes `src/` via `deploy/robot/pinky_pro/Dockerfile`.
- `test/` imports `deploy/robot/pinky_pro/release` via `test/conftest.py` `sys.path`.

### External

- ROS 2 Jazzy, rclpy/rclcpp, Nav2, CycloneDDS
- FastAPI, uvicorn, pydantic, PyYAML, httpx, websockets
- Optional: slam_toolbox, sllidar_ros2, Gazebo (ros_gz), wiringPi I2C, ws2811, Dynamixel SDK

<!-- MANUAL: -->
