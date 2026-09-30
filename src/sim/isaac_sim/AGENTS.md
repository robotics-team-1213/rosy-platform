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
| `prepare_omx_urdf.py` | OMX-F/OMX-L URDF preparation for the official importer |
| `graph_contract.py` | Isaac-side action graph contract |
| `run_rosy.py` | URDFImporter → USD + ROS 2 OmniGraph runner (single robot) |
| `model_checks.py` | Asset hash and URDF mesh/joint preflight; `run_rosy.py` refuses to start without it |
| `import_omx.py` | OMX URDF → USD import and articulation check |
| `assets/` | `open_manipulator_description` (vendored reference) |
| `test/` | Host pytest: `test_graph_contract.py`, `test_model_checks.py`, `test_prepare_urdf.py` |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- This is a `sim`-domain package: outgoing edges are unrestricted (`edge_allowed`).
- Not installed on the robot; not part of any colcon build closure.
- No AGENTS.md in `assets/` — vendored reference tree.

### Testing Requirements

```bash
python -m pytest src/sim/isaac_sim/test -q
```

Host-only: `test_graph_contract.py` (cmd_vel/odom/joint_states namespace and initial-wheel contracts), `test_model_checks.py` (OMX/Pinky asset hashes and URDF mesh/joint preflight), `test_prepare_urdf.py` (URDF generation). The Isaac Sim 6.1 runtime is not exercised here — that is the ROS-SIM HOLD of D-322.

### Common Patterns

URDF reference: `package://description/…` for robot mesh; `package://open_manipulator_description/…` for the vendored arm.

## Dependencies

### Internal

- `description` (URDF mesh references)

### External

- Isaac Sim (not ROS)

<!-- MANUAL: -->
