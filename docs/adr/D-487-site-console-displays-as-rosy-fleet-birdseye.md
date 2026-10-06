## D-487 사이트 관제 화면의 표시 이름은 Rosy Fleet이다 — 관제는 위에서 내려다보고, 로봇 한 대는 Rosy Robot이 본다

**Status:** Accepted (2026-10-07, 사용자 결정). 사이트 관제 화면의 표시 이름과 관제 화면의 카메라 배치만 정한다. 와이어 식별자, 웹 경로, 레지스트리 id, 아이콘 파일 이름은 바꾸지 않는다.

**부분 대체:** [D-377](D-377-app-names-rosy-plus-one-english-word.md) 2항 대응표의 사이트 관제 행 표시 이름 `Rosy Console`을 `Rosy Fleet`으로 바꾼다. D-377의 나머지 행과 1항 규칙은 그대로다. 이 행만 1항의 "id·아이콘이 같은 한 단어에서 나온다"의 예외다(2항).

잇는 결정: [D-257](D-257-site-lane-map-and-overhead-sightings.md) · [D-370](D-370-site-app-roles-names-and-shared-link.md) · [D-374](D-374-app-identity-follows-one-role-name.md) · [D-377](D-377-app-names-rosy-plus-one-english-word.md) · [D-410](D-410-console-operate-and-install-documents.md).

### Context

사용자가 관제 화면 스크린숏을 보고 이름과 역할이 맞지 않는다고 했다. 사용자의 기대는 이렇다. 로봇 한 대를 보는 화면은 그 로봇의 카메라를 보인다. 관제는 여러 로봇을 보므로 위에서 내려다본 천장 카메라(버드아이)를 보인다.

이름이 혼동을 만들었다. 관제 화면은 `Rosy Console`인데, 로봇 대시보드(Rosy Robot)에도 `/console` 경로(운용 칸)가 있다. 관제를 서빙하고 Mission·로스터를 가진 서비스는 `Fleet`인데, 그 이름은 화면에 보이지 않았다.

같은 스크린숏의 화면 결함:
- 천장 카메라 영상이 두 번 보였다. 지도 아래 `#map-camera`와 카메라 칸 `#vision-frame`이다.
- 지도가 없으면 지도 칸이 빈 안내만 보였다. 카메라는 옆 칸에 있었다.
- 접속 전에 "관제 접속 필요"가 세 번(접속 띠, 발행 띠, 지도 칸) 나오고, 빨간 표시가 둘(`인증 필요`, `토큰 필요`)이었다.
- 대형 칸의 버튼 네 개가 저마다 "운용자 권한이 필요합니다"를 되풀이했다.

### Decision

#### 1. 표시 이름

| 화면 | 표시 이름 | 보는 것 |
|---|---|---|
| 사이트 관제 (Fleet 8090 `/console`, `/console/install`, `/console/cell`) | **Rosy Fleet** | 여러 로봇, 지도, 위에서 내려다본 천장 카메라 |
| 로봇 한 대 (CORE 8080) | Rosy Robot (그대로) | 그 로봇의 상태, 전방 카메라, 조작 |

`<title>`, 머리 워드마크, `surfaces.yaml`의 `app_name`·`app_name_en`·`short_name`, 아이콘 SVG `<title>`이 `Rosy Fleet`이다. 화면은 Fleet 서버 안의 정적 파일이므로 서비스 이름과 화면 이름이 같다.

#### 2. 바꾸지 않는 것

레지스트리 id `console`, 아이콘 파일 `console.svg`, 웹 경로 `/console`·`/console/install`·`/console/cell`, 브라우저 저장소 키(`rosy-console-token` 등), 패키지 `fleet`. D-374 3항이 웹 경로와 저장소 키를 와이어 식별자로 고정했고, 이 ADR은 그것을 다시 열지 않는다. D-374 단계 4의 폴더·패키지 이동 대상 이름(`rosy_console`)은 이 ADR이 정하지 않는다. 단계 4를 열 때 정한다.

#### 3. 관제 화면의 카메라 배치

- 천장 카메라 원본은 카메라 칸에 한 번만 보인다. 지도 아래 사본(`#map-camera`)은 없앤다. 보정된 맞춤이 있으면 지도 캔버스가 같은 프레임을 바닥에 그린다(이미 있던 동작).
- 지도가 없고(접속 전·지도 없음·대기) 카메라가 살아 있으면, 지도 칸은 한 줄 상태로 줄고 카메라가 주 화면이 된다. 넓은 창(110rem 이상)에서는 카메라가 전체 폭을 쓴다. 지도가 오면 지도·카메라 두 칸 배치로 돌아간다.
- 로봇 전방 카메라는 관제에 두지 않는다. Rosy Robot의 몫이다(D-257, D-370 4항).

#### 4. 접속 전·권한 잠금 문구

- 접속 전 안내는 접속 띠 하나가 한다. 발행 띠(`#dispatch-control`)는 접속 전에 접힌다. 지도 칸은 한 줄 상태만 보인다.
- 빨간 표시는 역할 표시 `인증 필요` 하나다. 연결 표시는 `접속 전`(중립)이다.
- `[data-role-lock]` 묶음 안의 공용 버튼은 버튼마다 사유를 쓰지 않는다. 묶음의 안내 한 줄을 켜고 `aria-describedby`로 잇는다. 묶음 밖 버튼(비상 정지, 전체 주행 취소)은 그대로 자기 사유를 보인다. [D-359](D-359-theme-ready-tokens-shared-controls-and-responsive-tiers.md) 5.3항의 "말없이 막지 않는다"는 지켜진다.

### Consequences

- 옛 문서·로그의 "Rosy Console"은 사이트 관제 화면 Rosy Fleet으로 읽는다. 역사 기록은 고치지 않는다.
- D-377 1항 규칙에 예외가 하나 생긴다. 이 화면의 표시 단어는 `Fleet`인데 id·아이콘 파일은 `console`이다.
- 작업 브랜치: `uiux/fleet-name-birdseye`.

### Validation

- `shared/web/test/test_surface_icons.py`가 `console` 항목의 세 이름이 `Rosy Fleet`인지 본다.
- `operations/fleet/test/test_server_app.py`가 `/console`에 `Rosy Fleet`이 있고 `Rosy Console`이 없는지 본다.
- `test/test_fleet_console_browser.py`가 지도 아래 카메라 사본이 없고, 보정된 캔버스가 프레임을 그리는지 본다.
- `operations/fleet/test/test_start_point_browser.py`가 접속 전에 발행 띠가 접히고 접속 뒤 다시 보이는지 본다.
- `operations/fleet/test/web/authorization.test.mjs`가 묶음 안 버튼이 사유를 되풀이하지 않고 묶음 안내를 켜는지 본다.
