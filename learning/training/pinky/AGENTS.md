# pinky

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Compares speed models on Pinky recordings. `comparison_job.py` verifies the source MCAP, trains on two sessions, and evaluates on a third. The target is the recorded CORE final output, not an expert label. Random frame splits are not used.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | CLI, the CPU pins, and the MAE reporting rules |
| `comparison_job.py` | Train two sessions, eval a third, write a new directory |
| `artifact_export.py` | Export the comparison artifact |
| `test/` | Host tests |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `test/` | Checks for the comparison job |

## For AI Agents

### Working In This Directory

- Refuse overlapping Dataset, Episode, session names, or MCAP hashes.
- Report m/s and rad/s separately for all, moving, and stop. Do not average the two units.
- Moving in this report means recorded `|v| > 0.01` m/s or `|w| > 0.05` rad/s. That is not a claim about physical motion.
- Dependencies come from a separate Python 3.12 environment (torch 2.7.1, numpy 2.2.6, OpenCV 4.12) plus `learning/curation/pinky/requirements-raw.txt`. Do not install them into the contract wheel or the robot.

### Testing Requirements

`python -m pytest learning/training/pinky/test -q` for host checks. A real comparison uses the pinned environment and writes only to a new directory on X:.

### Common Patterns

Constant-mean and zero baselines sit beside the ridge and small CNN so a learned number has something to beat.

## Dependencies

### Internal

- Episodes from `learning/curation/pinky/`.
- `contracts/learning/` manifest shapes.

### External

- The CPU pins in the README. Not robot CI.

## Manual Notes
