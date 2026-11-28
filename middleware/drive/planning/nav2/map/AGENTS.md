
# map

**Parent context:** `../AGENTS.md`

## Purpose

Packaged occupancy maps used only when the host has no site map at
`/var/lib/rosy/maps/site.yaml`.

## For AI Agents

### Working In This Directory

`map_id` in CORE is filename + content checksum (D-13). Renaming files changes ids.

### Common Patterns

YAML + image pair.

## Dependencies

### Internal

- Nav2 map_server
