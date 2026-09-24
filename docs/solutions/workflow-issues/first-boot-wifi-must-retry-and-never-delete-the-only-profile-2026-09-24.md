---
title: First boot gave up on one Wi-Fi attempt and deleted the only profile back to it
date: 2026-09-24
category: workflow-issues
module: deploy/image/first-boot/rosy-first-boot.py (Pinky Pro release 2026.09.24-010, real device rosy-pinky-e4us)
problem_type: logic_error
component: development_workflow
symptoms:
  - "journal: site Wi-Fi activation reached 18.7 s, then NM reported activation failed at 44.0 s"
  - "first-boot declared PROVISIONING_AP / site_wifi_unreachable off a single attempt and unlinked the rosy-site-sta.nmconnection profile"
  - "the LCD showed FAILED:rosy-first-boot"
  - "NetworkManager's own autoconnect joined the same network at 84.9 s, after first-boot had already given up and deleted the profile"
  - "the runtime never started even though the network eventually came up, and the profile would have been gone on the next reboot"
root_cause: missing_workflow_step
resolution_type: code_fix
severity: critical
tags: [first-boot, wifi, networkmanager, retry, bricking-risk, pinky-pro, provisioning]
---

# First boot gave up on one Wi-Fi attempt and deleted the only profile back to it

## Problem

First boot on a real Pinky Pro (`rosy-pinky-e4us`) tried to bring up the site Wi-Fi profile exactly
once. That single attempt reached NetworkManager's `activating` state at 18.7 s but was reported as
failed at 44.0 s — a 25.3 s window that, on real hardware near a phone hotspot, was not long enough.
First-boot treated that one failure as final: it declared `PROVISIONING_AP` /
`site_wifi_unreachable`, unlinked the `rosy-site-sta.nmconnection` profile, and left the LCD showing
`FAILED:rosy-first-boot`. NetworkManager's own background autoconnect logic, unrelated to
first-boot's attempt, went on to join the same network at 84.9 s — 40 s after first-boot had already
deleted the only profile that pointed at the site network. The runtime never started despite the
network eventually working, and the profile the device needed to retry after a reboot no longer
existed.

## Symptoms

- A single failed NetworkManager activation (25.3 s) was enough to move first-boot to its terminal
  failure state.
- The `nmconnection` profile for the site network was deleted as part of that failure path.
- NetworkManager reached `activated` on its own, later, using a mechanism first-boot's failure
  handling did not observe or wait for.

## What Didn't Work

- A single bounded wait on one activation attempt, with no retry. On a phone-hotspot-style access
  point on real hardware, one join attempt failing inside ~25 s does not mean the network is
  unreachable — it means try again.
- Deleting the profile on failure. This is the more serious defect: even if the network later comes
  up (as it did, via NM's own autoconnect), first-boot has thrown away its only path back to
  provisioning that network on the next attempt.

## Solution

Branch `fix/first-boot-wifi-retry` (PR #38, merged) bounds the retry instead of giving up after one
attempt, checks `GENERAL.STATE` between attempts rather than trusting a single terminal signal, and
keeps the profile on disk regardless of outcome:

```python
# first association failed at 44.0 s (25 s), NM's own autoconnect retry began
# ... used to discard the profile and fail the boot. Three attempts of at most 30 s
# with 15 s pauses cover those 66 s almost twice over, and the 120 s ceiling
NETWORK_ATTEMPT_WAIT_S = 30
...
NETWORK_BUDGET_S = 120
```

`_wifi_state()` polls NetworkManager's own `GENERAL.STATE` for the profile (`nmcli -t -f
GENERAL.STATE connection show <profile>`) between attempts instead of asking once and giving up. A
`rosy-first-boot-retry.timer`/`.service` pair keeps retrying in the background after the main
first-boot unit exits, and that retry path is a short-circuit read (`--network check`) that only
polls `GENERAL.STATE` — a review catch on an earlier version of this fix found it re-running the
entire `apply()` (state.json rewrite, hostname change, avahi restart) every 30 s instead of just
checking whether the network was already up:

```python
# rosy-first-boot-retry.timer finishes provisioning once it is up.
...
# The retry timer's run: until NM has the site profile up, change nothing
# (no state.json, hostname, avahi restart or file rewrite every 30 s).
```

The retry service is guarded with `flock` so a manual re-run and the timer's own run never overlap,
and the timer stops itself once the network comes up and the runtime is provisioned.

## Why This Works

Bounding the retry (3 attempts × 30 s, 120 s ceiling) covers the observed 66 s of real-world
activation slack almost twice over, while `GENERAL.STATE` polling means each attempt's outcome is
read from NetworkManager's own state machine instead of inferred from a single pass/fail callback.
Never deleting the profile means a device that fails every attempt within the budget still has, on
its next boot or its background retry timer, exactly the same path to the site network it started
with — first-boot's job is to keep trying, not to conclude the network is gone.

## Prevention

- Any first-contact step a device runs against real-world Wi-Fi (as opposed to a lab AP) needs a
  bounded retry against the actual state machine (`GENERAL.STATE`), not a single timed attempt.
- A recovery/provisioning path must never destroy the one resource (here: the site network profile)
  it would need to retry. Treat "delete the only way back" as a design smell in any fallback branch,
  independent of whether the fallback itself is otherwise correct.
- A background retry loop that repeats the *entire* apply logic on every tick, instead of a narrow
  "is it already done" check, is its own defect even when the retry idea is right — caught here by
  review before merge.

## Related Issues

- [all-zero-first-sector-reads-as-a-different-cards-identity-2026-09-24.md](all-zero-first-sector-reads-as-a-different-cards-identity-2026-09-24.md)
