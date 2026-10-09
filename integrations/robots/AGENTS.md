# robots

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Robot integration wheels. They bind a ROS-free Skill to a device owner that already exists. They do not ship a ROS graph of their own.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `omx/` | Wheel `rosy-integration-robot-omx`: pallet transfer Skill onto the OMX cell planner and `PickPlaceRunner` (see `omx/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Cancellation stays with the runner that owns the active goal.
- No direct ROS imports in the OMX integration. The adapter package supplies device types.

### Testing Requirements

See `omx/AGENTS.md`. CI installs this wheel next to the manipulation Skill wheel before consumer tests.

### Common Patterns

`COLCON_IGNORE` plus `pyproject.toml`. README in the child is the binding story.

## Dependencies

### Internal

- `middleware/skills/manipulation/` and `middleware/apps/device/omx/adapter/`.

### External

None beyond the child's declared wheels.

## Manual Notes
