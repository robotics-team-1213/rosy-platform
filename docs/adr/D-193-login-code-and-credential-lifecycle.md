## D-193 대시보드 로그인은 로봇 화면의 일회용 코드로 한다 — 장기 토큰은 화면에 띄우지 않고, 장치 기본값에는 로그인이 없다

**Status:** Proposed (2026-09-24). 따르는 결정:

- D-161: CORE는 비특권이고 인터넷에 닿는 프로세스다.
- D-176: AP 비밀번호는 물리 접근자에게만 보인다.
- D-190: LCD는 CORE 밖의 `rosy-display`가 그리고, root가 핸드오프 파일을 쓴다.
- D-191 US-009: 카드마다 administrator 토큰을 발급한다.

런북 "CORE API administrator credential"의 열린 항목도 닫는다. overlay가 비면 `rosy-dev-*`가 되살아나는 문제다.

**Context:** 2026-09-24 실기와 대시보드 점검(`rosy-pinky-e4us`)에서 확인한 것:

- **카드 005:** 카드별 토큰이 없다. CORE는 `rosy_default.yaml`로 돌아가고, 공용 개발 토큰 `rosy-dev-admin`/`operator`/`viewer`가
  LAN에서 그대로 통한다(`src/core/core/config/rosy_default.yaml` `auth.tokens`). 같은 Wi-Fi에 붙은 누구나 로봇을 관리할 수 있다.
- **008부터:** 카드에는 administrator 토큰 하나가 있다.
  - 원문은 기록 PC의 DPAPI 저장소(`%LOCALAPPDATA%\Rosy\api\<device>.credential.xml`)와 한 번 찍힌 출력에만 있다.
  - 첫 부팅은 sha256 레코드만 `/var/lib/rosy/core/.rosy/rosy.yaml`에 넣는다. 그 목록이 기본 목록을 통째로 덮어 개발 토큰이 막힌다.
  - **장치에는 토큰 원문이 없다.**
- **운영자의 불편:** 대시보드(`/dashboard`, `#token-input`, `sessionStorage`)에 들어가려면 그 PC에서 43자 토큰을 옮겨 와야 한다.
  태블릿이나 다른 PC에서는 사실상 로그인할 수 없다. 사용자는 "LCD에 토큰을 띄워 로그인"을 제안했다.
- **토큰 모델**(`core_api_web/api/deps.py`): sha256 다이제스트, 역할 3개다. 만료와 출처 구분이 없다.
  대시보드는 역할을 `/api/v1/logs/audit?limit=1`의 응답 코드로 추측한다(`web/app.js` `detectRole`).
- **전송:** LAN 위 평문 HTTP다. WebSocket은 토큰을 쿼리 문자열로 싣는다(`ws.py` `?token=`).

**Decision:**

1. **LCD에는 장기 토큰이 아니라 일회용 로그인 코드를 띄운다.**
   - 형식: 8자, 알파벳 `23456789ABCDEFGHJKMNPQRSTUVWXYZ`(혼동 문자 제외, `secrets.choice`), 약 39.6 bit. `ABCD-EFGH`로 보인다.
   - 한 번만 쓸 수 있고 수명은 기본 10분이다.
   - 대시보드는 `POST /api/v1/auth/pair`로 코드를 **이 브라우저 전용 새 토큰**(역할·이름표·만료 포함)으로 바꾼다.
   - 장기 토큰을 띄우지 않는 이유:
     - 장치에 원문이 없다. 띄우려면 원문을 카드에 되돌려야 하고, 그것은 US-009를 되돌리는 일이다.
     - 사진 한 장이 회전 전까지 영구 관리자 권한이 된다.
     - 회수하면 운영 PC의 자격도 함께 죽는다.
     - 43자는 어차피 손으로 치기 어렵다.
   - 코드가 사진에 찍혀도 다음으로 제한된다.
     - 첫 사용자만 쓸 수 있다.
     - 수명은 10분, 기본 역할은 `operator`다.
     - 사용되면 LCD에서 즉시 사라진다.
     - 결과 토큰은 `pair-physical` 출처로 목록에 보이고 회수할 수 있다.
2. **코드는 root가 만들고, CORE는 검증자만 읽는다(D-161).**
   - **발급자:** 새 unit `rosy-login-code.service`(root). 샌드박스는 `PrivateNetwork=true`, `RestrictAddressFamilies=AF_UNIX`,
     `ProtectSystem=strict`, `ReadWritePaths=/run/rosy-boot`이고, 셸은 없다.
   - **발급 시점:**
     - (a) `boot-status.json`이 처음 `CORE_READY`가 될 때. 전원을 다시 넣는 것이 곧 물리 동작이다.
     - (b) SSH나 콘솔에서 `sudo rosy-login-code [--role operator|administrator] [--minutes N]`을 부를 때.
       코드는 그 터미널에만 찍히고 journal에는 남지 않는다.
     - (c) Pinky Pro에 사용자 버튼이 확인되면 그 버튼. Pi 5 전원 버튼은 종료 동작이므로 쓰지 않는다.
   - **CORE의 입력은 root가 쓰는 파일 하나뿐이다:** `/run/rosy-boot/login-code.json`, root:rosy-core 0640, tmpfs.
     - 담는 것: `code_id`, `role`, `source`, scrypt 매개변수·`salt`·`digest`, `boot_id`, `expires_monotonic`.
     - 원문은 없다.
     - CORE는 코드를 만들 수도, 원문을 볼 수도 없다.
   - **LCD용:** `/run/rosy-boot/login-display.txt`(root:rosy-display 0640). D-190의 `ap-display.txt`와 같은 방식으로 쓴다.
   - **콘솔 배너용:** `/run/rosy-boot/login.issue`(0600) → `/etc/issue.d/60-rosy-login.issue`.
   - avahi TXT, 블랙박스, 진단 번들에는 코드를 넣지 않는다.
   - **CORE → root 신호는 "지워라" 하나뿐이다.**
     - CORE는 코드를 쓰거나 폐기하면 자기 `/run/rosy/login-code-state.json`에 `{code_id, state}`를 쓴다.
     - root는 1 s마다 이 파일을 읽는다. `O_NOFOLLOW`, 정규 파일, 256 B 이하, 정규식에 맞는 `code_id`일 때만 받아들인다.
     - 자기가 발급한 `code_id`와 같을 때만 세 파일을 지운다.
     - 탈취된 CORE가 할 수 있는 최악은 코드를 일찍 지우는 것이다.
   - **경계:** CORE를 원격 실행으로 탈취하면 이미 API 관리자다. 이 결정이 막는 것은 둘이다.
     - 물리 접근의 증표가 인터넷에 닿는 프로세스에 원문으로 존재하는 것.
     - CORE의 파일 읽기 결함이 곧 로그인이 되는 것.
3. **검증자는 느린 해시다.**
   - scrypt(N=2^14, r=8, p=1): 39.6 bit 코드를 sha256으로 두면 파일을 읽은 공격자가 오프라인으로 몇 분 안에 푼다.
   - 만료는 `boot_id`가 같고 `time.monotonic() < expires_monotonic`일 때만 유효로 본다. 그래서 NTP 점프에 흔들리지 않는다.
   - Pi 5 검증 시간은 실기에서 재서 `deploy/logs.md`에 남긴다.
4. **`POST /api/v1/auth/pair`(인증 없음)는 좁게 연다.**
   - 출발지: 사설·AP 대역(RFC 1918, `10.42.0.0/24`, 루프백)만 받는다. 그 밖은 403이다.
   - 속도 제한: IP마다 60 s에 5회, 전체 60 s에 30회. 넘으면 429다.
   - 틀린 시도가 한 코드에 5회 쌓이면 코드를 폐기(`burned`)하고 LCD에 "코드 폐기됨"을 보인다.
   - 성공하면 다음을 한다.
     - `generate_token()`으로 토큰을 만든다.
     - 감사 이벤트 `auth.paired`(코드 없음)를 남긴다.
     - 원문 토큰은 응답에 한 번만 싣고 `Cache-Control: no-store`를 붙인다.
5. **토큰 수명주기.**
   - **레코드 필드 추가:** `expires_at`, `source`(`card`|`manual`|`pair-physical`|`pair-admin`|`legacy`), `paired_via`.
   - **만료:** `authenticate`는 만료된 레코드를 거부한다. 페어링 토큰의 기본 수명은 `operator`/`viewer` 7일, `administrator` 24시간이다.
   - **새 API:**
     - `GET /api/v1/auth/whoami`: 대시보드가 역할을 추측하던 방식을 대신한다.
     - `POST /api/v1/auth/logout`: 자기 페어링 토큰만 지운다.
     - `PATCH /api/v1/system/tokens/{id}`: 이름표를 바꾼다.
     - 토큰 목록에는 `expires_at`, `source`, `current`, `last_used_at`을 싣는다.
   - **마지막 관리자 규칙:** 삭제 뒤에 만료 없는 `administrator`가 하나 이상 남아야 한다.
   - **관리자가 다른 기기를 붙이는 법:** 자기 화면에서 `POST /api/v1/auth/enrollment-codes`로 코드를 받는다.
     역할은 자기 역할 이하, 수명은 5분이고, 코드는 CORE 메모리에만 둔다.
   - **카드 토큰 회전:** PC 스크립트 `deploy/sd/rotate-core-api-credential.ps1`이 추가 → DPAPI 저장 → whoami 확인 → 옛 id 삭제
     순서로 처리한다.
6. **대시보드 저장소 규칙.**
   - 만료 없는 토큰은 `sessionStorage`에만 둔다.
   - 페어링 토큰은 "이 브라우저에서 로그인 유지(최대 7일)"를 고를 때만 `localStorage`에 둔다.
   - 머리글에는 역할·이름표·만료를 보인다.
   - 인증은 Bearer 헤더로만 한다. 쿠키는 쓰지 않는다.
   - 로그인 서랍은 "로봇 화면 코드"(기본)와 "API 토큰" 두 탭이다.
7. **장치 기본값에는 로그인이 없다(fail closed). 개발과 시뮬만 켠다.**
   - `rosy_default.yaml`의 `auth.tokens`는 `[]`가 된다.
   - 개발 토큰은 새 `config/rosy_dev_auth.yaml`로 옮기고, `ROSY_DEV_AUTH=1`일 때만 병합한다.
   - 네이티브 `runtime.env`는 `ROSY_DEPLOYMENT=device`를 싣는다. 이 상태의 CORE는 다음을 한다.
     - `ROSY_DEV_AUTH`를 무시한다.
     - 평문 레거시 항목과 세 개발 토큰 다이제스트를 거부한다.
     - 토큰이 0개여도 뜨지만, 모든 요청은 401이다.
   - 복구는 SSH `sudo rosy-login-code --role administrator`로 한다.
   - 이미지 검사는 페이로드 `rosy_default.yaml`에 토큰이 있으면 빌드를 멈춘다.
8. **부팅 코드 정책은 카드에서 정한다(물리 접근).**
   - `rosy-config.yaml`의 `login.boot_code`는 `off`|`operator`(기본)|`administrator`를 받는다.
   - LCD를 불특정 다수가 보는 곳에서는 `off`를 권한다.
9. **LCD가 없는 보드.**
   - 같은 코드가 콘솔 배너(0600)에 뜨고, SSH에서는 `sudo rosy-login-code`로 받는다.
   - DPAPI 카드 토큰도 그대로 유효하다.
10. **전송(TLS)은 이 ADR 범위 밖이다.**
    - **위협:** 같은 WPA2-PSK를 아는 사람은 평문 Bearer 토큰과 페어링 응답을 볼 수 있다.
    - **이 ADR의 완화:**
      - 페어링 토큰은 만료가 있고, 기본 역할은 `operator`다.
      - 코드는 한 번만 쓴다.
      - 코드는 사설 대역에서만 받는다.
      - 응답에 `no-store`를 붙인다.
      - fallback AP는 카드별 WPA2다.
      - WebSocket 토큰은 첫 메시지로 옮긴다. `?token=`은 한 릴리스 동안만 받는다.
      - 런북은 로봇 LAN을 운영자 전용 SSID/VLAN으로 두라고 쓴다.
    - **TLS를 별도 ADR로 여는 조건:** 로봇 LAN을 운영자 외의 사람과 공유할 때, 대시보드를 VLAN 밖에서 열 때,
      중앙 Fleet 서버가 생길 때.

**Alternatives:**

- **LCD에 장기 관리자 토큰을 띄운다.** 원문이 장치에 없다(US-009). 사진 한 장이 영구 권한이 되고, 43자라 입력도 어렵다.
- **CORE가 코드를 만든다.** 원문이 인터넷에 닿는 프로세스에 남는다. CORE의 파일 읽기 결함 하나가 곧 로그인이 된다.
- **root가 검증도 한다(유닉스 소켓).** CORE 입력을 root가 해석하는 새 표면이 생긴다. 검증자 파일로 같은 성질을 더 작은 표면으로 얻는다.
- **root가 검증자를 CORE overlay에 쓴다.** root가 CORE 소유 디렉터리에 써야 해서 심볼릭 링크 위험이 생긴다.
  또 일회용 값이 영구 파일에 남는다.
- **6자리 숫자 코드.** 검증자 파일이 새면 2^20 경우는 순식간에 풀린다.
- **부팅 코드 기본 역할을 administrator로 한다.** LCD를 본 방관자가 영구 관리자가 된다. 카드 설정으로만 켤 수 있게 남긴다.
- **개발 토큰을 두고 장치에서만 거부한다.** 가드 환경 변수가 빠지면 다시 열린다. 기본값을 비우는 편이 닫힌 실패다.

**Consequences:**

- 운영자는 로봇 화면을 보고 8자를 치면 로그인한다. 관리자 작업은 카드 토큰이나 SSH로 받은 관리자 코드로 한다.
- root 코드(`rosy-login-code`, 네트워크 없음)가 하나 는다. D-189 샌드박스 계약이 쓰기 경로를 고정한다.
- 개발 토큰을 쓰는 host 시험과 시뮬 launch는 `ROSY_DEV_AUTH=1`이나 새 fixture를 써야 한다.
- 카드 토큰이 없는 005 같은 장치는 새 릴리스에서 개발 토큰이 막힌다. 005는 어차피 재기록 대상이다.
- 시계가 맞지 않은 채 발급된 토큰은 일찍 만료될 수 있다(닫힌 실패). 코드 자체는 monotonic 시계라 영향이 없다.

**평가표 (D-191 행 6 교체):**

| # | 확인 | PASS 조건 |
|---|---|---|
| 6a | 개발 토큰 차단 | 새 이미지에서 `rosy-dev-admin` → 401. overlay의 `auth`를 지우고 CORE를 재시작해도 401 |
| 6b | 카드 토큰 | DPAPI 값으로 `GET /api/v1/auth/whoami` = `administrator`, `source: card` |
| 6c | LCD 코드 | `CORE_READY` 뒤 LCD에 `로그인 XXXX-XXXX operator`. 휴대폰 대시보드에서 로그인되고 역할이 보인다. 코드는 LCD에서 1 s 안에 사라지고, 다시 쓰면 401 |
| 6d | 폐기·속도 | 틀린 코드 5회 → "코드 폐기됨". 한 IP에서 6번째 요청 → 429 |
| 6e | 비밀 위생 | `login-code.json` root:rosy-core 0640, `login-display.txt` root:rosy-display 0640. journal에 코드 없음 |
| 6f | LCD 없음 | 콘솔 배너에 코드. `sudo rosy-login-code --role administrator`로 페어링 → administrator, 만료 +24h |
| 6g | 수명주기 | 설정 화면에 출처·만료·"이 기기"가 보인다. 로그아웃이 된다. 만료 없는 마지막 관리자 삭제 → 409 |

**실행 계획:**

- **S1 CORE 토큰 모델:** 만료·출처 필드, whoami, logout, pair, enrollment-codes, 장치 모드의 개발 토큰 거부, 빈 기본 목록.
- **S2 root 발급자와 LCD·콘솔 표시:** `rosy-login-code` unit·CLI, `login-display.txt`, 이미지 설치·검사.
- **S3 대시보드와 PC 도구:** 코드 로그인 탭, 저장소 규칙, whoami 배지, WebSocket 첫 메시지 인증, 회전 스크립트.
- **S4 실기:** 새 이미지 카드로 평가표 6a-6g를 채운다. 장치에서 즉석으로 고치지 않는다(D-190 결정 6).

**2026-09-24 보안 리뷰 반영 (구현 `feat/login-code`):**

- **소비·실패 상태의 지속:** CORE 재시작이 쓴 코드를 되살리지 않도록 CORE는 자기 `/run/rosy/login-code-state.json`을
  root와 같은 규칙(`O_NOFOLLOW`, 정규 파일, 256 B)으로 다시 읽는다. 틀린 시도는 `{"state": "failing", "attempts": n}`으로
  남긴다(root는 모르는 상태를 무시한다). `rosy-core.service`는 `RuntimeDirectoryPreserve=restart`다.
- **scrypt 동시 실행:** 한 번에 둘까지(각 16 MiB).
- **페어링 세션의 한계:** 만료가 있는 호출자는 만료 없는 토큰을 만들 수 없고 만료 없는 administrator를 지울 수 없다(403).
  등록 코드로 받은 토큰은 발급자 토큰의 만료를 넘지 않고, 발급자 토큰이 사라지면 코드도 무효다.
- **그 밖:** 토큰 목록 쓰기는 하나의 락 안에서 읽고 쓴다. WebSocket은 30 s마다 토큰을 다시 보고 사라졌으면 4401로 닫는다.
  첫 메시지를 기다리는 소켓은 16개까지다. 등록 코드가 살아 있는 동안 틀린 시도는 부팅 코드가 아니라 그 코드에 센다.
  `POST /system/tokens` 응답은 `no-store`다. uvicorn은 `proxy_headers=False`로 소켓 주소만 믿는다.

**2026-09-24 S3 구현 (`feat/login-dashboard`):**

- **로그인 서랍:** "로봇 화면 코드"(기본)와 "API 토큰" 두 탭. 코드는 공백·하이픈을 버리고 대문자로 바꾼 뒤 알파벳·길이를
  브라우저에서 먼저 본다(틀린 형식은 시도 횟수를 쓰지 않는다). 실패 문구는 서버가 말한 것만 말한다: 401은 "틀림·사용됨·만료·
  발급 없음"을 한 문장으로, 429는 `Retry-After` 초와 함께 버튼을 그동안 끈다, 403은 LAN 밖. 코드를 폐기시킨 5번째 요청만
  401 `error.detail.burned`를 받는다(나머지 401은 구분하지 않는다 — 추측하는 쪽에 살아 있는 코드를 알려 주지 않는다).
- **저장소:** 만료 없는 토큰(붙여 넣은 카드·수동 토큰)은 `sessionStorage`에만. 페어링 토큰은 "로그인 유지(최대 7일)"를 고를
  때만 `localStorage`에 `{token, expires_at}`로 두고, 읽을 때 만료가 지났으면 지운다. 토큰은 URL·쿠키·콘솔에 두지 않는다.
- **머리글:** `whoami`로 역할·이름표·출처·만료를 보인다(역할 추측과 `system/info.caller_role` 대신). 페어링 토큰은
  "로그아웃"(`POST auth/logout`), 다른 토큰은 "이 브라우저에서 잊기"(로봇의 토큰은 남는다고 말한다). 설정의 토큰 목록에
  출처·만료·"이 기기"를 보이고 쓰는 토큰의 삭제 버튼을 끈다.
- **WebSocket:** URL에 토큰 없이 열고 첫 메시지로 보낸다. 4401이면 REST `whoami`로 확인해 401이면 로그아웃, 아니면 재시도.
  4403은 재시도하지 않는다. 그 밖(1013은 수락 전이라 브라우저에 1006으로 온다)은 1 s부터 두 배씩 30 s까지 늘리는 백오프로
  다시 붙고, 상태를 한 번 받은 뒤에만 백오프를 되돌린다. 끊긴 동안은 REST 2 s 폴링. REST 401도 세션을 끝낸다.
- **회전 스크립트:** `deploy/sd/rotate-core-api-credential.ps1 -DeviceName rosy-pinky-xxxx`. 모두 CORE API로 한다
  (SSH 없음): 저장된 값이 그 로봇의 만료 없는 administrator인지 `whoami`로 확인 → `POST system/tokens` → DPAPI 저장(옆 파일에
  쓰고 백업과 바꿈, `<id>|<device_uid>` 유지) → 저장소에서 다시 읽은 값으로 `whoami` → 새 값으로 옛 id `DELETE`. 저장·확인이
  실패하면 옛 저장소를 되돌리고 새 id를 지운다. 새 값은 출력하지 않는다(읽는 명령만 알려 준다). HttpClient로 프록시와
  리다이렉트를 끈다. 회전된 토큰의 출처는 `manual`이다(API가 `card` 출처를 만들지 않는다) — 평가표 6b는 새 카드 기준이다.
- **하지 않은 것:** 대시보드의 등록 코드 발급 UI(`POST auth/enrollment-codes`)는 S3 목록에 없어 넣지 않았다.
