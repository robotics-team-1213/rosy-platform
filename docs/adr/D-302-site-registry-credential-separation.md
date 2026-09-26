## D-302 Site Fleet 사용자 API와 CORE registry 자격 증명을 분리한다

**Status:** Accepted (2026-09-27). This clarifies and makes deployable the separation already required by D-276.

**Connects:** D-267, D-276, D-293, D-301.

**Context:** D-276 requires per-person bearer credentials in `site-users.yaml` and a separate credential for the CORE `/registry` endpoint. Compose currently passes the `operator_token` secret as `--token-env` while also expecting that same token to be present as the operator's user digest. `create_app` correctly rejects this overlap, so the Fleet container restarts and the stack cannot become healthy.

**Decision:**

1. The person-specific browser/API credential is represented only by its digest in `site-users.yaml`; the user's raw token is delivered out of band.
2. A different high-entropy `registry_token` Compose secret supplies `ROSY_SITE_REGISTRY_TOKEN` to the Fleet `--token-env` option. It protects CORE registry readback and is never used as a site user's bearer.
3. Registry, each site user, CORE robot/pairing, phone ingress, and vision-to-Fleet credentials remain distinct. Compose and the runbook name each purpose separately.
4. The distinction is configuration-only; it does not change API paths, envelopes, roles, or robot command authorization.

**Consequences:** The current Fleet process starts with the D-276 per-user authorization enabled and a separate registry credential. Missing or overlapping credentials remain fail-closed. Deployments must create `registry_token` and continue delivering user tokens separately from their digests.

**Validation / Transition:** A contract test pins the Compose environment-to-secret mapping. A packaged Docker Compose LOCAL run must show all services healthy and prove unauthenticated requests are rejected while a distinct named operator can read session/task APIs. Ubuntu host, real CORE, user handoff, and FIELD acceptance remain separate gates.
