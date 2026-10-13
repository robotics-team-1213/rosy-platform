<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# core_features

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Python package of feature managers behind CORE's `CoreServices`, one subpackage per requirement family. Library tier: no process, no ROS imports. CORE (`middleware/core/gateway`) owns the single `/cmd_vel` output through `CommandManager.select_output()`. Features here propose, gate, or cap motion; none publishes the final command.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Installed package identity and declared source-only Drive search path |
| `_source_layout.py` | D-649 exact behavior holders; no installed repository dependency |
| `maps.py` | Last OccupancyGrid / Path / Costmap snapshots for the render path (MAP-003/004); no authoring or persistence |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `command/` | Mode and source arbitration, emotion map (see `command/AGENTS.md`) |
| `safety/` | Safety manager and shadow evaluation (see `safety/AGENTS.md`) |
| `state/` | State snapshot manager (see `state/AGENTS.md`) |
| `core_features.navigation` | Drive goal/readiness facade: `middleware/control/drive/behaviors/navigation` |
| `waypoints/` | Waypoint manager (see `waypoints/AGENTS.md`) |
| `power/` | Battery policy and power manager (see `power/AGENTS.md`) |
| `core_features.docking` | Drive docking/parking: `middleware/control/drive/behaviors/docking` |
| `core_features.swarm` | Robot reference-follow behavior: `middleware/control/drive/behaviors/swarm` |
| `diagnostics/` | Diagnostics collector (see `diagnostics/AGENTS.md`) |
| `calibration/` | Calibration session (see `calibration/AGENTS.md`) |
| `core_features.line_follow` | Drive lane/curvature/body proof and bounded recovery: `middleware/control/drive/behaviors/line_follow` |
| `fleet_agent/` | Fleet enrolment and discovery (see `fleet_agent/AGENTS.md`) |
| `decision/` | Shared allowed-action judgment, D-228 (see `decision/AGENTS.md`) |
| `core_features.localization` | Drive evidence consumer, autonomy halt and bounded pose/search lifecycle: `middleware/control/drive/behaviors/localization` |
| `recovery/` | `camera_fault.py`: operator-selectable camera-fault actions; reports eligibility only, no motion |
| `core_features.road_behaviour` | Drive road-state speed cap and branch choice: `middleware/control/drive/behaviors/road_behaviour` |
| `core_features.traffic_policy` | Drive traffic admission and signal-evidence polling: `middleware/control/drive/behaviors/traffic_policy` |
| `vision/` | `store.py` latest-only JPEG preview store (no backpressure), `transport.py` names the one handoff Core accepts |

## For AI Agents

### Working In This Directory

- Stay ROS-free and depend only on `core_common`; never import `core_api_web`, `core`, or `control` (D-126).
- A new feature that moves the robot must go through `CommandManager` slots; fail closed when evidence is missing or stale.
- Wire managers in `gateway/core/services.py`, not here.
- Structure rules (tier, coupling, 600/10k line budget): D-168, `test/architecture/test_module_structure.py`.

### Testing Requirements

```bash
python -m pytest middleware/core/services/test -q
```

Sibling `../test/` covers docking, decision, road behaviour, recovery, localization assist, swarm, safety shadow, and vision transport. These are ROS-free and run on Windows.

### Common Patterns

- Docs name contracts in docstrings (D-/SRS ids); read them before changing behaviour.
- Time and transport are injected so tests need no ROS.

## Dependencies

### Internal

`core_common`

### External

None required; `httpx` is imported lazily in `traffic_policy/observer_source.py`.
