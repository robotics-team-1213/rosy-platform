<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-14 -->

# assets

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Non-executable images used by repository documentation. Requirements, runbooks, and architecture decisions belong in the appropriate `docs/` subdirectory.

## Key Files

| File | Description |
|------|-------------|
| `architecture.png` | High-level Rosy OS architecture diagram |
| `rosy_pro_image.png` | Pinky Pro product image |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `calibration/` | 보정 체계 문서 그림 (`docs/reference/calibration-system*.md`) |
| `video-records/` | 영상 기록 문서 GIF (`docs/reference/video-records-*.md`) |

## For AI Agents

### Working In This Directory

- Do not put Markdown requirements or deployment instructions in this folder.
- Do not regenerate or replace an image unless the documented architecture or product representation actually changed.
- Link to these files from Markdown with the `docs/assets/` path.

### Testing Requirements

None.

### Common Patterns

PNG·JPG images. `video-records/` holds GIF previews (3 MB or less each). Referenced from README and governance docs.

## Dependencies

### Internal

- Consumers: `docs/` markdown

### External

None.

<!-- MANUAL: -->
