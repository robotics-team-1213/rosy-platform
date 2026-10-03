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
| `operations/` | D-427 operations part (a `colcon_roots` entry): `world/` (wheel `rosy-world`), `processes/palletizing/` (wheel `rosy-palletizing`, harness module `palletizing`), `execution/` (wheel `rosy-execution`: `rosy.execution.api`, `rosy.execution.site`), `apps/fleet/` (wheel `rosy-app-gateway`, import `rosy_gateway`, console script `rosy-site-gateway`). Wave 3b: ROS packages `apps/games/` (`games`), `vision/` (`rosy_vision`, with the read-only `vision/signal_observer/`), `processes/cell/` (`rosy_cell`); `ui/cam/` (Rosy Cam Android app, `COLCON_IGNORE`); `site_devices/` (dock and signal firmware, see its `AGENTS.md`). Wheel folders carry `COLCON_IGNORE`; see `tools/harness/platform_parts.yaml` |
| `data/` | Local teleop checks and drive recordings. Session files stay untracked |
| `operations/site_devices/` | Dock and signal site devices: firmware outside colcon, device contracts (see `operations/site_devices/AGENTS.md`, D-427 wave 3b) |
| `test/` | Host pytest for deploy/robot/pinky_pro/release/motor contracts (see `test/AGENTS.md`) |
| `docs/assets/` | Architecture and product images (see `docs/assets/AGENTS.md`) |
| `docs/solutions/` | Documented solutions to past problems — bugs, best practices, workflow patterns — by category, with YAML frontmatter (`module`, `tags`, `problem_type`). Relevant when implementing or debugging in a documented area |
| `reference/` | Frozen upstream pinky_pro zip (see `reference/AGENTS.md`) |
| `.github/` | CI workflow (see `.github/AGENTS.md`) |

## For AI Agents

### D-427 이동 기간 규칙 (2026-10-03, 사용자 결정 — 이동 완료 시 2·5항 삭제)

소스 이전(D-427·D-429·D-430, 계획 `docs/plans/2026-10-03-d427-source-migration.md`)이 끝날 때까지 모든 세션이 지킨다.

1. **우선순위:** 폴더 이동 > main CI 초록불 > 안전(D-430 공백) > 기능. 충돌하면 앞이 이긴다.
2. **이동 중 경로 동결:** wave를 시작하면 그 wave의 경로(계획의 wave 표, 매니페스트 `wave:`)를 고치지 않는다. 다른 경로 작업은 계속한다. 이동 뒤 미병합 브랜치는 주인이 rebase한다.
3. **main 체크아웃에서 작업하지 않는다.** 모든 작업은 `.worktrees/<topic>`에서 한다. main 체크아웃에 커밋 안 된 변경을 남기면 다른 세션의 fast-forward와 pre-push가 막힌다.
4. **push 전 순서:** `git fetch` → `origin/main` 위로 rebase → `python tools/harness/rosy_harness.py generate`(생성 문서가 바뀌면 커밋) → pre-push 검사(`tools/hooks/pre-push` 목록). force-push 하지 않는다.
5. **새 코드는 D-427 목표 경로에만 둔다.** `tools/harness/platform_parts.yaml`의 `d427_target`을 따른다. 동결된 최상위 `modules/`·`apps/`·`ui/`와 이동 예정 `src/` 아래에 새 패키지를 만들지 않는다.
6. **구조를 바꾸는 ADR은 D-427·D-429·D-430과의 관계를 표로 적는다.** ADR 없이 새 최상위 폴더를 만들지 않는다.
7. **safety 태그 경로**(매니페스트 `concern: safety`, `safety_modules`, `safety_anchors`)를 바꾸거나 옮기는 커밋은 `Safety-Review:` trailer와 독립 리뷰가 필요하다(D-430 §5, CI가 검사).

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

Tiers (D-436). **This machine runs the affected tier (fast iteration) and the pre-push fast gate only. The full suite never runs locally by default; it runs on GitHub Actions runners** as a parallel matrix (`.github/workflows/ci.yml`): push to `main`, pull requests whose selection escalates, nightly schedule, `workflow_dispatch`, and before a release build. The arm64 payload already builds on the GitHub ARM64 runner (`build-native-payload.yml`). PR CI runs affected and goes full by itself when the selector escalates (shared foundation `src/contracts/**`, `tools/harness/**`, `conftest.py`, packaging/pytest config, requirements pins, `.github/workflows/**`, or a file that maps to no module). `affected --run` on an escalated selection runs only the guards plus the suites mapped from the changed files (owning module, direct reverse dependents, referencing tests) and says the rest is on GitHub; `--full` forces a local full run (avoid: 40-60 min here, and Windows lacks wheels CI installs).

GitHub results (the full tier is never re-run locally to "check"):

```bash
gh run list --branch <branch> -L 3                      # find the run for your push / PR
gh run watch <run-id> --exit-status                     # wait; non-zero exit when it fails
gh run view <run-id> --log-failed                       # only the failed steps' logs
gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | .name'
```

Reproduce locally only the failed matrix entry's pytest invocation (the job name `test (<entry>)` maps to `CI_FULL_MATRIX` in `tools/harness/affected_tests.py`, or to the `affected-N` invocation printed by the `Test scope (D-436)` step). A local `main` that is not pushed has no CI evidence.

```bash
# Affected tier (D-436): tests of the touched modules + reverse dependents + tests naming the
# changed paths + the guard set; prints why each suite runs and when it escalates to FULL.
# Suites sharing a test basename (gateway vs sensing test_battery.py) come out as separate runs.
python tools/harness/rosy_harness.py affected --base main          # print the selection
python tools/harness/rosy_harness.py affected --base main --run    # run it

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

# Full tier: runs on GitHub runners (see above), not here. The commands below are what a
# Linux/WSL host would run to reproduce one CI matrix entry, not a routine local step.
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
