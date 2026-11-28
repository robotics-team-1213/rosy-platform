
# launch

**Parent context:** `../AGENTS.md`

## Purpose

XML launches for Nav2, SLAM, localization, and Gazebo variants.

## Key Files

| File | Description |
|------|-------------|
| `hardware.launch.py` | Composes robot bringup with localization or SLAM from `navigation_backend`; validates Device limits and optionally injects measured footprints |
| `mapping_bringup_launch.xml` | Real-robot Nav2 navigation stack without AMCL/map_server, paired with SLAM Toolbox |
| `navigation_launch.xml` | Navigation stack; smoother output remaps to `nav_cmd_vel` (D-2) |

## For AI Agents

### Working In This Directory

- The Flask-era `web_*.launch.xml` entry points are deleted (2026-09-29, scorecard §6): `core` starts from its own launch/deploy, never from navigation XML (D-3).
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
