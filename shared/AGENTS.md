# shared

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Shared web components and operator copy. Protocol and skill contracts stay in `contracts/`, not here.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `web/` | Shared web package used by the dashboard and Fleet UI (see `web/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- A string or component shared by two UIs belongs here. A REST field does not. Add the field in the API reference and the schema first.
- Follow `DESIGN.md` for tokens and components.

### Testing Requirements

`python -m pytest shared/web/test -q`

### Common Patterns

One web package. Its `AGENTS.md` has the file-level rules.

## Dependencies

### Internal

- Served by `middleware/core/api_web` and `operations/fleet`.

### External

- None beyond what `web/AGENTS.md` names.

## Manual Notes
