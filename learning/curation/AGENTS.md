# curation

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Host-side builders that turn an existing recording into a common Episode and DatasetManifest. They copy into a new directory and check hashes. They do not train a model.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `omx/` | LeRobot export and the common OMX Episode (see `omx/AGENTS.md`) |
| `pinky/` | Closed Pinky recording sessions into a common Episode (see `pinky/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Preserve original bytes and declared clocks. Do not infer Action, Attempt, or Fleet ids.
- Write outputs on X:. Refuse to overwrite the source or an existing output directory.

### Testing Requirements

`omx/test/` and `pinky/` checkers named in those READMEs.

### Common Patterns

Profile, owner, units, and camera identity stay as declared. Null stays null.

## Dependencies

### Internal

- `contracts/learning/` validators.
- `learning/registry/policy/` can register a finished dataset.

### External

- Pinky raw verify uses the versions pinned in `pinky/requirements-raw.txt`.

## Manual Notes
