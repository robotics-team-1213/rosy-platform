<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# reference

## Purpose

Frozen upstream snapshot used as the implementation baseline (D-16). The zip is the as-is pinky_pro tree; ROSY does not merge upstream automatically.

## Key Files

None at this level.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `src/` | Contains `pinky_pro-main.zip` (gitignored). Cited by `docs/plans/ROSY Implementation Plan.md` |

## For AI Agents

### Working In This Directory

- Do not treat zip contents as live code. Current packages are the domain groups under `src/` (`core`, `apps`, `hardware`, `navigation`, `sim`, `site`).
- Live API and ADR documents are `docs/reference/`, not this folder.
- When comparing behavior, unzip locally and diff against those domain groups.

### Testing Requirements

None.

### Common Patterns

Read-only archive. Do not add new reference trees here.

## Dependencies

### Internal

- Implementation Plan §2 As-Is analysis

### External

- https://github.com/pinklab-kr/pinky_pro

<!-- MANUAL: -->
