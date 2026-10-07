# apps

**Parent context:** `../AGENTS.md`
**Generated:** 2026-10-07 · **Updated:** 2026-10-07

## Purpose

Operator applications that run with the site, not on the robot CORE process.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `games/` | ROS package `games` (see `games/AGENTS.md`) |
| `fleet/` | Wheel `rosy-app-gateway`, console script `rosy-site-gateway` (see `fleet/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Games is an ament package. The gateway wheel is not. Do not add `package.xml` to the wheel to make colcon notice it.
- The gateway composes palletizing and execution. It is not a second Fleet server.

### Testing Requirements

`python -m pytest operations/apps/games/test -q`. Gateway coverage is the tests that import `rosy_gateway`.

### Common Patterns

`COLCON_IGNORE` on `fleet/` only.

## Dependencies

### Internal

- `operations/fleet/` for the console the gateway sits in front of.
- `operations/processes/palletizing/` and `operations/execution/`.

### External

- PyYAML for the gateway wheel. Games names ROS deps in its `package.xml`.

## Manual Notes
