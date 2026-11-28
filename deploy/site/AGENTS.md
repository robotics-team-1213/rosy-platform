
# site

**Parent context:** `../AGENTS.md`

## Purpose

Ubuntu site-host stack: Caddy TLS proxy, Fleet console and task SQLite, Vision (camera frames, ArUco), host services (mDNS, firewall, model watch) and signed site-candidate tooling. It is the current site control server; it does not replace the ROS 2/Pi product runtime, Fleet does not join DDS, and CORE keeps final motion and stop authority. Read `README.md` first (roles, LAN access, bring-up, firewall, pairing, candidate flow); files: `ls`.

## For AI Agents

### Working In This Directory

- Real secrets, tokens, robot lists, and certificates never live here; only `*.example` and `*.template.txt`. Real files go in gitignored paths such as `deploy/site/secrets/`.
- Bind the proxy with a wildcard plus the interface firewall, never a literal LAN IP. No hosts or addresses in tracked files (public repo).
- Browser `/console` (site) and robot `/console` have different origins and credentials (D-275).
- Keep this stack separate from the Pi image under `deploy/robot/pinky_pro/`.
- Fleet and Vision listen on `ROSY_FLEET_PORT` / `ROSY_VISION_PORT` and stay unpublished; only Caddy is exposed.
- D-437: candidates are built by `.github/workflows/build-site-candidate.yml`; signing stays on the offline station. The builder refuses git-ignored files under this folder and under every path the Fleet/Vision Dockerfiles COPY, so keep real secrets out of the build checkout.
- Never run `sign_candidate.py` manually. Unsigned candidates are signed only by the signing PC's `RosySiteAutoSign` task (D-441) after provenance checks and a green exact-main CI run; an out-of-band signature skips the audit and the (unsigned)→(signed) retitle (misleading titles 2026-10-29, 10-31).
- `fetch_candidate.sh` runs on the site host without sudo and prints the D-301 verify/load commands; `rosy_site_autoupdate.py` installs the newest signed candidate with health gate and rollback (D-441).
- `site-maps/map_v2_fleet-v5.json` (D-525) is activated through the Fleet site-map draft/activate API, never read at start.
- The D-446 model-code controller runs only signed jobs from the allowlisted signed layout (`rosy_model_code.py`, `model_code_jobs.py`).
- Each host script has a matching `test/test_site_*.py` pinning unit files, compose, and templates; units come as service plus timer pairs.

### Testing Requirements

```bash
python3 -m pytest test/test_site_*.py -q
python3 -m pytest test/architecture/test_document_placement.py -q   # secret paths stay ignored, templates tracked
```

Refs: `src/site/`, `docs/reference/site-lan-discovery-profile.md`, `docs/adr/D-301-site-candidate-signatures.md`.
