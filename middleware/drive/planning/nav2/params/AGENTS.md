
# params

**Parent context:** `../AGENTS.md`

## Purpose

Nav2 and slam_toolbox YAML. Velocity smoother output must be remappable to `nav_cmd_vel` (D-2).

## For AI Agents

### Working In This Directory

Changing max velocities here does not replace CORE/HWA profile limits — CommandManager still clips.

### Testing Requirements

None automated.

### Common Patterns

ROS 2 params YAML.

## Dependencies

### Internal

- Loaded by `launch/`

### External

- Nav2, slam_toolbox
