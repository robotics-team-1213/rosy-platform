---
title: "A page overflow check can pass while a card clips a child identifier"
date: "2026-10-27"
category: logic-errors
module: console_source
problem_type: ui_bug
component: frontend
severity: medium
symptoms:
  - "The recovery child identifier touches or crosses the card edge at 320px."
  - "The page and the child element both pass their own scrollWidth checks."
root_cause: missing_validation
resolution_type: code_fix
applies_when:
  - "A nested console panel displays an unbroken identifier inside an overflow-clipping ancestor."
tags: [console, responsive, overflow, identifiers, browser-evidence]
---

# A page overflow check can pass while a card clips a child identifier

## Problem

The new recovery result used a paragraph for its child Mission ID. Actual remote Chromium captures suggested clipping on a narrow console even though the browser suite passed. This fix is verified on a local topic branch and is pending official landing; it is not deployment or device acceptance.

## Symptoms

An initial page-width assertion and a later element scroll-width assertion both passed. Random UUIDs also let an ancestor-bounds check pass. A valid fixed UUID containing 32 wide digits made the problem reproducible: commit `88eb429814` failed at 320px with the result's right edge at 309.75px and the visible card ending at 308px. The viewport itself was 320px wide.

## What Didn't Work

Checking only the page's scroll width misses content clipped by an ancestor. Checking only the paragraph's scroll width also misses the case where its entire box grows beyond the visible card. Random identifiers are a poor boundary fixture because proportional glyph widths change the required space.

## Solution

Commit `477761474d` renders the child ID and result as the incumbent `work-detail` definition list. Its value cells already use `overflow-wrap: anywhere` and a shrinkable grid column in `applications/fleet/web/work/work.css`. No global clipping, font, or overflow rule was weakened. Recovery authority and retry limits did not change.

The real HTTP/browser regression now uses a valid wide-digit UUID and checks both the element's own overflow and its right edge against the visible card and viewport. It keeps all existing failure, separate-operator, lost-reply, child-read-unavailable and one-child assertions.

## Why This Works

Nested layout sizing and clipping can hide overflow without making the document scrollable. Testing the visible ancestor boundary detects that failure; using the established value-cell wrapping prevents the long identifier from determining the panel's minimum width.

## Prevention

For a new long identifier inside a clipped panel, use a valid boundary fixture and check the operative container's geometry as well as the page. Inspect the actual capture at the shipping narrow width.

Verification: the official remote run on local-only commit `477761474d` passed 14 browser cases, zero skips, runner/classifier exit 0 and NEW0. The log is run-1.txt in the external system-TEMP directory named rosy-recovery-visual-fit, outside the repository. Captures were fetched without pixel changes and SHA-256 checked; 320px, 390px and 1920px were visually inspected. Restore the previous paragraph rendering to reproduce the deterministic boundary failure; retain the stronger regression when changing layouts again. The cited local commits have no public PR yet; the project's local landing uses fast-forward merging and does not rewrite them.

## Related Issues

- [Real recovery HTTP/browser regression](../../../operations/fleet/test/test_transfer_recovery_console_browser.py)
- [Console value-cell wrapping](../../../applications/fleet/web/work/work.css)
