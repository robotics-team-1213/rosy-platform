<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# perception

## Purpose

Camera and lane evidence (D-209, D-228). This folder answers what is visible. It does not publish `cmd_vel`. Lidar, body geometry, and dock tags stay in the parent `sensing/` package.

## Key Files

| File | Description |
|------|-------------|
| `camera.py` | Floor, void, and obstacle classification |
| `lane.py` | Line centre and error |
| `road.py` | Road observation |
| `scene_context.py` | Closed scene profiles |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not import ROS. Observation nodes live above this folder and publish facts.
- Do not import `core` or emit a twist.
- A learned backend, when added, returns `perception/evidence` and stays behind `perception.backend=rule` until the D-205 replay gate passes.

### Testing Requirements

`src/runtime/control/test/test_lane.py`, `test_camera.py`, `test_road_perception.py`, `test_perception_folder.py`

## Dependencies

### Internal

Sibling modules in this folder only.

### External

None.

<!-- MANUAL: -->
