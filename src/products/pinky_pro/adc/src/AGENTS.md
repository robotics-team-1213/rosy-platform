<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# src

## Purpose

ADC node implementation.

## Key Files

| File | Description |
|------|-------------|
| `main_node.cpp` | `RosySensorADC`: IR/US/battery channels, `power/mode` rate switching |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

Channel map is a comment contract (`CH_IR_FIRST=0`, `CH_ULTRASONIC=3`, `CH_BATTERY=4`). CORE outage must not leave the node at standby rate.

### Testing Requirements

Hardware + `docs/deployment/power-bench-verification.md`.

### Common Patterns

Realtime publishers; parameter rates per PowerMode.

## Dependencies

### Internal

- CORE `power/mode` topic

### External

- rclcpp, wiringPiI2C, realtime_tools, sensor_msgs

<!-- MANUAL: -->
