# Signed three/four-service site migration

## Scope and source

2026-10-26 KST. Base commit b79265d9fac7022564c704e8296cf184bcda06ef contains the landed pure runtime extraction. Tested final source is commit d4a0e5b96885b6fe4a14469c9177e03ee23b2619 on `fix/site-three-four-image-migration-current-main`. [D-887](../../adr/D-887-signed-site-service-set-migration.md) defines exact authenticated legacy3/current4 service inventories, target-bound Compose/overlays and identity-bound retirement of outgoing PostgreSQL. Builder output remains four services; builder and signing-module blobs are identical to the base. No Robot/Fleet wire version changes.

Independent implementation review by `/root/admission_arch_v1` approved frozen tree `3d656bb2ac`; root reviewed the same verification, stage and rollback paths. The first source commit preserved those four production blobs exactly; subsequent changes were regenerated indexes. The reviewer and root separately approved correction tree `f32fd0b400`: four lines retain `Refused` result reporting, with two narrowly corrected test fixtures. These paths have no Safety tag; no Safety trailer or test/field attestation was inferred from source review.

## Separate committed RED records

All logs below are outside Git under `%LOCALAPPDATA%/Temp/rosy-site-three-four-migration/`. Each named directory contains `run-1.txt` and `run-1-known.txt`; its sibling `<name>-runner.txt` retains the official runner and fresh disk preflight. Rows were not added together or substituted for one another. Every row below ended official child 1 and outer cmd 1, with zero skips, known 0 and flaky 0; NEW equals the failure count.

| Commit | Log directory | Fail / pass | Observed cause and limit |
|---|---|---|---|
| commit bc61f16ea9e6b6e3311f389bcd535e600e1d9301 | `red-real-verifier` | 3 / 8 | Real signatures: authentic legacy3 rejected in both modes; current4 package mode lacks `verified_images`. Invalid sets, bad signature and missing-PG archive controls pass. |
| commit a4a7576377c7090efc21dee3ea98ff352271c8d1 | `red-lifecycle` | 42 / 8 | Initial exploratory fixture wrongly includes hashless manual Fleet in Compose ps. Preserve raw results; these are not uniform migration-failure proof. |
| commit 8c7e075eebc3465f4e5315a198f3100fdfa37112 | `red-current-binding` | 1 / 1 | Manual-free current4 passes; authentic legacy3 specifically fails the fixed PostgreSQL cardinality check. |
| commit 77d8b34bace274e59af8baa992ae7aa553e2c77a | `red-lifecycle-canonical` | 38 / 13 | Correct canonical selector: global inventory retains manual Fleet while Compose ps selects canonical Fleet. Current4 and physical4 controls pass; legacy3, PG residue/identity/fault recovery and missing proof fail. |
| commit 1c0cbb94b3c7fc35ea0c59d47431c15b1d085c9b | `red-overlays` | 1 / 2 | Overlay positive is blocked by legacy3 admission, so this run does not independently prove the overlay defect. |
| commit 9e8e86575f1ce174c16c65ec5e84574855f8a4d0 | `red-overlays-current4` | 2 / 1 | Qualified current4 reaches a successful update without staged target config. Missing target overlay is loaded/switched before restart failure; unsigned coverage control refuses. |
| commit 8e856f02a908f1ad3d750d588dcfe46843196c7f | `red-physical-binding` | 1 / 0 | Forged same-commit physical flag restores OLD despite active NEW; health fails later, after active state has already changed. |

The supplied Compose 5.6.1 baseline distinguishes global Fleet inventory (canonical plus hashless manual) from canonical Compose ps. The fake models that selection and retains actual containers independently of environment/link edits. Lifecycle tests use an explicit trusted-verifier stub and persistent Docker inventory, not real signing. The separate service-set suite exercises real Ed25519 signatures, archive verification and the actual verifier.

## Final GREEN and retained first attempt

Initial source commit 01d7ffdfd2f5727dddbb6cd2f81cc5d7f2968a53 ran all nine suites: 6 failures / 285 passes, no skips, NEW 6, official/outer 1. Preserve `green-focused/` and its runner. Four override cases exposed missing `last_run.result` reporting after moving validation earlier. The pre-OMX direct rollback fixture lacked the complete normal journal and outgoing signed target now required. The inconsistent-journal test incorrectly called the deliberately rejecting loader to inspect preserved evidence. The correction retains refusal before selection/staging, all denial/no-mutation assertions, a complete positive normal journal, and raw journal equality plus explicit loader refusal.

Final committed source ran through the official remote runner with the disk-qualified lab wrapper:

The command example abbreviates the full tested commit above to an unambiguous revision; the original runner logs retain the execution record.

```text
--sha d4a0e5b96885 --
test/test_site_candidate.py test/test_site_candidate_signing.py
test/test_site_candidate_verifier.py test/test_site_candidate_workflow.py
test/test_site_candidate_fetch.py test/test_site_autoupdate.py
test/test_site_service_sets.py test/test_site_service_migration.py
test/test_site_preflight.py -q
```

Actual result: **291 passed, 0 failed, 0 skipped; official child 0, outer cmd 0; known NEW 0 / known 0 / flaky 0.** Quiet output suppresses the numeric summary; counts are derived from all 291 per-case progress dots. Logs: `green-focused-final/{run-1.txt,run-1-known.txt}` and `green-focused-final-runner.txt`. Fresh preflight qualified model (90.124 GiB available, 79.44% used) and AI (130.701 GiB, 70.53%). No site/laptop fallback. `evidence-manifest.json` records SHA-256 hashes of all external run/known/runner files.

Coverage includes real authenticated sets, unchanged current4 builder, complete standalone administrator helper closure, current/staged image and overlay binding, observed active link/environment during staging/load, normal cold rollback with missing/partial/stopped outgoing containers, immutable-ID/hash/image conflicts, manual and volume survival, failed enumeration/inspection/stop/remove/no-op, missing outgoing proof, full incoming health and separate physical3/physical4 relocation phases. Missing outgoing loaded image references leave recovery pending even if accepted-image cache entries remain.

## Limits and CE decision

Source files are 410/534/184/540 lines (verifier/I/O/runtime/updater), below the 570-line pre-split boundary. Reviewed source AST parses, diff checks, source lint and complete per-commit D766 passed; final documentation checks and dry-run are recorded in the handoff. Existing Native/A/C2 refs are retained. This is committed source evidence: no official feature land, helper install, signed candidate rebuild, live migration/rollback, robot access or field acceptance occurred.

CE: 해당 없음. Existing whole-configuration and identical-external-helper lessons were applied. D-887, explicit failure ordering and regression fixtures retain the service-set, physical-journal and manual-selector reasoning; another solved-problem document would duplicate those artifacts. Operational migration remains unverified.

## Official gate format correction

The first official integration at commit `7b2dbeb623` passed its separate 287-test guard, then the related gate reported 1 failure / 1093 passes / 2 skips. The failure was `test_no_secrets_in_tracked_files`: the full tested Git ID in the CLI code block was classified as a high-entropy token. It reproduced alone and passed on main commit `e6e7c47b3c`; the branch did not land. No raw finding excerpt was printed during diagnosis. Git object lookup confirmed commit provenance, and the full source ID remains in the introduction.

Commit `6d493681e4` changes only the command example to an explicitly abbreviated, unambiguous revision. The same committed-revision remote secret guard passed once in 22.14 seconds, official runner and outer cmd exit0; known NEW0/known0/flaky0. Logs outside Git: `format-guard-green/{run-1.txt,run-1-known.txt}` and `format-guard-green-runner.txt` under the same evidence root. The failed first gate and standalone/main checks remain under the official landing log directory. Scanner, allowlist, tests and all four production files are unchanged. Official re-landing, publication and field acceptance remain pending.

CE: 기존 교훈 갱신 — [Git ID 표기 규칙](../../solutions/workflow-issues/git-ids-in-validation-records-need-the-commit-prefix-2026-10-07.md)에 CLI 코드블록 적용과 실제 RED/GREEN 근거를 보강했다. 시간 정밀도나 운영 migration 해결 기록으로 확대하지 않는다.
