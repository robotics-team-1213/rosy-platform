<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-22 | Updated: 2026-09-24 -->

# core_features

## Purpose

Feature managers behind `CoreServices`: command arbitration, safety, state, navigation, swarm, waypoints, power, docking, diagnostics, fleet_agent, maps, line_follow, traffic_policy, vision, and shared `decision/` (allowed action id only, D-228).

Library/contract tier (D-168 P2): no process of its own. ROS-SIM/ARTIFACT/DEVICE/FIELD are judged on the runtime module that ships it (`core`, and `fleet` where it consumes it).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | Declared deps: `core_common` |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |
| `test/` | `test_docking.py` (DNC-001~003), `test_swarm.py` (SWM follow) |
| `core_features/<feature>/` | One requirement family per subpackage; split rules in `docs/plans/2026-09-06-module-split-criteria.md` |
| `core_features/maps.py` | Map read path (not SLAM) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Depends on `core_common`. Never on `core_api_web` or `core`. Never import `control` (D-126).
- Structure rules (package tier, declared coupling, direction table, 600/10k line budget): D-168, enforced by `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest src/runtime/features/test -q
```

## Dependencies

### Internal

`core_common`

<!-- MANUAL: -->
