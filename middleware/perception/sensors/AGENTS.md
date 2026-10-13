# sensors

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Holder for sensor evidence that the `control` distribution installs as `control.sensing`. The implementation is `sensing/`. This folder does not publish `/cmd_vel`. Camera and lane evidence live in `../vision/perception`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `sensing/` | Scan geometry, body footprint, dock tags, and localization evidence (see `sensing/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Add sensor logic in `sensing/`, not in a new sibling package.
- Keep the installed import `control.sensing`. Do not add a second package name.
- Headings go through `sensing/lidar.py` `robot_yaw()` / `wrap_pi()`. Scan angle 0 is the rear.

### Testing Requirements

Tests for this tree are `middleware/perception/test/test_lidar*.py`, `test_body.py`, `test_filt.py`, and the `test_loc_*.py` / `test_dock_*.py` modules. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`.

### Common Patterns

ROS-free modules. One subject per file.

## Dependencies

### Internal

- Installed by `middleware/perception/setup.py` as `control.sensing`.
- Drive consumers are `middleware/drive/`.

### External

- `math`, `numpy`. ROS types stay in the node layer under `middleware/perception/control`.

## Manual Notes
