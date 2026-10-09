# simulation

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Simulator adapters for ROSY. The Gazebo package is the live simulation tree.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `gazebo/` | Worlds, models, plugins, launch, and tests (see `gazebo/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Sim must not become the operational command path. CORE still owns the final `/cmd_vel` on a real robot.
- Multi-robot namespaces follow D-4. Do not invent a default robot number.

### Testing Requirements

See `gazebo/AGENTS.md` and `gazebo/test/AGENTS.md`.

### Common Patterns

ament packages keep their own `AGENTS.md` one level down.

## Dependencies

### Internal

- Robot description and Nav2 params consumed by the Gazebo launch files.

### External

- Gazebo (ros_gz) on a Linux host. Not a Windows host dependency.

## Manual Notes
