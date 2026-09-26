# Site Fleet local Docker smoke — 2026-09-26

## Result

**PASS at LOCAL only.** The revision-pinned site candidate ran as an isolated
Docker Compose stack on the Windows workstation's Docker Desktop Linux/amd64
engine (Docker 29.7.2, Compose 5.3.1). Fleet, vision, and Caddy became healthy.
The smoke used temporary test credentials and a local test CA under
`X:\DevTemp`; no credentials, certificates, or image payloads are committed.

| Boundary | Evidence |
|---|---|
| Browser/operator API auth | `/api/fleet/events` without a token returned 401; the operator token returned 200; the phone-ingress token returned 401 on the operator API. |
| CORE FleetAgent → site Fleet | The repository's `FleetAgent` connected through the TLS Caddy endpoint, registered its synthetic identity, and delivered heartbeat plus `nav.completed`; the event appeared in authenticated `/api/fleet/events`. |
| Ceiling camera → vision → Fleet | A synthetic 640×480 JPEG with four map markers and one robot marker traversed WSS, CPU ArUco, HTTPS, and the Fleet sighting API. Readback was `(2.0, 1.0)` with the configured map/calibration revisions. |
| Operator task path | A goal against the reserved, unreachable test address `192.0.2.10` was persisted as `REQUESTED → UNKNOWN`. It did not claim robot acceptance or completion. |
| Persistent state | After restarting Fleet, the CORE event, sighting, and task/history were readable from the Compose SQLite volume. By the delayed post-restart read, the sighting had correctly crossed its 1 s display lease and was `stale=true`; it remained stored and was not eligible for action. |

## Browser console to test CORE

A Playwright browser session exercised the rendered `/console` page through the local TLS proxy. An invalid operator token left the console locked; the valid test token showed `1/1` connected and loaded the 50 x 50 `e2e-map`. Selecting `rosy_01` and clicking the map submitted one goal to an isolated fake CORE HTTP endpoint. The fake endpoint logged `(2.55, 2.55, 0.0)` and returned `accepted=true`; Fleet persisted the task as `REQUESTED then ACCEPTED`, and the authenticated task readback returned the same actor (`site-console`) and history. The browser screenshot and raw run result remain under `X:\DevTemp\rosy-site-e2e-db857cb2` and are not repository artifacts.

This proves the local browser-to-Fleet-to-test-endpoint flow only. The fake CORE has no actuator, and this does not prove an actual robot accepted or executed a command. Shared-token role identity, revocation, and physical-device acceptance remain open.

## Latest revision candidate replay

The exact source revision `64cdb3041f04ac6ca5b04ac8a127850242e7f0c6` was built as a clean `linux/amd64` candidate, including three SPDX SBOMs. The manifest, deployment-file hashes, SBOM hashes, and `images.tar` SHA-256 were checked. The archive was loaded into Docker and its packaged Compose file was started with `--no-build`; Fleet, Vision, and Caddy all became healthy. On that revision, `/healthz` returned 200, unauthenticated Fleet state returned 401, and authenticated state returned 200. The rendered console stayed locked for an invalid token and unlocked for the valid test token. Its single configured robot showed offline because the config intentionally points to the reserved unreachable test address; no physical CORE was contacted.

- Source commit: `64cdb3041f04ac6ca5b04ac8a127850242e7f0c6`
- `images.tar` SHA-256: `831279b60d6f69aa844d32016310e92e1119dbfbebf83d69a0ed2de9eaa7702b`
- Fleet image ID: `sha256:f49d130ae020d50418ebf820b6b4b96202865ce8bef2df4239800e7f1829f425`
- Vision image ID: `sha256:77e3014ccc90bd434f6fb7f82fa6e69222b8727df458422160ae2c9374a7ed97`
- Proxy image ID: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`

The candidate and test-only screenshots/configuration remain under `X:\DevTemp`; they contain no provisioned site credentials. This still runs on Docker Desktop's Linux/amd64 engine, not on the Ubuntu RTX 5080 target.

## Synthetic camera sample

Twenty sequential frames were sent over one authenticated WSS connection at
3 Hz. Every generated sighting was read back, none was stale at its immediate
readback, and each reconstructed pose was within 0.15 m of the synthetic map
point. The
measurements below cover this local test only; they are not a production
freshness threshold or an automatic-motion acceptance result.

See [camera_bench.json](camera_bench.json) for the recorded sample summary.

## Candidate identity

- Source commit: `db857cb26ad9ae3d5f7fba6de8d64a61c220495b`
- Platform: `linux/amd64`
- `images.tar` SHA-256: `ece020ca1d78eebe7d6586f241d977c1e5a65f3ad6b111c6f3ed80a0d6e989b5`
- Fleet image ID: `sha256:f49d130ae020d50418ebf820b6b4b96202865ce8bef2df4239800e7f1829f425`
- Vision image ID: `sha256:d0501909f4c32009908ca5ce368ebfb209c2ee53176e465cd104c072205d1f75`
- Proxy image ID: `sha256:92285397b659eb03fbe532a76d061738d5f9b0f7f45027a68c662caa44276c3f`

The archive and SBOM hashes were checked against `release.json`. These checks
detect corruption; this candidate is not cryptographically signed or origin
authenticated.

## Required next evidence

This result does **not** establish Ubuntu 24.04, RTX 5080/container GPU access,
physical-phone pairing, surveyed calibration, physical CORE connectivity,
per-user identity, backup/restore, or DEVICE/FIELD acceptance. The vision image
is CPU ArUco and Compose has no GPU reservation. Automatic policy dispatch
remains `HOLD`; D-268 still needs an accepted evidence contract and measured
freshness/false-trigger gates. D-177 ACK/correlation work remains deferred by
Accepted D-170 until central Fleet Phase 4. Arm pickup and Pinky/robot cameras
remain separate follow-up gates.

Related decisions and plan: [D-267](../../adr/D-267-ubuntu-site-fleet-and-vision-workflow.md),
[D-269](../../adr/D-269-device-server-contracts-and-ros-boundary.md), and the
[device/server contract integration plan](../../plans/2026-09-26-middleware-device-server-contract-integration.md).
