# execution

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-execution` 0.1.0. ROS-free PlanBundle and existing authority projections. Import roots `rosy.execution.api` and `rosy.execution.site`. Depends on `rosy-contracts-skill`. This is not `middleware/execution/local/` (`rosy-execution-local`), which checks an installed policy and does not project a plan.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and the skill-contract pin |
| `src/` | `rosy.execution.api` and `rosy.execution.site` |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

None beyond `src/`.

## For AI Agents

### Working In This Directory

- Project authority that already exists. Do not add a new publisher or a stop fence here.
- The site gateway (`operations/apps/fleet/`) depends on this wheel. A signature change has to install there too.

### Testing Requirements

Gateway and palletizing consumer tests. This folder has no `package.xml`.

### Common Patterns

Two namespace packages in one wheel: `api` and `site`.

## Dependencies

### Internal

- `contracts/skill/`.
- Used by `operations/apps/fleet/` and palletizing.

### External

- Python >= 3.12.

## Manual Notes
