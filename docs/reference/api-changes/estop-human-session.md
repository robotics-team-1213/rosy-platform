---
surface: fleet
kind: additive
slug: estop-human-session
date: 2026-11-21
title: E-stop needs an operator or a signed-in human session
history: POST /api/fleet/estop: viewer and policy-admin only from an interactive human session; bearer token-only viewers get 403
---
D-1043 narrowed: POST /api/fleet/estop is accepted from an operator (any credential) or from a human in an interactive Account session (cookie, or an Account-signed identity) with fleet.read, including viewer and policy-admin. A bearer token without a named human (Monitoring, token-only viewer, policy-admin token, service, machine, ai_observer) is 403 FORBIDDEN. Rearm, release, clear and resume are unchanged (operator only). `GET /api/fleet/session` adds `estop: bool`, the server's answer for this caller, which the header follows. Audit rows carry the pressing principal and role.
