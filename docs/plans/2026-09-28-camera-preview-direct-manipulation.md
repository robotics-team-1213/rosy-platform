# Camera Preview Direct Manipulation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let operators mark the floor quadrilateral on the raw camera frame by touch, pointer, or keyboard and inspect the rectified result without entering eight coordinates by hand.

**Architecture:** Extend D-318's existing Fleet camera view. A source-frame SVG overlay is positioned over the raw JPEG, and its four normalized points stay synchronized with the existing percentage inputs and browser-local profile. Separate controls select raw-area editing or rectified preview; changing corners does not issue a lease on every pointer move. The signed profile, OpenCV operation, raw-frame path, and sighting boundary stay unchanged.

**Tech Stack:** Existing Fleet HTML/CSS/JavaScript, SVG, Pointer Events, Playwright browser tests, D-318 Vision preview lease.

---

### Task 1: Prove the direct adjustment interaction

**Files:**
- Modify: `test/test_fleet_console_browser.py`
- Test the Fleet browser page with the existing synthetic REST/WebSocket fixtures.

**Step 1: Add a failing browser test**

Assert that the calibration controls expose raw editing and adjusted-preview actions; drag a named corner handle and verify its percentage input and source-local storage update; press an arrow key and verify an additional bounded movement; select preview and verify the rectification profile is sent in the Vision lease. Confirm raw-edit mode issues an identity profile.

**Step 2: Run the test and confirm expected failure**

Run `python -X utf8 -m pytest test/test_fleet_console_browser.py -k camera_rectification_direct_manipulation -q`.

Expected: fail because direct corner controls and the raw/adjusted mode switch are not present.

### Task 2: Add an accessible raw-frame quadrilateral overlay

**Files:**
- Modify: `src/site/fleet/fleet/server/web/index.html`
- Modify: `src/site/fleet/fleet/server/web/vision-view.js`
- Modify: `src/site/fleet/fleet/server/web/styles.css`

Add a responsive image stage that sizes from the JPEG's intrinsic ratio and an SVG overlay with four labeled focusable handles. Pointer capture updates normalized corners during touch/mouse drag; arrow keys move the focused point by a bounded percentage step. Update existing inputs, polygon geometry, and localStorage through one shared profile writer. Avoid network requests while a corner is moving. In raw-edit mode issue an identity lease and show the polygon over the source image; in adjusted-preview mode issue the saved profile lease and hide editing handles. Keep both paths source-scoped and retain the numeric fields as a fallback.

**Step 1: Run the focused browser test and confirm it passes.**

### Task 3: Verify regressions and responsive output

**Files:**
- Update: `test/test_fleet_console_browser.py` if a regression is found.
- Update: `docs/logs.md`, `src/site/fleet/logs.md`, progress/index only after verification.

Run the new test, the Fleet browser/dialog suite, Fleet host tests, governance checks, and local Docker viewport capture. Check keyboard access, image-overlay alignment, mobile touch target size, request rate limits, and zero horizontal overflow. Keep real camera, measured calibration, Ubuntu/site, DEVICE, and FIELD gates unchanged until separate evidence exists.

### Task 4: Integrate the verified UI slice

Stage only the plan, UI, tests, and required generated evidence files. Commit the verified change on the feature branch, then cherry-pick into local `main` after checking its current ancestry and preserving unrelated work. Do not push.

## Completion record · 2026-09-28

- [x] Raw-frame quadrilateral can be adjusted by pointer/touch and keyboard; percentage inputs remain available and retain decimal precision across reloads.
- [x] Raw editing requests an identity profile; adjusted preview requests the source-local profile. Dragging does not issue a lease per movement.
- [x] Fleet host suite: 545 passed, 5 skipped. Full browser/dialog suite: 31 passed before the final precision-retention assertion; focused direct-manipulation browser test rerun after final edits: 1 passed.
- [x] Harness generation completed; lint reports 0 errors and 17 freshness warnings. `git diff --check` passed.
- [ ] Local-main integration is the remaining step. Physical camera, measured calibration, Ubuntu/site, DEVICE, and FIELD gates remain outside this local UI change.
