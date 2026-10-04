<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# params

## Purpose

Nav2 and slam_toolbox YAML. Velocity smoother output must be remappable to `nav_cmd_vel` (D-2).

## Key Files

| File | Description |
|------|-------------|
| `nav2_params.yaml` | Nav2 stack parameters |
| `mapper_params.yaml` | slam_toolbox; watch `scan_topic` absolute vs namespaced |

## Subdirectories

None.

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

<!-- MANUAL: -->
