<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# description

## Purpose

Robot URDF/xacro, visual/collision meshes, and RViz model view. First hardware is Pinky Pro. Supports `namespace` / `frame_prefix` (D-4).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_cmake; xacro, robot_state_publisher |
| `CMakeLists.txt` | Installs urdf, meshes, launch, rviz |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `urdf/` | `robot.urdf.xacro`, `rosy.urdf.xacro`, `rosy_gz.urdf.xacro` (see `urdf/AGENTS.md`) |
| `meshes/` | `visual/*.dae`, `collision/*.stl` (see `meshes/AGENTS.md`) |
| `launch/` | `upload_robot.launch.py`, `view_robot.launch.py` (see `launch/AGENTS.md`) |
| `rviz/` | `view_robot.rviz` |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Gazebo uses `rosy_gz.urdf.xacro`. Do not break the sim-specific plugins/topics.
- Keep inertia helper in `urdf/common/insert_inertia.urdf.xacro`.
- Joint names `left_wheel_joint` / `right_wheel_joint` must stay aligned with `bringup`.

### Testing Requirements

Launch `view_robot.launch.py` locally. ament_lint via CMake.

### Common Patterns

xacro args for namespace and use_sim_time.

## Dependencies

### Internal

- Consumed by `bringup` and `gz_sim`

### External

- xacro, robot_state_publisher, joint_state_publisher_gui

<!-- MANUAL: -->
