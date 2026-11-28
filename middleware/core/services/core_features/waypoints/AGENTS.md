
# waypoints

**Parent context:** `../AGENTS.md`

## Purpose

WPT-001–005 local JSON store (D-9). CRUD, unique names, reserved `__home__`.

## For AI Agents

### Working In This Directory

- Default file `~/.rosy/waypoints.json`. On the robot HOME is `/var/lib/rosy`.
- Name collisions raise `WaypointError` — API maps it via `errors.py`.

### Testing Requirements

`test_core_logic.py`

### Common Patterns

pydantic `Waypoint` with x/y/yaw/`map_id`.

## Dependencies

### Internal

- API waypoints router

### External

- pydantic
