<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# interfaces

## Purpose

Custom ROS 2 services for LED, lamp, brightness, and LCD emotion. rosidl package; rebuild after any `.srv` change.

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | `rosidl_default_generators`; member of `rosidl_interface_packages` |
| `CMakeLists.txt` | Generates interfaces from `srv/` |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `srv/` | `Emotion.srv`, `SetLed.srv`, `SetBrightness.srv`, `SetLamp.srv` (see `srv/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
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

<!-- MANUAL: -->
