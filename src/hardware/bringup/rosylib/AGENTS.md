<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-24 | Updated: 2026-09-24 -->

# rosylib

## Purpose

Rosy-owned stand-in for the vendor's closed `pinkylib` (D-192). Installed by the `bringup` package as the top-level module `rosylib`, because Rosy code imports that name (`battery_publisher.py`, `led/led_server.py`).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Exports `Battery`; `from rosylib import LED` raises a clear ImportError (LED is bench-only, D-169) |
| `battery.py` | `Battery.get_voltage()` / `battery_percentage()` over the I2C-1 ADC MCU (0x08, channel 4 `0xF8`), CORE's 2S curve copied |

## For AI Agents

### Working In This Directory

- ROS-free and importable on Windows: `fcntl` is imported only inside `DeviceIO`.
- Never import CORE (`core_features`, `core_common`): the I/O runtime must not pull pydantic. `test/test_rosylib_battery_curve.py` pins `CURVE_2S` equal to CORE's `DEFAULT_CURVE_2S`.
- Bus ownership: hold `flock(LOCK_EX)` on the `/dev/i2c-1` descriptor for the whole pointer-write, settle, read transaction. `control`'s `ir_adc_node` does the same. The C++ `sensor_adc` does not and must never run beside either.
- Only add what the product device surface (D-169) uses.

### Testing Requirements

```bash
python -m pytest src/hardware/bringup/test/test_rosylib_battery.py src/hardware/bringup/test/test_adc_ownership.py test/test_rosylib_battery_curve.py -q
```
