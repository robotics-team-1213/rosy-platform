---
title: "Remote Control-Unit Containers Need Tunnel Bridge Binding and Combined CA for Central Account Login"
date: 2026-11-15
category: deployment
module: deploy/site
problem_type: integration_issue
component: service_object
symptoms:
  - "Remote paired Fleet console (:8543/console/login) fails operator password login while R Account holds the real user store."
  - "Containerized Fleet cannot reach R Account over a loopback-only host SSH tunnel or rejects TLS with untrusted peer CA."
  - "On a held R site-fleet image, /console/login returns 200 static HTML even though /api/fleet/auth/login already returns 303 to Account."
root_cause: config_error
resolution_type: workflow_improvement
severity: high
tags: [rosy-account, docker, tunnel-bridge, control-unit, tls-ca, machine-token]
applies_when:
  - "Wiring a separate host's Dockerized Fleet control unit (e.g. cell-a on rosy-arm-cell) to R's central rosy-site-account service."
  - "Diagnosing why /console/login on R or a remote cell does not behave identically to recent main redirects."
---

# Remote Control-Unit Containers Need Tunnel Bridge Binding and Combined CA for Central Account Login

## Problem

When integrating a separate control-unit host (`rosy-arm-cell`, `cell-a-fleet-1`) with 통합관제 R (`rosy-fleet-r`, Docker `rosy-site-account-1`), operator logins on the cell console failed, while R itself looked inconsistent because `/console/login` served static HTML (`200`) on a held R container image.

## Symptoms

- Operator credentials valid in R's `rosy-site-account` failed on `rosy-arm-cell:8543/console/login`.
- Inside `cell-a-fleet-1`, loopback `127.0.0.1:443` reaches the container itself rather than the host's `rosy-account-tunnel.service` forwarding to R Account.
- `rosy-site-fleet-1` on `rosy-fleet-r` already ran with `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG` (`/api/fleet/auth/login?return=%2Fconsole` returned `303` to Account), yet `/console/login` on R still returned `200` static HTML because R ran a held Nov 8 image (`autoupdate` hold) pre-dating `@app.get('/console/login')` redirect.

## What Didn't Work

- **Assuming `rosy-fleet-r` wasn't running central Account in Docker:** Inspecting `rosy-site-account-1` (`:8098` -> `:443`) and `rosy-site-fleet-1` (`:8090` -> `:8443`) showed Docker central Account and `/api/fleet/auth/login` `303` redirect were already active on R; only the held image's `/console/login` route returned `200`.
- **Reusing host loopback tunnel from Docker container:** A container on a bridged Docker network (`rosy-control-peers`) cannot reach `127.0.0.1:443` on the host, and host `rosy-account-tunnel` starting before `docker.service` fails to bind the Docker bridge gateway IP.
- **Assuming status/observation daemons used human credentials:** `omx-arm-status` and `omx-observation-bridge` use `machine: true` viewer bearer tokens in `site-users.yaml`, completely separate from human `rosy-site-account` logins.

## Solution

1. **Register the remote cell console client on R (`rosy-fleet-r`):**
   - Back up `/etc/rosy/account/authority.json`, register the cell `client_id` with its exact HTTPS callback URI (`https://<cell-host>:8543/api/fleet/auth/callback`) and resource (`site:rosy-site`), and restart only `rosy-site-account-1` (do not run manual `compose up` on held R site containers).
2. **Expose the host Account tunnel to the cell Docker bridge (`rosy-arm-cell`):**
   - Update `rosy-account-tunnel.service` with `After=network-online.target docker.service` and listen on both `127.0.0.1:443` and the Docker bridge gateway `<bridge-gateway>:443`.
3. **Provision cell Account client config + combined TLS trust (`cell-a-fleet-1`):**
   - Provide UID/GID `10001` read-only `/etc/rosy/cell-a/account/` (`0400` keys/config, `0644` combined CA concatenating `/etc/ssl/certs/ca-certificates.crt` and `control-peers-ca.pem`).
   - Set `ROSY_FLEET_ACCOUNT_CLIENT_CONFIG`, `SSL_CERT_FILE`, and `extra_hosts` mapping the Account issuer hostname to the Docker bridge gateway in `compose.yaml`.
4. **Keep machine credentials isolated:**
   - Leave `omx-arm-status.env` and `omx-observation-bridge.env` bound to `site-users.yaml` `machine: true` viewer tokens; verify machine health/telemetry still succeeds after container recreation.

## Why This Works

Containerized Fleet processes validate both the HTTP issuer URL (matched against `authority.json` and TLS SAN) and the X.509 certificate chain via `SSL_CERT_FILE`. Routing traffic through the bridge-bound tunnel keeps end-to-end TLS hostname verification intact without disabling certificate checks or coupling container networks directly to loopback.

## Prevention

- When diagnosing `/console/login` behavior on any Fleet instance, check three endpoints together before modifying config:
  1. `GET /api/fleet/auth/connection` (`paired` mode with `password_login` flag enabled)
  2. `GET /api/fleet/auth/login?return=%2Fconsole` (`303` Location to R Account `/api/fleet/auth/authorize`)
  3. `GET /console/login?return=%2Fconsole` (live image version indicator)
- Record all remote paired control-unit Account contracts under ADR `D-1034`.

## Related Issues

- `docs/adr/D-1034-paired-control-unit-central-account-wiring.md`
- `docs/solutions/logic-errors/fleet-development-mode-hides-central-account-login-2026-11-02.md`
- `docs/solutions/runtime-errors/clock-skew-rejected-account-tokens-after-time-source-name-vanished-2026-11-13.md`
