---
title: Site clients pin the site by name and CA, resolve its address by mDNS on every connect, and say when the Wi-Fi is the wrong one
date: 2026-10-01
category: design-patterns
module: src/site/cam (Rosy Cam site link, D-391) and the site host mDNS advertiser
problem_type: design_pattern
component: service_layer
severity: high
applies_when:
  - "a phone, tablet or robot connects to a site PC on a LAN whose addresses or access point can change"
  - "a client stores how to reach a site (pairing link, config file)"
  - "an error message has to tell an operator whether the problem is the network, the site PC or the pairing"
tags: [mdns, nsd, dns-sd, site-link, d-391, d-341, d-370, tls-pin, rosy-cam, same-ssid, wifi, diagnosis]
---

# Site clients pin the site by name and CA, resolve its address by mDNS on every connect, and say when the Wi-Fi is the wrong one

## Context
On 2026-10-01 the site access point (BSSID `c8:bf:4c:…`, 192.168.1.0/24, where the robots were) vanished from scans. Another AP broadcasting the same SSID `1213_device` (locally administered BSSID `32:63:6b:…`, 10.16.36.0/24, no robots) took over. The site PC and a tablet silently joined it.
- Rosy Cam stored the site PC's IP from the pairing link. After the change it could only say "unreachable".
- The site PC's IP had also moved, so every paired phone would have needed a new link.
- The same class of failure hit earlier that day: the PC's Wi-Fi dropped while a wired network came up, and the compose proxy lost its bind address.

## Guidance
Store the site's **identity**, not its **address**. Look the address up at connect time.
- **The record.** Keep `tls_host` (a `.local` name in the site certificate's SAN) plus the site **CA** pin (never a leaf alone, D-341 §9). An IP from an IP-form link is kept only as a labelled fallback `manual_host` ("수동 주소"), and a later name link clears it (`src/site/cam/app/src/main/java/io/github/livsbittt/rosy/cam/settings/SiteLink.kt`, `SiteLinkPrefs.kt`).
- **Resolve per connect, verify by name.** A custom OkHttp `Dns` (`SiteDns` in `src/site/cam/app/src/main/java/io/github/livsbittt/rosy/cam/link/SiteResolver.kt`) browses `_rosy-overhead._tcp` on every (re)connect and matches TXT `tls_host`. The URL, SNI and hostname check stay on `tls_host`, and only the socket address comes from mDNS. Any address a spoofer offers must still pass the CA pin plus the hostname check. A failed connect drops the cached address so the next attempt browses again.
- **Order:** mDNS → `manual_host` → failure class `not_discovered` (D-391, `src/site/cam/app/src/main/java/io/github/livsbittt/rosy/cam/link/FailureClass.kt`).
- **Diagnose the network, not just the socket.** When the browse finds nothing, compare the current Wi-Fi subnet/gateway with the subnet recorded at pairing:
  - different: "사이트가 이 Wi-Fi에서 보이지 않습니다 — 같은 이름의 다른 Wi-Fi일 수 있습니다";
  - same address range: "사이트가 자동 찾기(mDNS)에 보이지 않습니다" (the advertiser or firewall is the suspect).
- **Harden against the LAN** (from the independent review):
  - use mDNS only for pinned records, because a plain `ws://` link would hand its token to any responder;
  - learn a `tls_host` for an IP-only record only after a pinned handshake whose leaf names it, and only from exactly one matching advertisement;
  - treat the first pin mismatch on a discovered route as "browse again", not fatal;
  - flag `conflict` only when two adverts' address sets are disjoint.
- **Advertise from the site host.** On Ubuntu, `deploy/site/rosy-overhead-advertise.service` (avahi) publishes `_rosy-overhead._tcp` with TXT `role=overhead-camera`, `proto=rosy-overhead/1`, `tls=required`, `tls_host`, and UDP 5353 must be open inbound.

## Why This Matters
- An IP-pinned client breaks on every DHCP change, AP swap or re-cabling, and then can't tell the operator why.
- Name + CA pinning keeps the security property (only the site that holds the CA-signed key for `tls_host` is accepted) while letting the address float.
- The explicit same-SSID diagnosis turns an hour of "is it the app, the PC or the router?" into one screen that says which.

## When to Apply
- Any site client: Rosy Cam today; FleetAgent under D-391 E1/E2, which share the site-link field names.
- Not Fleet → robot CORE (plain HTTP, enrolled address), which D-370 5.3 keeps as the stated exception.

## Examples
- **Device test, Lenovo TB-J606F (Android 11, API 30), 2026-10-01.** Paired by name (`rosyov://<tls_host>:<port>/?…&tls=1&pin=sha256/…`). With the site PC moved from 192.168.1.102 to 10.16.36.17 and a bench advertiser running, the app showed "주소: 10.16.36.17 (자동 찾기로 찾음)" and streamed at about 2.5 fps with no re-pair.
- **Unadvertised name.** It showed the `not_discovered` text with the current subnet and gateway compared against the pairing subnet.
- **Bench caveats:**
  - A Windows site PC has no avahi, and inbound 5353 was firewalled with no admin rights, so the bench advertiser (python-zeroconf) had to re-announce every 2 s instead of answering queries.
  - Android's NSD cache kept resolving a killed advertiser for minutes. That's harmless because of the pin and the invalidate-on-failure, but don't read a stale "found" as proof that the advertiser is up.

## Related
- ADR D-391 (site-link record and device-link ownership), D-341 §9/§11/§13, D-370 5.2/5.3.
- `docs/deployment/site-ceiling-camera-console-runbook.md` (operator procedure and troubleshooting table).
- `docs/solutions/runtime-errors/cpu-bound-thread-starves-asyncio-ingest-loop-2026-10-01.md` (the same bench's other failure mode).
- (auto memory [claude]) docker-desktop-lan-unreachable and robot-fleet-shared-and-gated record the site network state that day.
