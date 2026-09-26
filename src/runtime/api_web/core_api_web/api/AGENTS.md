<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# api

## Purpose

FastAPI surface for ROSY-API-REF-001. Factory builds the app, serves `/dashboard`, and mounts v1 routers plus WebSocket.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `app.py` | `create_app`; routers; static dashboard; CSP on HTML |
| `deps.py` | SEC-101 token auth (sha256 at rest, opaque ids); `require_role`; `get_services`; re-exports router-facing `core_features` types so v1 fan-out stops here |
| `errors.py` | ERR-101 `ApiError` + domain exception mapping |
| `ws.py` | `/ws/state` (10 Hz), `/ws/events` glob filters, `/ws/swarm/pose` (SWM-003) and `/ws/swarm/reference` (SWM-007 ingest, operator) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `v1/` | REST routers (see `v1/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Roles: viewer < operator < administrator. Teleop/mode/nav mutations need operator+.
- REST uses `Authorization: Bearer`; WebSocket auth is `?token=` (close 4401 on bad token).
- Tokens are stored as `sha256` only (D-30). `AuthContext` carries `token_id`, never the secret — do not add a field that echoes a token or anything derived from one, including to the Host Agent.
- `/metrics` is unauthenticated Prometheus text — do not put secrets there.
- `/ws/swarm/reference` is the only inbound stream (D-31). It takes operator, and a malformed frame is dropped rather than closing the socket — closing would let one bad sample put the formation into HOLD.
- Dashboard is first-party static files from `../web/`. Do not add inline scripts (CSP `script-src 'self'`).
- `app.state.core` is `CoreServices`. Routes must not touch rclpy.
- Domain conflicts (`MODE_CONFLICT`, `EMERGENCY_ACTIVE`) map to HTTP 409.

### Testing Requirements

`src/runtime/gateway/test/test_api.py`, `test_dashboard.py`.

### Common Patterns

`ApiError(code, http_status, message)` — do not raise raw HTTPException for domain failures.

## Dependencies

### Internal

- `core.services.CoreServices`, protocol schemas, web assets

### External

- FastAPI, uvicorn, pydantic

<!-- MANUAL: -->
