# ui

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11

## Purpose

Site UI source holders: Fleet Console in `operations/site_ui/console` and Rosy Cam in `operations/site_ui/cam`. The existing Fleet distribution installs and serves Console as `fleet/server/web`; API, ledger and final execution authority remain with their existing owners (D-637).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `console/` | Fleet Console source; installed identity `fleet.server.web`, backend `operations/fleet/fleet/server` (see `console/AGENTS.md`) |
| `cam/` | Rosy Cam Android app, `COLCON_IGNORE` (see `cam/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Cam owns capture on the phone. Overhead ingest and ArUco live in `operations/vision/`, not in the app module.
- Wire names (`rosy-overhead/1`, `/overhead/v1/frames`) stay as the vision package documents them.

### Testing Requirements

See `console/AGENTS.md` for Console and `cam/AGENTS.md` for Cam. Pytest and browser checks run on the remote test PCs per D-584. Protocol fixtures are shared with `operations/vision/test/fixtures/protocol/`.

### Common Patterns

Android/Kotlin tree under `cam/app/`. The Java package `AGENTS.md` is the deepest code note.

## Dependencies

### Internal

- `operations/vision/` for the ingest contract.
- Console consumes the static allowlist/CSP and API from `operations/fleet/fleet/server`, plus common assets from `shared/web`.

### External

- Android SDK and CameraX, as the app module already uses.

## Manual Notes
