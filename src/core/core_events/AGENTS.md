<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# core_events

## Purpose

In-process EventBus and file audit log (D-8).

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: `core_common` |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `core_events/events/` | EventBus + audit writer |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Depends only on `core_common`.
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/test_module_structure.py`.

### Testing Requirements

```bash
PYTHONPATH=src/core:src python -m pytest src/core/core/test -q
```

## Dependencies

### Internal

`core_common`

<!-- MANUAL: -->
