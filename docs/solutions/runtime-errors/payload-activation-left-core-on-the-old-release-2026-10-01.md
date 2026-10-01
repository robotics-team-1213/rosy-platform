---
title: Payload activation left rosy-core on the old release while the readiness probe passed
date: 2026-10-01
category: runtime-errors
module: deploy/robot/pinky_pro (native/native_release.py, rosy-release-push.ps1; releases 2026.10.01-019..021 on rosy-pinky-9dfk and rosy-pinky-8kcn)
problem_type: runtime_error
component: development_workflow
symptoms:
  - "rosy-release-push.ps1 printed 'current release: 2026.10.01-019' and 'CORE readiness: PASS', yet CORE served the old API (openapi v1.63 instead of v1.68)"
  - "rosy-core kept its boot-time PID; /proc/<MainPID>/cwd still pointed at /opt/rosy/releases/2026.09.30-009"
  - "the journal shows 'Stopped target rosy-runtime.target' and rosy-io/rosy-camera stopping, but no 'Stopping rosy-core'"
  - "a new endpoint (GET /api/v1/calibration/session) returned 404 right after a 'successful' push, so the calibration guard could not run"
root_cause: concurrency
resolution_type: code_fix
severity: high
framework_version: systemd 255 (Ubuntu 24.04 raspi)
tags: [systemd, partof, job-replacement, release-activation, payload-push, readiness-probe, rosy-core, d-225, d-388]
---

# Payload activation left rosy-core on the old release while the readiness probe passed

## Problem
`native_release.py` activated a payload with `systemctl stop rosy-runtime.target`, a symlink switch, then `systemctl start rosy-runtime.target`. rosy-core was never stopped, so after every "successful" push CORE kept serving the previous release. The push's readiness probe answered from that old CORE and passed.

## Symptoms
- Seen on rosy-pinky-9dfk when release 019 replaced 009: the push reported success, but CORE's PID and cwd were unchanged and the API was the old version.
- The same thing happened again on rosy-pinky-8kcn (013 → 020) and on 9dfk (019 → 021). The new push check caught both (see Solution).
- 8kcn had looked fine earlier only because it rebooted after its 013 push: a boot starts CORE from whatever `/opt/rosy/current` points at.

## What Didn't Work
- Trusting `CORE readiness: PASS`. `wait-core-ready.py` checks that a CORE answers, not which release it runs.

## Solution
Reproduced on the device (core, io and camera are `PartOf=rosy-runtime.target`; io and camera are `Requires=`/`After=rosy-core`; the target is `After=` all three):

```text
stop rosy-runtime.target; start rosy-runtime.target                       -> core PID 9030 -> 9030 (never stopped)
stop rosy-runtime.target rosy-core rosy-io rosy-camera; start target     -> core inactive after stop, PID 9030 -> 9825
```

1. `native_release.py` `_systemctl("stop")` now names the target and every PartOf unit (`RUNTIME_STOP_UNITS`). A test pins that list to the unit files that carry `PartOf=rosy-runtime.target`. Start stays target-only.
2. `rosy-release-push.ps1` gained a `core-release-check` step. It runs right after activation, and after the image-layer sync on a rollback. It compares `readlink /proc/<rosy-core MainPID>/cwd` with `readlink -f /opt/rosy/current`. If they differ, it runs `systemctl restart rosy-core.service` and warns. If that restart fails, the push stops and tells the operator to run `-Rollback`.

The second guard is required, not optional. A robot keeps its installed activator (`/opt/rosy/native-runtime/native_release.py`) until the image-layer sync replaces it, and that sync runs *after* activation. So the first push of the fix still went through the old activator. On 8kcn and 9dfk the push check caught the stale CORE and restarted it (`CORE_RELEASE_STALE ... CORE_RESTARTED /opt/rosy/releases/2026.10.01-02x`), and the sync then installed the fixed activator.

Landed on main in the merge a48f75f8. Branch: `fix/native-activate-stops-core`.

## Why This Works
The target is ordered `After=` its units, so on stop the target's own job finishes first and `systemctl` returns. CORE's stop job is still queued, waiting for io and camera, which are ordered after CORE. The `start` that arrives next replaces that pending stop job with a start job, which is a no-op for a running unit. Naming every PartOf unit makes `systemctl stop` wait for all of their jobs. The push-side check does not depend on how the activator behaves: it looks at the running process.

## Prevention
- After any release switch, verify the *process*, not readiness: the CORE MainPID's cwd must equal the resolved `/opt/rosy/current`. The push now prints `CORE runs the activated release: <path>`.
- When a fix ships inside the thing it fixes (an activator delivered by the release it activates), add a guard on the caller's side for the first rollout.
- Related: `docs/solutions/workflow-issues/release-cycle-time-one-release-per-deployment-2026-10-01.md`.
