---
title: Host guard files reach a PC only through rosy-host-state install; a hand copy is reverted and an undeclared file never drifts
date: 2026-10-30
category: deployment
module: deploy/site/rosy-host-guard, deploy/hosts/common/rosy-update-report, deploy/hosts/common/rosy-host-state (D-530, D-871)
problem_type: deployment_error
component: deployment
symptoms:
  - "Fleet update view (/api/fleet/updates) empty for every PC, four days after D-871 was published"
  - "no row of /var/lib/rosy-host-guard/status.json had an `updates` key"
  - "host-state status.json showed no drift although /usr/local/bin/rosy-host-guard was the pre-D-871 copy"
root_cause: missing_rollout_step
resolution_type: procedure
applies_when:
  - "a change touches the guard, its forced command, or any file a host-state manifest line installs"
  - "a host feature looks published but its data never appears"
---

## Problem

D-871 added update collection to the site guard and a new `rosy-update-report` on each watched PC. The code
was on origin/main, yet no guard row carried `updates`. Nothing reported the gap.

## Cause

- The guard and its remote scripts have no updater. They change only through `install-host-guard.sh`,
  `install-guard-remote.sh` or `rosy-host-state install <role>`, all run by hand with root.
- `rosy-host-state check` compares the host with the **approved copy** in `/usr/local/lib/rosy-host-state`,
  not with the repository ("it never pulls the repo"). The copy was from 10-26, so the old guard matched it:
  no drift.
- `rosy-update-report` had no manifest line at all, so its absence could not show up as drift either.

## Fix

1. Install from an origin/main export on the site PC: `install-host-guard.sh`, then
   `install-guard-remote.sh --site-key "$(cat /etc/rosy/host-guard/id_ed25519.pub)"` for the site PC's own
   `updates` line, then add `site updates <user>@127.0.0.1` to `hosts.conf` and its key to `known_hosts`.
2. Run `rosy-host-state install site` from the same export, after a root `--dry-run`. Without this step the next
   `check` restores the `safe` line `/usr/local/bin/rosy-host-guard` to the old approved copy.
3. Declare `rosy-update-report` in the common manifest as `approval=recovery` (next to the forced command
   that calls it), so `install <role> --approve recovery` installs it and `check` reports a stale or missing copy.

## Verification

- One guard run after the install: `site` row had `updates` (gate open, three updaters, site stack state).
- `rosy-host-state check` afterwards: fixed, drift and errors all empty; the guard hash stayed at the new copy.
- `test/test_host_state.py::test_recovery_install_is_a_single_explicit_approval_group` now lists the forced
  command and `rosy-update-report`.

## Next time

After landing a change to any manifest-installed host file, the rollout is not done until
`rosy-host-state install <role>` has run on each PC; record it in the owning ADR's DEVICE section.
A file a forced command or timer calls must have a manifest line.
