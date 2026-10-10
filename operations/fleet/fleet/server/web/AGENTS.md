<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# web

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-07

## Purpose

Static Fleet console UI (vanilla ES modules, no build step), served at `/console/assets/*`. It talks only to the Fleet server (`/api/fleet/*`), never to a robot API directly. `__init__.py` makes the folder a package so it ships with the install. D-518 shared-read modules and the two shared stylesheets live in `shared/`. The Cell document lives in `cell/`. Browsers still request `/console/assets/<basename>`.

## Key Files

| File | Description |
|------|-------------|
| `index.html` | Shell; loads shared `/common/` tokens, theme, components and `ui.js`, then `console.js` |
| `styles.css` | Console styles (shared tokens come from `/common/tokens.css`, not this folder) |
| `console.js` | Shell: token, polling cadence, click-to-goal; composes the modules below |
| `map-view.js` | Site map grid, coordinate transforms, robots, goals, overlays |
| `camera-backdrop.js` | D-513 7 / D-515 / D-560 camera picture path: Vision's map plane (`shared/vision-view.js` `createPlaneFeed`) drawn on `toPx`, the D-515 top-down warp (`camera-warp.js` math) only as the fallback, large view/thumbnail turn, Vision frame binding. `map-view.js` passes its draw hook and `toPx` |
| `traffic-view.js` | D-517 10 traffic layer drawing (bands, zones, grant ticks). Polling and the toggle stay in `map-view.js` |
| `roster.js` | Robot cards and attention/intervention queues |
| `formation.js` | Formation panel |
| `signals.js` | Traffic-signal cards |
| `site-layer.js` | Ceiling-camera sightings layer (pure; display and cross-check only) |
| `vision-view.js`, `field-view.js`, `field-layers.js` | Camera preview, field proposal/rectified view, layer toggles |
| `site-map.html`, `site-map.js`, `site-map-model.js`, `site-map.css` | D-488 `/console/site-map`: 활성 지도·초안 보기, 장소·차로 초안 편집과 활성화, D-490 경로 미리보기, D-494 5 운행 칸(시작·취소·바뀐 경로 확인, 1 s 조회), D-494 6 지도 가르치기 칸(`site-map-teach.js`, 1 s 조회). 순수 계산은 `site-map-model.js` |
| `map-fit.js`, `map-fit-view.js` | D-375 lane-paint map fit proposal (pure math / view) |
| `field-warp.js` | Shared `warpImage` read (D-518). The install proposal screen stays in `field-view.js` |
| `enrollment.js`, `camera-pairing.js` | Robot enrollment (D-361) and camera pairing approval (D-341) panels |
| `address-drift.js`, `state-age.js`, `localization-badge.js`, `poll-gate.js`, `authorization.js` | Pure helpers: address drift text, queue state staleness (D-493), localization badge, 404 poll gate, role-lock reasons |
| `password-login.js`, `password-login.css` | D-519 아이디·비밀번호 로그인 칸 — 네 화면이 같이 쓴다. `password_login` 현장이면 잠김 때 칸을 보이고 "토큰으로 접속"(`#token-access`)을 접는다. 쿠키는 HttpOnly라 화면은 토큰이 없을 때 `Authorization`만 빼면 된다 |
| `fleet-header.js`, `fleet-header.css` | D-540 2 공통 머리 — 네 문서가 같은 `<ui-topbar>` 마크업(`test_fleet_header.py`가 글자 그대로 고정)을 쓰고 역할 글·개발 배지·연결 수·시계·설정 접힘·비상 정지 규칙(401이면 `접속이 필요합니다`, 보기 전용이면 운영자 사유, 모름은 눌림)을 이 모듈 하나로 그린다. 문서 시트는 머리를 칠하지 않는다 |
| `package.json` | `{"type": "module"}` so node can run the tests |

## For AI Agents

### Working In This Directory

- Read DESIGN.md color-role laws and shared component catalog before UI changes (D-624). Paint belongs to shared/web tokens and components; surfaces own placement and actions. Keep gallery and responsive/accessibility checks aligned.

- CSP is `style-src 'self'; script-src 'self'` (`static_routes.py` `CONSOLE_CSP`): no inline scripts, no `style=` attributes, no `el.style.x =`. Express colour and layout with classes.
- A new asset must be added to the allowlist in `../static_routes.py`; unlisted files are not served.
- Robot pose is in the shared `map` frame (TF `map` to `<ns>base_footprint`); never introduce per-robot map frames in the drawing code.
- Keep DOM-free logic in pure functions (the `*-view` / `createXPanel` files wire the DOM) so node tests cover it. Sightings and proposals are display-only: never feed them into goals or `cmd_vel`.
- Do not call CORE directly or hold robot tokens in the browser.

### Testing Requirements

```bash
node --test operations/fleet/test/web/
python -m pytest operations/fleet/test/test_server_app.py operations/fleet/test/test_console_palette.py operations/fleet/test/test_console_disabled_features.py -q
```

`node --check <file>.js` is a quick syntax check.

### Common Patterns

Factory functions (`createMapView`, `createFormation`, ...) return handlers the shell wires; operator-facing strings are Korean.

## Dependencies

### Internal

- `../static_routes.py` (allowlist, CSP), `../app.py`, `shared/web` (`/common/` assets)

### External

- None at runtime (browser only); node for tests
