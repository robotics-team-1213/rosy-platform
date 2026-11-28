
# meshes

**Parent context:** `../AGENTS.md`

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

### Common Patterns

One visual + one collision per link where both exist.

## Dependencies

### Internal

- Referenced from `urdf/`
