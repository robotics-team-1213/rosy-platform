<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-22 -->

# core_common

## Purpose

Protocol schemas (D-18 single source), config loader, identity, robot profile, capability, domain model, RMW settings. Every other package that shares a wire contract imports it; it imports no workspace package in code.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: none (leaf) |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `core_common/protocol/` | `schemas.py` — wire schema source of truth; change with `docs/reference/ROSY API & Protocol Reference.md` (D-18) |
| `core_common/domain/` | Domain model types |
| `core_common/config.py` | Default config loader. Reads the `core` share for `config/rosy.yaml` — a known back-edge (D-168 `KNOWN_CHAIN_BACK_EDGES`) |
| `core_common/identity.py`, `profile.py`, `capability.py`, `rmw.py` | Identity, hardware profile, capability manifest, RMW settings |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Leaf of the core chain. Do not import `core_events`/`core_features`/`core_api_web`/`core`.
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest src/contracts/core_common/test -q
```

## Dependencies

### Internal

none (leaf)

<!-- MANUAL: -->
