<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# state

## Purpose

CORE-001 immutable snapshots (~10 Hz). Thread-safe; API and WS read `snapshot()`.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `manager.py` | `StateManager`: pose, velocity, battery, mode, nav, power, health, safety, swarm |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Snapshots are pydantic models from `protocol.schemas`. Add fields there first.
- Lock is short; do not I/O inside `snapshot()`.

### Testing Requirements

`test_core_logic.py`

### Common Patterns

Monotonic `seq` on each snapshot.

## Dependencies

### Internal

- `core.protocol.schemas`

### External

None.

<!-- MANUAL: -->
