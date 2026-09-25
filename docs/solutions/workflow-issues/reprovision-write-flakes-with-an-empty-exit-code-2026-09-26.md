---
title: An empty writer exit code in the reprovision test is a known flake, not your change
date: 2026-09-26
category: workflow-issues
module: test/test_sd_writer_contract.py, deploy/sd/prepare-rosy-sd.ps1
problem_type: workflow_issue
component: development_workflow
severity: low
symptoms:
  - "test_reprovisioning_reuses_the_stored_core_api_credential fails as 'image writer failed with exit code ' with nothing printed after 'code'"
  - "the same failure line carries stage=write card_state=writing"
  - "rerunning the single test passes often enough that a green rerun looks like a fix"
applies_when:
  - "a host pytest run fails inside test/test_sd_writer_contract.py on Windows where PowerShell is available"
  - "a full-suite green has to be judged while this test fails intermittently"
tags: [sd-writer, flaky-test, reprovision, prepare-rosy-sd, empty-exit-code]
---

# An empty writer exit code in the reprovision test is a known flake, not your change

## Context
`test_reprovisioning_reuses_the_stored_core_api_credential` (the D-191 contract that a rewritten
card keeps the stored core API credential) intermittently fails on the Windows host with
`image writer failed with exit code ` — a message whose exit code is *empty* — followed by
`stage=write card_state=writing`. The full-suite run of 2026-09-25 failed the same way
(`X:\DevTemp\opencode\full_test.log`: `AssertionError: image writer failed with exit code`).

The empty value is the signature, not a truncation: `deploy/sd/prepare-rosy-sd.ps1` initialises
`$writerExitCode = $null` (line 1008), assigns `$writerExitCode = $writerProcess.ExitCode`
after `WaitForExit()` (line 1147), and fails on `if ($writerExitCode -ne 0)` (line 1148) —
`$null -ne 0` is `$true` in PowerShell, so a null/empty code reaches the fail path with an empty
interpolation. *How* line 1147 can yield null is **not established**; treat that as an open
question owned by the SD-writer lane (D-230 series), not as a diagnosis.

Repro rate on this host: 10 solo runs, 6 failed (~60%) — 4 of 7 on 2026-09-25, and
FAIL/PASS/FAIL across three consecutive solo runs on 2026-09-26. It never reproduced deterministically.

## Guidance
1. Recognise the exact signature (`image writer failed with exit code` + empty value +
   `stage=write card_state=writing`) and stop there: unless the change under review touched
   `deploy/sd/` or the writer contract, the failure is this flake. Do not chase it into your diff.
2. Do not "stabilise" the suite by loosening the assert, adding a retry, or `xfail`ing the test.
   The assert is the D-191 contract; masking it would turn a visible flake into a silent hole.
3. When reporting a full-suite result while this flake is live, quote it explicitly with the
   count (e.g. "1 failed — the known sd-writer empty-exit-code flake, 6/10 solo repro; 2275
   passed") instead of a bare green/red.
4. The repair belongs to the SD-writer lane: instrument line 1147 (log the type and value of
   `$writerExitCode` and whether the `else` write branch at line 1015 was entered) before
   changing any logic. A fix without that evidence is a guess.

## Why This Matters
The flake passes reruns, so an unqualified rerun-green reads as "fixed" and burns the next
session's time re-diagnosing a failure already seen three times. Recording the signature, the
code path and the measured repro rate turns an unexplained red into a one-line adjudication.

## When to Apply
- Any `test/test_sd_writer_contract.py` failure whose message matches the signature above.
- Judging `python -m pytest test/ -q` green while the SD-writer lane has not landed a fix.

## Examples
- 2026-09-26 solo runs: `FAIL (empty code) / PASS / FAIL (empty code)` — three consecutive runs
  of the single test, no other change in between.
- Message shape from `full_test.log`:
  `AssertionError: image writer failed with exit code` + `stage=write card_state=writing`.
- Offending lines: `prepare-rosy-sd.ps1` 1008 (`$writerExitCode = $null`), 1147 (assignment),
  1148 (`-ne 0` check that fires on `$null`).

## Related
- `docs/solutions/workflow-issues/card-readback-slows-under-parallel-cpu-load-2026-09-25.md`
  (same SD-writer surface, different failure: load, not exit code)
- `docs/solutions/workflow-issues/long-elevated-card-write-needs-liveness-and-one-verify-2026-09-23.md`
  (writer liveness, the stall branch next to line 1148)
