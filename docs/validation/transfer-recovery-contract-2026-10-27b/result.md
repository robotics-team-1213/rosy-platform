# Recovery contract version alignment — 2026-10-27

Follow-up to [focused contract evidence](../transfer-recovery-contract-2026-10-27/result.md).
The earlier focused GREEN did not include the canonical version-table alignment test.

The official FULL attempt on `b5dcb04ce6` did not land: its collect-alone guard found
`middleware/core/gateway/test/test_protocol_version_alignment.py::test_changelog_has_a_row_for_the_live_version`
failing because the API Ref header and section said v1.327 while the final changelog table
had no `| v1.327 |` row. The isolated guard retry reproduced the same assertion.
This is an owned documentation omission; the failed/incomplete FULL is not acceptance evidence.

Fix `6645ad829bb1ae8e31de1df6b4215103fb7fb522` adds that one table row.
It changes no model, runtime code, test assertion, baseline or quarantine.

```powershell
python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-recovery-contract-alignment-green" -- contracts/foundation/test middleware/core/gateway/test/test_protocol_schemas.py middleware/core/gateway/test/test_protocol_version_alignment.py operations/fleet/test/test_development_session.py operations/fleet/test/test_lane_route.py operations/fleet/test/test_mission_progress.py operations/fleet/test/test_task_contract_docs.py test/test_line_follow_contract_docs.py
python test/known_failures.py "$env:TEMP/rosy-recovery-contract-alignment-green/run-1.txt"
```

Remote result on the committed fix: **1,586 passed/0 skipped**,12 warnings,22.41s,
runner/classifier0, NEW0/known0/flaky0.
The existing observed alignment RED is the regression proof; no duplicate test was added.
Incomplete FULL logs are preserved outside the repository in
`%TEMP%/rosy-recovery-contract-incomplete-b5dcb04/`.

Official FULL must run again before landing. This record proves focused schema/version alignment;
it proves no HTTP installation, producer, browser behavior, physical task or learning acceptance.
CE: 해당 없음 — the existing independent version-alignment test explains and guards the correction.
