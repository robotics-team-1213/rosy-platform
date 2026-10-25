---
title: A safety-module tag failed only at the end of a 25-minute FULL land round; run the structural guards first
date: 2026-10-15
last_updated: 2026-10-25
category: workflow-issues
module: tools/land.py, test/architecture/test_safety_separation.py, tools/harness/platform_parts.yaml
problem_type: workflow_issue
component: development_workflow
severity: medium
root_cause: missing_tooling
resolution_type: tooling_addition
symptoms:
  - "NEW test/architecture/test_safety_separation.py::test_safety_anchors_live_in_safety_tagged_files"
  - "AssertionError safety module has no anchor: middleware/drive/behaviors/line_follow/authority.py"
  - "rosy_harness.py lint and tools/harness/safety_review.py both passed before the land"
  - "queued FULL pretest entered its long suite before the structural guard round"
  - "file-wide Safety classification introduced forbidden imports and stale frozen edges"
applies_when:
  - "adding a path to safety_modules or a safety root in tools/harness/platform_parts.yaml"
  - "a change is FULL tier (tools/harness, contracts/foundation) and lands through land.py"
tags: [safety-modules, safety-anchors, d-430, land-py, guard-set, fast-fail, queued-pretest]
---

# A safety-module tag failed only at the end of a 25-minute FULL land round; run the structural guards first

## Context
The original 2026-10-15 entry reported the incident below; its timing and precheck observations are
retained as historical context, rather than revalidated measurements from the current run.

D-760 2c added `middleware/drive/behaviors/line_follow/authority.py` and
`middleware/core/gateway/core/trip_lease.py` to `safety_modules`. `tools/harness/**` is a FULL
trigger, so land.py ran every suite. The one failure was a structural guard: every safety module
needs at least one entry in `safety_anchors` (the D-430 §1 drift guard). The reported early checks
did not require an anchor for every safety-tagged file, so nothing failed before the long round.
`safety_review.py` does check anchor removals; that is separate from this coverage requirement.

## Guidance
- **A new safety module needs an anchor in the same commit**: a `{symbol: ...}` entry naming the
  function that makes the file safety-relevant (here `AuthorityMixin._authority_gate` and
  `TripLeaseManager.expire_due`).
- **Before a FULL land, run the guard set yourself**:
  `python tools/remote/remote_pytest.py --sha <commit> --log-dir <scratch> -- test/architecture test/test_harness_contracts.py`.
  Compare the retrieved log with `python test/known_failures.py <scratch>/run-1.txt`.
  The guard set checks size, anchors, platform parts, version pins and dependency/public boundaries.
- **Check every execution path.** The regular landing round had a first guard round, but queued
  FULL pretesting bypassed it. The correction in commit `f7357ca121` calls the existing
  [guard runner](../../../tools/land_guards.py) from [pretest](../../../tools/land.py) before its long suite.
  The helper retains its normal skip, cache and known-failure handling. This extends the earlier
  [guard-cost lesson](full-host-suite-per-branch-cost-hours-while-failures-sat-in-the-guard-set-2026-10-04.md).

## Queued-path recurrence, 2026-10-25

The commit IDs below identify retained local source snapshots, including the separate C1 candidate
branch. They document reproduction and verification as of this date, not published PRs or shipped fixes.

C1 candidate commit `9f9fc5846d` passed lint and the safety-review check, but its FULL root suite
found two `test_safety_separation.py` failures. Both failed again alone and passed on the exact
base main commit `6abf6a8a7e`; these were branch regressions, not known or load-related failures.

Adding file-wide Safety tags changed the meaning of existing imports even though the moved
lifecycle bodies were unchanged. Decision implementations became forbidden dependencies, and a
public class anchor did not publish sibling DTOs imported through reexports. The separate C1
correction used owner-local API declarations and kept actual lifecycle/admission enforcement in
Safety owners. Candidate commit `cc237b02c1` passed 578 focused tests with 5 skips. Classification
and public ownership follow [D-430](../../adr/D-430-safety-as-a-separate-concern.md); adding frozen
violations or relabeling whole implementations was not the repair.

The workflow defect was independent: queued `pretest()` ran FULL before the regular-round guard
hook. It now invokes that same hook with phase `pre`, giving guards `run-gpre-*` logs and leaving
FULL at `run-pre-*`. A failed guard prevents both the long suite and saving FULL evidence. HEAD
is checked after the guards and again after FULL; the saved main base and later delta verification
remain unchanged.

Tests-only commit `c0449396f7` reproduced all three missing-guard cases. Corrected source commit
`f7357ca121` passed 98 land/queue/record tests, no skips and NEW 0. The queued success case checks
`gpre → pre → save`; failure cases check no long suite or save, unchanged main, release of the
caller ticket and preservation of the peer ticket. See the [source verification record](../../validation/land-pretest-guards-2026-10-25/result.md).

These are committed-source test results as of 2026-10-25. Official landing, publication and device
acceptance are separate evidence; no deployment claim follows from these tests.

## Moving-main generation and recovery

The subsequent landing attempt exposed a second ordering constraint: even a conflict-free merge
of individually current indexes can leave generated records stale. Regenerate from merged inputs
before creating that merge commit, rather than weakening the lint guard or changing FULL receipts.
If generation partially changes tracked output, Git may refuse `merge --abort`. Check its exit
status and preserve the pending merge, index and worktree with an explicit recovery diagnostic;
never report successful rollback or force-reset unexpected edits. Source `18c09b384e` passed 207
remote land/queue/record/harness tests, including partial-output and abort-refusal cases (NEW 0).
The verification record above retains the preceding failing runs and exact source review.

## Applicability
Any change to `tools/harness/platform_parts.yaml`, size verdicts, or other repository-structure
contracts that only `test/architecture` enforces.
