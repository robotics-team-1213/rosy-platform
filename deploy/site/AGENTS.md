<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-07 -->

# site

## Purpose

Ubuntu site-host stack: Caddy TLS proxy, Fleet console and task SQLite, and Vision (camera frame reception and ArUco projection), plus the host services around them (mDNS advertising, firewall, model watch) and the signed site-candidate tooling. It is the current site control server; it does not replace the ROS 2/Pi product runtime, Fleet does not join DDS, and CORE keeps final motion and stop authority.

## Key Files

| File | Description |
|------|-------------|
| `README.md` | Roles, LAN access, bring-up, firewall, pairing, candidate flow. Read first |
| `compose.yaml`, `compose.pairing.yaml` | Site stack and the pairing overlay |
| `Caddyfile`, `Dockerfile.proxy` | TLS proxy; Fleet and Vision listen on `ROSY_FLEET_PORT` and `ROSY_VISION_PORT` and stay unpublished |
| `Dockerfile.fleet`, `Dockerfile.vision`, `requirements-*.txt` | Fleet and Vision images (each has a `.dockerignore` sibling) |
| `site_preflight.py` | Stops cert, TXT host, or Caddy host mismatches before start |
| `site-firewall.py`, `rosy-site-firewall*.service/.timer` | Interface firewall, fail-closed and periodic check units |
| `fleet-mdns.py`, `mdns-bridge.py`, `rosy-*advertise.service`, `rosy-mdns-bridge.*` | LAN discovery advertising and bridge |
| `build_candidate.py`, `sign_candidate.py`, `verify_candidate.py`, `candidate_signing.py` | Signed site candidate build (`--sbom-tool scout` or `syft`), sign (full or `--manifest-only`, D-437), verify |
| `fetch_candidate.sh` | Site host, no sudo: download a CI-built signed prerelease, check `SHA256SUMS`, join parts, stage, print the D-301 verify/load commands |
| `auto_sign_candidates.py`, `register_auto_sign_task.ps1` | Signing PC (D-441): sign unsigned `site-*` releases after main-branch provenance and ancestry checks; Windows scheduled task registration |
| `rosy_site_autoupdate.py`, `rosy-site-autoupdate.service`, `rosy-site-autoupdate.timer` | Site host (D-441), installed beside the verifier: install the newest signed candidate, health gate, rollback |
| `site_db.py`, `site_users.py`, `secret_exec.py` | Site DB maintenance, atomic `site-users.yaml` maintenance (digest-only registry), secret-injecting exec wrapper |
| `install-model-watch.sh`, `rosy-model-watch`, `rosy-model-watch.*`, `model-watch.yaml.example` | Model watch installer, stable entry-point wrapper (finds the watcher before or after the D-427 move), units and config template |
| `rosy-site-stack.service` | systemd unit for the stack |
| `*.example`, `*.template.txt` | Config and secret templates only (robots, users, cameras, tokens) |

## For AI Agents

### Working In This Directory

- Real secrets, tokens, robot lists, and certificates never live here; only `*.example` and `*.template.txt`. Real files go in gitignored paths such as `deploy/site/secrets/`.
- Bind the proxy with a wildcard plus the interface firewall, never a literal LAN IP. No hosts or addresses in tracked files (public repo).
- Browser `/console` (site) and robot `/console` have different origins and credentials (D-275).
- Keep this stack separate from the Pi image under `deploy/robot/pinky_pro/`.
- D-437: candidates are built by `.github/workflows/build-site-candidate.yml`; signing stays on the offline station. The builder refuses git-ignored files under this folder (the proxy build context) and under every path the Fleet/Vision Dockerfiles COPY, so keep real secrets out of the checkout used for builds.

### Testing Requirements

```bash
python3 -m pytest test/test_site_preflight.py test/test_site_firewall.py \
  test/test_site_candidate.py test/test_site_candidate_signing.py test/test_site_candidate_verifier.py \
  test/test_site_candidate_workflow.py test/test_site_candidate_fetch.py \
  test/test_site_fleet_mdns.py test/test_site_mdns_bridge.py test/test_site_pairing_deploy.py \
  test/test_site_task_queue_deploy.py test/test_site_map_fit_deploy.py test/test_site_db_maintenance.py \
  test/test_site_users_cli.py -q
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
