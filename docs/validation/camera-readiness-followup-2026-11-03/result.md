# Camera readiness and software follow-up — 2026-11-03

This freezes the evidence available before the integrated publication qualification. The date is Korea Standard Time; the camera backup below uses UTC. It follows the [original camera recovery](../camera-readiness-rebind-2026-11-02/result.md).

## Camera recovery after USB reconnection

All four external camera device paths had disappeared, kernel logs recorded USB disconnects, and the observations stopped advancing. Top and side returned first; both wrist cameras were still physically absent. A later read-only query found all four registered devices present and fresh.

The stopped readiness baseline's saved character-node identities differed from the re-enumerated devices, a mismatch the readiness engine rejects. Both cameras' original control values still matched by readback. Under the existing cell and updater locks, the operator wrapper verified idle ownership, preserved the old profile/environment/state, and created a new baseline through the existing readiness engine. It did not edit the old identity record to suppress the guard.

The executed engine is the immutable snapshot from landed commit `cbfb144767f424f9e082c038fad54f94874ed9a3`, also used for the original recovery. Its camera-readiness source SHA-256 remains `c0600495e69d283c8e6fbf6c6bf00220851c8ad2aaedd13f2b40fb42ebfc0b78`. No new product source or global release pointer was installed during this recovery.

| Check | Observed result |
|---|---|
| Registry/environment mapping | All four configured roles matched their persistent paths |
| Device ownership | Four distinct character devices, one expected producer per role |
| Readiness start | READY with fresh/NORMAL top and front observations |
| Stop | Controls matched the saved originals by readback |
| Restart | READY again; configured top/front producer identities unchanged |
| Independent follow-up | Three unexpired READY samples; all four camera sequences advanced in every sample |
| Motion authority | `motion_admitted=false`; no arm or Pinky commands |

The preserved site backup is `camera-readiness-migration-20261102T161343Z`. The operator-private receipt is `camera-readiness-rebind-20261102/reconnect-verified-20261103.json`, SHA-256 `7da824933463e40b674a3e0c70e2440adb578b654447d9d9cb2b849b095cbb17`. Filled configuration and device identities remain private. The existing [baseline migration lesson](../../solutions/runtime-errors/omx-camera-readiness-preview-active-before-owning-camera-2026-10-23.md) supplied this recovery sequence.

READY here is photometric readiness for the configured top/front pair; freshness and ownership were independently checked for all four roles. The four-role owner comparison covers the three independent samples; the start/stop lifecycle compared the configured pair. These timestamps describe host capture/read time, not synchronized exposure. Camera-to-arm geometry, repeated picks, loaded-joint safety and Pinky re-parking were not tested. A reboot or another USB reset/updater transition was not exercised. The earlier no-supervised-motion constraint remains in effect.

## Software regressions

The following are committed branch checks, not claims that an integrated release was tested or deployed. Reports live in the operator's external scratch directory.

| Change | Executed source evidence | Result |
|---|---|---|
| Preserve observation failures instead of reporting an empty source | Commit `5eff2fd4d0`, automatic carry and pick suites | 59 passed, no skips; NEW/known/flaky 0 |
| Corresponding reviewed carry record | Commit `74fa035912`, identical source plus task log/index | Independent review: no findings |
| Share map geometry work outside the Fleet request loop | Commit `9f666845e8`, three mapped invocations | 328 passed/28 skipped; 4676 passed/188 skipped/5 passed subtests; 7550 passed/585 skipped; each NEW/known/flaky 0 |
| Final Fleet documentation head | Commit `b0360e7fbe`, lane-progress and module-structure suites | 58 passed, no skips; NEW/known/flaky 0 |
| Require actual FULL publication proof | Commit `f8fdc85890`, seven publication/landing suites | 318 passed, no skips; NEW/known/flaky 0 |
| Final proof documentation head | Commit `d98d5a5082`, harness/document placement/public provenance | 132 passed, no skips; NEW/known/flaky 0 |

The carry RED commit `314f571ea0` failed both observation-error cases. The Fleet RED commit `ec040ca3c5` failed three responsiveness/reuse cases. Publication RED commits `b1cf199195` and `d4ed8d5348` failed three and four cases respectively, including new code after preparation and replaced log contents. The corresponding final sources passed independent review.

The Fleet change preserves current robot poses per request; its deterministic tests are not a real-load latency bound. The skipped tests in mapped suites do not establish browser or ROS runtime acceptance. The publication proof tests include qualified fixtures and rejection of the historical PR #227 candidate; they do not themselves constitute a FULL run of the integrated product.

## Publication boundary

A previous `--no-cache` FULL on commit `154a7e6ef6` completed its body, but used the old writer that discarded the execution mappings required by the new verifier. Its later main-delta run was stopped by its owner; completed reports were preserved and the interrupted job returned 143. It is not publication proof for these fixes and is not retroactively upgraded.

Before publishing, verify that the selected candidate includes commits `74fa035912`, `b0360e7fbe` and `d98d5a5082`, then use the current canonical FULL path and its per-SHA execution record. The same head still needs independent review and green public CI. Record those later results against that exact SHA in the landing record and publication PR; do not infer them from this checkpoint.

CE: the existing [FULL publication lesson](../../solutions/workflow-issues/own-full-landing-to-publish-wasted-hours-2026-11-02.md) was corrected. The camera recovery reused an existing documented migration; the two runtime fixes are explained by their source and regressions.
