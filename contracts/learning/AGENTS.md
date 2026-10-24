# learning

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Wheel `rosy-contracts-learning` (D-449). ROS-free, torch-free, LeRobot-free checks for Episode, DatasetManifest, PolicyArtifact, and PromotionRecord. `seal()` hashes canonical JSON. Validators return a copy and do not fill nulls. This package does not run inference, talk to an API, or admit an owner.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Wire rules, camera fingerprint notes, and what 0.1.x does not prove |
| `pyproject.toml` | Package `rosy-contracts-learning` |
| `src/` | Import root `rosy.contracts.learning` |
| `src/rosy/contracts/learning/action_space.py` | D-854 OMX action space declaration and versioned `lerobot_norm_v1` <-> `dynamixel_rad_v1` converters; clips are counted, never silent. Test `test/test_learning_action_space.py` |
| `src/rosy/contracts/learning/prediction.py` | D-782 PredictionRequest/Result, the M1 artifact schema and its single `forward` rule; a result may only support REJECT or HOLD |

## Subdirectories

None beyond the wheel source.

## For AI Agents

### Working In This Directory

- Do not add timestamps, inferred task outcomes, or owner admission inside `seal()` or the validators.
- OMX rad goals and Pinky m/s·rad/s stay separate profiles. This package does not convert between them.
- OMX unit conversion (D-854) lives only in `action_space.py`; curation and the policy runner import it. A changed formula is a new converter version, never an edit of an existing one.
- Tests that need a sample wire live with the contract tests, not in a robot session.

### Testing Requirements

`python -m pytest test/test_learning_artifact_contracts.py test/test_learning_action_space.py -q` from the repo (through `tools/remote/remote_pytest.py`), with this wheel importable.

### Common Patterns

File names inside a manifest are normalized POSIX relative paths and must stay inside the given root.

## Dependencies

### Internal

- OMX dataset export lives in `learning/curation/omx/`; its unit conversion calls `action_space.py`. Pinky conversion lives in `learning/curation/pinky/`.

### External

- Python 3.12. No ROS, torch, or LeRobot.

## Manual Notes
