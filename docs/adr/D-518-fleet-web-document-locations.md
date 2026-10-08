## D-518 관제 웹의 위치는 문서 네 개와 공유 읽기다 — 패키지는 Fleet 서버 안에 둔다

**Status:** Accepted (2026-10-08, 사용자 선택: 문서 소유 + 하위 폴더). 페이지 경로와 서빙 프로세스는 바꾸지 않는다. 구현된 것은 네 엔트리 import 울타리, `warpImage`를 `field-warp.js`로 나눈 것, 공유 읽기 아홉 파일의 `web/shared/` 이동, Cell 문서 네 파일의 `web/cell/` 이동이다. 현장 지도, 설치, 운용은 아직 `web/` 바로 아래에 있고, 문서마다 옮긴다.

**부분 유지:** [D-410](D-410-console-operate-and-install-documents.md)의 운용·설치 두 문서, [D-450](D-450-palletizing-app-completion-goals.md) 보충의 `/console/cell`, [D-488](D-488-fleet-site-map-address-routes.md)의 `/console/site-map`, [D-487](D-487-site-console-displays-as-rosy-fleet-birdseye.md)의 표시 이름·id·경로. [D-427](D-427-platform-three-parts-middleware-operations-learning.md)이 미룬 `operations/ui/console` 분리는 열지 않는다.

### 기존 결정과의 관계

| 결정 | 이 ADR |
|---|---|
| D-427 | 패키지를 `operations/ui/console`로 떼지 않는다. 위치는 `operations/fleet/fleet/server/web` 안의 문서다. |
| D-429 | 다섯 관심사, 장치 제어 포트, 사이트 장치 경계를 바꾸지 않는다. |
| D-430 | 안전 체인과 비상 정지의 소유를 바꾸지 않는다. |
| D-425 | 화면 소유와 공유 경계는 유지한다. 최상위 `ui/` 이전은 계속 동결이다. |
| D-410 | 운용과 설치를 한 문서로 합치지 않는다. Cell과 현장 지도를 같은 울타리에 넣는다. |

### Context

Rosy Fleet은 Fleet 프로세스 한 곳이 서빙하는 정적 웹이다. 사람이 여는 문서는 넷이다. `/console`(운용), `/console/install`(설치·보정), `/console/cell`, `/console/site-map`. 결정 당시 파일은 `server/web` 한 폴더에 모여 있었고, import 울타리는 운용·설치·Cell 엔트리만 보았다. `/console/site-map`의 `site-map.js`는 설치 문서의 `field-view.js`를 가져와 영상 펴기를 썼다. `field-view.js`는 설치 제안 화면이다.

패키지를 `operations/ui/console`로 옮기면 폴더 이름만 바뀐다. 서빙은 Fleet에 남고, 문서가 서로의 모듈을 가져오는 문제는 그대로다. D-427이 그 분리를 미룬 이유도 여기 있다.

### Decision

1. **패키지와 경로.** 관제 웹은 `operations/fleet/fleet/server/web`에 둔다. 페이지는 `/console`, `/console/install`, `/console/cell`, `/console/site-map`이다. 공개 자산 URL은 `/console/assets/<파일 이름>`이다. 파일을 하위 폴더로 옮겨도 이 URL은 유지하고, `static_routes.py`의 allowlist가 파일 이름을 실제 경로에 매핑한다. 새 프론트 서버, 새 로그인, 새 제품 앱은 없다.

2. **문서 넷.** 엔트리와 그 문서만 쓰는 파일이다. 엔트리는 자기 문서의 파일과 아래 공유 읽기만 import한다. 다른 문서의 파일은 import하지 않는다.

   | 문서 | 페이지 | 파일 |
   |---|---|---|
   | 운용 | `index.html`, `console.js` | `connection-view.js`, `formation.js`, `map-view.js`, `roster.js`, `line-stuck.js`, `signals.js`, `tracking-view.js`, `tracking-layer.js`, `start-point-view.js`, `start-point-layer.js`, `site-path.js`, `site-layer.js`, `confirmed-action.js`, `camera-warp.js`, `motion-readiness.js`, `link-tag.js`, `localization-badge.js`, `power-health-view.js`, `state-age.js` |
   | 설치 | `install.html`, `install.js` | `enrollment.js`, `camera-pairing.js`, `camera-peer.js`, `field-view.js`, `field-layers.js`, `map-fit-view.js`, `peer-picker.js` |
   | Cell | `cell.html`, `cell.css`, `cell.js` | `cell-document-editor.js` |
   | 현장 지도 | `site-map.html`, `site-map.css`, `site-map.js` | `site-map-model.js`, `site-map-teach.js` |

3. **공유 읽기.** 어느 문서의 조작도 소유하지 않는다. `address-drift.js`, `authorization.js`, `poll-gate.js`, `development-auth.js`, `map-fit.js`, `vision-view.js`, `field-warp.js`, `styles.css`, `doc-tabs.css`. `map-fit.js`는 DOM이 없는 맞춤 계산이다. `vision-view.js`는 미리보기와 렌즈 헤더 읽기이고 설치 쓰기를 받지 않는다. `field-warp.js`는 `warpImage`만 둔다. `styles.css`는 운용과 설치가 같이 쓰고, `doc-tabs.css`는 네 페이지가 같이 쓴다.

4. **울타리.** `operations/fleet/test/test_document_imports.py`가 네 엔트리에서 따라간 모듈을 검사한다. `/common/`은 공유 웹이다. 동적 `import()`는 엔트리에서 거절한다. 시험은 파일 단위다. 공유 파일에 다른 문서의 조작을 넣으면 그 파일을 가져오는 문서가 같이 깨진다.

5. **하위 폴더.** 목표 자리는 `web/operate/`, `web/install/`, `web/cell/`, `web/site-map/`, `web/shared/`다. 한 번에 문서 하나만 옮긴다. 순서는 공유 읽기, Cell, 현장 지도, 설치, 운용이다. 그 커밋은 allowlist 경로, `setup.py`의 `package_data` 글롭, 그리고 폴더를 벗어나는 `./` import를 `/console/assets/<파일 이름>`으로 바꾼다. 같은 문서 안의 `./`는 유지해도 된다. 공유 읽기 아홉 파일은 `web/shared/`에 있고, Cell 문서 네 파일은 `web/cell/`에 있다. 현장 지도, 설치, 운용은 `web/` 바로 아래에 있고, 이 순서로 문서마다 옮긴다.

6. **하지 않는 것.** `operations/ui/console` 분리, 최상위 `ui/` 이전, 수동 운전 패널 제거, 표시 이름·id·저장소 키 변경, `map-view.js` 카메라 그림 분리는 이 결정의 조각이 아니다. 카메라 그림 분리는 `docs/plans/2026-10-07-fleet-site-map-web-server-seam.md`에 남아 있다.

### Consequences

- 설치 제안 화면과 영상 펴기가 갈라진다. `map-fit-view.js`는 계속 `field-view.js`에서 `warpImage`를 받고, `field-view.js`가 `field-warp.js`를 다시 내보낸다.
- Cell 엔트리가 이미 import하던 `development-auth.js`는 공유 읽기로 울타리에 들어온다. 새 권한이 아니다.
- 공유 읽기의 디스크 위치와 남은 폴더 이동은 결정 5다. 공개 URL은 `/console/assets/<파일 이름>`이다.

### Validation

- `operations/fleet/test/test_document_imports.py`
- `operations/fleet/test/test_server_app.py::test_every_console_module_import_is_served`
- `operations/fleet/test/test_site_lanes_api.py`의 `map-fit-view.js` → `field-view.js` `warpImage` import
