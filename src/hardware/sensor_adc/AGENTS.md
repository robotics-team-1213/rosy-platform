<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# sensor_adc

## Purpose

C++ I2C ADC node (`sensor_adc`). Channels 0–2 IR, 3 ultrasonic, 4 battery. Publishes `sensor_msgs/Range`, battery state, and respects `power/mode` duty cycling (PWR-001) without slowing down if CORE is absent. Failed I2C cycles publish nothing (fail-closed) and are reported on the latched `sensors/adc/status` health topic (1 Hz JSON, same contract as `imu_bno055`).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_cmake; rclcpp, sensor_msgs, realtime_tools |
| `CMakeLists.txt` | Builds `src/main_node.cpp` **only on aarch64** (wiringPi); x86 logs skip |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | `main_node.cpp` (see `src/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61 Proposed): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Default I2C `/dev/i2c-1`, address `0x08`.
- Parameters `rate_active` / `rate_idle` / `rate_standby` (20 / 5 / 2 Hz). Until a valid `power/mode` arrives, keep the startup rate.
- wiringPi I2C is a Pi-only dependency.

### Testing Requirements

ament_lint. Hardware-in-the-loop on Pi; power policy tests are in `core`.

### Common Patterns

`RealtimePublisher` for range messages.

## Dependencies

### Internal

- CORE publishes `power/mode`; this node subscribes

### External

- rclcpp, wiringPiI2C, realtime_tools

<!-- MANUAL: -->
