# evaluation

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-12 · **Updated:** 2026-10-12

## Purpose

Host-side replay evaluation for the learning part. The implementation is `perception/`. Evaluation scores existing recordings and labels. It does not activate a model, admit an artifact, or publish a command.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception/` | Road replay, fitness, and line-stop checkers (see `perception/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Do not add a second evaluation package beside `perception/`.
- A report stays diagnostic until the child module's lineage, coverage, and device evidence say otherwise.
- Datasets and weights stay out of this public tree.

### Testing Requirements

The child names `learning/evaluation/perception/test`, `test/learning/perception`, and `operations/world/test`. Run committed HEAD through `tools/remote/remote_pytest.py`, then `test/known_failures.py`.

### Common Patterns

Offline checkers with explicit HOLD when evidence is missing. No robot runtime in this folder.

## Dependencies

### Internal

- Curation owns input conversion. Registry owns artifacts. Training owns trainer jobs.
- The CLI is `tools/perception/rosy_ml.py`.

### External

- The perception job environment named by the child. It is not the robot image.

## Manual Notes
