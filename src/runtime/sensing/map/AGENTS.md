<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-21 -->

# map

## Purpose

Gazebo world asset for the Pinky Pro desk maze used by Control sim rigs.
D-150: the operational map home is `src/runtime/navigation/map` — this
bundle is a calibration-reference asset only, not the source of runtime maps.

## Key Files

| File | Description |
|------|-------------|
| `map_260905.world` | Desk-maze Gazebo world (2026-09-05 capture) |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `map_260905_update_v2/` | Versioned MAP 260905 bundle (world + occupancy map + docs + scripts + MANIFEST); read its README first (see `map_260905_update_v2/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Treat as a measured environment snapshot. Do not silently reshape walls to make a planner pass.
- Live Nav2 maps for the OS runtime live in `navigation/map/`, not here.

### Testing Requirements

None. Loaded by `../tools/gz/` rigs.

### Common Patterns

One world file at this level; generated maze SDF also exists under `../tools/gz/pinky_maze.sdf`.

## Dependencies

### Internal

- `../tools/gz/`

### External

- Gazebo

<!-- MANUAL: -->

