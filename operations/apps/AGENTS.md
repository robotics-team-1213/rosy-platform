# apps

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Operator applications that run with the site, not on the robot CORE process.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `games/` | ROS package `games` (see `games/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Games is an ament package. Fleet application composition moved to `applications/fleet/gateway` (D-822); follow that holder's instructions for its wheel.

### Testing Requirements

Games tests live in `operations/apps/games/test`; use the root remote-testing procedure.

### Common Patterns

`COLCON_IGNORE` on `fleet/` only.

## Dependencies

### Internal

- `operations/fleet/` for the console the gateway sits in front of.
- `operations/processes/palletizing/` and `operations/site_execution/`.

### External

- PyYAML for the gateway wheel. Games names ROS deps in its `package.xml`.

## Manual Notes
