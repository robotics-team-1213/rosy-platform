
# rosy_cell

**Parent context:** `../AGENTS.md`

## Purpose

D-413 compatibility import facade for `operations/processes/palletizing`, whose implementation owns the following behavior. Do not restore process implementations here. Rosy Cell (D-399): parses `recipe.yaml` (`rosy_cell.recipe/1`) and `cell.yaml` (`rosy_cell.cell/2`), lays out pallet patterns, and compiles a hashed Job of `pick`/`place`/`pallet_done` Steps in the robot base frame. It plans no motion, solves no IK and judges no reachability; the device owner does (D-376, D-399).

## Key Files

| File | Description |
|------|-------------|
| `pattern.py` | Single-layer placements in the pallet frame |
| `sequence.py` | Order inside a layer: far-from-base first; gripper clearance is not modelled |

## For AI Agents

### Working In This Directory

- `carry_z` is owned by `rosy.processes.palletizing.compiler.carry_z`; this package only re-exports it. Fleet calls it and must not re-implement it.
- Thresholds (`tol_m` etc.) are passed in; do not add physical defaults. Units are SI.
- Reject unknown schema versions (`cell/1` is invalid); loaders raise via `fields.py` with the field name.
- No `rclpy`, no network, no I/O beyond YAML loading.

### Testing Requirements

```bash
python -m pytest operations/processes/cell/test -q
```

Tests: `test_cell.py`, `test_cell_frame.py`, `test_recipe.py`, `test_pattern_grid.py`, `test_pattern_split.py`, `test_stack.py`, `test_sequence.py`, `test_compiler.py`, `test_cell_package.py` (fixtures in `test/fixtures/`).

### Common Patterns

Frozen dataclasses for value objects; loaders validate and fail with a precise field path; hashing makes a Job reproducible from its inputs.

## Dependencies

### Internal

- `operations/processes/palletizing` owns the process implementation. This package preserves legacy imports only.

### External

- PyYAML
