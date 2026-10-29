# Authenticated simulation recovery HTTP and console — 2026-10-27

This record covers source integration with synthetic World observations and an SDK fixture. It is not deployment, a Gazebo producer installation, physical-device acceptance, or model/VLA training evidence. Official local landing is a separate pending gate at the time this record was written; no push was performed.

## Behavior verified

The original proposer requests recovery for an exact retained source. A separately authenticated observer provides two new reset observations. A different named operator approves the exact request, proof and generation. Current Account authority is checked inside the child-creation transaction. One root can create only one child; the original failure remains unchanged. Public responses contain the filtered job and bounded owner-reported review, never an execution grant or inferred physical failure cause.

Expired or replaced evidence, a changed task assessment, stopped/current-generation mismatch, body actor spoofing, wrong observer credentials, and cross-origin writes are rejected. Concurrent approvals and historical exact replay return the same child. The HTTP regression reconstructs the service on the same journal with the startup fence closed and SDK offline, then verifies same-child replay without an additional submission. Real Account manager PATCH disable/grant revocation blocks a new child but preserves historical reads.

The console separates original failure from child outcome and visibly labels simulation. It does not automatically resend a failed/unknown write. A lost approval reply followed by a child-read 503 preserves known ID and consumed budget; later read shows the same child's synthetic physical completion. Independent proposer and operator pages use their own credentials. The browser never receives observer credentials or asserts clearance.

## Source and remote runs

All Python/Chromium execution below used the official remote runner on committed source. No laptop pytest or product browser run was used.

| Source commit | Selection / log directory under system TEMP | Result |
|---|---|---|
| `2addc3cd56` | new current-authority tests; rosy-recovery-auth-red | RED 5, missing lookup method |
| `543a7c210a` | new auth + existing Account/password suites; rosy-recovery-auth-green | 109 passed, zero skips |
| `be3acf9914` | recovery HTTP acceptance; rosy-recovery-api-red2 | RED 6, missing routes |
| `0b5a08df7b` | HTTP + request service + observer + recovery flow; rosy-recovery-api-green2 | 37 passed, zero skips |
| `61f1e0f169` | new API/auth; rosy-recovery-api-authority3 | 17 passed, zero skips |
| `61f1e0f169` | actual recovery and existing ARM browsers; rosy-recovery-console-green2 | 14 passed, zero skips |
| `7630dbb300` | 17 transfer/evidence/recovery suites + applications/fleet/test + existing Account/password; rosy-recovery-public-broad | 453 passed, 35 skipped |
| `b59cd2182a` | final API/auth including HTTP reconstruction; rosy-recovery-api-final | 18 passed, zero skips |
| `88eb429814` | actual browser with valid worst-width child ID; rosy-recovery-clipping-red3 | RED 1 at 320px, child right 309.75px > card right 308px |
| `477761474d` | final recovery and existing ARM browsers; rosy-recovery-visual-fit | 14 passed, zero skips |

The broad run did not enable opt-in browser execution; its 35 skips are not acceptance evidence. Dedicated Chromium runs above actually executed. Every listed GREEN runner exited 0; the final/broad reports were compared with `test/known_failures.py`, NEW0/known0/flaky0. Warnings include existing Starlette/httpx and process-fork deprecations. Fixture setup failures before the useful REDs and earlier failing UI runs are preserved in external scratch and are not acceptance evidence.

The reproducible final browser command was:

```powershell
python tools/remote/remote_pytest.py --log-dir "$env:TEMP/rosy-recovery-visual-fit" -- ROSY_RUN_BROWSER_TESTS=1 operations/fleet/test/test_transfer_recovery_console_browser.py operations/fleet/test/test_arm_transfer_console_browser.py -s
python test/known_failures.py "$env:TEMP/rosy-recovery-visual-fit/run-1.txt"
```

API/auth used the same runner with the two explicit test_transfer_recovery_api.py and test_transfer_recovery_auth.py paths. Exact expanded broad arguments are retained in its run-1.txt. Native final landing must run its own current selection rather than substituting these focused results.

## Actual visual evidence

Six remote Chromium PNGs were retained in the test-PC artifact store, fetched byte-for-byte into external system TEMP under rosy-recovery-public-screenshots/477761474d, and checked against the hashes printed by the committed test. The actual 320px, 390px and 1920px images were opened and inspected. These are captured console pixels, not a mock or generated image.

| Captured case | Integrity |
|---|---|
| 320px normal and lost reply | SHA-256 `bdb15cc2076ef0d27b0a67402859186bb304459e88d22b709a0040799770d004` |
| 390px normal and lost reply | SHA-256 `2f401b83bd83e89a63d61cd8e43274d7e58ee8ccf867f02916f1e922cdd3e9bb` |
| 1920px normal | SHA-256 `8d68784278dd19c22de209a3c4d2c4808dec7ec7f465da676f5ee14134f5f0a7` |
| 1920px lost reply | SHA-256 `fa192fee0139c69ece2e02560bc31af51096111da832d77ffead69a66c47c49d` |

Normal/lost narrow captures can be identical because both end at the same retained failure and fixed wide-ID child result; the behavior branches are asserted before capture. Root-page, element-overflow and visible-ancestor bounds are independently checked. The regression and [lesson](../../solutions/logic-errors/page-overflow-guards-miss-clipped-child-identifiers-2026-10-27.md) explain why the page-only assertion missed clipping.

## Review and source checks

Five read-only simplification passes: reuse/quality/test-value no findings; eager pending-parent materialization removed; two redundant source comments/docstrings removed. The proof assertions remained intact. No project typecheck is configured for this Python/vanilla-JS scope. Node syntax and the existing ARM admission unit passed. Impeccable detector returned an empty finding list; no new assets, tokens, stylesheets or dependencies were introduced.

Independent contract review found no supported Critical/Important issue. The Minor missing simulation label was fixed and re-reviewed through source commit477761474d with no supported regressions. The real HTTP reconstruction, unknown-reply and narrow-ID assertions were included in follow-up review. The separate visual finish reviewer opened all six captures and returned `disposition: ship` for this existing-console extension, with no material fixes. This is a source/visual review, not independent device safety certification.

The read-only shipped documenter compared the extension with incumbent PRODUCT/DESIGN, tokens, components and all six captures; no durable design-system change was needed or made. It correctly noted that final confirmed-child captures cannot independently prove the earlier lost-result state. The actual browser assertions and logs establish that intermediate behavior; the PNG labels identify the tested branch, not a screenshot of its intermediate error.

CE: new lesson recorded for ancestor clipping missed by page/element overflow guards; parser-safe frontmatter, code links and local RED/GREEN verified. Vocabulary scan found no new domain term; incumbent CONCEPTS.md and DESIGN.md are preserved. Mechanical claims flags for local-only source commits were intentionally adjudicated: no public PR is authorized and no published/landed claim is made here.
