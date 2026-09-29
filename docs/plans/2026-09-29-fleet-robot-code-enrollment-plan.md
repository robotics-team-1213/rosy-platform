# 사이트 콘솔 로봇 화면 코드 등록 계획 (D-352)

**ADR:** [D-352](../adr/D-352-site-console-enrolls-robot-by-screen-code.md) (Proposed)
**작성:** 2026-09-29. 기준 커밋 `main` 86ba6e4c.
**목표:** 운용자가 로봇 전원을 넣고, 콘솔에서 **등록**을 누르고, 로봇 화면의 8자를 치면 그 로봇이 사이트 로스터에 들어온다. SSH·`robots.yaml` 편집·재시작이 없다. 순서는 **현 로봇 이미지로 먼저 쓸 수 있는 Fleet 쪽(S1–S3) → CORE 이미지 변경(S4) → 갱신(S5) → 이벤트 연결(S6, 조건부)** 이다.

## 범위 밖

- 로봇 CORE TLS(D-352 9항 조건만), 이미지 재빌드·서명·배포 시점.
- 천장 카메라 연결 승인(D-341). S3의 "기기 등록" 패널은 카메라 구역 자리만 남기고 D-341 구현이 채운다.
- D-351 계약 스냅샷·적합성 탐침 자체. 단, S4가 API를 바꿀 때 스냅샷이 `main`에 있으면 같은 변경에서 재생성한다.
- 이동·정지 명령의 실물 시험.

## 규칙

- 단계마다 먼저 실패하는 시험을 쓰고, 고치고, 단계 끝에 커밋한다. 커밋 메시지는 `Co-Authored-By` 줄로 끝난다.
- Windows에서는 `python`을 쓴다. pytest는 `--basetemp`를 `X:\DevTemp\...` 아래로 준다.
- 코드·토큰 원문은 시험 픽스처의 가짜 값만 쓴다. 로그·감사·응답·예외 메시지에 원문이 없음을 시험으로 고정한다(`caplog`·응답 본문 검색).
- Fleet은 CORE 코드를 import하지 않는다(D-18, D-59). 등록 서비스 시험의 "가짜 CORE"는 `httpx.MockTransport`다. 실제 CORE와의 결합 시험은 S2 끝의 한 파일만 `core_api_web.create_app`을 띄운다(`src/runtime/gateway/test`의 conftest 규칙을 따른다).
- 모듈 기록: 바꾼 모듈의 `logs.md`에 추가하고, gate가 바뀌면 `progress.md`를 고치고, `python tools/harness/rosy_harness.py generate` 후 `lint`.
- 실물 로봇 작업은 "벤치 절차"의 명시적 회차에만 한다. SSH 금지.

## S1 — Fleet 등록부와 동적 로스터

**왜:** 로스터가 기동 때 고정이고(`FleetConsole`·`SiteHub` 생성자), `robots.yaml`은 빈 목록을 거절한다. 자격을 둘 Fleet 소유 저장소가 없다.

**파일**
- 새 `src/site/fleet/fleet/server/enrollment_store.py`: SQLite 표 `robot_enrollments`, `robot_enrollment_audit`(D-352 4항 열). `seal(token, robot_id, token_id)`/`open_(...)` — `cryptography.hazmat.primitives.ciphers.aead.AESGCM`, 행마다 새 12 byte nonce, AAD `robot_id‖token_id`. 키 파일은 정확히 32 byte(원시 또는 base64 44자)만 받는다. 감사 보존 상한 10,000행. `sqlite_policy.py`의 연결 규칙을 재사용한다.
- `src/site/fleet/fleet/swarm/robots.py`: `load_robots(path, allow_empty=False)` — 등록부가 켜진 기동만 `allow_empty=True`.
- `src/site/fleet/fleet/server/console.py`: `add_robot(endpoint, client)`, `remove_robot(robot_id)`, `replace_address(robot_id, base_url)`. `_rest_tokens`·`_registered_endpoints`·`_order`를 메서드 뒤로 옮기고, 정적 항목과 등록 항목의 출처(`file`/`enrolled`)를 기억한다. 제거 때 그 로봇의 `_goals`·`_claims`·`_queued`·`_yielding`을 정리하고 대형 구성원이면 거절(409)한다.
- `src/site/fleet/fleet/hub/hub.py`: 짝 토큰 표를 `set_pairing_token(robot_id, token)`/`drop(robot_id)`로 바꿀 수 있게 한다(S6이 쓴다. 이 단계는 인터페이스와 시험만).
- `src/site/fleet/fleet/server/app.py`: `create_app(..., enrollment_store=None)`. 자격 분리 검사(`uses_rest_token` 등)가 등록부 토큰도 보게 한다 — 복호는 기동 때 한 번, 메모리에만.
- `src/site/fleet/fleet/cli.py`: `console --robot-credential-key-file PATH`(`--tasks-db`가 있어야 함). 키가 있으면 `--robots` 선택 사항.
- `deploy/site/requirements-fleet.txt`: `cryptography==<고정판>`. `deploy/site/compose.yaml`: secret `robot_credential_key`, fleet 서비스에 마운트. 새 `deploy/site/robot-credential-key.template.txt`(형식만).
- `src/site/fleet/package.xml`: `python3-cryptography` exec_depend.

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/test_enrollment_store.py`: 봉인·개봉 왕복, 다른 행의 AAD로 열면 실패, 키가 다르면 실패, DB 파일 바이트에 토큰 원문이 없음, 짧은·긴 키 거절, 감사 상한.
- `src/site/fleet/test/test_robots.py`: `allow_empty` 경로, 기존 거절 유지.
- `src/site/fleet/test/test_server_console.py`: 추가 → 스냅샷에 보임, 제거 → 목표·점유 정리, 대형 구성원 제거 409, 정적 `robot_id` 중복 추가 거절.
- `src/site/fleet/test/test_hub.py`: 동적 짝 토큰 추가·삭제 뒤 HELLO 수락·거절.
- `src/site/fleet/test/test_server_app.py`: `robot_credential_key`가 다른 비밀과 같으면 기동 거절. `test_cli.py`: 키 없이 `--robots` 생략하면 거절.

**완료 기준:** 위 시험과 Fleet 스위트 녹색. `robots.yaml`만 쓰는 기존 구성의 동작이 그대로다.

## S2 — 등록 서비스와 API (현 이미지 호환)

**왜:** D-352 1–3·6항. 현 벤치 이미지(`pair-physical`, `device_uid` 없음)로 끝까지 되게 한다.

**파일**
- 새 `src/site/fleet/fleet/server/enrollment.py`: `EnrollmentService`.
  - `enroll(candidate, code, principal)`: 코드 정규화·형식 검사(알파벳 `23456789ABCDEFGHJKMNPQRSTUVWXYZ`, 8자) → `POST /api/v1/auth/pair` `{code, label: "site:<fleet_name>", purpose: "site"}` → 역할 검사(operator만; 아니면 `logout` 후 거절) → `whoami`·`system/info` 읽기 → 결속 검사(hostname == 발견 인스턴스·`.local`, 정적·등록 `robot_id` 충돌) → 봉인 저장 → `console.add_robot` → 감사. 실패 경로는 받은 토큰을 `logout` 후 버린다. 자동 재시도 없음.
  - `unenroll(robot_id, principal)`, `replace(...)`, `on_discovery(scan)`: 같은 이름의 새 주소 → `system/info` 결속 확인 → `replace_address` 또는 격리.
  - httpx 클라이언트: `trust_env=False`, `follow_redirects=False`, 연결 3 s·전체 10 s.
  - 오류 분류: `bad_format`, `code_rejected`, `code_burned`, `rate_limited(retry_after)`, `lan_forbidden`, `role_too_low`, `admin_code_refused`, `unreachable`, `wrong_robot`, `robot_id_conflict`, `store_unavailable`.
- `src/site/fleet/fleet/server/discovery.py`: `snapshot`이 등록부를 받아 새 상태 `enrolled`를 낸다. 등록 로봇의 주소 매칭은 이름 기준.
- `src/site/fleet/fleet/server/app.py`: 라우트(모두 `require_named_operator`, 읽기는 `require_viewer`):
  - `GET /api/fleet/enrollment/robots` — 등록부(원문 없음, 만료·출처·상태).
  - `POST /api/fleet/enrollment/robots` `{discovery_name | address, code, replace?: bool}`.
  - `DELETE /api/fleet/enrollment/robots/{robot_id}`.
  - `POST /api/fleet/enrollment/robots/{robot_id}/release-quarantine` — 결속 재확인 후만.
  - 403 문구는 라우트별로 매개변수화한다("mission admission" 재사용 금지 — D-341 5항과 같은 지적).

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/test_enrollment_service.py` (`httpx.MockTransport`로 가짜 CORE):
  - 성공(새 이미지 모양 `pair-site`)과 옛 이미지 모양(`pair-physical`, `purpose` 무시) 모두 등록, 후자는 `renewable=False`.
  - 관리자 코드 → `logout` 호출 후 거절, viewer 코드 → 같음.
  - 401·401 burned·429(`Retry-After`)·403 → 각 분류, 코드 원문 비노출, `pair` 호출 1회(재시도 없음).
  - 형식 오류 → CORE 호출 0회.
  - hostname 불일치 → `wrong_robot` + `logout`. 정적 `robot_id` 충돌 → 409 + `logout`.
  - 주소 이동: 같은 결속이면 이동, 다르면 격리하고 그 주소로 Bearer를 보내지 않음(요청 헤더 검사).
  - 해제: `logout` 호출, 로봇 불통이면 로컬 삭제 + 경고.
- 새 `src/site/fleet/test/test_enrollment_api.py`: 단일 console 토큰 구성 403, viewer 읽기만, 감사 행에 principal, 응답·로그에 토큰 원문 없음.
- `src/site/fleet/test/test_discovery.py`·`test_discovery_api.py`: `enrolled` 상태, 충돌 행은 등록 불가 플래그.
- 새 `src/site/fleet/test/test_enrollment_core_contract.py`(유일한 결합 시험): 실제 `core_api_web` 앱을 host pytest로 띄우고 검증자 파일 픽스처로 코드를 만든 뒤, Fleet 등록 서비스가 ASGI 전송으로 교환→`whoami`→`system/info`→`logout`까지 도는지. `src/runtime/gateway/test/test_auth_pairing.py`의 픽스처 방식을 재사용한다.

**완료 기준:** 위 시험 녹색. 결합 시험이 **현재 CORE 코드**(S4 전)로 녹색 — 옛 이미지 경로의 증거다.

## S3 — 콘솔 "기기 등록" 패널과 문서

**왜:** D-352 1·8·10·11항의 사람 쪽.

**파일**
- `src/site/fleet/fleet/server/web/index.html`, `console.js`, `styles.css`: 발견 목록을 "기기 등록" 패널로 옮긴다. 구역 "로봇"(발견 행 + **등록** 버튼 + "주소로 추가"), 구역 "카메라"(D-341 자리, 이번에는 비어 있음 문구만). 코드 입력 대화상자: 정규화·형식 검사, 서버 분류별 문구(D-352 10항), 429 동안 버튼 끔. 로스터 행에 출처 **파일/등록**, 만료, "새 코드 필요" 경고. `discoveryLabels`에 `enrolled: "등록됨"`, `pairing_pending: "이벤트 연결 대기"`.
- `src/site/fleet/fleet/server/web/authorization.js`: 등록 버튼은 이름 있는 operator만.
- `deploy/site/README.md`: "Same-LAN ROSY discovery"와 "Advertise and locate" 절에 콘솔 등록 절차, `robot_credential_key` 준비, 평문 LAN 조건(D-352 9항), 옛 절차는 정적 로봇용으로 남긴다는 문장.
- `docs/reference/site-lan-discovery-profile.md`: "발견에서 연결까지"에 ROSY 로봇 등록은 D-352라는 한 줄.
- `.claude/skills/rosy-device-access/SKILL.md`: 사이트에 붙일 때는 SSH 대신 콘솔 등록이 기본이라는 한 줄.

**시험 (먼저 실패)**
- 새 `src/site/fleet/test/web/enrollment.test.mjs`: 코드 정규화·형식 거절, 분류 → 문구 표, 429 타이머, viewer에게 버튼 없음.
- `src/site/fleet/test/test_console_palette.py`·표면 계약 시험이 새 패널에서도 녹색(D-329·D-345 규칙).

**완료 기준:** node·pytest 녹색. 로컬 Fleet + 가짜 CORE로 브라우저에서 등록→해제를 한 번 돌린 화면 캡처(`X:\DevTemp`)를 로그에 경로로만 남긴다.

**→ 여기서 벤치 D1을 할 수 있다(현 이미지).**

## S4 — CORE: 사이트 출처, 갱신, 장치 UID 읽기 (이미지 변경)

**왜:** D-352 2·3·5항의 CORE 쪽. 7일 만료를 재부팅 없이 넘기고, 결속에 `device_uid`를 쓴다.

**파일**
- `src/contracts/foundation/core_common/config.py`: `ROSY_DEVICE_UID`를 `robot.device_uid`로 읽는다(`ROSY_DEVICE_NAME`과 같은 불변 규칙).
- `src/contracts/foundation/core_common/identity.py`: `info()`에 `device_uid`, `device_name`(additive).
- `src/runtime/api_web/core_api_web/api/deps.py`: `PAIRED_SOURCES`에 `pair-site`. 레코드 필드 `lineage_id`, `lineage_expires_at`, `superseded_by`, `first_used_at`. 인증 성공 때 `first_used_at`을 한 번 쓰고, 그때 부모 레코드를 지운다. 부모가 자식 사용 뒤 나타나면 계보 회수 + `auth.site_token_reuse`.
- `src/runtime/api_web/core_api_web/api/v1/auth.py`: `PairRequest.purpose: Literal["", "site"]`. `purpose="site"`: 코드 역할 ≥ operator 요구(아니면 403 `ROLE_TOO_LOW`), 발급 역할 `operator`, 출처 `pair-site`, 계보 시작. 새 `POST /auth/renew`(`pair-site`만, 안 쓰인 자식 교체 규칙, 계보 상한 → 403 `RENEWAL_LIMIT`, 응답 `no-store`). `whoami`에 `lineage_expires_at`.
- 설정: `auth.pairing.site_lineage_days`(기본 90, 1–365로 자름). `deploy/robot/pinky_pro/native/rosy-config-apply.py`가 카드 `login.site_lineage_days`를 넘길지 여기서 정하고 시험한다.
- `docs/reference/ROSY API & Protocol Reference.md`: MINOR 올림, 변경 이력, §5 auth·system/info. D-351 스냅샷이 `main`에 있으면 재생성. `src/runtime/api_web/core_api_web/api/app.py` description 판.
- 로봇 대시보드 토큰 목록(`src/runtime/api_web/core_api_web/web/` 해당 파일): 출처 `pair-site`를 "사이트"로 표시.

**시험 (먼저 실패)**
- `src/runtime/gateway/test/test_auth_pairing.py`: `purpose=site` 발급 모양, 관리자 코드 → operator로 낮춤, viewer 코드 403, 옛 본문(없는 `purpose`) 동작 불변, `pair-site` logout 204.
- 새 `src/runtime/gateway/test/test_auth_site_renew.py`: 회전, 자식 첫 사용 뒤 부모 401, 안 쓰인 자식 교체, 재사용 감지로 계보 전체 401 + 이벤트, 계보 상한 403, `pair-physical`·카드 토큰 renew 403, 응답 `no-store`, 만료 없는 토큰 생성 불가 유지.
- `src/runtime/gateway/test/test_runtime_config.py`: `ROSY_DEVICE_UID` 반영. `src/runtime/gateway/test/test_api.py`: `system/info`의 새 필드. `test_fleet_agent.py`: HELLO에 `device_uid`가 실림.
- `test_protocol_version_alignment.py` 녹색.

**완료 기준:** gateway 스위트 녹색(두 줄 명령, `src/runtime/gateway/AGENTS.md`). S2 결합 시험이 새 경로(`pair-site`)로도 녹색. 이미지 변경이 필요하다는 기록.

## S5 — Fleet 갱신 루프와 수명 표시

**왜:** D-352 5항의 Fleet 쪽.

**파일**
- `src/site/fleet/fleet/server/enrollment.py`: `renew_due(now)` — 남은 수명 < 절반 또는 < 72 h. 갱신 응답을 **먼저 봉인 저장**(`pending_token`)하고, 새 토큰으로 `whoami` 성공 뒤 활성으로 바꾼다. 실패 1 h 상한 백오프. 401 → `credential_lost`/`revoked_by_robot` 구분(재사용 이벤트는 로봇 이벤트로만 알 수 있으므로 문구는 둘 다 "새 코드로 다시 등록"). 옛 이미지 행은 갱신하지 않고 72 h 전 경고. `lineage_expires_at` 14일 전 경고.
- `src/site/fleet/fleet/server/app.py`: 기동 때 백그라운드 작업 등록(기존 수명 관리 패턴을 따른다).
- `console.js`: 경고 배지.

**시험 (먼저 실패)**
- `src/site/fleet/test/test_enrollment_service.py`에 추가: 갱신 시점 판단(가짜 시계), 저장 전 중단 뒤 재기동 → 옛 토큰으로 다시 갱신 성공, 401 → 상태 전이, 옛 이미지 행 비갱신, 경고 시점.
- S2 결합 시험에 실제 CORE로 renew 왕복 한 건.

**완료 기준:** 녹색. **→ 새 이미지가 있으면 벤치 D2.**

## S6 — FleetAgent 이벤트 연결 (조건부)

**여는 조건(D-352 7항, 모두):** D-351 S2의 Hub 세션-로봇 결속·상수 시간 비교가 `main`에 있다. Fleet에 로봇이 닿는 `wss://` 주소와 맞는 SAN의 사이트 인증서가 있다. S4가 착지했다. 조건이 안 되면 이 단계는 시작하지 않고 `docs/logs.md`에 HOLD로 적는다.

**파일**
- 새 `src/runtime/api_web/core_api_web/api/v1/fleet_link.py`: `GET`(공개, 설정 여부·hub 호스트만), `PUT`·`DELETE`(`pair-site` 출처만). `hub_url`은 `wss://`만, CA PEM 크기·형식 검사, `pairing_token` 43자 이상. `patch_local_config({"fleet": ...})`로 쓰고 CA는 CORE 쓰기 가능한 오버레이 옆 파일(0600)로 둔다. FleetAgent `stop()`→`start()`.
- `src/runtime/services/core_features/fleet_agent/agent.py`: 설정 재적용 경로(`reload(config)`), CA 파일 경로를 오버레이 위치에서도 받음.
- `src/runtime/api_web/core_api_web/api/app.py`: 라우터 등록. API Ref MINOR.
- `src/site/fleet/fleet/server/enrollment.py`: 등록 성공 뒤(또는 기존 등록에 "이벤트 연결" 동작) 짝 토큰 생성 → 봉인 저장 → Hub `set_pairing_token` → CORE `PUT /fleet/link`. 해제는 `DELETE` 먼저.
- 사이트 설정: `ROSY_SITE_ROBOT_HUB_URL`(로봇에서 닿는 `wss://<site>.local:8443/ws/robots`).

**시험 (먼저 실패)**
- 새 `src/runtime/gateway/test/test_fleet_link.py`: 출처별 403, `ws://` 거절, 오버레이 기록, 에이전트 재시작 호출, `GET`에 비밀 없음.
- `src/site/fleet/test/test_console_hub_integration.py`에 추가: 합성 CORE Agent가 새 짝 토큰으로 HELLO → `verified_online`, 다른 `robot_id`로 보낸 EVENT 거절(D-351 S2 시험과 같이), 해제 뒤 HELLO 거절.

**완료 기준:** 녹색. **→ 벤치 D3.**

## 벤치 절차 (DEVICE, 사람 입회)

대상 `rosy-pinky-8kcn`, 같은 Wi-Fi의 벤치 PC. 이동·정지 명령을 보내지 않는다. SSH를 쓰지 않는다. 결과는 `docs/validation/2026-MM-DD-fleet-robot-code-enrollment.md`에 쓰고 코드·토큰은 `***`로 가린다.

**준비:** 벤치 Fleet `console`을 `--tasks-db`, `--users-file`(이름 있는 operator 1명), `--robot-credential-key-file`(`X:\DevTemp` 아래 32 byte 키)로, 로봇에서 닿는 주소로 띄운다(`fleet/cli.py` 루프백 밖 규칙). 발견은 WSL Ubuntu의 `mdns-bridge.py` 또는 콘솔 "주소로 추가"(`http://192.168.1.202:8080`)로 한다 — 어느 쪽을 썼는지 기록한다. 기존 `robots.yaml`에 이 로봇이 있으면 빼고 띄운다.

**D1 (S1–S3, 현 이미지 `2026.09.27-010`):**
1. 사람이 로봇 전원을 다시 넣는다. LCD에 코드가 뜬 시각.
2. 콘솔 "기기 등록"에 `rosy-pinky-8kcn` 행이 **등록 대기**로 보인다(또는 주소로 추가).
3. 형식은 맞지만 틀린 코드 1회 → 401 문구. 로봇 코드는 살아 있다(LCD 유지).
4. 올바른 코드 → 로스터에 온라인, 출처 **등록**, "갱신 불가 이미지" 표시, `robot/state` 수신 시각과 로봇 `ts` 차이.
5. 로봇 대시보드(사람이 휴대폰으로, 별도 코드 또는 기존 세션) 토큰 목록에 이름표 `site:<fleet_name>`, operator, 만료가 보인다.
6. Fleet을 재시작 → 코드 입력 없이 다시 온라인.
7. **등록 해제** → 로봇 토큰 목록에서 사라짐, 로스터에서 빠짐. 감사 표 행 수.
8. "SSH를 쓰지 않았다", 운용자 동작 수(전원·클릭·입력)를 적는다.

**D2 (S4 이미지 + S5):** 출처 `pair-site`, `system/info.device_uid` 결속, 카드 설정으로 짧게 둔 수명에서 무인 갱신 1회 이상과 옛 토큰 401, 공유기에서 로봇 DHCP 주소를 바꾼 뒤 이름 추종(옛/새 IP, 걸린 시간).

**D3 (S6):** 같은 등록으로 이벤트 연결 → 발견 상태 **확인됨**, CORE 재시작 없이 이벤트가 Fleet SQLite에 쌓이고 Fleet 재시작 뒤 남음.

## 완료 판정

- S1–S3 녹색 + D1 기록 = D-352를 Accepted로 올릴 **후보**(현 이미지 범위). ADR 개정 회차에서 사용자가 판단한다.
- S4–S5 + D2가 있어야 "7일 넘게 손대지 않는 등록"을 주장한다.
- S6 + D3 전에는 이벤트 이력을 등록 경로로 주장하지 않는다.
