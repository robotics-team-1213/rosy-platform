
# interfaces

**Parent context:** `../AGENTS.md`

## Purpose

Custom ROS 2 services for LED, lamp, brightness, and LCD emotion. rosidl package; rebuild after any `.srv` change.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `srv/` | `Emotion.srv`, `SetLed.srv`, `SetBrightness.srv`, `SetLamp.srv` (see `srv/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- REST/Fleet contracts do **not** live here — those are pydantic in `core.protocol.schemas`.
- After editing `.srv`, `colcon build --packages-select interfaces` and rebuild dependents.

### Testing Requirements

ament_lint. Compile is the real check.

### Common Patterns

Simple request/response strings and RGB fields; keep them stable for hardware nodes.

## Dependencies

### Internal

- Used by `led`, `emotion`, `lamp_control`, `core` (SetLed)

### External

- std_msgs, action_msgs, builtin_interfaces, rosidl
