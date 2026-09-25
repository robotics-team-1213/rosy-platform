---
title: Concurrent sessions picked the same ADR number twice, and skipping ahead broke the harness lint
date: 2026-09-25
category: workflow-issues
module: docs/adr, docs/reference/ROSY ADR Log.md, tools/harness
problem_type: workflow_issue
component: development_workflow
severity: low
applies_when:
  - "more than one agent session writes ADRs in the same Rosy OS checkout or against the same origin/main"
  - "choosing the next D-number for a new ADR"
tags: [adr, numbering, concurrent-sessions, harness-lint, adr-gaps]
---

# Concurrent sessions picked the same ADR number twice, and skipping ahead broke the harness lint

## Context
On 2026-09-25 one session wrote the reflash ADR as D-223 while another session was writing a keyboard-
vocabulary ADR as D-223 in the same working tree (uncommitted). Both renumbered to D-224 at the same moment.
The first session then jumped to D-230 to get clear, which left D-225..D-229 as gaps. `python
tools/harness/rosy_harness.py lint` fails on any missing ADR number that is not declared in `adr_gaps`
(`tools/harness/harness.yaml`), so the jump produced 6 lint errors (D-223 and D-225..D-229).

## Guidance
1. Right before numbering, look at all three places: `git ls-tree --name-only origin/main docs/adr/`,
   the working tree's `docs/adr/` (untracked files from other sessions), and the `| D-nnn |` rows in
   `docs/reference/ROSY ADR Log.md` (a peer may have added a row without a file yet).
2. Take the next free number, not a far-ahead one. Commit and push the ADR file plus its Log row promptly,
   so the number is claimed on origin.
3. If a collision already happened, move to the next free number. When a number is skipped for good,
   declare it in `adr_gaps` with the reason, e.g.
   `D-223: "skipped: the surface keyboard-vocabulary ADR moved to D-224 during a concurrent-session numbering collision (2026-09-25)"`.
4. The ADR Log may hold another session's uncommitted row. Stage only your row: build the blob from
   `HEAD:` plus your line and `git update-index --cacheinfo`, rather than `git add` on the whole file.

## Why This Matters
A far-ahead number looks safe, but the harness treats gaps as errors, and renumbering later touches code
comments, tests and log entries that already cite the number (the reflash ADR went D-223 → D-224 → D-230 →
D-225 and needed a follow-up commit because the heading still said D-230).

## When to Apply
- Every new ADR while `ListAgents` shows other Rosy sessions.

## Examples
Final state: D-224 = surface keyboard vocabulary, D-225 = update without reflash (commits 1a1a4a69,
e5ef699f), D-223 declared as a gap in `tools/harness/harness.yaml`.

## Related
- `docs/solutions/workflow-issues/a-fixture-from-the-same-model-is-one-belief-not-two.md` (unrelated
  area; same "check the shared state first" theme)
- auto memory [claude]: peers commit into the same Rosy OS tree and branch; check ListAgents before bulk
  commits
