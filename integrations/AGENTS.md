# integrations

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Adapters that bind ROSY contracts to a robot or a simulator. Placement and import boundaries follow the ownership manifest. This folder is not itself a ROS package.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `robots/` | Robot adapters. OMX binds the pallet transfer Skill to the cell planner (see `robots/AGENTS.md`) |
| `simulation/` | Simulator adapters. Gazebo lives in `gazebo/` (see `simulation/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- An integration projects an accepted grant into an existing owner. It does not become a second command publisher.
- Do not import this tree from `middleware/core/gateway` to sneak a device path around CORE.

### Testing Requirements

Run the child package tests named in `robots/omx/` and `simulation/gazebo/AGENTS.md`.

### Common Patterns

Wheels carry `COLCON_IGNORE`. ROS packages keep `package.xml` beside their own `AGENTS.md`.

## Dependencies

### Internal

- Skill and execution contracts under `contracts/`. Device runtime under `middleware/apps/device/`.

### External

- Gazebo / ros_gz only inside `simulation/gazebo/`.

## Manual Notes
