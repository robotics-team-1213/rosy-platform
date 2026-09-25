<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# test

## Purpose

Package pytest: deadman unit test plus ament copyright/flake8/pep257.

## Key Files

| File | Description |
|------|-------------|
| `test_command_deadman.py` | CommandDeadman arm/timeout/stop |
| `test_pinky_pro_adapter.py` | Pinky Pro ROS parameter boundary; no device I/O |
| `test_copyright.py` | ament_copyright |
| `test_flake8.py` | ament_flake8 |
| `test_pep257.py` | ament_pep257 |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

MotorController/Dynamixel tests live in **repo-root** `test/`, not here. Add ROS-free tests next to the code they cover.

### Testing Requirements

```bash
python3 -m pytest src/hardware/bringup/test/test_command_deadman.py -v
```

### Common Patterns

Standard ament Python linter tests.

## Dependencies

### Internal

- `bringup.command_deadman`

### External

- pytest, ament_copyright/flake8/pep257

<!-- MANUAL: -->
