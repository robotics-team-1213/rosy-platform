# ui

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Robot-facing UI served or packaged beside CORE. The dashboard is static files, not a Node server (D-23).

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `robot/` | CORE dashboard static files served by FastAPI (see `robot/AGENTS.md`) |
| `face/` | Emotion face (see `face/AGENTS.md`) |
| `pilot/` | Pilot tablet UI (see `pilot/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Dashboard screens live in `robot/` and are served in-process by `core_api_web`. Do not add a Vite dev server as the product path.
- Visual rules are `DESIGN.md` at the repo root. ADRs and contract tests own behavior.
- A UI change that an operator sees has to be exercised in a browser, not only described.

### Testing Requirements

Dashboard contract tests are under `middleware/core/gateway/test/` (`test_console_layout.py` and the host card tests). Face and Pilot name their own suites.

### Common Patterns

Static HTML, CSS, and JS. No React app in the current dashboard.

## Dependencies

### Internal

- `middleware/core/api_web/` serves `robot/`.
- `shared/web/` for shared operator copy and components.

### External

- A browser. No Node production server.

## Manual Notes
