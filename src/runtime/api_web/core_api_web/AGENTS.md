<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# core_api_web

## Purpose

Python package holding the CORE HTTP/WebSocket surface: the FastAPI app factory, `/api/v1` routers, token auth, and the Host Agent client. It is a library tier module: CORE (`src/runtime/gateway`) imports it and remains the only external API process and the only final `/cmd_vel` publisher. Nothing here touches rclpy or publishes a command.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `api/` | App factory, auth deps, errors, grants, WebSocket, UI manifest/registry, Host Agent client (see `api/AGENTS.md`) |
| `api/v1/` | REST routers, one module per resource area (see `api/v1/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Add routes under `api/v1/` and register them in `api/v1/routes.py`; reach `core_features` only through `api/deps.py`.
- Do not import rclpy and do not publish `cmd_vel`; mutations go through `CoreServices` managers.
- Do not echo tokens (or anything derived from them) in responses, events, or logs.

### Testing Requirements

```bash
python -m pytest src/runtime/api_web/test -q
```

Tests live in the sibling `../test/` and need `fastapi`, not rclpy.

### Common Patterns

- Package-level contract and import boundary checks: `../test/test_package_contract.py` and `src/runtime/gateway/test/test_v1_import_boundary.py`.

## Dependencies

### Internal

`core_common`, `core_features`, `web_common`, `dashboard` (see `../package.xml`)

### External

`fastapi`, `uvicorn` (served by CORE)
