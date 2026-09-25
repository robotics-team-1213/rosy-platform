<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# hardware

## Purpose

Device nodes moved out of `hardware/`. Package names are still the chip or board (`imu_bno055`, `sensor_adc`, `lamp_control`, `led`) plus `bringup` for the Pinky drive. A second IMU or arm must not become another top-level package name. C++ drivers (`lamp_control`, `imu_bno055`, `sensor_adc`) build only on aarch64.

## Key Files

None at this level. Each package directory has its own `AGENTS.md`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bringup/` | Motors (Dynamixel), odometry, LiDAR, battery publisher, `cmd_vel` deadman, Pinky Pro adapter (see `bringup/AGENTS.md`) |
| `led/` | Python LED service (`set_led`, `set_brightness`) (see `led/AGENTS.md`) |
| `lamp_control/` | C++ WS2811 lamp + SetLamp service — aarch64 only (see `lamp_control/AGENTS.md`) |
| `imu_bno055/` | C++ BNO055 IMU driver — aarch64/wiringPi only (see `imu_bno055/AGENTS.md`) |
| `sensor_adc/` | C++ I2C ADC: IR, ultrasonic, battery — aarch64 only (see `sensor_adc/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Almost every package here depends on `src/contracts/interfaces`.
- C++ drivers are ament_cmake and aarch64-only; keep host-safe test paths in the Python packages.

### Testing Requirements

```bash
# from src/
python3 -m pytest hardware/bringup/test/ hardware/led/test/ hardware/imu_bno055/test/ -v
```

## Dependencies

### Internal

- `bringup` launch includes `src/sim/description`.
- `core` consumes bringup topics at runtime.

### External

- ROS 2 Jazzy, rclcpp/rclpy, Dynamixel SDK, wiringPi I2C, ws2811, sllidar_ros2

<!-- MANUAL: -->
