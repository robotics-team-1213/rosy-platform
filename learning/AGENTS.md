# learning

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-12

## Purpose

D-427 learning part. Perception curation, replay evaluation and offline training, shared artifact/provenance and policy registries, and Isaac Sim. Only the ROS package `isaac_sim` is a `colcon_roots` entry and only that package is allowed onto a device payload (D-427 Q8). The other folders are host-side tools. Local development outputs stay on $ROSY_SCRATCH, not in this repo. Existing remote data and store paths retain their declared lineage.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `curation/` | Perception recording/review/dataset preparation, OMX LeRobot export, and Pinky Episode conversion (see `curation/AGENTS.md`) |
| `evaluation/` | Replay evaluation holder. The implementation is `perception/` (see `evaluation/AGENTS.md`) |
| `envs/` | Simulation environments. `isaac/` is ROS package `isaac_sim` (see `envs/AGENTS.md`) |
| `registry/` | Shared perception artifact/provenance store and model lifecycle, plus offline policy metadata (see `registry/AGENTS.md`) |
| `training/` | Offline jobs for perception, OMX ACT, and Pinky speed models (see `training/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Do not install torch, LeRobot, or these job CLIs onto the robot image or the contract wheels.
- A training result is not promotion and not a Fleet dispatch. Registry promotion is metadata only.
- New run outputs go to a new directory on $ROSY_SCRATCH. Do not overwrite a previous run.

### Testing Requirements

Each child names its suite. Run pytest only for committed HEAD through `tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<session>" -- <suite>`, then compare the returned log with `test/known_failures.py` (D-584). The unified perception suite is `test/learning/perception/`; host results do not replace device or field acceptance.

### Common Patterns

Korean README titles, English module names. Jobs take explicit train and eval sessions and refuse overlapping dataset names or MCAP hashes.

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/` for Episode and PolicyArtifact shapes; standalone loaders add `contracts/learning/src` to the import path.
- `contracts/foundation/` for existing protocol validators where required.
- `tools/perception/` for the cross-owner `rosy_ml.py` CLI and pinned operator SSH options.
- `deploy/robot/omx/` for the LeRobot export requirements file.

### External

- Separate Python environments and CPU/GPU dependencies named by each job README; perception can use a model PC or Colab. Keep them separate from the robot venv.

## Manual Notes
