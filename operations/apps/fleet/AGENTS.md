# fleet

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-app-gateway` 0.1.0. Site gateway application composition. Console script `rosy-site-gateway` calls `rosy_gateway.compose:main`. Depends on `rosy-palletizing` and `rosy-execution`. This is not the Fleet server package in `operations/fleet/`.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Script entry and wheel pins |
| `src/rosy_gateway/compose.py` | Process composition and `main` |
| `src/rosy_gateway/cell_compiler.py` | Cell document compilation for the gateway |
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

Import `rosy_gateway` with the two declared wheels installed. There is no ament test directory here.

### Common Patterns

Composition roots stay in `compose.py`. Cell compilation stays in `cell_compiler.py`.

## Dependencies

### Internal

- `operations/processes/palletizing/` (`rosy-palletizing`).
- `operations/execution/` (`rosy-execution`).

### External

- PyYAML >= 6.

## Manual Notes
