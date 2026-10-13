# world

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11 (D-630)

## Purpose

Wheel `rosy-world` 0.1.1. ROS-free observation references and current-state projections. `rosy.world.api` holds evidence references; `rosy.world.state.projections.map_pose` owns the existing sighting/odom projection consumed by Fleet. `COLCON_IGNORE` keeps colcon off this folder.

D-667: observation types and pure input validity are implemented once in `core_common.observation`. Existing World API/projection imports re-export those same objects. The wheel declares `core_common`; installed-wheel tests include that contract wheel. World still owns observation producers, state and physical calibration.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Package `rosy-world` |
| `src/rosy/world/api/` | Immutable observation/evidence references |
| `src/rosy/world/state/projections/map_pose.py` | Existing MapPose tracker: sightings, operator pins and odom bridging; stdlib only |
| `src/rosy/world/state/projections/road_region.py` | D-665 camera-local region input validity: timestamps, frame, calibration, transform and evidence binding; offline evaluation consumer, no image geometry or driving |
| `test/` | Fleet compatibility identity and independent wheel installation |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

`api/` and `state/projections/` are namespace package responsibilities beneath `src/rosy/world/`.

## For AI Agents

### Working In This Directory

- References describe evidence. They are not the JPEG path and not a Fleet policy decision.
- Keep the package ROS-free.
- MapPose projects received observations into current state. Its odom dead reckoning is not action-conditioned future prediction or goal-completion evidence.
- Fleet keeps the service, transaction and admission owners. `fleet.localization.map_pose` aliases the implementation module and preserves object identity.

### Testing Requirements

Run `operations/world/test` and the affected Fleet suites through `tools/remote/remote_pytest.py` on committed HEAD. No laptop pytest (D-584). The wheel test builds and installs a copy in the remote pytest temporary directory.

### Common Patterns

Single namespace package. No third-party dependencies in `pyproject.toml`.

## Dependencies

### Internal

- Site and learning code that cites an observation by reference.

### External

- Python >= 3.12.

## Manual Notes
