# Camera Preview Final Polish

## Goal

Close the remaining local SOURCE/LOCAL follow-up for D-318's operator camera calibration UI and make the plan/status records agree with the commits already on `main`.

## Scope

1. Reproduce keyboard fine adjustment in Chromium: focused corner handles move by 1% with arrows and 0.1% with Shift+arrow, remain keyboard reachable, and retain the draft after reload.
2. Add a small drag affordance polish if the test/evidence exposes text selection or focus loss.
3. Correct the prior direct-manipulation plan's integration checkbox and record the final-main verification without changing physical/site acceptance.
4. Run focused and relevant host/browser/governance checks; commit and integrate only this validated slice.

## Discovery

The existing direct-manipulation browser test proved ordinary arrow movement but did not prove that focus remained on the handle. Fleet has a document-level roster shortcut for ArrowUp/ArrowDown. Because the SVG handle's target is not a native button element, the shortcut also received an arrow event already handled by the handle, moved focus to a robot card, and made the next fine-adjustment key ineffective. The handle now prevents that global shortcut by having the roster handler respect `defaultPrevented`.

## Verification

- The new 0.1% Shift+arrow assertion failed before the event-propagation fix and passed after it.
- Fleet direct camera, roster-arrow navigation, and map keyboard-goal browser regressions: 3 passed.
- Full Fleet host suite: 545 passed, 5 skipped. Palette contract: 9 passed. `git diff --check`: passed.
- Integrated into local `main` as `2ec41b9a`; append-only logs and generated indexes follow in the documentation closeout.

## Completion boundary

The local camera-editor focus and precision defect is closed. Full product G2/G3 acceptance is not closed: current documents still require operator G3 evaluation, deployed site/TLS and real camera readback, robot/physical E-stop evidence, and DEVICE/FIELD acceptance. Those require a reachable site and physical participants; browser fixtures and Docker demos do not substitute for them.

## Evidence boundary

The current UI tests use controlled browser responses and synthetic frames. They do not establish the phone camera path, surveyed calibration, deployed site TLS, robot/device readback, human G3 acceptance, or DEVICE/FIELD gates.
