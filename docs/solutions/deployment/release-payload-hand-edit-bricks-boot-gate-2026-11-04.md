---
title: Editing files inside the signed native release payload bricks the boot gate; restore from the release git revision, never in place
date: 2026-11-04
category: deployment
module: deploy/robot/pinky_pro/native, deploy/robot/pinky_pro/release, middleware/drive/planning/nav2
problem_type: deployment_error
component: deployment
symptoms:
  - "after a reboot CORE never starts; mDNS advertises stage FAILED:rosy-release-recover"
  - "rosy-release-recover.service exits 1 with {\"phase\":\"HOLD\",\"reason\":\"OS_RECOVERY_HOLD\"} and no detail"
  - "running os_boot_recover manually shows the swallowed cause: ValueError: CHECKSUM_MISMATCH: expected <sha>, got <sha>"
  - "SSH over the robot Wi-Fi flaps (banner exchange timeouts) while the box boot-cycles"
root_cause: missing_rollout_step
resolution_type: procedure
applies_when:
  - "tuning nav2_params.yaml or any other file under /opt/rosy/releases/<id>/ on a provisioned device"
  - "a native Pinky booted after someone changed files in the active release payload"
---

## Problem

geg6 (release 2026.10.29-001) had a one-line bench edit inside the signed
payload (`install/share/navigation/params/nav2_params.yaml`,
`allow_reversing: false → true`, mtime 2026-11-04 01:57). The robot kept
running, but the next reboot made `rosy-release-recover` fail closed:
`NativeReleaseManager.verify_payload` → `verify_release_files` compares every
payload file against the signed `SHA256SUMS`, finds the mismatch, and the
whole runtime stays down (CORE requires the gate). The gate prints only
`OS_RECOVERY_HOLD`; the checksum detail is swallowed.

## Cause

The boot gate verifies the full signed manifest on every boot. Any in-place
edit of payload content (even a "harmless" param flip) diverges from the
signature and holds the device at the next boot — potentially long after the
edit, when nobody remembers it. The error path hides the offending file name,
so the mismatch must be enumerated by hand.

## Fix (bench procedure, robot-side)

1. Find the mismatched file(s): hash every entry of
   `/opt/rosy/releases/<id>/SHA256SUMS` against the live tree (script the
   loop; `verify_release_files` names no path).
2. Get the signed original from the repo at the release revision
   (`git_revision` in the payload `manifest.json`):
   `git show <rev>:<repo-path>` — its sha256 equals the signed expectation
   (verified byte-identical for nav2_params.yaml). Beware PowerShell `>`
   redirection mangling UTF-8; use `cmd /c` or hash on the robot.
3. Back up the modified file outside the payload (kept at
   `/root/nav2_params.yaml.bak-allow-reversing-true`), restore the original
   with owner/mode preserved, re-run the sum check until `bad = 0`, then
   `systemctl start rosy-release-recover` (expect `phase: RECOVERED`) and
   start CORE.
4. Ship the intended tuning the supported way instead (params override at
   launch / profile / a new signed release), never by editing the payload.

Related: `native-hardware-mode-profile-and-canonical-runtime-env-2026-11-03.md`
(same device, `/etc/rosy` projection canonicalization). Also note
`docs/deployment/pinky-native-mapping-recovery.md` §3 still tells the operator
to edit `/etc/rosy/runtime.env` directly — on ab-v2 devices that either breaks
the projection gate or is silently reverted by the image-layer reconcile; use
`commit_runtime` (see the 2026-11-03 lesson) until the runbook is updated.

## Verification (2026-11-04, geg6)

- Payload sum check `bad = 0`; `rosy-release-recover` →
  `{"phase": "RECOVERED", "release_id": "2026.10.29-001"}`; CORE active;
  mDNS stage left `FAILED:rosy-release-recover` behind.
- Session follow-up: committed `ROSY_NAVIGATION_BACKEND=slam` through
  `commit_runtime` (projection stays `PROJECTED`), started
  `rosy-navigation` with slam_toolbox active, `/rosy_42/scan` 10 Hz,
  `/rosy_42/odom` 30 Hz, CORE logging `cmd_vel sole publisher @50Hz`.

## Next

- Runbook §3 rewrite (runtime.env edit → commit_runtime) is a repo change,
  not done in this session.
- The gate should name the mismatching path in its HOLD output (repo change).
