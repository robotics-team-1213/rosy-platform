<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-24 -->

# core_api_web

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

FastAPI app, `/api/v1` routers, and the host-agent client. Operator screens are `middleware/ui/robot`.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: `core_common`, `core_features`, `web_common`, `dashboard` |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `core_api_web/api/` | `app.py`, `deps.py` facade (v1 routers import features only through it), `v1/`. Screens are `middleware/ui/robot`; tokens are `shared/web` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core_api_web/` | Python package: FastAPI app, `/api/v1` routers, auth, Host Agent client (see `core_api_web/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- v1 routers reach `core_features` only through `api/deps` (`test_v1_import_boundary.py`).
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest middleware/core/api_web/test -q
```

## Dependencies

### Internal

`core_common`, `core_features`, `web_common`, `dashboard`

<!-- MANUAL: -->
