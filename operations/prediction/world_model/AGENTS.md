# world_model

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-17 · **Updated:** 2026-10-17 (D-782)

## Purpose

D-782 pre-execution checker for OMX action chunks. `checker.py` loads only an approved, unaltered M1 artifact and returns a `PredictionResult`: REJECT when a predicted state leaves the configured normalized limits, HOLD when ensemble spread is too large, ABSTAIN when the input is stale, from another rig/calibration, another horizon/period or outside the training range, otherwise NO_OBJECTION (not a permission). `shadow.py` records verdicts and replays them against human-labelled attempts. ROS-free, stdlib only.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Verdict meaning, CLI, stage status |
| `checker.py` | `CheckerConfig`, `WorldModelChecker.check(request, now_ns)` |
| `shadow.py` | `ShadowLog.record`, offline `replay` and CLI |
| `test/` | Verdict, abstention, digest and shadow checks |

## For AI Agents

### Working In This Directory

- The forward pass is `rosy.contracts.learning.prediction.forward`. Do not reimplement it.
- `ShadowLog.record` returns nothing on purpose. Do not add a return path that a caller could use to admit or dispatch.
- Live use (W4) is not wired. Connecting this checker to Fleet admission or an owner recheck needs user approval, a D-430 Safety review and D-773 A4.
- Limits may only narrow the normalized range. Physical joint limits remain the owner's.

### Testing Requirements

`python tools/remote/remote_pytest.py --log-dir <dir> -- operations/prediction/world_model/test`, then `test/known_failures.py`.

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/prediction.py`

### External

- Python 3.12 standard library.
