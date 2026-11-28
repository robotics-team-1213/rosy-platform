
# console

**Parent context:** `../AGENTS.md`

## Purpose

Static Fleet console UI (vanilla ES modules, no build step), served at `/console/assets/<basename>`. Operational screens use the Fleet server (`/api/fleet/*`), never a robot API. Login, profile and account assets are also served by [Account](../../../operations/account/AGENTS.md); the URL prefix does not decide backend ownership. This folder is the source holder; Fleet static mapping installs it as `fleet.server.web` (D-637) and backend source stays in `operations/fleet/fleet/server`. D-518 shared-read modules and the two shared stylesheets live in `shared/`, the Cell document in `cell/`. Move records: [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md).

## For AI Agents

### Working In This Directory

- Read DESIGN.md color-role laws and the shared component catalog before UI changes (D-624). Paint belongs to shared/web tokens and components; surfaces own placement and actions.
- CSP is `style-src 'self'; script-src 'self'` (`operations/fleet/fleet/server/console/static_routes.py` `CONSOLE_CSP`): no inline scripts, `style=` attributes or `el.style.x =`; use classes.
- A new asset must be added to the allowlist in `static_routes.py`; unlisted files are not served. Size units (D-766): `shared/`, `work/`, `devices/`, `calibration/` (`test/architecture/size_units.txt`).
- Robot pose is in the shared `map` frame; never add per-robot map frames in drawing code. Do not call CORE directly or hold robot tokens in the browser.
- Keep DOM-free logic in pure functions so node tests cover it. Sightings (`site-layer.js`) and proposals are display and cross-check only: never feed them into goals or `cmd_vel`.
- `console.js` keeps session, polling cadence and command authority; `incident-view.js`, `inbox.js`, `roster.js` receive them by injection. `devices/device-discovery.js` consumes injected Fleet reads and never imports registration writes.
- `work/work-view.js` (D-664): source-scoped read view with server-side owner scope and no direct dispatch; a selected PROPOSED Mission uses the existing admit route with named-operator checks and the current dispatch generation.
- `shared/unit-scope.js` (D-960 4, D-974): blocks tagged `data-unit-scope` that the unit does not own are hidden. E-stop is never tagged. No scope (older server) shows everything.
- `shared/fleet-header.js` (D-540 2, D-741 3): the one shared app bar; markup is pinned verbatim by `test_fleet_header.py`. Emergency-stop states: 401 reads `접속이 필요합니다`, view-only gives the operator reason, unknown stays pressable.
- Login (D-683, D-962): Account authentication plus Fleet receiver session; return only to allowed Fleet addresses; logout confirms the session is gone and clearing Bearer is not server revocation; development connections still need human login.
- Camera picture (D-513 7, D-515, D-560): Vision map plane first; the top-down warp is only the fallback. Maps/editors (D-825) keep public `/console/site-map` and `/console/assets/<basename>`.
- `motion-source.js` shows `확인 불가` when no fact proves who moves the robot.

### Testing Requirements

D-584: pytest and browser checks run from committed HEAD on remote test PCs.

```bash
node --test operations/fleet/test/web/
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/console" -- operations/fleet/test/test_server_app.py operations/fleet/test/test_console_palette.py operations/fleet/test/test_console_disabled_features.py -q
```

`node --check <file>.js` is a quick syntax check. `test/test_remaining_platform_installed.py` checks wheel/sdist resources and HTTP allowlist/CSP.

### Notes

Factory functions (`createMapView`, `createFormation`, ...) return handlers the shell wires; operator-facing strings are Korean.
