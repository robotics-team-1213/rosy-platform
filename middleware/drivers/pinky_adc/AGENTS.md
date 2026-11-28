
# sensor_adc

**Parent context:** `../AGENTS.md`

## Purpose

C++ I2C ADC node (`sensor_adc`). Channels 0–2 IR, 3 ultrasonic, 4 battery. Publishes `sensor_msgs/Range`, battery state, and respects `power/mode` duty cycling (PWR-001) without slowing down if CORE is absent. Failed I2C cycles publish nothing (fail-closed) and are reported on the latched `sensors/adc/status` health topic (1 Hz JSON, same contract as `imu_bno055`).

## Key Files

| File | Description |
|------|-------------|
| `CMakeLists.txt` | Builds `src/main_node.cpp` **only on aarch64** (wiringPi); x86 logs skip |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | `main_node.cpp` (see `src/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
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
