---
title: API version numbers collide between parallel landings; reserve before use, renumber only on the later lander
date: 2026-10-15
category: workflow-issues
module: docs/reference/ROSY API & Protocol Reference.md, middleware/core/api/core_api_web/api/app.py, version-pin tests
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: concurrency
resolution_type: workflow_improvement
symptoms:
  - "local main carried two different v1.225 history rows (D-754 and D-760 stage 2) after two sessions landed the same number"
  - "one branch (D-758 stage 0) was renumbered v1.228, v1.231, v1.232, v1.234, each time after a 22-minute FULL land round"
  - "land.py stopped with merge conflicts on the Version header, app.py docstring and five pin tests"
applies_when:
  - "two or more sessions have unlanded branches that bump the API Reference version"
  - "a landing takes longer than the time between other sessions' landings"
tags: [api-version, version-pins, parallel-sessions, land-py, merge-conflict, d-762]
---

# API version numbers collide between parallel landings; reserve before use, renumber only on the later lander

## Context
On 2026-10-14..15 five sessions bumped the API Reference version in parallel. Each picked "main's
version + 1" when it started, and the number was checked again only at landing. For a contract
change that is a FULL round of about 22-30 minutes.

- **Collision on main:** D-754 and D-760 stage 2 both landed as v1.225. The duplicate stayed on local
  main until a follow-up branch moved D-760's sections and pins to v1.226.
- **Repeated renumbering:** D-758 stage 0 was ready at v1.228 and landed as v1.234. Each time a peer
  took the number during its FULL round, the round stopped on pin conflicts, and the branch was merged
  and renumbered by hand. A version is three pins plus the history row
  (`a-contract-version-bump-is-three-pins-not-one.md`), so each renumber touched about eight files.

## Guidance
- **Reserve the number in the shared channel before writing pins**, and keep one list of every
  reservation (for example `v1.237 slice 4, v1.238 regulation-capabilities, v1.239 ...`). Sessions that
  announced their numbers did not collide.
- **Order landings by number.** When the queue lands out of order, the later lander renumbers;
  nobody edits a number that is already on main.
- **Prefer a tool over etiquette.** D-762 lists "the landing tool assigns the version (vNEXT)" as a
  follow-up, and a branch `api-version-reserve` was queued on 2026-10-15 (pending). Until it lands,
  the reservation message is the only guard.
- **Do not rewrite a landed log entry** that names the old number. Append a new entry that records
  the move; logs are append-only and lint rejects edits.

## Applicability
Any number shared by parallel sessions: API versions, ADR numbers
(`adr-numbers-collide-between-concurrent-sessions-2026-09-25.md`, now guarded by
`tools/harness/adr_reserve.py`), migration numbers.
