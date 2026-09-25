<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# map_260905_update_v2

## Purpose

Versioned MAP 260905 bundle (v2): Gazebo world, static occupancy map, human
plans, generation/validation scripts, and an integrity manifest. Read
`README.md` first — it separates verified facts from unverified proposals.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Bundle guide: file roles, change summary, verified/unverified boundary |
| `MANIFEST.sha256` | Integrity list — check with `scripts/validate_bundle.py` |
| `worlds/` / `original/` | Updated and source-preserved Gazebo worlds |
| `maps/` | Nav2 `map_260905.yaml` + 5 mm `.pgm` (+ png preview variant) |
| `docs/` | Gazebo/Nav2 cautions, parameter reference, validation checklist, sources |
| `scripts/` / `tests/` | Map regeneration, sim-param preparation, static checks |
| `reports/` | Build/validation outputs from the 2026-09-20 run |

## For AI Agents

### Working In This Directory

- The 16 walls are a measured snapshot — do not reshape them to make a planner pass.
- `config/*.patch.yaml` are PROPOSALS, not finished Nav2 configs.
- End-to-end results (2026-09-20, Gazebo Harmonic): bundle integrity and world
  load PASS; physics/sensor bridge/SLAM/driving FAIL or BLOCKED — recorded in
  `../../../../../docs/validation/map-260905-update-v2-2026-09-20/result.md`.

### Testing Requirements

`python -m pytest tests/ -q` — static checks only, no ROS required.

## Dependencies

### Internal

- `../../` control package; end-to-end evidence in `../../../../../docs/validation/`

### External

- Gazebo Harmonic + ROS 2 Jazzy (runtime), numpy/Pillow/shapely/scipy/PyYAML/cairosvg (tools)

<!-- MANUAL: -->
