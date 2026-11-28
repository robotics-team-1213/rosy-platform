
# launch

**Parent context:** `../AGENTS.md`

## Purpose

Upload URDF to robot_state_publisher and optional RViz view.

## For AI Agents

### Working In This Directory

Keep prefix logic identical to `bringup/launch/bringup_robot.launch.py`.

### Testing Requirements

Manual `ros2 launch description view_robot.launch.py`.

### Common Patterns

Python launch; xacro substitutions.

## Dependencies

### Internal

- `../urdf`, `../rviz`

### External

- xacro, robot_state_publisher, rviz2
