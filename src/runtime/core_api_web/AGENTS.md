<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-24 -->

# core_api_web

## Purpose

FastAPI app, `/api/v1` routers, dashboard static assets, host-agent client.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: `core_common`, `core_features`, `web_common` |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `core_api_web/api/` | `app.py`, `deps.py` facade (v1 routers import features only through it), `v1/` |
| `core_api_web/web/` | Dashboard static files; colour tokens come from `web_common` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- v1 routers reach `core_features` only through `api/deps` (`test_v1_import_boundary.py`).
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest src/runtime/core_api_web/test -q
```

## Dependencies

### Internal

`core_common`, `core_features`, `web_common`

<!-- MANUAL: -->
