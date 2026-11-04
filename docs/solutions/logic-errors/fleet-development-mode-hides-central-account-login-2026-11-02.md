---
module: applications/fleet/web/shared/password-login.js
date: 2026-11-02
last_updated: 2026-11-02
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
No production credential was entered in that diagnostic.

Before the new signed module release, a reviewed incident repair used the
existing signed image and its supported connection-mode setting to restore the
production password form temporarily. The installed independent verifier bound
the loaded image to the signed archive, and the Compose preview changed exactly
one Fleet command argument, `development` to `paired`. Only Fleet was recreated;
the existing updater hold, enrollment/work state and other containers were
verified unchanged. A non-pruning SQLite backup passed integrity verification.
The real Learning-to-Account path then returned HTTP 200 and showed one visible
password input in Edge with normal DNS and certificate verification enabled.
Anonymous state access and development-session issuance were refused.

This observation verifies form availability, not a completed human password or
PKCE login. The final signed Account service deployment and real-user acceptance
remain pending. The original development mode must be restored with the new
authenticated-development implementation.

## Recovery and prevention

Ship the permanent fix through the signed site release process and verify it in
development mode. A temporary paired-mode incident repair does not discharge that
requirement. Preserve the original configuration, independently verify the signed
image and exact Compose change, retain existing holds, and restore development
only with the corrected implementation. Do not clear enrollment holds or change
grants to make a login probe pass. Roll back a temporary configuration change by
restoring only its own env edit with a fresh comparison; never restore an older
database over later writes. The standalone Account rollout also requires its
explicit stopped-writer migration and recovery procedure in D-962.

For cross-app login checks, assert the form is visible and complete a synthetic
cookie login/return flow. Run the enabled-account case with Fleet in development
mode as well as paired mode.
