# Fleet 호출 지도

현재 소스의 호출 지도다. 기준은 local main `e14245e86`(2026-10-13)이다. 계약은 ADR과 API Reference다. 화면 구조의 결정은 [D-540](../../../docs/adr/D-540-fleet-console-structure-v2.md)(Proposed)이고, CORE trip 소유는 [D-541](../../../docs/adr/D-541-core-fleet-trip-lease.md)(Proposed)이다. 구현 순서는 [콘솔 v2 계획](../../../docs/plans/2026-10-09-fleet-console-v2.md)이다. 이 문서는 그 결정을 바꾸지 않는다. D-540은 Proposed인 채로 브랜치 (a) 이름 있는 운영자, (b) 공통 머리, (c) 예외 큐 펼침, 이 트리에 있고, (d)의 로봇 카드 운행 폼(`card-trip.js`)도 있다. D-541 7의 Fleet trip lease holder도 있다. 기본은 `fleet.trip_lease_required` false라 lease를 열지 않는다.

현장에 올라가 있는 Fleet 이미지가 이 커밋보다 이전일 수 있다. 이 문서는 그 이미지를 열어서 확인하지 않았다. 소스·호스트 대조는 장치 주행과 현장 수용을 대신하지 않는다.

신호등 감독의 살아 있는 설명은 [signals.md](signals.md)다. 천장 카메라에서 브라우저까지의 경로는 [현장 천장 카메라 · 관제 운영 가이드](../../../docs/deployment/site-ceiling-camera-console-runbook.md) §1이다.

## 누가 무엇을 소유하는가

| 자리 | 소유 | 이 트리에서 하는 일 |
|---|---|---|
| 브라우저 (Rosy Fleet, D-487) | `applications/fleet/web` (원본, D-518·D-637) | 정적 ES 모듈이며 Fleet이 `fleet.server.web`으로 설치해 서빙한다. 문서는 `/console`, `/console/install`, `/console/cell`, `/console/site-map`, `/console/login`, `/console/profile`이다. 공통 머리 `shared/fleet-header.js`가 있다(D-540 2). ADR 자체는 Proposed다 |
| 현장 프록시 | `deploy/site/Caddyfile` | 운영 PC는 `ROSY_SITE_HTTPS_PORT`(`.env.example` 예시 8443)로 연다. `/api/vision/sources/*`와 `/overhead/v1/frames`는 Vision, 그 밖은 Fleet이다. Fleet 리스 경로는 Fleet으로 간다 |
| Fleet | `fleet` 패키지, CLI 기본 포트 8090 | 사이트 오케스트레이터. 로봇 계약 호출은 `HttpRobotClient`(`fleet/swarm/transport.py`) 하나다. `/cmd_vel`을 내지 않고 JPEG를 중계하지 않는다 |
| CORE | `middleware/core` | 동작과 최종 `/cmd_vel`. Fleet 경로는 `/api/fleet/*`, 로봇 경로는 `/api/v1/*` |
| Cam / Vision | 현장 스택 | Cam은 Vision으로 프레임을 보낸다. 브라우저는 Fleet이 준 `frame_path`를 Vision에서 직접 받는다 |
| 허브 | `fleet/hub` | 서버 안 수집이다. 브라우저 API가 아니다 |

## 브라우저 → Fleet

로봇 행은 `GET /api/fleet/state` 폴링이다. 추적 고리는 `GET /api/fleet/tracking`을 `TRACKING_MS`(400 ms)마다 읽는다. 한 대라도 읽기가 실패하면 그 행만 `online: false`이고 나머지는 온다. 허브 heartbeat가 `hub_state_max_age_s`(기본 3 s) 안이면 `gather_source`는 `hub`, 아니면 REST `GET /api/v1/robot/state`라서 `rest`다.

연결 단어는 `classify_link`가 닫는다. 성공은 `up`이다. 화면 태그(`link-tag.js`)는 `up`을 그리지 않고 `unreachable`, `moved`, `degraded`, `tls-refused`, `protocol`만 그린다. 마지막 성공 뒤 `LINK_DEGRADED_S`(10 s) 안의 실패는 `degraded`(응답 지연)다. 이때 `online`은 false라서 교통·핸드오프·목표 판단은 오프라인과 같다. 카드는 `degraded`를 오프라인 표시로 보지 않는다. `link_reason`(D-535)은 `{code, message, action, retry}`다.

| 화면 동작 | Fleet 경로 | 본문·결과 |
|---|---|---|
| 상태·세션 | `GET /api/fleet/state`, `GET /api/fleet/session` | 로봇 행, 세션 역할. D-540 2가 말한 `/auth/session` 하나로의 합치기는 아직이다 |
| 목표 | `POST /api/fleet/robots/{id}/goal` | `{x, y, yaw}`. 지도 클릭은 `yaw: 0`과 `Idempotency-Key`(UUID)를 보낸다. 작업 서비스가 켜져 있으면 헤더가 없으면 400 `IDEMPOTENCY_KEY_REQUIRED`. 이름 있는 운영자만 보낸다(D-540 9). 그 로봇에 열린 Fleet 운행이 있으면 목표 버튼은 잠긴다(`motion-readiness.js`). 공유 토큰은 403 `OPERATOR_IDENTITY_REQUIRED`. Fleet은 CORE `POST /api/v1/navigation/goal`에 `correlation_id`를 보탠다. 로봇이 `goal_lease`를 알리면 `lease_ttl_s`를 넣을 수 있다(D-550 10). 갱신은 `POST /api/v1/navigation/goal/lease` |
| 목표 lease presence | `POST /api/fleet/goal-lease/presence` | 보이는 운영 콘솔이, 어떤 로봇의 `goal.goal_lease`가 `leased`인 동안만 보낸다. lease가 꺼져 있으면 새 호출이 없다 |
| 목표 버튼 | 위와 같음 | 첫 잠금은 이름 있는 운영자(`이름 있는 운영자 로그인이 필요합니다`). 그 다음 열린 운행·대형 참여, Fleet 상태 없음, 오프라인, `navigation.goal_navigation` 없음, 지도 없음, 비상 정지, 안전 상태 미확인, 라인 추종 중이다. 지도 프레임 `LOCALIZED`가 아니어도 버튼은 눌린다. CORE가 거절하면 로그에 미션 거절로 남는다 |
| 라인 추종 | `POST /api/fleet/robots/{id}/line-follow` `{mode}` | 화면은 `IR_LINE`과 `OFF`만 보낸다. 클라이언트도 그 둘만 `PUT /api/v1/line-follow/mode` 한다. 이름 있는 운영자다 |
| 취소·전체 취소 | `POST .../cancel`, `POST /api/fleet/cancel-all` | 로봇 취소, 전체 취소 |
| 비상 정지 | `POST /api/fleet/estop` | `fleet-header.js`의 `bindEstop` 하나. 401이면 `접속이 필요합니다`, 보기 전용이면 운영자 사유, 모름(로딩·Fleet 끊김)은 눌린 채다 |
| LED 확인 | `POST /api/fleet/robots/{id}/identify` | `color`는 없거나 `blue`·`amber`. 이름 있는 운영자다 |
| 절전·깨우기 | `POST /api/fleet/robots/{id}/power` `{action}` | `sleep`·`wake`만(D-440 6). 이름 있는 운영자다. 로봇이 `IDLE`이 아니면 절전 버튼은 `일하는 로봇은 절전할 수 없습니다`로 잠기고, 보내더라도 CORE가 `ACTIVE`로 답한다 |
| 막힘 | `POST .../line-stuck/claim`, `POST .../line-stuck/decision` | 운영자 값은 `WAIT`, `RESUME`, `BACK_AND_RETRY`, `MANUAL`, `ABORT`. 다섯 답은 예외 큐 행 펼침에 있다(D-540 3). `WAIT`·`ABORT`·claim은 열린 멈춤이고, 나머지 답은 이름 있는 운영자다 |
| 대형 | `GET /api/fleet/formation`, `POST .../start`·`/reform`·`/resume`·`/stop` | 시작 본문은 `{leader, formation, spacing}`, 일부만 고르면 `members`. `max_speed`는 생략하고 서버 기본을 쓴다. start·reform·resume은 이름 있는 운영자, stop은 열린 멈춤이다. 따라가기는 `session.py`가 `POST /api/v1/swarm/follow` |
| 물리 신호 | `POST /api/fleet/signals/presence`, `POST /api/fleet/signals/{id}/command` | `{mode, lamps}`. `flash_red`·`all_red`는 열린 멈춤이고 나머지 명령은 이름 있는 운영자다. 감독은 [signals.md](signals.md) |
| 가상 신호 | `POST /api/fleet/traffic/signals/presence`, `POST /api/fleet/traffic/signals/{id}` | `{verb}` 또는 `{verb, approach}`. 장치 명령이 아니다(D-525). 이름 있는 운영자다 |
| 천장 영상 | `GET /api/fleet/vision/sources`, `POST /api/fleet/vision/lease` | 리스는 `{source_id, rectification}`를 받고 `frame_path`를 준다. 브라우저는 그 경로를 Vision에 `Authorization: Bearer`, `credentials: "omit"`으로 받는다 |
| 현장 지도·운행 | `PUT /api/fleet/site-map/draft`, `POST .../activate`, `POST /api/fleet/robots/{id}/trip`, `POST /api/fleet/trips/{id}/start`·`/cancel`·`/confirm-replan` | 쓰기·시작은 이름 있는 운영자다. 운행 시작은 현장 지도(`shared/site-map-model.js`)와 로봇 카드 폼(`card-trip.js`) 둘에 있고, 취소는 카드(`roster.js`)에 있다. 재계획 확인은 예외 큐 행(`trip-replan.js`)이다. 현장 지도 쪽 시작을 걷는 것은 계획 브랜치 (e)다. `fleet.trip_lease_required`가 참이면 시작이 CORE `PUT /api/v1/trip-lease`를 연다(D-541 7, 기본 false) |
| 가르치기·시작점 | `/api/fleet/teach/*`, `/api/fleet/start-points` | 설치·보정 문서 |
| 등록 | `/api/fleet/enrollment/robots` | Fleet이 로봇 `POST /api/v1/auth/pair`, `GET /auth/whoami`, `GET /system/info`, `POST /auth/logout`을 한다. TLS 프로브는 `GET /api/v1/auth/peer-pairing/identity` |
| 셀 | `/api/fleet/cell-app/*`, `/api/fleet/cell-jobs/*`, `/api/fleet/missions/{id}/admit` | 읽기·컴파일·제안·작업. 승인 자리의 이동은 D-540 8항 |
| 로그인 | `/api/fleet/auth/connection`, `/session`, `/login`, `/logout`, `/change-password`, `/profile`, `/development-session` | 개발 세션은 이름 있는 운영자다(D-473) |
| 호스트 서비스 | `GET /api/fleet/hosts`, `POST /api/fleet/hosts/{host_id}/control` | 설치 문서의 `host-services.js`가 부른다. 서비스 제어 API(D-524, Proposed). 헬퍼가 없으면 503이고 재부팅하지 않는다 |
| 설치·발견 | `/api/fleet/discovery`, `/discovery/addresses`, `/tracking/relearn`, `/tracking/identity`, `POST`·`DELETE /api/fleet/robots/{id}/hub-link` 등 | 등록·허브 연결·추적 배경 학습. 설치·보정 문서 |
| 사건·작업 읽기 | `/api/fleet/incidents`, `/api/fleet/work`, `/api/fleet/channel-requests`, `/api/fleet/dispatch-control` | 사건 증거와 검토, 출처별 Task/Mission 읽기, 채널 요청, 작업 배정 제어. 이 문서가 본문까지 대조한 범위가 아니다 |

전원은 상태 행의 `power_health`(`PowerHealthResponse`)와 `power_health_age_s`다. Fleet은 `GET /api/v1/power/health`로 읽는다. 나이가 오래되거나 값이 없으면 카드는 `확인 불가`다(`power-health-view.js`).

## Fleet → CORE

`HttpRobotClient`가 부르는 경로다. 텔레옵 경로는 없다.

| 읽기 | 쓰기 |
|---|---|
| `GET /api/v1/robot/state` | `POST /api/v1/navigation/goal`, `/navigation/cancel` |
| `GET /api/v1/power/health` | `POST /api/v1/safety/stop` |
| | `POST /api/v1/power/mode` (`STANDBY`만), `POST /api/v1/power/wake` |
| `GET /api/v1/system/capabilities` | `POST /api/v1/swarm/follow`, `/swarm/cancel` |
| `GET /api/v1/map`, `/navigation/path`, `/swarm/state` | `PUT /api/v1/line-follow/mode` (`IR_LINE`·`OFF`만) |
| `GET /api/v1/line-follow` | `POST /api/v1/line-follow/junction`, `/authority`, `/advice`, `/stuck/decision` |
| `GET /api/v1/localization/candidates`, `/localization/request`, `/localization/mission` | `POST /api/v1/localization/decision`, `/suspect`, `/mission` |
| `GET /api/v1/vision/front/status`, `/vision/front/frame` | `POST /api/v1/host/lamp/identify` (결과는 `GET .../identify/{request_id}`) |
| `GET /api/v1/motion/rotate_to` | `POST /api/v1/motion/rotate_to`, `POST /api/v1/line-follow/lane-cue` |
| `GET /api/v1/fleet/link` | `PUT`·`DELETE /api/v1/fleet/link` (허브 연결) |
| | `PUT /api/v1/trip-lease`, `DELETE /api/v1/trip-lease/{lease_id}` (D-541 7, 설정이 참일 때만) |
| | `POST /api/v1/navigation/goal/lease` (D-550 10, 로봇이 `goal_lease`를 알릴 때) |

`advice`(D-551)는 표시용이며 허가가 아니다. 막힘 `YIELD`와 `yield_m`은 해결기→CORE 경로다(`fleet/stuck/resolver.py`, D-453). 운영자 라우트의 Literal에는 `YIELD`가 없다. 이름 분기는 `WAIT`·`ABORT`가 아닌 답을 이름 있는 운영자로 보므로, Literal에 `YIELD`가 들어오는 순간 그 분기가 적용된다. 지금은 검증이 먼저 거절한다.

등록 게이트가 잡혀 있어도 멈추는 세 경로는 열린다. `STOP_PATHS`는 `/api/v1/safety/stop`, `/api/v1/navigation/cancel`, `/api/v1/swarm/cancel`이다. 비상 정지가 OMX 로컬 정지를 함께 뿌리는 것은 서버 안 동작이고 브라우저 경로가 아니다.

## 프록시가 나누는 것

| 매처 | 도착 |
|---|---|
| `@lan_camera`: 사설망의 `GET /api/fleet/vision/sources`, `POST /api/fleet/vision/lease` | Fleet. `X-Rosy-Lan-Camera: 1` |
| `@camera`: `/overhead/v1/frames` | Vision |
| `@vision_preview`: `/api/vision/sources/*` | Vision |
| 그 밖 | Fleet. 위 헤더는 지운다 |

## 화면이 부르지 않는 경로

콘솔에 호출이 없는 경로다. 깨진 프론트 호출이 아니다.

| 경로 | 지금 쓰는 쪽 | D-540이 이미 말한 처분 |
|---|---|---|
| `POST /api/fleet/do` | 기계 intent. 가드된 goal을 탄다 | 유지. 이름 있는 운영자 규칙을 따른다(8·9항) |
| `GET /api/v1/fleet/robots` | 다른 클라이언트용 레지스트리 | 화면 경로가 아니다. 지우지 않는다 |
| `POST /api/fleet/robots/{id}/route` | 화면 없음 (D-463) | 제거. trip이 대신한다 |
| `GET /api/fleet/tethers` | 꼬리 그림 (`trail-view.js`) | 읽기는 유지. `POST`/`DELETE`는 제거 |
| `GET` map-pose, lane-compliance, sightings 일부, policy-evidence, goal-evidence, owner recover, `GET .../traffic/signals/ahead/{robot}` | 서버·다른 행위자 | 필요가 생기면 별도. D-540 10항이 범위를 닫아 둔 화면이 있다 |

## 맞춰 둔 경계

- 브라우저가 부르는 Fleet 경로의 메서드와 본문은 서버 모델과 맞다. 없는 경로를 치는 화면 호출은 이 대조에서 보이지 않았다.
- CORE 클라이언트 경로는 이 트리의 `core_api_web`와 맞다.
- 프록시 분기는 위 표와 같다.
- 클릭 목표는 방향 0이다. 고리 주행처럼 방향이 필요한 이동은 trip이다.
- 연결 단어 `up`은 성공이다. 태그가 없는 것이 정상이다.

## 개선

아래는 구현하지 않는다. 화면을 다시 설계하지 않는다.

### 이미 결정된 것

[D-540](../../../docs/adr/D-540-fleet-console-structure-v2.md)과 [계획](../../../docs/plans/2026-10-09-fleet-console-v2.md)이 처분했다. ADR은 Proposed다. 이 트리에 이미 있는 구현은 (a) 이름 있는 운영자의 움직임 경로, (b) 공통 머리, (c) 예외 큐 펼침(막힘 다섯 답, 재계획 확인, 접힌 카드)이다. Cell 승인을 큐로 옮기는 부분은 (c)에 없다. 세션 경로를 `/auth/session` 하나로 합치는 것도 남아 있다. D-541 7 Fleet lease holder는 기본 false로 들어 있다. D-550 10 목표 lease도 로봇이 능력을 알릴 때만 탄다.

남은 순서와 각 브랜치의 착지 여부는 [계획](../../../docs/plans/2026-10-09-fleet-console-v2.md)과 ADR Log를 본다. 이 문서는 (e) 이후의 착지를 소스로 확인하지 않았다. lease 설정이 false면 CORE 점유는 열지 않는다.

D-540 8항이 이미 처분한 항목은 배터리 `battery_pct`와 `motion_reason` 표시, 보정 lease 보유자, payload 읽기 전용, D-524의 이동 또는 제거, 막힘 증거, D-395 확정 동작, `/route` 제거, 카메라 승인 패널 병합, tether 쓰기 제거, 대형·대열 병합, Cell 승인 이동, `/api/fleet/do` 유지다. 9항의 멈춤(estop, cancel-all, 로봇 취소, trip 취소, task 취소, formation stop, 신호의 `flash_red`·`all_red`, WAIT, ABORT, claim)은 이름 없는 운영자에게 열려 있다.

### 구현할 때 같이 접을 것

별도 화면 과제가 아니다. D-540을 구현하는 커밋에 붙인다.

1. **목표 yaw.** `console.js` `commitGoal`은 항상 `yaw: 0`이다. 카드 운행 폼은 이미 있다. 점 목표는 로봇의 현재 지도 yaw를 보내고, 방향이 필요한 고리 주행은 trip을 쓴다. 새 목표 API는 만들지 않는다.
2. **위치 미확정 목표.** 목표 버튼은 `LOCALIZED`가 아니어도 잠기지 않는다. 배지만 보이고 CORE가 거절한다. 맞는 잠금은 지도 프레임이 `LOCALIZED`일 때만 목표 지정을 열고, 사유는 예외 큐를 가리키는 것이다. D-540의 "한 원인은 한 번"과 같은 자리다. 버튼을 다른 문서로 옮기지 않는다.
3. **YIELD 문장.** 운영자 Literal과 `line-stuck.js`의 값은 `WAIT`, `RESUME`, `BACK_AND_RETRY`, `MANUAL`, `ABORT`다. `YIELD`는 해결기가 CORE `POST /api/v1/line-follow/stuck/decision`에 보내는 값이다(D-453). D-540 9항은 `YIELD`를 운영자의 움직이는 답으로 적는다. 권한 코드는 이미 `WAIT`·`ABORT`가 아닌 답을 이름 있는 운영자로 본다. Literal이 `YIELD`를 거절하므로 그 분기와 trip 바쁨 검사의 `YIELD`는 도달하지 않는다. 같은 단어가 `fleet/stuck/ai_facts.py`의 AI 판단 Literal에는 있다. 여섯 번째 버튼을 넣기 전에 ADR 문장과 Literal을 한쪽으로 맞춘다. `YIELD`를 9항에서 빼 해결기 전용으로 두거나, Literal과 큐에 넣거나 둘 중 하나다. 이 문서는 D-540을 고치지 않는다.
4. **전원 나이.** 카드는 `GET /api/v1/power/health`의 나이·근거 규칙을 쓴다. D-540 8항은 CORE `/safety/state`의 `battery_pct`를 행에 더한다. `battery_pct`를 붙일 때 `power_health`의 나이 규칙과 `확인 불가`를 빼지 않는다. 이 트리의 CORE에는 `GET /api/v1/power/health`가 있다(`robot.py`). 옛 로봇 이미지가 그 경로를 모르면 행은 비고 콘솔은 그 실패로 죽지 않는다.
