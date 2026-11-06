---
title: A local Chromium page can load without its application modules
date: 2026-11-05
category: test-failures
module: test/browser_harness.py
problem_type: test_failure
component: testing_framework
severity: medium
symptoms:
  - "A visible account-menu button does not open its hidden token controls"
  - "A local document loads but its scripts report net::ERR_NETWORK_CHANGED"
root_cause: environment
resolution_type: test_fix
tags: [playwright, chromium, network-change, initialization]
---

# A local Chromium page can load without its application modules

During the follow-up to [PR #235](https://github.com/robotics-team-1213/rosy-platform/pull/235), the site-map browser file passed all 101 cases on one test host but intermittently timed out while opening token controls on another. Waiting longer for the hidden summary did not establish that its application handlers existed. The fixture's `page.goto()` had returned with visible HTML.

## Verified cause

Temporary request-failure and pointer-path diagnostics at commit `dfa0363e2b` captured two failed cases in one 101-case run: `test_site_map_body_keeps_usable_columns_beside_the_sub_nav[1366-768-1]` and `test_viewer_cannot_be_offered_operator_actions[320-568]`. Both failed at token-menu interaction. Their failed requests reported `net::ERR_NETWORK_CHANGED` for application modules: `ui.js`/`site-map.js` in the first case and imported editor modules in the second. The run finished 2 failed / 99 passed. Its raw log SHA-256 is `ed7306ce292a27e0a09a5c3e55e27268bbaa3b484f81a65a4e4fd151cf256a3f`.

This establishes a browser module-load interruption on those cases. It does not identify which host network event caused Chromium's notification, or prove that every earlier timeout had the same cause. No host networking or authentication policy was changed.

## Recovery boundary

`goto_with_network_change_retry()` in `test/browser_harness.py` observes failed document/script requests during navigation. Only the exact `net::ERR_NETWORK_CHANGED` failure permits one additional navigation to the same URL. A matching navigation exception has the same bound. A repeated network change raises; other navigation exceptions propagate. The observer is removed in `finally`.

Use this preparation helper before the test starts interacting with a console. It does not retry a test body, token submission, API request, permission check, or product assertion. It also does not introduce a general HTTP-error or JavaScript-exception validator. Do not broaden it into retries for failed assertions or arbitrary resource failures.

The site-map fixture and its two explicit initial query navigations use the helper. Existing layout, role and stored-data assertions remain intact. Temporary DOM/event diagnostics were removed. The independent hashchange screen-readiness fix still waits for the active nav item and visible heading before measuring layout.

At commit `d3ae2203af`, the remote harness suite passed all 10 cases. Its five recovery cases cover clean navigation, script interruption, navigation interruption, a repeated interruption and another navigation exception, including observer cleanup. Before implementation, those five new cases failed at commit `0648824e9c`. The same implementation then passed all 101 site-map browser cases on the host that exposed the module interruptions, with zero skips and NEW/known/flaky 0. The raw browser log SHA-256 is `7a6ad7c8f03c7f457d02b98ca9b823bfb575acce8a2abbe265fb35cfbe85ce83`. This run does not establish which particular navigations required recovery. Canonical FULL acceptance is separate; the follow-up has not yet been published.

## Apply next time

Capture `requestfailed`, module HTTP failures and `pageerror` before the first navigation when HTML is visible but controls have no effect. Include the actual pointer path before blaming a click helper, authentication refresh or responsive layout. Preserve the failed run; a later passing run alone does not explain it.
