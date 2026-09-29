## D-352 사이트 콘솔이 로봇 화면 코드로 로봇을 등록한다 — Fleet이 코드를 로봇에서 직접 교환하고, 자격은 Fleet 소유 저장소에 둔다

**Status:** Proposed (2026-09-29, 같은 날 독립 리뷰 2회·사용자 결정 반영 개정). 등록 흐름·자격 모양·결속·저장·수명 규칙과 구현 순서를 정한다. 구현 GO, CORE 이미지 교체, TLS 도입, DEVICE·FIELD 승격이 아니다.

잇는 결정: [D-193](D-193-login-code-and-credential-lifecycle.md)(로봇 화면 일회용 코드·`POST /api/v1/auth/pair`·§10 전송) · [D-5](D-5-outbound-ws-fleet-rest.md)(FleetAgent 바깥 연결) · [D-30](D-30-.md)·[D-31](D-31-fleet.md)(장치 로컬 토큰, Fleet 제어는 operator 이상) · [D-276](D-276-site-fleet-per-principal-api-authorization.md)(`require_named_operator`) · [D-302](D-302-site-registry-credential-separation.md)(사이트 자격 분리) · D-341(천장 카메라 콘솔 승인, 브랜치 `docs/d341-overhead-console-pairing`) · D-351(로봇 ↔ 관제 통신 적합성, 브랜치 `docs/robot-fleet-protocol-conformance`).
발견 규칙: [`site-lan-discovery-profile.md`](../reference/site-lan-discovery-profile.md). SRS: ROSY FLEET SRS REG-001(①mDNS ②수동 주소), REG-001a, SEC-203. 실행 계획: [`2026-09-29-fleet-robot-code-enrollment-plan.md`](../plans/2026-09-29-fleet-robot-code-enrollment-plan.md).

### Context

1. **오늘의 연결 절차.** 사이트 Fleet이 로봇 CORE에 닿으려면 누군가 `robots.yaml`(root 소유, 0600, 컨테이너에는 읽기 전용 `/run/rosy-config/robots.yaml`)에 `robot_id`·`base_url`·CORE operator `token`을 손으로 적고 Fleet을 다시 띄워야 한다. 그 토큰을 얻는 길은 SSH `sudo rosy-login-code` 또는 로봇 대시보드 세션뿐이다. FleetAgent 이벤트까지 받으려면 `fleet_pairing_token`을 로봇 `/var/lib/rosy/core/.rosy/rosy.yaml`과 사이트 `robots.yaml` 양쪽에 넣고 CORE를 통제된 재시작으로 돌려야 한다(`deploy/site/README.md` "Advertise and locate").
2. **2026-09-29 벤치.** 로봇 `rosy-pinky-8kcn`(192.168.1.202:8080, 릴리스 `2026.09.27-010`)이 Fleet 콘솔에 OFFLINE/UNAUTHORIZED로 보였다. 에이전트 세션은 SSH 없이 토큰을 얻을 수 없었다. 사용자 요청: "로봇을 사이트 콘솔에 붙이는 일을 간단하게."
3. **이미 있는 조각.**
   - D-193 S1/S3 착지: LCD 일회용 코드(8자, 약 39.6 bit, 10분, 부팅 첫 `CORE_READY`에 발급, 카드 `login.boot_code` 기본 `operator`), `POST /api/v1/auth/pair`(인증 없음, 사설 대역만, IP당 60 s 5회·전체 30회, 코드당 5회 틀리면 폐기) → 역할·이름표·만료가 있는 토큰. 페어링 토큰 수명 상한은 168 h(`MAX_LIFETIME_HOURS`), 관리자 등록 코드로 받은 토큰은 발급자 토큰의 만료를 넘지 않는다(D-193 보안 리뷰 M2). `auth/logout`으로 스스로 지울 수 있다. 벤치 이미지(API Ref v1.41)에도 이 경로가 있다(D-351 실측에서 `whoami` 401 확인).
   - Fleet 발견: `mdns-bridge.py`가 `_rosy._tcp` 해석 결과(TXT `name`, avahi 호스트 이름 `<host>.local`, IPv4)를 45 s 임대로 올리고 콘솔이 **등록 대기 / 페어링 대기 / 신원 충돌 / 확인됨**을 보인다(`server/discovery.py`, `web/console.js`). 발견은 자격을 주지 않는다.
   - Fleet 사용자: D-276 이름 있는 principal, 감사, `require_named_operator`.
4. **드러난 공백(코드 판독).**
   - **로스터가 기동 때 고정이고 여러 곳에 복사된다.** `FleetConsole`의 클라이언트·순서, `SiteHub`의 클라이언트·짝 토큰, `FleetTaskService.robot_ids`, sighting 설정의 `known_robot_ids`가 모두 기동 때 `robots.yaml` 목록에서 따로 만들어진다(`cli.py:353`, `:364`). `load_robots`는 빈 목록을 거절한다. `snapshot`·`_observe`·`estop_all`은 `await` 사이에서 순서 목록을 그대로 순회한다(`console.py:168-173`, `:466-469`, `:695-700`).
   - **CORE가 장치 UID를 모른다.** first boot가 `ROSY_DEVICE_UID`를 `runtime.env`에 쓰지만(`rosy-first-boot.py:620`) `core_common/config.py`는 `ROSY_DEVICE_NAME`만 읽는다. FleetAgent HELLO의 `device_uid`는 비고, 발견 상태 `verified_online`은 실물에서 나올 수 없다. `GET /api/v1/system/info`에도 UID가 없다(`hostname`·`serial_number`·`robot_id`는 있다).
   - **7일 만료와 코드 재발급 비용이 맞지 않는다.** 새 LCD 코드는 부팅마다 한 번(전원 재투입), SSH, 또는 관리자 등록 코드로만 생긴다. Fleet이 7일마다 새 코드를 받아야 한다면 10대 사이트는 매주 10번 재부팅한다.
   - **Hub 세션 결속 결함**(D-351 발견 6): 짝지은 소켓이 다른 `robot_id`의 HEARTBEAT·EVENT를 넣을 수 있고, 짝 토큰 비교가 상수 시간이 아니다.
5. **전송.** 로봇 CORE는 LAN 평문 HTTP다(TXT `tls=none`). 사이트 Fleet은 사용자 쪽으로 TLS(8443, 사이트 CA)지만 로봇 쪽 호출은 평문이다. D-193 §10은 "중앙 Fleet 서버가 생길 때" TLS ADR을 열라고 했다.

### Decision

1. **흐름: 발견 → 등록 클릭 → 로봇 화면 코드 입력 → Fleet이 교환 → 읽어서 확인 → 로스터.**
   1. 콘솔 "기기 연결" 패널(11항)의 **로봇 등록** 구역이 발견된 `_rosy._tcp` 로봇(상태 **등록 대기**)을 보인다. 멀티캐스트가 막힌 망은 같은 구역의 "주소로 추가"로 들어간다(SRS REG-001 ②). 수동 주소는 **사설 IPv4[:포트]만** 받는다(`.local`은 Fleet 컨테이너가 풀지 못하므로 받지 않는다. 포트 기본 8080).
   2. 이름 있는 `operator`가 행의 **등록**을 누르고 그 로봇 LCD의 코드(`ABCD-EFGH`)를 친다. 로봇 대시보드에서 관리자가 발급한 등록 코드도 같은 칸에 넣을 수 있다.
   3. **Fleet 서버가** 그 로봇의 `POST /api/v1/auth/pair`를 직접 부른다. 본문은 `{code, label: "site:<fleet_name>", purpose: "site"}`다. 브라우저는 로봇에 닿지 않고 토큰 원문을 보지 않는다.
   4. Fleet은 받은 토큰으로 곧바로 `GET /api/v1/auth/whoami`와 `GET /api/v1/system/info`를 읽어 결속을 확인하고(3항), 통과하면 자격을 저장하고(4항) 로스터에 넣는다(5항). 실패하면 받은 토큰으로 `POST /api/v1/auth/logout`을 부른 뒤 버린다.
2. **자격의 모양: 긴 수명의 사이트 토큰 하나, 역할 `operator`, 출처 `pair-site`. 회전·갱신은 없다.**
   - Fleet은 목표·모드·정지 요청·swarm 참조 소켓을 쓰므로 operator가 필요하다(D-31). viewer로는 관제가 안 되고, administrator는 필요 없다.
   - **새 역할(`site`)은 만들지 않는다.** CORE 권한은 순위 비교(`ROLE_RANK`)라 병렬 역할은 모든 라우트를 건드린다. 대신 **출처 `pair-site`**로 구분한다. 로봇 대시보드 보안 패널(`src/hmi/dashboard/panels/system/security.js`)이 이름표 `site:<fleet_name>`과 출처 "사이트"로 보이고, 로봇 관리자가 그 자리에서 회수할 수 있다.
   - **operator도 사이트 토큰을 보고 회수한다(S4).** 새 CORE 경로 `GET /api/v1/auth/site-tokens`(operator 이상, `pair-site` 행만: id·이름표·만료·`last_used_at`, 원문·digest 없음)와 `DELETE /api/v1/auth/site-tokens/{id}`(operator 이상, `pair-site` 출처만 지움, 다른 출처 id면 404). 대시보드 보안 패널이 operator 세션에서도 "사이트 연결" 목록과 회수 버튼을 보인다. 90일 토큰이 LCD 코드를 본 사람 누구에게나 갈 수 있으므로(3항 한계), 회수가 관리자 전용이면 안 된다. 회수는 감사 이벤트 `auth.site_token_revoked`(id·회수자 id)를 남긴다.
   - **CORE 규칙(S4).** `purpose: "site"`인 교환은 코드 역할이 `operator` 이상일 때만 받고(아니면 403 `ROLE_TOO_LOW`), 발급 역할은 항상 정확히 `operator`다(관리자 코드는 operator로 낮춘다). `pair-site`를 `TOKEN_SOURCES`와 `PAIRED_SOURCES`에 넣는다(`deps.py:103`; 없으면 `new_token_record`가 `:199`에서 출처를 `manual`로 바꾼다). `logout`이 된다.
   - **수명.** `pair-site`의 수명은 카드 설정 `auth.pairing.site_token_days`(기본 90, 1–365로 자름)다. 이것은 D-193의 168 h 상한을 **`pair-site` 출처에 한해** 바꾸는 개정이다 — 168 h는 브라우저의 "로그인 유지"를 위한 값이고(D-193 6항), 브라우저 출처(`pair-physical`·`pair-admin`)에는 그대로 남는다. 만료 없는 사이트 토큰은 만들지 않는다.
   - **관리자 등록 코드에서 나온 사이트 토큰(D-193 M2).** 만료 = `min(사이트 수명, 발급자 토큰 만료)`로 한다. D-193 M2를 고치지 않는다. 근거: 카드 관리자 토큰(만료 없음)이 발급하면 결과는 그대로 90일이고, 만료가 있는 페어링 관리자(최대 24 h)가 발급한 코드로 90일짜리 사이트 자격이 생기면 짧은 세션이 긴 자격을 낳는 M2의 구멍을 다시 여는 것이다. 콘솔은 교환 결과의 실제 만료를 보이고, 사이트 수명보다 짧으면 "발급한 관리자 세션의 만료에 묶였습니다 — 카드 관리자 토큰으로 발급한 코드면 N일"을 함께 적는다.
   - **옛 이미지 호환.** `PairRequest`는 모르는 필드를 무시하므로 옛 이미지는 `purpose`를 버리고 `pair-physical` 토큰(operator, 168 h)을 준다. Fleet은 응답 `source`를 보고 등록을 받아들이되 "이 이미지는 사이트 수명을 모름 — 7일 뒤 새 코드 필요"로 표시한다. 응답 역할이 `administrator`면(부팅 코드 정책이 관리자인 카드) Fleet은 즉시 `logout`하고 거절한다. viewer도 같다.
   - **만료 처리.** 만료 경고는 Fleet 자기 시계로 잡는다: `경고 기준 = Fleet이 교환 응답을 받은 시각 + (expires_at − whoami.created_at)`. Pi 시계가 틀려도 경고 시점이 흔들리지 않는다. 14일 전(옛 이미지는 48 h 전)부터 경고하고, 만료되거나 401이 오면 상태 `needs_new_code` "새 코드 필요"로 두고 자동 재시도하지 않는다.
3. **결속과 위장 방지: 신원은 인증된 읽기에서, 주소는 등록 때 고정한다.**
   - **결속 키.** 등록 순간 `system/info`에서 `robot_id`, `hostname`, `serial_number`, `device_uid`(S4에서 추가, 옛 이미지는 없음)를 읽어 저장한다. 발견 행에서 온 등록이면 `system/info.hostname`이 브리지 행의 avahi 호스트 이름(`<host>.local`에서 `.local`을 뗀 것)과 TXT `name` 모두와 같아야 한다. avahi 인스턴스 이름(`ROSY %h` 같은 표시용 문자열)은 비교하지 않는다. 다르면 등록하지 않는다(**잘못된 로봇**). 수동 주소 등록은 비교할 발견 행이 없으므로 읽은 `hostname`·`robot_id`를 완료 화면에 크게 보이고 감사에 남긴다.
   - **`robot_id`가 로스터 키다.** `robots.yaml`의 정적 로봇과 같은 `robot_id`면 409 — 파일 항목이 이긴다. 이미 등록된 `robot_id`면 409 **이미 등록됨**. 바꾸려면 먼저 해제(6항) 뒤 새로 등록한다. 첫 조각에 "교체"는 없다.
   - **주소는 등록 때 해석된 IPv4:포트로 고정한다.** 전송 주소는 그 값뿐이다. 이후 발견 스캔에서 같은 이름이 다른 주소로 보이면 상태를 **`address_changed` "주소 바뀜 — 확인 필요"**로 두고 **어느 주소에도 Bearer를 보내지 않는다**(옛 주소는 다른 기기가 받았을 수 있고, 새 주소는 확인되지 않았다). 운용자의 선택은 둘이다: (a) 해제 후 새 코드로 다시 등록(확인이 있는 길), (b) 이름 있는 operator의 **"새 주소로 옮기기"** — 감사에 남는 명시적 확인이며, Fleet은 그 뒤 새 주소에 Bearer로 `system/info`를 읽어 결속 키가 다르면 즉시 `needs_new_code`로 두고 "토큰이 다른 기기에 갔을 수 있음 — 로봇 대시보드에서 사이트 토큰을 회수하고 새로 등록"을 띄운다. 자동 추종은 없다. README는 등록 로봇에 공유기 DHCP 예약을 권한다.
   - **`address_changed`에서도 정지는 고정 주소로 간다.** `estop_all`과 로봇별 정지 요청만은 고정 주소에 계속 보낸다. 정지가 로봇에 닿지 못하는 위험이 토큰이 다른 기기에 새는 위험보다 크다(정지 요청이 새도 그 토큰의 노출은 3항 한계 안이고, 이미 평문 LAN이다). 상태 읽기·목표·모드 같은 나머지 요청은 보내지 않는다.
   - **움직이던 로봇이면 경보.** `address_changed`가 된 로봇에 진행 중 목표나 대형 참여가 있으면 콘솔이 경보("주행 중 로봇의 주소가 바뀜 — 상태를 모름")를 띄우고, 교통 정리는 그 로봇을 마지막 알려진 위치·점유 경로의 **막힌 장애물**로 두고 그 경로와 겹치는 다른 로봇의 하달을 보류한다. 대형은 멈춤 요청 뒤 해제한다.
   - **충돌이 우선이다.** 한 이름이 여러 주소에 동시에 보이면 상태는 `address_changed`가 아니라 발견의 `conflict`다(고정 주소가 그중 하나여도). 정지 규칙은 같다.
   - **등록 버튼은 발견 상태가 등록 대기일 때만 켜진다.** 충돌 행에는 코드를 보낼 수 없다. 스캐너가 오프라인이어도 "주소로 추가"는 된다.
   - **한계(평문 LAN).** 발견은 위장할 수 있고 CORE에는 Bearer 없이 장치를 증명하는 경로가 없다(D-193 S3 기록). 같은 이름으로 먼저 광고해 코드를 가로채 진짜 로봇에 중계하는 공격은 이 ADR로 막지 못한다. 평문 HTTP에서는 수동 도청으로도 같은 토큰을 얻으므로 위협 모델은 D-193 §10(운영자 전용 SSID/VLAN)과 같다. 해제 조건은 9항이다.
   - **위협 변화(명시).** `purpose`는 인증 없는 `auth/pair`에서 **호출자가 고른다.** 그래서 LCD 코드를 읽은 누구나 — 옆에 선 사람, 사진을 찍은 휴대폰, 코드를 중계받은 사람 — Fleet 대신 `purpose: "site"`로 교환해 **90일짜리 operator 토큰**을 얻는다. D-193에서 같은 코드가 주던 최대 수명은 168 h였다. 사용자 결정(2026-09-29)으로 90일 기본값을 유지하고, 대응은 (a) 코드는 한 번만 쓰이므로 Fleet 등록이 실패하면 운용자가 즉시 안다("코드가 틀렸거나 이미 쓰였습니다"), (b) operator가 로봇 대시보드에서 사이트 토큰 목록을 보고 회수한다(2항), (c) 사람이 많은 곳은 카드 `login.boot_code: off`나 짧은 `site_token_days`를 쓴다(README)이다.
4. **저장: Fleet SQLite의 등록부 + 토큰은 AES-256-GCM 암호문, 키는 별도 Compose secret.**
   - `robots.yaml`은 고치지 않는다. root 소유·읽기 전용인 사람 관리 파일이고, 서버가 그것을 다시 쓰면 D-302의 "설치자가 검토한 설정" 경계가 깨진다. `robots.yaml`은 정적 로봇·시뮬용으로 남고, 등록부가 켜진 기동에서는 없거나 빈 목록이어도 된다.
   - 표 `robot_enrollments`: `robot_id`, 결속 키, 발견 이름, 고정 주소, CORE 토큰 id·역할·출처·`expires_at`·Fleet 기준 경고 시각, 암호문, 등록자 principal, 상태(`active`·`needs_new_code`·`address_changed`·`pending_logout`), 시각. 감사는 11항의 공유 표에 쓴다. 코드·토큰 원문은 감사·로그·응답·예외 메시지에 싣지 않는다.
   - **암호화.** `cryptography` AESGCM, 키 32 byte, 행마다 새 96 bit nonce. AAD는 길이 접두 부호화 `len‖"rosy-robot-cred/1" ‖ len‖slot ‖ len‖robot_id ‖ len‖token_id`(각 길이는 4 byte 빅엔디언)이고 `slot`은 `rest`(이 조각) 또는 `agent`(S6 짝 토큰)다 — 이어 붙이기 모호성과 칸 바꿔치기를 막는다. 키 파일은 **base64 44자(32 byte) 한 줄만** 받는다. 키는 새 secret `robot_credential_key`(`${ROSY_SITE_SECRETS_DIR}`, root 소유, 그룹 10001 읽기)이며 다른 모든 사이트 비밀과 달라야 한다(`create_app` 중복 거절 목록에 더함).
   - **키 실패는 실행 상태다.** 키가 없거나 형식이 틀리거나 복호가 실패하면 등록 라우트는 503을 내고 등록 로봇은 이번 실행 동안 로스터에 오르지 않으며 패널이 "자격 키를 읽을 수 없음"을 보인다. **이 상태를 DB에 쓰지 않는다** — 키를 바로잡고 다시 띄우면 코드 재입력 없이 돌아온다. `robots.yaml` 경로는 그대로 돈다.
   - **키 보관·교체(README).** 키는 DB 백업과 **다른** 보관처에 백업한다(둘을 한 매체에 두면 암호화의 뜻이 없다). 키를 잃으면 모든 등록 로봇을 다시 등록해야 한다. 교체는 오프라인 명령 `site_db.py rekey --old-key-file --new-key-file`(Fleet 정지 상태, 전부 다시 봉인한 뒤 원자적 교체)로 하고 첫 조각 범위다.
   - 근거: Fleet SQLite는 백업 절차가 별도 대상으로 복사한다(`deploy/site/README.md` Backup). DB 사본만으로는 토큰이 나오지 않고, 키와 DB를 함께 복원하면 되살아난다. D-341은 digest만 저장하는데, 거기서는 Fleet이 자격을 **검증하는 쪽**이기 때문이다. 여기서는 Fleet이 CORE에 자격을 **제시하는 클라이언트**라 원문이 필요하고, 그래서 암호문이다.
5. **로스터 소유자는 하나다.** 새 `SiteRoster`가 정적(`robots.yaml`)과 등록 로봇의 유일한 목록이다. 추가·제거는 한 곳에서 콘솔 클라이언트, Hub 클라이언트, Hub 짝 토큰, `FleetTaskService.robot_ids`, sighting 검증의 알려진 로봇 목록을 함께 바꾼다.
   - `snapshot`·`_observe`·`estop_all`·`map()`·`_make_room`은 `await` 전에 `order = list(self._order)`로 순서를 복사해 순회한다. 추가·제거가 진행 중인 수집·정지와 엇갈리지 않는다. 정지(`estop_all`)는 등록 로봇에도 닿는다.
   - 제거 때 그 로봇의 `RobotClient`(httpx)를 닫는다. 대형 구성원이거나 끝나지 않은 task(대기·배정·진행)가 있으면 해제를 409로 거절하고 목록을 보인다. 운용자가 먼저 취소한다.
   - sighting 설정(`site-sightings.yaml`의 `robot_ids`)은 기동 때 로스터 전체(정적 + 등록부)로 검증한다. 해제됐거나 `pending_logout`인 등록 로봇을 가리키는 항목만 **기동 실패가 아니라** 경고와 함께 그 로봇 매핑을 끈다 — 해제 한 번이 다음 Fleet 기동을 깨지 않는다. 등록부에도 `robots.yaml`에도 없던 `robot_id`(오타)는 지금처럼 기동을 거절한다.
6. **해제·회수.**
   - 콘솔 **등록 해제**(이름 있는 operator): (S6이 켜져 있으면 이벤트 연결 해제 먼저) Fleet이 그 토큰으로 `auth/logout` → 등록부 행 삭제 → 감사.
   - 로봇에 닿지 않으면 로스터에서는 바로 빼되 행을 `pending_logout`으로 남기고 암호문을 지우지 않는다. Fleet은 고정 주소가 다시 응답하고 **그 이름이 다른 주소에 보이지 않을 때** `logout`을 **한 번** 부른다(`system/info` 사전 읽기 없음 — 결속 확인을 위해 Bearer를 한 번 더 보낼 이유가 없다). 성공하면 행을 지우고, 실패하면 행과 수동 회수 안내를 남기고 더 시도하지 않는다. 패널은 "로봇에 토큰이 남아 있음(만료 `expires_at`) — 로봇 대시보드에서 회수 가능"을 보인다.
   - 로봇 쪽 회수(대시보드 토큰 삭제) → Fleet은 401을 보고 `needs_new_code`로 바꾸고 자동 재시도하지 않는다.
   - 권한: 등록·해제·새 주소로 옮기기는 `require_named_operator`(D-276·D-341 5항과 같음). 단일 console 토큰 구성에서는 403이고, 403 문구는 라우트별로 매개변수화한다. `viewer`는 패널을 읽기만 한다.
7. **FleetAgent 이벤트 경로: 같은 등록 흐름이 짝 토큰까지 넣는다 — 단, D-351 Hub 결속 수정 뒤에 연다.**
   - CORE 새 경로 `PUT /api/v1/fleet/link`·`DELETE /api/v1/fleet/link`(S6). 긴 수명의 사이트 토큰 하나로 로봇의 이벤트 목적지를 바꿀 수 없게, **`PUT`은 사이트 토큰에 더해 새 로봇 화면 코드를 요구한다**(본문 `code`; CORE가 D-193 교환과 같은 검증·시도 횟수·폐기 규칙으로 소모). 그 코드의 역할은 operator 이상이어야 한다. 관리자 등록 코드도 받는다(역할이 operator 이상이고 코드 자체가 일회용·5분이므로 LCD 코드와 같은 성질이다). viewer 코드는 403. 그래서 이벤트 연결은 "등록할 때 같은 코드로 한 번에"(교환과 연결을 한 요청 흐름으로 묶는 CORE 경로는 S6에서 정한다) 또는 "나중에 새 코드로" 한다. `DELETE`는 사이트 토큰만으로 된다(끊는 쪽은 권한을 좁힌다). 본문은 `hub_url`(`wss://`만), 사이트 CA PEM, Fleet이 만든 256 bit `pairing_token`. CORE는 `patch_local_config`로 오버레이 `fleet.*`에 쓰고 FleetAgent를 프로세스 안에서 `stop()`→`start()`한다. **CORE 재시작이 없다.** 설정 여부 조회는 인증된 `GET`(viewer 이상)만 두고, 인증 없는 조회는 만들지 않는다.
   - Fleet은 같은 짝 토큰을 등록부(슬롯 `agent` 암호문)와 로스터를 통해 Hub 토큰 표에 넣는다. REST 토큰과 짝 토큰이 같으면 거절하는 기존 규칙은 유지한다.
   - **여는 조건(모두 필요):** (a) D-351 S2의 Hub 세션-로봇 결속과 상수 시간 비교가 `main`에 있다, (b) Fleet이 로봇에서 닿는 `wss://` 주소와 그 SAN을 가진 사이트 인증서를 가진다(D-351 발견 5), (c) S4의 `device_uid`가 HELLO에 실린다. 그 전까지 등록된 로봇은 발견 상태 **등록됨**(REST 확인, 이벤트 연결 전)에 머문다.
   - 평문 `ws://` 짝 연결은 이 경로로 만들지 않는다. CA PEM이 평문 HTTP로 가는 위험은 3항 한계와 같고 9항 조건이 풀 때 함께 풀린다.
8. **발견 상태와 용어.** 발견 상태는 `registration_pending` "등록 대기" → `enrolled` "등록됨"(새, REST 결속 확인) → `verified_online` "확인됨"(FleetAgent HELLO가 같은 이름·UID로 온라인)이고, `pairing_pending`은 "이벤트 연결 대기"로 문구를 바꾼다(`robots.yaml` 로봇용). `conflict` "신원 충돌"은 그대로다. 등록부 상태(2·3·6항)는 로스터 행에 따로 보인다. 로스터 행은 출처 **파일**/**등록**을 보인다.
9. **전송 위험과 TLS 조건.** 코드·토큰·(7항의) 짝 토큰·CA가 로봇 LAN 평문 HTTP로 간다. 받아들이는 조건: 로봇 LAN이 운영자 전용 SSID/VLAN이다(사이트 검증 기록에 적는다). 다음 중 하나면 **로봇 CORE TLS ADR이 먼저**이고 이 등록은 FIELD 판정을 받을 수 없다: 로봇 LAN을 운영자 밖 사람·장치와 공유한다, Fleet과 로봇이 라우팅된 다른 망에 있다, 한 Fleet이 여러 사이트의 로봇을 관리한다(중앙 Fleet), 사이트 로봇이 10대를 넘는다. Fleet이 로봇에 보내는 **모든** HTTP — 등록 교환과 운용 `HttpRobotClient`(`swarm/transport.py:140`) 둘 다 — 는 `trust_env=False`(환경 프록시가 Bearer를 가로채지 않게)로 만들고, 등록 교환은 추가로 리다이렉트 금지, 연결 3 s·전체 10 s 제한이다.
10. **오류 문구(서버가 말한 것만 말한다, D-193 S3 규칙).**
    - 입력 칸은 공백·하이픈을 버리고 알파벳·길이를 먼저 본다 — 형식이 틀리면 로봇에 보내지 않아 시도 횟수를 쓰지 않는다. Fleet은 교환을 **자동 재시도하지 않는다.**
    - 401: "코드가 틀렸거나, 이미 쓰였거나, 만료됐습니다. 선택한 행의 이름이 로봇 화면의 이름과 같은지 확인하세요." 401 `detail.burned`: "이 로봇의 화면 코드가 폐기됐습니다 — 로봇 전원을 다시 넣거나 관리자 등록 코드를 받으세요." 429: `Retry-After` 초 동안 버튼을 끈다. 403 `FORBIDDEN`: "로봇이 이 서버를 LAN 밖으로 봅니다(주소 변환 확인)." 연결 실패: "로봇에 닿지 않습니다(주소·포트)."
    - **코드를 소모한 뒤의 실패**(교환은 성공했으나 관리자·viewer 역할, 잘못된 로봇, `robot_id` 충돌, 저장 실패로 `logout`한 경우)는 공통으로 "코드가 소모됐습니다 — 로봇을 재시작하거나 관리자 코드를 받으세요"와 원인 한 줄을 보인다. `wrong_robot` 도움말에는 한 줄을 더한다: "같은 이름의 기기가 둘이면 Avahi가 한쪽을 `<이름>-2.local`로 바꿉니다 — 발견 목록에 `-2`가 붙은 행이 있으면 그 기기부터 확인하세요."
11. **D-341과의 관계.** 방향이 반대다: 카메라는 기기가 요청하고 콘솔이 기기 화면의 확인 코드를 입력해 승인한다(기기 → 사이트). 로봇은 콘솔이 로봇 화면의 코드를 입력해 사이트가 로봇에서 자격을 받는다(사이트 → 로봇).
    - **패널 이름은 "기기 연결" 하나다.** D-341 계획의 "기기 연결 요청" 패널을 이 이름으로 부르고, 그 안에 구역 **카메라 연결 요청**(D-341)과 **로봇 등록**(이 ADR)을 둔다. 사람에게 보이는 동사는 로봇 **등록**, 카메라 **연결 승인**이다.
    - **감사 표는 하나다.** D-341 계획의 `device_pairing_audit`(보존 상한 10,000행)에 `device_kind`(`overhead-camera`·`robot`) 열을 두고 두 절차가 같은 열(시각, `device_kind`, 동작, 결과 분류, principal_id, 대상 식별자, 원문 없음)로 쓴다.
    - **먼저 착지하는 브랜치가 패널 틀과 감사 표를 만들고, 뒤에 착지하는 쪽이 맞춘다.** 지금 D-341이 계획상 앞서 있으므로 기본은 D-341이 만들고 D-352 S1–S3이 거기에 구역·`device_kind='robot'` 행을 더한다. D-352가 먼저 착지하면 같은 이름·열로 만들고 D-341이 구역을 더한다. D-341 계획의 표에는 `device_kind`가 없으므로, D-341이 먼저 착지하면 D-352 S1이 `ALTER TABLE device_pairing_audit ADD COLUMN device_kind TEXT NOT NULL DEFAULT 'overhead-camera'` 이전 단계를 둔다(기존 행은 카메라).
    - 저장은 다르다: D-341은 digest만(Fleet이 검증자), D-352는 암호문(Fleet이 클라이언트, 4항). 수명도 다르다. D-341 18항의 역할 등록표에 로봇을 넣지 않는다 — 로봇 쪽 코드 발급자는 CORE이고 절차가 다르다.
12. **정직한 사용성 범위.**
    - 운용자 동작은 **로봇 전원 켜기 → 등록 클릭 → 8자 입력** 셋이다. SSH, 파일 편집, CORE·Fleet 재시작이 없다.
    - **"SSH 없음"은 LCD가 있고 카드 `login.boot_code`가 기본(`operator`)인 로봇에만 성립한다.** LCD가 없는 보드나 `boot_code: off` 카드는 관리자 등록 코드(로봇 대시보드의 관리자 세션 필요) 또는 SSH `sudo rosy-login-code`가 코드의 출처다. 이 범위 제한을 README와 패널 도움말에 적는다.
    - **재부팅 비용.** 새 LCD 코드는 부팅당 하나다. 따라서 (a) 첫 등록에는 새 코드가 필요하다 — 그 부팅의 코드를 이미 대시보드 로그인에 썼다면 전원 재투입 또는 관리자 코드, (b) 이후 사이트 토큰 수명마다 한 번(기본 90일, 옛 이미지는 7일), (c) 코드를 소모한 실패(10항) 뒤마다 한 번, (d) S6 이벤트 연결을 등록과 따로 켤 때 한 번(7항 `PUT`이 새 코드를 요구한다 — 등록과 같은 코드로 묶는 CORE 경로가 생기면 없어진다). 콘솔 도움말이 이것을 먼저 말한다.

### ADR 항목 ↔ 계획 단계, 첫 조각

| ADR 항목 | 계획 단계 |
|---|---|
| 1 흐름, 3 결속·주소 고정, 6 해제, 10 오류 | S2 |
| 2 자격 — Fleet 쪽 판정(출처·역할 검사, 옛 이미지, 만료 경고) | S2 |
| 2 자격 — CORE 쪽(`purpose`, `pair-site`, 수명, M2, operator 회수), 3의 `device_uid` | S4 (이미지) |
| 3 `address_changed` 정지·경보·교통 보류·충돌 우선 | S2 |
| 4 저장·키, 5 로스터 소유자 | S1 |
| 8 상태·용어, 11 패널·감사, 12 사용성 문구 | S3 (감사 표는 S1) |
| 9 전송(`trust_env=False`) | S1(운용 클라이언트)·S2(교환) |
| 7 이벤트 연결 | S6 (조건부) |

**첫 조각(현 이미지로 쓸 수 있는 최소)** = S1–S3: 등록부·키·로스터 소유자, 교환·결속·주소 고정·해제·만료 경고, 패널. 상태는 `active`·`needs_new_code`·`address_changed`·`pending_logout`만. 첫 조각에 없는 것: 주소 자동 추종, 격리 해제, 교체, 갱신·회전, 이벤트 연결, CORE 변경. 옛 이미지에서는 7일마다 새 코드가 필요하다는 것을 첫 조각의 알려진 한계로 적는다.

### 판정 등급 (Acceptance gates)

| 등급 | 인정하는 증거 |
|---|---|
| SOURCE | 이 ADR, 계획, ADR Log 행, 하네스 lint(이 변경이 만든 오류 없음). README·발견 규칙 교차 참조는 구현 단계에서 |
| LOCAL | 계획 S1–S3 pytest·node 녹색: 가짜 CORE(`httpx.MockTransport`)에 대한 등록·잘못된 로봇·관리자 코드 거절·옛 이미지 모양 응답·주소 바뀜에서 Bearer 0회·해제·`pending_logout` 재시도, 로스터 추가 뒤 e-stop 도달·진행 중 수집과 추가의 정렬·등록 로봇의 task 생성, 등록부 DB 사본만으로 토큰이 안 나오는 시험. 저장소 루트 `test/`의 결합 시험 하나가 **현재 CORE 코드**로 교환→`whoami`→`system/info`→`logout`을 돈다 — 이것은 코드 수준 증거이고 배포 이미지의 증거가 아니다. S4 이후 같은 결합 시험이 `pair-site`로 돈다 |
| DEVICE | 벤치 로봇 `rosy-pinky-8kcn`, 같은 Wi-Fi의 벤치 Fleet, 이동·정지 명령 없음, SSH 없음. **(D1, 현 이미지 `2026.09.27-010`)** 전원 재투입 → LCD 코드 → 콘솔 **등록** → 로스터에 온라인·상태 신선 → 로봇 쪽 토큰 존재 확인 → Fleet 재시작 뒤 온라인 → **등록 해제** 뒤 로봇 쪽 토큰 부재 확인. "로봇 쪽 확인"에 쓴 자격은 계획 벤치 절차의 두 방법 중 하나로 정하고 기록한다. 옛 이미지 동작의 증거는 D1뿐이다. **(D2, S4 이미지)** `pair-site` 출처·90일 만료·`device_uid` 결속, 공유기에서 DHCP 주소를 바꿨을 때 `address_changed`로 멈추고 정지 외 Bearer를 보내지 않음 — 증거는 벤치 Fleet의 httpx 요청 로그(`httpx` 로거 INFO, 요청 줄만, 헤더 없음)에서 옛·새 주소로의 요청 목록이며, 가능하면 벤치 PC 패킷 캡처(`tcp port 8080`, `Authorization` 문자열 검색 수만 기록)로 교차 확인한다. **(D3, S6)** 같은 등록 흐름으로 FleetAgent HELLO가 `verified_online`, CORE 재시작 없이 이벤트가 Fleet SQLite에 쌓임 |
| FIELD | 실제 Ubuntu 사이트 호스트(Avahi 브리지, Compose, 사이트 CA)에서 4대 이상 등록, 재부팅·DHCP 예약 포함, 9항 운영자 전용 망 기록. D-351 Decision 5의 관제 DEVICE 다섯 항목이 별도로 필요 |

host pytest 통과는 DEVICE가 아니고(D-91), 벤치 1대는 FIELD가 아니다(D-95).

### 이 ADR이 정하지 않는 것

- 로봇 CORE TLS의 방식(자체 서명 + 등록 때 지문 고정, 사이트 CA 발급 등). 9항은 필요 조건만 정한다.
- Bearer 없는 장치 증명(예: 토큰 digest 키의 HMAC 챌린지). 이것이 생기면 주소 자동 추종을 다시 볼 수 있다.
- 사이트 토큰 기본 90일·경고 14일의 현장 튜닝.
- operator가 로봇 대시보드에서 **사이트 전용 등록 코드**를 발급하게 할지(지금 등록 코드는 administrator만). 열리면 재부팅 비용이 준다.
- LCD에 "사이트 등록됨: <이름표>"를 띄울지(표시기는 CORE 밖 `rosy-display`, D-190 경로 필요). LCD QR 입력.
- 여러 사이트가 한 로봇을 동시에 등록하는 것(막지 않지만 지원하지 않는다), 사이트 간 이전, 등록 교체.
- SRS SEC-201 문구("Fleet이 발급한 페어링 토큰을 로봇 설정에 입력") 개정. 7항이 그 의도를 사람 입력 없이 채우므로 Clarify 행으로 맞추는 것은 후속이다.
- 7항의 "교환과 이벤트 연결을 한 코드로 묶는" CORE 경로 모양.

### Alternatives

- **`robots.yaml`을 계속 손으로 쓴다.** 오늘 공백 그 자체다(SSH·파일·재시작). 정적 로봇·시뮬 경로로만 남긴다.
- **SSH 스크립트가 코드 발급·교환·파일 기록을 대신한다.** 운용자 PC에 SSH 키·sudo가 필요하고, 비밀이 셸 이력과 운용자 PC에 남는다. 등록이 사이트 감사 밖에서 일어난다. 기각.
- **Fleet이 `robots.yaml`을 다시 쓴다.** root 소유·읽기 전용 설정을 서버 프로세스에 쓰기 가능하게 해야 하고, 사람이 검토한 파일과 서버 상태가 섞인다. 기각.
- **토큰을 평문으로 SQLite나 0600 파일에 둔다.** 가장 작지만 DB 백업 사본이 곧 operator 토큰 N개다. 별도 0600 파일은 백업에서 빼면 복원 때 모든 로봇을 재등록해야 한다. 기각(사용자 결정 2026-09-29: 암호화 유지).
- **7일 토큰을 회전 갱신한다(`auth/renew`, 계보 상한, 재사용 감지).** 초안이 택했던 안이다. 기각(사용자 결정 2026-09-29, 독립 리뷰 근거): 평문 HTTP 위협 모델에서는 토큰을 볼 수 있는 공격자가 갱신 요청과 응답도 보므로 회전이 더하는 보호가 작다. 반면 계보·툼스톤·유예 창·대기 토큰·Fleet 갱신 루프가 CORE와 Fleet 양쪽에 상태 기계를 만들고, 충돌 복구 규칙(저장 전 중단, 안 쓰인 자식 교체)이 시험 표면을 크게 늘린다. 긴 수명 토큰 하나 + 로봇 쪽 회수 + 만료 시 새 코드가 같은 위협 모델에서 더 단순하다. TLS가 들어와 도청 위협이 빠지면 다시 볼 수 있다.
- **7일마다 새 코드(수명 변경 없음).** 새 코드가 재부팅을 요구하므로 "간단하게"에 반한다. 옛 이미지 호환 모드로만 남는다.
- **만료 없는 사이트 토큰.** D-193 페어링 규칙을 깬다. 기각.
- **관리자 등록 코드 사이트 토큰에 D-193 M2 예외를 둔다(카드 관리자 발급자만).** 발급자가 만료 없는 카드 관리자면 `min()`이 이미 90일을 주므로 예외가 얻는 것이 없다. 기각.
- **주소 자동 추종(같은 이름의 새 IP에 Bearer로 읽어 확인).** 확인하려고 Bearer를 먼저 보내야 하므로 확인이 안 된 호스트가 토큰을 받는다. 기각 — Bearer 없는 장치 증명이 생길 때까지.
- **로봇이 코드를 들고 Fleet에 접속한다(D-341 방향).** 로봇에는 입력 장치가 없고, 로봇이 먼저 사이트 CA·주소를 알아야 한다. FleetAgent 경로만 7항처럼 등록 뒤에 연다. 기각.
- **LCD QR.** 코드가 사진 한 장에 이름과 함께 담기고 표시기 경로 변경이 필요하다. 정하지 않는 것으로 남긴다.
- **새 CORE 역할 `site`.** 2항 근거로 기각. 출처로 충분하다.

### Consequences

- CORE(S4): `pair`에 `purpose` 필드, 출처 `pair-site`(`TOKEN_SOURCES`·`PAIRED_SOURCES`), 사이트 수명 설정(D-193 168 h 상한의 출처 한정 개정), `system/info.device_uid`·`device_name`, 대시보드 보안 패널의 출처 표시, (S6) `fleet/link`. operator용 `auth/site-tokens` 목록·회수. D-193을 개정한다(`pair-site` 수명, operator 회수) — D-193 본문과 ADR Log 행에 그 표시를 둔다. 모두 additive이며 API Ref MINOR를 올리고 D-351 계약 스냅샷이 있으면 재생성한다. 이미지 재빌드가 필요하다.
- Fleet: 로스터가 동적이 되고 소유자가 하나가 된다. 자격 없는 라우트는 늘지 않는다 — 등록 라우트는 모두 이름 있는 operator 뒤다. `cryptography`가 Fleet 이미지 의존성이 되고 새 Compose secret과 오프라인 `rekey` 명령이 생긴다. 운용 `HttpRobotClient`가 환경 프록시를 무시한다.
- 운영: 로봇마다 SSH가 필요했던 등록이 콘솔 한 곳으로 모인다. 대신 Fleet 호스트와 그 키가 사이트 전체 로봇의 operator 자격을 모은 곳이 되므로, Fleet 호스트 보호와 `robot_credential_key`의 별도 보관이 사이트 검증 기록 항목이 된다. 사이트 토큰이 도난되면 로봇 쪽에서 회수할 때까지 최대 90일 유효하다 — 회수 절차를 README에 둔다.
- 현 벤치 이미지로 D1이 가능하다 — 등록 자체는 이미지 교체를 기다리지 않는다. 다만 7일 한계가 있다.

**References:** D-5, D-30, D-31, D-91, D-95, D-190, D-193, D-276, D-302, D-341(브랜치), D-351(브랜치), ROSY FLEET SRS REG-001/REG-001a/SEC-201/SEC-203, `site-lan-discovery-profile.md`, `deploy/site/README.md`.
