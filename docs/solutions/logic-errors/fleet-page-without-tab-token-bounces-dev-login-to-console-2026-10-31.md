---
title: A Fleet page that ignores the tab's stored token looks signed out, and its login bounces to /console
date: 2026-10-31
module: applications/fleet/web (work/policy-page.js)
problem_type: logic_error
component: frontend
severity: medium
symptoms:
  - "Clicking 학습 정책 승인 from the work screen in a development (개발) session seems to land on the 관제 home screen."
  - "/console/policy shows 인증 필요 and 관제 인증이 필요합니다 while every other Fleet page shows 운영자."
root_cause: missing_credential
resolution_type: code_fix
applies_when:
  - "Adding or moving a Fleet document that calls /api/fleet/* with its own createFleetClient()."
  - "Checking a Fleet page only on the sample server (applications/fleet/dev) or with a cookie login."
tags: [fleet, console, development-session, auth, login-redirect, browser-test]
---

# Every Fleet page reads the tab's token, or a development session looks signed out

## Problem

Development sessions (D-473) and pasted token sessions keep the credential in `sessionStorage['rosy-console-token']`, not in a cookie. `/console`, install, site-map and Cell send it (`createFleetClient({credential: ...})` plus `developmentToken()`). `work/policy-page.js` called `createFleetClient()` with no credential, so its first `/api/fleet/auth/session` returned 401 and the page drew the signed-out header.

The operator then pressed the header `로그인` (`/console/login`, no `return`). The login page saw that the tab was already authenticated and auto-continued to its default target, `/console`. To the operator, the policy link just led back to 관제.

## Why the earlier check missed it

The D-926 move of the policy page to the work shell was checked on the sample server. That server logs in with a cookie, so a page that sends no token still works there. `test_development_console_browser.py` covered `/console`, install, site-map and Cell only.

## Fix and verification

- `policy-page.js` reads the stored token, passes it as `credential`, and calls `developmentToken()` before the session probe, the same as the other work pages.
- `/console/policy` was added to `test_development_console_browser.py`. Run locally with real Chromium against `create_app(... development_sessions=DevelopmentSessions())`: the new case failed with the old page and passed with the fix. A click from `/console?view=work&show=done` now stays on `/console/policy` with `운영자` shown.

## Next time

A new Fleet document that calls the API joins the parametrize list in `operations/fleet/test/test_development_console_browser.py`. A pass on the sample server alone does not show that token and development sessions work.
