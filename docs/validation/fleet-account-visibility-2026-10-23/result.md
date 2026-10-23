# Account visibility browser regression — 2026-10-23

The account row now stays folded until explicitly opened and folds after successful authentication. Several site-map browser tests still filled the hidden token input directly. A preserved real Chromium run on commit `91f444c8ac381c0c1027b7b4852b51097cf0aa53` was interrupted after **55 failed, 70 passed**. All 55 failures were `Locator.fill` timeouts waiting for `#console-token`; these are NEW failures, not accepted flakes. The interrupted run does not verify its remaining cases.

Fix commit: `24856e823e2f7f8daa99b7d0b4ba2581d9a93c54`. It adds **24** calls to the existing `open_token_access(page)` helper in `operations/fleet/test/test_site_map_browser.py`, including two later cases not reached before interruption. All **35** token fills now follow the helper. The 42 save clicks already follow a fill or explicit opening. Removing only helper-call expression statements yields identical before/after AST: fixtures, assertions and other behavior are unchanged. The fixture keeps the initial row folded, and existing initial/follow-up closure checks remain intact.

Committed remote Chromium verification, with `ROSY_RUN_BROWSER_TESTS=1`, ran these two existing functions across their desktop/mobile parameters: **5 passed, skip 0, NEW 0**.

- `test_mapless_driven_survey_records_unknown_robot_and_confirms_only_a_draft`
- `test_changed_draft_keeps_local_edits_and_conflict_after_reconnect`

The test correction and the complete incoming presentation feature were independently reviewed with no Important findings. Production authentication, role checks, token storage, E-stop gating and command calls retain their previous behavior. This record covers the bounded regression above; the full official landing verification is separate.

External evidence is under `C:/DevTemp/learning-execution-20261023/`: `front-browser-interrupted-full.log`, `front-browser-interrupt-receipt.json`, preserved original/duplicate landing logs, and `front-account-visibility-smoke/run-1.txt`. The interrupted job was matched by revision, checkout, process ancestry and exact pytest arguments before SIGINT. The branch's existing commits and files were preserved. Interrupted/terminated attempts are not passing checks.

| Log | SHA256 | Bytes |
|---|---|---:|
| interrupted original | sha256:9be600c1aa2337a4f12659b60794d92a5d57475fac1dca2e799d2261d67e2469 | 222658 |
| committed browser smoke | sha256:8b0f0973893e837a9f18808b386482b6260a5e531a7154b2e1d71e3a864f8f6e | 987 |

CE: 해당 없음 — 필요한 화면 열기 동작은 기존 helper와 수정된 검사에 직접 드러나며, 별도 교훈 없이 코드·실패 로그·회귀 근거로 복구할 수 있다. 실물 장치·배포·현장 수용을 추가하지 않는다.
