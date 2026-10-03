<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# test

## Purpose

ament linters only (no hardware LED tests).

## Key Files

| File | Description |
|------|-------------|
| `test_copyright.py` | ament_copyright |
| `test_flake8.py` | ament_flake8 |
| `test_pep257.py` | ament_pep257 |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

Do not add tests that import `rosylib` unless you mock it — CI may not have the hardware lib.

### Testing Requirements

```bash
python3 -m pytest src/hardware/led/test/ -v
```

### Common Patterns

Stock ament Python linter tests.

## Dependencies

### External

- ament_copyright, ament_flake8, ament_pep257

<!-- MANUAL: -->
