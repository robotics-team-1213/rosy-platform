# skill

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-contracts-skill` 0.1.1. ROS-free Skill invocation, receipt identity and PlanBundle/PlanStep shape shared by the other ROSY wheels. `COLCON_IGNORE` keeps colcon off this folder.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Package name `rosy-contracts-skill` |
| `src/` | Import root `rosy.contracts.skill`; `plan.py` holds PlanBundle/PlanStep (`rosy.execution.api` re-exports them) |

## Subdirectories

None beyond the wheel source.

## For AI Agents

### Working In This Directory

- Skill identity belongs here. Execution authority stays in the execution wheels and in CORE, not in this contract package.
- Do not add ROS imports.

### Testing Requirements

Importers (`contracts/motion`, `operations/site_execution`, `middleware/skills/api`) cover this wheel. Run those suites after a shape change.

### Common Patterns

Namespace package under `src/`. No runtime dependencies in `pyproject.toml`.

## Dependencies

### Internal

- Used by motion, execution, and the skill API wheel.

### External

- Python >= 3.12.

## Manual Notes
