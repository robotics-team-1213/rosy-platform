
# src

**Parent context:** `../AGENTS.md`

## Purpose

BNO055 node implementation.

## For AI Agents

### Working In This Directory

Parameters: `interface`, `frame_id`, `rate`, `reset_on_start` (default false). Initialization errors exit nonzero;
the external supervisor owns bounded restarts. Never reset on invalid chip ID.
Enter CONFIGMODE. Only when reset is explicitly enabled, reset then wait 700 ms
without I2C before polling boot. Both paths require chip ID and bounded boot/fusion checks.
Failed or short reads must not publish an IMU sample. Keep angular velocity
in degrees/s to preserve the deployed consumer conversion contract.

### Testing Requirements

`test_imu_sample` is ROS-free. `test/test_driver_faults.py` injects bus failures
against `BNO055_TEST_EXECUTABLE` on an isolated ROS domain (231), without hardware.
Actual sensor health still requires live samples, not just node presence.

### Common Patterns

rclcpp node in a single translation unit.

## Dependencies

### External

- rclcpp, wiringPiI2C, realtime_tools, sensor_msgs, std_msgs
