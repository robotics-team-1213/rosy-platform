<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-21 -->

# launch

## Purpose

XML launches for Nav2, SLAM, localization, and Gazebo/web variants.

## Key Files

| File | Description |
|------|-------------|
| `hardware.launch.py` | Composes robot bringup with localization or SLAM from `navigation_backend`; validates Device limits and optionally injects measured footprints |
| `bringup_launch.xml` | Real-robot Nav2 bringup (composition FQN, lifecycle list) |
| `mapping_bringup_launch.xml` | Real-robot Nav2 navigation stack without AMCL/map_server, paired with SLAM Toolbox |
| `navigation_launch.xml` | Navigation stack; smoother output remaps to `nav_cmd_vel` (D-2) |
| `localization_launch.xml` | AMCL localization |
| `map_building.launch.xml` / `map_view.launch.xml` | SLAM mapping |
| `nav2_view.launch.xml` | RViz nav view |
| `gz_bringup_launch.xml` | Includes `bringup_launch.xml` with `use_sim_time:=true` |
| `gz_map_building.launch.xml` / `gz_map_view.launch.xml` / `gz_nav2_view.launch.xml` / `gz_web_nav2.launch.xml` / `gz_web_slam.launch.xml` | Gazebo counterparts |
| `web_nav2.launch.xml` / `web_slam.launch.xml` | Nav2/SLAM + `core` FastAPI (Flask node removed, D-3) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Prefer `core` + `gz_multi.launch.py` over `web_*.xml` for new work (D-3).
- When including from `gz_multi`, preserve namespace.
- Hardware defaults require a mounted Device profile and a loadable site map.
  `allow_demo_map:=true` is an explicit simulation/bench override. A measured
  mobile state is selected with `footprint_profile_file` and `footprint_state`.
- The `slam` backend is the exception to the existing-map requirement and must use mapper readiness; the default `localization` backend preserves the map gate.

### Testing Requirements

Launch-level only.

### Common Patterns

XML `include` of nav2_bringup with param files from `../params`.

## Dependencies

### Internal

- `../params`, `../map`, `../rviz`, `../scripts`

### External

- Nav2, slam_toolbox

<!-- MANUAL: -->
