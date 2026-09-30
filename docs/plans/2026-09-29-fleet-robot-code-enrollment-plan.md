# 사이트 콘솔 로봇 화면 코드 등록 계획 (D-361)

**ADR:** [D-361](../adr/D-361-site-console-enrolls-robot-by-screen-code.md) (Proposed, 2026-09-29 개정)
**작성:** 2026-09-29. 기준 커밋 `main` 86ba6e4c.
**목표:** 운용자가 로봇 전원을 넣고, 콘솔에서 **등록**을 누르고, 로봇 화면의 8자를 치면 그 로봇이 사이트 로스터에 들어온다. SSH·`robots.yaml` 편집·재시작이 없다(범위: LCD가 있고 `login.boot_code`가 기본인 로봇, ADR 12항). 순서는 **현 로봇 이미지로 쓸 수 있는 첫 조각(S1–S3) → CORE 이미지 변경(S4) → 이벤트 연결(S6, 조건부)** 이다. 갱신·회전 단계는 없다(사용자 결정 2026-09-29, ADR Alternatives).

## ADR 항목 ↔ 단계

| ADR 항목 | 단계 |
|---|---|
| 4 저장·키, 5 로스터 소유자, 9 운용 클라이언트 `trust_env=False`, 11 감사 표 | S1 |
| 1 흐름, 2 Fleet 쪽 판정·만료 경고, 3 결속·주소 고정·`address_changed` 정지·경보·교통 보류·충돌 우선, 6 해제, 9 교환 제한, 10 오류 | S2 |
| 8 상태·용어, 11 패널, 12 사용성 문구 | S3 |
| 2 CORE 쪽(`purpose`, `pair-site`, 수명, M2 `min()`, operator 회수 경로), 3 `device_uid`, D-193 개정 표시 | S4 |
| 7 이벤트 연결 | S6 |

**첫 조각 = S1–S3.** 등록부 상태는 `active`·`needs_new_code`·`address_changed`·`pending_logout`만. 주소 자동 추종·격리 해제·교체·갱신·이벤트 연결·CORE 변경은 첫 조각에 없다. (S5 번호는 비워 둔다 — 초안의 갱신 단계가 빠졌다.)

## 범위 밖

- 로봇 CORE TLS(ADR 9항 조건만), 이미지 재빌드·서명·배포 시점.
- 천장 카메라 연결 승인(D-341). S3의 "기기 연결" 패널 틀과 `device_pairing_audit` 표는 먼저 착지하는 쪽이 만든다(ADR 11항).
- D-382 계약 스냅샷·적합성 탐침 자체. S4가 API를 바꿀 때 스냅샷이 `main`에 있으면 같은 변경에서 재생성한다.
- 이동·정지 명령의 실물 시험.

## 규칙

- 단계마다 먼저 실패하는 시험을 쓰고, 고치고, 단계 끝에 커밋한다. 커밋 메시지는 `Co-Authored-By` 줄로 끝난다.
- Windows에서는 `python`을 쓴다. pytest는 `--basetemp`를 `X:\DevTemp\...` 아래로 준다.
- 코드·토큰 원문은 시험 픽스처의 가짜 값만 쓴다. 로그·감사·응답·예외 메시지에 원문이 없음을 시험으로 고정한다(`caplog`·응답 본문 검색).
- Fleet 패키지는 CORE 코드를 import하지 않는다(D-18, D-59). Fleet 시험의 가짜 CORE는 `httpx.MockTransport`다. 실제 CORE와의 결합 시험은 **저장소 루트 `test/`**의 한 파일만 두 쪽을 함께 띄운다.
- 결합 시험은 **현재 소스의 CORE**를 돌린다. 배포 이미지의 증거로 쓰지 않는다 — 옛 이미지 동작의 증거는 벤치 D1뿐이다.
- 모듈 기록: 바꾼 모듈의 `logs.md`에 추가하고, gate가 바뀌면 `progress.md`를 고치고, `python tools/harness/rosy_harness.py generate` 후 `lint`.
- 실물 로봇 작업은 "벤치 절차"의 명시적 회차에만 한다. SSH 금지.

## S1 — 등록부·키·단일 로스터 소유자

**왜:** 로스터가 기동 때 고정이고 콘솔·Hub·task 서비스·sighting 검증에 따로 복사된다. `await` 사이에 순서 목록을 그대로 순회한다. 자격을 둘 Fleet 소유 저장소가 없다.

**파일**
- 새 `src/site/fleet/fleet/server/enrollment_store.py`: 표 `robot_enrollments`(ADR 4항 열, 상태 4개). `seal(token, *, slot, robot_id, token_id)`/`unseal(...)` — `AESGCM`, 행마다 새 12 byte nonce, AAD는 길이 접두(4 byte 빅엔디언) `"rosy-robot-cred/1"‖slot‖robot_id‖token_id`, `slot ∈ {"rest","agent"}`. 키 파일은 base64 44자 한 줄만(원시 바이트·공백 뒤섞임 거절). `sqlite_policy.configure_connection`/`enable_wal` 재사용.
- 감사: `device_pairing_audit`(보존 10,000행, `device_kind` 열). D-341 `pairing_store.py`가 이미 `main`에 있으면 이전 단계 `ALTER TABLE device_pairing_audit ADD COLUMN device_kind TEXT NOT NULL DEFAULT 'overhead-camera'`(열이 없을 때만, `PRAGMA table_info`로 확인)를 먼저 돌리고 그 표에 `device_kind='robot'` 행을 쓰고, 없으면 같은 이름·열로 여기서 만든다(D-341이 맞춘다).
- 새 `src/site/fleet/fleet/server/roster.py`: `SiteRoster` — 정적 + 등록 엔드포인트의 유일한 목록. `add(endpoint)`/`remove(robot_id)`가 한 번에 바꾸는 것: `FleetConsole` 클라이언트·순서·`_registered_endpoints`·REST 토큰, `SiteHub` 클라이언트·짝 토큰(`set_pairing_token`/`drop`), `FleetTaskService.robot_ids`, sighting 검증의 알려진 로봇. 제거 전 검사: 대형 구성원 → 409, 끝나지 않은 task(대기·배정·진행) → 409 + 목록. 제거 뒤 그 로봇의 `RobotClient.aclose()`.
- `src/site/fleet/fleet/server/console.py`: 로스터 변경 메서드를 `SiteRoster`만 부르게 하고, `snapshot`(:168-173)·`map()`(:216-218)·`_make_room`·`_observe`(:466-469)·`estop_all`(:695-700)이 `await` 전에 `order = list(self._order)`로 순회. 제거 때 `_goals`·`_claims`·`_queued`·`_yielding`·`_seen` 정리.
- `src/site/fleet/fleet/hub/hub.py`: 짝 토큰 표 동적화(`set_pairing_token`, `drop`).
- `src/site/fleet/fleet/server/task_service.py`: `robot_ids`를 로스터가 바꿀 수 있는 속성으로(`frozenset` 교체).
- `src/site/fleet/fleet/server/sightings_config.py`·`cli.py:353`: 알려진 로봇 = 로스터 전체. 등록부에서 해제됐거나 `pending_logout`인 `robot_id`만 기동 실패가 아니라 경고 + 그 로봇 매핑을 끈다. 등록부에도 `robots.yaml`에도 없던 `robot_id`는 지금처럼 기동 거절.
- `src/site/fleet/fleet/swarm/transport.py:140`: `HttpRobotClient`의 `httpx.AsyncClient(..., trust_env=False)`.
- `src/site/fleet/fleet/swarm/robots.py`: `load_robots(path, allow_empty=False)`.
- `src/site/fleet/fleet/server/app.py`: `create_app(..., roster, enrollment_store=None)`. 자격 분리 검사가 등록부 토큰(기동 때 한 번 복호, 메모리에만)도 본다. 키 실패는 실행 상태(`enrollment_available=False`, 사유)로만 들고 DB에 쓰지 않는다.
- `src/site/fleet/fleet/cli.py`: `console --robot-credential-key-file PATH`(`--tasks-db` 필수). 키가 있으면 `--robots` 선택 사항.
- `deploy/site/site_db.py`: `rekey --old-key-file --new-key-file`(Fleet 정지 상태, 트랜잭션 하나로 전부 다시 봉인).
- `deploy/site/requirements-fleet.txt`: `cryptography==<고정판>`. `src/site/fleet/package.xml`: `python3-cryptography`. `deploy/site/compose.yaml`: secret `robot_credential_key`. 새 `deploy/site/robot-credential-key.template.txt`(형식만).

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/test_enrollment_store.py`: 봉인·개봉 왕복, 슬롯·`robot_id`·`token_id` 하나라도 바꾸면 개봉 실패, 이어 붙이기 모호성(`("ab","c")` vs `("a","bc")`) 구분, 다른 키 실패, DB 파일 바이트에 원문 없음, 원시 32 byte·짧은·긴 키 거절, `rekey` 왕복, 감사 상한.
- 새 `src/site/fleet/test/test_site_roster.py`: 추가 → 콘솔 스냅샷·Hub·task 서비스·sighting 검증에 동시에 보임, **추가한 로봇에 `estop_all`이 닿음**, **수집(`snapshot`) 진행 중 추가해도 클라이언트·결과 정렬 유지**(느린 가짜 클라이언트로 `await` 사이 추가), **등록 로봇으로 task 생성 성공**, 제거 → 클라이언트 `aclose` 호출·목표 정리, 대형 구성원·진행 task 409, 정적 `robot_id` 중복 추가 거절.
- `src/site/fleet/test/test_hub.py`: 동적 짝 토큰 추가·삭제 뒤 HELLO 수락·거절.
- `src/site/fleet/test/test_transport.py`: `HttpRobotClient`가 `HTTP(S)_PROXY` 환경을 무시.
- `src/site/fleet/test/test_server_app.py`: `robot_credential_key`가 다른 비밀과 같으면 기동 거절, 키 실패 시 앱은 뜨고 등록 라우트 503·DB 상태 불변. `test_cli.py`: 키 없이 `--robots` 생략 거절, 해제된 로봇을 가리키는 sighting 설정으로도 기동 성공(경고), 한 번도 없던 `robot_id`는 기동 거절 유지.
- `src/site/fleet/test/test_robots.py`: `allow_empty` 경로, 기존 거절 유지.

**완료 기준:** 위 시험과 Fleet 스위트 녹색. `robots.yaml`만 쓰는 기존 구성의 동작이 그대로다.

## S2 — 등록 서비스와 API (현 이미지 호환)

**파일**
- 새 `src/site/fleet/fleet/server/enrollment.py`: `EnrollmentService`.
  - `enroll(candidate, code, principal)`: 코드 정규화·형식 검사(알파벳 `23456789ABCDEFGHJKMNPQRSTUVWXYZ`, 8자) → `POST /api/v1/auth/pair` `{code, label: "site:<fleet_name>", purpose: "site"}` → 역할 검사(operator만; 아니면 `logout` 후 "코드 소모" 거절) → `whoami`·`system/info` → 결속 검사(발견 행이면 `system/info.hostname` == 브리지 행 `hostname`에서 `.local`을 뗀 값 == TXT `name`; 정적·등록 `robot_id` 충돌) → 봉인 저장(슬롯 `rest`) → `roster.add` → 감사. 실패 경로는 받은 토큰을 `logout` 후 버린다. 자동 재시도 없음.
  - 후보 주소: 발견 행의 해석 IPv4:포트, 또는 수동 입력 — **사설 IPv4[:포트]만**(`.local`·호스트명·공인 주소 거절, 포트 기본 8080). 등록부에 고정 주소로 저장.
  - 만료 경고 기준: `Fleet 수신 시각 + (expires_at − whoami.created_at)`. 14일 전 경고(`pair-physical`은 48 h 전). 만료·401 → `needs_new_code`.
  - `on_discovery(scan)`: 등록 로봇 이름이 고정 주소와 다른 **한** 주소로 보이면 `address_changed`, 여러 주소에 동시에 보이면 `conflict`(우선). 두 상태 모두 그 로봇 클라이언트는 **정지 요청만** 고정 주소로 보내고 나머지(상태·지도·목표·모드)는 멈춘다. 원래 주소로만 다시 보이면 `active`로 복귀.
  - 진행 중 목표·대형이 있는 로봇이 `address_changed`/`conflict`가 되면 콘솔 경보를 올리고, `console.py` 교통 정리(`_run_traffic`)가 그 로봇을 마지막 pose·점유 경로의 막힌 장애물로 두고 겹치는 하달을 `_queued`로 보류한다. 대형이면 정지 요청 뒤 대형 해제.
  - `move_address(robot_id, principal)`: 이름 있는 operator의 명시적 확인 → 새 주소로 `system/info` 결속 확인 → 같으면 고정 주소 교체, 다르면 `needs_new_code` + 회수 안내.
  - `unenroll(robot_id, principal)`: `roster.remove` 검사 통과 → `logout` → 행 삭제. 불통이면 `pending_logout`(암호문 유지). 고정 주소가 다시 발견되고 그 이름이 다른 주소에 없을 때 `logout`을 **한 번**만 부른다(`system/info` 사전 읽기 없음). 성공 시 삭제, 실패 시 행과 수동 회수 안내를 남기고 더 부르지 않는다.
  - httpx: `trust_env=False`, `follow_redirects=False`, 연결 3 s·전체 10 s.
  - 오류 분류: `bad_format`, `code_rejected`, `code_burned`, `rate_limited(retry_after)`, `lan_forbidden`, `code_consumed(reason)`(`role_too_low`·`admin_code_refused`·`wrong_robot`·`robot_id_conflict`·`store_failed`), `unreachable`, `store_unavailable`.
- `src/site/fleet/fleet/server/discovery.py`: `snapshot`이 등록부를 받아 `enrolled` 상태를 낸다. 등록 로봇 매칭은 이름 기준, 주소 차이는 등록부 상태로 따로 보낸다.
- `src/site/fleet/fleet/server/app.py` 라우트(쓰기는 `require_named_operator`, 읽기는 `require_viewer`, 403 문구는 라우트별):
  - `GET /api/fleet/enrollment/robots` — 등록부(원문 없음).
  - `POST /api/fleet/enrollment/robots` `{discovery_name | address, code}`.
  - `POST /api/fleet/enrollment/robots/{robot_id}/move-address`.
  - `DELETE /api/fleet/enrollment/robots/{robot_id}`.

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/test_enrollment_service.py`(`httpx.MockTransport`):
  - `pair-site` 모양 응답과 `pair-physical` 모양 응답(`purpose` 무시) 모두 등록, 후자는 7일 한계 표시.
  - 관리자·viewer 역할 → `logout` 호출 + `code_consumed`.
  - 401·401 burned·429(`Retry-After`)·403 → 각 분류, 원문 비노출, `pair` 호출 정확히 1회.
  - 형식 오류 → CORE 호출 0회. 수동 주소 `.local`·공인 IP → CORE 호출 0회.
  - 결속: `hostname` ≠ 브리지 `hostname` 또는 ≠ TXT `name` → `wrong_robot` + `logout`. avahi 인스턴스 문자열이 달라도 통과. Avahi가 `<이름>-2.local`로 바꾼 행이면 `wrong_robot` 도움말에 `-2` 안내 줄.
  - **주소 바뀜: 같은 이름이 새 IP로 나오면 `address_changed`, 새 주소로의 요청 0건, 고정 주소로는 정지 요청만**(MockTransport 요청 기록 검사: 경로가 정지 계열이 아닌 `Authorization` 요청 0건). **`address_changed` 중 `estop_all`이 고정 주소에 닿음.** `move_address` 뒤에만 새 주소로 요청, 결속 불일치면 `needs_new_code`.
  - **충돌 우선:** 같은 이름이 고정 주소와 다른 주소에 동시에 보이면 `conflict`(not `address_changed`), 정지 규칙 동일.
  - **경보·교통:** 진행 중 목표가 있는 로봇이 `address_changed`가 되면 경보 항목이 스냅샷에 있고, 그 점유 경로와 겹치는 다른 로봇의 목표가 보류(`_queued`)되며 겹치지 않는 목표는 하달된다. 대형 구성원이면 정지 요청 후 대형 해제.
  - `pending_logout`: 재발견 때 `logout` 정확히 1회, 이름이 다른 주소에도 보이면 0회, `system/info` 호출 0회.
  - 해제: `logout` 호출. 불통 → `pending_logout`, 복귀 후 재시도로 삭제. 진행 task가 있으면 409.
  - 만료 경고 시점이 로봇 시계 오프셋(±1일)에 흔들리지 않음.
- 새 `src/site/fleet/test/test_enrollment_api.py`: 단일 console 토큰 구성 403(라우트별 문구), viewer 읽기만, `device_pairing_audit`에 principal·`device_kind='robot'`, 응답·로그에 원문 없음.
- `src/site/fleet/test/test_discovery.py`·`test_discovery_api.py`: `enrolled` 상태, 충돌 행 등록 불가 플래그.
- 새 `test/test_fleet_robot_enrollment_contract.py`(저장소 루트, 유일한 결합 시험): 현재 소스의 `core_api_web` 앱을 검증자 파일 픽스처로 띄우고(`src/runtime/gateway/test/test_auth_pairing.py` 방식), Fleet 등록 서비스가 ASGI 전송으로 교환→`whoami`→`system/info`→`logout`. S4 전에는 `purpose`가 무시되고 `pair-physical`이 오는 것을, S4 뒤에는 `pair-site`를 확인한다. 이 시험은 배포 이미지 증거가 아니다.

**완료 기준:** 위 시험 녹색.

## S3 — 콘솔 "기기 연결" 패널과 문서

**파일**
- `src/site/fleet/fleet/server/web/index.html`, `console.js`, `styles.css`: 발견 목록을 "기기 연결" 패널의 **로봇 등록** 구역으로 옮긴다(D-341이 먼저 착지했으면 그 패널에 구역을 더하고, 아니면 패널 틀을 만들고 **카메라 연결 요청** 구역 자리를 남긴다). 발견 행 + **등록** + "주소로 추가"(사설 IPv4[:포트]). 코드 대화상자: 정규화·형식 검사, 분류별 문구(ADR 10항, `code_consumed` 공통 문구, `wrong_robot`의 Avahi `-2.local` 안내), 429 동안 버튼 끔. `address_changed`/`conflict` 로봇의 주행 경보 배너. 로스터 행에 출처 **파일/등록**, 만료, 상태(`needs_new_code` "새 코드 필요", `address_changed` "주소 바뀜 — 확인 필요" + "새 주소로 옮기기", `pending_logout` 안내). 관리자 코드로 만료가 짧아졌으면 그 문구(ADR 2항). `discoveryLabels`에 `enrolled: "등록됨"`, `pairing_pending: "이벤트 연결 대기"`. 도움말에 ADR 12항(범위·재부팅 비용).
- `src/site/fleet/fleet/server/web/authorization.js`: 등록·해제·옮기기 버튼은 이름 있는 operator만.
- `deploy/site/README.md`: 콘솔 등록 절차, `robot_credential_key` 만들기·**DB 백업과 다른 곳에 키 백업**·키 분실 = 전부 재등록·`rekey` 절차, DHCP 예약 권장, 평문 LAN 조건(ADR 9항), 도난 시 로봇 쪽 회수, 범위 제한(LCD·`boot_code`). 옛 절차는 정적 로봇용으로 남긴다.
- `docs/reference/site-lan-discovery-profile.md`: "발견에서 연결까지"에 ROSY 로봇 등록은 D-361라는 한 줄.
- `.claude/skills/rosy-device-access/SKILL.md`: 사이트에 붙일 때는 SSH 대신 콘솔 등록이 기본이라는 한 줄.

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/web/enrollment.test.mjs`: 코드 정규화·형식 거절, 수동 주소 검사, 분류 → 문구 표, 429 타이머, viewer에게 버튼 없음, 상태별 행 문구.
- 표면 계약 시험(`test_console_palette.py` 등, D-329·D-345)이 새 패널에서도 녹색.

**완료 기준:** node·pytest 녹색. 로컬 Fleet + 가짜 CORE로 브라우저에서 등록→해제를 한 번 돌린 화면 캡처는 `X:\DevTemp`에 두고 로그에는 경로만.

**→ 여기서 벤치 D1을 할 수 있다(현 이미지).**

## S4 — CORE: 사이트 출처·수명, 장치 UID 읽기 (이미지 변경)

**파일**
- `src/contracts/foundation/core_common/config.py`: `ROSY_DEVICE_UID` → `robot.device_uid`(`ROSY_DEVICE_NAME`과 같은 불변 규칙).
- `src/contracts/foundation/core_common/identity.py`: `info()`에 `device_uid`, `device_name`(additive).
- `src/runtime/api_web/core_api_web/api/deps.py`: `TOKEN_SOURCES`(:103)와 `PAIRED_SOURCES`에 `pair-site`(`new_token_record` :199가 `manual`로 떨어뜨리지 않게).
- `src/runtime/api_web/core_api_web/api/v1/auth.py`: `PairRequest.purpose: Literal["", "site"]`. `purpose="site"`: 코드 역할 ≥ operator(아니면 403 `ROLE_TOO_LOW`), 발급 역할 `operator`, 출처 `pair-site`, 수명 `auth.pairing.site_token_days`(기본 90, 1–365로 자름, 168 h 상한은 `pair-site`에만 적용하지 않음), 관리자 등록 코드면 만료 `min(사이트 수명, 발급자 만료)`.
- `src/runtime/api_web/core_api_web/api/v1/auth.py`: 새 `GET /api/v1/auth/site-tokens`(operator 이상, `pair-site` 행만, 원문·digest 없음, `no-store`)와 `DELETE /api/v1/auth/site-tokens/{id}`(operator 이상, `pair-site`만 지움, 그 밖 id는 404, 이벤트 `auth.site_token_revoked`). 토큰 목록 쓰기는 기존 `TOKEN_WRITE_LOCK` 안.
- `deploy/robot/pinky_pro/native/rosy-config-apply.py`: 카드 `login.site_token_days` → `auth.pairing.site_token_days`.
- 로봇 대시보드: `src/hmi/dashboard/panels/system/security.js`(토큰 목록)와 `src/hmi/dashboard/settings.js`에서 출처 `pair-site`를 "사이트"로 표시. operator 세션에는 관리자 토큰 목록 대신 `auth/site-tokens` 기반 "사이트 연결" 목록과 회수 버튼(확인 대화상자)을 보인다.
- `docs/adr/D-193-login-code-and-credential-lifecycle.md`와 ADR Log D-193 행: "D-361가 개정(`pair-site` 수명, operator 회수)" 표시(이 계획 커밋에서 이미 넣었다 — S4는 착지 때 확인만).
- `docs/reference/ROSY API & Protocol Reference.md`: MINOR, 변경 이력, §5 auth·system/info. `src/runtime/api_web/core_api_web/api/app.py` description 판. D-382 스냅샷이 있으면 재생성.

**시험 (먼저 실패)**
- `src/runtime/gateway/test/test_auth_pairing.py`: `purpose=site` 발급 모양(출처가 `manual`이 아닌 `pair-site`), 관리자 부팅 코드 → operator로 낮춤, viewer 코드 403, 옛 본문(`purpose` 없음) 동작 불변, 사이트 수명 기본·자름, 브라우저 출처 168 h 상한 불변, 만료 있는 관리자가 발급한 등록 코드 → `min()`, 카드(만료 없음) 관리자 발급 → 90일, `pair-site` logout 204.
- 새 `src/runtime/gateway/test/test_auth_site_tokens.py`: viewer 403, operator 목록에 `pair-site`만·원문/digest 없음·`no-store`, operator가 `pair-site` 삭제 → 그 토큰 401 + 이벤트, 카드·수동·`pair-physical` id 삭제 시도 404이고 그 토큰은 살아 있음, administrator도 같은 경로 사용 가능.
- 대시보드 시험(`src/hmi/dashboard` 기존 node 시험 위치를 따른다): operator 역할에서 사이트 연결 목록·회수 버튼이 보이고 관리자 토큰 목록은 안 보임, viewer에게 둘 다 없음.
- `src/runtime/gateway/test/test_runtime_config.py`: `ROSY_DEVICE_UID` 반영. `src/runtime/gateway/test/test_api.py`: `system/info` 새 필드. `src/runtime/gateway/test/test_fleet_agent.py`: HELLO에 `device_uid`.
- `test_protocol_version_alignment.py` 녹색. 저장소 루트 결합 시험이 `pair-site`로 녹색.

**완료 기준:** gateway 스위트 녹색(`src/runtime/gateway/AGENTS.md`의 두 줄 명령). 이미지 변경 필요 기록. **→ 새 이미지가 있으면 벤치 D2.**

## S6 — FleetAgent 이벤트 연결 (조건부)

**여는 조건(ADR 7항, 모두):** D-382 S2의 Hub 세션-로봇 결속·상수 시간 비교가 `main`에 있다. Fleet에 로봇이 닿는 `wss://` 주소와 맞는 SAN의 사이트 인증서가 있다. S4가 착지했다. 안 되면 시작하지 않고 `docs/logs.md`에 HOLD로 적는다.

**파일**
- 새 `src/runtime/api_web/core_api_web/api/v1/fleet_link.py`: `PUT`(`pair-site` 토큰 **+ 새 로봇 화면 코드**, 코드는 D-193 규칙으로 소모, 코드 역할 operator 이상 — LCD 코드와 관리자 등록 코드 모두 받음, viewer 코드 403), `DELETE`(`pair-site` 토큰만), `GET`(viewer 이상, 설정 여부·hub 호스트만; 인증 없는 조회 없음). `hub_url`은 `wss://`만, CA PEM 크기·형식 검사, `pairing_token` 43자 이상. `patch_local_config({"fleet": ...})`, CA는 오버레이 옆 0600 파일. FleetAgent `stop()`→`start()`.
- `src/runtime/services/core_features/fleet_agent/agent.py`: `reload(config)`, 오버레이 위치 CA 경로 수용.
- `src/runtime/api_web/core_api_web/api/app.py`: 라우터 등록. API Ref MINOR.
- `src/site/fleet/fleet/server/enrollment.py`: "이벤트 연결"(새 코드 입력) → 짝 토큰 생성 → 봉인(슬롯 `agent`) → `roster`로 Hub 토큰 → CORE `PUT /fleet/link`. 해제는 `DELETE` 먼저.
- 사이트 설정: `ROSY_SITE_ROBOT_HUB_URL`(`wss://<site>.local:8443/ws/robots`).

**시험 (먼저 실패)**
- 새 `src/runtime/gateway/test/test_fleet_link.py`: 출처별 403, 코드 없는 `PUT` 거절·틀린 코드 시도 계수, viewer 코드 403·관리자 등록 코드 수락, `ws://` 거절, 오버레이 기록, 에이전트 재시작 호출, `GET` 인증 필요·비밀 없음.
- `src/site/fleet/test/test_console_hub_integration.py`: 합성 CORE Agent가 새 짝 토큰으로 HELLO → `verified_online`, 다른 `robot_id`의 EVENT 거절, 해제 뒤 HELLO 거절.

**완료 기준:** 녹색. **→ 벤치 D3.**

## 벤치 절차 (DEVICE, 사람 입회)

대상 `rosy-pinky-8kcn`, 같은 Wi-Fi의 벤치 PC. 이동·정지 명령을 보내지 않는다. SSH를 쓰지 않는다. 결과는 `docs/validation/2026-MM-DD-fleet-robot-code-enrollment.md`에 쓰고 코드·토큰은 `***`로 가린다.

**준비:** 벤치 Fleet `console`을 `--tasks-db`, `--users-file`(이름 있는 operator 1명), `--robot-credential-key-file`(`X:\DevTemp` 아래 base64 키)로, 로봇에서 닿는 주소로 띄운다(`fleet/cli.py` 루프백 밖 규칙). 발견은 WSL Ubuntu의 `mdns-bridge.py` 또는 "주소로 추가"(`192.168.1.202:8080`) — 어느 쪽인지 기록한다. 기존 `robots.yaml`에 이 로봇이 있으면 빼고 띄운다.

**로봇 쪽 토큰 확인 방법(D1 5·7단계) — 둘 중 하나를 정하고 기록한다.**
- **방법 A(권장, 카드 관리자 자격이 있을 때):** 벤치 PC DPAPI 저장소의 카드 관리자 토큰으로 **읽기 전용** `GET /api/v1/system/tokens`만 부른다. 이름표 `site:<fleet_name>`인 행의 id·역할·출처·만료를 기록하고, 해제 뒤 그 id가 없음을 기록한다. 이 자격으로는 다른 요청을 보내지 않는다.
- **방법 B(카드 관리자 자격이 없을 때):** 등록 직후 하네스가 벤치 키로 등록부를 열어 토큰을 **메모리에만** 꺼내고 `GET /api/v1/auth/whoami` → 200(역할·출처·만료, id 기록), 해제 뒤 같은 토큰으로 `whoami` → 401. 토큰은 파일·출력에 남기지 않는다.

**D1 (S1–S3, 현 이미지 `2026.09.27-010`):**
1. 사람이 로봇 전원을 다시 넣는다. LCD에 코드가 뜬 시각.
2. 콘솔 "기기 연결 → 로봇 등록"에 `rosy-pinky-8kcn` 행이 **등록 대기**로 보인다(또는 주소로 추가).
3. 형식은 맞지만 틀린 코드 1회 → 401 문구. LCD 코드는 살아 있다.
4. 올바른 코드 → 로스터에 온라인, 출처 **등록**, "7일 뒤 새 코드" 표시, `robot/state` 수신 시각과 로봇 `ts` 차이.
5. 로봇 쪽 확인(방법 A 또는 B): 역할 operator, 출처 `pair-physical`(현 이미지), 만료.
6. Fleet 재시작 → 코드 입력 없이 다시 온라인.
7. **등록 해제** → 로스터에서 빠짐, 로봇 쪽 확인(방법 A: 행 없음 / 방법 B: 401). `device_pairing_audit` 행 수.
8. "SSH를 쓰지 않았다", 운용자 동작 수, 쓴 확인 방법을 적는다.

**D2 (S4 이미지):** 출처 `pair-site`, 만료 ≈ 90일, `system/info.device_uid` 결속, 로봇 대시보드 operator 세션에서 사이트 연결이 보이고(회수는 해제 회차에서만). 공유기에서 로봇 DHCP 주소를 바꿨을 때 `address_changed`로 멈춘다. **Bearer 부재 증거 수집:** 벤치 Fleet을 `httpx` 로거 INFO로 띄워 요청 줄(메서드·URL·상태, 헤더 없음)을 `X:\DevTemp` 로그로 받고, 주소 변경 시각 이후 새 주소로의 요청 0건·고정 주소로는 정지 계열 경로만임을 기록한다. 가능하면 벤치 PC에서 `tcp port 8080` 패킷 캡처를 함께 떠 새 주소 대상 `Authorization` 출현 수(0)만 기록하고 캡처 파일은 저장소에 넣지 않는다. 이 회차에서 정지 명령을 실제로 보내지는 않는다. "새 주소로 옮기기" 뒤 온라인 복귀.

**D3 (S6):** 새 코드(재부팅 또는 관리자 코드 — ADR 12항 (d))로 이벤트 연결 → 발견 상태 **확인됨**, CORE 재시작 없이 이벤트가 Fleet SQLite에 쌓이고 Fleet 재시작 뒤 남음.

## 완료 판정

- S1–S3 녹색 + D1 기록 = D-361를 Accepted로 올릴 **후보**(현 이미지 범위, 7일 한계 명시). ADR 개정 회차에서 사용자가 판단한다.
- S4 + D2가 있어야 "90일 동안 손대지 않는 등록"을 주장한다.
- S6 + D3 전에는 이벤트 이력을 등록 경로로 주장하지 않는다.
