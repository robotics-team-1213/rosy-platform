
# description

**Parent context:** `../AGENTS.md`

## Purpose

Robot URDF/xacro, visual/collision meshes, and RViz model view. First hardware is Pinky Pro. Supports `namespace` / `frame_prefix` (D-4).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `urdf/` | `robot.urdf.xacro`, `rosy.urdf.xacro`, `rosy_gz.urdf.xacro` (see `urdf/AGENTS.md`) |
| `meshes/` | `visual/*.dae`, `collision/*.stl` (see `meshes/AGENTS.md`) |
| `launch/` | `upload_robot.launch.py`, `view_robot.launch.py` (see `launch/AGENTS.md`) |
| `rviz/` | `view_robot.rviz` |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Gazebo uses `rosy_gz.urdf.xacro`. Do not break the sim-specific plugins/topics.
- Keep inertia helper in `urdf/common/insert_inertia.urdf.xacro`.
- Joint names `l_wheel_joint` / `r_wheel_joint` must stay aligned with `bringup` and `SensorMirror`.

### Testing Requirements

Launch `view_robot.launch.py` locally. ament_lint via CMake.

### Common Patterns

xacro args for namespace and use_sim_time.

## Dependencies

### Internal

- Consumed by `bringup` and `gz_sim`

### External

- xacro, robot_state_publisher, joint_state_publisher_gui
