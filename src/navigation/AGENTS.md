<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# navigation

## Purpose

Nav2/SLAM launch, maps, and params for the real robot and Gazebo — the hardware navigation graph. One package: `navigation`.

## Key Files

None at this level. See `navigation/AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `navigation/` | Nav2/SLAM Toolbox launch/config/maps/params, RViz config; ament_cmake (see `navigation/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Follow/session logic moved out to `src/runtime/core_features/core_features/swarm` (D-60); this tree is launch/config/maps only.
- No dedicated pytest here; integration is launch + navigation tests in `src/runtime/core/test/`.

## Dependencies

### Internal

- Consumed by `src/sim/gz_sim` launches; exec_depends on `src/hardware/bringup`.

### External

- nav2_bringup, navigation2, slam_toolbox

<!-- MANUAL: -->
