<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# spec

## Purpose

Approved software requirements. CORE is the robot/edge obligation; FLEET is the central server (not implemented in this repo).

## Key Files

| File | Description |
|------|-------------|
| `ROSY CORE SRS.md` | ROSY-CORE-SRS-001 — robot middleware, local-first, API-only external interface, AT |
| `ROSY FLEET SRS.md` | ROSY-FLEET-SRS-001 — multi-robot fleet server (Linux/Docker) |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- CORE SRS §1.3: no external `cmd_vel`; Fleet never drives motors directly.
- Implement against requirement IDs (`CORE-001`, `SAF-001`…) not heading numbers.
- FLEET SRS must not be implemented inside `core`. Phase 4 is a separate server.

### Testing Requirements

New CORE behavior needs an AT/unit test named in Implementation Plan §11.

### Common Patterns

Both docs inherited PKY-* IDs and were renamed ROSY (D-15/D-16).

## Dependencies

### Internal

- `docs/reference/ROSY API & Protocol Reference.md` for the shared contract
- `src/runtime/core` implements CORE SRS

### External

None.

<!-- MANUAL: -->
