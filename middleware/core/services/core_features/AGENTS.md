<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# core_features

## Purpose

Python package of feature managers behind CORE's `CoreServices`, one subpackage per requirement family. Library tier: no process, no ROS imports. CORE (`middleware/core/gateway`) owns the single `/cmd_vel` output through `CommandManager.select_output()`. Features here propose, gate, or cap motion; none publishes the final command.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `maps.py` | Last OccupancyGrid / Path / Costmap snapshots for the render path (MAP-003/004); no authoring or persistence |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `command/` | Mode and source arbitration, emotion map (see `command/AGENTS.md`) |
| `safety/` | Safety manager and shadow evaluation (see `safety/AGENTS.md`) |
| `state/` | State snapshot manager (see `state/AGENTS.md`) |
| `navigation/` | Nav facade, initial pose, readiness (see `navigation/AGENTS.md`) |
| `waypoints/` | Waypoint manager (see `waypoints/AGENTS.md`) |
| `power/` | Battery policy and power manager (see `power/AGENTS.md`) |
| `docking/` | Docking and parking state machine (see `docking/AGENTS.md`) |
| `swarm/` | Formation follow (see `swarm/AGENTS.md`) |
| `diagnostics/` | Diagnostics collector (see `diagnostics/AGENTS.md`) |
| `calibration/` | Calibration session (see `calibration/AGENTS.md`) |
| `line_follow/` | Line-follow manager, clearance, stuck recovery (see `line_follow/AGENTS.md`) |
| `fleet_agent/` | Fleet enrolment and discovery (see `fleet_agent/AGENTS.md`) |
| `decision/` | Shared allowed-action judgment, D-228 (see `decision/AGENTS.md`) |
| `localization/` | D-395 CORE side: `assist.py` relays localization state/candidates/decisions, `halt.py` stops autonomy when a robot leaves LOCALIZED, `mission.py` very slow check and homing manoeuvres written to the nav slot |
| `recovery/` | `camera_fault.py`: operator-selectable camera-fault actions; reports eligibility only, no motion |
| `road_behaviour/` | D-384 `machine.py` (speed cap, keep-right branch choice), `model.py`, `table.py` (transition table rendered into the plan doc); outputs a cap, never a command |
| `traffic_policy/` | `manager.py` fail-closed policy between perception and arbitration; `observer_source.py` polls the read-only signal observer, silence on anything unconfirmed |
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
