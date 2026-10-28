# curation

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Host-side preparation of existing recordings: common Episodes, perception frames and labels, human review workspaces, and datasets. Builders copy into new directories and check declared hashes; curation does not train or activate a model.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `perception/` | Recording conversion, reviewed labels and class assets, dataset publication, review UI and smoke tooling (see `perception/AGENTS.md`) |
| `omx/` | LeRobot export and the common OMX Episode (see `omx/AGENTS.md`) |
| `pinky/` | Closed Pinky recording sessions into a common Episode (see `pinky/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Preserve original bytes and declared clocks. Do not infer Action, Attempt, or Fleet ids.
- Write outputs on $ROSY_SCRATCH. Refuse to overwrite the source or an existing output directory.

### Testing Requirements

Run the child suites `learning/curation/omx/test/`, `learning/curation/pinky/test/`, and the unified `test/learning/perception/` suite through the committed-HEAD remote runner, followed by `test/known_failures.py`. Do not run pytest on the laptop (D-584).

### Common Patterns

Profile, owner, units, and camera identity stay as declared. Null stays null.

## Dependencies

### Internal

- `contracts/learning/src/rosy/contracts/learning/` validators, loaded from `contracts/learning/src`.
- `learning/registry/policy/` can register a finished Episode dataset.
- `learning/registry/perception/store.py` owns the shared datasets, evalsets, READY inbox and model artifact/provenance store. Its existing paths and content signatures remain unchanged.
- `tools/perception/operator_ssh.py` supplies the pinned operator transport options to existing recording consumers.

### External

- Pinky raw verify uses the versions pinned in `pinky/requirements-raw.txt`.

## Manual Notes
