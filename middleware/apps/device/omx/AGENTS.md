# omx

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

OMX on the robot: the ROS adapter, the profile, and the ROS-free agent composition wheel.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `adapter/` | ROS package `omx_adapter` (see `adapter/AGENTS.md`) |
| `profile/` | OMX profile data (see `profile/AGENTS.md`) |
| `agent/` | Wheel `rosy-app-agent` (see `agent/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- The adapter is the ROS workspace package. The agent wheel must not grow a direct ROS import of its own.
- Keep planner and runtime types in the adapter so the integration wheel can reuse them.

### Testing Requirements

`python -m pytest middleware/apps/device/omx/adapter/test -q` for the adapter. Agent tests follow `agent/AGENTS.md`.

### Common Patterns

`COLCON_IGNORE` on the wheel only. The adapter keeps `package.xml`.

## Dependencies

### Internal

- `integrations/robots/omx/` and `operations/processes/palletizing/`.

### External

- Declared in `agent/pyproject.toml` and the adapter `package.xml`.

## Manual Notes
