# training

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Offline training jobs. They run in a separate CPU environment, write a new directory on X:, and do not deploy weights to a robot.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception/` | D-356 learned-loop tooling for lane and perception models (see `perception/AGENTS.md`) |
| `omx/` | OMX ACT research on existing LeRobot exports (see `omx/AGENTS.md`) |
| `pinky/` | Pinky recording speed-model comparison against recorded CORE output (see `pinky/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Train and eval sessions must be distinct. Overlapping dataset names or MCAP hashes are a refusal, not a warning.
- Do not resume a failed ACT run in place. Start a new `--out`.
- Reported metrics are not a promotion. The registry does that separately.

### Testing Requirements

Each child has its own README command. Perception tests are the ones wired like the other learning packages; the ACT and Pinky jobs need their pinned CPU environments.

### Common Patterns

`--steps`, `--seed`, and an explicit output directory. Failure keeps a state file and partial outputs.

## Dependencies

### Internal

- Curated episodes from `learning/curation/`.
- Contract shapes from `contracts/learning/`.

### External

- torch, numpy, and OpenCV only in the environment the child README names.

## Manual Notes
