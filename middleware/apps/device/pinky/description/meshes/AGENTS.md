<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# meshes

## Purpose

Visual Collada and convex collision STL for Pinky Pro links (base, wheels, caster, cameras, lamp, RPLidar, screen).

## Key Files

None at this level.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `visual/` | `*.dae` visuals (binary; no AGENTS.md) |
| `collision/` | `*.stl` collisions (binary; no AGENTS.md) |

## For AI Agents

### Working In This Directory

Do not retarget mesh filenames without updating xacro. Treat as vendor assets.

### Testing Requirements

None.

### Common Patterns

One visual + one collision per link where both exist.

## Dependencies

### Internal

- Referenced from `urdf/`

### External

None.

<!-- MANUAL: -->
