
# verify

**Parent context:** `../AGENTS.md`

## Purpose

Checks after install. They read identity, health, motors, and power. They do not install the robot.

## Key Files

| File | Description |
|------|-------------|
| `verify-motors.sh` | UART probe. Refuses to run while the motor runtime cannot be shown down |
| `device_readback.py` | Secret-free JSON evidence |
| `verify-from-windows.ps1` | Read-only peer check from Windows |

## For AI Agents

### Working In This Directory

- Installed path is `/opt/rosy/deploy/robot/verify/`.
- `device-readback.sh` must stay next to `device_readback.py`.

### Testing Requirements

```bash
python -m pytest test/test_device_readback.py test/test_rosy_motor_udev.py test/test_windows_connection_evidence.py -q
```

### Common Patterns

Readback JSON does not include tokens or the environment file body.

## Dependencies

### Internal

- `install-pi.sh` points operators at `verify-pi.sh`

### External

- The installed robot tree under `/opt/rosy`
