# ui

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Site UI that is not the Fleet console. The Fleet console stays in `operations/fleet/fleet/server/web/`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `cam/` | Rosy Cam Android app, `COLCON_IGNORE` (see `cam/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Cam owns capture on the phone. Overhead ingest and ArUco live in `operations/vision/`, not in the app module.
- Wire names (`rosy-overhead/1`, `/overhead/v1/frames`) stay as the vision package documents them.

### Testing Requirements

See `cam/AGENTS.md`. Protocol fixtures are shared with `operations/vision/test/fixtures/protocol/`.

### Common Patterns

Android/Kotlin tree under `cam/app/`. The Java package `AGENTS.md` is the deepest code note.

## Dependencies

### Internal

- `operations/vision/` for the ingest contract.

### External

- Android SDK and CameraX, as the app module already uses.

## Manual Notes
