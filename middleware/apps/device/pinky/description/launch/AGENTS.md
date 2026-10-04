<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# launch

## Purpose

Upload URDF to robot_state_publisher and optional RViz view.

## Key Files

| File | Description |
|------|-------------|
| `upload_robot.launch.py` | xacro + RSP with namespace/frame_prefix |
| `view_robot.launch.py` | Same plus RViz |

## Subdirectories

None.

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

<!-- MANUAL: -->
