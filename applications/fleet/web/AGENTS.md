<!-- Parent: ../AGENTS.md -->
<!-- Generated: 2026-10-02 | Updated: 2026-10-02 -->

# console

**Parent context:** `../AGENTS.md`
**Updated:** 2026-10-11

## Purpose

Static Fleet console UI (vanilla ES modules, no build step), served at `/console/assets/*`. It talks only to the Fleet server (`/api/fleet/*`), never to a robot API directly. The physical source holder is `applications/fleet/web`. Fleet static mapping installs it as the existing `fleet.server.web` package and `fleet/server/web` resource path. Backend source remains `operations/fleet/fleet/server`. D-518 shared-read modules and the two shared stylesheets live in `shared/`. The Cell document lives in `cell/`. Browsers still request `/console/assets/<basename>`.

Source-move verification is recorded in [progress.md](progress.md), [logs.md](logs.md), and the generated [index.md](index.md). D-637 keeps the Fleet distribution and installed `fleet.server.web` resource identity.

## Key Files

| File | Description |
|------|-------------|
| `index.html` | Shell; loads shared `/common/` tokens, theme, components and `ui.js`, then `console.js` |
| `shared/` | Shared read assets served at `/console/assets/<name>` (D-518). D-766 size unit (`test/architecture/size_units.txt`). |
| `shared/styles.css` | Console styles (shared tokens come from `/common/tokens.css`, not this folder) |
| `shared/fleet-client.js`, `shared/request.js` | Console transport and Fleet response interpretation. New imports use `/console/assets/`; Fleet retains only the two exact former `/common/` URLs as compatibility aliases. |
| `work/work.css`, `shared/power-action.js`, `shared/area-nav.js` | D-766 splits: the work-area sheet, the robot card sleep/wake button (D-440 6, out of `roster.js`), the address-view area selection (D-741 6·7, out of `console.js`) |
| `console.js` | Shell: auth state, `call()`, render, polling cadence; composes the modules below |
| `console-auth.js`, `console-goal.js`, `console-refresh.js` | D-798 3.2 splits of `console.js`: lock/unlock, session, token and password login, development mode; roster keys, click-to-goal and the operator pin; dispatch band and rearm, site path, state poll, cancel-all |
| `map-view.js` | Site map grid, coordinate transforms, robots, goals, draw order |
| `map-overlays.js`, `map-polling.js` | D-798 3.2 splits of `map-view.js`: chips, formation, mediation, sightings, camera tracking and site overlays; site-map, grid, traffic, guide and sightings polling and the traffic toggle |
| `camera-backdrop.js` | D-513 7 / D-515 / D-560 camera picture path: Vision's map plane (`shared/vision-view.js` `createPlaneFeed`) drawn on `toPx`, the D-515 top-down warp (`camera-warp.js` math) only as the fallback, large view/thumbnail turn, Vision frame binding. `map-view.js` passes its draw hook and `toPx` |
| `traffic-view.js` | D-517 10 traffic layer drawing (bands, zones, grant ticks). Polling and the toggle live in `map-polling.js` |
| `roster.js` | Robot workspace and trip-form lifetime; composes summary, cards and attention queues. Console uses its task methods instead of its private trip object. |
| `roster-presentation.js`, `roster.css` | Robot list presentation, shared robot labels/DOM helpers, and roster/workspace-only styles. Shared installation headings and formation actions remain in `shared/styles.css`. |
| `shared/trip-display.js` | Trip/action/AI display vocabulary and explanations, without DOM, geometry or requests. Map and trip consumers import the display owner directly. |
| `devices/` | Device connection/approval UI and read-only discovery/address/app-directory adapters. Own size unit (D-766); enrollment and camera pairing keep their existing public asset URLs and API owners. `device-discovery.js` consumes injected Fleet reads and lifetime; it does not import registration writes. |
| `inbox.js` | D-632 notification view; transport and polling remain in the Console shell |
| `work/work-view.js`, `work/channel-request-view.js` | Work area, its own size unit `fleet/web/work` (docs/plans/2026-10-15-fleet-console-work-unit.md); `channel-request-view.js` is the D-680 대화 요청 review. D-664 source-scoped Task/Mission/trip/Cell Job read view at `/console?view=work` (D-741 7: `show=pending|done` filters the same answer by status in the browser; D-763 4: rows read the server's `visible_state` and trip wait, `show=new` shows only the server's `kinds`); owner scope remains server-side, source status/identity is preserved, no direct dispatch; selected PROPOSED Missions use the existing admit route with named-operator checks and current dispatch generation |
| `incident-view.js` | D-362/D-641 incident evidence, human review and JSON export; at `/console?view=records` (D-741 8) the sub-nav's `show` filters the same answer and the opened incident's handoff and review stand in `#incident-judgment`; session, polling cadence and command authority remain in `console.js` |
| `formation.js` | Formation panel |
| `signals.js` | Traffic-signal cards |
| `site-layer.js` | Ceiling-camera sightings layer (pure; display and cross-check only) |
| `shared/vision-view.js`, `field-view.js`, `field-layers.js` | Camera preview, field proposal/rectified view, layer toggles |
| `maps/`, `shared/site-map-model.js`, `shared/site-map-edit.js` | D-825 지도 문서와 편집 자산 holder. 공개 주소는 기존 `/console/site-map`·`/console/assets/<basename>`이며 매핑은 Fleet `console/static_routes.py`를 본다. 기하·이력은 도메인 독립 함수, `map-editor.js`는 Fleet DTO 어댑터, `map-authoring.js`는 화면 조립이다. 기존 경로 미리보기·가르치기는 유지한다. |
| `shared/map-fit.js`, `map-fit-view.js` | D-375 lane-paint map fit proposal (pure math / view) |
| `shared/field-warp.js` | Shared `warpImage` read (D-518). The install proposal screen stays in `field-view.js` |
| `enrollment.js`, `camera-pairing.js` | Robot enrollment (D-361) and camera pairing approval (D-341) panels |
| `shared/address-drift.js`, `state-age.js`, `localization-badge.js`, `shared/poll-gate.js`, `shared/authorization.js` | Pure helpers: address drift text, queue state staleness (D-493), localization badge, 404 poll gate, role-lock reasons |
| `login.html`, `shared/login-page.js`, `shared/login-return.js`, `shared/password-login.js`, `shared/password-login.css` | D-683 우측 로그인/계정과 전용 로그인 문서. D-519 인증 API·HttpOnly 쿠키를 유지하며 허용된 Fleet 업무 주소로만 복귀한다. 지도/Cell은 새 탭 로그인으로 입력을 보존한다. 로그아웃은 세션 부재를 확인하며 Bearer 해제는 서버 폐기가 아니다. 토큰 접속과 화면 표시는 계정 단추 아래에 둔다(D-741) |
| `shared/fleet-header.js`, `shared/fleet-header.css` | D-540 2 / D-741 3 공통 앱 바 — 네 문서가 같은 `<ui-topbar>` 마크업(`test_fleet_header.py`가 글자 그대로 고정)을 쓰고 연결 글(`실시간`·`지연`·`연결 끊김`)·시계·알림 수·계정 단추의 역할 글·개발 배지·계정 칸 접힘·비상 정지 규칙(401이면 `접속이 필요합니다`, 보기 전용이면 운영자 사유, 모름은 눌림)을 이 모듈 하나로 그린다. 한 줄이고 셸 칸(`.fleet-shell`)의 폭으로 접힌다. 로봇 연결 수는 관제 문서의 지도 머리에 있다. 문서 시트는 머리를 칠하지 않는다 |
| `package.json` | `{"type": "module"}` so node can run the tests |
| `calibration/` | Camera field/map proposal views, layer calculations and measured-preview approval view. D-766 size unit. Existing public `/console/assets/<basename>` URLs are preserved by the explicit static map |

## For AI Agents

### Working In This Directory

- Read DESIGN.md color-role laws and shared component catalog before UI changes (D-624). Paint belongs to shared/web tokens and components; surfaces own placement and actions. Keep gallery and responsive/accessibility checks aligned.

- CSP is `style-src 'self'; script-src 'self'` (`operations/fleet/fleet/server/console/static_routes.py` `CONSOLE_CSP`): no inline scripts, no `style=` attributes, no `el.style.x =`. Express colour and layout with classes.
- A new asset must be added to the allowlist in `operations/fleet/fleet/server/console/static_routes.py`; unlisted files are not served.
- Robot pose is in the shared `map` frame (TF `map` to `<ns>base_footprint`); never introduce per-robot map frames in the drawing code.
- Keep DOM-free logic in pure functions (the `*-view` / `createXPanel` files wire the DOM) so node tests cover it. Sightings and proposals are display-only: never feed them into goals or `cmd_vel`.
- Do not call CORE directly or hold robot tokens in the browser.

### Testing Requirements

```bash
node --test operations/fleet/test/web/
python tools/remote/remote_pytest.py --log-dir "${ROSY_SCRATCH:-${TMPDIR:-/tmp}}/<name>/console" -- operations/fleet/test/test_server_app.py operations/fleet/test/test_console_palette.py operations/fleet/test/test_console_disabled_features.py -q
```

`node --check <file>.js` is a quick syntax check for DOM-free source. Pytest and browser checks run from committed HEAD on remote test PCs per D-584. `test/test_remaining_platform_installed.py` checks wheel/self-contained sdist resources and HTTP allowlist/CSP.

### Common Patterns

Factory functions (`createMapView`, `createFormation`, ...) return handlers the shell wires; operator-facing strings are Korean.

## Dependencies

### Internal

- `operations/fleet/fleet/server/console/static_routes.py` (allowlist, CSP), `operations/fleet/fleet/server/app.py`, `shared/web` (`/common/` assets)

### External

- None at runtime (browser only); node for tests
