# manipulation

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-skill-manipulation` 0.1.0. ROS-free manipulation Skill contracts and evidence gates. Depends on `rosy-skill-api`. Import root `rosy.skills.manipulation`. The OMX integration binds `pallet.transfer` through this contract.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and the API pin |
| `src/` | Namespace package `rosy.skills.manipulation` |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

None beyond `src/`.

## For AI Agents

### Working In This Directory

- Evidence gates belong in this wheel. The cell planner and `PickPlaceRunner` stay in the OMX adapter and the integration provider.
- Do not treat a passing gate as ROS-SIM acceptance. The integration README says that acceptance is separate.

### Testing Requirements

Consumer tests install this wheel before the OMX integration tests. There is no `package.xml`.

### Common Patterns

Depends on `rosy-skill-api`, which depends on `rosy-contracts-skill`.

## Dependencies

### Internal

- `middleware/skills/api/`.
- Used by `integrations/robots/omx/`.

### External

- Python >= 3.12.

## Manual Notes
