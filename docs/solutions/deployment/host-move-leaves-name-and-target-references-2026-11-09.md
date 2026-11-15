---
title: Moving the site host leaves references that still name the old PC, and host-state check changes timers
date: 2026-11-09
category: deployment
module: deploy/site/install-host-control.sh, deploy/hosts/common/rosy-host-state, deploy/robot/omx (D-994)
problem_type: deployment_error
component: deployment
symptoms:
  - "Fleet host-control `site` target on the new R still read the old PC's user and LAN address, so Service Control for `site` would act on the arm cell"
  - "rosy-omx-arm-status on the old PC kept posting to `https://<R .local name>:8543`; the name now resolves to R, which does not publish 8543 (connection refused)"
  - "`rosy-host-state check` enabled rosy-nightly-reboot.timer and rosy-host-state.timer on R during the 24 h watch window"
root_cause: missing_rollout_step
resolution_type: procedure
applies_when:
  - "a site role (R, Account, Monitoring) moves to another PC or the `.local` / Tailscale name is handed over"
  - "someone runs rosy-host-state check on a host whose timers are held on purpose"
---

## Problem

Name handover (the R PC took the old `.local` name) made the stack work for robots and phones, but three
things kept the old meaning and failed quietly or acted on the wrong PC.

## Cause

- `/etc/rosy/fleet-host-control/targets` and `known_hosts` are copied by hand; nothing derives them from the
  host. Copied from the old PC, the `site` line pointed at it. The directory is bind-mounted into the Fleet
  container, so the file change is live; no stack restart is needed.
- A service on another PC that reached its own CELL through the shared `.local` name started reaching R after
  the handover. Use `127.0.0.1` (the peer certificate carries that SAN) for same-host calls.
- `rosy-host-state check` is not read-only: it fixes every `safe` line (enables timers). A hold on
  `rosy-nightly-reboot.timer` survives only while host-state is not run.

## Fix

- targets `site rosy@<new site PC LAN address>`; append `ssh-keyscan` of that address to `known_hosts`. Check the
  chain from the Fleet container with a copy of the key at mode 0600: `refused: not allowlisted` for an unknown
  verb means the forced command ran.
- Grep other PCs' `~/.config/rosy/*.env` and compose files for the old name and port, and for `from=` patterns.
- Do not run `rosy-host-state check` during a hold; read `/var/lib/rosy-host-state/status.json` instead. If it
  ran, disable the timers it enabled.

## Verification

R fleet container reached R's forced command with the fixed target (2026-11-09); arm-status log stopped
reporting refused connections after the env change.
