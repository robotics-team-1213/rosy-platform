
# test

**Parent context:** `../AGENTS.md`

## Purpose

Info-screen unit tests plus ament linters.

## Key Files

| File | Description |
|------|-------------|
| `test_info_screen.py` | PIL card rendering without LCD |

## For AI Agents

### Working In This Directory

Keep tests ROS-free. Do not open `/dev` LCD in pytest.

### Testing Requirements

```bash
python3 -m pytest middleware/robot_ui/face/test/test_info_screen.py -v
```

### Common Patterns

Standard ament Python tests.

## Dependencies

### Internal

- `emotion.info_screen`

### External

- pytest, PIL
