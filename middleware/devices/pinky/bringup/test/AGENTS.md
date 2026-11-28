
# test

**Parent context:** `../AGENTS.md`

## Purpose

Package pytest: deadman unit test plus ament copyright/flake8/pep257.

## Key Files

| File | Description |
|------|-------------|
| `test_pinky_pro_adapter.py` | Pinky Pro ROS parameter boundary; no device I/O |

## For AI Agents

### Working In This Directory

MotorController/Dynamixel tests live in **repo-root** `test/`, not here. Add ROS-free tests next to the code they cover.

### Testing Requirements

```bash
python3 -m pytest middleware/devices/pinky/bringup/test/test_command_deadman.py -v
```

### Common Patterns

Standard ament Python linter tests.

## Dependencies

### Internal

- `bringup.command_deadman`

### External

- pytest, ament_copyright/flake8/pep257
