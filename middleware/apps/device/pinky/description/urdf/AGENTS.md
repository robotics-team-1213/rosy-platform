<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# urdf

## Purpose

xacro models for real robot and Gazebo.

## Key Files

| File | Description |
|------|-------------|
| `robot.urdf.xacro` | Primary robot model |
| `rosy.urdf.xacro` | ROSY-named wrapper |
| `rosy_gz.urdf.xacro` | Gazebo plugins/topics variant |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `common/` | `insert_inertia.urdf.xacro` inertia helper (no separate AGENTS.md) |

## For AI Agents

### Working In This Directory

- Wheel joints must match bringup names.
- Sim-specific tags stay in `rosy_gz.urdf.xacro` only.

### Testing Requirements

xacro CLI / view_robot launch.

### Common Patterns

xacro includes; mesh paths `package://description/meshes/...`.

## Dependencies

### Internal

- `../meshes/visual`, `../meshes/collision`

### External

- xacro

<!-- MANUAL: -->
