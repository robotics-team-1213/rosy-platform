## D-382 로봇 ↔ 사이트 관제 통신은 계약 스냅샷 하나로 판정하고, 실물 확인은 읽기 전용 적합성 탐침으로 시작한다

**Status:** Proposed (2026-09-29, 판정 기준·증거 등급·탐침 경계만; 2026-10-01 D-351에서 재부여·교차 세션 검토 반영 — 로봇 판 갱신, 발견 상태, 벤치 기준선). 새 경로·새 envelope·새 인증 방식을 만들지 않는다. 로봇 이미지 교체, 토큰 발급, 이동 명령은 이 ADR의 범위가 아니다.

### Context

관제(Fleet console)는 로봇이 보내는 데이터를 받고, 두 쪽은 ROSY 내부 계약(ROSY-API-REF-001)으로 통신한다. 계약은 이미 정해져 있다. 이번 회차는 그 계약이 실제 로봇에서 그대로 돌아가는지를 처음으로 대조했다.

**통신 경로는 셋이다.**

| 경로 | 방향 | 인증 | 스키마 원천 | 로봇 구현 | Fleet 구현 | 시험 |
|---|---|---|---|---|---|---|
| CORE REST `/api/v1/*` (state, map, navigation, safety, swarm, events) | Fleet → 로봇 (pull·명령) | CORE 운영자 Bearer 토큰(`robots.yaml` `token`) | API Ref §5, `core_api_web/api/v1/*.py` | `src/runtime/api_web/core_api_web/api/app.py:140-163` | `src/site/fleet/fleet/swarm/transport.py:145-213` | `src/runtime/gateway/test/test_api.py`, `src/site/fleet/test/test_transport.py` |
| CORE WS `/ws/state`·`/ws/events`·`/ws/swarm/*` | 로봇 → Fleet (Fleet이 연결) | 같은 토큰, 쿼리 전달(API Ref §6) | `core_api_web/api/ws.py:84-257` | 같음 | `swarm/robots.py:122` `ws_url`, `transport.py:222-228` | `test_transport.py` |
| FleetAgent `/ws/robots` (HELLO/WELCOME/HEARTBEAT/EVENT, PRT-001~005) | 로봇 → Fleet (로봇이 연결) | 로봇별 `fleet_pairing_token`(REST 토큰과 달라야 함, `robots.py:46`) | `core_common/protocol/schemas.py:394-432`, API Ref §7 | `src/runtime/services/core_features/fleet_agent/agent.py:34-49` | `src/site/fleet/fleet/hub/server.py:28`, `hub/hub.py:75-135`, `server/core_event_store.py` | `test_fleet_agent.py`, `test_fleet_agent_mdns.py`, `test_hub.py`, `test_hub_server.py`, `test_core_event_store.py` |
| mDNS `_rosy._tcp` TXT | 로봇 → LAN | 없음(공개 정보만) | `docs/reference/site-lan-discovery-profile.md:16-26` | `deploy/robot/pinky_pro/native/rosy-boot-status.py` | `deploy/site/mdns-bridge.py` | discovery 계약 시험 |

관제 화면의 로봇 목록·상태·지도는 REST pull(`server/console.py:166-169`, `:218`)에서 나오고, 이벤트 이력은 FleetAgent EVENT를 SQLite에 쌓은 것(`core_event_store.py:42-93`)에서 나온다. 즉 **이벤트 이력은 로봇이 Fleet으로 먼저 연결해야 생긴다.** 기본 설정은 `fleet.enabled: false`이고 토큰이 없으면 Agent가 시작하지 않는다(`agent.py:44-46`).

증거 등급은 Fleet `DEVICE: PARKED`, gateway `DEVICE: HOLD`(`src/site/fleet/progress.md`, `src/runtime/gateway/progress.md`)다. 가장 높은 기록은 합성 CORE Agent가 사이트 후보의 Hub에 TLS로 짝지어 PRT 이벤트를 보낸 LOCAL 증거(`docs/progress.md:126`, `test_console_hub_integration.py`)와 CORE REST의 ROS-SIM이다. D-316 상관은 SOURCE/LOCAL이다. 로봇과 관제를 실물로 이어 본 기록은 없다. 두 쪽이 함께 읽는 시험 벡터도, 실물 적합성 탐침도 없다.

**2026-09-29 실측(LOCAL + DEVICE 읽기 전용).** 대상은 `rosy-pinky-8kcn`(192.168.1.202:8080, 릴리스 `2026.09.27-010`)이다. 같은 Wi-Fi의 Windows PC에서 토큰 없이 GET과 WS 연결만 했다. 이동·상태 변경·인증 추측은 하지 않았다.

| 확인 | 결과 | 계약 대조 |
|---|---|---|
| `GET /` | 307 → `/dashboard` | 코드와 같음(`app.py:170-172`) |
| `GET /api/v1` | 200 `{"name":"core","api_versions":["v1"]}` | 코드와 같음. 릴리스·계약 버전은 알려 주지 않는다 |
| `GET /api/v1/health` | 404 | 계약·코드 모두 이 경로가 없다. 생존 확인 경로가 계약에 없다 |
| `GET /openapi.json`, `/docs` | 200 (Swagger는 jsdelivr CDN을 부른다) | 계약에 공개 여부가 없다 |
| `GET /metrics` | 200, 토큰 없음. 배터리·가동 시간·구성요소 health가 보인다 | API Ref §5 273행: "토큰 면제는 배포 정책". 그 배포 정책 문서가 없다 |
| state, map, events, system/info, capabilities, whoami | 401 `UNAUTHORIZED` | 계약대로 막힌다 |
| WS `/ws/state`, `/ws/events` (토큰 없음) | close 4401 | 계약대로 막힌다 |
| mDNS TXT | `product=rosy role=robot proto=core-v1 tls=none stage=CORE_READY release=2026.09.27-010 name=rosy-pinky-8kcn network=sta` | 프로파일 26행이 `stage`·`release`·`name`·`network` 유지를 허용한다. **적합** |
| OpenAPI 대조(로봇 vs `main` 9b3cfb59 `create_app`) | 경로 93개 동일. 스키마 두 개 차이: `GoalRequest.correlation_id`, `TrafficPolicyPatch.junction_rule`가 로봇에 없다 | 아래 발견 1, 2 |
| 버전 표기 | 로봇 description `v1.41`, `main` `app.py:96` `v1.52`, API Ref 헤더 `v1.56`. `info.version`은 셋 다 `1.20.0` | 아래 발견 2, 3 |
| `test_protocol_version_alignment.py` (`main`) | 1 failed: app description `v1.52` ≠ 문서 `v1.56` | D-18 규칙이 `main`에서 이미 깨져 있다 |

**2026-10-01 갱신(교차 세션 검토에서 모은 사실, 재측정 아님).** 위 표는 2026-09-29의 기록으로 둔다. 그 뒤 바뀐 것:

- 로봇 판: 192.168.1.202 `rosy-pinky-8kcn`은 2026-09-30 16:30 UTC에 릴리스 `2026.10.01-012`가 활성화됐다(그 전: 이미지 `2026.09.27-010` 위 payload `2026.09.30-008`, 일부 유닛은 손 설치). 192.168.1.201은 새 카드 `rosy-pinky-9dfk`(이미지 `2026.09.30-009`)다. 두 대 모두 `GET /api/v1`에 판 정보가 없고 `info.version`은 1.20.0이다. 표의 "v1.41"은 로봇 OpenAPI `description`의 판 표기다.
- `main` 계약: API Ref v1.64(Pilot `/pilot` 라우트, line-follow hold 등 포함).
- 그래서 이 ADR은 이미지 판을 기준으로 고정하지 않는다. 판정은 탐침이 로봇에서 읽은 TXT `release`와 (2항 이후) `contract_version`으로 한다. 발견 1(상관 ID 버림)은 새 이미지에서 탐침으로 다시 본다.
- 발견 상태(`main` 41cde1d2): 3 해결(정렬 시험 녹색), 8 해결(4e6563ce, 브리지가 공통 TXT 규칙 사본을 씀), 6 부분(c4904cb7 이후 연결이 끊기면 짝 집합에서 뺀다; 소켓-로봇 결속과 상수 시간 비교는 남음), 7·10 열림.

**발견(심각도 순, 2026-09-29 기준).**

1. **높음 — 배포 이미지는 D-316 상관 ID를 조용히 버린다.** Fleet은 `POST /api/v1/navigation/goal`에 `correlation_id`를 넣는다(`transport.py:199-203`). 로봇 이미지의 `GoalRequest`에는 그 필드가 없고 `extra="forbid"`도 아니다. 요청은 성공하지만 CORE 이벤트에 상관 ID가 실리지 않아 Fleet task가 결과와 맞물리지 않는다. D-316은 API Ref v1.44(2026-09-28)에 들어왔고 이미지는 v1.41이다.
2. **높음 — 와이어 스키마가 바뀌어도 런타임에서 알 수 있는 버전이 바뀌지 않는다.** `info.version`은 1.20.0에 머물고, `/api/v1`은 `v1`만 말한다. Fleet도 탐침도 로봇이 어느 계약 판을 서빙하는지 판정할 수 없다. 릴리스는 mDNS TXT에만 있다.
3. **중간 — 계약 판 표기가 세 곳에서 다르다**(v1.41 / v1.52 / v1.56). `main`의 정렬 시험이 실패 상태로 합쳐져 있다.
4. **중간 — 토큰 없이 열리는 경로의 정책이 문서에 없다.** `/metrics`는 "배포 정책"에 맡겨졌지만 그 정책이 없다. `/openapi.json`, `/docs`는 계약에 언급이 없다. 로봇 AP처럼 인터넷이 없는 곳에서 `/docs`는 CDN 때문에 그려지지 않는다.
5. **중간 — 벤치 도달성.** 관제 이벤트 이력은 로봇이 Fleet `/ws/robots`에 연결해야 생긴다. Fleet을 `127.0.0.1`에만 열면 로봇이 닿지 않는다. `robots.yaml.example`은 `https://…:8443`을 예로 들지만 로봇 광고는 `tls=none`, 포트 8080이다.
6. **높음(보안) — Hub가 소켓과 로봇을 묶지 않는다.** HEARTBEAT·EVENT는 전역 `_paired` 집합에 있는 아무 `robot_id`나 받는다(`hub/hub.py:142-144`, `:156-159`). 연결이 끊겨도 `_paired`에서 빠지지 않는다(`hub/server.py:62-64`는 `online=False`만). 짝지은 로봇 하나가 다른 로봇의 이벤트를 넣을 수 있다. 짝 토큰 비교는 상수 시간이 아니다(`hub.py:106`, CORE는 `hmac.compare_digest`).
7. **높음 — CORE 재시작 뒤 이벤트 이력이 빠질 수 있다.** Agent의 이벤트 `seq`는 프로세스마다 1부터 다시 센다(`fleet_agent/agent.py:79-80`). Fleet이 켜진 채 CORE만 재시작하면 WELCOME `last_event_seq`가 옛 큰 값이고, Agent는 그 이하를 버린다(`agent.py:122`). 또 `agent.py:80`이 EventBus 링 버퍼가 가진 같은 `EventMessage` 객체의 `seq`를 덮어써 `/api/v1/events`·`/ws/events`·감사 기록의 seq가 바뀐다(`events/bus.py:42-55`). SOURCE 판독이며 실측은 S5에서 한다.
8. **중간 — 사이트 mDNS 브리지는 공통 TXT를 보지 않는다.** `deploy/site/mdns-bridge.py:21-37`은 `product`/`role`/`proto`/`tls`를 검사하지 않고, 중복 키를 거르지 않으며, `network == "sta"`가 아니면 버린다. 프로파일 16행 규칙(필수 키 중복·불일치면 버림)과 다르다. 로봇 쪽 광고(`rosy-boot-status.py:253-261`)와 로봇의 `_rosy-fleet` 해석(`fleet_agent/discovery.py:18-40`)은 적합하다.
9. **중간 — 문서와 코드가 다른 곳.** API Ref `:504`는 `wss://fleet:8081/ws/robots`이지만 코드는 관제 앱(:8090, Caddy :8443)에 붙는다. §7.5 `:553`은 `X-Correlation-Id` 헤더이지만 코드는 본문 `correlation_id`다. §7.2 `:533`의 장기 토큰 발급(`WelcomePayload.long_term_token`)은 채워지지 않는다. §7.4의 `since_seq` 재전송은 WELCOME `last_event_seq`로 구현됐다. AUTH-101은 첫 메시지 인증을 주로 하는데 Fleet은 폐기 예정인 `?token=`을 쓴다(`swarm/robots.py:122-131`). `docs/progress.md:88`은 FleetAgent·Hub가 미구현이라고 적었지만 둘 다 있다.
10. **낮음 — 계약에 생존 확인 경로가 없다.** 지금 쓸 수 있는 공개 경로는 `GET /api/v1`과 `/metrics`다. `tools/sim/probe_*.sh`는 토큰 없이 `robot/state`를 불러 401을 받는다. Agent 종료 때 `events.unsubscribe`는 EventBus에 없는 메서드다(`agent.py:149`).

### Decision

1. **메시지마다 원천은 하나다.**
   - CORE REST·WS의 와이어 모양: CORE가 만드는 OpenAPI(`create_app().openapi()`)를 정규화해 저장한 **계약 스냅샷** `docs/reference/contracts/core-openapi.v1.json`이 원천이다. API Ref 본문은 의미·권한·순서를 설명하고, 필드 목록은 스냅샷이 정한다. 첫 스냅샷은 S1 시점의 `main`에서 만든다(2026-10-01 기준 v1.64 이상).
   - 로봇 안의 ROS 토픽(예: D-373 `camera/front/compressed`, `perception/learned/*`)은 CORE HTTP 계약이 아니므로 스냅샷 대상이 아니다.
   - FleetAgent envelope: `core_common/protocol/schemas.py`의 Pydantic 모델이 원천이다(D-18 유지). envelope `protocol_version`은 1.0 고정.
   - mDNS TXT: `site-lan-discovery-profile.md` 표가 원천이다.
   - 이 셋 밖의 사본(Fleet 쪽 요청 모델, 예제 파일)은 원천을 따라가는 소비자다.
2. **스키마가 바뀌면 판이 바뀐다.** 스냅샷의 정규화 해시가 바뀌는 변경은 API Ref의 MINOR를 올리고, `app.py` description과 `info.version`을 같은 변경에서 올린다. `GET /api/v1`은 `contract_version`(예: `"1.57"`)과 `schema_sha256`을 추가로 답한다(additive, 공개). 로봇이 어느 판을 서빙하는지 토큰 없이 판정할 수 있어야 한다.
3. **적합성 시험은 양쪽이 같은 벡터를 읽는다.**
   - CORE 쪽: 스냅샷과 현재 `create_app().openapi()`가 같아야 한다.
   - Fleet 쪽: `transport.py`가 보내는 요청 본문과 받는 응답 파싱을 스냅샷의 스키마로 검증한다. Fleet은 CORE 코드를 import하지 않는다(D-18, D-59) — 스냅샷 JSON 파일만 읽는다.
   - 공유 벡터 `test/fixtures/protocol/`에 HELLO/WELCOME/HEARTBEAT/EVENT 예제와 `robot/state`, `map`, `navigation/goal` 요청·응답 예제를 두고 양쪽 시험이 같은 파일을 쓴다.
4. **실물 확인은 읽기 전용 적합성 탐침으로 한다.** `tools/protocol/conformance_probe.py`:
   - 기본은 토큰 없이 공개 등급만 본다(`/api/v1`, `/openapi.json`, 401/4401 거절, mDNS TXT).
   - 토큰은 환경 변수로만 받는다(`ROSY_CORE_TOKEN`). 인자·파일·로그에 남기지 않는다. 토큰이 있으면 viewer 등급 GET과 WS 수신만 추가한다.
   - 쓰기·이동·정지 요청은 보내지 않는다. 비이동 명령 왕복은 별도 플래그와 별도 회차로만 연다(아래 5).
   - 출력은 JSON 보고서 하나다: 로봇이 서빙한 OpenAPI와 스냅샷의 차이, TXT 대조, 거절 확인, 판정.
5. **관제의 DEVICE 증거는 다섯 가지가 모두 있을 때만 쓴다.**
   1. Fleet 로봇 목록에 실물 로봇이 보이고 상태가 신선하다(`robot/state` 수신 시각과 로봇 `ts` 차이 기록).
   2. 관제 지도에 로봇 `map`이 그려진다.
   3. FleetAgent HELLO가 `fleet_pairing_token`으로 받아들여지고, 이벤트가 Fleet SQLite에 쌓이며, Fleet 재시작 뒤에도 남는다.
   4. 비이동 명령 한 번의 왕복이 D-316 상관 ID로 이어진다. 이미지가 v1.44 이상일 때만 가능하다. 그 전에는 이 항목을 HOLD로 적고 DEVICE를 주장하지 않는다.
   5. 정지는 CORE가 소유한다. Fleet의 `safety/stop`은 요청일 뿐이고 정지 사실은 CORE `safety/state`로 읽는다(D-276, D-330). 이 회차에서 정지 명령을 보내지 않는다.
   읽기 전용 탐침만 통과한 상태는 **DEVICE(읽기 전용)**으로 따로 적는다. 관제 DEVICE가 아니다.
6. **벤치 기준선.** S4를 시작할 때 벤치를 새로 세우고 그 구성을 보고서에 적는다. 2026-09-29 벤치(Fleet `127.0.0.1:8090`, Vision `0.0.0.0:8095`, Caddy `127.0.0.1:8443`)는 종료됐다. 이후 벤치들이 쓴 포트(예: 18447·18448)는 벤치별 값이지 Fleet 기본값이 아니다. FleetAgent 경로를 보려면 로봇이 닿는 주소에 `/ws/robots`를 열어야 한다. 이는 `fleet/cli.py:274-315` 규칙(루프백 밖은 `--token`/`--users-file`과 `--tasks-db` 필수)을 따른다.

### Alternatives

- **API Ref 본문을 손으로 OpenAPI YAML로 옮겨 원천으로 삼는다.** 거부한다. 코드와 문서 두 벌이 다시 어긋난다. 이번 발견 3이 바로 그 결과다. 생성된 스냅샷을 커밋하고 차이를 시험으로 막는 편이 싸다.
- **Fleet 시험이 CORE `create_app`을 직접 import해 대조한다.** 거부한다. D-18/D-59의 import 경계를 깬다.
- **`/api/v1/health`를 새로 만든다.** 지금은 보류한다. `GET /api/v1`이 공개이고 판 정보를 싣게 되면 생존 확인도 겸한다. 별도 경로가 필요하다는 근거가 생기면 다시 본다.
- **탐침이 처음부터 명령 왕복까지 한다.** 거부한다. 토큰·이미지·입회 조건이 없는 상태에서 쓰기 경로를 기본으로 두면 실수 한 번이 로봇을 움직인다.

### Consequences

- 정렬 시험 실패(발견 3)는 S1 전에 이미 고쳐졌다(2026-10-01 녹색).
- 발견 6·7은 관제 DEVICE ③(이벤트 이력)의 신뢰를 직접 깎는다. S2에서 시험으로 먼저 재현하고 고친 뒤에야 ③을 DEVICE로 적는다. 고치는 방법(세션-로봇 결속, Agent의 부팅 세대 + seq)은 S2의 구현 선택이며 envelope 필드를 더하면 API Ref MINOR를 올린다.
- 발견 9의 문서 정정은 API Ref Clarify 행으로 한 번에 한다(스키마 변경 없음).
- 배포 이미지 `2026.09.27-010`에서는 상관 ID 왕복을 증명할 수 없다. 관제 DEVICE는 새 이미지 전까지 부분(①②③)까지만 가능하다.
- `/metrics`, `/openapi.json`, `/docs`의 공개 여부를 배포 정책으로 문서화해야 한다. 이 ADR은 방향만 정한다: `/metrics`는 공개 유지하되 배터리·health 외 식별자를 싣지 않는다. `/docs`는 기기 모드에서 끌 수 있게 하는 안을 S1에서 판단한다.
- 스냅샷이 생기면 API 변경마다 스냅샷 재생성이 필요하다. 재생성 명령은 하나로 둔다.

### 결정하지 않는 것

- 로봇 이미지 재빌드·서명·배포 시점.
- 토큰 발급 절차 변경, TLS 도입, 로봇 포트 변경.
- PRT-004 envelope `correlation_id` 활성화(D-170/D-297). D-316 REST 상관만 다룬다.
- 천장 카메라 페어링([D-341](D-341-overhead-console-approved-pairing.md))과 관제 지도 사이트 레이어의 설계. 이 ADR은 그 두 가지를 다시 정하지 않는다.
- 이동 명령·정지 명령의 실물 시험.

### Validation

- SOURCE/LOCAL: 스냅샷 동일성 시험(CORE), 스냅샷 기반 요청·응답 시험(Fleet), 공유 벡터 시험, 탐침 단위 시험(가짜 서버), `test_protocol_version_alignment.py` 통과.
- DEVICE(읽기 전용): 탐침 JSON 보고서를 `docs/validation/`에 남긴다. 토큰은 가린다.
- DEVICE(관제): Decision 5의 다섯 항목 기록.

이 ADR의 근거는 LOCAL 시험 한 번과 DEVICE 읽기 전용 관찰이다. 관제 DEVICE·FIELD 수용이 아니다.

### References

[D-5](D-5-outbound-ws-fleet-rest.md), [D-10](D-10-fleet-envelope.md), [D-12](D-12-mission-fleet.md), [D-18](D-18-rosy-core.md), [D-59](D-59-.md), [D-170](D-170-prt-004-deferred-until-central-fleet.md), [D-177](D-177-prt-004-activation-design.md)(D-297이 대체), [D-193](D-193-login-code-and-credential-lifecycle.md), [D-276](D-276-site-fleet-per-principal-api-authorization.md), [D-297](D-297-command-ack-and-fleet-record-activation.md), [D-316](D-316-pinky-site-fleet-navigation-result-correlation.md), [D-330](D-330-fleet-action-admission-stop-and-recovery.md). [D-341](D-341-overhead-console-approved-pairing.md). 계획: [2026-09-29-robot-fleet-protocol-conformance-plan.md](../plans/2026-09-29-robot-fleet-protocol-conformance-plan.md).
