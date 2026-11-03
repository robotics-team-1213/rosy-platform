# agent

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-app-agent` 0.1.3. ROSY agent application compositions. It depends on `rosy-contracts-skill` and `rosy-skill-manipulation`. Import root is `rosy_agent`. Palletizing rules are injected by the composition (`build_cell_owner(document_rules=...)`), never imported here (D-413 §1).

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and the integration pins |
| `src/rosy_agent/fleet_fence.py` | Fleet stop-fence composition |
| `src/rosy_agent/omx_cell_documents.py` | Wraps injected process rules into the acceptance store's validated types |
| `src/rosy_agent/transfer_provider.py` | Binds the `pallet.transfer` Skill to the OMX analytic cell planner and the local `PickPlaceRunner`; `ActionRunner` validates grant, peer, revision, stop fence and journal first |
| `src/rosy_agent/arm_transfer.py`, `cell_workflow.py` | Fleet-managed ARM_TRANSFER installation and the pick-place workflow execution |
| `src/rosy_agent/mixed_reach.py` | D-402 IK reach in the `mixed_cell.Reach` shape for the mixed planner (per arm base, profile limits, single poses only) |
| `src/rosy_agent/omx_cell_owner.py` | OMX cell owner composition |
| `src/rosy_agent/omx_sim.py` | Sim-side composition helper |
| `src/rosy_agent/barrier_journal.py` | D-780 `PHASE_WAIT`/release/expiry rows in the owner journal (safety-tagged) |
| `src/rosy_agent/barrier_supervisor.py` | D-780 barrier gate, timeout FAILED/HOLD, coordinator liveness HOLD (safety-tagged) |
| `src/rosy_agent/coordinator_api.py` | D-780 coordinator peer roles, `GetBarrier`/`ReleaseBarrier` (safety-tagged) |
| `src/rosy_agent/workcell_coordinator.py` | D-780 two-arm coordinator: barrier release, coupled stop (safety-tagged) |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/rosy_agent/` | The wheel's Python package |

## For AI Agents

### Working In This Directory

- Compose the device adapter and the manipulation Skill. Take process rules by injection. Do not publish `/cmd_vel` from this wheel.
- Fleet fence behavior has to match the stop fence the integration README describes. Do not add a second cancel path.

### Testing Requirements

Run the agent tests that import `rosy_agent` with the declared wheels installed. This folder has no `package.xml` suite.

### Common Patterns

Lazy imports of the device adapter. The wheel stays ROS-free at import of the package itself.

## Dependencies

### Internal

- `middleware/devices/omx/adapter/` (`omx_adapter`) and `middleware/skills/manipulation/`.
- `operations/processes/palletizing/` supplies `CellDocumentRules` through the composition (`deploy/robot/omx`), not by import.

### External

- PyYAML, as pinned in `pyproject.toml`.

## Manual Notes

Read [progress.md](progress.md) for current gates and append results to [logs.md](logs.md). Regenerate the module index and repository STATUS with `python tools/harness/rosy_harness.py generate`.
