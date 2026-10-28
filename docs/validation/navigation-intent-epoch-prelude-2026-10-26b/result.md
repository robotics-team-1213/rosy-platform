# D-890 first FULL failure and Gateway seam classification

This follows the [initial focused evidence](../navigation-intent-epoch-prelude-2026-10-26/result.md). Those results remain unchanged. This record does not claim FULL success, landing, public CI, deployment or device acceptance.

## First official FULL

Candidate commit `c2ae9f884aec9e4c22597611f95d5f6cab151724` ran the official29-invocation FULL pretest over main commit `cb0b71b2e66be8e7cfd73de626fe184745de9907`. Guard was287PASS separately. Across29 invocations the raw summaries contain1FAIL/34989PASS/2235SKIP, with overlapping test coverage between invocations. Opt-in browser groups26–29 actually ran:138/127/214/164PASS, all0SKIP. The classifier produced28 clean invocation verdicts and oneNEW1 verdict; the separate guard was also clean. No LOAD-FLAKY waiver occurred.

The failure was `test/test_behavior_test_ownership.py::test_external_behavior_tests_match_the_frozen_set` in run-pre-23:1FAIL/11169PASS/1214SKIP. Its exact assertion was new=`middleware/core/gateway/test/test_intent_home_epoch.py`, stale=empty. The official isolated candidate rerun also failed1/0; the sameID on actual main commit `209dbf98b34e2dc469b4c4735c45a5c134eea080` passed1/0. This is a branch failure, not MAIN-RED or a known failure. The native official actor ended exit1 before landing. Brief SSH polling retries during browser jobs recovered; no incomplete invocation remained.

The first run's34raw files (29invocations, guard, lint and isolated/main controls), console and separate known verdict were copied before retry into `%LOCALAPPDATA%/Temp/rosy-admission-prelude/first-full-c2ae/`. Every source/copy SHA-256 matched. Important preserved hashes:

| Evidence | SHA-256 |
|---|---|
| console.txt | sha256 `632f4c32304b01eb12b71bafe65fbe948bd534b9f3ea2de925545cd9406835d6` |
| raw/run-pre-23.txt | sha256 `8810f96fafd2ad8360b7f4f61993320d491bf8a257f0cf9c8e9ba5a5f494842d` |

## Cause and minimal correction

The scanner matches the test's direct `core_features.waypoints.Waypoint` fixture import. D-184 §2 permits CORE public-contract tests. Independent admission_arch_v1 traced the real core_client/CoreServices/HTTP `/do`/HomeRequest/reservation/native.expect path and confirmed Gateway ownership. The test checks invalid boot/generation refusal before owner/mode/backend mutation and a valid original-pair Home success control. It is not a pure feature-manager branch test. Existing exact entries for real HTTP/native seams provide the same placement pattern.

Commit `e18c084879f3ebfaefeeb591c73c4b344b1ea9c8` adds only this exact path and its public-seam reason comment to the existing frozen classification. Regex, scan roots, set equality, stale detection and the Home test itself are unchanged. Imports are retained; no shim/reexport hides the dependency. No production file, known-failure registry or broader allowance changed.

## Committed correction verification

The existing qualified-labs wrapper checked fresh operating disk policy before the official remote run at commit `e18c084879f3ebfaefeeb591c73c4b344b1ea9c8`. Selectors were the same ownership guard plus `middleware/core/gateway/test/test_intent_home_epoch.py`. Result:3PASS/0SKIP; official child0, native outer0, known classifier0; NEW0/known0/flaky0. Native session74112 was observed closed0. The two existing FastAPI/Starlette deprecations remain. No laptop pytest ran.

Raw `%LOCALAPPDATA%/Temp/rosy-admission-prelude/ownership-green/run-1.txt`, sibling runner and known.txt retain the exact source/command/exit/verdict. Run SHA-256: sha256 `a6a7d7f0bb22280812b93ebba51c1fde87e41f1da6e86ca478f11e079237a139`.

The unchanged production source still needs official integration/FULL landing against the newer main. New arm/wire/UI/Monitoring exports, signed site-tool verification and C2 captureless regression must be preserved. Retained clean invocation cache is managed only by the official gateway; no manual queue/cache/receipt waiver is used.

CE: 해당 없음 — D-184 placement, exact guard comment and this failure/control/verification evidence retain the reasoning. The existing Git-ID lesson is applied; no new duplicated lesson or weakened scanner is needed. UTC precision and Pinky installation remain unaccepted.
