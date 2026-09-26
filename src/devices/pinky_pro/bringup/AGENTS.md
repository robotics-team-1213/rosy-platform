<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# bringup

## Purpose

Physical robot bringup: Dynamixel differential drive, odometry/TF, optional LiDAR and battery publisher, and a driver-side cmd_vel deadman independent of `core` (D-22).

## Key Files

| File | Description |
|------|-------------|
| `package.xml` | ament_python; exec depends include sllidar_ros2, robot_state_publisher |
| `setup.py` / `setup.cfg` | Package install |
| `config/pinky_pro_adapter.yaml` | ROS parameter source for the Pinky Pro board adapter |
| `bringup/pinky_pro_adapter.py` | ROS-free validation boundary before Dynamixel I/O |
| `progress.md` | Current gate snapshot (SOURCE…FIELD). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `bringup/` | Nodes and ROS-free motor contracts (see `bringup/AGENTS.md`) |
| `rosylib/` | Rosy-owned `pinkylib` stand-in: I2C-1 ADC `Battery` (see `rosylib/AGENTS.md`, D-192) |
| `launch/` | `bringup_robot.launch.py` with namespace/frame_prefix (see `launch/AGENTS.md`) |
| `config/` | Params + localhost CycloneDDS (see `config/AGENTS.md`) |
| `scripts/` | Per-robot env isolation `rosy_env.sh` (see `scripts/AGENTS.md`) |
| `test/` | Deadman + ament linters (see `test/AGENTS.md`) |
| `resource/` | ament marker |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- `motor_control.py` and `command_deadman.py` must remain importable without rclpy (repo `test/` uses them).
- Default serial `/dev/ttyAMA4`, baud 1_000_000, IDs `[1, 2]` (left, right). Do not coerce IDs.
- Driver enforces RPM limits and 32-bit encoder wrap even if CORE is down.
- Stale `cmd_vel` → confirmed zero-RPM stop (`CommandDeadman`).
- `PinkyProAdapter` validates the complete parameter mapping before the SDK is
  constructed; it must not open a device or publish a command.

### Testing Requirements

```bash
python3 -m pytest test/test_motor_control.py test/test_bringup_motor_contracts.py \
  test/test_dynamixel_driver_safety.py src/hardware/bringup/test/test_command_deadman.py -v
```

### Common Patterns

Launch arguments: `namespace`, `enable_battery`, `enable_lidar`, `use_sim_time`, `drive_enabled`.

`drive_enabled:=false` is the D-192 no-motion mode: torque stays off, `cmd_vel` is not subscribed, `motor/ready` stays false; odometry, joint states and TF still publish. `rosy-io.service` defaults to it (`ROSY_IO_DRIVE_ENABLED=false`).

## Dependencies

### Internal

- `description` (robot_state_publisher from launch)

### External

- dynamixel_sdk, sllidar_ros2, tf_transformations, rclpy

<!-- MANUAL: -->
