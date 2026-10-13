# omx

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Offline ACT research on existing LeRobot 0.4.4 OMX demonstrations. `act_job.py` checks the export, splits train and eval by episode, trains, reloads weights, evaluates offline, and writes a DatasetManifest and PolicyArtifact. It does not create a promotion, a READY flag, or a dispatch.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | CLI, the CPU environment, and the current ACT hyperparameters |
| `act_job.py` | Train, save, reload, and offline eval |
| `act_inference.py` | Offline inference helper |
| `act_inference_replay.py` | Replay path for a saved run |
| `act_owner_capture.py` | Capture helper for owner-side observations |
| `test/` | Host tests for the job |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Checks that do not need a robot |

## For AI Agents

### Working In This Directory

- Use the Python 3.12 CPU environment from `deploy/robot/omx/requirements-lerobot-export.txt`. Put the adapter and foundation on `PYTHONPATH`.
- Chunks do not cross episode boundaries. Normalization is train-only.
- Windows outputs go on X:. A failed run is not resumed.

### Testing Requirements

`python -m pytest learning/training/omx/test -q` for the host checks. The full ACT job needs the pinned torch environment and is not part of robot CI.

### Common Patterns

Current research settings are in the README (ResNet18 ACT, chunk 4, VAE off, CPU). Change them in the job and the README together.

## Dependencies

### Internal

- `learning/curation/omx/` exports.
- `contracts/learning/` for the artifact manifest.

### External

- LeRobot 0.4.4 stack in the separate CPU environment. Not installed on the robot.

## Manual Notes
