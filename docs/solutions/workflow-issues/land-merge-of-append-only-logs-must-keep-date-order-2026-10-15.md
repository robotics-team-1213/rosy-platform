---
title: Auto-merging append-only logs put an older entry after newer ones; fixing it by hand made the next land refuse
date: 2026-10-15
category: workflow-issues
module: tools/land.py (merge auto-resolver), tools/harness/rosy_harness.py lint, module logs.md files
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "rosy_harness.py lint ERROR fleet/logs.md: a 2026-10-14 entry out of order (after 2026-10-15)"
  - "land.py STOP lint failed right after '[merge] auto-resolved operations/fleet/index.md, operations/fleet/logs.md'"
  - "after moving the block by hand, the next land refused with 'a side changed existing lines, not only appended'"
applies_when:
  - "a branch with logs.md entries dated day N lands after peers appended entries dated day N+1"
  - "a land.py round stops on lint right after an auto-resolved merge"
tags: [land-py, logs-md, append-only, merge, lint, date-order]
---

# Auto-merging append-only logs put an older entry after newer ones; fixing it by hand made the next land refuse

## Context
D-760 stage 4 wrote its `operations/fleet/logs.md` entry on 2026-10-14 and landed on 2026-10-15.
In between, peers appended 2026-10-15 entries to the same file.

- **Merge:** land.py's resolver keeps both sides of an append-only file. It appended the branch's
  10-14 block after main's 10-15 blocks.
- **Lint:** the date-order check then failed, and the land round stopped after its tests had passed.
- **Hand fix:** the block was moved above the first 10-15 entry. The next land merged a newer main,
  saw that the branch had changed existing lines (the move), and refused to auto-resolve.
- **Final fix:** a hand merge that took main's file and inserted the branch-only blocks at their date
  position, followed by `rosy_harness.py generate`.

## Guidance
- When resolving a logs.md conflict by hand, start from main's file and **insert** the branch-only
  `## ` blocks at their date position. Never reorder main's blocks.
- Regenerate `index.md` with `rosy_harness.py generate` instead of merging it.
- Tooling fix in progress on branch `fix/land-fast-fail-and-log-order` (2026-10-15, pending): the
  resolver writes the union in date order and treats a pure move of a side's own appended blocks as
  auto-resolvable.

## Applicability
Every append-only, date-ordered journal checked by lint: module `logs.md` files and `docs/logs.md`.
