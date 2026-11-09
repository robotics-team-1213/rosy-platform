---
title: A rerun by node id must keep pytest's escaped parameter id byte for byte
date: 2026-11-09
category: workflow-issues
module: test/known_failures.py
problem_type: workflow_issue
component: testing_framework
severity: high
symptoms:
  - "One browser test with Korean parameter ids stops many different branches' landings in a few hours"
  - "The MAIN-RED rerun prints 'ERROR: not found: ...::test_x' and 'main check gave no verdict (exit 4 ...)'"
  - "Rerun command lines show ids like [390-844-delayed-/uc9c0/uc5f0]"
root_cause: logic_error
resolution_type: code_fix
tags: [land, main-red, known-failures, pytest-node-id, unicode, rerun]
applies_when: "Code parses FAILED/ERROR/PASSED node ids from a pytest report and feeds them back to pytest"
---

# A rerun by node id must keep pytest's escaped parameter id byte for byte

## Symptom

On 11-04, `middleware/core/api/test/test_d283_console_browser.py` (7 ids) stopped 8 landings of 7 different branches on all three test hosts within about 3.5 hours. Main itself was red at that time: the console overflow and the KPI strip were reverted on main afterwards, and the failures stopped. The landings should have reported `MAIN-RED` and pointed to main. Instead each stop said "main check gave no verdict (exit 4 ...)", so each branch looked guilty and was re-queued.

## Cause

pytest prints a non-ASCII parameter id escaped: `[390-844-delayed-\uc9c0\uc5f0]`. `test/known_failures.py` turned every `\` in a reported node id into `/` so that Windows paths would match. That also rewrote the escape to `/uc9c0/uc5f0`. `land_checks.main_red` and the LOAD-FLAKY alone rerun pass these ids straight back to pytest. pytest found no such parametrisation (`ERROR: not found`, exit 4). The landing treated that as "no verdict" rather than main's failure.

You only see the problem when a parametrised test has a non-ASCII id and also fails. The same id works in the first run because there it is only printed, not passed back to pytest.

## Fix

`known_failures._posix()` converts separators only in the file part before the first `::`. The bracketed parameter id is left unchanged. `test/test_known_failures.py::test_an_escaped_non_ascii_param_id_keeps_its_backslashes` pins this behaviour.

## Evidence

- `.git/rosy-land-wt/land-uiux-account-table-20261104193446.log`: the rerun on main c3f014a6f9 passed the `/uc9c0` form and got `ERROR: not found` for every id.
- 11-09, main 91889eb4c3, model PC: the escaped id `[390-844-disconnected-\uc5f0\uacb0 \ub04a\uae40]` ran 1 test and exited 0. The same id in the old `/uc5f0...` form returned `ERROR: not found` with exit 4.
- On the same main, `test_d283_console_browser.py` and `test_shared_controls.py` passed with the browser tests opted in: 49 passed on each of the AI PC, model PC and site PC. So the d283 stops were main being red on 11-04, not a flaky test.

## Next time

- Any tool that reads node ids from a report and reruns them must keep the bracketed part unchanged. Check with an id that contains a backslash escape and a space (`연결 끊김` → `\uc5f0\uacb0 \ub04a\uae40`).
- When `main check gave no verdict` repeats across branches for the same test, suspect the rerun's id first, before blaming the branch.
