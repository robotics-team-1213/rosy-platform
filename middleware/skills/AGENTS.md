# skills

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

ROS-free Skill wheels shared by agent and site compositions. They define invocation and evidence gates. They do not run the robot loop.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `api/` | Wheel `rosy-skill-api`: versioned Skill contracts and invocations (see `api/AGENTS.md`) |
| `manipulation/` | Wheel `rosy-skill-manipulation`: manipulation Skill contracts and evidence gates (see `manipulation/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A Skill contract is not an executor. Dispatch stays with the owner and the stop fence.
- Both wheels carry `COLCON_IGNORE`.

### Testing Requirements

Importers in `integrations/robots/omx/` and `middleware/apps/device/omx/agent/` are the consumers to run after a shape change.

### Common Patterns

Namespace packages under `src/rosy/skills/`.

## Dependencies

### Internal

- `contracts/skill/` (`rosy-contracts-skill`).

### External

- Python >= 3.12.

## Manual Notes
