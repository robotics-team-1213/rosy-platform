---
title: Live Docker and cross-host mDNS E2E fixes for Rosy World and Fleet federation
category: runtime-errors
problem_type: runtime_error
date: 2026-11-24
tags: [rosy-world, docker, mdns, tls, sni, zeroconf, windows]
---

# Live Docker and cross-host mDNS E2E fixes for Rosy World and Fleet federation

Three real failure modes surfaced only when running Rosy World under concurrent Edge `--app` loads on Windows and across separate Docker stacks with mDNS (`.local`) + HTTPS on `rosy-OMEN` and `ai`:

1. **Windows HTTP/SSE backlog starvation (`ERR_CONNECTION_REFUSED`)**: Python's default `ThreadingHTTPServer.request_queue_size` is `5`. When a standalone Edge window held an SSE stream plus ~25 static assets and a second client refreshed simultaneously, TCP SYN backlog overflowed with `ERR_CONNECTION_REFUSED`. Subclassing `WorldHTTPServer` with `request_queue_size = 128` eliminated the timeouts under concurrent Edge `--app` + Playwright loads.
2. **Hardcoded repo parent traversal at `/world` (`IndexError: 1`)**: `tools/sim/world_swarm.py` and `tools/sim/world_env_adapter.py` indexed `.parents[1]` to probe repo paths, which crashed in a crash-loop inside `/world/` (`read_only` Docker container root has only `parents == ['/']`). Guarding `len(parents) > 1` fixed container startup immediately.
3. **mDNS `.local` TLS SAN mismatch (`CERTIFICATE_VERIFY_FAILED`) + non-root D-Bus absence**:
   - `world_mdns.py` and `world_entry.py` initially passed the resolved LAN IPv4 address directly into `urllib.request.urlopen("https://<ip>:...")`, which sets OpenSSL `server_hostname` to the IP literal and fails certificates issued solely for `<host>.local`. Connecting TCP to the resolved IPv4 while calling `ssl_context.wrap_socket(..., server_hostname=hostname)` (matching `deploy/site/fleet-mdns.py`) preserved `.local` SAN verification.
   - Inside unprivileged `cap_drop: [ALL]` `read_only` containers, `avahi-browse`/D-Bus and `/etc/avahi/services` writes fail. Installing `zeroconf==0.151.5` in `applications/world/Dockerfile`, advertising `_rosy-world._tcp` on `network_mode: host`, and scanning with `ServiceBrowser` in `world_mdns.py` and `world_entry.py` enabled non-root cross-host mDNS discovery without static IPs or `extra_hosts`.

Verified end-to-end across isolated Docker networks on `rosy-omen-max-gaming-laptop-16-ah0xxx.local` (`:18140` World + `real-bridge` + `sim-swarm` vs. `:18443` separate Fleet container with Site CA TLS), across the physical LAN from `ai.tailb4b84d.ts.net` (401 unauthenticated rejection, 200 Bearer push, `/api/worlds` live registration), and through stop/restart fault injection (fail-closed `waiting`/`503` and automatic `.local` recovery), with remote pytest passing 12 affected suites after fixes.
