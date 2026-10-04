<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# map

## Purpose

Packaged occupancy maps used only when the host has no site map at
`/var/lib/rosy/maps/site.yaml`.

## Key Files

| File | Description |
|------|-------------|
| `my_map.yaml` / `my_map.pgm` | Default occupancy map |
| `pinklab.yaml` / `pinklab.png` | PinkLab map |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

`map_id` in CORE is filename + content checksum (D-13). Renaming files changes ids.

### Testing Requirements

None.

### Common Patterns

YAML + image pair.

## Dependencies

### Internal

- Nav2 map_server

### External

None.

<!-- MANUAL: -->
