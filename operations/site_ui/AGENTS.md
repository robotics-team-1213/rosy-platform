# site_ui

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-11

## Purpose

Site capture and media holder. Fleet product UI moved to `applications/fleet/web` (D-822); the existing Fleet distribution still installs it as `fleet/server/web`. `cam/` is Rosy Cam. API, ledger and final execution authority remain with their existing owners.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `cam/` | Rosy Cam Android app, `COLCON_IGNORE` (see `cam/AGENTS.md`) |
| `media/` | Site media-session service (see `media/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Cam owns capture on the phone. Overhead ingest and ArUco live in `operations/overhead/`, not in the app module.
- Wire names (`rosy-overhead/1`, `/overhead/v1/frames`) stay as the vision package documents them.

### Testing Requirements

See `cam/AGENTS.md` and `media/AGENTS.md`. Pytest and browser checks run on the remote test PCs per D-584. Protocol fixtures are shared with `operations/overhead/test/fixtures/protocol/`.

### Common Patterns

Android/Kotlin tree under `cam/app/`. The Java package `AGENTS.md` is the deepest code note.

## Dependencies

### Internal

- `operations/overhead/` for the ingest contract.
- Console consumes the static allowlist/CSP and API from `operations/fleet/fleet/server`, plus common assets from `shared/web`.

### External

- Android SDK and CameraX, as the app module already uses.

## Manual Notes
