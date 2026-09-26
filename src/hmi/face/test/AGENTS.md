<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# test

## Purpose

Info-screen unit tests plus ament linters.

## Key Files

| File | Description |
|------|-------------|
| `test_info_screen.py` | PIL card rendering without LCD |
| `test_copyright.py` | ament_copyright |
| `test_flake8.py` | ament_flake8 |
| `test_pep257.py` | ament_pep257 |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

Keep tests ROS-free. Do not open `/dev` LCD in pytest.

### Testing Requirements

```bash
python3 -m pytest src/hmi/face/test/test_info_screen.py -v
```

### Common Patterns

Standard ament Python tests.

## Dependencies

### Internal

- `emotion.info_screen`

### External

- pytest, PIL

<!-- MANUAL: -->
