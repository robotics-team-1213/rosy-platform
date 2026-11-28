
# core_features

**Parent context:** `../AGENTS.md`

## Purpose

The `core_features` distribution installs common CORE command arbitration, safety, state, waypoints, power, diagnostics, Fleet attachment, maps, preview transport and local allowed-action judgment. D-649 places Base navigation, swarm, docking, localization, line-follow, road and traffic behavior sources in `middleware/drive/behaviors`; this same distribution installs them once under their original `core_features.*` identities. General calibration-session leases and camera-fault action eligibility remain CORE admission policy.

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `core_features/maps.py` | Map read path (not SLAM) |
| `drive/behaviors/docking` | D-766 size unit: docking phases, relative observations, seating and charging evidence; installed once as `core_features.docking` |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `core_features/` | Python package: feature managers, one subpackage per requirement family (see `core_features/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Depends on `core_common`. Never on `core_api_web` or `core`. Never import `control` (D-126).
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest middleware/core/services/test -q
```

## Dependencies

### Internal

`core_common`

## Current source names (D-749)

`core_features/action_rules`, `safety_gate`, `preview` hold the implementation. The old decision/safety/vision entries are source facades; installed names remain `core_features.decision/safety/vision`. No second runtime implementation.
