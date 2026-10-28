# training

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Offline training jobs and their input/output contracts. Each job uses its declared separate CPU/GPU environment and a new output directory; local development artifacts belong on $ROSY_SCRATCH. Existing remote stores retain their paths. Training does not deploy or activate robot behavior.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception/` | Actual trainer, recording/training jobs, review admission composition and notebook recipes (see `perception/AGENTS.md`) |
| `omx/` | OMX ACT research on existing LeRobot exports (see `omx/AGENTS.md`) |
| `world_model/` | D-782 M1 action-conditioned dynamics ensemble on world-model datasets (see `world_model/AGENTS.md`) |
| `pinky/` | Pinky recording speed-model comparison against recorded CORE output (see `pinky/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Train and eval sessions must be distinct. Overlapping dataset names or MCAP hashes are a refusal, not a warning.
- Do not resume a failed ACT run in place. Start a new `--out`.
- Reported metrics are not a promotion. The registry does that separately.

### Testing Requirements

Each child has its own README command and declared environment. Perception source and fixtures use the unified `test/learning/perception/` suite. Run pytest only for committed HEAD via `tools/remote/remote_pytest.py`, followed by `test/known_failures.py` (D-584); the ACT and Pinky jobs retain their pinned CPU environments.

### Common Patterns

`--steps`, `--seed`, and an explicit output directory. Failure keeps a state file and partial outputs.

## Dependencies

### Internal

- Curated episodes from `learning/curation/`.
- Contract shapes from `contracts/learning/src/rosy/contracts/learning/`, loaded from `contracts/learning/src`.
- `learning/registry/perception/store.py` for shared datasets, evalsets, READY inbox and model provenance.
- `learning/evaluation/perception/` for existing replay evaluation and `tools/perception/` for the cross-owner CLI/transport. Curation and registry implementation lives in those holders, not inside the trainer directory.

### External

- torch, numpy, and OpenCV only in the environment the child README names.

## Manual Notes
