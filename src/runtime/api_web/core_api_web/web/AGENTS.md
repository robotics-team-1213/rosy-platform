<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-09-02 | Updated: 2026-09-02 -->

# web

## Purpose

Embedded operator dashboard (D-23). Served by FastAPI from this folder. No Node/Vite build step in the current tree (D-7 is not implemented here).

## Key Files

| File | Description |
|------|-------------|
| `__init__.py` | Package marker so setuptools includes the package |
| `index.html` | Dashboard shell |
| `styles.css` | Dashboard CSS (no inline styles in HTML) |
| `app.js` | Shell: login, state/events WS, telemetry render, teleop, e-stop, host cards |
| `dom.js` | `elements` registry, formatting (`number`/`bytes`/`duration`), small DOM setters, `bindFormSave` |
| `client.js` | `session`, `authHeaders`, `api`/`apiMaybe`, `isAdmin`, token storage (`rememberToken`/`forgetToken`), `pairWithCode`, `logout`. The only module that stores the token |
| `settings.js` | 현장 설정 panel: identity, tokens, waypoints, safety policy, SLAM, docks |

## Subdirectories

None.

## For AI Agents

### Working In This Directory

- Assets are packaged via `setup.py` `package_data`. Keep filenames `index.html`, `styles.css`, `app.js`.
- CSP forbids inline script/style. Do not add `onclick=` handlers or `<style>` blocks.
- Talk only to `/api/v1` and `/ws/*` on the same origin.

### Testing Requirements

`src/runtime/gateway/test/test_dashboard.py`, `test_host_cards.py`; browser: `test/test_dashboard_browser.py`.

### Common Patterns

Vanilla ES modules, no bundler. Import direction is one-way: `dom.js` ← `client.js` ← `settings.js` ← `app.js`. `settings.js` never imports the shell — when it must update something outside its panel it calls a hook the shell passed to `initSettings`, which is what keeps the graph acyclic. `app.js` owns session/auth/teleop and the host cards. The caller's identity (role, label, source, expiry) comes from `GET /api/v1/auth/whoami` (D-193, API Ref v1.19); never probe an admin-only route to learn it (a viewer then logs a 403 on every load). D-193 6 storage rule: a token without an expiry lives only in `sessionStorage`; only a paired token, and only with "로그인 유지", goes to `localStorage` (`rosy.dashboard.paired`, dropped once expired). Never put a token in a URL, cookie or console. WebSockets open without `?token=` and send `{"type":"auth","token":...}` first; 4401 re-checks whoami, 4403 does not retry, other closes back off 1 s -> 30 s. Settings forms use `type="button"` plus `bindFormSave` so Enter does not navigate. A new module must be added to `dashboard_assets` in `api/app.py` or it 404s at import time. Network profile apply goes through `POST /api/v1/host/network/apply` (Host Agent); never send a PSK. `map.js` owns GridFrame, occupancy/costmap/path layers, and click-to-goal. Costmap is sampled in occupancy world coordinates. Teleop is hold-to-drive (~100 ms). Do not add a Fleet/swarm settings UI here — outbound Fleet is disabled.

## Dependencies

### Internal

- `api/app.py` FileResponse + MIME map

### External

None (browser APIs only).

<!-- MANUAL: -->
