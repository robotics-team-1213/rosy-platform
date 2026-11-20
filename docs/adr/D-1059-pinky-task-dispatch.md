## D-1059 Pinky 작업은 Fleet trip으로 한 번만 배차한다

**Status:** Proposed (2026-11-21, 패널 5 조각 3. 안전 경로: robot-08 조정자 Safety-Review 대기. 첫 실물 실행은 사람 입회)

잇는 결정: [D-494](D-494-fleet-trip-execution-m2-contracts.md)(trip 실행·trip_guard) · [D-421](D-421-fleet-cancel-all-driving-separate-from-latched-estop.md)(전체 주행 취소) · [D-1029](D-1029-low-battery-fleet-charge-return.md)(같은 모양의 in-process trip 시작) · [D-1047](D-1047-cell-s-automatic-departure-and-link-failure-clear.md)(셀 S 자동화).

### Context

- `POST /api/fleet/pipeline/pinky-tasks`(S3 도킹+하역 등), `station-zones/dispatch`, `decision-gate`는 `pinky_tasks`에 QUEUED 행만 쓴다. 이 행을 읽어 Pinky를 움직이는 코드가 없었다. 화면은 등록을 실행처럼 보였다(패널 5 합의 1a).
- 이름 있는 장소로 보내는 정본 경로는 Fleet trip이다(robot-7b, named-stop 소유). trip 경로가 지도 자세 LOCALIZED·신선도, CORE trip lease, 지도 버전, 콘솔 동작 충돌, E-stop·취소(`trip_guard`)를 이미 맡는다. 정밀 정차(approach_m, IN_ZONE)도 trip 단계 안에 들어간다.

### Decision

1. 소비자 `pipeline_pinky_dispatch.dispatch_tick`가 파이프라인 1초 루프(`depart_tick` 다음)에서 돈다. 장소 목표가 있는 QUEUED 행마다 `app.state.trip_plan(robot, TripRequest(to=place), 요청자)` → `TripRunner.start(plan_id, 요청자)`를 한 번 부른다. 직접 goal을 보내지 않는다.
2. 한 번만: 계획 전에 SENDING을, 시작 전에 `plan_id`(= trip_id)를 장부에 쓴다. 다음 tick에서 SENDING 행을 만나면(재기동·응답 유실·예외) 다시 계획·시작하지 않는다. trip이 있으면 SENT, 없으면 FAILED `DISPATCH_INTERRUPTED`.
3. SENT = trip 시작 영수증(trip 상태·lease id). ARRIVED·FAILED·CANCELLED는 trip 상태(`arrived`·`failed`·`canceled`)에서만 온다. 타이머로 정하지 않는다.
4. 거절은 끝 상태 REFUSED와 사유이며 아무것도 움직이지 않는다. 사람이 새 작업을 보낸다.
5. 취소: `POST /api/fleet/pipeline/pinky-tasks/{task_id}/cancel`(operator, 정지는 거절하지 않음). QUEUED는 끝내고, 진행 중이면 `TripRunner.cancel`로 trip을 멈춘다. 시작 중에 취소되면 시작 직후 그 trip을 취소한다.
6. `ROSY_FLEET_PINKY_TASK_DISPATCH=1`일 때만 돈다(기본 꺼짐). 배포만으로 주행하지 않는다.

### 가드 목록

| 사유 | 확인 |
|---|---|
| `ACTION_NOT_DISPATCHABLE` | 장소 목표가 없음(미세 이동, stop_now, depart_s3) |
| `REQUESTER_UNKNOWN` | 요청 운영자 신원 없음 |
| `REQUESTER_NOT_NAMED` | 등록 때 요청자가 trip 경로와 같은 가드(`site_auth.build_role_guards`의 `require_operator` → `require_named_operator`)를 통과하지 못함(`requester_named`가 `true`가 아니면, 필드가 없는 옛 행 포함) |
| `REQUEST_STALE` | 등록 뒤 120 s 넘음 |
| `NO_ACTIVE_MAP` · `MAP_VERSION_CHANGED` · `PLACE_NOT_ON_MAP` | 등록 때 지도 버전과 활성 지도가 다르거나 장소가 없음 |
| `ROBOT_UNKNOWN` · `ROBOT_OFFLINE` · `ROBOT_ESTOP` | 콘솔 스냅숏 |
| `DISPATCH_CLOSED` | Fleet dispatch 래치 닫힘(사이트 E-stop, 시작 직후) |
| `CANCEL_ALL_AFTER_REQUEST` | 등록 뒤 D-421 전체 주행 취소 창이 열림 |
| `HUMAN_HOLD` | 사람 감지 또는 셀 HUMAN_HOLD |
| `CELL_HOLD` · `CELL_BUSY` | 목표 셀(S3=cell_s, S5=cell_ab) ABORTED·팔 보류 / `amr_motion_inhibited`·ARM_IN_BED_ZONE·다른 기체 정차·RUNNING 작업 |
| `ROBOT_DISPATCH_IN_FLIGHT` | 같은 기체의 trip이 열려 있거나 이 소비자의 SENDING·SENT 행이 있음 |
| `TRIP_PATH_UNAVAILABLE` · `FLEET_JOURNAL_UNAVAILABLE` | trip runner·lease·작업 장부가 없음 |
| trip 경로 코드(`TRIP_POSE_UNTRUSTED`, `TRIP_BUSY`, `TRIP_MAP_CHANGED`, 배터리 등) | trip 계획·시작이 거절하면 FAILED와 그 코드 |

LOCALIZED·자세 신선도는 trip 계획·시작의 판정을 그대로 쓴다(모터 모드 기체는 MapPose만 LOCALIZED라 콘솔 값으로 따로 판정하면 어긋난다).

### Consequences

- 등록과 주행이 하나의 경로로 이어진다. 자동 출발(`depart_tick`)은 아직 `console.goal`을 직접 쓰며 이 결정의 대상이 아니다.
- 120 s 상한은 사람 의도의 신선도 근사다. 셀 claim이 대기 시간을 가지게 되면 다시 본다.
- 남은 확인: 플래그를 켠 첫 실물 S3 도킹은 사람 입회. 정밀 정차는 robot-7b named-stop 착지 뒤 trip 단계에서 확인한다.
