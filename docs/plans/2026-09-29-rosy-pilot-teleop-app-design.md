# 2026-09-29 Rosy Pilot 원격 조종 앱 설계 (D-323)

상태: 설계 승인(구현 전). 실행 계획은 별도 파일로 이어 붙인다.
관련 결정: D-323(이 설계), D-1(단일 프로세스), D-2(cmd_vel 단일 발행자), D-23(임베디드 정적 대시보드 패턴),
D-193(토큰 저장 규칙), D-226(비공개 자료 배치), D-275(카메라 관측선 분리), D-296(기기별 최종 명령 소유).
계약: `ROSY API & Protocol Reference.md` v1.21(capabilities.runtime), SAF-002(WS watchdog·감사 로그).

## 1. 배경과 목적

Pinky·OMX 등 기기를 브라우저(휴대폰 포함)에서 원격 조종할 전용 표면이 필요하다. 기존 operator
dashboard는 기기 1대당 관제 콘솔이라 직접 잡는 조종 surface 로는 무겁다. 이 앱(Rosy Pilot)은
조종에만 특화한다: 영상 위 HUD, 홀드형 컨트롤, 입력 장치 조정, 카메라 증거 확보.

역할 구분: **dashboard = 관제(내려다보는 콘솔), pilot = 조종(직접 잡는 스틱)**.

## 2. 범위

### v1 (Pinky)

- 대상: Pinky CORE 1대, same-origin 접속(현장 LAN, VPN/Tailscale 보완).
- 주행 teleop: 가상 패드·페달(클릭/터치), 게임패드, 키보드.
- 전방 카메라 스트리밍 + 스냅샷/클립 확보.
- 입력 장치 조정 UI(축 매핑·데드존·감도·스케일).
- PWA 설치(manifest + service worker, 이미지 버전과 같은 캐시 키).

### 비목표 (v1)

- 인터넷 경유 중계(Fleet 릴레이) — catalog 확장점만 남긴다.
- OMX 실기 조종 — 드라이버 슬롯과 화면 자리만 선행한다(§10).
- 맵 편집, 미션/태스크, swarm, 도킹 UI — dashboard/Fleet 관할.
- 새 영상 전송 경로(MJPEG/WebRTC) — 기존 인증 JPEG 폴링을 재사용한다.

## 3. 이름과 배치

- 제품명 **Rosy Pilot**, ROS 패키지명 `pilot`(저장소 규칙: `rosy_*`/`pinky_*` 금지 준수).
- 소스: `src/hmi/pilot/`(hmi 그룹, 정적 브라우저 자산 — D-23 패턴). ament_cmake 로 `share/pilot`
  설치, `core_api_web`의 `api/app.py` 자산 목록에 등록해 CORE 가 `/pilot/` 로 서빙.
- **서빙 경로(계약)**: 조종 `http://<host>/pilot`(자산 `/pilot/assets/*`), 관제는 기존 그대로
  `http://<host>/` → `/dashboard`(역할 표면 `/{console,setup,device}`). 두 앱은 pilot 상단의
  조용한 버튼으로 왕래한다. PWA(T10)는 `start_url=/pilot`, `scope=/pilot` 로 설치 아이콘이
  앱별로 분리된다.
- same-origin 만 통신(`/api/v1`, `/ws/*`). CORS 신규 개방 없음. 앱은 이미지와 함께 배포되므로
  앱↔CORE API 버전 정합성이 이미지 단위로 보장된다.

### 3.1 접속·발견 경로(mDNS)

- 진입 주소는 IP 가 아니라 **검증된 호스트네임**이다: `http://<hostname>.local/pilot/`.
  현장 LAN 발견 규칙 v0.1(`docs/reference/site-lan-discovery-profile.md`)에서 SRV
  target 이 `<hostname>.local` 이며 주소 식별자는 호스트네임이다.
- 태블릿(Android)은 OS 의 mDNS 해상으로 `.local` 을 연다. 브라우저에는 발견 API 가
  없으므로 **앱이 스캔하지 않는다** — same-origin 원칙은 그대로다.
- 입력 없는 진입: CORE 가 `_rosy._tcp.local` 을 광고하고(Avahi, `feat/addressless-mdns`
  진행 중) QR(`http://<hostname>.local/pilot/`)로 연다 — 규칙 v0.1 이 이미 허용하는
  진입 수단이다. QR 발행 위치(대시보드 장치 카드·스티커)는 후속 태스크.
- 채택된 주소는 이후 바뀌지 않는다(규칙 v0.1). 토큰·Wi-Fi 자격은 TXT/mDNS 에 두지
  않는다.

## 4. 패키지 구조

```
src/hmi/pilot/                    # ROS 패키지 pilot (ament_cmake → share/pilot)
├── package.xml / CMakeLists.txt
├── AGENTS.md · progress.md · logs.md · index.md      # D-61 harness
├── index.html                    # web_common template.html 기반 ui-shell + ui-topbar
├── manifest.webmanifest          # PWA 메타 (Rosy Pilot, standalone)
├── sw.js                         # 캐시 키 = 이미지 버전
├── styles.css                    # 표면 규칙만 — tokens/components 는 web_common 링크(D-130.3)
├── app.js                        # 부트, 화면 전환, 역할·capability 게이트
├── client.js                     # dashboard client.js 패턴 재사용: whoami, 토큰 저장(D-193)
├── link.js                       # DeviceSession: WS auth → teleop 채널, 백오프 1s→30s
├── stick.js                      # 입력→{linear, angular} 순수 매핑(스케일·데드존·곡선)
├── drivers/
│   ├── registry.js               # 기기 종류 → 드라이버 (확장점)
│   └── pinky_core.js             # capabilities 조회 · WS teleop · e-stop
├── screens/
│   ├── connect.js                # 접속 게이트 화면
│   ├── drive.js                  # 주행 화면(§5.2)
│   └── inputs.js                 # 입력 장치 조정 화면(§5.3)
└── test/                         # ROS-free pytest + Playwright(§9)
```

import 방향은 dashboard 와 같은 단방향: `dom/ui(web_common) ← client ← link/stick ← screens ← app`.

## 5. 화면 설계

### 5.1 connect — 접속 게이트

`GET /api/v1/auth/whoami` 로 역할 확인(viewer 는 조종 차단 + 안내), capabilities(v1.21
`runtime.truth`)로 `teleop` 플래그와 `runtime.drive` 확인. `motor/ready: false` 이면 서버가 이미
teleop 을 내리고 있으므로 앱은 `withheld.reasons` 를 운용자 말로 보여주고 진입을 막는다.

### 5.2 drive — 게임식 주행 화면 (NFS 계열)

- **영상 풀블리드**: 전방 카메라 프레임이 화면 전체. 상태는 HUD 오버레이로 얹는다(web_common
  tokens 색만 — 임의 색 금지).
- **HUD**: 상단 상태 배지(연결·역할·capability·배터리), 좌하단 속도 readout(명령 linear/angular
  실측치), 우상단 e-stop(항상 노출, `ui-button kind=irreversible`).
- **컨트롤(클릭/터치 조종)**: 좌측 **원형 스티어링 휠**(NFS 계열 — Pointer Events 로
  터치점 각도 → `steer`, 뗄 때 즉시 0), 우측 전진/후방 **홀드 페달**(→linear).
  누르고 있을 때만 움직인다. 회전 각도는 조향 클램프로 묶는다.
- **게임패드**: Gamepad API 폴링, 연결하면 자동 인계(매핑은 §5.3 설정). 연결 끊기면 즉시 0.
- **키보드**: 화살표/WASD(데스크톱 검증용).
- **속도 프리셋**: 저속/중속/고속 스케일 토글. 기본값은 저속.
- 모든 입력 경로는 동일한 **hold-to-drive(~100ms)** 원칙 아래: 손을 떼면·탭이 화면을 벗어나면
  (`visibilitychange`)·게임패드가 끊기면 즉시 0 발행.

### 5.3 inputs — 입력 장치 조정

- 게임패드: 축 매핑(어느 축이 linear/angular), 축 반전, 데드존, 감도 곡선(선형/지수), 최대 스케일.
- 가상 컨트롤: 패드 크기, 좌/우손 배치, 페달 감도.
- 키보드: 키 바인딩.
- **입력 미리보기 패널**: raw 입력 → 매핑 결과를 실시간 readout — 조정 즉시 확인(캘리브레이션 UX).
- 저장: 브라우저 localStorage(개인 선호 — 기기 설정은 CORE 관할과 분리). 기본값은 안전 쪽
  (저스케일·넓은 데드존).

## 6. 카메라: 스트리밍·캡처·다운로드

- **스트리밍**: 기존 인증 JPEG 폴링(`/api/v1/vision/front/status` + frame)을 재사용한다. dashboard
  `vision.js` 팩토리 패턴 그대로, pilot 은 풀스크린 표기만 다르게. stale 프레임은 HUD 에 STALE 배지.
- **스냅샷**: 현재 프레임 즉시 다운로드(`saveCameraFile` 재사용).
- **클립 녹화**: 조종 세션 녹화 — `camera-capture.js` 바운드 재사용(최대 5분/60MB), 명령
  타임라인(coalescing) 포함.
- **증거 업로드**: 기존 bounded evidence 저장(`vision_evidence.py`) 재사용. pilot 이 새 저장 경로를
  만들지 않는다.
- 로컬 세션 기록은 `data/teleop/`(비추적, D-186).

## 7. 안전과 오류 처리

- **2겹 안전**: 클라이언트(hold-to-drive, 탭 이탈→0, 게임패드 끊김→0, WS 끊김→0 발행 후 종료) +
  CORE(WS watchdog·감사 로그 SAF-002, capability 박탈 409).
- **e-stop**: 모든 화면에서 항상 닿는 버튼 → 기존 e-stop API. 문구는 triage 규칙 그대로 — CORE 의
  정지는 소프트웨어 정지이며 "전원 차단"이라 말하지 않는다.
- **오류 처리**(dashboard 패턴 동일): WS 4401 → whoami 재확인 / 4403 → 재시도 없음 / 그 외 백오프
  1s→30s. 재연결 중 스틱·페달 비활성 + 상태 배지. 조종 중 409 수신 시 즉시 조종 중단 + 이유 표시.

## 8. 보안

- 토큰: D-193 규칙 그대로(만료 없는 토큰은 sessionStorage, "로그인 유지" 만 localStorage). 토큰을
  URL·쿠키·콘솔에 두지 않는다. WS 는 `?token=` 없이 `{"type":"auth"}` 첫 프레임.
- 실기 주소·계정·채운 설정 값은 `private/`(D-226). 공개 문서에는 `<robot-ip>` 표기.

## 9. 테스트와 증거

- **ROS-free pytest** `src/hmi/pilot/test/`: stick 매핑 순수 함수(데드존·곡선·스케일·반전 대칭),
  link 상태머신(4401/4403/백오프), web_common 규칙 준수(ui-shell·ui-button kind·색 드리프트).
- **Playwright**: 가짜 CORE 대상 접속→게이트→페달 클릭→WS 프레임 캡처(`test_dashboard_browser.py`
  패턴). PWA 설치·오프라인 캐시 동작.
- **CORE 쪽 변경분**(자산 라우트 등)은 gateway 테스트에 추가.
- 게이트: host pytest = SOURCE/SIM. 실기 Pinky 주행 확인 = DEVICE. 현장 수용 = FIELD. 증거는
  `docs/validation/pilot-<YYYY-MM-DD>/`. host 통과는 기기·현장 수용이 아니다.

## 10. OMX·Fleet 확장 경로

- **OMX**: `drivers/registry` 에 kind 등록 + `drivers/omx_local.js` + `screens/arm.js` 추가만으로
  확장. 단, OMX 로컬 컨트롤러의 teleop API 계약이 API Ref 사이클을 통해 확정된 뒤에만(D-296: 팔
  최종 명령은 OMX 로컬 소유). pilot 은 어떤 기기 종류도 ROS 를 몰라야 한다(SRS §1.3).
- **Fleet**: 관제 PC 중계·원격(외부망) 접속이 필요해지면 앱은 그대로 두고 catalog 의 기기 목록
  출처만 확장한다. 최종 명령 소유는 그대로 기기 로컬(D-12).
- **설치형(D-328)**: PWA 로 우선한다 — manifest(standalone·가로·scope `/pilot`), 서비스 워커는
  앱 셸만 캐시하고 `/api/*`·`/ws/*` 는 네트워크 전용(오프라인 조종 금지), Wake Lock 은 T7.
  Capacitor 네이티브 래퍼는 스토어/APK 배포·화면 꺼짐 조종 등 네이티브 전용 수요가 **실측될
  때까지** 보류 — 앱↔CORE 버전 스큐와 두 번째 배포 원장(Gradle·서명)을 만들지 않기 위해서다.
- **조종 대상 확장(D-331)**: 기기 종류별 드라이버 레지스트리로만 수용한다. 장치별 조종
  컨트롤(OMX 그리퍼·팔 위치 이동 등)과 아이콘은 그 장치의 API 계약이 노출하는 능력에서만
  생기며 화면 파일(`screens/<device>.js`) 하나가 소유한다. Pinky 가제보 주행이 최우선.

### 10.1 입력 모델과 조작 프로필 (2026-09-29 가제보 실측 반영)

입력은 세 층으로 나눈다. 앞 두 층은 기기를 모르고, 기기 차이는 세 번째 층만 안다.

| 층 | 모듈 | 하는 일 |
|---|---|---|
| 입력원 | `screens/*`, 게임패드·키보드 | 손가락·축·키를 `{kind, …}` 원시 입력으로 |
| 의도 | `stick.js` (순수) | 데드존(2 축은 원형)·감도 곡선·부호 규약·제자리 스냅 → 정규화 의도 |
| 명령 | 드라이버 `profile` + 기기 한도 | 의도 × (기기 한도 × 프리셋 × 정밀) → 기기 명령 |

- **부호**: REP-103 을 그대로 쓴다(angular > 0 = 반시계·좌회전). 화면·게임패드 x 오른쪽 + 는
  `stick.js` 한 곳에서만 뒤집는다. 가제보 실측: angular +0.5 → yaw +18°(반시계). 이 규약 이전
  매핑은 휠을 오른쪽으로 꺾으면 왼쪽으로 돌았다.
- **한도**: 프리셋은 절대값이 아니라 CORE 가 실제 허용하는 수동 상한(`GET /api/v1/safety/state`
  `limits.manual_*`·`max_*`·`session_linear` 중 작은 값)의 비율(저 0.4·중 0.7·고 1.0)이다.
  CORE 는 축마다 따로 자르므로(box clip) 앱이 한도를 넘겨 보내면 저·중·고가 같아지고 회전
  반경이 틀어진다. 앱이 먼저 한도 안에 둔다.
- **제자리 회전**: 전용 홀드 버튼(↺/↻, 키보드 Q/E, 게임패드 LB/RB)과, 스틱을 수평 ±12° 안으로
  민 입력이 모두 `linear = 0` 회전이다. 스냅이 없으면 손가락의 작은 상하 성분 때문에 제자리
  회전이 호로 샌다. HUD 는 제자리 회전을 별도 배지로 보인다.
- **정밀**: 한도에 0.3 을 곱하는 모드. 팔 조그의 속도 배율과 같은 개념이다.

조작 프로필(드라이버의 `profile`)이 화면이 그릴 조작부를 정한다.

| kind | command | 조작부 | 상태 |
|---|---|---|---|
| `base` | `velocity` (REST teleop, hold-to-drive) | 2 축 스틱·페달·제자리 회전·정밀 | Pinky v1 등록 |
| `arm` | `jog` | 관절/직교 공간 선택, 연속 조그(홀드) + 단계 조그(1 회 1 증분), 그리퍼, 데드맨 | HOLD — 계약 없음 |

팔 정밀 조작의 원칙(계약이 열릴 때 그대로 구현한다):

1. **최종 명령은 기기 로컬 소유**(D-296). 앱은 관절 목표를 계산하지 않고 "이 축을 이만큼/이
   속도로" 라는 조그 의도만 보낸다. 역기구학·충돌·가동 범위는 OMX 로컬 컨트롤러가 판정한다.
2. **단계 조그는 폐루프**다. 한 증분을 보내고 기기 관절 상태(readback)가 그 증분을 반영한 뒤에만
   다음 증분을 받는다. 응답 없는 재전송은 하지 않는다(UNKNOWN 은 재제출 권한이 아니다, API Ref
   §10.12 와 같은 원칙). 관절 상태가 `max_joint_state_age_s`(기본 0.5 s)보다 오래되면 조그를
   막는다(`command_owner.ArmCommandConfig`).
3. **연속 조그는 주행과 같은 hold-to-drive**: 100 ms 주기, 놓으면 즉시 0, 기기 워치독보다 짧은
   요청 시한. 속도 상한은 기기가 알려주는 값 × 프리셋 × 정밀.
4. **증분 크기는 기기가 알려준다**(예: 관절 0.5°/1°/5°, 직교 1/5/10 mm). 앱에 상수로 두지 않는다.
5. 현재 OMX 계약(API Ref v1.48 §10.12)은 Site Fleet→OMX 로컬 UDS 의 작업 단위(`PICK_PLACE`)
   계약이며 브라우저 조그 경로가 아니다. 그래서 `arm` 드라이버·화면은 등록하지 않는다. 필요한
   것은 OMX 로컬 컨트롤러의 조그 API(연속/단계, 관절 상태 readback, 한도·증분 광고)이고, 그
   계약이 API Ref 사이클로 확정되면 `drivers/omx_local.js`(profile `arm`) + `screens/arm.js` 를
   더한다.

### 10.2 송신 타이밍 (가제보 실측 반영)

- 주기는 **발행 시작 시각** 기준 100 ms 다. 응답 시각 기준이면 지연만큼 주기가 늘어 CORE
  워치독(500 ms)을 넘긴다.
- 한 번에 한 요청만 날린다(겹치면 서버 도착 순서가 뒤집힐 수 있다). 날아가는 동안 들어온
  입력은 최신 하나만 남긴다. 요청 시한은 400 ms — 한 요청이 멈춰도 다음 명령이 워치독 전에
  나간다.
- 놓으면 0 을 즉시 보내고, 날아가던 움직임이 늦게 도착할 수 있으니 0 을 한 번 더 덮는다. 유휴
  중엔 0 을 3 번 보낸 뒤 조용해진다(감사 로그·`manual_active` 도배 방지 — 배터리 복귀 정책이
  유휴 pilot 에 막히지 않는다).
- 수동 모드(`POST /api/v1/mode MANUAL`)가 200 을 낸 뒤에만 명령을 보낸다. 409 로 막히면
  "수동 모드 다시 잡기"로만 재개한다.
- 카메라 프레임은 CORE 하한(0.4 s)보다 자주 당기지 않는다. 더 당기면 429 만 늘고 그 요청이
  teleop 과 같은 브라우저 연결 풀을 잡아먹는다.

## 11. 변경 이력

- 2026-09-29 최초 작성. 브레인스토밍 세션에서 형태(PWA)·네트워크 범위(LAN+VPN)·v1 범위(Pinky)·
  이름(pilot)·서빙(CORE same-origin) 확정, NFS 계열 HUD/클릭 조종/카메라 요구 반영.
  동시 진행 Isaac 세션이 `docs/logs.md`에서 D-322를 먼저 사용해 이 설계는 D-323으로 재번호부여했다.
- 2026-09-29 가제보 실조종 검증 반영: §10.1 입력 모델·조작 프로필·팔 정밀 조작 원칙, §10.2 송신
  타이밍. 원형 휠(x 한 축)을 2 축 스틱으로 바꾸고 제자리 회전을 명시 입력으로 올렸다.
