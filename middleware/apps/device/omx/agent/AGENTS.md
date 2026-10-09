# agent

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-app-agent` 0.1.0. ROSY agent application compositions. It depends on `rosy-integration-robot-omx` and `rosy-palletizing`. Import root is `rosy_agent`.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and the integration pins |
| `src/rosy_agent/fleet_fence.py` | Fleet stop-fence composition |
| `src/rosy_agent/omx_cell_documents.py` | Cell document reads for the agent |
| `src/rosy_agent/omx_cell_owner.py` | OMX cell owner composition |
| `src/rosy_agent/omx_sim.py` | Sim-side composition helper |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/rosy_agent/` | The wheel's Python package |

## For AI Agents

### Working In This Directory

- Compose the existing integration and palletizing owners. Do not publish `/cmd_vel` from this wheel.
- Fleet fence behavior has to match the stop fence the integration README describes. Do not add a second cancel path.

### Testing Requirements

Run the agent tests that import `rosy_agent` with the declared wheels installed. This folder has no `package.xml` suite.

### Common Patterns

Lazy imports of the device adapter. The wheel stays ROS-free at import of the package itself.

## Dependencies

### Internal

- `integrations/robots/omx/`.
- `operations/processes/palletizing/` (`rosy-palletizing`).

### External

- PyYAML, as pinned in `pyproject.toml`.

## Manual Notes
