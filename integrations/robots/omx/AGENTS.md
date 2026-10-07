# omx

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel that binds the ROS-free `pallet.transfer` Skill to the OMX analytic cell planner and the local `PickPlaceRunner`. `ActionRunner` validates the Fleet grant, peer, capability revision, stop fence, and Action journal before it calls this provider. The provider does not create destination-pose evidence or ROS-SIM acceptance by itself.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Grant projection, grasp resolution, and what this wheel does not prove |
| `pyproject.toml` | Integration wheel metadata |
| `COLCON_IGNORE` | Keeps colcon from building this folder |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Project the grant into the Skill contract, resolve grasp geometry from the accepted recipe revision, and plan against the accepted Cell profile plus a fresh joint snapshot.
- Adapt the plan to the existing four-phase runner. Leave cancellation on that runner's active goal.
- Do not import ROS here.

### Testing Requirements

Consumer tests install this wheel with the manipulation Skill wheel. There is no rclpy suite in this folder.

### Common Patterns

ROS-free provider. Device planner types come from `omx_adapter` in the ROS workspace.

## Dependencies

### Internal

- `middleware/apps/device/omx/adapter/` for planner and runtime types.
- Manipulation Skill wheel.

### External

None imported directly.

## Manual Notes
