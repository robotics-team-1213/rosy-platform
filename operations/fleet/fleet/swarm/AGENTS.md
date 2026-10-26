<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# swarm

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-26

## Purpose

Robot endpoints, HTTP/WS transport, byte-for-byte pose relay, pure arming plans, and the FOR-004 formation session. This is where safety-after-await and liveness-decay rules apply.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `robots.py` | `RobotEndpoint`; `load_robots()` / `write_robots()` for `robots.yaml` (per-robot token, D-30) |
| `api/types.py`, `api/ports.py` | Canonical declarations and Protocols only; existing public modules reexport the same objects (D-875) |
| `transport.py` | `HttpRobotClient` and the `RobotClient` reexport — the only module that calls the robot contract |
| `relay.py` | Leader pose socket 1 → follower reference sockets N; stopped stream is 0 Hz, not last-frame repeat |
| `arming.py` | `FormationSpec` + pure pre-check/assignment; finished before the relay is touched |
| `session.py` | `FormationSession` Decision construction facade; injects the existing planner and default assigner factory |
| `session_lifecycle.py` | Safety lifecycle: arm → relay → watch → HOLD/ABORT, reform/resume and stop cleanup |
| `session_arming.py` | Member preflight and all-or-nothing arming on session-owned state |
| `session_state.py` | Reexports SessionState and HoldPolicy from api/types.py; session.py retains existing exports |

## Subdirectories

`api/` contains only the two neutral declaration leaves and their package marker. The finite import exception and purity guard are defined by [D-875](../../../../docs/adr/D-875-swarm-api-and-safety-lifecycle-boundary.md); it does not permit transport, planning math, clocks or I/O in that root.

## For AI Agents

### Working In This Directory

- Re-check safety after every `await` in `session_lifecycle.py` (`reform` / `resume`). Watcher and operator `stop` run in the gaps. `session.py` only constructs this lifecycle; stop and cleanup must not invoke planning (D-875).
- HOLD is `relay.pause()`, not a new HTTP endpoint. Resume is operator-only (SRS forbids auto-retry).
- A rejected `reform` must leave a running formation untouched — planning happens in `arming.py` first.
- Do not collapse "peer refused" and "peer closed" into one quiet return (see `docs/solutions/design-patterns/`).
- `arming.py` stays pure (no httpx/websockets/asyncio/rclpy).

### Testing Requirements

Use the repository's [remote test procedure](../../../../docs/reference/developer-guide.md) from the repository root. Run the relay, session, arming, transport and robots modules under `operations/fleet/test/`, plus `test_swarm_api_boundary.py` and `test_boundaries.py`; classify each returned log with `test/known_failures.py`. These checks do not establish device acceptance.

### Common Patterns

`SessionState`: IDLE / ARMING / RUNNING / HOLDING / STOPPED. Deduplicate pending triggers by `(reason, robot_id)`.

## Dependencies

### Internal

- `fleet.formation` for slots/assignment
- `core_common.protocol.schemas` (`RobotMode`, `SwarmFollowParams`)

### External

- httpx, websockets (transport only)

<!-- MANUAL: -->
