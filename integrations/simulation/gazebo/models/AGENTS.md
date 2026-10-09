<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# models

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

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
| `crosswalk_pedestrian_legs/` | D-573 sim pedestrian: two 0.60 m leg cylinders, static (spawned by the crosswalk baseline runner) |
| `crosswalk_figurine_150/` | D-573 sim figurine 0.15 m (field minimum, above the 0.125 m LiDAR plane) |
| `crosswalk_figurine_100/` | D-573 sim figurine 0.10 m (below the LiDAR plane, blind case) |

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
