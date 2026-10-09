# envs

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Learning simulation environments. The only ROS package here is `isaac_sim`.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `isaac/` | ROS package `isaac_sim`, Isaac Sim 6.1 integration, and a `colcon_roots` entry (see `isaac/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- D-427 Q8: `isaac_sim` is the learning package that may reach a device, as a native payload. The training jobs under `learning/training/` do not.
- Model source notes live in `isaac/assets/README.md`.

### Testing Requirements

See `isaac/AGENTS.md`.

### Common Patterns

One ROS package per environment folder, with its own `AGENTS.md`.

## Dependencies

### Internal

- Colcon root list from `tools/harness/colcon_roots.py`.

### External

- Isaac Sim 6.1 for the integration described in `isaac/README.md`.

## Manual Notes
