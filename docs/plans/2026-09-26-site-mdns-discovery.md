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
