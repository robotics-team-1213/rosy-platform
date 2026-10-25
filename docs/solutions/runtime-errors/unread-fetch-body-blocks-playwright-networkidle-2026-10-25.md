---
title: An unread fetch response body keeps the request open, so Playwright goto(networkidle) times out
date: 2026-10-25
category: runtime-errors
module: learning/curation/perception/review_app_web (Learning pages, browser tests)
problem_type: test_failure
component: testing_framework
symptoms:
  - "Page.goto: Timeout 30000ms exceeded ... waiting until \"networkidle\" on /learning/evaluate"
  - "the server log shows every request answered (including a 404) within the same second"
  - "document.readyState is 'complete' and the page has rendered its final text"
tags: [playwright, networkidle, fetch, response-body, browser-test, review-app]
root_cause: logic_error
resolution_type: code_fix
severity: low
applies_when: "a Learning page fetches something whose body it does not read (often a status-only check) and a browser test waits for networkidle"
---

# An unread fetch response body keeps the request open, so Playwright goto(networkidle) times out

## Problem

The evaluate page started calling `accountFetch('/api/accounts/session')` and read the body only when `response.ok` was true. In local mode the route returns 404, so the body was never read. Every browser test that opens `/learning/evaluate` with `wait_until='networkidle'` then timed out after 30 s. That included the existing `test_learning_stages_browser.py`, which passed on the base commit.

## Why it was hard to see

The server log listed every request as answered. The page had loaded and rendered its final text. Nothing looped. Playwright counts a request as finished only after its response body is consumed. A body that is never read keeps the request in flight forever, so the page never reaches network idle.

## How it was found

A throwaway browser test logged `request`, `requestfinished` and `requestfailed` events, then printed what was still open 3 s after `load`. Only `GET /api/accounts/session` was left. The test ran from an unreferenced commit made with `git commit-tree` and `--sha`, so the branch history stayed clean.

## Fix

Do not fetch something the page does not need. `review_app.py` `send()` already swaps the collaboration CSRF token into every JSON body that has a `token` key, so `/api/learning`'s `token` is enough. If a page must check only a status, it still reads or cancels the body (`await response.text()` or `response.body?.cancel()`).

## Verification

After the fix, `test_promotion_request_browser.py` (1440, 390) and `test_learning_stages_browser.py` passed on the remote test PC: 10 passed, with `ROSY_RUN_BROWSER_TESTS=1`.
