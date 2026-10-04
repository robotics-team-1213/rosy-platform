<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# swarm

## Purpose

Robot endpoints, HTTP/WS transport, byte-for-byte pose relay, pure arming plans, and the FOR-004 formation session. This is where safety-after-await and liveness-decay rules apply.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `robots.py` | `RobotEndpoint`; `load_robots()` / `write_robots()` for `robots.yaml` (per-robot token, D-30) |
| `transport.py` | `RobotClient` protocol + `HttpRobotClient` — the only module that calls the robot contract |
| `relay.py` | Leader pose socket 1 → follower reference sockets N; stopped stream is 0 Hz, not last-frame repeat |
| `arming.py` | `FormationSpec` + pure pre-check/assignment; finished before the relay is touched |
| `session.py` | `FormationSession`: arm (all-or-nothing) → relay → watch → HOLD/ABORT; `pending_triggers` while HOLDING |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Re-check safety after every `await` in `session.py` (`reform` / `resume`). Watcher and operator `stop` run in the gaps.
- HOLD is `relay.pause()`, not a new HTTP endpoint. Resume is operator-only (SRS forbids auto-retry).
- A rejected `reform` must leave a running formation untouched — planning happens in `arming.py` first.
- Do not collapse "peer refused" and "peer closed" into one quiet return (see `docs/solutions/design-patterns/`).
- `arming.py` stays pure (no httpx/websockets/asyncio/rclpy).

### Testing Requirements

```bash
python -m pytest operations/fleet/test/test_relay.py operations/fleet/test/test_session.py operations/fleet/test/test_arming.py operations/fleet/test/test_transport.py operations/fleet/test/test_robots.py -v
```

### Common Patterns

`SessionState`: IDLE / ARMING / RUNNING / HOLDING / STOPPED. Deduplicate pending triggers by `(reason, robot_id)`.

## Dependencies

### Internal

- `fleet.formation` for slots/assignment
- `core.protocol.schemas` (`RobotMode`, `SwarmFollowParams`)

### External

- httpx, websockets (transport only)

<!-- MANUAL: -->
