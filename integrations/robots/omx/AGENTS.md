# omx

**Parent context:** `../AGENTS.md`

## Purpose

Wheel with the OMX LeRobot `rosy_omx` Robot, the CORE arm client and the preflight entry point. It imports no middleware. The `pallet.transfer` Skill binding and the mixed-planner IK reach live in the OMX cell owner `rosy_agent` (`middleware/devices/omx/agent`).

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

Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
