
# test

**Parent context:** `../AGENTS.md`

## Purpose

ament linters only (no hardware LED tests).

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
