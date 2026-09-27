<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# led (Python package)

## Purpose

LED service implementation.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `led_server.py` | `LedServiceServer`: `set_led`, `set_brightness` |

## Subdirectories

None.

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

<!-- MANUAL: -->
