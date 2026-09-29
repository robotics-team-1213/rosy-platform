<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-30 | Updated: 2026-09-30 -->

# isaac_sim

## Purpose

Isaac Sim assets and Python probes (D-322). Not a buildable package — marker only so the D-168 structure scan sees it. URDF worlds, graph contract helpers, and the Isaac-side run scripts live here.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python marker; `exec_depend` on `description` (URDF reference) |
| `progress.md` | Gate snapshot (overwrite; state of record) |
| `logs.md` | Append-only journal |
| `index.md` | Generated (do not edit) |
| `prepare_urdf.py` | Adapts the description URDF for Isaac |
| `graph_contract.py` | Isaac-side action graph contract |
| `assets/` | `open_manipulator_description` (vendored reference) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- This is a `sim`-domain package: outgoing edges are unrestricted (`edge_allowed`).
- Not installed on the robot; not part of any colcon build closure.
- No AGENTS.md in `assets/` — vendored reference tree.

### Testing Requirements

None (no own tests; the graph contract is tested by `test_graph_contract.py`).

### Common Patterns

URDF reference: `package://description/…` for robot mesh; `package://open_manipulator_description/…` for the vendored arm.

## Dependencies

### Internal

- `description` (URDF mesh references)

### External

- Isaac Sim (not ROS)

<!-- MANUAL: -->
