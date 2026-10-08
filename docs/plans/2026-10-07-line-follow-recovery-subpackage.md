# line_follow 차선 복구 하위 패키지 분리 계획

**날짜:** 2026-10-07
**상태:** 완료 (2026-10-07, 브랜치 `refactor/line-follow-recovery-subpackage`. 이동 d37bc0883, 크기 판정 f50b33fb6는 독립 검토를 거쳤다)
**이유:** `core_features` 크기 판정(14449, D-476 rev 1)에는 조건이 붙어 있다. 다음 재판정 전에 이 분리 계획이 있어야 한다. 브랜치 `feat/d491-core-junction-action`의 D-494 4항·D-495 교차로 동작(`line_follow/junction.py`)이 그 다음 재판정을 부른다.

## 무엇을 옮기나

`core_features/line_follow/`의 차선 복구 모듈을 새 하위 패키지 `core_features/line_follow/recovery/`로 옮긴다. 모듈은 다음과 같다.

| 지금 | 옮긴 뒤 |
|------|---------|
| `lane_return.py`, `lane_return_approach.py`, `lane_return_decision.py`, `lane_return_evidence.py`, `lane_return_wiring.py` | `recovery/lane_return*.py` |
| `lane_bridge.py` | `recovery/lane_bridge.py` |
| `stuck_recovery.py`, `stuck_wiring.py` | `recovery/stuck_*.py` |
| `junction.py` | `recovery/junction.py` |

`junction.py`도 `recovery`에 둔다. 교차로 동작은 정상 추종 바깥의 한정된 동작이고, D-468 근거(PoseTrail, 동작 확인)와 D-407 stuck과 같은 매니저 결정 경로를 공유한다. 그래서 같은 하위 패키지가 맞다. 이름을 `actions`로 넓히지 않는다.

다음은 그대로 둔다. `manager.py`, `model.py`, `body_stop.py`, `clearance.py`, `__init__.py`다. 이유는 둘이다. 추종 정책과 D-422 안전 경로(`concern: safety`, D-430)가 여기 있다. 그리고 모든 믹스인을 묶는 매니저가 여기 있다.

## 지키는 것

- **매니저 잠금 하나와 generation 하나.** 하위 패키지는 지금처럼 `LineFollowManager`의 믹스인으로만 쓰인다. 자기 잠금, 스레드, 저장소, 발행자를 두지 않는다.
- **최종 발행자.** 최종 `cmd_vel` 발행자는 그대로 CORE CommandManager다(D-2, D-18).
- **외부 계약.** API, 스냅숏, 설정 키, 이벤트 이름을 바꾸지 않는다. `core_features.line_follow`의 공개 이름(`LineFollowManager`, `LineFollowConfig`, `LineFollowMode`, `LineObservation`)도 그대로다.
- **import 호환.** 옮긴 모듈의 옛 경로를 쓰는 곳(시험, `core.bridge`, `core_api_web.api.deps`의 `JunctionRefused`·`LineStuckRefused`)은 같은 변경에서 새 경로로 고친다. 재수출 shim은 두지 않는다.

## 크기 판정

- `test/architecture/test_module_structure.py`의 `SIZE_UNITS`가 `core_features/line_follow/recovery`를 별도 단위로 센다. `tools/harness`는 크기를 세지 않으므로 고치지 않는다. 그 단위에 자기 크기 판정을 준다. 판정 기준선은 옮긴 시점의 줄 수에 +150이다.
- `core_features`의 판정은 옮긴 줄 수만큼 낮춘다. 옮긴 뒤 `core_features`는 12772줄이고 `recovery`는 2320줄이다.

## 순서와 검증

1. 파일을 이동한다(`git mv`). import를 고친다. 동작 변경은 없다.
2. `line_follow` 시험을 돌린다. `test_line_follow*.py`, `test_lane_return*.py`, `test_lane_bridge.py`, `test_line_stuck_recovery.py`, `test_line_junction*.py`다. 그 다음 gateway 전체와 `test/architecture`를 돌린다. `test/known_failures.py`가 0 new여야 한다.
3. 크기 판정을 두 단위로 나눈 것을 독립 검토한다.

## 착지 순서

D-495 교차로 동작 브랜치가 main에 들어간 뒤에 한다. 같은 시기에 열린 다른 line_follow 브랜치와 충돌하지 않도록, 그 브랜치들이 들어간 다음 짧은 단독 브랜치(`refactor/line-follow-recovery-subpackage`)로 한다.

## 후속 (2026-10-08): 교차로 코드를 `recovery/junction/` 하위 패키지로

**이유.** `recovery` 크기 판정(2987, 3038에서 재판정)의 조건이다. 교차로 코드(gate 530, approach 207, bend 208 = 945줄)는 이 분리 전에는 늘 수 없다. 다음 교차로 변경은 lap SIM(`docs/validation/lane-trip-lap-sim-2026-10-08`) 원인 A의 굽이→교차로 넘겨주기다.

| 지금 | 옮긴 뒤 |
|------|---------|
| `recovery/junction.py` | `recovery/junction/gate.py` |
| `recovery/junction_approach.py` | `recovery/junction/approach.py` |
| `recovery/junction_bend.py` | `recovery/junction/bend.py` |

- `git mv`만 한다. 동작, API, 설정 키, 이벤트 이름은 바꾸지 않는다. 재수출 shim은 두지 않는다. `junction/__init__.py`는 설명 문자열뿐이다.
- import는 같은 변경에서 고친다: `line_follow/manager.py`, `core_api_web/api/deps.py`, 시험 `test_line_junction.py`, `test_junction_approach.py`, `test_junction_bend.py`, Fleet `test_trip_runner.py`(CORE 기동 상태 목록 대조).
- `motion_admit.py`는 `recovery`에 남는다. `lane_bridge`와 `lane_return_decision`도 쓴다.
- 지키는 것은 위와 같다. 교차로 믹스인은 그대로 `LineFollowManager`의 믹스인이고 매니저 잠금 하나와 generation 하나를 쓴다. 최종 발행자는 CORE CommandManager다.
- 크기: `SIZE_UNITS`에 `core_features/line_follow/recovery/junction`을 더하고 파일은 가장 안쪽 단위로 센다. 옮긴 뒤 `recovery` 2093, `junction` 947(`__init__.py` 2줄 포함). 두 판정은 독립 재판정을 받는다.
- 독립 검토: critic 에이전트(읽기 전용) 2026-10-08 승인(APPROVE WITH CHANGES, 요구 문구 반영). recovery 2093, junction 947.
- 검증: `test_line_junction.py`, `test_junction_approach.py`, `test_junction_bend.py`, `test_junction_turn_site_basis.py`, gateway `test_line_junction_api.py`, `test_line_follow*.py`, Fleet `test_trip_runner.py`, `test/architecture`. `test/known_failures.py`가 새 실패 0이어야 한다.
