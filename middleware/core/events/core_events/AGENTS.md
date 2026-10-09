<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# core_events

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Python package for the in-process event bus (EVT-001..005) and the file audit log (LOG-001). ROS-free and framework-free, so it runs under plain pytest. CORE owns the instance; this package never publishes `/cmd_vel`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `events/` | `bus.py` (EventBus: monotonic seq, ring buffer, sync subscribers, `since_seq` gap fill), `audit.py` (append-only audit file, background retention pruning, tail-first history) (see `events/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Bus subscribers are called synchronously on the publisher thread, and the audit writer is one of them. Keep `record()` append-only and cheap; pruning runs on a worker thread (the 50 Hz timer must not pay for it).
- Depend only on `core_common` (`EventMessage`, `Severity`).

### Testing Requirements

```bash
python -m pytest middleware/core/events/test -q
```

`test_audit.py` covers restart survival, retention, pruning, and health. No rclpy needed.

### Common Patterns

- Both classes share the `EventMessage` schema, so bus and file history are interchangeable for API consumers.

## Dependencies

### Internal

`core_common`

### External

None (standard library only).
