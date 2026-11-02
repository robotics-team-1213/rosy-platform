---
title: Leaving the extra-arm Compose overlay needs a runtime the old candidate can run, and a host verifier from a reviewed checkout
date: 2026-11-01
category: deployment
module: deploy/site (compose.workcell.yaml, rosy_site_autoupdate.py, verify_candidate.py)
problem_type: deployment_error
component: deployment
symptoms:
  - "site autoupdate refused every candidate from 10-27: ROSY_SITE_PAIRING_COMPOSE adds a Compose file other than the candidate's overlays (/etc/rosy/site/compose-arm-s.yaml)"
  - "after removing the overlay from site.env: fleet runtime differs from current Compose configuration"
  - "Fleet recreated on the old candidate restarted in a loop: observation credential ROSY_ARM_S_TOKEN is required"
  - "the new candidate was refused: verification failed: unsupported deployment file path"
root_cause: missing_rollout_step
resolution_type: procedure
applies_when:
  - "a site still runs an unsigned extra Compose overlay and must move to a candidate that replaces it"
  - "a candidate is refused with unsupported deployment file path"
---

## Problem

The site added Arm S credentials with an unsigned overlay (`/etc/rosy/site/compose-arm-s.yaml`). The updater
refuses any extra overlay, so the site stopped updating on 10-27. The README said only "keep the full mapping and
remove the overlay when switching". Doing just that does not get through.

## Cause

Three refusals in a row, each from a separate check:

1. The updater requires the running containers' config-hash to match the **current** candidate's config.
   Fleet ran with the overlay, so removing it from `site.env` made the runtime differ.
2. Matching the runtime to the old candidate (c47d7c3e78) failed: the observation manifest names `arm_s`, and the
   old candidate's `compose.workcell.yaml` gives only A/B tokens. Fleet crash-looped (about 2.5 minutes until the
   overlay was put back), and the updater refuses an unhealthy stack.
3. The host `verify_candidate.py` predated the new candidate's file layout. Site-tools autoupdate is not installed
   on that PC, so the verifier and updater I/O never move with candidates.

## Solution

On the site PC, in this order:

1. `rosy_site_autoupdate.py hold`.
2. Copy the observation manifest without the extra arm and the wrist camera bound to it, and point
   `ROSY_SITE_WORKCELL_MANIFEST` at the copy. Remove the overlay from `ROSY_SITE_PAIRING_COMPOSE` and recreate
   Fleet and Vision from the current candidate's files only. Wait for healthy.
3. Install `verify_candidate.py`, `site_update_io.py` and `site_update_runtime.py` from a reviewed `origin/main`
   checkout the way README "Site host (once)" does. Never take them from the candidate being verified.
4. `forget-failed site-<sha12>` for the refused candidate, `resume`, `run --dry-run` to see the pick, then `run`.
5. After the switch: `hold`, restore the original manifest path, set `ROSY_SITE_WORKCELL_ARM_CREDENTIAL_PATHS` to
   the full A/B/S mapping, recreate Fleet and Vision, check Fleet's env has all three tokens, `resume`,
   `run --dry-run` reports `idle`.

`site.env` is root-only, so pass the Compose file list literally to `docker compose` rather than sourcing it.

## Verification

2026-11-02 09:17 KST: `/opt/rosy/candidate` → 2ba97ac, proxy, fleet, vision and postgres healthy; Fleet
`ROSY_ADDITIONAL_CREDENTIAL_PATHS` lists the A, B and S tokens; dry-run `idle`.

## Prevention

- Add arms and cameras only through the credential-mapping variables, never another overlay.
- The verifier lags candidates on any PC without site-tools autoupdate; when a candidate is refused with
  `unsupported deployment file path`, update the host tools first (step 3).
