<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-25 | Updated: 2026-09-28 -->

# hmi

## Purpose

Human-facing screens and shared browser assets. These source locations do not identify a separate server process or deployment host. The CORE dashboard is served in-process by core_api_web; web_common assets are shared by browser surfaces.

## Subdirectories

| Directory | ROS package / purpose |
|-----------|-----------------------|
| dashboard/ | Operator screens served by the CORE FastAPI process (core_api_web); static screens, not a Node server |
| pilot/ | ROS package pilot; Rosy Pilot teleop surface (D-323) served by the CORE FastAPI process — same static pattern, v1 Pinky driving only |
| face/ | ROS package emotion; Pinky LCD face and status surfaces |
| web/ | ROS package web_common; shared browser tokens and controls |

## For AI Agents

### Adding a surface or an app

Every screen a person sees is registered in `web_common/surfaces.yaml`. Walk this list in the same commit:

1. **Place it by owner:**
   - Robot screens served by CORE go in `hmi/<surface>` (D-243, D-275).
   - Site service screens go in that service's package (D-243).
   - An app that is the sole client of one site service goes beside that service with `COLCON_IGNORE` (D-340 §4).
   - An installed shell around web screens goes in repo-root `apps/<name>/`, only when D-340 §2 triggers are recorded.
2. **Register it** in `surfaces.yaml`:
   - Required fields: `id` (`<scope>-<target>`, D-339), `path`, `surface` (robot/site/sim/dev), `medium` (web/native/lcd), and a one-line `audience`.
   - `contracts` for the medium, or a `contract_reason`.
   - `baseline` or a `baseline_reason`.
   - `ports` with their `source` — pick a port no other entry uses.
3. **Names** (D-339 §4, D-345 §4):
   - Browser title: `Rosy <로봇|사이트|시뮬> — <화면 이름>`.
   - App and PWA `name`/`short_name`: `Rosy <이름>`.
   - Console script: the package name, with no `rosy_` prefix.
4. **Look** (D-280, D-345):
   - Web pages start from `web_common/template.html` and link `/common/tokens.css`.
   - Native and LCD code copies token values one per line, `Color(0xFFRRGGBB) // --name` or `(r, g, b)  # --name #hex`, and points `token_copy` at that file.
   - Use no platform default theme. The rose colour is for the ROSY name only.
5. **Transport:**
   - Serve shared files from `web_common/shared-assets.json`; never add a per-server allowlist.
   - Robot screens use same-origin `/api/v1` and `/ws/*`. The WS token goes in the first frame, never the URL (D-193).
   - Send a CSP on every HTML response.
6. **Verify:** `python -m pytest shared/web/test -q` checks the registry, titles, ports and token copies.

- Keep the physical source directory distinct from the ROS package name (web/ is web_common).
- The browser workstation may differ from the host running Fleet or CORE. Follow D-275 and deployment configuration.
- Do not infer final command authority from an HMI asset or screen.

<!-- MANUAL: -->
