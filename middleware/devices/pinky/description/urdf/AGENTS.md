
# urdf

**Parent context:** `../AGENTS.md`

## Purpose

xacro models for real robot and Gazebo.

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
