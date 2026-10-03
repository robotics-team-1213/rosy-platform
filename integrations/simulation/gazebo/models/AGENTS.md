<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# models

## Purpose

Gazebo model assets (robot mesh, shelf SDF, images). Binary/mesh children have no AGENTS.md.

## Key Files

| File | Description |
|------|-------------|
| `PLACE_GZ_MODELS` | Marker/notes for placing models on the Gazebo path |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `robot/` | `jetcobot.dae` (legacy mesh name) |
| `shelf/` | `model.sdf`, `model.config`, meshes, thumbnails |
| `img/` | `pinklab.jpg`, `pinklab_half.jpg` |

## For AI Agents

### Working In This Directory

Do not rename SDF model names without updating worlds. `original_modl.sdf` looks like an upstream typo — leave unless you migrate references.

### Testing Requirements

None.

### Common Patterns

Gazebo model.config + model.sdf.

## Dependencies

### Internal

- Worlds in `../worlds`

### External

- Gazebo

<!-- MANUAL: -->
