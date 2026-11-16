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
  - "2026-11-17: R console never saw CELL-A for 8 days (control-unit peer UNAVAILABLE, nothing logged): R's control-unit.yaml still dialled https://127.0.0.1:8543, CELL-A dialled peer-r:8544 which R did not publish"
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
  the handover. Use `127.0.0.1` (the peer certificate carries that SAN) only for a call that must stay on the
  same host — never in a control-unit peer URL (see 2026-11-17 below).
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

## 2026-11-17: control-unit peers kept the same-host wiring

Five independent breaks hid behind one silent `UNAVAILABLE` row (Fleet swallowed the exception):

1. Peer URLs were same-host (`https://127.0.0.1:8543`, docker alias `peer-r`); R published no peer port.
2. Both units carried revision `site-2026-11-12-r1` but different manifests (R: three robots, CELL-A: one).
   Fleet compared only the revision string, ids and robot counts.
3. Peer certificates named only `peer-r` / `peer-cell-a`, so no real host name verified.
4. R's peer proxy trusted only the control-peers CA, but R's Fleet serves the site certificate (site CA):
   R's peer origin answered 502 `unknown authority` even locally.
5. CELL-A's hand-made compose had no `/run/avahi-daemon` bind, so its container could not resolve `.local`;
   someone pinned `peer-r` to a DHCP LAN address in `extra_hosts` instead.

Rule since then: every ROSY host advertises `<name>.local`; peer URLs are `https://<host>.local:<port>`, the
peer certificate carries that name, containers resolve it through the host avahi socket, both manifests are
identical with a new revision on every change. `deploy/site/control_unit_check.py` (5-minute timer on R and the
cell PC, host-state declared) checks exactly this path and fails the unit on the first broken step; Fleet now
logs each link transition with a reason and compares `manifest_digest` (API v1.404). The old control-peers CA
key was lost, so a new CA was issued and each unit's `tls_ca_file` holds old+new; the proxy's own trust file
keeps the CA of the certificate its Fleet actually serves. Verified: Fleet's own peer client in R's container
judged CELL-A AVAILABLE on `site-2026-11-17-r1`, and the check passed on both hosts (exit 0). Apply when: a unit
moves host, a peer certificate is reissued, or the manifest changes.
