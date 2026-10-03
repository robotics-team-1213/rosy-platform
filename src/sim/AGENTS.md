<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# sim

## Purpose

Simulation assets and launches: shared URDF/xacro description, Gazebo worlds with multi-robot launch (`gz_multi.launch.py`), and an Isaac Sim integration area. `gz_sim` CMake no-ops on aarch64.

## Key Files

None at this level. Each package directory has its own `AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `description/` | URDF/xacro, meshes, RViz view (see `description/AGENTS.md`) |
| `gz_sim/` | Gazebo worlds, multi-robot launch, lamp plugin, launch tests (see `gz_sim/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- `gz_sim` includes `description` and `navigation` launches.
- Isaac Sim scenes and adapters live in `learning/envs/isaac/` (D-427 wave 1, ROS package `isaac_sim`); they reuse `description/` as the robot model source where practical. Do not copy Gazebo-specific plugins into Isaac Sim.
- D-98's deferred `src/site/games/games/isaac/` soccer training environment is a separate scope. This directory does not enable that environment.
- Multi-instance launch tests self-skip when `ros_gz_sim` share is absent (CI shows them as skip).

### Testing Requirements

```bash
# from src/ — needs a ROS overlay
python3 -m pytest sim/gz_sim/test -v
```

## Dependencies

### Internal

- `description`, `navigation`, and exec_depend on `src/site/fleet`.

### External

- gz_ros2_control, ros_gz (Gazebo)

<!-- MANUAL: -->
