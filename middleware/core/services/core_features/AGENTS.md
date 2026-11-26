<!-- Parent: ../AGENTS.md -->

# core_features

**Parent context:** `../AGENTS.md`

## Purpose

Python package of feature managers behind CORE's `CoreServices`, one subpackage per requirement family. Library tier: no process, no ROS imports. CORE (`middleware/core/gateway`) owns the single `/cmd_vel` output through `CommandManager.select_output()`. Features here propose, gate, or cap motion; none publishes the final command.

Subpackages with an `AGENTS.md` (`command/`, `safety/`, `state/`, `waypoints/`, `power/`, `diagnostics/`, `calibration/`, `fleet_agent/`, `decision/`) document themselves. `core_features.{navigation,docking,swarm,line_follow,localization,road_behaviour,traffic_policy}` are Drive facades onto `middleware/drive/behaviors/<name>` (`_source_layout.py`, D-649). The D-1046 SLAM fallback lives in `behaviors/localization` (`slam_health.py`, `slam_fallback.py`: stop first, zero velocity 2 s, host switch at machine grade, goals refused until a post-restart LOCALIZED, one switch per boot, no way back). `recovery/camera_fault.py` reports eligibility only, no motion. `vision/` is a latest-only JPEG preview store (no backpressure) with one accepted handoff in `transport.py`. `maps.py` keeps the last OccupancyGrid/Path/Costmap snapshots for rendering (MAP-003/004).

## For AI Agents

### Working In This Directory

- Stay ROS-free and depend only on `core_common`; never import `core_api_web`, `core`, or `control` (D-126).
- A new feature that moves the robot must go through `CommandManager` slots; fail closed when evidence is missing or stale.
- Wire managers in `gateway/core/services.py`, not here.
- Structure rules (tier, coupling, 600/10k line budget): D-168, `test/architecture/test_module_structure.py`.
- Docs name contracts in docstrings (D-/SRS ids); read them before changing behaviour. Time and transport are injected so tests need no ROS. `httpx` is imported lazily in `traffic_policy/observer_source.py`.

### Testing Requirements

```bash
python -m pytest middleware/core/services/test -q
```

Sibling `../test/` covers docking, decision, road behaviour, recovery, localization assist, swarm, safety shadow, and vision transport; ROS-free, runs on Windows.
