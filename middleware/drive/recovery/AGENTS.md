# recovery

**Parent context:** `../AGENTS.md`

## Purpose

Bounded recovery proposals for Drive: escape, retreat along a measured trail, and hazard response. A proposal is not motor authority and this folder does not publish `/cmd_vel`. Activation stays with the caller that already owns the mission.

## Key Files

| File | Description |
|------|-------------|
| `recover.py` | Stuck, escape, backup, and hazard response. Pure, no ROS |
| `recovery_budget.py` | Bounds contact retries by displacement, not repeated forward attempts |
| `route_recovery.py` | Repeated paths are not successful recovery |
| `straight_escape.py` | Fixed-budget, fixed-heading escape. No ROS and no motor authority |

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
