# 앱·웹 역할 검토

- 날짜: 2026-10-05 (Asia/Seoul)
- 기준: 로컬 main HEAD `cf7d4f5b62c2228b2163429154a33431a907098c`
- 상태: 검토용 스냅샷. 뒤의 「SRP」 절은 제안이다. Accepted ADR을 대체하지 않는다. 코드·경로·API·서빙을 바꾸지 않는다.
- 범위: 사람이 여는 앱과 웹. 등록부 `shared/web/surfaces.yaml`, D-370, D-377, D-410, D-425, D-427, D-450, 로봇 `panels.yaml`, Fleet `static_routes.py`.
- 제외: 새 화면 추가, 폴더 이전, 수동 운전 패널 제거, 이름 변경, 장치·현장 수용.

이 문서는 현재 계약을 한 장으로 모아 검토하기 위한 것이다. 표에 적힌 소유는 이미 `surfaces.yaml`과 D-425가 정한 것이다. 「SRP」 절의 제안도 새 계약으로 읽지 않는다.

## 검토 결론

앱과 웹의 제품 화면은 다섯이다. Rosy Robot, Rosy Pilot, Rosy Pilot 셸, Rosy Console, Rosy Cam. 한 조작은 한 화면만 소유한다. 일부러 겹치는 것은 비상 정지와, Pilot 실기 수용 전까지 남아 있는 수동 운전이다.

화면이 버튼을 가진다고 그 화면이 사실을 기록하거나 바퀴를 움직이지는 않는다. 브라우저는 요청과 표시를 한다. 움직임은 로봇 CORE가, Mission 원장은 Fleet이, 천장 프레임은 Vision이 맡는다.

폴더는 이 역할과 이미 대체로 맞다. 로봇 쪽 사람 화면은 `middleware/ui`, 사이트 네이티브 앱은 `operations/ui`(지금 Cam만), 관제 웹은 Fleet 서버 안의 `operations/fleet/fleet/server/web`이다. D-425가 그리던 별도 `ui/console`로는 옮겨지지 않았고, D-427이 그 최상위 `ui/` 이전을 동결했다.

## 어떤 문서가 정본인가

| 문서 | 상태 | 이 검토에서 쓰는 범위 |
|---|---|---|
| `shared/web/surfaces.yaml` | 시험이 읽는 등록부 (D-329) | 매체, 코드 경로, 포트, `owns`, 표시 이름 |
| [D-425](../adr/D-425-app-surface-ownership-shared-boundaries-and-source-layout.md) §1–§3 | Accepted | 화면 소유, API 소유, 상태 정본, 최종 writer를 구분. 공유는 토큰·통신 도구·계약까지 |
| [D-427](../adr/D-427-platform-three-parts-middleware-operations-learning.md) | Accepted | D-425 §4의 최상위 `apps/`·`ui/`를 파트 안으로 대체. 최상위 `ui/`로의 새 이전은 동결 |
| [D-377](../adr/D-377-app-names-rosy-plus-one-english-word.md) | Accepted | 표시 이름은 `Rosy` + 영어 한 단어. D-370 2항 이름표를 대체 |
| [D-370](../adr/D-370-site-app-roles-names-and-shared-link.md) | Proposed | 역할 표·화면 소유·「관제」는 Console만. 이름표는 D-377이, 소유 구분의 일부는 D-425가 이어 받는다 |

화면 소유자와 API 소유자는 같을 필요가 없다. Console이 Mission 입력을 가져도 승인·순서·원장은 Fleet이다. Pinky의 최종 `cmd_vel`은 CORE다.

## 제품 화면

| 화면 | 매체 | 코드 | 서빙 | API 주인 | 이 화면만 하는 일 | 하지 않는 일 |
|---|---|---|---|---|---|---|
| Rosy Robot | 웹 | `middleware/ui/robot` | 로봇 CORE, 8080. `/dashboard`·`/console`·`/setup`·`/device` | CORE | 로봇 한 대의 상태, 작업 준비, 설치·정비, 로봇 자격 | 여러 로봇 관제, Mission, 사이트 기기 승인 |
| Rosy Pilot | 웹 PWA | `middleware/ui/pilot` | Pinky는 CORE `/pilot`(같은 8080의 다른 경로). OMX 연습만 격리 호스트 8088 | CORE | 로봇 한 대의 수동 운전, 운전석 영상, 누르는 동안만 가는 보조 | Fleet 호출, Mission, 영구 설정 쓰기, 여러 로봇 관제 |
| Rosy Pilot 셸 | Android | `middleware/ui/pilot/android` | 앱 자신. 등록부 포트 없음 | CORE | 태블릿에서 로봇을 찾고 연결 (`pilot-device-lobby`) | 조종 화면과 명령. 그건 Pilot PWA |
| Rosy Console | 웹 | `operations/fleet/fleet/server/web` | Fleet 8090. 현장 브라우저는 사이트 프록시 8443 | Fleet | 여러 로봇 모니터링, Mission, 사이트 정지 요청, 기기 연결 승인, 천장 영상 표시, Cell 작업 준비 | 영상 중계·저장, 최종 명령 계산, 로봇 설정 쓰기, 수동 운전 |
| Rosy Cam | Android | `operations/ui/cam` | 앱 자신. Vision `8095` `/overhead/v1/frames`로 송신 | Fleet 페어링, Vision 수신 | 캡처, 프레임 송신, 물리 설치 안내 (`camera-physical-install`) | 로봇 명령, 정지, CORE 연결, 경기장 좌표 보정 |

등록부의 Pilot 포트는 8088뿐이다. 두 웹 표면이 같은 포트를 적지 못하게 되어 있고, 8080은 Robot이 적는다. Pinky Pilot의 실제 서빙은 CORE의 `/pilot`이다. OMX 팔 연습만 8088이다.

Cam의 8095는 앱이 듣는 포트가 아니다. 네이티브 표면은 접속하는 포트를 적는다.

같은 숫자를 두 화면이 보여주는 것은 조작이 두 벌인 것이 아니다. 배터리는 Console 요약, Robot 진단, Pilot HUD가 각자 읽는다. 전방 카메라는 Robot이 저주기 미리보기, Pilot이 운전 중에만 본다. 천장 영상은 Cam이 보내고 Vision이 최신 한 장을 두며, Console 브라우저가 Vision에서 직접 받는다. Fleet은 영상을 중계하지 않는다.

## 폴더

D-427 이후의 현재 자리다. D-425 §4의 최상위 `ui/console` 같은 경로는 목표로 남아 있지 않다.

| 자리 | 무엇이 있는가 | 사람 화면인가 |
|---|---|---|
| `middleware/ui/robot` | Rosy Robot | 웹. CORE가 프로세스 안에서 정적 파일로 서빙 |
| `middleware/ui/pilot` | Rosy Pilot PWA | 웹. 같은 방식 |
| `middleware/ui/pilot/android` | Rosy Pilot 셸 | Android. 웹을 감싸는 로비 |
| `middleware/ui/face` | Rosy Face | LCD. 아래 「제품 역할 표 밖」 |
| `operations/ui/cam` | Rosy Cam | Android. `COLCON_IGNORE`, Gradle만 |
| `operations/fleet/fleet/server/web` | Rosy Console | 웹. Fleet 프로세스 안의 정적 파일. 별도 `operations/ui/console`은 없다 |
| `shared/web` | 토큰, 공용 컨트롤, 아이콘, `surfaces.yaml` | 아님. 조작을 소유하지 않는다 |

`operations/apps`는 게임 호스트처럼 실행 조합이다. 사용자 화면 폴더와 같지 않다. 새 프론트 서버는 없다.

## 웹 안의 칸

### Rosy Robot

`middleware/ui/robot/panels.yaml`. 패널은 스스로 마운트하지 않고 셸이 올린다.

| 경로 | 칸 | 최소 역할 | 패널 |
|---|---|---|---|
| `/console` | 운용 | viewer. 조작은 operator | 로봇 상태, 지도 및 위치, 운전 모드, 수동 운전, 전방 카메라, 도킹 운용, 차선 추종 |
| `/setup` | 작업 준비 | operator. 도크 등록은 administrator | 웨이포인트, 위치·맵, 도킹 준비, 도크 등록, 교통 정책 |
| `/device` | 설치·정비 | administrator | 시스템·기능, 네트워크·장치 운영, 보안, 보드 장치, 최근 이벤트, 진단, 화면 테마 |

### Rosy Pilot

정적 파일이고 `/api/v1`·`/ws/*`만 말한다. 화면은 연결, 주행, 팔 연습(OMX 시뮬), 녹화다. Android 셸은 발견·연결에서 끝나고, 스틱과 명령은 PWA가 한다.

### Rosy Console

서버는 하나고 문서는 셋이다. 로그인은 Fleet 세션 하나다.

| 경로 | 파일 | 하는 일 |
|---|---|---|
| `/` | `/console`로 보낸다 | |
| `/console` | `index.html` | 운용. 로스터, 지도, 대형, 신호, 천장 영상 |
| `/console/install` | `install.html` | 기기 등록, 카메라 연결 승인, 맵 보정 (D-410) |
| `/console/cell` | `cell.html` | Cell 작업 준비. 별도 서버가 아니다 (D-450) |

### Rosy Cam

`operations/ui/cam` 안의 Kotlin 패키지다.

| 패키지 | 하는 일 |
|---|---|
| `camera` | CameraX 촬영, JPEG |
| `link` | Vision으로의 프레임 송신 (`rosy-overhead/1`) |
| `pairing` | 관제 승인 요청. 프레임 링크와 신뢰를 섞지 않는다 |
| `settings` | mDNS 발견, 저장된 사이트 링크 |
| `ui` | 설치 안내, 송출, 페어링 화면 |
| `service` | 포그라운드 송출 |
| `health` | 기기·화면 열 |

와이어 이름은 앱 이름과 다르다. `OverheadLink`, `rosyov://`, `_rosy-overhead._tcp`, `/overhead/v1/frames`는 유지한다.

## 일부러 겹친 곳

비상 정지는 Robot, Pilot, Console에 모두 있다. 링크만 두지 않는다. 정지 사실은 CORE `safety/state`가 말한다. Cam과 Face에는 정지 자격을 주지 않는다. Cam은 관제에서 정지하라는 안내만 둘 수 있다.

수동 운전은 Pilot이 소유한다. Robot `console.teleop`은 Pilot이 DEVICE 수용을 통과할 때까지의 이행기 표면이다 (`surfaces.yaml`의 `manual-drive`, `transitional`). 새 조종 기능은 Pilot에만 둔다. 수용 뒤 Robot 패널은 Pilot으로 가는 링크가 된다. 이 검토는 그 패널을 제거하지 않는다.

## 공유하는 것과 남기는 것

D-425 §3. 전역 토큰이나 전역 store는 없다.

| 층 | 공유 | 소유자에게 남김 |
|---|---|---|
| UI | `shared/web`의 토큰, 테마, 기본 컨트롤, 대화상자 | 화면 구성, 메뉴, 작업 절차 |
| 통신 도구 | 인증 헤더, 시간 제한, 오류 표현, 폴링의 시작·종료 | 자격 발급, 조종 세션, Mission 복구. 이동·집기·Mission 요청은 자동 재전송하지 않는다 |
| 계약 | 버전 있는 API, 언어 간 적합성 벡터 | 서비스별 원장, 승인, 최종 실행 |

CORE 클라이언트는 Robot과 Pilot이, Fleet 클라이언트는 Console이 쓴다. Console 운용과 설치는 같은 origin 세션을 공유한다. CORE·Fleet·Vision 자격은 합치지 않는다.

## 제품 역할 표 밖

등록부에는 있으나 D-370 역할 표의 제품 앱은 아니다.

| id | 매체 | 코드 | 자리 |
|---|---|---|---|
| `web-common` | 웹 라이브러리 | `shared/web` | 화면이 아님 |
| `robot-face` | LCD | `middleware/ui/face` | 부팅 단계, 이름, 로그인 코드만. 입력과 명령이 없다 |
| `game-board` | 웹 | `operations/apps/games/games/web` | 게임 호스트 보드, 8765. Mission과 최종 명령을 소유하지 않는다 |
| `control-diagnostic` | 웹 | `middleware/perception/web/diagnostic.html` | PARKED (D-266). 운영 대시보드가 아니다 |
| `pinky-review` | 웹 | `learning/training/perception/dataset/review_app_web` | 로컬 학습 검수, 8767. 런처·PWA·Android 앱이 아니다 |
| `lane-live-view` | 웹 | `integrations/simulation/gazebo/scripts/lane_live_view.html` | Gazebo 레인 뷰어, 28183 |

화면이 없는 서비스도 역할은 있다. CORE는 최종 명령·정지·외부 API·로봇 자격이다. Fleet은 로스터·Mission·사이트 정지 요청·기기 연결 승인이다. Vision은 프레임 수신·최신 한 장·검출·미리보기이고, 사람 화면과 로봇 명령이 없다.

## SRP로 나누는 방법

여기서 SRP는 한 문서가 한 사람의 한 가지 일을 맡는다는 뜻이다. 앱 수나 프로세스를 늘리는 뜻이 아니다. 화면 소유, API 소유, 상태 정본, 최종 writer는 계속 따로 둔다 (D-425).

### 새 제품 앱은 만들지 않는다

사람 일은 이미 다섯 화면으로 나뉜다. 한 화면 안에 일이 둘 이상이면, 받아 둔 방법은 문서를 나누는 것이다. 서버와 로그인을 새로 만들지 않는다.

| 후보 | 사람의 일 | 지금 자리 | 앱으로 열지 않는 이유 |
|---|---|---|---|
| 설치·보정 | 사이트 설치자가 기기를 등록하고 카메라를 맞춘다 | Console `/console/install` | D-410이 운용과 문서를 나눴다. 토큰은 `rosy-console-token` 하나다. 독립 표면은 「나중에」로 남아 있다 |
| Cell 준비 | 작업 준비자가 초안·계산·제안을 다룬다 | Console `/console/cell` | D-450이 별도 서버·포트 대신 이 경로를 골랐다. 운용 관제로 돌아가는 링크가 있다 |
| 로봇 설치·정비 | 관리자가 한 로봇을 고친다 | Robot `/device` | 같은 CORE 자격, 같은 8080. `panels.yaml`이 administrator로 잠근다 |
| 로봇 작업 준비 | 운용자가 웨이포인트·맵·도크를 준비한다 | Robot `/setup` | 같은 이유. 문법은 procedure, 운용 문서는 spatial |
| 수동 운전 | 운전석 한 사람이 한 로봇을 민다 | Pilot. Robot `console.teleop`은 이행기 | 운전 앱을 하나 더 두면 소유가 다시 둘이 된다. 닫는 방향은 Pilot 링크다 |
| 천장 영상 서비스 | 프레임을 받는다 | Vision. 화면 없음 | 사람 일이 없다. Console이 미리보기를 읽고 Cam이 보낸다 |
| 바닥 확인 전용 앱 | 슬립시트를 넣고 다음 층을 확인한다 | Cell 화면의 named operator 확인 (D-450) | 확인하는 사람이 관제 운용자와 같고, 자격이 같으면 문서가 맞다. 다른 사람·다른 자격이 되기 전에는 앱이 아니다 |

D-410은 설치 화면이 나중에 독립 표면이 될 때 그 문서가 뿌리라고 적는다. 그 조건은 아직 없다. 설치자가 운용 콘솔과 다른 자격으로 접속하거나, 운용 화면 없이 설치 화면만 배포해야 할 때 다시 연다.

### 리팩터는 문서와 모듈에서 한다

1. **문서 경계를 유지한다.** Console은 세 HTML이다. `/console`은 exception(감시·목표·정지), `/console/install`은 procedure(등록·승인·보정), `/console/cell`은 Cell 초안이다. Robot은 `/console`·`/setup`·`/device`다. 운용 문서에 등록·보정 마크업을 다시 넣지 않는다 (D-410 §5). `console.js`는 등록·카메라 승인·맵 보정 뷰를 만들지 않는다.
2. **셸은 배선만 한다.** Console 셸은 토큰, 폴링, 목표 클릭이고, 맵·로스터·대형·신호·추적은 각 모듈이다. DOM 없는 판단은 순수 함수로 둔다 (`address-drift.js`, `poll-gate.js`, `map-fit.js`). Robot은 `panels.yaml`의 패널 하나가 일 하나다. 패널은 자기를 마운트하지 않는다.
3. **쓰기는 그 문서의 모듈에만 둔다.** 설치 쓰기는 `install.js`와 `enrollment.js`·`camera-pairing.js`·`map-fit-view.js`다. Cell 쓰기는 `cell.js`다. 운용 프리뷰의 `vision-view.js`는 읽기만 한다. 공유 파일에 조작 규칙을 쌓지 않는다.
4. **이행기 겹침은 앱을 추가해서 닫지 않는다.** Pilot이 DEVICE 수용을 통과하면 Robot `console.teleop`을 Pilot 링크로 바꾼다 (D-370, D-425). 그 전에 새 조종 기능을 Robot에 넣지 않는다.
5. **패키지 자리를 이번 리팩터로 옮기지 않는다.** 관제 웹은 Fleet 서버가 서빙하므로 `operations/fleet/fleet/server/web`에 둔다. D-427은 최상위 `ui/` 이전을 동결했다. 폴더를 `operations/ui/console`로 옮기는 일은 책임 분리와 별도다.

같은 origin 안의 문서 분리는 이미 1·3의 상당 부분이 코드에 있다. 남은 구현은 경계를 넘는 import와, 셸에 다시 붙는 조작뿐이다. 이 문서는 그 구현을 시작하지 않는다.

### 새 앱을 여는 조건

네 가지가 모두 맞을 때만 `Rosy` + 영어 한 단어 앱을 등록부에 더한다 (D-377, D-425).

1. 그 일을 하는 사람이 기존 화면의 사람과 다르다. 또는 자격이 다르다.
2. 그 일이 기존 문서의 문법과 권한 안에 들어가지 않는다.
3. 소유할 조작이 하나 있고, 그 조작은 지금 다른 표면의 `owns`에 없다. 비상 정지만 예외다.
4. 새 프론트 서버를 만들지 않는다. 로봇 화면은 CORE가, 사이트 화면은 Fleet이, 폰 앱은 그 앱이 서빙한다.

조건을 통과하면 ADR이 `surfaces.yaml`의 `owns` 한 줄과 역할 표를 같은 변경으로 고친다. 메뉴나 폴더를 먼저 만들지 않는다.

지금 이 조건을 통과하는 후보는 없다.

## 검토에서 확인할 것

아래는 이 스냅샷을 읽고 닫을 질문이다. 답을 이 문서가 결정으로 바꾸지는 않는다.

1. 제품 화면 다섯(Robot, Pilot 웹, Pilot 셸, Console, Cam)으로 앱·웹 역할이 닫히는가.
2. 수동 운전의 이행기 겹침을 Pilot DEVICE 수용 전까지 유지하는 현재 결정이 그대로인가.
3. 관제 웹이 Fleet 서버 안에 있는 현재 배치를 유지하는가. 별도 `operations/ui/console`은 D-427로 동결된 목표다.
4. 게임 보드, 제어 진단, Pinky 학습 검수, 레인 뷰어, Face LCD를 제품 역할 표 밖으로 두는 현재 구분이 맞는가.
5. 「관제」라는 말을 Rosy Console에만 쓰는 D-370 규칙이 화면 문구와 문서에서 아직 지켜지는가. 이 검토는 문구를 다시 검색하지 않았다.
6. SRP 제안대로 새 제품 앱 없이, Console 세 문서와 Robot 세 문서의 경계만 유지하는가.
7. 설치 독립 표면과 바닥 확인 앱은, 사람과 자격이 관제 운용자와 갈라질 때까지 열지 않는가.
