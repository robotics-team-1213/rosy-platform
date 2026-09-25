<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# test

## Purpose

Decoder and package-contract checks stay ROS-free on the host. Injected-bus fault tests need a Linux ARM64 ROS executable and are separate from live BNO055 acceptance. Node startup is not calibration proof.

## Key Files

| File | Description |
|------|-------------|
| `test_package_contract.py` | Package layout / default reset policy / launch presence |
| `test_driver_faults.py` | Injected I2C backend; hardware-free failure stages |
| `test_sample.cpp` | ROS-free IMU sample decoder (always built) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Keep decoder and contract tests importable without rclpy/wiringPi.
- The injected-bus harness must not be treated as live-chip acceptance.
- No test here may treat node startup as a calibrated IMU.

### Testing Requirements

```bash
python3 -m pytest src/hardware/imu_bno055/test/test_package_contract.py src/hardware/imu_bno055/test/test_driver_faults.py -v
```

`test_driver_faults.py` may skip off ARM64/Linux. C++ decoder test is built by the package CMake even when the driver `return()`s on non-aarch64.

### Common Patterns

Inject a fake bus; assert stage/register/errno on failure. Do not talk to a real `/dev/i2c-*` in pytest.

## Dependencies

### Internal

- `../src/` decoder and device code

### External

- pytest; gtest/CMake for `test_sample.cpp`

<!-- MANUAL: -->
