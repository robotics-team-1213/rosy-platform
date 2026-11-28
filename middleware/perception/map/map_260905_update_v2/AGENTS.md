
# map_260905_update_v2

**Parent context:** `../AGENTS.md`

## Purpose

Versioned MAP 260905 bundle (v2): Gazebo world, static occupancy map, human
plans, generation/validation scripts, and an integrity manifest. Read
`README.md` first — it separates verified facts from unverified proposals.

## For AI Agents

### Working In This Directory

- The 16 walls are a measured snapshot — do not reshape them to make a planner pass.
- `config/*.patch.yaml` are PROPOSALS, not finished Nav2 configs.
- End-to-end results (2026-09-20, Gazebo Harmonic): bundle integrity and world
  load PASS; physics/sensor bridge/SLAM/driving FAIL or BLOCKED — recorded in
  `../../../../docs/validation/map-260905-update-v2-2026-09-20/result.md`.

### Testing Requirements

`python -m pytest tests/ -q` — static checks only, no ROS required.

## Dependencies

### Internal

- `../../` control package; end-to-end evidence in `../../../../docs/validation/`

### External

- Gazebo Harmonic + ROS 2 Jazzy (runtime), numpy/Pillow/shapely/scipy/PyYAML/cairosvg (tools)
