# drivers

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Pinky board drivers that publish sensor or actuator topics. They do not own the robot mode or the final command.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `imu_bno055/` | BNO055 IMU (see `imu_bno055/AGENTS.md`) |
| `pinky_adc/` | ADC, battery, IR, ultrasonic (see `pinky_adc/AGENTS.md`) |
| `pinky_lamp/` | WS2812 lamp (see `pinky_lamp/AGENTS.md`) |
| `pinky_led/` | Status LED (see `pinky_led/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A driver that reads 4095 or times out is a bringup problem. Use the `rosy-hw-bringup` skill on a robot rather than changing a threshold to hide it.
- Do not subscribe here and publish `/cmd_vel`.

### Testing Requirements

Each package's `test/` AGENTS.md names the suite. IMU and LED have host tests. ADC and lamp are closer to the hardware.

### Common Patterns

ament_cmake or ament_python as the package already uses. Node names stay in the package, not in CORE.

## Dependencies

### Internal

- Started by `middleware/apps/device/pinky/bringup/`.
- CORE reads their topics through `core.bridge`.

### External

- I2C, ws2811, and the Pinky ADC path named in each package.

## Manual Notes
