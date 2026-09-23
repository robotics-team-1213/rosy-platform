<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# tools

## Purpose

Host-side utilities for the absorbed Control package: a static ROS-name audit, calibration YAML migration, and Gazebo desk-maze rigs. Not launch entry points and not the pytest suite.

## Key Files

| File | Description |
|------|-------------|
| `audit_ros_names.py` | AST inventory of publishers/subscriptions/services/frames; not a live graph validator |
| `migrate_calibration.py` | Merge legacy cliff/drive YAML into a new file; never overwrite sources; conflicts need an operator |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `gz/` | Gazebo calibration, localization, obstacle, and track-run rigs (see `gz/AGENTS.md`) |
| `device/` | On-device measurement: `hotpath_measure.py` (D-185 R8 hot-path bench and node CPU watch, JSON report; device evidence only on the Pi) |

## For AI Agents

### Working In This Directory

- `audit_ros_names.py` does not see launch remaps or YAML overrides. Live ROS still required for those.
- `migrate_calibration.py` refuses an existing destination and bound identity records. It does not invent device identity.
- Do not import these scripts from runtime nodes.

### Testing Requirements

`audit_ros_names` / migrate are operator tools. Gazebo rigs are not CI. Package tests stay in `../test/`.

### Common Patterns

CLI + stdout/CSV. Tools that touch calibration never modify the source file.

## Dependencies

### Internal

- `control.calibration_storage` / `calibration_record` for migrate
- Package Python under `../control/`

### External

- PyYAML (migrate). Gazebo tools additionally need gz / numpy (see `gz/AGENTS.md`)

<!-- MANUAL: -->
