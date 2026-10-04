<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# launch

## Purpose

Real-robot bringup launch with namespace plumbing (P0-4).

## Key Files

| File | Description |
|------|-------------|
| `bringup_robot.launch.py` | Namespaced bringup, description upload, optional LiDAR/battery |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

```bash
ros2 launch bringup bringup_robot.launch.py
ros2 launch bringup bringup_robot.launch.py namespace:=rosy_01
```

- `frame_prefix` is `ns/` when namespace is set, else empty — same pattern as `upload_robot.launch.py`.
- Flags: `enable_battery`, `enable_lidar`, `use_sim_time`.

### Testing Requirements

Launch on hardware or mock; contract tests cover motor code not this file.

### Common Patterns

Python launch (XML `$(eval)` is insufficient for prefix logic).

## Dependencies

### Internal

- `description` share

### External

- launch_ros, sllidar_ros2 (when lidar enabled)

<!-- MANUAL: -->
