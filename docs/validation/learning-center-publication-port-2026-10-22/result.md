# Learning Center publication-source verification

## Scope

The shared center targets multiple robot kinds and instances in one existing Account Learning
project. OMX is the first concrete learning adapter. Model and AI are execution resources,
not robot kinds or new projects. D-840 and the deployment plan record this distinction.

The publication branch is `feat/fleet-learning-center`, based on public `origin/main`
commit 4c0504cbd4b1becf94b13828bc5e0a69c18fc04d. The prior development branch is preserved;
its unrelated unpublished platform history was not imported.

## Committed remote evidence

All pytest and Chromium executions below ran through `tools/remote/remote_pytest.py`,
not on the development PC. Each terminal log was compared with `test/known_failures.py`.
Logs are external workspace artifacts under the respective named log directories.

| Source commit | Log directory | Result and limit |
|---|---|---|
| commit `b2af171cc57cf28ca680bc862398bcf8a8a994dc` | `learning-publication-release` | New Fleet collection failure exposed an invalid package import; fixed using the public flat module layout. |
| commit `b2af171cc57cf28ca680bc862398bcf8a8a994dc` | `learning-publication-backend` | A new snapshot/count consistency failure was fixed. This run is not green evidence. |
| commit `b2af171cc57cf28ca680bc862398bcf8a8a994dc` | `learning-publication-browser` | Selected full Learning, OMX, accounts, camera, SIM, pipeline and shared-shell Chromium invocation exited 0; no skips observed. This is the earlier UI source, not the later reader transport fix. |
| commit `1d9bce11ac9e29dcef488ce4126b2367c9cc5468` | `learning-publication-release-final` | 258 passed, zero skipped, two dependency deprecation warnings; failure comparison: zero new. Covers Fleet launcher, navigation, official review installer, signed model-code closure and browser-scope selection. |
| commit `1d9bce11ac9e29dcef488ce4126b2367c9cc5468` | `learning-publication-backend-final` | 2,366 passed, 78 skipped, one failed. The failure was a new HTTPS test fixture assuming a particular stdlib internal context representation; subsequently corrected. Skips are not acceptance evidence; this log did not preserve their reasons. |
| commit `1dd36577a5f97eb559b7dc52a468255834ae3925` | `learning-publication-transfer-green` | All 28 transfer tests passed, zero skipped; failure comparison: zero new. The fixture now checks effective certificate/hostname verification and supplies complete HTTP response metadata. This resolves the identified full-run failure without claiming a rerun of the entire suite. |
| commit `1dd36577a5f97eb559b7dc52a468255834ae3925` | `learning-publication-browser-final` | All 18 affected Account, pipeline, center and review-playback Chromium tests passed, zero skipped; failure comparison: zero new. This rechecks the later backend/reader integration source. |

The retained-unit regression also found different center/collaboration option ordering on
roundtrip; the official installer's generated unit order was stabilized and is covered by
the green 258-test run. Independent scoped reviews found the Account scoped-cookie
authorization defect, protected-origin transfer mismatch and web/learner interpreter
preview mismatch; each was corrected with regression coverage.

The preview reader now uses the configured ACT Python, a fixed trusted module/cwd,
offline hub settings, 64 KiB input, 30-second execution timeout and kernel-bounded
12 MiB output. Existing source revision, exact episode/frame row and image-size checks
remain. This verifies software behavior, not a real field episode or physical camera sync.

## Remaining acceptance

This work did not activate a production Fleet image or change existing protected services.
Signed CI image creation/activation, controller provisioning, host-specific Account clients,
the same actual project binding on both hosts, real user/HF consent and the AI lab resource
exclusion remain deployment acceptance items in the plan.

The generic robot/device/participant/task identity flow and incompatible-group rejection
still need end-to-end acceptance. Existing OMX arm profiles are not a general robot registry.
Host-side HIL-SERL updates are not proof of a connected device actor, live intervention,
reward/reset behavior or physical learning. SIM execution requires its separately trusted
runtime. No new device motion, policy activation or automatic cross-host catalog sync is
claimed.

See [D-840](../../adr/D-840-shared-multi-robot-learning-center.md),
[D-832](../../adr/D-832-omx-learning-workspace-and-multicamera.md) and the
[deployment plan](../../plans/2026-10-22-fleet-learning-entry-deployment.md).
