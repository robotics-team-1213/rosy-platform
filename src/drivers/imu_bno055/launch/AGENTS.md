<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# launch

## Purpose

Optional launch for the BNO055 driver only. Not part of default Rosy OS bringup until ARM64 sensor and localization gates pass.

## Key Files

| File | Description |
|------|-------------|
| `bno055.launch.py` | Starts `imu_bno055`; hardware parameters via launch arguments; reset remains explicit opt-in |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Do not include this launch from `bringup` until the IMU gates pass.
- Preserve the explicit `reset_on_start` opt-in; default false.
- Expose I2C device, address, rate, and `frame_id` as launch arguments rather than hardcoding.

### Testing Requirements

Launch-file presence is covered by `../test/test_package_contract.py`. Driver start is not calibration proof.

### Common Patterns

One node, parameter overlay from `../config/bno055.yaml`.

## Dependencies

### Internal

- `../src/`, `../config/bno055.yaml`

### External

- ROS 2 launch / launch_ros

<!-- MANUAL: -->
