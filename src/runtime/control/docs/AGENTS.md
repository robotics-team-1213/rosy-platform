<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# docs

## Purpose

Operator-facing notes for camera ground calibration, localization, and narrow-passage navigation. Korean prose. These are package notes, not the repo governance docs in `Rosy OS/docs/`.

## Key Files

| File | Description |
|------|-------------|
| `camera-ground-calibration.md` | Measure camera height/pitch/focal length so region bottom edges become meters; do not invent defaults |
| `localization.md` | Localization notes for the desk-maze robot |
| `narrow-passage-navigation.md` | Narrow-passage behavior and limits |

## Subdirectories

None. Dated evidence goes in `../../../../docs/validation/`; data a test reads goes in `../test/fixtures/` (D-226).

## For AI Agents

### Working In This Directory

- Unmeasured camera geometry stays `distance_m: null`. A plausible fake distance is worse than unknown.
- Do not add a `validation/` folder here. Dated results go in the repo `docs/validation/<topic>-<YYYY-MM-DD>/` (D-226).
- Repo-level SRS/ADR changes go in `../../../docs/`, not here.

### Testing Requirements

None for the markdown. Calibration math is covered by `../test/`.

### Common Patterns

Korean how-to; English identifiers (`ground_plane()`, `distance_m`).

## Dependencies

### Internal

- `control` camera / localization / planning subjects
- `../test/fixtures/` for machine-readable traces

### External

None.

<!-- MANUAL: -->
