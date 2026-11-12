---
title: Pinky to Fleet-R hub-link provisioning and Avahi negative-lookup head-of-line blocking
date: 2026-11-13
last_updated: 2026-11-13
category: runtime-errors
module: operations/fleet/fleet/swarm/discovery_transport.py, operations/fleet/fleet/server/auth, middleware/core/services/core_features/fleet_agent/discovery.py
problem_type: runtime_error
component: fleet_robot_communication
symptoms:
  - "Enrolled Pinky robot remained on gather_source='rest' with hub_linked=False and stale expected_hostname in rosy.yaml, never opening /ws/robots to Fleet-R."
  - "Polling powered-off enrolled robots over mDNS/Avahi every 2.0 s saturated host NSS/Avahi lookups and stalled state reads and event-loop ticks for online robots."
  - "FleetAgent locate_fleet failed to rediscover the site hub when the shared zeroconf DiscoveryCache missed the initial multicast advertisement."
root_cause: logic_error
resolution_type: code_fix
severity: medium
tags: [pinky-pro, fleet-r, hub-link, mdns, avahi, discovery-transport, websocket]
---

# Pinky to Fleet-R hub-link provisioning and Avahi negative-lookup head-of-line blocking

## Problem

Communication between Pinky Pro robots and Fleet-R experienced recurring stalls, event-loop lag (`0.5–0.8 s`), and fallback to REST polling due to three interacting issues:

1. **Unlinked WebSocket Hub (`hub_digest=None`) after enrollment/cutover**:
   - Enrolling a TLS-bound robot (`POST /api/fleet/enrollment/robots`) records the REST token and TLS binding, but D-555 requires an explicit `POST /api/fleet/robots/{robot_id}/hub-link` call to provision the `/ws/robots` pairing credential, site CA, and `expected_hostname` onto the robot (`PUT /api/v1/fleet/link`). Without that step, the robot kept its pre-cutover `rosy.yaml` discovery hostname and disabled `FleetAgent`, leaving `SiteHub` (`/registry`) with zero connected robots and forcing Fleet-R onto continuous HTTPS REST polling.
2. **Avahi/NSS head-of-line blocking and SQLite churn on Fleet-R**:
   - Inside the bridged Fleet container, `DiscoveryCache` (`zeroconf`) cannot receive LAN multicast and returns `()`, so `DiscoveryTransport` falls back to `_HostLookups` (`socket.getaddrinfo` via host `/run/avahi-daemon/socket`).
   - Because `_HostLookups` used a single `ttl_s=2.0` for both positive and negative lookups with 4 worker threads, powered-off enrolled robots triggered `3–5 s` Avahi timeouts every `2.0 s`, saturating Avahi and delaying lookups for online robots.
   - In addition, `EnrolledTlsBindings._read()` queried `EnrollmentStore.tls_renumbers()` once per binding row inside its loop, and `HubLinkMixin._hub_fields()` re-queried `self._store.get(robot_id)` for every robot on each `listing()` / `address_reasons()` call.
3. **Missed multicast recovery and permanent self-disabling on transient `/healthz` errors in `locate_fleet` / `probe_health` on Pinky**:
   - `locate_fleet()` relied solely on `get_shared_cache().wait("_rosy-fleet._tcp", timeout_s=3)`. Because `DiscoveryCache` runs one initial 3-second browse window and relies on passive multicast updates thereafter, a missed multicast packet during Wi-Fi roam or boot left the cache empty until process restart.
   - When the site Fleet container restarted behind its TLS reverse proxy, `probe_health()` connected to the proxy and received HTTP `502`/`503` (or a transient socket error), raising plain `ValueError("Fleet HTTPS health probe failed")`. `FleetAgent._run()` caught `ValueError` as a permanent configuration error (`Fleet link configuration rejected`), set `self.enabled = False`, and permanently stopped reconnecting until `rosy-core` was restarted.
4. **1 Hz SQLite write-lock starvation and startup event-replay stalls on Fleet-R**:
   - `RuleSelectionStore.append_batch()` pruned its 100,000-row cap inside a 1 Hz write transaction using `ORDER BY selection_id DESC LIMIT 1 OFFSET 100000` (`588–760 ms` per call), and `LineStuckAnswerLog.record_judgment()` pruned `fleet_judgment_records` (`>53,000` rows) 3 times per second without an index on `recorded_at` (`3 x 217 ms = 651 ms/s`). Together they held the SQLite write lock for `>1.2 s` per second, blocking main-loop sighting writes (`SightingStore.save_sighting`) and causing continuous `0.5–0.9 s` event-loop lag.
   - `SiteHub._project_async()` replayed 100-row batches of `core_event_audit` (`>15,000` rows on restart) synchronously on the event loop without yielding (`await asyncio.sleep(0)`), starving the robot's 2.0 s heartbeat reply deadline.

## Symptoms

- `GET /api/fleet/enrollment/robots` showed `state="active"`, `hub_linkable=True`, `hub_linked=False`, `hub_online=False`, and `GET /api/fleet/state` reported `gather_source="rest"`.
- `FleetAgent` on the robot logged `"Fleet agent disabled (no approved pairing token or site location)"` with a stale `expected_hostname` in `/var/lib/rosy/core/.rosy/rosy.yaml`.
- `rosy-site-fleet-1` logged recurring `fleet event loop lag (0.5–0.8 s)` while polling powered-off enrolled robots alongside online robots.

## Solution

1. **Provisioned the live D-555 hub link on Fleet-R**:
   - Invoked `POST /api/fleet/robots/{robot_id}/hub-link` on Fleet-R for the online robot, delivering the site CA and `expected_hostname: rosy-fleet-r.local` over the pinned TLS enrollment transport.
   - Verified `/registry` (`online: True`, `has_snapshot: True`), `/api/fleet/enrollment/robots` (`hub_linked: True`, `hub_online: True`, `hub_state: "online"`), and `/api/fleet/state` (`online: True`, `gather_source: "hub"`, `link: "up"`).
2. **Separated negative lookup TTL and expanded DNS worker pool (`discovery_transport.py`)**:
   - Kept positive `ttl_s=2.0` in `_HostLookups` so DHCP changes on online robots are still observed within 2 seconds, while caching failed lookups for `failure_ttl_s=10.0` (with `workers=8`) so powered-off robots fail fast without starving Avahi or online robots.
3. **Eliminated redundant SQLite reads in `EnrolledTlsBindings` and `HubLinkMixin`**:
   - Read `self._store.tls_renumbers()` once per `EnrolledTlsBindings._read()` call instead of once per robot row, and passed the existing `row` from `_hub_fields()` into `_tls_client()`.
4. **Added `_via_avahi` fallback on shared-cache miss and raised `DiscoveryUnavailable` on transient `/healthz` failures (`discovery.py`)**:
   - When `locate_fleet()` uses the shared cache (`cache is None`) and finds no record for `expected_hostname`, it queries `core_common.discover._via_avahi("_rosy-fleet._tcp", 3.0)` before declaring `DiscoveryUnavailable`, while preserving all D-432 TXT classification and pinned TLS `/healthz` probe checks.
   - In `probe_health()`, raised `DiscoveryUnavailable("Fleet HTTPS health probe failed")` (a `ValueError` subclass) on non-200 HTTP status or `(OSError, http.client.HTTPException)` while re-raising `ssl.SSLCertVerificationError`, so `FleetAgent._run()` retries with exponential backoff instead of setting `self.enabled = False`.
5. **Eliminated 1 Hz SQLite full-table scans and yielded during startup event replay (`rules.py`, `reports.py`, `hub.py`)**:
   - Bounded `RuleSelectionStore.append_batch()` by `(SELECT COALESCE(MAX(selection_id), 0) FROM fleet_rule_selections) - ?` (`0.08 ms` vs `588–760 ms`), added `fleet_judgment_time ON fleet_judgment_records(recorded_at)` (`0.05 ms` vs `217 ms`), and added `await asyncio.sleep(0)` inside `SiteHub._project_async()`.

## Prevention

- After enrolling or re-enrolling a TLS-bound robot on a site Fleet, always verify `hub_linked: True` and `gather_source: "hub"` (triggering `POST /api/fleet/robots/{robot_id}/hub-link` if `hub_linked` is `False`).
- Never use the same short TTL for negative mDNS/NSS lookups (`gaierror`) as for positive IPv4 resolutions when background loops poll potentially powered-off robots at 2 Hz.
