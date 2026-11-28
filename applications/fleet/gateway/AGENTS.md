# fleet

**Parent context:** `../AGENTS.md`

## Purpose

Wheel `rosy-app-gateway` (version in `pyproject.toml`). Site gateway application composition. Console script `rosy-site-gateway` calls `rosy_gateway.compose:main`. Depends only on PyYAML; Cell compilation lives in `operations/fleet` (`PalletizingCellJobCompiler`). This is not the Fleet server package in `operations/fleet/`.

## Key Files

| File | Description |
|------|-------------|
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/rosy_gateway/` | Import package `rosy_gateway` |

## For AI Agents

### Working In This Directory

- Keep the Fleet HTTP API in `operations/fleet/`. This wheel only composes processes that already have owners.
- Do not point the console script at a robot `/cmd_vel` topic.

### Testing Requirements

Import `rosy_gateway` with PyYAML installed. There is no ament test directory here.

### Common Patterns

Composition roots stay in `compose.py`. Cell compilation is not here; it stays in the Fleet server (D-413).

## Dependencies

### External

- PyYAML >= 6.
