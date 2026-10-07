# processes

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Site processes that compile or run a cell task. They sit behind Fleet and the gateway wheel.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `cell/` | ROS package `rosy_cell` (see `cell/AGENTS.md`) |
| `palletizing/` | Wheel `rosy-palletizing`, harness module `palletizing` (see `palletizing/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A process plans and tracks work. Motion commands still go through CORE on the robot and through the existing OMX owner on the arm.
- Read the child harness files (`progress.md`, `logs.md`) before changing a module that has them.

### Testing Requirements

Each child `AGENTS.md` names the suite.

### Common Patterns

`cell/` is an ament package. `palletizing/` is a wheel with `COLCON_IGNORE`.

## Dependencies

### Internal

- Fleet trip and dispatch APIs in `operations/fleet/`.
- Skill contracts for pallet transfer.

### External

- Named by each child.

## Manual Notes
