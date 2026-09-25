<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-25 -->

# decision

## Purpose

Shared judgment library (D-228). A product supplies an allowed action set and a deterministic rule. The result is an action id or a failure status. It is not a velocity, and it is not a safety override.

## Key Files

| File | Description |
|------|-------------|
| `contract.py` | `DecisionRequest`, `DecisionResult`, `DecisionStatus` |
| `router.py` | Hard constraints, then one local rule |
| `lane.py` | `lane_recovery`: `FOLLOW` or `STOP`, no velocity |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- `selected_action` is set only when status is `DECIDED`.
- `SAFE_STOP`, `EMERGENCY`, and `MANUAL` drop options marked `motion` before the rule runs.
- An id outside the constrained set is `INVALID`. Do not rewrite it into a legal id.
- `fallback_action` is a separate field. `ERROR` and `TIMEOUT` stay those statuses.
- Do not import ROS, `control`, or a network client. Remote models are not this folder.

### Testing Requirements

`src/runtime/core_features/test/test_decision.py`

## Dependencies

### Internal

`core_features.decision` only.

### External

None.

<!-- MANUAL: -->
