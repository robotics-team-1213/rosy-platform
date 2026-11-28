
# decision

**Parent context:** `../AGENTS.md`

## Purpose

Shared judgment library (D-228). A product supplies an allowed action set and a deterministic rule. The result is an action id or a failure status. It is not a velocity, and it is not a safety override.

## Key Files

| File | Description |
|------|-------------|
| `lane.py` | `lane_recovery`: `FOLLOW` or `STOP`, no velocity |

## For AI Agents

### Working In This Directory

- `selected_action` is set only when status is `DECIDED`.
- `SAFE_STOP`, `EMERGENCY`, and `MANUAL` drop options marked `motion` before the rule runs.
- An id outside the constrained set is `INVALID`. Do not rewrite it into a legal id.
- `fallback_action` is a separate field. `ERROR` and `TIMEOUT` stay those statuses.
- Do not import ROS, `control`, or a network client. Remote models are not this folder.

### Testing Requirements

`middleware/core/services/test/test_decision.py`

## Dependencies

### Internal

`core_features.decision` only.
