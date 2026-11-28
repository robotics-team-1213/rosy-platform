
# core_events

**Parent context:** `../AGENTS.md`

## Purpose

In-process EventBus and file audit log (D-8).

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core_events/` | Python package: EventBus and file audit log (see `core_events/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Depends only on `core_common`.
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest middleware/core/events/test -q
```

## Dependencies

### Internal

`core_common`
