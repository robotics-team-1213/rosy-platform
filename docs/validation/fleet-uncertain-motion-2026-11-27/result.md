# Fleet 불확실 이동 복구 — 2026-11-27

기준: `678cb248df3e9ffd68351ec277bc74f5f291a49b` (`origin/main`), 브랜치 `fix/fleet-uncertain-motion`.
후속 기준: HEAD `22aa6d824c`, 같은 브랜치의 미커밋 수정. 전달받은 독립 안전 검토의 cancel 해제 지적을 반영했다.
이번 수정에서는 pytest·실물 접속·커밋을 하지 않았으며, 수정 후 원격 회귀와 독립 재검토는 남아 있다.

## `_uncertain_motion 해제`

기존 상태는 `set`에 추가만 되어 Fleet 재시작 전까지 named stop 준비와 peer 정지 증명을 막았다.
로봇별 dict 표지에 단조 시각, wall time, wire version, motion epoch를 보관한다.
반복 불확실 요청은 표지를 교체한다. cancel 해제 전용 navigation-only 구분은 제거했다.

해제는 표지 이후 시작된 다음 관측만 받는다. 해제 로그는 `uncertain motion of <robot> resolved: <basis>` 한 줄이다.

| 경로 | 재사용한 증거와 추가 freshness 경계 |
|---|---|
| console snapshot | 불확실 로봇은 heartbeat·공유 상태 캐시 대신 `client.state()`를 직접 읽음. 표지 이후에 측정된 standstill 또는 확인된 E-stop만 인정 |
| named-stop custody 정산 | `NamedStopMotion.stopped` / `new_boot_stopped`의 exact run·owner·두 번의 측정 정지 증명. 첫 속도 표본도 불확실 표지 이후여야 함 |

모든 경로는 관측 시작·종료 시 pending이 없어야 하며, 관측 중 로봇 wire version·불확실 표지·클라이언트가 바뀌면 해제하지 않는다.
시간 경과, `clear()`, cancel 응답으로는 해제하지 않는다. 로봇별 해제는 CORE E-stop·Fleet dispatch latch·named-stop custody를 풀거나 작업을 재개하지 않는다.

CORE `api/v1/navigation.py`의 `/navigation/cancel`은 `navigation`과 `operation`을 반환하며 `canceled` 키가 없다.
이미 CANCELED인 경우에도 `{"navigation": "CANCELED", "operation": null}`을 반환할 수 있다.
`cancel_confirmed`는 이 응답을 True로 보지만 측정 속도는 확인하지 않는다. 따라서 기존 대기열 판정은 유지하고,
`GoalLeases.cancel`의 불확실 표시 해제 연결만 제거했다. 해제 증거는 위의 직접 상태·exact custody 정지 증명뿐이다.

## 재사용한 판정

- `named_stop_motion.py:21` `measured_stop_proof`: `TripHalts.measured_stop`의 기존 판정을 그대로 추출했다. 목표 없음, line-follow OFF, 종료 navigation, 허용 mode, fresh 속도·시각·기존 0.01 m/s·0.02 rad/s 경계를 유지한다.
- `trips/trip_halts.py:166` `measured_stop`이 위 함수를 계속 사용한다. `measured_idle_stop`의 같은 idle owner·wire 확인과 `measured_ended_stop`의 같은 navigation·wire 확인은 유지한다.
- `named_stop_motion.py:43` `confirmed_estop`: 기존 `verify_release_proof`의 hardware-estop-latched 판정을 추출해 원래 경로에서도 재사용한다. safety.estop=true, EMERGENCY, line-follow OFF, fresh 측정 속도 정확히 0이 필요하다. 불확실 해제에는 표지 이후의 신선한 속도 시각도 요구한다.
- `named_stop_motion.py:81,150`의 exact custody proof를 재사용한다.
- 11/27 main의 `804318ed21`, `1dfe16aaa7`, `b8a66ce7b7`이 도입·수정한 closed-trip measured idle/ended standstill 의미를 유지한다.

## 변경 파일

| 파일 | D-430 safety 태그 | 변경 |
|---|---|---|
| `operations/fleet/fleet/server/goal_lease.py` | 예 | dict 표지·exact custody 정산 연결, 후속에서 cancel 기반 해제 제거 |
| `operations/fleet/fleet/server/peer_motion_wire.py` | 예 | 표지 기록·readback race fence·직접 상태 읽기 |
| `operations/fleet/fleet/server/named_stop_motion.py` | 예 | 기존 measured standstill·E-stop 판정 공유 |
| `operations/fleet/fleet/server/console/console.py` | 예 | 불확실 로봇 snapshot의 직접 readback |
| `operations/fleet/fleet/server/trips/trip_halts.py` | 아니오 | 기존 measured_stop이 공유 판정을 호출 |
| `operations/fleet/test/test_uncertain_motion.py` | 시험 | 회귀 시험 작성, 미실행 |
| `operations/fleet/logs.md`, 생성 `index.md` | 문서 | 변경·검증 범위 기록 |

## 유지한 것과 운영 가시성

`goal_lease.py:460`의 전역 `if self._uncertain_motion`과 `idle_wire_epoch`의 로봇별 차단은 유지한다.
기존 `check_motion`·`custody_view.motion_refused_site_wide` 및 `test_named_stop_motion.py`의 peer 배제는 사이트 전역 reservation을 전제로 한다.
D-1051은 Fleet 실행·안전 검토 경계를 정의하며, 불확실성 검사를 대상 로봇으로 좁히는 근거는 찾지 못했다.

기존 Fleet 상태/콘솔 응답에 불확실 로봇 목록을 내는 경로는 찾지 못했다. 새 API·응답 필드는 추가하지 않았다.
E-stop HTTP ACK 자체는 standstill로 취급하지 않는다(D-369). stop/cancel 대상·전송·재시도 정책은 바꾸지 않았다.

## 작성한 시험 — 실행하지 않음

`operations/fleet/test/test_uncertain_motion.py`:
표지 추가·시간 경과·clear·미확인 cancel 유지, 표지 이전 state/cancel 읽기 거절,
표지 이후 idle·ended·E-stop 증거, 오래된 속도·이동 중·다른 로봇 상태 거절,
새 uncertainty·wire 변경·pending wire·client 교체 race, 해제 뒤 prepared admission,
다른 로봇 uncertainty의 전역 거절, 비 navigation uncertainty와 console 캐시 우회,
exact custody의 두 정지 표본 및 표지 이전 첫 표본 거절, GET 직전의 신선한 표지 이후 encoder 표본 허용.

### 후속 시험 변경과 원격 실패 원인

사용자가 전달한 원격 결과는 439 통과, 아래 2건 실패다. 원본 로그와 `known_failures.py` 비교는 이번에 실행하지 않았다.

- `test_readback_started_during_a_pending_wire_cannot_resolve_it`
- `test_console_gather_bypasses_shared_and_heartbeat_caches_while_uncertain`

두 건 모두 두 번째 state 읽기의 가짜 wall clock 오차다. `FakeClock.advance`는 소수 9자리 반올림이지만,
epoch `1800000000.0`에 `.1`을 두 번 더하면 `1800000000.1999998`이다. ISO microsecond 변환 뒤 표본은
`1800000000.2`로 읽혀 `now - stamp = -2.384185791015625e-07`이 된다.
제품 `measured_stop_proof`의 `0 <= now - stamp < STALE_POSE_S`가 미래 표본으로 거절한다.
표지는 정상적으로 안전 방향으로 유지된 것이며, pending·wire version 조건을 완화할 이유는 없다.
stdlib 시각 왕복으로 이 수치를 확인했다. 시험의 wall clock 증가만 이진수로 정확한 `.25`로 바꾸고 제품 시각 경계는 유지했다.

시험 변경 목록:

- 기본·지연 cancel 대역을 실제 CORE의 `navigation`·`operation` 응답 모양으로 교체.
- 이미 IDLE/CANCELED인 cancel 응답 뒤 같은 표지·peer 차단·prepared admission 거절 유지 시험 추가.
- state/cancel 예외 전파 뒤 같은 표지·peer 차단 유지 시험 추가.
- 미래 속도 표본 거절 시험 추가. cancel을 해제 성공 증거 목록에서 제거.
- peer의 전역 차단 시험은 대상 로봇을 측정 정지로 해제하도록 변경.
- pending wire·console 캐시 우회 실패 2건은 공통 시험 wall clock의 `.25` 증가로 수정. 다른 wall clock 증가도 같은 간격으로 통일.

## 실행한 확인

초기 구현에서 저장소 `.venv/bin/python`으로 아래 6개 파일의 `-m py_compile`을 실행했다(exit 0).
바이트코드 출력은 `/tmp/rosy-fleet-uncertain-pycache`에 두었다.

```text
operations/fleet/fleet/server/goal_lease.py
operations/fleet/fleet/server/peer_motion_wire.py
operations/fleet/fleet/server/named_stop_motion.py
operations/fleet/fleet/server/trips/trip_halts.py
operations/fleet/fleet/server/console/console.py
operations/fleet/test/test_uncertain_motion.py
```

`PYTHONDONTWRITEBYTECODE=1`과 source PYTHONPATH로 `GoalLeases`, `TripHalts`, `FleetConsole` import 확인: exit 0, `Fleet imports OK`.
기본 `/usr/bin/python3`의 import는 pydantic 미설치로 실패했고, 기존 저장소 가상환경으로 확인했다. 의존성은 설치하지 않았다.
`git diff --check` 확인. 제품 diff를 직접 검토했다. pytest 및 로직 self-check는 실행하지 않았다.

후속 수정에서는 아래 명령으로 제품 2개·시험 1개 문법 검사를 다시 실행했다(exit 0).

```bash
PYTHONPYCACHEPREFIX=/tmp/rosy-fleet-uncertain-review-pycache /home/jeongmin/Desktop/rosy-platform/.venv/bin/python -m py_compile operations/fleet/fleet/server/goal_lease.py operations/fleet/fleet/server/peer_motion_wire.py operations/fleet/test/test_uncertain_motion.py
```

`rosy_harness.py generate`는 `operations/fleet/index.md`만 갱신했다. `git diff --check`는 exit 0이며 제품·시험·문서 diff를 검토했다.
`rosy_harness.py lint`는 exit 1(오류 1, 경고 51)이다. 오류는 D-1061 전환 후 `operations/fleet/logs.md` 직접 수정 금지다.
판정 코드 `records_rules.shared_line_edits`는 base~HEAD를 검사하며, `git log origin/main..HEAD -- operations/fleet/logs.md`에서 기존 `22aa6d824c`가 해당 파일을 수정했음을 확인했다.
현재 HEAD에 이미 있는 위반이므로 이 작업에서 이력을 고치지 않았다. pytest 실행·실물 접속·commit/push/amend는 하지 않았다.

## 남은 위험: 늦게 도착한 이동 요청(CORE 기한 없음, 새 계약 필요)

정지 표본이 표지 이후여도, 응답을 잃은 이전 이동 요청이 CORE에 아직 도착하지 않았다면 정지 확인 뒤 실행될 수 있다.
Fleet의 pending·wire version은 관측 가능한 요청 구간을 막지만, 로컬 요청 종료 뒤 네트워크·서버 안에 남은 요청까지 종결시키지는 못한다.
현재 CORE에는 이 이전 이동 요청을 수신 시 거절하도록 보장하는 요청 기한 계약이 없다. goal lease TTL도 수락 이후의 유지 기한이어서 이를 대신하지 않는다.
요청 기한 또는 수신 측 세대 fencing으로 늦은 요청의 실행을 거절하는 새 CORE/Fleet 계약과 독립 안전 검토가 필요하다.
이번 변경은 cancel 응답의 잘못된 해제만 없앴으며 이 위험을 해결했다고 주장하지 않는다.

## 남은 위험·후속

수정 후 독립 재검토와 작성 시험의 원격 실행이 남았다. 실물 정지·장치 배포·DEVICE/FIELD 수용은 확인하지 않았다.
측정 정지 해제는 CORE의 속도 표본 시각과 Fleet의 `time.time()` 표지를 비교한다. `after < stamp <= now`와 `now - stamp < STALE_POSE_S`(2초)를 만족하면 이 범위 안의 시계 어긋남도 통과할 수 있다. 이는 시계 동기화나 인과 순서를 보장하지 않는다.
표지 이후 속도 표본이 없거나 시각 경계를 벗어나면 보수적으로 계속 보류한다. GET 직전의 표본도 표지 이후이고 신선하면 인정한다.
불확실 로봇에는 snapshot마다 직접 REST 읽기가 추가된다. 도달 불가·관측 중 pending·새 wire가 계속되면 불확실성은 유지된다.
이전 프로세스의 불확실성은 기존처럼 메모리에만 남으며 재시작 영속화는 이번 범위가 아니다. 자동 replay·재출발은 추가하지 않았다.
사람이 D-430 독립 안전 검토 후 `Safety-Review:` trailer로 커밋한다. 이 작업에서는 commit/push/stash/reset·실물 접속을 하지 않았다.

## D-1079 — 이동 수락 기한과 불확실 표시 해제

기준 HEAD는 `b053a0413d`(`fix/fleet-uncertain-motion`)이며, 독립 D-430 검토 4회차 APPROVE·5회차(변경분 e496ca632d..b053a0413d) APPROVE와 원격 시험(모델 PC·AI PC: CORE 630 passed, Fleet 546 passed, `known_failures` 0 new)을 거친 뒤 4회차 검토의 비차단 지적 2건을 미커밋으로 추가 반영했다.
설계 방향은 장원종 승인, ADR Status는 요청대로 **Proposed**다. 위 절의 과거 lint 오류·기한 없음 설명은 당시 기록으로 보존한다.

CORE는 HTTP 라우트 진입 단조 시각을 본문 파싱·의존성·동기 threadpool 진입 전에 보관한다(`navigation.py:38–46`).
각 이동 핸들러 첫 줄에서 그 값을 읽어 전달한다. 위치 추정·지도 격자·nav 락을 기다린 시간도 기한에 포함한다.
`NavigationManager.goal`의 실제 수락 락 안 `manager.py:284,287`에서 handoff 검사 전·후에 검사하며,
초과 시 `goal_contract.py:32–35`가 `NavigationError(MOTION_ADMIT_DEADLINE_EXCEEDED)`를 낸다.
`api/errors.py:50`이 기존 ERR-101 응답의 HTTP 409로 매핑한다. native admission(`manager.py:291`)과 backend 전송 전이다.
기존 필드 없는 내부 호출과 수락된 route의 다음 구간에는 새 기한을 부과하지 않는다.

### 이동 시작 경로 전수 확인과 적용

모든 경로의 접두사는 `/api/v1`이다. API navigation 라우터의 모든 POST 및 API에서 `nav.goal/home/route`를 부르는 실제 진입점을 확인했다.

| 메서드·경로 | 모델/핸들러 위치 (`middleware/core/api/core_api_web/api/v1/navigation.py`) | 적용 |
|---|---|---|
| POST `/navigation/goal` | GoalRequest, `navigation_goal:130` | 수신→실제 goal admission 기한 |
| POST `/navigation/bound-goal` | BoundGoalRequest, `bound_navigation_goal:137` | 같은 기한, plan/grid·기존 무수락 오류 detail 유지 |
| POST `/navigation/line-handoff-goal` | LineHandoffGoalRequest, `line_handoff_navigation_goal:161` | 같은 기한, handoff 소비 전 검사 및 소비 후 재검사 |
| POST `/navigation/home` | HomeRequest, `navigation_home:431` | home→goal 공통 admission에 전달, 본문 없는 호출 유지 |
| POST `/navigation/route` | RouteRequest, `navigation_route:326` | 최초 route→goal admission에 전달 |
| POST `/navigation/bound-route` | BoundRouteRequest, `bound_navigation_route:334` | 최초 route→goal admission에 전달 |
| POST `/navigation/bound-plan` | BoundPlanRequest, `prepare_bound_path:144` | 필드는 상속하지만 이동 시작 없음. 실행 요청에 별도 기한 필요 |
| POST `/navigation/goal/lease` | GoalLeaseRequest | 기존 run 임대 갱신이며 새 이동 수락 아님 |
| POST `/navigation/cancel`, `/navigation/cancel-scoped`, `/navigation/handover` | 기존 모델/핸들러 | 새 이동 시작 아님, 기존 동작 유지 |

Fleet `motion_ingress`의 이동 시작/유지 전체 목록도 대조했다. 아래는 여섯 navigation 시작과 다른 owner 경로다.
`navigation.admit_deadline`이 있어도 이 경로에는 기한을 싣지 않으며 불확실 표지는 None으로 남아 자동 해제하지 않는다.

| 경로 | 실제 역할·이번 적용 |
|---|---|
| POST `/swarm/follow` | moving session/follow owner 시작, 기한 미지원 |
| POST `/motion/rotate_to`, `/motion/repark`, `/motion/repark/run` | precision mission/repark owner 시작, 기한 미지원 |
| POST `/motion/nudge` | 기존 ingress의 보수적 분류 항목이며 현재 v1 API 라우트 정의는 없음, 미지원 |
| POST `/localization/mission` | localization mission owner 시작, 기한 미지원 |
| POST `/docking/dock`, `/docking/undock` | docking owner 시작, 기한 미지원 |
| POST `/docking/station-dock`, `/docking/station-undock` | station owner의 start_docking/start_departure, 기한 미지원 |
| PUT `/docking/station-return`, `/docking/station-departure` | station grant_return/renew_departure 허가, 기한 미지원 |
| PUT `/line-follow/mode` (OFF 제외) | line-follow owner 시작, 기한 미지원 |
| POST `/line-follow/junction`, `/line-follow/authority` | 이후 움직임 지시·허가, 기한 미지원 |
| POST `/line-follow/hold` | 정지 경로이나 ingress가 보수적으로 이동 유지로 분류, 기존 분류 유지 |
| POST `/line-follow/stuck/decision` (WAIT/ABORT 제외) | 재개·복구·MANUAL 권한 변경, 기한 미지원 |
| POST `/mode` (IDLE/EMERGENCY 제외), `/teleop` (0/0 제외) | 제어 모드·수동 속도, 기한 미지원 |

`/slam/{start,stop,save,reset}`·`/localization/initialpose`는 이 navigation 라우터의 이동 목표 시작 API가 아니다.
목표 임대 갱신도 새 요청 수락 기한을 만들지 않는다. 준비된 목표의 기존 custody 전용 실패 처리와 전역 차단은 유지한다.

### capability·기본값·해제 경계·세대 fence 보충

- 이름: `navigation.admit_deadline: true`, `navigation.generation_fence: true` (`system.py:196-197`). 주행 runtime readiness나 다른 이동 API의 지원을 뜻하지 않는다.
- 모델: 공통 MotionAdmitRequest의 `admit_within_s: float | None`, 유한한 `0 < s <= 10`; 생략/null은 기존 동작. `NavigationCancelRequest`의 선택 `advance_generation: bool = False` (`navigation.py:399-400`).
- CORE 무동작 세대 fence: `POST /api/v1/navigation/cancel`에 `{"advance_generation": true}`를 주면 `NavigationManager.cancel(..., advance_generation=True)`(`manager.py:479,505-507`)가 `nav._lock` 안에서 이미 IDLE/종료 상태(`_nav_state in _IDLE_STATES`, `_admitting is None`, `session is None`)여도 이동이나 `nav.canceled` 이벤트 없이 `self.native.generation`을 1 올리고 응답 `owner`에 갱신된 `{boot_id, owner_generation, owner_run_id}`를 돌려준다.
- Fleet `boot_id` 귀속과 세대 전송: `HttpRobotClient.capabilities()`(`transport.py:242-250`)는 `navigation.admit_deadline is True`와 `navigation.generation_fence is True`가 **둘 다** 성립할 때만 `/api/v1/navigation/state`를 읽어 `owner.boot_id`·`owner.owner_generation`에 capability를 묶는다. 여섯 시작 요청 전송 시(`transport.py:160-187`) 본문에 `expected_boot_id`·`expected_owner_generation`이 **둘 다** 있고 두 capability가 모두 true일 때만 `admit_within_s=3.0`을 붙인다. 세대 갱신이 실패하거나 둘 중 하나라도 없으면 `admit_within_s`를 붙이지 않고 unbounded로 보내며, `boot_id` 변경이 관측되면 capability를 즉시 초기화한다.
- 총 전송 timeout과 세대 fence: bounded 요청에는 httpx의 단계별 timeout 외에 `asyncio.wait_for`로 실제 클라이언트의 총 timeout(기본 5초)을 적용한다. 라우트 진입 전 네트워크·커널 버퍼에 지연된 요청은 해제 전에 확정하는 세대 fence가 `409 OWNER_GENERATION_CHANGED`로 차단한다.
- 여유 상수 근거: 기존 5초 transport 예산에서 응답에 2초를 남기려는 기본 정책(`admit_within_s=3.0`)과 `MOTION_RELEASE_MARGIN_S=0.5`(`motion_ingress.py:18`)는 설계 기본값이며 **실측값이 아니다(실물 측정 필요)**.
- 표지: 실제 보낸 payload의 `admit_within_s`, `expected_boot_id`, `expected_owner_generation`만 읽어 `sent_at`, `timeout_s`, `admit_within_s`, `release_after`, `boot_id`, `owner_generation`, `fenced_generation`, `fenced_at`, `fenced_wall_time`을 저장한다(`uncertain_motion.py:55-113`, client 캐시 fallback 없음). 표지의 기존 `since`, `wall_time`, wire version, motion epoch는 유지한다. 앞선 무기한 요청이나 더 긴 해제 경계, 다른 `boot_id`와의 충돌은 뒤의 짧은 요청으로 사라지지 않는다.
- 해제: 기존 정지 증거에 더해 조회 시작이 `sent_at + timeout_s + admit_within_s + 0.5` 이상이어야 한다(기본 8.5초, 끝나는 시각만 경계를 넘긴 조회는 불가). 또한 정지 증거를 읽기 **전에** `_verify_uncertain_release_fence`(`uncertain_motion.py:114-164`)가 참고용 사전 조회(`/api/v1/navigation/state`)로 `owner.boot_id`가 표지 `boot_id`와 일치하는지 확인하고(다르면 해제 거절 및 capability 초기화), 불확실 로봇은 `navigation`이 비활성(`STOPPED_NAVIGATION = {"IDLE", "ARRIVED", "CANCELED", "FAILED"}`, `named_stop_motion.py:20` 정지 상태 집합 재사용)일 때만 `POST /api/v1/navigation/cancel`(`{"advance_generation": true}`)을 보내 응답 자체의 `owner.owner_generation`으로 같은 `boot_id`에서 `fenced_generation`을 먼저 전진·확정한 뒤, 그 fence 확정 시각 **이후**의 정지 표본과 비활성 `navigation` 및 동일한 `fenced_generation` 유지가 재확인될 때만 해제한다(`uncertain_motion.py:197-215`, `goal_lease.py:308-333`). 사전 조회에서 `navigation`이 활성이면 fence하지 않고 표시를 유지하며, `TypeError`나 응답 `owner` 부재 시 plain cancel+GET으로 넘어가지 않고 `False`(fence 실패)로 처리한다.
- None: `기한 없는 CORE라 해제 불가 (or motion without admission deadline)`를 기존 logger에 남긴다. 새 Fleet API·응답 필드는 없다.

### 변경 파일과 D-430 safety 해당 여부

매니페스트 `safety_modules`·`safety_anchors`와 변경 경로를 직접 대조했다. 아래 다섯 파일이 해당한다. `concern: safety` root에 별도로 해당하는 이번 변경은 없다.

| 파일 | safety | 변경 |
|---|---|---|
| `operations/fleet/fleet/server/goal_lease.py` | **예**, anchor GoalLeases | exact custody 정산 전·후 세대/boot fence 확인 및 `uncertain_motion.py` 분리 |
| `operations/fleet/fleet/server/peer_motion_wire.py` | **예**, anchor PeerMotionWire.motion_wire | `UncertainMotion` 상속 및 wire epoch 추적 |
| `operations/fleet/fleet/server/uncertain_motion.py` | **예**, GoalLeases 상위 mixin | 실제 보낸 payload 기반 불확실 표시 생성, 비활성 nav 사전 확인 후에만 선행 세대 fence 전진 및 응답 `owner` 필수 검증, 정지 관측 전·후 동일 `boot_id`·세대 재확인 |
| `operations/fleet/fleet/server/named_stop_motion.py` | **예**, anchor NamedStopMotion | `STOPPED_NAVIGATION` 정지 상태 집합 정의 및 `measured_stop_proof`·`uncertain_motion` 공유 |
| `operations/fleet/fleet/swarm/motion_ingress.py` | **예**, anchor starts_or_sustains_motion을 포함한 파일 전체 | 지원 경로·기본 timeout/기한/여유 상수(`MOTION_RELEASE_MARGIN_S=0.5`, 실물 측정 필요 주석) |
| `operations/fleet/fleet/swarm/navigation_transport.py` | **예**, anchor NavigationTransport | `navigation_cancel(advance_generation=...)` 선택 본문 전달 |
| `operations/fleet/fleet/swarm/transport.py` | 아니오 | 두 capability(`admit_deadline`·`generation_fence`) 동시 확인·`boot_id` 귀속·owner epoch 완비 시에만 기한 주입·총 5초 timeout |
| `middleware/core/api/core_api_web/api/v1/navigation.py` | 아니오 | 모델 필드·라우트 수신 시각·기한 전달·`/navigation/cancel`의 `advance_generation` 선택 플래그와 `owner` 반환 |
| `middleware/core/api/core_api_web/api/v1/system.py` | 아니오 | `navigation.admit_deadline` 및 `navigation.generation_fence` capability 노출 |
| `middleware/core/api/core_api_web/api/errors.py` | 아니오 | 새 오류의 409 매핑 |
| `middleware/drive/behaviors/navigation/goal_contract.py` | 아니오 | 실제 단조 기한 검사 |
| `middleware/drive/behaviors/navigation/manager.py` | 아니오 | nav admission 락 안 기한 검사·home 전달·`cancel(advance_generation=True)` 무동작 세대 증가 |
| `middleware/drive/behaviors/navigation/route.py` | 아니오 | 최초 route admission으로 전달 |
| `middleware/core/gateway/test/test_motion_admit_deadline.py` | 시험, 새 파일 | 여섯 시작 경로 전체의 localization·nav 락 대기, 의존성 대기, 무동작 세대 fence 및 옛 세대 `OWNER_GENERATION_CHANGED` 거절, 모델·capability 회귀 |
| `middleware/core/gateway/test/test_navigation_plan_api.py` | 시험 | bound-goal·line-handoff 기한 초과 회귀 |
| `operations/fleet/test/test_motion_admit_transport.py` | 시험, 새 파일 | 두 capability 동시 협상·`boot_id` 귀속 및 변경 리셋·세대 갱신 실패 시 unbounded 유지·실패 메타데이터 |
| `operations/fleet/test/test_uncertain_motion.py` | 시험 | 기존 증거 규칙 유지, 8.5초 경계·구형 CORE·caps True 뒤 옛 CORE/boot 변경 미해제·비활성 nav일 때만 선행 세대 fence 전송(활성 nav는 cancel 미전송·표시 유지)·cancel 응답 `owner` 부재/`TypeError` 시 fence 실패·정지 표본 뒤 늦은 수락(gen 증가) 미해제 |
| `docs/adr/D-1079-motion-admit-deadline-and-uncertain-motion-release.md` | 문서, 새 파일 | Proposed, 승인자·이유·보충 세대 fence·`MOTION_RELEASE_MARGIN_S=0.5` 실물 측정 필요 명시 |
| `docs/reference/api-changes/motion-admit-deadline-d1079.md` | 문서 조각, 새 파일 | CORE 필드·409·capability·무동작 세대 fence |
| `docs/reference/api-changes/uncertain-motion-admit-release-d1079.md` | 문서 조각, 새 파일 | Fleet `boot_id` 귀속·선행 세대 fence 해제 경계 |
| `operations/fleet/logs/2026/11/27-d-1079.md` | Log 조각, 새 파일 | fleet 기록 |
| `middleware/core/gateway/logs/2026/11/27-d-1079-navigation.md` | Log 조각, 새 파일 | core 기록 |
| `middleware/core/api/logs/2026/11/27-d-1079-navigation-capability.md` | Log 조각, 새 파일 | core_api_web 기록 |
| 이 `result.md` | 검증 문서 | D-1079 절 및 안전 검토 보완 기록 |

CORE의 새 수락 검사와 세대 fence는 위 매니페스트의 기존 safety 태그에는 없지만 독립 검토 범위에 함께 넣었다.
독립 D-430 검토 4회차에서 **APPROVE**를 받았으며, 비차단 지적 2건(비활성 nav일 때만 fence 전송, cancel 응답 `owner` 필수)을 반영했다. 사람이 최종 변경을 검토한 뒤 `Safety-Review:` trailer를 넣는다.

### 실행한 확인과 원격 회귀 결과

원격 시험(모델 PC·AI PC)과 독립 안전 검토 현황(`b053a0413d` 기준):

- 원격 시험(모델 PC·AI PC): **CORE 630 passed, Fleet 546 passed, `known_failures` 0 new** (`b053a0413d`).
- 독립 D-430 안전 검토: **4회차 APPROVE**. 4회차의 비차단 지적 2건(`uncertain_motion.py`에서 사전 조회 `navigation`이 비활성일 때만 `cancel(advance_generation=True)` 전송, `TypeError`·응답 `owner` 부재 시 plain cancel+GET 대신 `False` 처리)을 이번 5차 수정에서 반영했다(5차 로컬 수정에서는 사용자 규칙에 따라 로컬 pytest를 실행하지 않았다).

로컬 문법·import·lint 확인에는 저장소 공용 가상환경 `/home/jeongmin/Desktop/rosy-platform/.venv/bin/python`을 사용했다.

- py_compile: 수정·신규 Python 모두 exit 0. `PYTHONPYCACHEPREFIX=/tmp/rosy-fleet-d1079-pycache`에 출력했다.
- import: source PYTHONPATH와 `PYTHONDONTWRITEBYTECODE=1`로 CORE navigation 라우트·모든 요청 모델·system capabilities·NavigationManager 및 Fleet HttpRobotClient·GoalLeases import exit 0.
- 전체 `core_api_web.api.app.create_app` import도 시도했으나 기존 환경의 `cryptography` 미설치로 `account_receiver → account_client`에서 실패했다. 의존성을 설치하거나 stub으로 우회하지 않았다. 전체 앱 import 통과를 주장하지 않는다.
- `git diff --check`: exit 0. LF→CRLF 정규화 예고만 있으며 공백 오류는 없다. 제품·시험·조각·ADR diff를 직접 읽었다.
- `tools/harness/rosy_harness.py lint`: **exit 0, 오류 0·경고 52**. 추가 경고는 기록 봇이 넣을 D-1079 ADR Log 행이다.

작성한 시험은 위 네 파일이다. CORE는 여섯 시작 경로(`goal`, `bound-goal`, `line-handoff-goal`, `home`, `route`, `bound-route`) 전체의 기한 내·같은 경계·초과(409와 전송 없음)·생략, localization/nav 락·서비스 의존성 대기, 무동작 세대 fence(`advance_generation=True` 후 여섯 경로 모두 옛 세대 시작 `409 OWNER_GENERATION_CHANGED` 거절), 입력 상한·유한성, capability를 다룬다. Fleet은 여섯 지원 경로의 두 capability(`admit_deadline`·`generation_fence`) 동시 협상과 bound-plan 제외, `boot_id` 귀속과 boot 변경 시 capability 해제, 세대 갱신 실패 시 기한 미부착·unbounded 유지, timeout/취소/서버 오류의 원래 전송 시각·예산, 해제 경계 직전·같음·직후, 경계 전에 시작해 이후 끝난 조회 거절, caps True 상태에서 필드를 무시하는 옛 CORE 및 boot 변경 시 미해제, 비활성 nav일 때만 선행 세대 fence 전진 확인(활성 nav는 cancel 미전송·표시 유지), cancel 응답 `owner` 부재 및 `TypeError` 시 외부 세대 증가 미인정, 정지 표본 직후 늦은 수락(세대 증가) 시 미해제를 다룬다.

### 남은 위험과 인계

로봇 CORE 배포·capability 확인 전에는 표시를 해제할 수 없다(지금 main과 같은 보수적 동작). 다른 이동 owner도 기한을 지원하지 않아 보류한다. 로봇 CORE 배포와 실물 DEVICE/FIELD 수용은 남았다.

`MOTION_RELEASE_MARGIN_S=0.5`(`motion_ingress.py:18`)는 실측값이 아니므로 현장 네트워크·로봇 환경에서 실물 측정이 필요하다(실물 측정 필요). 라우트 진입 전에 중간 프록시나 수신 커널 버퍼에 지연된 바이트는 정지 관측 전에 먼저 확정하는 CORE의 무동작 세대 fence(`POST /api/v1/navigation/cancel` `advance_generation=True`)와 시작 요청의 `expected_boot_id`·`expected_owner_generation` 검사(`409 OWNER_GENERATION_CHANGED`)가 차단한다.

기존 속도 표본의 wall clock 오차와 인과성, 메모리 표지의 Fleet 재시작 영속화 한계도 유지된다. 새 목표 재전송·작업 자동 재출발·래치 해제는 추가하지 않았다.

`logs.md`·API 참조 본문·CONTRACT·ADR Log 행·생성 index는 직접 고치지 않았다. 기록은 `new_record.py log`(fleet/core/core_api_web)·`new_record.py api`(core/fleet)로 만들었다. ADR 번호 재선점, commit/push/amend/stash/reset은 하지 않았다.
