# device

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Product device trees for the OMX arm and the Pinky Pro base.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `omx/` | Adapter, profile, and the agent composition wheel (see `omx/AGENTS.md`) |
| `pinky/` | Bringup, description, and profile (see `pinky/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Pinky full spec in-tree is `pinky/profile/`. The robot advertises the overlays under `deploy/robot/pinky_pro/config/`.
- OMX agent code composes existing owners. It is not a new motion publisher.

### Testing Requirements

Adapter tests are `omx/adapter/test/`. Bringup tests are `pinky/bringup/test/`.

### Common Patterns

ROS packages and wheels are siblings. Read the child `AGENTS.md` before editing either.

## Dependencies

### Internal

- CORE gateway and the skill/execution wheels the OMX agent declares.

### External

- Dynamixel, lidar, and the OMX planner types named by the children.

## Manual Notes
