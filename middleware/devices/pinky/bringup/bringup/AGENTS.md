
# bringup (Python package)

**Parent context:** `../AGENTS.md`

## Purpose

Bringup node and ROS-independent motor/deadman/Dynamixel helpers.

## Key Files

| File | Description |
|------|-------------|
| `bringup.py` | `Rosy` node: cmd_vel → MotorController → Dynamixel, odom/TF/joint_states, `motor/health` JSON every 2 s for CORE heat mode |
| `command_deadman.py` | Stale cmd_vel → confirmed stop, independent of CORE |
| `dynamixel_driver.py` | SDK wrapper, RPM cap, 32-bit encoder wrap, ID validation; `read_health` (temperature, own limit, input voltage, hardware error per motor) |

## Subdirectories

None (ignore `__pycache__/`).

## For AI Agents

### Working In This Directory

- `MotorController` results: `APPLIED` / `LIMITED` / `REJECTED` / `DRIVER_ERROR`. Invalid input or UART error must attempt zero-RPM.
- Wheel radius default 0.028 m, separation 0.0971 m (URDF nominal, D-397; an accepted wheel_odometry record refines it, the launch `wheel_radius`/`wheel_separation` override wins), 4096 pulse/rev.
- `LOW_BATTERY_THRESHOLD = 6.8` in bringup is a driver-side hint; CORE SAF-005 is the operator policy.

### Testing Requirements

Repo `test/test_motor_control.py`, `test_dynamixel_driver_safety.py`, `test_dynamixel_probe.py`; package `test/test_command_deadman.py`.

### Common Patterns

Keep kinematics and deadman rclpy-free.

## Dependencies

### Internal

- Launch in `../launch`

### External

- dynamixel_sdk, rclpy, tf_transformations (bringup.py only)
