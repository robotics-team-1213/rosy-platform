<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# design-patterns

## Purpose

Compound lessons whose invariant is a design pattern (safety state machines, liveness, fail-loud transport). Apply when implementing or reviewing the named `module:`.

## Key Files

| File | Description |
|------|-------------|
| `a-safety-orchestrator-rechecks-after-every-await-and-lets-every-liveness-signal-decay.md` | Swarm formation slice: re-check safety after every await; rates/ages must decay; do not collapse refuse vs close |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- The swarm lesson constrains `operations/fleet/fleet/swarm/` (`session.py`, `relay.py`, `transport.py`). Do not add an await in the session without a post-await safety re-check.
- A liveness number derived from the last N samples must go to 0 Hz / grow age when samples stop. Do not hold the last frame.

### Testing Requirements

None here. The code tests that lock the lesson live in `operations/fleet/test/`.

### Common Patterns

YAML frontmatter `problem_type: design_pattern`, `applies_when` lists.

## Dependencies

### Internal

- `operations/fleet/fleet/swarm/`

### External

None.

<!-- MANUAL: -->
