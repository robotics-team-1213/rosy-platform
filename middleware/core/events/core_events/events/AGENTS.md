
# events

**Parent context:** `../AGENTS.md`

## Purpose

EVT-001–005 in-process bus (D-8): monotonic seq, ring buffer, subscriber broadcast, `since_seq` gap fill.

## Key Files

| File | Description |
|------|-------------|
| `audit.py` | `FileAuditLog` JSONL under the data dir (LOG-001, 30-day retention). Append-only writes; reads filter in memory and never rewrite; the write path prunes at most hourly outside the lock; `health()` reports write/prune failures |

## For AI Agents

### Working In This Directory

- Event `type` strings are dotted (`system.boot`, `battery.warning`). Match API ref §8.
- Buffer default 1000. WS layer filters with glob patterns.

### Testing Requirements

`test_core_logic.py`, API events tests.

### Common Patterns

`publish(type, source=..., data=..., severity=...)`.

## Dependencies

### Internal

- `protocol.schemas.EventMessage`
