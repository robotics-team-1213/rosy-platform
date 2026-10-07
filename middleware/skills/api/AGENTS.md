# api

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-skill-api` 0.1.0. ROS-free versioned ROSY Skill contracts and invocations. Depends on `rosy-contracts-skill`. Import root `rosy.skills.api`.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and the skill-contract pin |
| `src/` | Namespace package `rosy.skills.api` |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

None beyond `src/`.

## For AI Agents

### Working In This Directory

- Version the invocation shape here. Do not reach into CORE or a device driver.
- Manipulation and other skill wheels depend on this one. A break shows up in their install, not in a ROS launch.

### Testing Requirements

No package-local suite. Run the manipulation and OMX integration tests after a change.

### Common Patterns

`package-dir = {"" = "src"}`.

## Dependencies

### Internal

- `contracts/skill/`.

### External

- Python >= 3.12.

## Manual Notes
