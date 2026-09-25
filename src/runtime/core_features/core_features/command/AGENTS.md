<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# command

## Purpose

CORE-002 / §8.1 command arbitration. ROS-free. CommandManager is the only logical `cmd_vel` source; bridge publishes whatever `select_output()` returns.

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker |
| `arbitration.py` | `Priority` enum, `SourceRegistry`, `Mode` / `ModeMachine` |
| `manager.py` | Mux: EMERGENCY zero, MANUAL+watchdog, NAVIGATION clipped, DOCKING |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Priorities: EMERGENCY 1 … DOCKING 4, NAVIGATION 5, FLEET 6, IDLE 7. Do not let Fleet preempt docking.
- Mode table currently blocks NAVIGATION → DOCKING; docking action holds DOCKING mode for the whole sequence.
- Teleop watchdog timeout default 500 ms (SAF-002).

### Testing Requirements

`src/runtime/core/test/test_core_logic.py`

### Common Patterns

Local `Twist` dataclass — not `geometry_msgs`.

## Dependencies

### Internal

- `safety.manager.SafetyManager`, `TeleopWatchdog`

### External

None.

<!-- MANUAL: -->
