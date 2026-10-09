<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# calibration

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

D-321 addendum: the attended calibration session lease. One session per robot, renewed by heartbeat within `ttl_s`. While alive, the state snapshot carries `activity: CALIBRATING` and the API fences drive/mode writes from other tokens (`CALIBRATION_ACTIVE`). Policy only: no ROS, no mode transitions, no `cmd_vel` (D-2).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Re-exports `CalibrationSessionManager`, `CalibrationSessionError` |
| `session.py` | Lease lifecycle (start/heartbeat/end/expiry), `activity()` for the snapshot, `blocking(token_id)` for the API fence, `calibration.session_*` events |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Routers reach this only through `svc.calibration` and `core_api_web.api.deps` (import boundary test).
- Expiry is lazy (every read) plus the CORE power timer calls `expire_due()`; the expired event is emitted once.
- E-stop must never consult this lease. Stopping actions (e-stop, line-follow OFF) stay open to every token.
- Endpoint and `activity` shapes are consumed by `tools/calibration/run_calibration.py` and the screens; changes are an API Ref MINOR bump.

### Testing Requirements

`python -m pytest middleware/core/gateway/test/test_calibration_session.py -q`
