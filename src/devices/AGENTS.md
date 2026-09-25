<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-20 | Updated: 2026-09-20 -->

# devices

## Purpose

장치 패키지는 계열 안에 둔다. Pinky 보드 전용은 `pinky_pro`, 여러 차체가 쓰는 칩은 `common`, 팔은 `omx`. 패키지 이름은 칩·보드 이름 그대로다. C++ 드라이버는 aarch64에서만 빌드한다.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `pinky_pro/` | Pinky 보드: `bringup`, `sensor_adc`, `lamp_control`, `led` (see `pinky_pro/AGENTS.md`) |
| `common/` | 공유 칩: `imu_bno055` (see `common/AGENTS.md`) |
| `omx/` | 팔: `omx_adapter` (see `omx/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Almost every package here depends on `src/contracts/interfaces`.
- C++ drivers are ament_cmake and aarch64-only; keep host-safe test paths in the Python packages.

### Testing Requirements

```bash
# from src/
python3 -m pytest devices/pinky_pro/bringup/test/ devices/pinky_pro/led/test/ devices/common/imu_bno055/test/ -v
```

## Dependencies

### Internal

- `bringup` launch includes `src/sim/description`.
- `core` consumes bringup topics at runtime.

### External

- ROS 2 Jazzy, rclcpp/rclpy, Dynamixel SDK, wiringPi I2C, ws2811, sllidar_ros2

<!-- MANUAL: -->
