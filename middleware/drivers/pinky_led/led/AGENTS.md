
# led (Python package)

**Parent context:** `../AGENTS.md`

## Purpose

LED service implementation.

## For AI Agents

### Working In This Directory

Commands: `set_pixel` (list of indices) and `fill`. RGB from request fields.

### Testing Requirements

Linters in `../test/` only.

### Common Patterns

rclpy service callbacks returning `success` + `message`.

## Dependencies

### Internal

- `interfaces`

### External

- rosylib.LED, rclpy
