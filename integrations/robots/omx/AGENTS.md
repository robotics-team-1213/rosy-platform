# omx

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel with the OMX LeRobot `rosy_omx` Robot, the CORE arm client and the preflight entry point. It imports no middleware. The `pallet.transfer` Skill binding and the mixed-planner IK reach live in the OMX cell owner `rosy_agent` (`middleware/devices/omx/agent`).

## Key Files

| File | Description |
|------|-------------|
| `README.md` | What this wheel holds and where the Skill binding moved |
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

- `middleware/devices/omx/adapter/` for planner and runtime types.
- Manipulation Skill wheel.

### External

None imported directly.

## Manual Notes

Read [progress.md](progress.md) for current gates and append results to [logs.md](logs.md). Regenerate the module index and repository STATUS with `python tools/harness/rosy_harness.py generate`.
