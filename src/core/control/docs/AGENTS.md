<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# docs

## Purpose

Operator-facing notes for camera ground calibration, localization, and narrow-passage navigation, plus dated validation dumps. Korean prose. These are package notes, not the repo governance docs in `Rosy OS/docs/`.

## Key Files

| File | Description |
|------|-------------|
| `camera-ground-calibration.md` | Measure camera height/pitch/focal length so region bottom edges become meters; do not invent defaults |
| `localization.md` | Localization notes for the desk-maze robot |
| `narrow-passage-navigation.md` | Narrow-passage behavior and limits |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `validation/` | Dated mapping/planner evidence (`*.npz`, `*.json`). Artifact dumps — no nested AGENTS.md |

## For AI Agents

### Working In This Directory

- Unmeasured camera geometry stays `distance_m: null`. A plausible fake distance is worse than unknown.
- Do not treat `validation/` snapshots as the pytest suite; tests load `../test/fixtures/`.
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
