---
title: Drain active overlay route handlers before browser recovery
date: 2026-11-05
category: test-failures
module: test/test_games_board_browser.py
problem_type: test_failure
component: testing_framework
severity: low
symptoms:
  - "The compact recovery case fails with Route.fulfill: Route is already handled!"
  - "The same case passes alone and is recorded as LOAD-FLAKY"
root_cause: async_timing
resolution_type: test_fix
tags: [playwright, route-handler, recovery, flaky-test, games]
---

# Drain active overlay route handlers before browser recovery

The games board polls `overlay.json`. Its browser tests inject 503 responses, remove that route, then wait for the real server to recover. During the canonical FULL at commit 27156893ea, the 390×844 compact recovery case raised `Route.fulfill: Route is already handled!` from the injected handler after `page.unroute()` and before the restored phase assertion. The layout assertions had already passed. This identifies a test interception lifecycle failure; it does not demonstrate a production layout defect.

The full chunk returned 1 failed/158 passed. The unchanged case then passed alone and was classified LOAD-FLAKY. That pass is not green FULL evidence, and neither observation establishes that the Decision/VLA changes caused the failure.

The cited revisions are local investigation sources; no public PR merge or publication is claimed here.

## Change and boundary

The [official Playwright API](https://playwright.dev/python/docs/api/class-page#page-unroute-all) provides `page.unroute_all(behavior="wait")` to wait for running handlers. Use it at the six overlay teardown points in this file instead of removing the route while its callbacks may still be completing. Do not use `ignoreErrors`: it swallows handler errors.

Each of these pages has only the overlay fault route registered at teardown. `open_page()` installs none, and the matrix's stop route is registered after the last overlay teardown. If another mock is added, re-check that ownership before clearing all page routes; use a narrower lifecycle rather than dropping unrelated mocks. Keep the actual server, failure/recovery assertions, viewport checks and page-error assertions.

## Verified evidence and limits

- Original FULL source commit 27156893ea: the chunk had 1 failed/158 passed; the single-case rerun had 1 passed. Both outcomes remain recorded, and no failure/quarantine baseline was changed.
- Fix source commit d21cd5e7a1: remote opted-in `test/test_games_board_browser.py` returned 61 passed/0 skipped in 163.27 seconds, runner exit 0 and NEW 0. Independent review checked all six teardown sites and unchanged assertions.
- The original test environment and the focused fix environment differ. These runs are not an interleaved failure-rate comparison and do not prove zero recurrence under load. The final source still needs its canonical FULL.

This changes test fixtures only; there is no service or device rollback. If a later mock makes clearing all routes inappropriate, restrict the fixture lifecycle while retaining the assertions, then rerun the opted-in file and required FULL. Do not restore a green status by suppressing errors or listing the failure as known.

Related: [attribute intermittent failures by their failing line and matched comparisons](../workflow-issues/attribute-intermittent-failure-by-line-then-interleaved-comparison.md).
