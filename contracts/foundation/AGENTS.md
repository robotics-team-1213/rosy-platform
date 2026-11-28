
# core_common

**Parent context:** `../AGENTS.md`

## Purpose

Protocol schemas (D-18 single source), config loader, identity, robot profile, capability, domain model, RMW settings. Every other package that shares a wire contract imports it; it imports no workspace package in code.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `core_common/protocol/` | `schemas.py` — wire schema source of truth; change with `docs/reference/ROSY API & Protocol Reference.md` (D-18) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core_common/` | Importable package: config, identity, profile, capability, domain (see `core_common/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Leaf of the core chain. Do not import `core_events`/`core_features`/`core_api_web`/`core`.
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest contracts/foundation/test -q
```

## Dependencies

### Internal

none (leaf)
