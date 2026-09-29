## D-352 사이트 콘솔이 로봇 화면 코드로 로봇을 등록한다 — Fleet이 코드를 로봇에서 직접 교환하고, 자격은 Fleet 소유 저장소에 둔다

**Status:** Proposed (2026-09-29). 등록 흐름·자격 모양·결속·저장·수명 규칙과 구현 순서를 정한다. 구현 GO, CORE 이미지 교체, TLS 도입, DEVICE·FIELD 승격이 아니다.

잇는 결정: [D-193](D-193-login-code-and-credential-lifecycle.md)(로봇 화면 일회용 코드·`POST /api/v1/auth/pair`·§10 전송) · [D-5](D-5-outbound-ws-fleet-rest.md)(FleetAgent 바깥 연결) · [D-30](D-30-.md)·[D-31](D-31-fleet.md)(장치 로컬 토큰, Fleet 제어는 operator 이상) · [D-276](D-276-site-fleet-per-principal-api-authorization.md)(`require_named_operator`) · [D-302](D-302-site-registry-credential-separation.md)(사이트 자격 분리) · D-341(천장 카메라 콘솔 승인, 브랜치 `docs/d341-overhead-console-pairing`) · D-351(로봇 ↔ 관제 통신 적합성, 브랜치 `docs/robot-fleet-protocol-conformance`).
발견 규칙: [`site-lan-discovery-profile.md`](../reference/site-lan-discovery-profile.md). SRS: ROSY FLEET SRS REG-001(①mDNS ②수동 주소), REG-001a, SEC-203. 실행 계획: [`2026-09-29-fleet-robot-code-enrollment-plan.md`](../plans/2026-09-29-fleet-robot-code-enrollment-plan.md).

### Context

1. **오늘의 연결 절차.** 사이트 Fleet이 로봇 CORE에 닿으려면 누군가 `robots.yaml`(root 소유, 0600, 컨테이너에는 읽기 전용 `/run/rosy-config/robots.yaml`)에 `robot_id`·`base_url`·CORE operator `token`을 손으로 적고 Fleet을 다시 띄워야 한다. 그 토큰을 얻는 길은 SSH `sudo rosy-login-code` 또는 로봇 대시보드 세션뿐이다. FleetAgent 이벤트까지 받으려면 `fleet_pairing_token`을 로봇 `/var/lib/rosy/core/.rosy/rosy.yaml`과 사이트 `robots.yaml` 양쪽에 넣고 CORE를 통제된 재시작으로 돌려야 한다(`deploy/site/README.md` "Advertise and locate").
2. **2026-09-29 벤치.** 로봇 `rosy-pinky-8kcn`(192.168.1.202:8080, 릴리스 `2026.09.27-010`)이 Fleet 콘솔에 OFFLINE/UNAUTHORIZED로 보였다. 에이전트 세션은 SSH 없이 토큰을 얻을 수 없었다. 사용자 요청: "로봇을 사이트 콘솔에 붙이는 일을 간단하게."
3. **이미 있는 조각.**
   - D-193 S1/S3 착지: LCD 일회용 코드(8자, 약 39.6 bit, 10분, 부팅 첫 `CORE_READY`에 발급), `POST /api/v1/auth/pair`(인증 없음, 사설 대역만, IP당 60 s 5회·전체 30회, 코드당 5회 틀리면 폐기) → 역할·이름표·만료가 있는 토큰. 페어링 토큰 수명 상한은 168 h(`MAX_LIFETIME_HOURS`)이고 `auth/logout`으로 스스로 지울 수 있다. 벤치 이미지(API Ref v1.41)에도 이 경로가 있다(D-351 실측에서 `whoami` 401 확인).
   - Fleet 발견: `mdns-bridge.py`가 `_rosy._tcp` 해석 결과를 45 s 임대로 올리고 콘솔이 **등록 대기 / 페어링 대기 / 신원 충돌 / 확인됨**을 보인다(`server/discovery.py`, `web/console.js`). 발견은 자격을 주지 않는다.
   - Fleet 사용자: D-276 이름 있는 principal, 감사, `require_named_operator`.
4. **드러난 공백(코드 판독).**
   - **로스터가 기동 때 고정이다.** `FleetConsole`과 `SiteHub`는 생성자에서 `robots.yaml` 목록을 받아 끝까지 쓴다. `load_robots`는 빈 목록을 거절한다.
   - **CORE가 장치 UID를 모른다.** first boot가 `ROSY_DEVICE_UID`를 `runtime.env`에 쓰지만(`rosy-first-boot.py:620`) `core_common/config.py`는 `ROSY_DEVICE_NAME`만 읽는다. 그래서 FleetAgent HELLO의 `device_uid`는 비고, 발견 상태 `verified_online`은 실물에서 나올 수 없다. `GET /api/v1/system/info`에도 UID가 없다(`hostname`·`serial_number`·`robot_id`는 있다).
   - **7일 만료와 코드 재발급 비용이 맞지 않는다.** 새 LCD 코드는 부팅마다 한 번(재부팅), SSH, 또는 관리자 등록 코드로만 생긴다. Fleet이 7일마다 새 코드를 받아야 한다면 10대 사이트는 매주 10번 재부팅한다. 등록 코드로 받은 토큰은 발급자 만료를 넘지 못해 자기 갱신도 안 된다.
   - **Hub 세션 결속 결함**(D-351 발견 6): 짝지은 소켓이 다른 `robot_id`의 HEARTBEAT·EVENT를 넣을 수 있고, 짝 토큰 비교가 상수 시간이 아니다.
5. **전송.** 로봇 CORE는 LAN 평문 HTTP다(TXT `tls=none`). 사이트 Fleet은 사용자 쪽으로 TLS(8443, 사이트 CA)지만 로봇 쪽 호출은 평문이다. D-193 §10은 "중앙 Fleet 서버가 생길 때" TLS ADR을 열라고 했다.

### Decision

1. **흐름: 발견 → 등록 클릭 → 로봇 화면 코드 입력 → Fleet이 교환 → 읽어서 확인 → 로스터.**
   1. 콘솔 "기기 등록" 패널이 발견된 `_rosy._tcp` 로봇(상태 **등록 대기**)을 보인다. 멀티캐스트가 막힌 망은 같은 패널의 "주소로 추가"(`http://<host>.local:8080` 또는 사설 IPv4)로 같은 흐름에 들어간다(SRS REG-001 ②).
   2. 이름 있는 `operator`가 행의 **등록**을 누르고 그 로봇 LCD의 코드(`ABCD-EFGH`)를 친다. 관리자가 로봇 대시보드에서 발급한 등록 코드도 같은 칸에 넣을 수 있다.
   3. **Fleet 서버가** 그 로봇의 `POST /api/v1/auth/pair`를 직접 부른다. 본문은 `{code, label: "site:<fleet_name>", purpose: "site"}`다. 브라우저는 로봇에 닿지 않고 토큰 원문을 보지 않는다.
   4. Fleet은 받은 토큰으로 곧바로 `GET /api/v1/auth/whoami`와 `GET /api/v1/system/info`를 읽어 결속을 확인하고(3항), 통과하면 자격을 저장하고(4항) 로스터에 넣는다. 실패하면 받은 토큰으로 `POST /api/v1/auth/logout`을 부른 뒤 버린다.
   - 운용자 동작은 **전원 켜기 → 등록 클릭 → 8자 입력** 셋이다. SSH, 파일 편집, CORE·Fleet 재시작이 없다.
2. **자격의 모양: 역할은 `operator`, 출처는 새 값 `pair-site`.**
   - Fleet은 목표·모드·정지 요청·swarm 참조 소켓을 쓰므로 operator가 필요하다(D-31). viewer로는 관제가 안 되고, administrator는 필요 없다.
   - **새 역할(`site`)은 만들지 않는다.** CORE 권한은 순위 비교(`ROLE_RANK`)라 병렬 역할은 모든 라우트를 건드린다. 대신 **출처 `pair-site`**로 구분하고, 출처별 규칙(갱신 5항, 이벤트 연결 7항)을 거기에 건다. 로봇 대시보드 토큰 목록에서 사이트 자격이 이름표 `site:<fleet_name>`과 출처로 보이고, 로봇 관리자가 그 자리에서 회수할 수 있다.
   - CORE 규칙(S4): `purpose: "site"`인 교환은 코드 역할이 `operator` 이상일 때만 받고, 발급 역할은 항상 정확히 `operator`다(관리자 코드는 operator로 낮춘다). viewer 코드면 403 `ROLE_TOO_LOW`. `pair-site`를 `PAIRED_SOURCES`에 넣어 `logout`이 된다.
   - **옛 이미지 호환.** `PairRequest`는 모르는 필드를 무시하므로 옛 이미지는 `purpose`를 버리고 `pair-physical` 토큰(operator, 168 h)을 준다. Fleet은 응답 `source`를 보고 등록을 받아들이되 "갱신 불가 이미지 — 만료 전에 새 코드 필요"로 표시한다. 응답 역할이 `administrator`면(부팅 코드 정책이 관리자인 카드) Fleet은 즉시 `logout`하고 "관리자 코드로는 사이트를 등록하지 않는다"로 거절한다. viewer면 같은 방식으로 거절한다.
3. **결속과 위장 방지: 신원은 인증된 읽기에서, 주소는 발견에서.**
   - **결속 키.** 등록 순간 `system/info`에서 `robot_id`, `hostname`, `serial_number`, `device_uid`(S4에서 추가되는 필드, 옛 이미지는 없음)를 읽어 저장한다. `hostname`은 발견 행의 인스턴스 이름·`<hostname>.local`과 같아야 한다. 다르면 등록하지 않는다(**잘못된 로봇**).
   - **`robot_id`가 로스터 키다.** `robots.yaml`의 정적 로봇과 같은 `robot_id`면 409 — 파일 항목이 이긴다. 이미 등록된 `robot_id`에 다른 결속 키가 오면 409 **신원 충돌**이고 "교체"를 명시적으로 고를 때만 옛 등록을 해제(8항)한 뒤 새로 넣는다.
   - **주소는 저장하지 않고 따라간다.** 기준 이름은 mDNS 인스턴스 이름과 `<hostname>.local`이다. Fleet 컨테이너는 `.local`을 풀지 못하므로 전송 주소는 최신 발견 스캔의 해석 IP다. 같은 이름이 새 IP로 나타나면 Fleet은 그 IP에 `system/info`를 읽어 결속 키가 같을 때만 옮긴다. 다르면 그 로봇을 **격리**(자격을 보내지 않음, 상태 신원 충돌)한다. 같은 이름이 두 주소에 보이면 지금처럼 충돌이고 둘 다 쓰지 않는다. 수동 주소로 추가한 로봇은 그 주소에 고정된다.
   - **등록 버튼은 발견 상태가 등록 대기일 때만 켜진다.** 충돌 행에는 코드를 보낼 수 없다. 스캐너가 오프라인이어도 "주소로 추가"는 된다.
   - **한계(평문 LAN).** 발견은 위장할 수 있고 CORE에는 Bearer 없이 장치를 증명하는 경로가 없다(D-193 S3 기록). 같은 이름으로 먼저 광고해 코드를 가로채 진짜 로봇에 중계하는 공격, 주소 이동 때 토큰을 새 주소로 보내게 만드는 공격은 이 ADR로 막지 못한다. 평문 HTTP에서는 수동 도청으로도 같은 토큰을 얻으므로 위협 모델은 D-193 §10(운영자 전용 SSID/VLAN)과 같다. 해제 조건은 9항이다.
4. **저장: Fleet SQLite의 등록부 + 토큰은 AES-256-GCM으로 암호화, 키는 별도 Compose secret.**
   - `robots.yaml`은 고치지 않는다. root 소유·읽기 전용인 사람 관리 파일이고, 서버가 그것을 다시 쓰면 D-302의 "설치자가 검토한 설정" 경계가 깨진다. `robots.yaml`은 정적 로봇·시뮬용으로 남고 빈 목록도 허용한다(등록부가 켜진 경우).
   - 표 `robot_enrollments`: `robot_id`, 결속 키, 발견 이름, 수동 주소(선택), CORE 토큰 id·역할·출처·`expires_at`·계보 만료, 암호문, 등록자 principal, 상태(`active`·`renewing`·`quarantined`·`credential_lost`·`revoked_by_robot`), 시각. 표 `robot_enrollment_audit`: 등록·실패 사유 분류·갱신·격리·해제와 principal. 코드·토큰 원문은 감사·로그·응답에 싣지 않는다.
   - 암호화: `cryptography` AESGCM, 키 32 byte, nonce 96 bit 행마다 새로, AAD = `robot_id‖token_id`(행 바꿔치기 방지). 키는 새 secret `robot_credential_key`(`${ROSY_SITE_SECRETS_DIR}`, root 소유, 그룹 10001 읽기)이며 다른 모든 사이트 비밀과 달라야 한다(`create_app` 중복 거절 목록에 더함).
   - 근거: Fleet SQLite는 백업 절차가 별도 대상으로 복사한다(`deploy/site/README.md` Backup). DB 사본만으로는 토큰이 나오지 않고, 키와 DB를 함께 복원하면 코드 재입력 없이 되살아난다. 키가 없거나 복호가 실패하면 등록 기능은 닫히고(등록 라우트 503, 기존 등록 로봇은 `credential_lost`), `robots.yaml` 경로는 그대로 돈다.
5. **수명: 사이트 자격은 7일 토큰을 회전 갱신하고, 계보 상한은 90일이다.**
   - CORE 새 경로 `POST /api/v1/auth/renew`(S4): 호출자 토큰의 출처가 `pair-site`이고 살아 있을 때만. 같은 역할·이름표·계보로 새 토큰을 내고(수명은 역할 수명, 168 h 상한 유지) 새 토큰이 **처음 쓰일 때** 옛 토큰을 지운다. 새 토큰이 아직 안 쓰였으면 옛 토큰으로 다시 갱신할 수 있고, 그때 안 쓰인 자식은 버린다 — Fleet이 응답을 받고 저장 전에 죽어도 자격을 잃지 않는다.
   - **재사용 감지.** 새 토큰이 쓰인 뒤 옛 토큰이 나타나면 계보 전체를 회수하고 `auth.site_token_reuse`(warning)를 남긴다. Fleet은 401을 보고 `credential_lost` → "자격이 다른 곳에서 쓰였을 수 있음 — 새 코드로 다시 등록"을 띄운다.
   - **계보 상한.** 첫 교환 시각 + `auth.pairing.site_lineage_days`(기본 90, 카드 설정, 최대 365). 넘으면 갱신 403 `RENEWAL_LIMIT`. `whoami`가 `lineage_expires_at`을 더 싣고 콘솔은 14일 전부터 경고한다. D-193의 "만료가 있는 호출자는 만료 없는 토큰을 만들 수 없다"는 그대로다 — 사이트 자격도 항상 만료가 있다.
   - Fleet 갱신 주기: 남은 수명이 절반 아래이거나 72 h 아래면 갱신, 실패는 1 h 상한 백오프. 옛 이미지(`pair-physical`)는 갱신하지 않고 만료 72 h 전부터 "새 코드 필요"를 띄운다.
6. **해제·회수.**
   - 콘솔 **등록 해제**(이름 있는 operator): Fleet이 그 토큰으로 `auth/logout`(7항이 켜져 있으면 이벤트 연결 해제 먼저) → 등록부 행 삭제 → 감사. 로봇에 닿지 않으면 로컬에서 지우고 "로봇에 토큰이 남아 있음(만료 `expires_at`), 로봇 대시보드에서 회수하라"를 보인다.
   - 로봇 쪽 회수(대시보드 토큰 삭제) → Fleet은 401을 보고 `revoked_by_robot`으로 바꾸고 자동 재시도하지 않는다.
   - 권한: 등록·해제·교체·격리 해제는 `require_named_operator`(D-276·D-341 5항과 같음). 단일 console 토큰 구성에서는 403. `viewer`는 패널을 읽기만 한다.
7. **FleetAgent 이벤트 경로: 같은 등록이 짝 토큰까지 넣는다 — 단, D-351 Hub 결속 수정 뒤에 연다.**
   - CORE 새 경로 `PUT /api/v1/fleet/link`·`DELETE /api/v1/fleet/link`(S6): `pair-site` 출처 토큰만(다른 operator 토큰은 403). 본문은 `hub_url`(`wss://`만), 사이트 CA PEM, Fleet이 만든 256 bit `pairing_token`. CORE는 이것을 `patch_local_config`로 오버레이 `fleet.*`에 쓰고 FleetAgent를 프로세스 안에서 `stop()`→`start()`한다. **CORE 재시작이 없다.** `GET /api/v1/fleet/link`는 토큰 없이 설정 여부·hub 호스트만 답한다(원문 없음).
   - Fleet은 같은 짝 토큰을 등록부(암호화)와 Hub의 동적 토큰 표에 넣는다. REST 토큰과 짝 토큰이 같으면 거절하는 기존 규칙은 유지한다.
   - **여는 조건(모두 필요):** (a) D-351 S2의 Hub 세션-로봇 결속과 상수 시간 비교가 `main`에 있다, (b) Fleet이 로봇에서 닿는 `wss://` 주소와 그 SAN을 가진 사이트 인증서를 가진다(D-351 발견 5), (c) 4항 S4의 `device_uid`가 HELLO에 실린다. 그 전까지 등록된 로봇은 새 상태 **등록됨**(REST 확인, 이벤트 연결 전)에 머물고 이벤트 이력은 `robots.yaml` + 수동 절차로만 받는다.
   - 평문 `ws://` 짝 연결은 이 경로로 만들지 않는다. CA PEM이 평문 HTTP로 가는 위험은 3항 한계와 같고 9항 조건이 풀 때 함께 풀린다.
8. **발견 상태와 용어.** 사람에게 보이는 동사는 **등록**(로봇 REST 자격, 이 ADR)과 **연결 승인**(카메라, D-341)으로 나눈다. 발견 상태는 `registration_pending` "등록 대기" → `enrolled` "등록됨"(새, REST 결속 확인) → `verified_online` "확인됨"(FleetAgent HELLO가 같은 이름·UID로 온라인)이고 `pairing_pending`은 "이벤트 연결 대기"로 문구를 바꾼다(`robots.yaml` 로봇용). `conflict` "신원 충돌"은 그대로다. 로스터 행은 출처 **파일**/**등록**을 보인다.
9. **전송 위험과 TLS 조건.** 코드·토큰·(7항의) 짝 토큰·CA가 로봇 LAN 평문 HTTP로 간다. 받아들이는 조건: 로봇 LAN이 운영자 전용 SSID/VLAN이다(사이트 검증 기록에 적는다). 다음 중 하나면 **로봇 CORE TLS ADR이 먼저**이고 이 등록은 FIELD 판정을 받을 수 없다: 로봇 LAN을 운영자 밖 사람·장치와 공유한다, Fleet과 로봇이 라우팅된 다른 망에 있다, 한 Fleet이 여러 사이트의 로봇을 관리한다(중앙 Fleet), 사이트 로봇이 10대를 넘는다. Fleet의 로봇 호출은 `trust_env=False`(프록시 무시), 리다이렉트 금지, 연결 3 s·전체 10 s 제한이다.
10. **오류 문구(서버가 말한 것만 말한다, D-193 S3 규칙).**
    - 입력 칸은 공백·하이픈을 버리고 알파벳·길이를 먼저 본다 — 형식이 틀리면 로봇에 보내지 않아 시도 횟수를 쓰지 않는다. Fleet은 교환을 **자동 재시도하지 않는다.**
    - 401: "코드가 틀렸거나, 이미 쓰였거나, 만료됐습니다. 선택한 행의 이름이 로봇 화면의 이름과 같은지 확인하세요." 401 `detail.burned`: "이 로봇의 화면 코드가 폐기됐습니다 — 로봇 전원을 다시 넣거나 관리자 등록 코드를 받으세요." 429: `Retry-After` 초 동안 버튼을 끈다. 403 `FORBIDDEN`: "로봇이 이 서버를 LAN 밖으로 봅니다(주소 변환 확인)." 403 `ROLE_TOO_LOW`·관리자 코드: 2항 문구. 연결 실패: "로봇에 닿지 않습니다(주소·포트)." 결속 불일치: "다른 로봇이 답했습니다 — 등록하지 않았습니다."
    - LCD 코드는 부팅당 하나다. 운용자가 그 코드로 이미 로봇 대시보드에 로그인했다면 새 코드는 재부팅이나 관리자 등록 코드로 얻는다. 콘솔 도움말이 이것을 먼저 말한다.
11. **D-341과의 관계.** 방향이 반대다: 카메라는 기기가 요청하고 콘솔이 기기 화면의 확인 코드를 입력해 승인한다(기기 → 사이트). 로봇은 콘솔이 로봇 화면의 코드를 입력해 사이트가 로봇에서 자격을 받는다(사이트 → 로봇). 둘은 콘솔 **"기기 등록" 패널 하나**를 쓴다 — 위 "로봇"(발견·코드 입력·등록부), 아래 "카메라"(D-341 대기 요청·승인·자격 목록). 공유하는 것: 이름 있는 operator 승인, 감사 표 형식(principal·사유 분류·원문 없음), 오류 문구 규칙, 발견은 후보일 뿐이라는 원칙. 공유하지 않는 것: 자격 모양, 저장 위치, 수명. D-341 18항의 역할 등록표에 로봇을 넣지 않는다 — 로봇 쪽 코드 발급자는 CORE이고 절차가 다르다.

### 판정 등급 (Acceptance gates)

| 등급 | 인정하는 증거 |
|---|---|
| SOURCE | 이 ADR, 계획, ADR Log 행, 하네스 lint 녹색. README·발견 규칙 교차 참조는 구현 단계에서 |
| LOCAL | 계획 S1–S5 pytest 녹색: 가짜 CORE(실제 `core_api_web` `create_app`을 host pytest로 띄운 것 포함)에 대한 등록·결속 불일치·옛 이미지 `pair-physical` 경로·관리자 코드 거절·주소 이동·격리·갱신 회전·재사용 감지·해제. 등록부 DB 사본만으로 토큰이 안 나오는 시험. 콘솔 패널 node 시험. S6은 D-351 S2 착지 뒤 합성 CORE Agent로 HELLO까지 |
| DEVICE | 벤치 로봇 `rosy-pinky-8kcn`, 같은 Wi-Fi의 벤치 Fleet(이름 있는 operator, `robot_credential_key`), 이동·정지 명령 없음. **(D1, 현 이미지 `2026.09.27-010`으로 가능)** 사람이 로봇 전원을 다시 넣음 → LCD 코드 → 콘솔 발견 행 **등록** → 코드 입력 → 로스터에 온라인·상태 신선(`robot/state` 수신 시각 기록) → 로봇 대시보드 토큰 목록에 `site:<fleet_name>`·operator·만료 → Fleet 재시작 뒤에도 온라인 → 형식이 맞는 틀린 코드 1회의 401 문구 → **등록 해제** 뒤 로봇 토큰 목록에서 사라짐. 결과를 `docs/validation/`에 기록(코드·토큰 가림). SSH를 쓰지 않았음을 기록에 적는다. **(D2, S4 이미지 뒤)** `pair-site` 출처·`device_uid` 읽기·짧게 설정한 수명으로 갱신 회전·DHCP 주소 변경 추종. **(D3, S6 뒤)** 같은 등록 한 번으로 FleetAgent HELLO가 `verified_online`이 되고 CORE 재시작 없이 이벤트가 Fleet SQLite에 쌓임 |
| FIELD | 실제 Ubuntu 사이트 호스트(Avahi 브리지, Compose, 사이트 CA)에서 4대 이상 등록, 7일 이상 무인 갱신, 재부팅·DHCP 변경 포함, 9항 운영자 전용 망 기록. D-351 Decision 5의 관제 DEVICE 다섯 항목이 별도로 필요 |

host pytest 통과는 DEVICE가 아니고(D-91), 벤치 1대는 FIELD가 아니다(D-95).

### 이 ADR이 정하지 않는 것

- 로봇 CORE TLS의 방식(자체 서명 + 등록 때 지문 고정, 사이트 CA 발급 등). 9항은 필요 조건만 정한다.
- Bearer 없는 장치 증명(예: 토큰 digest 키의 HMAC 챌린지)으로 주소 이동 때 토큰을 보내기 전에 확인하는 경로.
- 계보 상한 90일·경고 14일·갱신 임계 72 h의 현장 튜닝.
- operator가 로봇 대시보드에서 **사이트 전용 등록 코드**를 발급하게 할지(지금 등록 코드는 administrator만). 이것이 열리면 "재부팅 없이 새 코드"가 쉬워진다.
- LCD에 "사이트 등록됨: <이름표>"를 띄울지(표시기는 CORE 밖 `rosy-display`, D-190 경로 필요).
- LCD QR(코드 + 이름)을 콘솔 휴대폰 화면으로 찍어 입력을 줄이는 방식.
- 여러 사이트가 한 로봇을 동시에 등록하는 것(지금은 막지 않지만 지원하지 않는다), 사이트 간 이전.
- SRS SEC-201 문구("Fleet이 발급한 페어링 토큰을 로봇 설정에 입력") 개정. 7항이 그 의도를 사람 입력 없이 채우므로 Clarify 행으로 맞추는 것은 후속이다.
- 부팅 코드 정책 `off` 카드에서의 등록(관리자 등록 코드만 가능) 안내 UI.

### Alternatives

- **`robots.yaml`을 계속 손으로 쓴다.** 오늘 공백 그 자체다(SSH·파일·재시작·7일마다 반복). 정적 로봇·시뮬 경로로만 남긴다.
- **SSH 스크립트가 코드 발급·교환·파일 기록을 대신한다.** 운용자 PC에 SSH 키·sudo가 필요하고, 비밀이 셸 이력과 운용자 PC에 남는다. 등록이 사이트 감사 밖에서 일어난다. 기각.
- **Fleet이 `robots.yaml`을 다시 쓴다.** root 소유·읽기 전용 설정을 서버 프로세스에 쓰기 가능하게 해야 하고, 사람이 검토한 파일과 서버 상태가 섞인다. 기각.
- **토큰을 평문으로 SQLite나 0600 파일에 둔다.** 가장 작지만 DB 백업 사본이 곧 operator 토큰 N개다. 별도 0600 파일은 백업에서 빼면 복원 때 모든 로봇을 재부팅·재입력해야 한다. 암호문 + 별도 키가 둘 다 푼다. 기각.
- **로봇이 코드를 들고 Fleet에 접속한다(D-341 방향).** 로봇에는 입력 장치가 없어 콘솔 코드를 로봇에 넣을 수 없고, 로봇이 먼저 사이트 CA·주소를 알아야 한다(오늘은 SD 준비 때만). FleetAgent 경로만 7항처럼 등록 뒤에 연다. 기각.
- **LCD QR.** 코드가 사진 한 장에 이름과 함께 담기고 LCD 크기·표시기 경로 변경이 필요하다. 정하지 않는 것으로 남긴다.
- **새 CORE 역할 `site`.** 1·2항 근거로 기각. 출처로 충분하다.
- **7일마다 새 코드(갱신 없음).** 새 코드가 재부팅을 요구하므로 "간단하게"에 반한다. 옛 이미지 호환 모드로만 남는다.
- **만료 없는 사이트 토큰.** D-193 페어링 규칙을 깬다. 기각.

### Consequences

- CORE: `pair`에 `purpose` 필드, 출처 `pair-site`, `auth/renew`, 토큰 레코드의 계보 필드, `whoami.lineage_expires_at`, `system/info.device_uid`·`device_name`, (S6) `fleet/link`. 모두 additive이며 API Ref MINOR를 올리고 D-351 계약 스냅샷이 있으면 재생성한다. 이미지 재빌드가 필요하다.
- Fleet: 로스터가 동적이 된다(콘솔·Hub·발견 상태가 등록부를 읽음). 자격 없는 라우트는 늘지 않는다 — 등록 라우트는 모두 이름 있는 operator 뒤다. `cryptography`가 Fleet 이미지 의존성이 되고 새 Compose secret이 하나 는다.
- 운영: 로봇마다 SSH가 필요했던 등록이 콘솔 한 곳으로 모인다. 대신 Fleet 호스트와 그 키가 사이트 전체 로봇의 operator 자격을 모은 곳이 되므로, Fleet 호스트 보호와 `robot_credential_key` 보관이 사이트 검증 기록 항목이 된다.
- 현 벤치 이미지로 D1이 가능하다 — 등록 자체는 이미지 교체를 기다리지 않는다.

**References:** D-5, D-30, D-31, D-91, D-95, D-190, D-193, D-276, D-302, D-341(브랜치), D-351(브랜치), ROSY FLEET SRS REG-001/REG-001a/SEC-201/SEC-203, `site-lan-discovery-profile.md`, `deploy/site/README.md`.
