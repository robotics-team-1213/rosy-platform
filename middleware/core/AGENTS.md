# core

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

CORE process and the libraries it loads. One robot process: rclpy on the main thread, uvicorn and FastAPI on a worker (D-1). Command Manager is the only `/cmd_vel` publisher (D-2). External clients talk HTTP to the gateway, not ROS.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `gateway/` | ROS package `core`. Entry `core.main:main`, port 8080 (see `gateway/AGENTS.md`) |
| `api_web/` | FastAPI routes served in-process (see `api_web/AGENTS.md`) |
| `events/` | Event catalogue and bus (see `events/AGENTS.md`) |
| `services/` | Command, safety, power, docking, navigation facade, and the other managers (see `services/AGENTS.md`) |
| `navigation/` | Nav2 launch, params, and maps (see `navigation/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Do not split CORE into two processes. Do not publish `/cmd_vel` from `api_web` or from Nav2 directly.
- Policy modules stay free of ROS imports so pytest runs without rclpy.
- `slam_toolbox` is optional and is imported inside try/except, not at module top.

### Testing Requirements

`python -m pytest middleware/core/gateway/test middleware/core/events/test middleware/core/services/test -q` for the host suites that do not need a live graph. Navigation launch checks need Linux.

### Common Patterns

Config merge: `contracts/foundation/config/rosy_default.yaml`, then `~/.rosy/rosy.yaml`, then `ROSY_CONFIG`.

## Dependencies

### Internal

- `contracts/foundation`, `contracts/ros_idl`, and `shared/web`.

### External

- rclpy, FastAPI, uvicorn, pydantic, Nav2. slam_toolbox optional.

## Manual Notes
