## D-358 앱과 표면은 한 역할씩 맡는다 — 역할·이름·아이콘·화면 소유를 한 표로 고정하고, 발견·기기 연결·실패 어휘는 공유 벡터로 하나로 맞춘다

**Status:** Proposed (2026-09-30). 역할 표, 이름·아이콘 규칙, 화면 소유 규칙, 공유할 조각과 이행 순서만 정한다. 코드·리소스·와이어 변경은 하지 않는다. D-2·D-12·D-38·D-330(정지·명령 권한), D-193(로그인 코드), D-257(영상 없는 Fleet)·D-152(대시보드 저주기 미리보기 예외), D-339·D-340·D-345(이름·셸·디자인)를 바꾸지 않는다. 브랜치에 있는 D-341·D-351·D-352·D-354와 Pilot 브랜치 ADR의 결정은 그대로 두고, 이 ADR은 그것들이 착지할 때 맞출 공통 틀만 정한다.

**사용자 확인 (2026-09-30).** 상태는 S1이 main에서 녹색이 될 때까지 Proposed로 둔다(Validation 절). 다음은 사용자가 확인했다.
- 2항 이름표를 승인했다: Rosy 천장 카메라 / Rosy Pilot / Rosy 관제(Fleet 전용) / Rosy 로봇 대시보드. Pilot의 "관제 화면" 버튼은 "로봇 대시보드"가 된다.
- 3항 아이콘 개념을 승인했다: 어두운 둥근 사각 바탕에 `--brand-rose` 점, 천장 카메라 = 천장 막대에 매달린 원, Pilot = 고리 안의 셰브런, Fleet = 한 줄로 이은 2×2 노드 격자, 대시보드 = 로봇 얼굴. 빨강은 비상 정지에만 남긴다.
- 8항 첫 질문을 결정했다: 천장 카메라 앱에는 **정지 전용 자격을 주지 않는다.** 카메라 기능만 두고, 정지는 관제에서 한다는 안내만 둔다.

잇는 결정: [D-2](D-2-cmd-vel.md) · [D-5](D-5-outbound-ws-fleet-rest.md) · [D-12](D-12-mission-fleet.md) · [D-38](D-38-core.md) · [D-193](D-193-login-code-and-credential-lifecycle.md) · [D-257](D-257-site-lane-map-and-overhead-sightings.md) · [D-261](D-261-overhead-camera-app-skeleton.md) · [D-318](D-318-site-camera-preview-rectification.md) · [D-323](D-323-rosy-pilot-teleop-app.md) · [D-330](D-330-fleet-action-admission-stop-and-recovery.md) · [D-339](D-339-surface-and-folder-role-names.md) · [D-340](D-340-app-shell-wraps-web-surfaces.md) · [D-345](D-345-design-philosophy-reaches-every-surface.md) · D-341(브랜치 `docs/d341-overhead-console-pairing`) · D-351(브랜치 `docs/robot-fleet-protocol-conformance`) · D-352(브랜치 `docs/fleet-robot-code-enrollment`, 코드 `feat/fleet-robot-enrollment-s1`) · D-354(브랜치 `feat/console-field-autodetect`) · Pilot ADR(브랜치 `feat/pilot-teleop`).

### Context

사용자 요청(2026-09-30): "앱마다 역할을 분명히 해서 나중에도 각자 역할에 충실하게 한다. 통신이 겹치거나 mDNS로 설정하는 곳은 같은 것을 쓰도록 개선할 방법을 찾아 ADR로 남기고 처리한다." 같은 날 두 가지가 더해졌다. 앱마다 최종 제품 이름과 서로 헷갈리지 않는 아이콘을 정한다. 화면(UI/UX)이 표면끼리 겹치지 않게 조작마다 소유 표면을 하나로 정한다.

2026-09-30 main(`dd8c61b2`)과 관련 브랜치를 읽기 전용으로 조사했다. 요점은 다음과 같다.

**참여자는 여섯이다.**
- 천장 카메라 앱: Android `src/site/overhead/android`, `:app` 모듈 하나, `io.github.livsbittt.rosy.overhead`, `minSdk 26`(`app/build.gradle.kts:12-13`). JPEG를 WSS `rosy-overhead/1`로 Vision에 보낸다. Bearer 헤더, 프레임마다 20바이트 `ROF1` 헤더가 붙는다.
- Site Vision: `src/site/overhead/overhead`. 화면이 없는 서비스다. 영상 수신, 마커 검출, 미리보기 JPEG 서빙(`ingest.py:186-235`, "never from Fleet"), sighting 발행(`publish.py:48-67`)을 맡는다.
- Fleet 관제: `src/site/fleet`. 로스터, 발견, sighting 저장·표시, 미리보기 lease 발급, 정지를 맡는다. `test_no_video_relay.py:45,55`가 영상 import와 영상 라우트를 막는다.
- 로봇 CORE: `src/runtime`. 최종 `cmd_vel` 발행자는 하나다(D-2, `test/test_module_separation.py:186`). 중재와 정지는 CORE가 소유한다(D-38). 평문 HTTP 8080을 쓴다(`gateway/core/node.py:140-161`).
- 로봇 대시보드와 LCD: `src/hmi/dashboard`는 CORE same-origin이다. 운용·작업 준비·설치·정비 세 표면이 있다(`panels.yaml:4-6`). LCD는 입력 장치가 없는 표시 전용이다(`rosy-boot-display.py:203-212`, D-352 대안 절).
- Rosy Pilot: `feat/pilot-teleop`의 `src/hmi/pilot`. **Android가 아니라 PWA**이고 CORE가 `/pilot/`로 서빙한다. D-193 로그인 코드를 `POST /auth/pair`(이름표 "Rosy Pilot")로 바꾼다. 토큰은 sessionStorage에 둔다. WS는 첫 메시지로, REST는 Bearer로 인증한다. Fleet을 부르지 않는다.

**발견(mDNS) TXT 파서가 다섯 벌이고 규칙이 조금씩 다르다.** 원천은 `docs/reference/site-lan-discovery-profile.md:18-24`의 표다(D-351 1항).
- `deploy/site/fleet-mdns.py:19-25,69-96`: Fleet·Vision 광고와 `_rosy-fleet._tcp` 해석. 공통 키를 정확히 일치시키고 중복 키를 거절한다.
- `src/runtime/services/core_features/fleet_agent/discovery.py:16-44`: 위의 `parse_avahi`를 **복사한 것**이다. `TXT` 사전까지 같다(`:18` ↔ `fleet-mdns.py:21`).
- `deploy/site/mdns-bridge.py:17-39`: `_rosy._tcp` 로봇 해석. `network=sta`와 `name`만 보고 `product/role/proto/tls`는 **보지 않는다**(D-351 발견 8). 열 개수 검사도 `< 10`으로, 위의 `!= 10`과 다르다.
- `src/site/fleet/fleet/server/discovery.py:19-95`: 스캔 행을 다시 검사한다. 이름 길이, `.local`, 사설 IPv4, `stage`, `release`.
- Kotlin `OverheadServiceRecord.kt:12-56`: `_rosy-overhead._tcp`에서는 `tls=required`이고 `tls_host`가 해석 호스트와 같아야 한다. `_rosy._tcp`에서는 `product/role/proto/tls` 네 키를 본다.
- 계획만 있는 것: Pilot D-348(브랜치)의 CORE 쪽 `_rosy._tcp` 이웃 목록. 여섯 번째 파서가 된다.

**다른 언어 사이에서 같은 벡터를 읽는 선례가 이미 있다.** `src/site/overhead/protocol/vectors.json`을 Kotlin 시험이 시스템 속성 `rosy.overhead.vectors`로 읽고(`app/build.gradle.kts:37-40`, `Vectors.kt`), Python `overhead/protocol.py`와 `test/test_protocol.py`도 같은 파일을 읽는다. D-351은 공유 벡터 자리로 `test/fixtures/protocol/`을 정했다.

**자격 발급 절차가 다섯 종류다.** 방향과 저장 방식이 제각각이다.

| 자격 | 발급자 | 제시자 → 검증자 | 원문 보관 | 수명 | 근거 |
|---|---|---|---|---|---|
| 브라우저 토큰(`pair-physical`·`pair-admin`) | CORE (LCD 코드·관리자 등록 코드) | 대시보드·Pilot → CORE | 브라우저(session/local storage), CORE는 digest | 168 h / 24 h | D-193, `auth.py:405` |
| 사이트 토큰(`pair-site`) | CORE (LCD 코드를 Fleet이 교환) | Fleet → CORE | Fleet이 AES-GCM 암호문 | 90일 | D-352 2·4항 |
| 카메라 자격(`rosy-pair/1`) | Fleet (콘솔 승인) | 폰 → Vision | 폰, Fleet·Vision은 digest | 180일 | D-341 8·11·12항 |
| 정적 카메라 토큰(`rosyov://`) | 설치자 (`site-cameras.yaml` env, `overhead receive` 즉석 발급) | 폰 → Vision | 폰 DataStore, Compose secret | 무기한 | `protocol.py:135-181`, `cli.py:91-103` |
| FleetAgent `fleet_pairing_token` | 설치자 (`robots.yaml`) | 로봇 → Fleet hub | 양쪽 원문 | 무기한 | D-5, `hub/hub.py:105-107` |

이 밖의 서비스 간 비밀(발견 스캐너 토큰, sighting 토큰, 미리보기 lease, D-341 `pairing_sync_token`)은 사람이 기기를 잇는 절차가 아니다. D-302의 자격 분리 규칙이 다룬다.

**전송과 주소 규칙이 섞여 있다.**
- CORE WS는 첫 메시지 인증이 정본이다. `?token=`은 한 릴리스 동안만 받는다(`api/ws.py:12,148-149`). 그런데 Fleet은 CORE WS에 여전히 `?token=`을 붙인다(`swarm/robots.py:122-131`, `transport.py:222-228`).
- 폰은 받은 호스트 문자열을 그대로 쓴다. D-341 13항은 이름(`tls_host`)을 따라가고 CA를 고정하자고 한다.
- D-352 3항은 로봇 주소를 등록 때 IPv4:포트로 고정하고, 바뀌면 `address_changed`로 멈춘 뒤 확인을 받는다.
- FleetAgent는 재접속할 때마다 `_rosy-fleet._tcp`를 다시 찾고 사이트 CA로 검증한다(`fleet_agent/agent.py:93-97`).

**상태와 실패 어휘가 따로 논다.**
- 상태: Fleet·Vision은 `/healthz` → `{"status":"ok"}`다(`fleet/server/app.py:438`, `ingest.py:170-171`). CORE에는 인증 없는 health가 없다. D-351은 `GET /api/v1`에 `contract_version`을 더하자고 했다.
- 오류 봉투: CORE는 `{"error":{code,message,detail}}`(`api/errors.py:26`)다. Fleet은 별도 코드 목록을 쓴다(`UNAUTHORIZED`·`OPERATOR_IDENTITY_REQUIRED`…).
- WS 닫힘 코드: CORE와 hub는 4401/4403, Vision은 4400/4401/4409, D-341은 4503을 새로 둔다.
- 폰 쪽 분류: `feat/overhead-app-ceiling-ux`의 `NetworkFailure`(UNREACHABLE/REFUSED/UNKNOWN_HOST/TLS/OTHER, `link/NetworkFailure.kt:10-24`)와 `ProblemGuide`다.
- 웹 쪽 중복: 인증 fetch, WS 재연결, 폴링이 대시보드 `client.js`/`app.js`, Fleet `console.js`, Pilot `client.js`/`link.js`/`vision.js`에 세 벌 있다. D-340 6항이 이미 `web_common`으로 모으기로 했다.

**이름과 아이콘도 어긋나 있다.**
- 이름이 없거나 어긋난 곳:
  - 폰 앱은 `app_name`이 `Rosy 천장 카메라`(D-345 4항 준수)지만 런처 아이콘이 없다. `AndroidManifest.xml`에 `android:icon`이 없어 기본 아이콘이 뜬다.
  - Pilot PWA는 `short_name`이 `Pilot`이다(`manifest.webmanifest:3`). D-345 4항("`short_name`도 `Rosy`로 시작")을 어긴다.
  - Pilot 상단 버튼이 로봇 대시보드를 **"관제 화면"**이라 부른다(`src/hmi/pilot/index.html:22`, 브랜치). 그런데 D-339 4항에서 "관제"는 Fleet 화면 이름(`Rosy 사이트 — 관제`)이다.
  - 웹 표면에는 파비콘이 하나도 없다.

**화면 소유가 겹치는 곳이 있다.**
- 수동 운전: 로봇 대시보드 `console.teleop`(`panels.yaml:35-45`, "수동 운전")과 Pilot(D-323).
- 로봇 카메라 보기: 대시보드 `console.camera`(`panels.yaml:46`)와 Pilot 운전석 MJPEG(Pilot D-346).
- 로봇 한도 설정: 대시보드 설치·정비와 Pilot 수동 한도 계단(Pilot D-347).
- 카메라 설치 안내: 폰 천장 UX와 Fleet 카메라 패널의 모서리 보정(D-318·D-354).

**번호 관리 위험.** Pilot 브랜치는 D-328, D-331, D-332, D-346–D-350 번호를 main과 다른 결정에 쓴다. 이 ADR 번호도 D-357이 `er2-feedback-loop` 워크트리에서 선점돼 있어 D-358로 잡았다. main은 같은 날 D-350·D-351을 도크 결정으로 선점했다 — 브랜치의 D-351(프로토콜 적합성)과 겹친다.

### Decision

#### 1. 역할 표 — 이후 ADR과 리뷰는 이 표에 대조한다

| 앱/표면 | 소유한다 | 절대 하지 않는다 | 만든다 | 쓴다 | 권한 |
|---|---|---|---|---|---|
| **천장 카메라 앱** (폰) | 카메라 캡처, 프레임 송신, 설치 위치·방향 안내, 자기 페어링 요청 | 로봇 명령·이동·정지 호출, 로봇 CORE 연결, Fleet 사용자 API 호출, 영상 저장 | JPEG 프레임(`rosy-overhead/1`), 페어링 요청(D-341) | Vision의 `config`·`status`, 발견 레코드 | 카메라 자격 하나(frames ingress 한 source 전용, D-341 11항) |
| **Site Vision** (서비스, 화면 없음) | 영상 수신·보관(최신 1장), 검출, 미리보기 JPEG, 경기장 제안(D-354) | 로봇 명령, 사람 화면, 자격 발급, 좌표를 주행·정책 입력으로 넘기기 | sighting(표시 전용, D-257), 미리보기, 제안 | 폰 프레임, Fleet 자격 digest 목록 | sighting 토큰으로 Fleet에 쓰기만 한다 |
| **Fleet 관제** | 사이트 로스터, 여러 로봇 모니터링, Mission(D-12), 교통·대형, 사이트 정지 요청, 기기 연결 승인·등록 | 영상 중계·저장·디코딩(D-257), 최종 명령 계산, 로봇 설정 쓰기, 수동 운전 | Mission·목표·정지 **요청**, 로스터, 감사 | CORE 상태·이벤트, sighting, Vision lease 경로 | 이름 있는 operator만 승인·등록한다(D-276). 정지 사실은 CORE가 소유한다(D-330, D-351 5항) |
| **로봇 CORE** | 최종 명령·중재·정지(D-2·D-38), 외부 API, 로봇 자격 발급 | Mission 실행(D-12), 사이트 로스터, 영상의 사이트 전송 | 상태·이벤트, 로그인 코드, 토큰 | 대시보드·Pilot·Fleet 요청 | 모든 움직임의 최종 권한 |
| **로봇 대시보드** | 한 로봇의 상세 상태, 작업 준비(웨이포인트·위치 추정·도크), 설치·정비(로봇 설정), 로봇 쪽 자격 목록·회수 | 여러 로봇 관제, Mission, 사이트 기기 승인 | 운용자 요청(CORE API 경유) | CORE API | 역할은 CORE 토큰이 정한다 |
| **로봇 LCD** | 부팅 단계, 이름, 로그인 코드 표시 | 입력 받기, 토큰 원문 표시, 명령 | 없음(표시) | 부팅 상태 파일 | 없음 |
| **Rosy Pilot** (태블릿 PWA) | 한 로봇 직접 수동 운전, 운전석 영상, 운전 보조(Pilot D-349) | 조향 계산을 최종 명령으로 삼기, Fleet 호출, 새 영상 경로(운전석 MJPEG 외), 여러 로봇 관제 | 조종 입력(CORE가 중재) | CORE API·운전석 영상 | 운전석 하나, 최종 권한은 CORE(D-2·D-38) |

표에 없는 새 앱이나 표면은 이 표에 행을 더하는 ADR 없이 만들지 않는다. 행을 바꾸는 ADR은 이 ADR을 부분 대체한다고 적는다.

#### 2. 이름표 — 제품 이름과 탭 제목

D-345 4항(`Rosy <이름>`, `short_name`도 `Rosy`로 시작)과 D-339 4항(`Rosy <범위> — <화면 이름>`)을 그대로 적용한 결과다. 패키지·폴더·applicationId·서비스 종류 이름은 바꾸지 않는다(D-231, D-339 1항).

| 표면 | 한국어 이름 (런처·PWA `name`) | English name | 짧은 이름 | 탭·창 제목 | 비고 |
|---|---|---|---|---|---|
| 천장 카메라 앱 | Rosy 천장 카메라 | Rosy Ceiling Camera | Rosy 카메라 | (네이티브) | `app_name` 유지. 코드 식별자 `overhead` 유지 |
| Rosy Pilot | Rosy Pilot | Rosy Pilot | Rosy Pilot | `Rosy 로봇 — 조종` | 고유명 Pilot 유지(D-345). `short_name` `Pilot` → `Rosy Pilot` |
| Fleet 관제 | Rosy 관제 | Rosy Site Console | Rosy 관제 | `Rosy 사이트 — 관제`(D-339) | "관제"는 이 표면에만 쓴다 |
| 로봇 대시보드 | Rosy 로봇 대시보드 | Rosy Robot Dashboard | Rosy 대시보드 | `Rosy 로봇 — 대시보드`·`— 운용/작업 준비/설치·정비`(D-339) | 다른 표면에서 부를 때도 "로봇 대시보드"다 |
| 로봇 LCD | 로봇 상태 화면 | Robot status display | — | — | 앱이 아니라 아이콘이 없다 |
| Site Vision | 사이트 비전 | Site Vision | — | — | 화면이 없어 아이콘이 없다. 관제 카메라 패널의 출처로만 보인다 |

"관제"는 Fleet 표면에만 쓴다. Pilot의 "관제 화면" 버튼은 "로봇 대시보드"로 바꾼다.

#### 3. 아이콘 — 한 가족, 다른 실루엣

- **가족 규칙.**
  - 모든 아이콘은 `--ground`(#101214) 둥근 사각 바탕에 글리프 하나를 올린다.
  - 모든 아이콘의 같은 자리(오른쪽 위 안전 영역 안)에 `--brand-rose`(#f697e7) 점을 하나 둔다. Rosy 제품임을 나타낸다.
  - 글리프 색은 표면마다 다른 토큰이다.
  - `--status-crit/warn/ok`는 정체성 색으로 쓰지 않는다. 빨강은 정지 버튼에만 남겨야 하기 때문이다(D-280).
  - 흑백으로 바꿔도 **실루엣만으로** 구분돼야 한다. Android 13 테마 아이콘(`monochrome`)이 그렇게 보이기 때문이다.
- 표면마다:

| 표면 | 글리프(실루엣) | 글리프 색 토큰 | 나오는 곳 |
|---|---|---|---|
| 천장 카메라 | 위쪽 가로 막대(천장)에 매달린 렌즈 원(고리+중심점). "T 아래 원" 윤곽 | `--series-primary` #49affd | Android 적응형 런처 아이콘 + 알림 아이콘(기존 `ic_stat_camera` 유지) |
| Rosy Pilot | 고리 안의 위쪽 쐐기(진행 방향 셰브런). "원 속 삼각" 윤곽 | `--brand-rose` #f697e7 | PWA 아이콘 192/512/maskable (기존 PNG 교체) |
| Fleet 관제 | 2×2 노드 격자와 대각선 연결 한 줄(여러 로봇, 지도). "네 점" 윤곽 | `--paper` #eeeeef | 파비콘 SVG, 향후 PWA |
| 로봇 대시보드 | 둥근 직사각 얼굴에 눈 두 개(로봇 얼굴 표면과 같은 정체성). "넓은 사각" 윤곽 | `--robot-1` #b6ddfe | 파비콘 SVG, 향후 PWA |

- **원본은 SVG 하나다.**
  - 표면마다 `src/hmi/web_common/icons/<surface-id>.svg`를 둔다. 108×108 격자에 안전 영역은 가운데 66이다.
  - Android 벡터 드로어블과 PNG는 이 SVG에서 만든 사본이다. 시험이 색 토큰과 도형 좌표를 대조한다(D-345 토큰 사본 규칙과 같은 방식).
- **Android 산출물.**
  - `mipmap-anydpi-v26/ic_launcher.xml`·`ic_launcher_round.xml`을 둔다. `background`, `foreground`, `monochrome` 세 층이다.
  - `drawable/ic_launcher_foreground.xml`과 `ic_launcher_monochrome.xml`을 둔다.
  - 밀도별 레거시 PNG(`mipmap-mdpi…xxxhdpi`)는 **만들지 않는다.** `minSdk 26`이라 모든 기기가 `anydpi-v26` 경로를 탄다. 배포 목록이나 문서용 512 px PNG 하나만 SVG에서 만든다.

#### 4. 화면 소유 표 — 조작마다 소유 표면은 하나다

규칙:
- 소유 표면만 그 조작의 화면을 가진다. 다른 표면은 **소유 표면으로 가는 링크**만 둔다.
- 운전·조작에 꼭 필요한 최소 읽기값은 예외다. 예: Pilot HUD의 속도·배터리. 이것은 "모니터링"이 아니다.
- 한 생산자의 데이터를 두 표면이 다른 목적으로 **소비**하는 것은 중복이 아니다. 같은 조작 화면을 두 벌 만드는 것이 중복이다.

| 조작 | 소유 | 천장 카메라 | Pilot | Fleet 관제 | 로봇 대시보드 | LCD |
|---|---|---|---|---|---|---|
| 사이트 전체 모니터링(여러 로봇·지도·sighting) | **Fleet 관제** | — | — | 소유 | — | — |
| 한 로봇 상세 상태·진단 | **로봇 대시보드**(운용) | — | 운전 HUD 최소값 + "로봇 대시보드" 링크 | 요약 행 + 주소 표시 | 소유 | 부팅 단계·이름 |
| 수동 운전(조이스틱) | **Pilot** | — | 소유 | 없음 | 이행기에만 `console.teleop`(아래) | — |
| Mission·여러 로봇 하달 | **Fleet 관제**(D-12) | — | — | 소유 | — | — |
| 한 로봇 목표·도킹 등 기본 조작 | **로봇 대시보드**(D-12 Local-First) | — | 보조 자율(Pilot D-349)은 누르는 동안만. 목표 편집은 하지 않는다 | Mission 경유 | 소유 | — |
| 로봇 카메라 보기 | 생산자 CORE, 소비 둘 | — | 운전석 실시간(운전 중에만) | 없음(영상 없음) | 모니터링 미리보기 | — |
| 천장 카메라 영상·보정 | Vision 생산, **Fleet 관제** 표시 | 자기 프레이밍 미리보기 | — | 소유(D-318·D-354, 브라우저가 Vision에서 직접 받는다) | — | — |
| 카메라 물리 설치 안내(높이·방향·수평) | **천장 카메라 앱** | 소유 | — | 모서리 확인만(경기장 보정은 관제 소유) | — | — |
| 기기 연결 — 사이트 쪽 승인·등록·회수 | **Fleet 관제 "기기 연결"**(D-352 11항) | 요청하고 확인 코드를 띄운다 | — | 소유 | — | — |
| 기기 연결 — 로봇 쪽 코드·토큰 목록·회수 | **로봇 대시보드**(보안 패널) | — | 자기 로그인만 | — | 소유 | 코드 표시 |
| 로봇 설정(한도·하드웨어·네트워크) | **로봇 대시보드**(설치·정비) | — | 읽기만. 한도 계단(Pilot D-347)은 쓰기를 대시보드로 옮기거나 링크한다 | 없음 | 소유 | — |
| **비상 정지** | **예외 — 모든 운용 표면** | 아래 참고 | 있음 | 있음(`/api/fleet/estop`, D-330) | 있음 | 입력 없음 |

**비상 정지는 일부러 둔 예외다.** 로봇이 움직일 수 있는 동안 사람이 보는 운용 표면에는 모두 정지 버튼이 있어야 한다. 정지 버튼은 링크로 대신하지 않는다. 모든 정지는 CORE의 한 경로로 모인다. 정지 사실은 CORE `safety/state`가 말한다(D-330, D-351 5항). 천장 카메라 앱은 카메라 자격만 가지므로 스스로 정지를 보낼 수 없다. 앱 안에 "관제에서 정지" 안내만 둔다. 폰에는 정지 전용 자격도 주지 않는다(사용자 확인 2026-09-30, 8항).

**지금 겹치는 곳과 결정:**
1. **수동 운전 두 벌.** 대시보드 `console.teleop`은 Pilot이 DEVICE 수용(D-323 Validation)을 통과할 때까지 **이행기 표면**으로 남긴다. 통과한 회차에 이 패널을 "Rosy Pilot으로 조종" 링크 패널로 바꾼다. 두 표면에서 동시에 운전 화면을 늘리지 않는다. 새 조종 기능은 Pilot에만 넣는다.
2. **로봇 카메라 두 소비자.** 중복이 아니다(한 생산자, 목적이 다르다). 다만 대시보드 미리보기는 모니터링용 저빈도로 두고, 운전석 품질의 영상은 Pilot D-346의 운전 중 세션에만 준다.
3. **Pilot의 "관제 화면" 버튼.** 이름이 틀렸다. "로봇 대시보드"로 바꾼다(2항).
4. **로봇 한도.** 설정 쓰기는 대시보드 설치·정비가 소유한다. Pilot D-347 계단 절차가 한도를 쓰면, 착지할 때 쓰기 화면을 대시보드로 옮기거나 대시보드 절차로 링크한다. 이 판단은 Pilot 브랜치 착지 회차가 한다.
5. **카메라 설치 안내와 경기장 보정.** 경계를 위 표처럼 나눈다. 폰은 물리 설치(높이·방향·수평·네 마커 보임)를 맡는다. 관제는 경기장 모서리와 보정을 맡는다. 폰이 모서리를 편집하지 않고, 관제가 폰 설치 절차를 되풀이하지 않는다.

#### 5. 겹치는 통신은 이렇게 하나로 모은다

**5.1 발견: 공유 TXT 벡터 하나, 언어마다 파서 하나.**
- 기계가 읽는 원천은 `test/fixtures/protocol/discovery-txt.v1.json`이다(D-351 3항의 자리). `site-lan-discovery-profile.md` 표는 사람이 읽는 설명으로 남는다. 시험이 둘이 같은지 대조한다.
- 벡터는 서비스 종류(`_rosy._tcp`, `_rosy-fleet._tcp`, `_rosy-overhead._tcp`)마다 받는 레코드와 거절 사유를 담는다. 공통 키는 `product/role/proto/tls`, 선택 키는 `tls_host`·`name`·`stage`·`release`·`network`·`pair`다.
- **거절 사유 어휘는 하나다:** `wrong_type`·`missing_key`·`duplicate_key`·`value_mismatch`·`bad_host`·`bad_address`·`bad_port`·`tls_host_mismatch`·`ap_mode`. 알 수 없는 키는 무시한다.
- **공통 키가 없는 옛 로봇 광고**(프로필 26행)는 거절하지 않는다. `legacy: true`로 받아 관찰 화면에만 쓴다.
- Python의 정본 파서는 `core_common/protocol/discovery_txt.py` 하나다(표준 라이브러리만 쓴다). FleetAgent·Fleet 서버·계획된 CORE 이웃 목록이 import한다.
- `deploy/site/*.py`는 사이트 호스트의 단독 스크립트라 `core_common`을 import할 수 없다. 그래서 자기 사본을 두되 **같은 벡터로 시험**한다. 사본끼리의 동등성은 벡터가 보증한다.
- Kotlin `OverheadServiceRecord`·`RobotCoreServiceRecord`도 같은 벡터 파일을 읽는다(`rosy.overhead.vectors` 방식).
- JS는 브라우저가 mDNS를 못 하므로 파서가 없다.

**5.2 기기 연결: 용어·감사·패널은 하나, 자격 모양은 방향마다 따로.**
- **공통 용어.** 사람이 보는 말은 D-352 11항을 넓힌다.
  - "기기 연결"은 패널 이름이다.
  - 동사는 로봇 **등록**, 카메라 **연결 승인**, 브라우저·태블릿 **로그인**이다.
  - 기록 용어: 자격마다 `발급자`·`제시자`·`검증자`·`보관 방식(digest|암호문|원문)`·`수명`·`회수 경로`를 적는다. 새 기기 연결 ADR은 Context의 자격 표에 한 행을 더한다.
- **감사 표는 하나다.** `device_pairing_audit`에 `device_kind`를 둔다(D-341·D-352 합의). 뒤에 오는 연결 종류(FleetAgent 짝 토큰, D-352 S6)도 같은 표에 `device_kind`로 쓴다.
- **관리 화면은 검증자나 발급자 쪽에 있다.**
  - 사이트가 검증하거나 제시하는 자격(카메라, 사이트 토큰, FleetAgent)은 Fleet "기기 연결"에서 본다.
  - 로봇이 발급한 자격(브라우저·Pilot·사이트 토큰)은 로봇 대시보드 보안 패널에서 보고 회수한다(D-352 2항과 같다).
- **자격 모양을 하나로 합치지 않는다.**
  - 방향이 다르면 누가 원문을 가져야 하는지가 다르다. Fleet은 카메라 자격의 **검증자**라 digest만 둔다(D-341). 로봇 자격의 **제시자**라 암호문을 둔다(D-352 4항).
  - 브라우저 토큰은 사람이 들고 다니는 짧은 수명 자격이다.
  - 하나로 합치면 가장 약한 쪽(원문 보관, 긴 수명)에 전체가 맞춰진다.
  - 정적 `rosyov://`와 `fleet_pairing_token`은 되돌림·벤치 경로로 남는다. 새 사이트는 페어링 경로를 기본으로 쓴다.

**5.3 주소: 이름을 따라갈지 고정할지는 한 규칙으로 판정한다.**
- **서버를 인증하는 채널은 이름을 따라간다.** 고정한 CA나 호스트명 검사가 있는 TLS가 여기에 든다. 광고는 주소 후보만 공급하고, 신원은 TLS가 증명한다. 해당: 폰 → Vision(D-341 13항), FleetAgent → Fleet.
- **서버를 인증하지 못하는 채널은 주소를 고정한다.** 평문 HTTP CORE가 여기에 든다. 주소가 바뀌면 사람이 확인할 때까지 자격을 보내지 않는다. 해당: Fleet → CORE(D-352 3항). Pilot·대시보드는 CORE가 same-origin으로 서빙하고 토큰이 origin에 묶이므로 origin이 곧 고정 주소다.
- **정지만은 예외다.** 고정 주소로 계속 보낸다(D-352 3항). 정지가 닿지 않는 위험이 더 크기 때문이다.
- 그러니 D-341과 D-352는 모순이 아니라 같은 규칙의 두 결과다. CORE가 TLS와 장치 신원 증명을 갖게 되면 Fleet → CORE도 이름 따라가기로 옮길 수 있다. 그 전환은 별도 ADR로 한다.
- 같은 이름이 여러 주소에 보이면 어느 채널이든 자동 선택을 멈추고 `conflict`로 둔다(프로필 규칙 2).

**5.4 전송: 토큰은 URL에 싣지 않는다.**
- REST는 `Authorization: Bearer`다. WS는 업그레이드 헤더나 첫 메시지로 인증한다.
- `?token=`은 새 코드에 쓰지 않는다. Fleet의 CORE WS 클라이언트(`swarm/robots.py:122-131`)는 첫 메시지 인증으로 옮긴다. CORE 쪽 `?token=` 수용은 그 뒤에 닫는다(`api/ws.py:12`의 한 릴리스 약속).
- WSS는 사이트 CA 하나만 믿는다. 앱 전역 신뢰 저장소를 바꾸지 않는다(D-341 9항).

**5.5 상태와 실패 어휘.**
- **공개 상태 모양은 하나다.** 토큰 없이 답하는 health는 `{"status":"ok"|"degraded"|"down","role","proto","contract_version"}`다. `role`·`proto`는 TXT와 같은 값이다. 이렇게 하면 광고와 실제 리스너가 맞는지 탐침 한 번으로 본다(프로필 26행, D-351 4항). Fleet·Vision `/healthz`와 CORE `GET /api/v1`(D-351 2항)이 이 모양으로 수렴한다. 필드를 더하기만 하고, 기존 `status` 값은 유지한다.
- **실패 분류는 클라이언트 쪽 공유 벡터 하나다.**
  - 파일은 `test/fixtures/protocol/failure-classes.v1.json`이다.
  - 분류는 `unreachable`·`refused`·`unknown_host`·`tls_untrusted`·`auth_final`·`auth_retry`·`forbidden`·`protocol_mismatch`·`busy`·`conflict`다.
  - 입력은 예외 종류, HTTP 상태, 서버 오류 코드, WS 닫힘 코드다. 예: 4401 → `auth_final`, D-341 4503 → `auth_retry`, 4403 → `forbidden`, 4409 → `conflict`.
  - 폰 `NetworkFailure`/`ProblemGuide`와 D-340 6항의 `web_common` 연결 모듈이 이 벡터로 시험한다.
- **서버 오류 봉투를 하나로 바꾸는 일은 하지 않는다.** CORE 봉투는 API 계약이다. 클라이언트 분류만 공유한다.

**5.6 Android 공유 모듈: 지금은 만들지 않는다.**
- 지금 Kotlin 앱은 천장 카메라 하나뿐이다. Pilot은 PWA다.
- 두 번째 Kotlin 소비자가 실제로 생기면(D-340 2항의 Capacitor 셸 조건이나 네이티브 앱) 그 회차에 NSD 발견, CA 고정 OkHttp, 설정 저장, 실패 분류를 모듈로 뽑는다.
- 그때 형식은 **Gradle included build**(`includeBuild`)다. 두 앱은 각자 Gradle 루트이고 colcon 밖이다(`COLCON_IGNORE`, D-340 3·4항). 복사 모듈과 동등성 시험 방식은 두 사본이 늘 어긋날 여지를 남긴다. 반면 included build는 applicationId가 다른 두 앱에 소스 한 벌을 준다.
- 그 전까지 공통성은 5.1·5.5의 **벡터**가 보증한다.
- 웹 쪽 중복(세 벌)은 D-340 6항대로 `web_common` 연결 모듈 하나로 모은다. 대상은 Pilot이 main에 착지하는 회차다.

#### 6. 따로 남겨야 하는 것 (합치지 않는다)

- 최종 명령과 정지 권한은 CORE 하나다(D-2·D-38). Fleet과 Pilot의 명령은 요청이다.
- Mission은 Fleet 하나다(D-12). 대시보드와 Pilot은 기본 조작만 한다.
- Fleet은 영상을 다루지 않는다(D-257, `test_no_video_relay`). 기기 연결 라우트도 영상 정규식에 걸리지 않게 짓는다(D-341 2항). Vision은 사람 화면과 명령을 갖지 않는다.
- 카메라 자격은 frames ingress 전용이다. 로봇·Fleet 사용자 API에 쓰지 못한다(D-341 11항). 이 ADR의 공유는 **어휘·벡터·감사**이지 자격 자체가 아니다.
- 자격 모양과 보관 방식은 방향마다 다르다(5.2).

#### 7. 이행 순서 — 진행 중 브랜치와의 관계

1. **이 ADR과 계획**(이 브랜치): 문서만 둔다.
2. **S1 발견 벡터·파서**(main 직행): 진행 중 브랜치와 겹치는 파일이 적다. `mdns-bridge.py`가 공통 키를 검사하게 되어 D-351 발견 8을 닫는다. D-351 브랜치가 먼저 착지하면 `test/fixtures/protocol/` 폴더를 그쪽이 만들고 S1이 파일을 더한다.
3. **S2 역할 경계 시험**: 역할 표를 시험으로 고정한다. 예: 카메라 앱 코드에 CORE·Fleet 사용자 API 경로가 없다, Pilot 코드에 `/api/fleet`이 없다, Vision에 로봇 명령 경로가 없다. 대상이 main에 있는 표면부터 시작하고, Pilot 시험은 Pilot이 착지할 때 더한다.
4. **S3 이름·아이콘**: 폰 앱 아이콘과 웹 파비콘은 main에서 한다. Pilot `short_name`과 버튼 이름은 Pilot 브랜치 착지 회차에 맞춘다(D-345 51행과 같은 방식).
5. **S4 화면 소유**: 대시보드 teleop 링크 전환은 Pilot DEVICE 수용 뒤에 한다. 카메라 설치와 보정의 경계는 D-354 착지 때 확인한다.
6. **S5 기기 연결 용어·감사**: D-341과 D-352 중 먼저 착지하는 쪽이 패널 틀과 `device_pairing_audit`를 만든다(D-352 11항). 이 ADR은 `device_kind` 확장 규칙과 관리 화면 위치만 더한다.
7. **S6 실패 분류 벡터**: `feat/overhead-app-ceiling-ux`의 `NetworkFailure`가 착지한 뒤 한다. 웹 쪽은 D-340 6항 회차에 한다.
8. **S7 전송·상태 정리**: Fleet의 CORE WS `?token=` 제거와 공개 상태 모양이다. D-351 계약 스냅샷 회차와 함께 간다.
9. **조건부 S8 Android 공유 모듈**: 두 번째 Kotlin 소비자가 생길 때만 한다.

#### 8. 정하지 않는 것

- ~~폰(천장 카메라 앱)에 정지 전용 자격을 줄지.~~ **사용자가 2026-09-30 정했다: 주지 않는다.** 카메라 기능과 "정지는 관제에서" 안내만 둔다. 설치자가 사다리 위에서 로봇을 멈춰야 하는 현장 요구가 새로 기록되면 새 ADR로 다시 연다. 그 경우에도 frames 자격과 섞지 않는다.
- CORE의 TLS·장치 신원 증명 도입. 5.3의 Fleet → CORE 이름 따라가기 전환 조건이다.
- mDNS 서비스 인스턴스 이름(`ROSY %h`, `ROSY Fleet %h`, `ROSY Overhead %h`)을 2항 이름표에 맞출지. 표시용이지만 이미 설치된 광고와 문서에 퍼져 있다.
- 경기 보드(`game-board`)·제어 진단·시뮬 라이브 뷰의 아이콘. 운용자 설치 앱이 아니므로 이번 범위 밖이다.
- Pilot 브랜치의 ADR 번호 충돌(D-328·D-331·D-332·D-346–D-350을 main이 다른 결정에 씀). 착지할 때 D-346 4항대로 새 번호로 바꿔야 한다. 이 ADR은 번호를 고치지 않는다. 같은 위험이 D-351에도 있다: main이 2026-09-30 D-351을 도킹 재시도 결정으로 선점했으므로(`2e0b699a`), 이 ADR이 인용하는 브랜치 `docs/robot-fleet-protocol-conformance`의 D-351(프로토콜 적합성)은 착지 때 새 번호를 받아야 하고, 그때 이 ADR의 D-351 인용을 그 번호로 읽는다.
- 폰 앱의 영어 표시 여부(현재 한국어 전용 문자열).

### Alternatives

- **역할을 ADR마다 산문으로 두고 표를 만들지 않는다.** 거부한다. 겹침은 이미 생겼다: 수동 운전 두 벌, "관제" 이름 충돌, TXT 파서 다섯 벌. 대조할 표가 없으면 리뷰가 잡지 못한다.
- **발견 파서를 공유 패키지 하나로 import한다.** 거부한다. 사이트 호스트 단독 스크립트, 로봇 CORE, Android가 같은 패키지를 설치할 수 없다. 공유할 단위는 코드가 아니라 벡터다(`vectors.json` 선례).
- **기기 연결 자격을 한 모양으로 통일한다.** 예: 모두 Fleet 발급, 모두 digest. 거부한다. Fleet이 로봇에 자격을 제시하려면 원문이 필요하다(D-352 4항). 로봇에는 입력 장치가 없다. 방향을 무시한 통일은 보관을 약하게 하거나 절차를 불가능하게 만든다.
- **이름 따라가기나 주소 고정 중 하나로 통일한다.** 거부한다. 평문 CORE에서 이름을 따라가면 먼저 광고한 누구에게나 Bearer를 보낸다. TLS 채널에서 주소를 고정하면 DHCP가 바뀔 때마다 사람이 다시 붙여야 한다. 채널이 서버를 인증하는지로 가르는 규칙 하나가 둘 다 설명한다.
- **Android 공유 모듈을 지금 만든다.** 거부한다. 소비자가 하나이고 Pilot은 PWA다. 빈 골격을 미리 만들지 않는다(D-231, D-340 대안 절).
- **아이콘 색만 다르게 하고 글리프를 같게 한다.** 거부한다. 테마 아이콘(흑백)과 색각 차이에서 구분이 사라진다. 실루엣이 먼저다.
- **정지도 소유 표면 하나(Fleet)로 모은다.** 거부한다. 정지는 사람이 지금 보고 있는 화면에서 바로 눌러야 한다. 링크는 정지 시간을 늘린다.

### Consequences

- 새 표면이나 새 연결 절차를 여는 ADR은 1항 역할 표, 4항 소유 표, 5.2 자격 표에 각각 한 행을 더하거나 이 ADR을 부분 대체한다고 적어야 한다.
- 발견 규칙을 바꾸려면 벡터 파일을 바꿔야 하고, 그러면 Python·Kotlin 시험이 함께 깨진다. 사본이 조용히 어긋나는 경로가 막힌다.
- 대시보드 수동 운전은 이행기 표면이 된다. Pilot 수용 전에는 사용자 경험이 바뀌지 않는다.
- Pilot 브랜치는 착지할 때 이름(`short_name`, 버튼), 역할 경계 시험, ADR 번호를 맞추는 일을 떠안는다.
- 아이콘 원본이 `web_common/icons/`에 생기므로 표면 레지스트리(`surfaces.yaml`)에 `icon` 항목이 늘어난다.

### Validation

증거 등급(D-91):
- **SOURCE/LOCAL**: 벡터 파일, Python·Kotlin 파서 시험, 역할 경계 시험, 이름·아이콘 레지스트리 시험, 하네스 lint. Windows 호스트에서 `python`으로 돌린다. Kotlin은 `gradlew testDebugUnitTest`로 돌린다.
- **G2(육안)**: 아이콘 네 개를 홈 화면 크기(48 dp), 테마 흑백, 원형 마스크로 나란히 캡처한다. 서로 구분되는지 사람이 확인한다.
- **DEVICE**: 실제 폰 런처의 아이콘과 이름, 실제 사이트 LAN에서의 `_rosy._tcp`/`_rosy-overhead._tcp` 발견(옛 이미지 광고 포함). 호스트 시험 통과는 DEVICE가 아니다.
- **FIELD**: 정지 도달성은 이 ADR이 새로 주장하지 않는다. D-330·D-351 5항의 기존 게이트를 따른다.

이 ADR은 Proposed다. 다음 두 조건이 모두 충족되면 Accepted로 올린다. S1(발견 벡터)이 main에서 녹색이다. 역할 표에 대한 사용자 확인이 있다(8항 질문 포함).

### References

`docs/reference/site-lan-discovery-profile.md`, `deploy/site/fleet-mdns.py`, `deploy/site/mdns-bridge.py`, `deploy/robot/pinky_pro/native/rosy-boot-status.py:252-278`, `src/runtime/services/core_features/fleet_agent/discovery.py`, `src/site/fleet/fleet/server/discovery.py`, `src/site/overhead/protocol/vectors.json`, `src/site/fleet/test/test_no_video_relay.py`, `src/hmi/dashboard/panels.yaml`, `src/hmi/web_common/surfaces.yaml`, `src/hmi/web_common/tokens.css`. 실행 계획: [2026-09-30 site app roles and shared link plan](../plans/2026-09-30-site-app-roles-and-shared-link-plan.md).
