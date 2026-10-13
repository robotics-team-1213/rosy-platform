# tracking

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Route and session tracking installed as `control.control.*`, plus the legacy wander FSM in `wander/` installed as `control.wander`. Tracking proposes motion. It does not publish the operational final `/cmd_vel`.

## Key Files

| File | Description |
|------|-------------|
| `burst_gate.py` | Video burst trigger. Corroboration or an operator, never vision alone (D-137) |
| `detection_evidence.py` | Advisory vision detection snapshot. LiDAR and IR decide; the camera reports |
| `navigation_session.py` | Bounded navigation sessions measured in real elapsed seconds |
| `path_follow.py` | Fail-closed map-route following for the slow desk robot |
| `pursuit.py` | Position-anchored route pursuit geometry |
| `route.py` | Straight-line route that avoids walls. Not a circular path |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `wander/` | Legacy autonomy FSM. Publishes semantic `/cmd_vel_raw`, never `/cmd_vel` (see `wander/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A route or pursuit result is a candidate. Do not publish `/cmd_vel` from this folder.
- Vision evidence stays advisory. Do not let a camera detection become a stop or a burst by itself.
- Wander shutdown behavior stays in `wander/node.py`.

### Testing Requirements

Matching tests live in `middleware/perception/test/test_<module>.py`, including `test_path_follow.py`, `test_route.py`, `test_burst_gate.py`, and `test_detection_evidence.py`. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`.

### Common Patterns

Pure functions with an explicit fail-closed result. No ROS imports in the flat modules.

## Dependencies

### Internal

- Safety clearance comes from `../safety/`. Wander consumes `/safety/*` vocabulary.
- Selected candidates go through CORE.

### External

- Python standard library and numpy.

## Manual Notes
