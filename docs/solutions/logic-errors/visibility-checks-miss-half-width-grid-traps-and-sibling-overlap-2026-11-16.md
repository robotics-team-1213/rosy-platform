---
title: "Playwright visibility and scrollWidth checks miss half-width grid traps, sibling badge overlap, and FIELD_PROBE desktop density blocks"
date: "2026-11-16"
category: logic-errors
module: console_source
problem_type: ui_bug
component: frontend
severity: medium
symptoms:
  - "Sidebar #robot-overview-list renders at half the column width (~180px), wrapping robot names into three lines and overlapping status badges onto titles while all browser tests pass."
  - "Stale OMX arm items repeat the same freshness timestamp (e.g. 3453초 전) four times across header badge, power, place, and task lines."
  - "Warning queue nests three 4-sided bordered boxes inside .queues-panel.ui-panel."
  - "Applying D-976 desktop compact height (--row-dense / --target-tool) to .map-display .choice-chip fails FIELD_PROBE in test_shared_controls_browser.py."
root_cause: missing_validation
resolution_type: code_fix
applies_when:
  - "Adding or modifying children inside multi-column section headers (.roster-block), rendering compact robot/queue lists, or applying D-976 desktop density tokens to radio choice chips."
tags: [console, layout-geometry, grid-column, choice-chip, browser-evidence]
---

# Playwright visibility and scrollWidth checks miss half-width grid traps, sibling badge overlap, and FIELD_PROBE desktop density blocks

## Problem

On the Fleet Console (`/console`), the sidebar robot list (`#robot-overview-list`), warning queue (`.queues-panel`), and map display toolbar passed all static gates and Playwright browser tests (`expect(locator).to_be_visible()` and `documentElement.scrollWidth <= innerWidth`), yet rendered broken in the live browser: `#robot-overview-list` was trapped in half the sidebar width, `arm_s (S3)` overlapped its `[지연 · 3453초 전]` badge, `rosy-pinky-geg6` wrapped into three lines, `3453초 전` repeated four times per row, and `.queues-panel` nested three bordered boxes.

## Symptoms

1. `.roster-block` in `applications/fleet/web/robot/roster.css` declared `grid-template-columns: minmax(0, 1fr) auto auto` for its title row and listed explicit full-width exceptions (`.roster-summary, .address-drift, #site-path, #discovery-pending { grid-column: 1 / -1 }`). When `#robot-overview-list` was added as a direct child without being added to that allowlist, CSS Grid auto-placed it into column 1 (`1fr`, ~180px), leaving column 2 (`auto`, width of the `로봇 전체 보기` link) blank.
2. Inside that narrow 180px track, `.robot-overview-head` (`display: flex; justify-content: space-between`) pitted a shrinking `.robot-overview-name` against a non-shrinking `.robot-overview-tags`, crushing names into three lines and overlapping badges.
3. `robotProfile()` in `shared/web/robot-profile.js` appends ` · <N>초 전` to every field (`link`, `power`, `place`, `task`) for table cells; `robot-dock-binding.js` concatenated all of them inside one compact overview item alongside the header link badge, repeating `3453초 전` four times.
4. `FIELD_PROBE` in `shared/web/test/test_shared_controls_browser.py` enforced `minHeight >= --target-secondary` (`48px`) on every `input[type=radio]` label (`label.choice-chip`) regardless of viewport, blocking `D-976` desktop fine-pointer density (`--row-dense`: `34px`) on `.map-display .choice-chip`.

## What Didn't Work

Relying on `expect(overview).to_be_visible()`, `document.documentElement.scrollWidth <= innerWidth`, and `patterns.yaml` `import` checks did not catch any of these defects:
- `to_be_visible()` succeeds whenever an element has a non-zero bounding box, even at 50% width or with overlapping children.
- `test_patterns_registry.py` passed because `robot-dock-binding.js` imported and called `createRobotRoster` (C14) on the `/console?view=robots` subview while building a separate imperative card list (`renderOverviewList`) on the main `/console` view.

## Solution

Commit `c4558f1959` fixes both the structural CSS/JS causes and the verification gap:

1. **Universal full-width child rule on `.roster-block`**: Replace the brittle child allowlist with `.roster-block > :not(h2):not(.ui-action-link) { grid-column: 1 / -1; }` on a 2-track header grid (`minmax(0, 1fr) auto`), so any present or future non-header child automatically spans 100% width.
2. **C14 hairline row discipline & 2-column header grid**: Convert `.robot-overview-item` from a 4-sided bordered card to a hairline row (`border: 0; border-block-start: 1px solid var(--border-subtle)`), make `.robot-overview-head` a 2-column grid (`minmax(0, 1fr) auto`) with single-line ellipsis on `strong`, and strip duplicate trailing freshness timestamps from `power`, `place`, and `task` when the header tag already displays the stale age.
3. **Flatten nested queue boxes & align desktop density**: Replace `.queue`'s 4-sided border and `.issue-list li`'s filled box with a left status accent bar (`border-inline-start`) and hairline rows; apply `--row-dense` (`34px`) on `@media (width >= 64rem) and (hover: hover) and (pointer: fine)` for `.map-display .choice-chip` and map disclosure summaries, and update `FIELD_PROBE` to validate `denseFloor` (`--row-dense`) for desktop `.map-display .choice-chip` while preserving `48px` for all form inputs and mobile/touch viewports.
4. **Automated geometry guard (`assert_layout_geometry`)**: Add `LAYOUT_GEOMETRY_PROBE` and `assert_layout_geometry(page)` to `test/browser_harness.py` (checking G1 under-fill `< 92%`, G2 sibling overlap/overflow, G3 crushed text `> 2.2` lines, G4 box-in-box depth `> 2`, G5 floating `#assistant-fab` vs `#robot-dock-mount`·`#estop`·`#robot-panel-mount` collision, G6 duplicate freshness timestamps, and G7 `#alert-popup-region` toast overlap with right-column, drawer, popover, or stage-head surfaces) plus static regression assertions in `shared/web/test/test_shared_controls.py`.

## Prevention

- Never apply multi-column `grid-template-columns` to a section container with an explicit allowlist of `grid-column: 1 / -1` children; either wrap the header row in its own element or use `:not(h2):not(.ui-action-link) { grid-column: 1 / -1 }`.
- Pair browser visibility checks on composite surfaces with `assert_layout_geometry(page)` from `test/browser_harness.py`.
- Verification evidence: remote static gates (`D:/DevTemp/ui-ux-static-1116/run-1.txt`, 88 passed) and remote Chromium browser suite (`D:/DevTemp/ui-ux-browser-1116/run-1.txt`, 28 passed, 0 skipped) passed on commit `c4558f1959` (source/remote test verification; not physical robot or site deployment acceptance).
