
# imu_bno055

**Parent context:** `../AGENTS.md`

## Purpose

C++ BNO055 IMU driver node `imu_bno055`. Publishes `sensor_msgs/Imu` on `imu_raw` via a realtime publisher.

## Key Files

| File | Description |
|------|-------------|
| `CMakeLists.txt` | Builds the driver **only on aarch64** (wiringPi); always builds the ROS-free decoder test |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | `main_node.cpp` plus device/sample sources (see `src/AGENTS.md`) |
| `config/` | Explicit opt-in BNO055 parameters; reset is false by default (see `config/AGENTS.md`) |
| `launch/` | Optional driver launch; no default Rosy OS runtime activation (see `launch/AGENTS.md`) |
| `test/` | Decoder, package contract, and injected-bus fault tests (see `test/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Default I2C `/dev/i2c-0`, address `0x28`, rate 100 Hz, `frame_id` `imu_link`.
- Missing chip ID or initialization timeout exits nonzero with stage/register/errno logs.
- `test/test_driver_faults.py` uses an injected I2C backend for hardware-free failure tests.
- SYS_TRIGGER reset (`0x3F`/`0x20`) runs only with explicit `reset_on_start:=true`;
  the default preserves the responsive chip across process restarts. Keep chip-ID,
  CONFIGMODE, normal-power, fusion-mode, and bounded status checks in both paths.

### Testing Requirements

ament_lint and the ROS-free package/decoder tests run on the development host.
The driver build, injected-bus executable tests, and live health still need a
Linux ARM64 ROS environment; a real BNO055 is required for physical acceptance.

### Common Patterns

wiringPiI2C register reads; `RealtimePublisher<sensor_msgs::msg::Imu>`.

## Dependencies

### Internal

None beyond workspace overlay.

### External

- rclcpp, sensor_msgs, std_msgs, realtime_tools, wiringPiI2C
