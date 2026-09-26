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

## Packaged-candidate verification (2026-09-27)

- Built clean commit `9aa985e96eee981b876990b3a57a0db64b803054`; `linux/amd64` archive SHA-256 `fc54ecad2146e0672e1a0736dffb4539e0c15cc7db9a0a61b9c526e9f957b942`. A throwaway Ed25519 key under `X:\DevTemp` signed the candidate. Signature/content check before Docker load and loaded image ID/platform verification after load both passed.
- The exact candidate Compose stack used only synthetic site secrets/TLS and TEST-NET CORE `192.0.2.10`. Fleet, Vision, proxy all healthy. API evidence: no bearer `401`; viewer session/readback succeeded; viewer command `403`; operator task accepted, idempotency replay returned the same task, and queued cancel persisted `CANCELED` across Compose recreation.
- A synthetic ArUco JPEG traversed TLS WebSocket `/overhead/v1/frames`, Vision's worker and source-authenticated Fleet sighting ingestion. Fleet read back frame 102 at approximately `(2.0, 1.0)` for `smoke-map`; incomplete calibration frame 101 and stale frame 103 (1600 ms) were rejected. The API response contained no JPEG/image URL.
- The project was stopped after LOCAL validation. This is not Ubuntu host, RTX GPU, physical phone/CORE, robot dispatch, automatic policy, or FIELD acceptance.

## Synthetic CORE Agent event checkpoint (2026-09-27)

- Restarted the exact candidate with a synthetic private `fleet_pairing_token` in the X:-only robot configuration. A TLS WebSocket Agent completed PRT 1.0 HELLO and submitted `nav.progress` event `local-core-event-9aa-2`; Fleet acknowledged it and the authenticated `/api/fleet/events` route returned it.
- Replaying the same event ID/content was deduplicated. Reusing an event ID with changed default timestamp had been rejected as `EVENT_NOT_AUDITABLE`, confirming the audit store's content-identity guard. `/registry` accepted the distinct `registry_token` and rejected the user's operator token; event history required a named viewer token.
- Restarted Fleet and verified the same event still existed in SQLite. This synthetic path proves packaging, transport, pairing, auth separation, and local persistence; it does not prove a live CORE's credentials, TLS/DNS, clock, reconnection, event continuity, or physical field behavior.

## Verification boundaries

This is local Docker Desktop evidence. It does not supply the site production key or prove Ubuntu host installation, NVIDIA GPU access, physical phone, real CORE events, robot dispatch, motion, or FIELD acceptance. Automatic movement remains disabled pending D-268 evidence gates.
