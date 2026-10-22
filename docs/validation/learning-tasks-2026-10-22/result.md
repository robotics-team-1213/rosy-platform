# Shared multi-robot Learning Center — 2026-10-22

## Implemented behavior

`/learning/tasks` now takes an authenticated project user through robot references,
an immutable task with ordered participants, dataset/method/host selection, execution,
progress, evaluation and model download. Independent arms and cooperative groups have
different validated scopes. Unsupported robot kinds can be registered, but cannot run
through the OMX adapter. Device references are explicitly unverified.

Task identity, robot/model/device revisions, participants, dataset/profile revisions and
actual compute host remain bound through worker requests, continuous experience,
evaluation and model ZIP receipts. Cross-host task export/import preserves dataset
ownership without transferring credentials or automatically synchronizing catalogs.
Existing Account authorization, CSRF, labels and earlier runs remain protected.

## Committed-source verification

All pytest invocations used `tools/remote/remote_pytest.py`, never laptop pytest.
Each green report in the table was compared with `test/known_failures.py`: NEW 0,
known 0 and flaky 0. Initial broader gate failures are described separately below.
Counts overlap across invocations and must not be added together.
The external log name identifies its directory; the file is `run-1.txt`.

| Source commit | External log | Observed result |
|---|---|---|
| commit `f5cb33bda891c15ba8f21917ade7be29925ff811` | `learning-tasks-final-backend` | 2,422 passed, 78 skipped; perception backend, OMX training and curation. |
| commit `f5cb33bda891c15ba8f21917ade7be29925ff811` | `learning-tasks-final-release` | 276 passed; signed closure, official installer, Fleet entry and browser selection. Two dependency warnings. |
| commit `f5cb33bda891c15ba8f21917ade7be29925ff811` | `learning-tasks-final-browser` | 167 passed, zero skipped; actual Chromium against test servers, including tasks, accounts, center, playback and pipeline. Workers are controlled fixtures. |
| commit `930d4b201d0a1c43ebc6877bc73d4555b89b3350` | `learning-tasks-layout-release` | 233 passed after the controller constants were extracted into its installed sidecar. |
| commit `d062ab0caae96d8c7d530955248b9df6d0aedda2` | `learning-tasks-structure-final` | 28 passed; part ownership and document placement. |
| commit `fd889ea429cf33cd4fabb838305a4e9c6405c02f` | `learning-tasks-pinned-model-reviewed` | Model host: 1 passed in 14.14 s; real pinned CPU ACT and HIL-SERL learner check. |
| commit `fd889ea429cf33cd4fabb838305a4e9c6405c02f` | `learning-tasks-pinned-ai-reviewed` | AI host: 1 passed in 11.23 s; the same real learner check. |
| commit `fd889ea429cf33cd4fabb838305a4e9c6405c02f` | `learning-tasks-account-integration` | 30 passed, zero skipped; OAuth, Account and actual Account/task Chromium after the upstream HF merge. |

The pinned test uses the existing isolated LeRobot 0.4.4 environment, synthetic two-arm,
three-camera episodes and two optimizer steps per method. It checks train/save/reload,
nonempty model weights, evaluation frames, two robot references, task/host identity and
the evaluation bytes' SHA-256 in `learning-task.json`. Each test owns a temporary center
and database. Cleanup waits for its workers using their persisted process identities;
an outer driver timeout also invokes cleanup. Environment probes and termination polling
fit within that cleanup's 100-second budget. No candidate app or protected service changes.

These are host learner checks with recorded synthetic experience. They establish neither
a live device actor nor physical online reinforcement learning. The 78 skipped checks
are not evidence of success; that full report did not preserve detailed skip reasons.

Full-suite source `f5cb33bda891` was independently reviewed without remaining findings.
Later changes extract unchanged controller layout declarations, install the sidecar, move
existing architecture string exceptions to their actual owner and add the pinned test.
The test's receipt-envelope mismatch was reproduced on both hosts, then corrected; its
timeout cleanup was strengthened after review. Final source `fd889ea429cf` also includes
published main `9aabe9fdad`'s single HF connection flow. Its scoped delta review found no
remaining required changes. The post-rebase Account/browser regression above verifies
the merged source. Size-range and safety review both passed all 26 unpublished commits;
no new size exceptions were introduced.
Harness generation completed; lint reported zero errors and 31 existing gate-freshness
warnings. These warnings were not cleared by claiming hardware or field verification.

### Report fingerprints

| External log | SHA-256 of `run-1.txt` |
|---|---|
| `learning-tasks-final-backend` | sha256 `6f9faf5afe535347903ea746dd15c44278037d575dc957ca7fa3ebc8eb91dbfc` |
| `learning-tasks-final-release` | sha256 `2b8a0a077135ad8e532185c4a4e5de54aa855eb641627954e8ca7558e650010c` |
| `learning-tasks-final-browser` | sha256 `29c66446a9091c1f2149f91a65c811f5d26934db2ac5b0006670404a15f8550b` |
| `learning-tasks-layout-release` | sha256 `0d12a572bbefbbd7559d4505ef0eaf3362e0fa67c63ac8052ef652cc22c758a1` |
| `learning-tasks-structure-final` | sha256 `9d26e53a3d75858fd982b39d2f18c36e6f33834280708c6213fae3fc59cdadef` |
| `learning-tasks-pinned-model-reviewed` | sha256 `98966a19e9708460ddbb16ceb5e1490bed2898a2fdfd4f2258b42a8ecedd8e89` |
| `learning-tasks-pinned-ai-reviewed` | sha256 `aec80a5ea77a7aa16a6729320dcd9776a28f17bc453abed568e4bc1de655cf4b` |
| `learning-tasks-account-integration` | sha256 `d789576edb07299dbe5949d9f0b38509466e6a302c6ba8cf97582edcd4bb1242` |

## Expanded publication checks and fixes

The first expanded fast/affected run tested commit `139dc53f5d61634ae92d8049b1f365722cd8a9c9`.
It was not fully green: fast contracts had 518 passed and one failure; affected groups
had 4,363 passed/61 skipped, 9,182 passed/951 skipped/one failure, and
619 passed/two skipped/two failures. Every terminal log was compared with the failure
ledger. These were four NEW failures in three causes, not established baseline failures.

The camera alignment renderer was absent from the shared canvas inventory. Commit
`c95916b97d` added it to normal palette/font checks, with no exemption; all 41 checks
passed remotely. The installed Fleet asset test still expected 113 members. Commit
`4a3e753cb9` updated that to 114 and explicitly required `learning.html`, preserving
the full installed-file hash comparisons; all four wheel/sdist tests passed remotely.
The secret scanner correctly demanded explicit integrity context for long document
values. Provenance rows now label their exact values as commit or sha256. No scanner
rule or provenance exemption was changed. Its first follow-up still detected unlabeled
report fingerprints (79 passed/one failure); those labels were then corrected too.

The 4,363-test group finished normally after 942.29 seconds. Earlier observations of
unchanging buffered progress did not establish a hung test. No safety code or process
was changed. A baseline-only suspected follow-cancel test also passed; that alone is
not evidence explaining the broader group's duration.

These late fixes change test inventories and documentation only. Publication still
requires the fast/affected hook and CI at the actual published head; this record does
not assert that the complete expanded gate was rerun green after these fixes.

## PR CI and installed Account gateway follow-up

PR #151 at commit `25cd64dc97cb36171fabf9ae55aac1ab9a9a8599` passed the actual
push hook: fast 519 passed; affected groups 4,363 passed/61 skipped,
9,185 passed/951 skipped and 621 passed/two skipped. Each report compared NEW0.
GitHub CI run `39720000886` subsequently found plain `setup` helper names in the
preview and task tests: apt pytest 7.4 interprets these as nose initialization hooks.
The existing CI dependency guard found the same naming issue. Those helpers were
renamed without disabling that guard, changing fixtures' data or changing test semantics.

Read-only Model deployment inspection also found that the long-running Account gateway
`legacy_review_account.py` was classified as legacy training and held code updates.
The controller now recognizes that gateway only as the actual Python entry script,
including isolated Python flags. Training stays protected, including a training process
whose input argument merely names the gateway file. The Account gateway is not stopped
or reconfigured to get past the update hold.

At commit `18f0277fbaf77e7f62c1db057243a5d08d317b96`, the remote updater/preview/task
regression passed all 251 checks; the existing CI dependency guard suite passed all 29.
The new monitor cases first reproduced two NEW failures before the controller change.
Final PR CI, installed controller identity and actual signed activation must still be
checked at the subsequent publication head. These local-host reports do not stand in
for the failed earlier GitHub CI run. Commit `8d938372a6` additionally passed the
117 remote document, release-boundary and CI dependency checks.

The same initial CI's Fleet browser job found an old four-link work-menu expectation
after the Learning link was added. Commit `2d38309d3a` includes Learning in that exact
menu inventory and verifies its `/console/learning` destination. The four actual Chromium
cases (operator/viewer, desktop/mobile) passed with the rest of their work-filter,
refresh-failure and accessibility assertions intact. This is a test expectation fix;
the production navigation is unchanged.

## Deployment and physical acceptance still pending

This branch is published in PR #151; installation on the official Fleet image is pending. Preserve all
effective base, Workcell and Account Compose overlays during the signed update.
Model's protected Learning service exists; AI still needs its protected origin, central
Account client, the same actual existing project binding and enforced separation from
production inference. Existing prototype services are not accepted product entry points.
Actual user HF consent/provider operations remain unverified.

Installer idle checks refuse active/corrupt center state before mutations. They are a
preflight, not an atomic deployment lock: operators must quiesce new submissions and
experience publishing throughout update/rollback, preserving jobs and artifacts.

Physical acceptance still requires calibrated arms, leader handover, camera timing and
views, bounded actions, reward classification, reset handling and controlled repeated
trials. No torque, grasp, policy activation or robot motion was performed here.

See [D-840](../../adr/D-840-shared-multi-robot-learning-center.md),
[implementation plan](../../plans/2026-10-22-learning-tasks-implementation.md) and
[official deployment plan](../../plans/2026-10-22-fleet-learning-entry-deployment.md).
