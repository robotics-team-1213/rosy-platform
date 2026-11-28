
# plugins

**Parent context:** `../AGENTS.md`

## Purpose

Gazebo plugin that mirrors `lamp_control` for sim.

## For AI Agents

### Working In This Directory

Keep service/topic names aligned with `lamp_control` / `interfaces/SetLamp`.

### Testing Requirements

Build via ament_cmake; visual check in Gazebo.

### Common Patterns

C++ Gazebo plugin.

## Dependencies

### Internal

- `lamp_control` behavior
- `interfaces`

### External

- Gazebo / gz-sim headers
