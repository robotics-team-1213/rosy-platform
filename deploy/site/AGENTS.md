<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# site

## Purpose

Ubuntu site-host stack: Caddy TLS proxy, Fleet console and task SQLite, and Vision (camera frame reception and ArUco projection), plus the host services around them (mDNS advertising, firewall, model watch) and the signed site-candidate tooling. It is the current site control server; it does not replace the ROS 2/Pi product runtime, Fleet does not join DDS, and CORE keeps final motion and stop authority.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Roles, LAN access, bring-up, firewall, pairing, candidate flow. Read first |
| `compose.yaml`, `compose.pairing.yaml` | Site stack and the pairing overlay |
| `Caddyfile`, `Dockerfile.proxy` | TLS proxy; Fleet 8090 and Vision 8095 stay unpublished |
| `Dockerfile.fleet`, `Dockerfile.vision`, `requirements-*.txt` | Fleet and Vision images (each has a `.dockerignore` sibling) |
| `site_preflight.py` | Stops cert, TXT host, or Caddy host mismatches before start |
| `site-firewall.py`, `rosy-site-firewall*.service/.timer` | Interface firewall, fail-closed and periodic check units |
| `fleet-mdns.py`, `mdns-bridge.py`, `rosy-*advertise.service`, `rosy-mdns-bridge.*` | LAN discovery advertising and bridge |
| `build_candidate.py`, `sign_candidate.py`, `verify_candidate.py`, `candidate_signing.py` | Signed site candidate build, sign, verify |
| `site_db.py`, `secret_exec.py` | Site DB maintenance and secret-injecting exec wrapper |
| `install-model-watch.sh`, `rosy-model-watch.*`, `model-watch.yaml.example` | Model watch units and config template |
| `rosy-site-stack.service` | systemd unit for the stack |
| `*.example`, `*.template.txt` | Config and secret templates only (robots, users, cameras, tokens) |

## For AI Agents

### Working In This Directory

- Real secrets, tokens, robot lists, and certificates never live here; only `*.example` and `*.template.txt`. Real files go in gitignored paths such as `deploy/site/secrets/`.
- Bind the proxy with a wildcard plus the interface firewall, never a literal LAN IP. No hosts or addresses in tracked files (public repo).
- Browser `/console` (site) and robot `/console` have different origins and credentials (D-275).
- Keep this stack separate from the Pi image under `deploy/robot/pinky_pro/`.

### Testing Requirements

```bash
python3 -m pytest test/test_site_preflight.py test/test_site_firewall.py \
  test/test_site_candidate.py test/test_site_candidate_signing.py test/test_site_candidate_verifier.py \
  test/test_site_fleet_mdns.py test/test_site_mdns_bridge.py test/test_site_pairing_deploy.py \
  test/test_site_task_queue_deploy.py test/test_site_map_fit_deploy.py test/test_site_db_maintenance.py -q
python3 -m pytest test/architecture/test_document_placement.py -q   # secret paths stay ignored, templates tracked
```

### Common Patterns

- Each host script has a matching `test/test_site_*.py` that pins unit files, compose, and templates.
- systemd units come as service plus timer pairs; the firewall also has a fail-closed variant.

## Dependencies

### Internal

- `src/site/` (Fleet, Vision, cam, cell), `docs/reference/site-lan-discovery-profile.md`, `docs/adr/D-301-site-candidate-signatures.md`

### External

- Docker Compose, Caddy, systemd, Ubuntu site host, OpenSSL
