# Site mDNS Discovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Show same-LAN ROSY devices in Fleet without treating mDNS advertisements as authenticated enrollment.

**Architecture:** The Ubuntu host browses `_rosy._tcp` through Avahi and sends bounded observations to Fleet with a dedicated credential. Fleet keeps a short-lived discovery list, compares advertised endpoints with configured robots and authenticated FleetAgent HELLO identities, and shows separate discovered, pending, verified, and conflict states. Robot DDS domains and command routes remain unchanged.

**Tech Stack:** Python, Avahi CLI, FastAPI, Fleet static UI, pytest, Docker Compose.

---

### Task 1: Discovery contract and state

**Files:** `src/site/fleet/fleet/server/discovery.py`, `src/site/fleet/test/test_discovery.py`

1. Write failing tests for ten observations, expiry, duplicate names, invalid addresses, AP filtering, and untrusted versus verified state.
2. Run `python -m pytest src/site/fleet/test/test_discovery.py -q` and confirm feature failures.
3. Implement bounded observation storage with no control authority and match only configured endpoint plus authenticated HELLO identity.
4. Run the focused tests.

### Task 2: Host Avahi bridge and authenticated Fleet API

**Files:** `deploy/site/mdns-bridge.py`, `src/site/fleet/fleet/server/app.py`, `src/site/fleet/fleet/cli.py`, `src/site/fleet/test/test_discovery_api.py`, `test/test_site_mdns_bridge.py`

1. Write failing parser and API tests, including malformed Avahi rows, unauthorized writes, and a valid batch.
2. Implement a host one-shot `avahi-browse -rtp _rosy._tcp` adapter and a dedicated Fleet ingest route; pass the secret through a mounted secret file.
3. Repeat focused tests; ensure no token enters logs, YAML, or mDNS TXT.

### Task 3: Fleet readback and UI

**Files:** `src/site/fleet/fleet/server/web/index.html`, `console.js`, `styles.css`, `src/site/fleet/test/test_discovery_api.py`

1. Add an authenticated read route and tests for pending, verified, expired, and conflict rows.
2. Add a separate read-only discovery panel; keep discovered devices out of motion controls.
3. Verify the static asset contract and UI smoke tests available on this host.

### Task 4: Deployment and evidence

**Files:** `deploy/site/README.md`, `deploy/site/compose.yaml`, site secret template, `docs/logs.md`, `src/site/fleet/logs.md`

1. Document host Avahi installation, dedicated secret generation, periodic bridge execution, TLS URL, and 4–10 robot acceptance checks.
2. Run focused and Fleet suites, flake8, Compose config, and `git diff --check`.
3. Record the SOURCE-level evidence and any device/site-host gaps. Do not claim field acceptance without two or more live Pis.

### Task 5: Define common LAN service rules and discover the future Ubuntu Fleet host

**Files:** `docs/reference/site-lan-discovery-profile.md`, `deploy/robot/native/rosy-boot-status.py`, `deploy/site/fleet-mdns.py`, `deploy/site/rosy-fleet-advertise.service`, `test/test_site_fleet_mdns.py`, `deploy/site/build_candidate.py`, `deploy/site/README.md`

1. Write failing tests for the advertised DNS-SD service, parsing tenanted `_rosy-fleet._tcp` candidates, and refusal to select an unknown or ambiguous host.
2. Define a product/role/protocol/TLS TXT profile, preserve existing robot service compatibility, and implement a boot-time Avahi service publisher using the actual Ubuntu hostname and configured HTTPS port. TXT carries protocol metadata only.
3. Implement a locator that lists candidates and returns an endpoint only after an operator-supplied expected `.local` hostname and site-CA TLS health probe.
4. Include publisher, locator, and unit in the site delivery candidate. Test packaging and document certificate SAN, operator bootstrap, and the unimplemented enrollment boundary.
5. Keep other SERION products as a catalog extension: each product needs its own service type and approved identity/API adapter before it joins this discovery profile.

### Task 6: Let paired ROSY robots reconnect to the pinned site

**Files:** `src/runtime/services/core_features/fleet_agent/{agent,discovery}.py`, `deploy/image/{customize-rootfs.sh,first-boot/rosy-first-boot.py}`, `src/runtime/gateway/test/test_fleet_agent_mdns.py`, `test/test_first_boot_provisioning.py`

1. Derive only the expected `.local` site hostname and CA path from the checksum-validated SD personalization bundle into CORE's private overlay. Never copy the one-time `pairing_credential` into `fleet.pairing_token`.
2. Keep Agent disabled without a separately approved persistent pairing token. With one, browse the expected `_rosy-fleet._tcp` service at startup and every reconnect; refuse absent, duplicate, malformed, or TLS-invalid candidates.
3. Use the provisioned CA for outbound WSS and keep discovery failures off the CORE startup critical path. Install Avahi command and `.local` resolver dependencies in the native image.
4. Test parser, trust refusal, bootstrap boundary, URL selection, retry wiring, existing direct URL behavior, and host contract suites. Ubuntu/Pi and real Fleet acceptance remain separate.
