<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# cell

## Purpose

Rosy Cell (D-377 id `cell`, package `rosy_cell`): the D-399 Application for palletizing and easy cell setup. ROS-free core that turns a taught cell config and a recipe into a hashed Job of `pick`/`place`/`pallet_done` Steps in the robot base frame. `cell.yaml` is schema `rosy_cell.cell/2` (required tool-down `home` pose and `kinematics_revision`; `/1` is rejected). The Job carries `carry_z`, computed only by `rosy_cell.compiler.carry_z(recipe, cell, *, tol_m)` (same checks as `compile_job`) (Fleet calls it, never re-implements it). It never sends Motion Intents, solves IK, or judges reachability; the device's local owner does (D-376, D-399).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` / `setup.py` / `setup.cfg` | ament_python, PyYAML only |
| `progress.md` | Gate snapshot (SOURCE…FIELD). Overwrite |
| `logs.md` | Append-only work journal |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `rosy_cell/` | `geometry`, `load`, `pattern`, `stack`, `sequence`, `fields`, `recipe`, `cell`, `compiler` |
| `test/` | ROS-free pytest; `conftest.py` puts the package on `sys.path` |
| `examples/omx_sim/` | C3 demo `cell.yaml`/`recipe.yaml` for the OMX-F Gazebo world `omx_cell_workcell.sdf`; `test/test_cell_omx_sim_layout_contract.py` (repo root) proves every transfer plans and the world matches |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first; append `logs.md`; overwrite `progress.md` when a gate moves; run `python tools/harness/rosy_harness.py generate`.
- Units are SI (m, rad, kg). Thresholds are always passed in from config; do not add physical defaults in code.
- `Pose` lives in `cell.py` (compiler re-exports it). `home` is a pose, not a frame, and is not an obstacle: it never enters `carry_z`.
- Pallet frame: origin at a pallet corner, +x along length, +y along width, +z up. `z_top` is the grasp height.

### Testing Requirements

```bash
python -m pytest src/site/cell/test -q
```
