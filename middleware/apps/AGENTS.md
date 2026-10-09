# apps

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Device application packages that sit beside CORE. They bring up a product (Pinky, OMX) and do not replace the CORE API.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `device/` | Pinky and OMX device trees (see `device/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Hardware profiles and launch files stay in the product child. CORE still arbitrates commands.
- Do not copy a board overlay into `deploy/robot/pinky_pro/config` for an alias that has no catalog mode.

### Testing Requirements

See the bringup and adapter `AGENTS.md` files under `device/`.

### Common Patterns

Each ROS package has its own `package.xml` and `AGENTS.md`.

## Dependencies

### Internal

- `middleware/core/gateway` for the runtime those launches join.
- `deploy/robot/pinky_pro/` for the image and native units.

### External

- ROS 2 Jazzy, and the board libraries named by each driver.

## Manual Notes
