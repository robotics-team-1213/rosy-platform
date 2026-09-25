<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-24 -->

# core

## Purpose

CORE domain — the external API gateway and the shared contracts. `core` (`runtime/core`) is the only ROS+FastAPI gateway process; `core_common` owns the protocol schemas that outside clients and packages share (D-18); `core_events` owns the event bus/audit; `core_features` owns the feature managers (command/safety/navigation/power/docking/…); `core_api_web` owns REST/WS routes, the dashboard static files, and the host-agent client. `interfaces` holds the custom service types.

## Key Files

None at this level. Each package directory has its own `AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core/` | Gateway kernel: `main.py`/`node.py`/`services.py`, `bridge/` (only ROS I/O), `system/` (see `core/AGENTS.md`) |
| `core_common/` | Protocol schemas, config, identity, profile, capability, domain model, rmw (see `core_common/AGENTS.md`) |
| `core_events/` | EventBus + file audit log (see `core_events/AGENTS.md`) |
| `core_features/` | Command arbitration, safety, state, navigation, swarm, waypoints, power, docking, diagnostics, fleet_agent, maps (see `core_features/AGENTS.md`) |
| `core_api_web/` | FastAPI app + `/api/v1`, dashboard web assets, host-agent client (see `core_api_web/AGENTS.md`) |
| `interfaces/` | Custom srv: Emotion, SetBrightness, SetLamp, SetLed (see `interfaces/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Declared dependency chain is one-way: `core_common` ← `core_events` ← `core`, and `core_common` ← `core_features` ← `core_api_web` ← `core`. Do not add back-edges.
- `core_common.protocol.schemas` (`core_common/core_common/protocol/schemas.py`) is the schema source of truth — change it together with `docs/reference/ROSY API & Protocol Reference.md` (D-18).
- Command Manager is the only `cmd_vel` publisher (D-2). External clients never speak ROS.

### Testing Requirements

```bash
# from src/
python3 -m pytest runtime/core/test/ runtime/core_events/test/ runtime/core_features/test/ hmi/web_common/test/ -v
```

### Common Patterns

- Policy/manager modules stay ROS-import-free so host pytest runs without rclpy.

## Dependencies

### Internal

- Consumed by `src/site/fleet` (schemas only), `deploy/`, and the dashboard clients.

### External

- ROS 2 Jazzy, rclpy, Nav2, FastAPI/uvicorn, pydantic

<!-- MANUAL: -->
