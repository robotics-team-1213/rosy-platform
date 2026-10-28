# execution

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-execution` 0.1.1. ROS-free PlanBundle and existing authority projections. Import roots `rosy.execution.api` and `rosy.execution.site`. Depends on `rosy-contracts-skill` and the existing `core_common` wire schemas; workflow helpers import without either Fleet or the wire schema package. This is not `middleware/robot_execution/local/` (`rosy-execution-local`), which checks an installed policy and does not project a plan.

## Key Files

| File | Description |
|------|-------------|
| `pyproject.toml` | Wheel name and existing skill/foundation contract pins |
| `src/` | `rosy.execution.api` and `rosy.execution.site` |
| `src/rosy/execution/site/goal_evidence.py` | D-657 pure bounded goal predicate/evidence types and verification; producer authentication and post-action admission remain Fleet-owned |
| `src/rosy/execution/site/workflow.py` | D-657 pure full progress projection, timestamp/freshness and Mission-to-step helpers; wire schemas load only when project_progress is called; never writes a transition, claim, fence or device command |
| `COLCON_IGNORE` | Not a colcon package |

## Subdirectories

None beyond `src/`.

## For AI Agents

### Working In This Directory

- Project authority that already exists. Do not add a new publisher or a stop fence here.
- The site gateway (`applications/fleet/gateway/`) depends on this wheel. A signature change has to install there too.

### Testing Requirements

Gateway and palletizing consumer tests, Fleet goal/progress/provenance tests, `test/test_judgment_extraction.py` and checkout-independent wheel/sdist/source-image probes. Fleet depends on the existing `rosy-execution==0.1.0` wheel without packaging its files twice. This folder has no `package.xml`. Run committed HEAD remotely via `tools/remote/remote_pytest.py` (D-584).

### Common Patterns

Two namespace packages in one wheel: `api` and `site`.

## Dependencies

### Internal

- `contracts/skill/`.
- `contracts/foundation/` for progress wire serialization.
- Used by `applications/fleet/gateway/` and palletizing.

### External

- Python >= 3.12.

## Manual Notes
