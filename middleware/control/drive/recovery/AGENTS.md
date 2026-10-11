# recovery

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Bounded recovery proposals for Drive: escape, retreat along a measured trail, and hazard response. A proposal is not motor authority and this folder does not publish `/cmd_vel`. Activation stays with the caller that already owns the mission.

## Key Files

| File | Description |
|------|-------------|
| `escape_budget.py` | Bounds separate recovery regions using continuous measured odometry |
| `escape_space.py` | Predicts useful straight repositioning from observed geometry |
| `execution_escape.py` | Executes one live, measured escape proposal inside the existing mission |
| `recover.py` | Stuck, escape, backup, and hazard response. Pure, no ROS |
| `recovery_budget.py` | Bounds contact retries by displacement, not repeated forward attempts |
| `rotation_relocation.py` | One measured straight relocation per navigation region |
| `rotation_trial.py` | Bounded left and right trials with independent repeated response checks |
| `route_recovery.py` | Repeated paths are not successful recovery |
| `safe_trail.py` | Measured odometry breadcrumbs back to a stable turn-safe refuge |
| `straight_escape.py` | Fixed-budget, fixed-heading escape. No ROS and no motor authority |
| `trail_retreat.py` | Bounded reverse tracking of an already verified odometry trail |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not start recovery automatically and do not add a command publisher.
- Retreat only along odometry that was actually recorded. Do not invent a refuge.
- A repeated path is feedback, not proof that recovery worked.

### Testing Requirements

Matching tests live in `middleware/perception/test/test_recover.py`, `test_escape_*.py`, `test_recovery_budget.py`, `test_rotation_relocation.py`, `test_rotation_trial.py`, `test_route_recovery.py`, `test_safe_trail.py`, `test_straight_escape.py`, and `test_trail_retreat.py`. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`.

### Common Patterns

Pure modules. Budgets use measured displacement. No ROS imports.

## Dependencies

### Internal

- Geometry and clearance come from `../safety/` and `middleware/perception/sensors/sensing`.
- The mission owner decides whether a proposal runs.

### External

- Python standard library and numpy.

## Manual Notes
