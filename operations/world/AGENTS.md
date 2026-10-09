# world

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-world` 0.1.0. ROS-free observation and evidence references. Import root `rosy.world.api`. `COLCON_IGNORE` keeps colcon off this folder.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Package `rosy-world` |
| `src/` | Namespace package `rosy.world.api` |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

None beyond `src/`.

## For AI Agents

### Working In This Directory

- References describe evidence. They are not the JPEG path and not a Fleet policy decision.
- Keep the package ROS-free.

### Testing Requirements

No local ament suite. Run the importers that pin `rosy-world` after a shape change.

### Common Patterns

Single namespace package. No third-party dependencies in `pyproject.toml`.

## Dependencies

### Internal

- Site and learning code that cites an observation by reference.

### External

- Python >= 3.12.

## Manual Notes
