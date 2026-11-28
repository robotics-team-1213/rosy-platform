
# dashboard

**Parent context:** `../AGENTS.md`

## Purpose

Operator dashboard screens (D-23, D-243). FastAPI in `core_api_web` serves this folder; assets install through `CMakeLists.txt` to `share/dashboard`. No Node/Vite build step (D-7 is not implemented here). Subfolders `panels/` (D-766 size unit) and `shell/` have their own `AGENTS.md`.

## For AI Agents

### Working In This Directory

- Harness (D-61): [progress.md](progress.md) · [logs.md](logs.md) · [index.md](index.md); procedure in the repository root `AGENTS.md`.
- Read DESIGN.md color-role laws and the shared component catalog before UI changes (D-624). Paint belongs to shared/web tokens and components; surfaces own placement and actions.
- Keep filenames `index.html`, `styles.css`, `app.js`. CSP forbids inline script/style: no `onclick=`, no `<style>` blocks. Talk only to `/api/v1` and `/ws/*` on the same origin.
- Vanilla ES modules, no bundler; import direction is one-way `dom.js` ← `client.js` ← `settings.js` ← `app.js`. `settings.js` never imports the shell; it calls a hook passed to `initSettings`. Telemetry, teleop and the state socket live in their own modules (D-362 P1).
- A new module must be added to `dashboard_assets` in `api/app.py` or it 404s.
- Identity comes from `GET /api/v1/auth/whoami` (D-193); never probe an admin-only route to learn it. Storage (D-193 6): a token without expiry lives only in `sessionStorage`; only a paired token with "로그인 유지" goes to `localStorage` (`rosy.dashboard.paired`,
- dropped once expired).
- `client.js` is the only module that stores the token. Never put a token in a URL, cookie or console.
- WebSockets open without `?token=` and send `{"type":"auth","token":...}` first; 4401 re-checks whoami, 4403 does not retry, other closes back off 1 s → 30 s.
- Settings forms use `type="button"` plus `bindFormSave`. Network profile apply goes through `POST /api/v1/host/network/apply` (Host Agent); never send a PSK.
- `map.js` asks for `/map` and `/map/costmap` only when `capabilities.runtime.maps` says the snapshot exists (API Ref v1.21). Hardware presence and drive state come from `capabilities.runtime`, never the `runtime_mode` string (`rosy-io` is started by hand under `core`, D-192).
- E-stop wording comes from `estopFault(source)` in `triage.js`; every CORE e-stop is a software stop, so never claim a motor power cut. Teleop is hold-to-drive (~100 ms). Do not add a Fleet/swarm settings UI: outbound Fleet is disabled.

### Testing Requirements

`middleware/robot_ui/robot/test`, `middleware/core/gateway/test/test_dashboard.py`, `test_host_cards.py`; browser: `test/test_dashboard_browser.py`.

### UI 역할과 공용 부품

- `/dashboard`는 대상 신원과 목적 선택, `/console`은 상태·지도·선택한 조작 결과, `/setup`과 `/device`는 현재 절차와 근거를 먼저 보여준다. 역할·capability·신선도 검사와 CORE 최종 명령 권한을 유지한다.
- 일반 조작·정지는 공용 48px/14px/좌우12px, 제목·묶음·접힘 행은 공용 역할 부품을 소비한다. 표면 CSS는 배치와 영상/지도 기하만 소유한다.
- 브라우저 시험은 현재 선택 절차와 의미 있는 readout 이름을 찾는다. 다른 역할의 숨겨진 패널이나 숫자 행 순서를 사용자 화면으로 간주하지 않는다.
