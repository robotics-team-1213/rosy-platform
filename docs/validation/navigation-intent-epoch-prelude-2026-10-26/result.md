# Navigation intent epoch preservation — D-890

Source verification only. This record does not claim runtime fence advertisement, mandatory public pairs, idle-cancel revocation, managed qualification, deployment, or device acceptance.

## Revisions and scope

- Tests-only RED: commit `0916d397f4e2a345727c0dfd161824c7be6d4087`, based on actual main commit `cb0b71b2e66be8e7cfd73de626fe184745de9907`.
- Reviewed implementation: commit `56d948bb92fac95e7f4809a89f8b79851e80cd80`, tree `bca9412e3340740afb6e54fcf247c18f45f374b8` independently approved by admission_arch_v1 with a genuine Safety-Review trailer.
- Tested GREEN: commit `959ec51bbffcec510df43a404ef4fa11edabfcd1`. Its only delta from the reviewed implementation is two declarations for concurrent D-888/D-889 reservations in adr_gaps.txt. No production or test changes.

Foundation accepts optional strict caller boot/generation fields for navigate/home only. CORE Home forwards them into existing HomeRequest/reservation/native checks. Fleet navigate explicitly rejects either supplied key before resources, admission, Task creation or dispatch because its traffic interface does not preserve that pair. The canonical version constant is registered and re-exported without advertising runtime support. API v1.323 and all nine pins selected by the official bump tool were updated; prior API history and Monitoring exports remain intact.

The Foundation FULL trigger is separated from the later navigation product change. The CORE and Fleet consumer bindings must accompany this contract: accepting fields while dropping them would expose an invalid execution path. No ROS IDL, lease/UI changes, new dependency, or feature flag is added.

## Committed-revision remote runs

All runs used the official remote runner through the existing qualified-lab wrapper. Each launch first checked the operating storage policy (at least30GiB available and less than90% used). No laptop pytest or site/robot tests ran. The wrapper qualified model/AI hosts only. Raw evidence is outside Git under `%LOCALAPPDATA%/Temp/rosy-admission-prelude/`; sibling `rosy-prelude-<phase>-<group>-runner.txt` preserves source, selected host, command and official exit. Each run was classified by `test/known_failures.py`.

| Phase/group | Observed result | Official / outer / known exits | Classification |
|---|---|---|---|
| RED Foundation | 21 FAIL,0 SKIP | 1/1/1 | NEW21,known0,flaky0 |
| RED CORE | 2 FAIL,0 SKIP | 1/1/1 | NEW2,known0,flaky0 |
| RED Fleet | 12 FAIL,4 PASS,0 SKIP | 1/1/1 | NEW12,known0,flaky0 |
| GREEN Foundation | 1318 PASS,0 SKIP | 0/0/0 | NEW0,known0,flaky0 |
| GREEN CORE | 25 PASS,0 SKIP | 0/0/0 | NEW0,known0,flaky0 |
| GREEN Fleet/pins | 109 PASS,0 SKIP | 0/0/0 | NEW0,known0,flaky0 |

RED failed on the missing canonical constant and the existing UNKNOWN_FIELD grammar rejection. CORE received400 instead of409; Fleet did not yet reach its final dispatch checks. These are not standalone execution proof of Home body loss or Fleet side effects. The final GREEN checks real CORE invalid-boot/generation rejection with unchanged owner/mode/send0, followed by the same valid original pair succeeding with kind=home/send1. It uses the real service/native admission path without idle cancel or mocking native.expect. Fleet tests cover direct robot dispatch, public step with/without Task service, and the Task branch; supplied single keys and complete pairs are rejected without effects, while no-epoch controls still dispatch. The independent source review traced both consumers.

GREEN selectors: all `contracts/foundation/test`; CORE `test_intent`, `test_intent_home_epoch`, `test_protocol_version_alignment`, `test_v1_import_boundary`; Fleet `test_intent_navigation_epoch`, `test_development_session`, `test_lane_route`, `test_mission_progress`, `test_task_contract_docs`, plus root `test_line_follow_contract_docs`. The two CORE/Fleet warnings are existing FastAPI/Starlette HTTPX and anyio deprecations, not skipped tests.

| Raw run | SHA-256 |
|---|---|
| red-foundation/run-1.txt | sha256 `1abbb86700fa172c74b67deaa352147b0a823e31dad84b0be3f20a4f84dd4902` |
| red-core/run-1.txt | sha256 `e371d667d9fdc08d08649cd734647d98275ebc0a7f5bf5d10a362b7079d36bf9` |
| red-fleet/run-1.txt | sha256 `752d120b47e5dab6105b69c94115f474963076b8fcf414e6958f926fac083257` |
| green-foundation/run-1.txt | sha256 `64e5f919a11aaf8dcb53a9a307dcb953e913a8f4ee3897a5d4fdaac232061068` |
| green-core/run-1.txt | sha256 `37ae80b01a5df92a89c297d1aa12d6ba79532dc63c791fcaacc063cfd514e8d4` |
| green-fleet/run-1.txt | sha256 `ac3f407973c889b1f1673c1fa028515f568ffdfcc0a603493399f764b0de6b25` |

## Static checks and limits

Source D-766 range checked all three commits successfully. Lint initially identified the two concurrent missing ADR gaps; after their explicit declaration it reported0 errors/36 warnings. Final documentation checks and official FULL landing remain pending at this record's creation. Focused results do not replace that gate or public CI.

CE: 해당 없음 — permanent source bindings, stateful regression controls and D-890 retain the reasoning. The existing Git-ID validation lesson was applied to this record; no additional lesson is needed. Pinky devices remain off and the common UTC precision threshold is not accepted by these tests.
