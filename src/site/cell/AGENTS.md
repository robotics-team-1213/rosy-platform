<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-01 | Updated: 2026-10-01 -->

# cell

## Purpose

Rosy Cell (D-377 id `cell`, package `rosy_cell`) is the D-399 Application for palletizing and easy cell setup. The canonical ROS-free Recipe/Cell/Job compiler lives in `modules/processes/palletizing`; `rosy_cell` re-exports its public types and functions for existing callers. `cell.yaml` remains schema `rosy_cell.cell/2` (required tool-down `home` pose and `kinematics_revision`; `/1` is rejected). Fleet calls `rosy_cell.compiler.carry_z(recipe, cell, *, tol_m)` and does not reimplement it. This package never sends Motion Intents, solves IK, or judges reachability; the device's local owner does (D-376, D-399).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` / `setup.py` / `setup.cfg` | ament_python compatibility package; depends on the `rosy-palletizing` process wheel |
| `progress.md` | Gate snapshot (SOURCE…FIELD). Overwrite |
| `logs.md` | Append-only work journal |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `rosy_cell/` | One-way re-exports to `modules/processes/palletizing`; no process implementation |
| `test/` | ROS-free pytest; `conftest.py` puts the package on `sys.path` |
| `examples/omx_sim/` | C3 demo `cell.yaml`/`recipe.yaml` for the OMX-F Gazebo world `omx_cell_workcell.sdf`; `test/test_cell_omx_sim_layout_contract.py` (repo root) proves every transfer plans and the world matches |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first; append `logs.md`; overwrite `progress.md` when a gate moves; run `python tools/harness/rosy_harness.py generate`.
- Units are SI (m, rad, kg). Thresholds are always passed in from config; do not add physical defaults in code.
- `Pose` lives in `cell.py` (compiler re-exports it). `home` is a pose, not a frame, and is not an obstacle: it never enters `carry_z`.
- Pallet frame: origin at a pallet corner, +x along length, +y along width, +z up. `z_top` is the item's top face; a box Step's `target.z` is the TCP grasp height `z_top - box.grasp_depth` (C3b, D-401 보강), `approach_z` is `z_top + approach_clearance_m`. `cell.yaml` requires `fingertip_overhang_m` (tool fingertips below the TCP, from the device profile); `carry_z` hangs max(height - grasp_depth, sheet, overhang) and compile rejects grasp_depth > height - overhang.

### Testing Requirements

```bash
python -m pytest src/site/cell/test -q
```
