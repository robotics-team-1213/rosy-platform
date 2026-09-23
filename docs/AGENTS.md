<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-14 -->

# docs

## Purpose

Governance documents (D-17): requirements, shared API/protocol contract, ADRs, implementation plan, dated design/execute plans, Pi deployment runbooks, and a Phase 1 test report. Requirement IDs are the cross-document keys, not section numbers.

## Key Files

Content lives in the subdirectories below; at this root only the harness records.

| File | Description |
|------|-------------|
| `progress.md` | Governance gate snapshot (ADR log, harness). Overwrite; state of record over this file |
| `logs.md` | Append-only work journal, one entry per change |
| `index.md` | Generated: ADRs, plans, solutions, tests, recent logs. Do not edit |

## Subdirectories

| Directory | Purpose |
|-----------|---------|
| `spec/` | CORE and FLEET software requirements (see `spec/AGENTS.md`) |
| `reference/` | Live API contract and ADR log. The frozen pinky zip is the repo-root `reference/`, not this directory |
| `plans/` | Dated design + execute plans; the historical WBS (`ROSY Implementation Plan.md`) and Flask parity checklist moved here when `docs/plan/` retired (see `plans/AGENTS.md`) |
| `deployment/` | Pi 5 runtime, Wi-Fi image, power bench, release keys (see `deployment/AGENTS.md`) |
| `test/` | P1 test report (see `test/AGENTS.md`) |
| `solutions/` | Durable learnings from reviews and bugs, YAML frontmatter, by category (see `solutions/AGENTS.md`) |
| `assets/` | Architecture and product images (see `assets/AGENTS.md`) |

## For AI Agents

### Working In This Directory

- Harness (D-61): read `progress.md` and `index.md` first. After a change, append `logs.md`, overwrite `progress.md` if a gate moved, then run `python tools/harness/rosy_harness.py generate` from the repo root.
- Do not put implementation code here. Specs constrain `src/`; deployment docs constrain `deploy/`.
- Changing API paths or envelope fields requires updating `reference/ROSY API & Protocol Reference.md` **and** `core_common/protocol/schemas.py` together (D-18).
- ADRs are append-only: mark old ones `Superseded`, add a new ID. Do not silently rewrite D-n.
- Dated files in `plans/` are the working design trail; `plans/ROSY Implementation Plan.md` is the (historical) WBS tracker.

### Testing Requirements

After doc edits, grep the code for the requirement IDs you changed and confirm tests still name them. ADR log shape and harness records are pinned by contract tests:

```bash
python3 -m pytest test/test_network_topology_contracts.py test/test_harness_contracts.py -q
python3 tools/harness/rosy_harness.py lint
```

### Common Patterns

- Korean prose for governance docs; English identifiers (`SAF-005`, `D-22`).
- Design docs often come in pairs: `*-design.md` then execute plan `*.md`.

## Dependencies

### Internal

- Implementation: `src/core/core`, `src/hardware/bringup`, `deploy/`
- Traceability matrix in Implementation Plan §11

### External

None.

<!-- MANUAL: -->
