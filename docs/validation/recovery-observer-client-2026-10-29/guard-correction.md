# Observer fixture packaging correction

This supplements [the frozen functional result](result.md); it does not rewrite the earlier 53 passing cases as a successful complete landing.

The first official native preparation stopped on `test_no_secrets_in_tracked_files`. Its branch-isolated rerun failed identically and its exact main-base rerun on commit cb72913972 passed. The source was the new CLI redaction test's fixed invalid-credential input, not an actual deployed credential or production behavior. No child was dispatched or external service accessed by this check.

An intermediate correction at commit c1572fbdf5 reused a slice of the existing fake observer fixture. The scanner still rejected that assignment expression. Reading its source established that code-reference exemptions are deliberately narrow, while explicit angle-bracket placeholders are already accepted. No scanner rule, exception, provenance allowance or failure baseline was changed.

Final test-only commit 8728fc6eb7d9cc6257f7fbe747ba3b81d52d98eb uses an explicit short invalid placeholder. It still fails the client credential minimum and the unchanged assertion still checks that stderr does not contain the supplied input. Independent read-only review confirmed this intent; the production client remains the implementation reviewed at commit afa10f26b2.

On commit 8728fc6eb7, the official remote invocation of the entire client suite plus the exact tracked-secret guard completed with exit 0: 36 passing progress symbols, no skipped or failed cases. `test/known_failures.py` returned exit 0, NEW 0. The repeated quiet option suppresses a normal pytest count line; counts are derived from completed progress, not summed with the overlapping earlier 53-case run.

The obsolete longer c1572fbdf5 correction run also eventually finished and reproduced the same guard failure. There are no standalone correction test processes left waiting from these runs. The original native failure was preserved before restart; its private transport details remain outside the repository.

| External system TEMP artifact | SHA-256 |
|---|---|
| `rosy-recovery-observer-owned-guard-failure/rosy-recovery-observer-land.txt` | `c8c2bc78ca18d8895ce68ab844bdccdee33699c40c719fec23f1bab063653fad` |
| `rosy-recovery-observer-guard-fix-short/run-1.txt` | `4640438616a7266678ce3944acc943b791524c2039c6b8e7495496a6788a7c5c` |
| `rosy-recovery-observer-guard-verified/run-1.txt` | `9c5e06c8cc878b62fdfbc97fb1b7e2422d64894af7d6d287e8972c358d1c050b` |

Official local-main integration is restarted after this verification. Its eventual ancestry and workspace cleanup belong in the workspace integration record. No actual producer installation, human labels, training or field acceptance is established here.

CE: not applicable. The existing scanner documents its narrow references and explicit placeholder syntax; this test, its unchanged assertions and this failure/correction record preserve the reason without a duplicate lesson.
