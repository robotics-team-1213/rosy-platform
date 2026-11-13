---
title: A 4 s slow clock rejected every Account login because the chrony source name had vanished in a host rename
date: 2026-11-13
last_updated: 2026-11-13
category: runtime-errors
module: contracts/foundation/core_common/protocol/account_access.py, deploy/hosts/common/rosy_time_sync.py, learning/curation/perception/learning_collaboration.py
problem_type: runtime_error
component: account_login
symptoms:
  - "Learning web apps on the model PC (ports 9444-9448) returned to /accounts?error=account_callback_failed after a correct login"
  - "Account issued tokens normally and no log line named a reason"
root_cause: missing_rollout_step
resolution_type: code_fix
severity: high
tags: [account, clock-skew, chrony, time-sync, d-859, access-token, host-rename]
---

# A 4 s slow clock rejected every Account login because the chrony source name had vanished in a host rename

## Problem

Every login to the model PC's Learning apps failed at the callback. Account itself was healthy and issued tokens.

## Cause

Two faults stacked.

- The model PC clock was about 4 s behind the R host. `verify_access` required `iat <= now < exp` with no leeway, so a token issued "in the future" was refused. The refusal was a `ValueError`, turned into `account_callback_failed` and never logged (Fleet's receiver did the same).
- The model PC's chrony client (D-859) pointed at a Tailscale name that disappeared in the 2026-11-09 host rename. It had zero sources, so nothing corrected the drift. The R host had never received the D-859 site time role either.

A host rename or move silently turns a named time source into "no source". chrony does not fail loudly, and the clock drifts until a check that compares two hosts' clocks (here token `iat`) trips.

## Fix

- `verify_access` accepts `iat` up to `CLOCK_SKEW_S` (60 s) ahead of the verifier clock; `exp` stays strict. It is the only verifier of Account access tokens (the Fleet, CORE, Learning clients and the Account authority all call it), so the rule lives in one place. Tests: 30 s ahead accepted, 120 s ahead refused.
- Learning and the Fleet receiver now log one line with the exception class and first message line when an Account exchange is refused. No token, code or secret is logged; user-facing behaviour is unchanged.
- The R host runs the chrony site role (D-859): upstreams are public NTP servers, clients are the LAN. The model PC and Pinkys use `rosy-fleet-r.local` as their single client source.
- Pinky SD cards carry the name: `prepare-rosy-sd.ps1 -TimeSource rosy-fleet-r.local` makes first boot write the chrony client config. The image does not bake a site name.
- Periodic check: `tools/ops/account_login_check.py` logs into each app with a read-only test account and exits non-zero on failure.

## Evidence

2026-11-13, live: `timedatectl` showed the model PC about 4 s behind R; `chronyc sources` listed no usable source; the operator then installed the site role on R and the client role on the model PC and one Pinky (offline Pinkys and the AI PC were not reachable). Re-checking the Learning logins and every client's `chronyc tracking` stays with the operator. The shipped unit tests cover the leeway bounds and the log line; they do not prove the live clock.

## Recovery

On a host with a wrong clock: `timedatectl` (is NTP service active, is the clock synchronized), `chronyc sources -v` and `chronyc tracking` (any source, offset). Reinstall the client with `rosy_time_sync.py install --maintenance --role client --source rosy-fleet-r.local` in a maintenance window (the tool refuses while rosy-core, rosy-io or rosy-navigation run).

## When to apply

- A login or token check fails across hosts while Account itself issues tokens fine: compare clocks before suspecting keys.
- After any host rename, move or Tailscale name change: re-check every host's chrony source (`chronyc sources`), not just the services the move touched.
- Adding a verifier of signed, time-bounded tokens: allow bounded skew on `iat`, keep `exp` strict, and log the refusal reason.
