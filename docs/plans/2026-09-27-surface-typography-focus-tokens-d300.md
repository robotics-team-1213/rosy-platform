# ROSY surface typography and focus token plan

**Decision:** [D-300](../adr/D-300-surface-typography-and-focus-token-contract.md)
**Status:** Complete

## Goal

Apply the shared typography and keyboard-focus vocabulary consistently to repeated rules in the HMI dashboard, Fleet console, and games board without changing the rendered hierarchy, palette, spacing, or surface layout.

## Steps

1. [x] Add failing surface CSS contract tests for repeated weights, canonical leading/tracking values, and standard `:focus-visible` ring dimensions.
2. [x] Add the regular-weight and outer-focus-offset tokens, then migrate the three surface CSS domains while preserving computed values. Retain only the documented surface-specific exceptions.
3. [x] Append module journals and update web-common/dashboard/Fleet/games progress references.
4. [x] Run focused contract tests, browser-enabled HMI tests, Fleet and games suites, and harness lint/generation. Compare unrelated failures against the base branch without hiding them.
5. [x] Review Fleet and games browser captures at desktop viewport dimensions. Captures are under `X:\DevTemp`.
6. [x] Commit exact changed paths, merge latest `main` into the branch, rerun relevant checks, and fast-forward local `main` if clean. Do not push.

## Acceptance

- Repeated weights, line heights, tracking values, and standard keyboard focus-ring dimensions use shared tokens in all three surface domains.
- Computed visual metrics remain unchanged; unique brand tracking, extended Fleet prose leading, canvas focus offset, and operational active outlines retain their documented treatment.
- Browser review finds no new page errors or horizontal overflow.
- Local source and browser evidence are reported separately from device or field acceptance.

## Verification note

- Surface/token contracts: 40 passed. Browser-enabled HMI suite: 102 passed.
- After latest-main integration `9049bd37`: surface/token contracts 40 passed; browser-enabled HMI suite 102 passed; Fleet and games host suite 636 passed, 5 skipped. The updated API reference v1.40 contract passes.
- Fleet/games browser suite: 17 passed, 2 known Fleet keyboard/queued interaction failures deselected; both reproduce on latest unmodified `main`.
- Harness generation and lint: 0 errors, 17 existing warnings.
- Feature commit: `bb58221b`; latest-main integration commit: `9049bd37`. Concurrent main work accepted D-296 for device-middleware terminology and D-297 for command ACK and Fleet activation, so this surface decision is D-300. Local `main` fast-forward is the final repository integration step.

## Latest-main integration (2026-09-27)

- Integrated latest local main `f4f15776`, including accepted D-296 and proposed D-297; this surface contract is D-300.
- Verification on the integrated tree: D-300 surface contracts 40 passed; HMI web tests 77 passed; Fleet host tests 526 passed, 5 skipped; games host tests 101 passed; site database/task-queue tests 8 passed; harness lint 0 errors and 17 existing warnings.
- The broader gateway/runtime host invocations were interrupted with Windows exit code `-1073741510` before a summary. Scoped HMI, Fleet, games, and site tests completed successfully.
- Browser evidence remains the earlier 17 passed with 2 known Fleet keyboard/queued failures deselected and reproduced on the then-current main. No new browser run or device/field acceptance is claimed for this integration.
- No remote push was performed.

## Latest-main integration (2026-09-27 · 9ca7bc26)

- Integrated main with D-298 for Fleet mission/action/stop terminology and D-299 for the OMX LeRobot boundary. This surface decision is D-300.
- Preserved the new dashboard skip link and Fleet keyboard-focus behavior. Added the shared focus-width token to the skip-link border and extended D-300 contract coverage to common HMI CSS.
- Verification: surface typography/focus contracts 41 passed; HMI web suite 78 passed; Fleet suite 526 passed, 5 skipped; games suite 101 passed; site database/task-queue tests 8 passed; two Fleet browser regressions passed; harness lint 0 errors, 21 existing warnings.
- Visible Chromium preview: `http://rosy.test/dashboard`, 1366×900; page errors 0, document width equals viewport. Screenshot: `X:\DevTemp\rosy-surface-d300-visible-dashboard.png`. The preview uses the local UI and a deterministic mock CORE API; it is not device acceptance.
- One broader gateway/runtime pytest invocation ended with Windows control-C exit code `-1073741510` before a summary. The focused UI and site suites above completed.
- No remote push or device/field acceptance is claimed.
