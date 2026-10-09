<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-14 | Updated: 2026-09-14 -->

# solutions

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Durable learnings captured after review or bug-fix cycles (`ce-compound`). Each note has YAML frontmatter (`module`, `tags`, `problem_type`, `applies_when`) and lives in a category folder. Read these before repeating a design or verification pattern in a documented area.

## Key Files

None at this directory root — notes live in the category folders below.

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `design-patterns/` | Recurring architecture/safety patterns (see `design-patterns/AGENTS.md`) |
| `workflow-issues/` | Verification and process failure modes (see `workflow-issues/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Do not put implementation code here. A lesson describes a class of mistake or a decision future cycles must respect.
- New notes go under the matching category with YAML frontmatter; do not dump ad-hoc markdown at this root.
- Before the next design/execute cycle, grep this tree for the module you are touching.

### Testing Requirements

None. Frontmatter is the machine-readable index.

### Common Patterns

One problem per file. Title is the invariant, not the ticket. Korean or English body; English identifiers.

## Dependencies

### Internal

- Code these notes constrain: `operations/fleet`, deploy/test gates, and whatever `module:` names

### External

None.

<!-- MANUAL: -->
