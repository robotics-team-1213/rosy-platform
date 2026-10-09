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

## Subdirectories

None beyond the wheel source.

## For AI Agents

### Working In This Directory

- Do not add timestamps, inferred task outcomes, or owner admission inside `seal()` or the validators.
- OMX rad goals and Pinky m/s·rad/s stay separate profiles. This package does not convert between them.
- Tests that need a sample wire live with the contract tests, not in a robot session.

### Testing Requirements

`python -m pytest test/test_learning_artifact_contracts.py -q` from the repo, with this wheel importable.

### Common Patterns

File names inside a manifest are normalized POSIX relative paths and must stay inside the given root.

## Dependencies

### Internal

- OMX conversion lives in `learning/curation/omx/`. Pinky conversion lives in `learning/curation/pinky/`.

### External

- Python 3.12. No ROS, torch, or LeRobot.

## Manual Notes
