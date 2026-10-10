<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-10 | Updated: 2026-10-10 -->

# stuck

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-10

## Purpose

D-438/D-577 Fleet stuck judgment, moved out of `server/` by D-607 P0 (`docs/plans/2026-10-10-fleet-stuck-subpackage.md`). Fleet picks one answer per open lane stuck by fixed rules, or hands it to a human; CORE re-checks every answer (D-407). Own P6 size unit (`SIZE_UNITS` in `test/architecture/test_module_structure.py`).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `board.py` | D-407 `LineStuckBoard` — per-robot open lane stuck (CORE `line_follow.stuck` + `nav.line_stuck_opened` clearances) and `LineStuckAnswerLog`. Console is `server/web/line-stuck.js` |
| `resolver.py` | D-438 `StuckResolver` — pure rule core (R1 WAIT for a peer ahead, R2 back-off, R3/R6 lane-lost or no-motion back-off, R5 hold + human), `ResolverConfig`. No I/O |
| `lane_lost.py` | D-577 lane-lost hold rules, AI PC proposal envelope check, `peer_ahead`/`peer_behind` on trusted map poses only |
| `loop.py` | `StuckResolverLoop` — 1 s poll + hub wake, board update, sends answers as `fleet-resolver` |
| `ai_facts.py` | D-577 AI PC facts, heartbeat and proposals (`ai_observer`, no command path), routes and audit |

## For AI Agents

### Working In This Directory

- Rules, API and audit table names do not change with the move. No re-export shim under `server/`.
- `server/app.py` and `server/console_routes.py` wire this package; `resolver.py` stays pure.

### Testing Requirements

Via `tools/remote/remote_pytest.py` only: `operations/fleet/test/test_stuck_*.py`, `test_line_stuck_*.py`, `test_ai_facts.py`, `operations/situation/test`.

## Dependencies

### Internal

- `fleet.server.sqlite_policy`, `fleet.server.console_routes`, `fleet.localization.trust`, `fleet.meet`, `fleet.site_map`, `fleet.swarm.transport`

<!-- MANUAL: -->
