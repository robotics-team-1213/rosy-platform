# motion

**Parent context:** `../AGENTS.md`

## Purpose

Wheel `rosy-contracts-motion` 0.1.0. ROS-free semantic Motion Intent and DeviceControlPort types. Depends on `rosy-contracts-skill`. `COLCON_IGNORE` keeps colcon off this folder.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Host pytest for the motion types |

## For AI Agents

### Working In This Directory

- These types describe intent. They are not a second `/cmd_vel` publisher. CORE remains the only final command publisher.
- Keep the package ROS-free so Windows host pytest can import it.

### Testing Requirements

`python -m pytest contracts/motion/test -q`

### Common Patterns

Namespace package under `src/`. No `package.xml`.

## Dependencies

### Internal

- `rosy-contracts-skill` (`contracts/skill/`).

### External

- Python >= 3.12.
