# Web surface and video role boundaries validation

**Date:** 2026-09-26
**Plan:** [D-275 implementation plan](../../plans/2026-09-26-web-surface-video-role-boundaries.md)
**Decision:** [D-275](../../adr/D-275-web-surface-and-video-runtime-ownership.md)
**Checkout:** Windows host, branch `docs/d275-runtime-roles`, based on `07ca4c690bb5011a3f652a506ec329d6a18392f5`.

## Result

The source and local test gates confirm the current ownership split. No runtime or wire-contract changes were needed.

- Robot `/dashboard`, `/console`, `/setup`, and `/device` are static assets installed as `share/dashboard` and served by the robot CORE `core_api_web` process. Browser API and WebSocket traffic remains same-origin; no separate robot web server is introduced.
- The site `/console` is a separate Fleet app behind Caddy. Fleet owns operator/site tasks and sightings readback; robot commands still use the existing CORE contract. Compose validates as three distinct Fleet, Vision, and proxy services.
- Robot camera preview and ceiling-camera ingestion stay separate. The robot preview serves authorized latest JPEGs; overhead Vision accepts ceiling frames and publishes derived sighting data to Fleet. The Fleet relay-boundary test prohibits video relay routes and imports.
- `src/runtime/sensing/web` remains a development/diagnostic surface and is not part of the native product or site Compose launch paths.
- Vision remains a placement-neutral responsibility for camera processing and derived evidence. This execution did not add learning, GPU inference, or autonomous decisions; a new workload still needs a separate input/output, placement, resource, authorization, and acceptance decision.

## Local evidence

All pytest scratch output was directed to `X:\DevTemp\`.

| Check | Result |
|---|---:|
| Initial dashboard/API/Fleet relay/overhead baseline | 117 passed |
| Plan integration suite (dashboard, API, no-video-relay, overhead, topology, harness) | 205 passed, 2 skipped |
| Native install-layout, payload, runtime docs, image pipeline, systemd contracts | 209 passed, 2 skipped |
| Fleet server/task/sighting and overhead tests | 112 passed |
| Network topology, launch boundary, dashboard/API route contracts | 70 passed |
| Opt-in dashboard browser tests | 64 passed |
| Harness contract tests after regenerating generated indexes | 47 passed, 21 freshness warnings |
| `python tools/harness/rosy_harness.py lint` | 0 errors, 21 warnings |
| `docker compose -f deploy/site/compose.yaml config --quiet` | passed with temporary X: config/secret path values |

The focused suites exercise installed asset mapping, auth and same-origin routes, preview stale/rate/sequence handling, Fleet task status/readback, sighting provenance, overhead stale/wrong-source rejection, and absence of Fleet video relay. Local contract/error cases were checked, but site/device process failure injection was not run. This is source/local evidence; no robot motion, E-stop, or physical camera test was run.

## Gates still open

- **ARTIFACT - HOLD:** This checkout is Windows x86_64. The native release builder requires a native aarch64 host, and `deploy/image/inputs.lock.yaml` contains unverified inputs. No ARM64 image, installed `share/dashboard` payload digest, or release manifest was produced here.
- **DEVICE - HOLD:** No named Pi or read-only device access was supplied. Running CORE PID/revision, installed prefix, browser route, and asset/API readback remain unverified.
- **SITE - HOLD:** Compose syntax passed locally, but there was no named Ubuntu host, site certificate/CA, real config/secrets, image digest, or host/process readback. Local config validation is not a site deployment.
- **FIELD - HOLD/PARKED:** No physical phone, ceiling camera, surveyed calibration, operator, or independent stop observer was available. Phone freshness, reconnect behavior, physical E-stop, and robot behavior remain unverified.

## Follow-up decision gate

Before adding another Vision workload, record its source and provenance, output contract, freshness/quality limits, placement options (robot edge, site CPU/GPU, or separate compute), resource budget, failure behavior, and independent acceptance evidence. Training and model rollout remain separate from live inference and Fleet policy. No new Fleet video relay or autonomous motion path is authorized by D-275.
