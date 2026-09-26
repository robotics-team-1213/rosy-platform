# Site Fleet Registry Credential Separation

## Goal

Restore Fleet startup under the accepted D-276 per-person authorization contract by separating the CORE `/registry` credential from named site-user API credentials.

## Root-cause evidence

The signed candidate passed signature and image identity verification, but the local Compose startup repeatedly restarted Fleet. Its log raised `ValueError: site user credentials must differ from the CORE registry credential`. The current Compose maps `operator_token` to `ROSY_SITE_OPERATOR_TOKEN` for `--token-env` while the `site-users.yaml` operator digest expects that same token. This violates D-276 and makes the stack unhealthy.

## Implementation

1. Add a failing deploy contract test for distinct `registry_token` wiring.
2. Map Compose `registry_token` to `ROSY_SITE_REGISTRY_TOKEN` and use it for `--token-env`.
3. Update the image default, operator runbook, and D-302; preserve individual user digests and raw-token out-of-band delivery.
4. Rebuild a clean immutable candidate, sign it with a throwaway X:-only LOCAL key, verify it before Docker load, load, and verify image IDs.
5. Start the full Compose stack on unique explicit local subnets; assert all services healthy, check unauthorized and authorized requests, and read back an audit-backed task without contacting a real CORE. Tear down only the uniquely named smoke project.

## Execution checkpoint (2026-09-27)

- Regression test first failed against the old Compose wiring, then passed after the distinct registry secret was added.
- Root cause reproduced: Fleet exited with `site user credentials must differ from the CORE registry credential` while Compose mapped `operator_token` to `--token-env` and its user digest simultaneously.
- Corrected worktree Compose plus the prior image candidate started Fleet, Vision, and proxy as healthy. Local API checks verified unauthenticated `401`, viewer session/read access, viewer command `403`, operator task submission, idempotent replay, task readback, and queued cancellation to durable `CANCELED`. Robot config used only the reserved synthetic address `192.0.2.10`; no physical CORE was contacted.
- Still required: build a clean candidate from the corrected commit, sign with an X:-only test key, verify before/after image load, repeat the Compose/API check against that exact candidate, then commit local evidence. No production key or host deployment is authorized by this LOCAL proof.

## Verification boundaries

This is local Docker Desktop evidence. It does not supply the site production key or prove Ubuntu host installation, NVIDIA GPU access, physical phone, real CORE events, robot dispatch, motion, or FIELD acceptance. Automatic movement remains disabled pending D-268 evidence gates.
