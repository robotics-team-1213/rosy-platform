---
title: Stale lab origin/main made the records cutover lint fail every remote run
date: 2026-11-26
category: workflow-issues
module: tools/remote/remote_pytest.py
problem_type: workflow_issue
component: testing_framework
severity: medium
applies_when:
  - "test_full_lint_including_git_history_checks fails on remote_pytest but passes in CI and in local rosy_harness.py lint"
  - "a lint or test diffs merge-base(HEAD, origin/main) on a test host"
tags: [remote-pytest, records, lint, origin-main, false-failure]
---

# Stale lab origin/main made the records cutover lint fail every remote run

## Symptom

`test/test_harness_contracts.py::test_full_lint_including_git_history_checks` failed on
every lab run with findings such as `docs/reference/ROSY API & Protocol Reference.md: edits shared
line '-**Version:** ...'` or `shared/web/logs.md: edited directly`, on branches that never touched
those files. `known_failures.py` reported it as NEW. The same commit passed in CI and in a local
`rosy_harness.py lint`, and the test failed identically on a plain `origin/main` sha.

## Cause

`records_rules.cutover_findings` diffs `merge-base(HEAD, origin/main)..HEAD`. The SHIP script in
`remote_pytest.py` fetched public main into the lab repo only when a bundle prerequisite was
missing, so the lab `origin/main` stayed hours behind. The merge base then sat before the records
bot's later main commits (API Reference version line, module `logs.md` folds), and the rule counted
those commits as the branch's own direct edits.

## Fix

SHIP fetches `+refs/heads/main:refs/remotes/origin/main` on every run, before the bundle check
(a fetch failure is still only a warning). Verified: the failing test passed on the next lab run of
the fixing commit; `test/test_remote_pytest.py` and `test/test_remote_sim.py` pass.

## Next time

A failure that appears on lab runs of unrelated branches and on `origin/main` itself, but not in CI
or locally, points at lab repo state (refs, history depth), not at the branch. Compare the lab's
`origin/main` with the public one before blaming the change or adding a known-failure entry.
