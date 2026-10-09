# execution

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Local execution evidence on the middleware side. This is the `rosy-execution-local` wheel, not the `rosy-execution` wheel in `operations/execution/`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `local/` | Policy installation checks and the optional OMX policy session (see `local/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Loading a policy here grants no stage, lease, or recovery authority.
- Do not deserialize weights in the installation loader.

### Testing Requirements

`python -m pytest middleware/execution/local/test -q`

### Common Patterns

`COLCON_IGNORE` wheel. Tests inject bindings. They do not read them out of the policy under test.

## Dependencies

### Internal

- `contracts/skill/` and `contracts/learning/`.
- Optional OMX adapter types, imported lazily.

### External

- Python >= 3.12. Pydantic comes in with the adapter path, not as a reason to import ROS.

## Manual Notes
