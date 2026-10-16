---
title: A safety-module tag failed only at the end of a 25-minute FULL land round; run the structural guards first
date: 2026-10-15
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
applies_when:
  - "adding a path to safety_modules or a safety root in tools/harness/platform_parts.yaml"
  - "a change is FULL tier (tools/harness, contracts/foundation) and lands through land.py"
tags: [safety-modules, safety-anchors, d-430, land-py, guard-set, fast-fail]
---

# A safety-module tag failed only at the end of a 25-minute FULL land round; run the structural guards first

## Context
D-760 2c added `middleware/drive/behaviors/line_follow/authority.py` and
`middleware/core/gateway/core/trip_lease.py` to `safety_modules`. `tools/harness/**` is a FULL
trigger, so land.py ran every suite. The one failure was a structural guard: every safety module
needs at least one entry in `safety_anchors` (the D-430 §1 drift guard). Lint and
`safety_review.py` do not check anchors, so nothing failed before the long round.

## Guidance
- **A new safety module needs an anchor in the same commit**: a `{symbol: ...}` entry naming the
  function that makes the file safety-relevant (here `AuthorityMixin._authority_gate` and
  `TripLeaseManager.expire_due`).
- **Before a FULL land, run the guard set yourself**:
  `python tools/remote/remote_pytest.py --log-dir X:/DevTemp/<name> -- test/architecture test/test_harness_contracts.py -q`.
  It takes minutes and catches size verdicts, anchors, platform parts and version pins.
- Tooling fix in progress on branch `fix/land-fast-fail-and-log-order` (pending): land.py runs that
  guard round first and stops before the long round when it shows NEW. This extends
  `full-host-suite-per-branch-cost-hours-while-failures-sat-in-the-guard-set-2026-10-04.md`.

## Applicability
Any change to `tools/harness/platform_parts.yaml`, size verdicts, or other repository-structure
contracts that only `test/architecture` enforces.
