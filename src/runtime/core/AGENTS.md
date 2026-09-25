<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# core

## Purpose

Robot middleware (ROSY-CORE-SRS-001). One process: rclpy node `core` + uvicorn FastAPI on port 8080 (D-1). Owns identity, capabilities, state snapshots, command arbitration, safety, navigation facade, waypoints, events, power/battery policy, docking SM, diagnostics, and the dashboard. All ROS I/O is confined to `core.bridge.ros_bridge`.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; slam_toolbox is optional at import time |
| `setup.py` | Console script `core=core.main:main`; installs `web/*` |
| `setup.cfg` | ament script install paths |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | Python package (see `core/AGENTS.md`) |
| `config/` | Default YAML, Pinky Pro profile, capabilities (see `config/AGENTS.md`) |
| `launch/` | `rosy_core.launch.py` (see `launch/AGENTS.md`) |
| `test/` | pytest for API, power, battery, protocol, dashboard (see `test/AGENTS.md`) |
| `resource/` | ament index marker `core` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Policy modules (`command`, `safety`, `power`, `docking`, `state`, `events`, `protocol`) must stay ROS-import-free so pytest can run on Windows/CI without rclpy.
- `CoreServices` in `services.py` is the DI container. Wire new managers there, then expose via API routes.
- Do not publish `cmd_vel` from API or Nav2. CommandManager.select_output() is the only source; bridge publishes at 50 Hz (D-2).
- Identity: `robot.id` follows `ROSY_NAMESPACE` / robot number. `PUT /api/v1/system/info` may rename; rebinding `robot_id` is `409 IDENTITY_LOCKED` (D-33, D-65).
- Inventory: `GET /api/v1/system/inventory` is a derived snapshot (Node/Device/Component/Asset/TaskKind ids). `GET /api/v1/system/capabilities` stays CAP-001.
- Battery deep shutdown: write sentinel JSON only. Host unit performs halt.
- Optional ROS pkgs: wrap slam_toolbox (and similar) in constructor try/except.
- Product `rosy-core.service` lives in `deploy/robot/native`. The old `core/deploy` installer is not a second unit.
- D-144: select navigation readiness from `runtime.navigation_backend`; SLAM
  requires hardware mode and a writable, bounded map output directory.

### Testing Requirements

```bash
python3 -m pytest src/runtime/core/test/ -v
```

### Common Patterns

- Config: `load_config()` deep-merges default + `~/.rosy/rosy.yaml` + `ROSY_CONFIG`.
- Auth: static tokens, roles viewer < operator < administrator (`api/deps.py`).
- Modes: IDLE / MANUAL / NAVIGATION / DOCKING / EMERGENCY. Docking outranks Nav (priority 4 vs 5).

## Dependencies

### Internal

- `interfaces` (SetLed)
- Host Agent socket via `system/host_agent_client.py`

### External

- rclpy, FastAPI, uvicorn, pydantic, PyYAML, nav2_msgs, geometry_msgs, sensor_msgs, tf2_ros
- Optional: slam_toolbox

<!-- MANUAL: -->
