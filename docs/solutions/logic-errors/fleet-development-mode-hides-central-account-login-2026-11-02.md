---
module: applications/fleet/web/shared/password-login.js
date: 2026-11-02
problem_type: ui_bug
component: frontend
severity: high
symptoms:
  - "Learning opens the central Account page but its password form is hidden."
  - "The connection endpoint reports mode=development and password_login=true."
root_cause: logic_error
resolution_type: code_fix
tags: [rosy-account, learning, fleet, development-session, browser-test]
applies_when:
  - "An application redirects to the central login hosted by a Fleet in development mode."
---

# Account availability must not depend on Fleet's connection mode

## Problem and cause

The deployed Learning receiver successfully redirected to the configured HTTPS
Account issuer, which served its login page and scripts. That did not establish
that a person could log in: Chromium showed the password form was hidden and a
Fleet development-mode notice replaced it.

`password-login.js` required both a non-development Fleet and
`password_login=true` to display the standalone form. Development mode controls
Fleet connectivity; it does not disable the configured central account service.
Checking HTTP 200 or the existence of the input elements missed the failure.

## Fix and verification

The pending worktree fix displays the form when `connection.password_login ===
true`. A false flag still hides it. No connection mode, account grant, password,
or deployment setting was changed.

`operations/fleet/test/test_fleet_account_browser.py` covers paired/development
and password login enabled/disabled against both legacy and managed real session
stores. The two enabled-development cases failed before the fix. The corrected
remote Chromium run, together with password-session browser and authorization
route tests, exited zero with no skipped cases. The test uses a synthetic app
authorization destination and checks that the real authenticated cookie session
and exact return URL survive; it is not production PKCE exchange acceptance.

On the actual Learning-to-Account path, replacing only the script response in
the diagnostic browser restored the visible form without JavaScript errors.
No production credential was entered, and the deployed server was unchanged.
Operational release and real-user login acceptance remain pending.

## Recovery and prevention

Ship through the signed site release process. Until then the production symptom
remains. Do not switch Fleet to paired mode or bypass project permissions to
repair a presentation error. If a release must be reverted, use the existing
release rollback; this change has no data migration.

For cross-app login checks, assert the form is visible and complete a synthetic
cookie login/return flow. Run the enabled-account case with Fleet in development
mode as well as paired mode.
