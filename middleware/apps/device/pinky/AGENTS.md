# pinky

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Pinky Pro device tree: board bringup, robot description, and the in-tree profile.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bringup/` | Launch and scripts that start the Pinky stack (see `bringup/AGENTS.md`) |
| `description/` | URDF, meshes, and rviz (see `description/AGENTS.md`) |
| `profile/` | In-tree Pinky full spec (see `profile/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- The profile YAML here is the source spec. What the robot advertises is `deploy/robot/pinky_pro/config/{profile,capabilities}.${ROSY_RUNTIME_MODE}.yaml`.
- Description frames have to match the URDF skill's conventions. Do not retarget a mesh without checking the joints.

### Testing Requirements

Bringup tests: `python -m pytest middleware/apps/device/pinky/bringup/test -q`.

### Common Patterns

Each child ROS package has its own `AGENTS.md`.

## Dependencies

### Internal

- Drivers under `middleware/drivers/`.
- CORE launch `middleware/core/gateway/launch/`.

### External

- ROS 2 Jazzy and the Pinky board libraries named by the drivers.

## Manual Notes
