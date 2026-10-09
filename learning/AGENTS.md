# learning

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

D-427 learning part. Curation, offline training, the policy metadata registry, and Isaac Sim. Only the ROS package `isaac_sim` is a `colcon_roots` entry and only that package is allowed onto a device payload (D-427 Q8). The other folders are host-side tools. Their outputs stay on X:, not in this repo.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `curation/` | Episode builders. OMX LeRobot export and Pinky recording conversion (see `curation/AGENTS.md`) |
| `envs/` | Simulation environments. `isaac/` is ROS package `isaac_sim` (see `envs/AGENTS.md`) |
| `registry/` | Offline policy metadata ledger (see `registry/AGENTS.md`) |
| `training/` | Offline jobs for perception, OMX ACT, and Pinky speed models (see `training/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Do not install torch, LeRobot, or these job CLIs onto the robot image or the contract wheels.
- A training result is not promotion and not a Fleet dispatch. Registry promotion is metadata only.
- New run outputs go to a new directory on X:. Do not overwrite a previous run.

### Testing Requirements

Each child names its pytest. Perception training tests are not a substitute for a device acceptance run.

### Common Patterns

Korean README titles, English module names. Jobs take explicit train and eval sessions and refuse overlapping dataset names or MCAP hashes.

## Dependencies

### Internal

- `contracts/learning/` for Episode and PolicyArtifact shapes.
- `deploy/robot/omx/` for the LeRobot export requirements file.

### External

- Separate Python 3.12 CPU environments for torch jobs. Not the robot venv.

## Manual Notes
