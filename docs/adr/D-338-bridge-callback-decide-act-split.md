## D-338 브리지 콜백의 판정은 ROS-free 시블리가 소유한다

**Status:** Accepted (2026-09-24 구현 `24b6d4bb`, 2026-09-29 기록). 게이트웨이 브리지의 소스 구조와 추출 원칙만 결정한다. 분리 기준 문서(2026-09-06, C1)와 D-171의 개선 순서를 대체하지 않으며, 실기에서 콜백이 실제로 돌아가는 증거(ROS-SIM/DEVICE)도 이 ADR의 범위가 아니다.

### Context

`ros_bridge.py`(ROS-101)는 선택적 ROS 의존(rclpy·nav2_msgs·slam_toolbox) 때문에 호스트 pytest가 import조차 할 수 없다. 그 안의 콜백이 값을 정하는 순간, 그 결정은 이 저장소의 모든 시험에서 도달 불능이 되고, 소스 grep 검사만 그 자리를 대신한다 — grep은 잘못된 값에도 통과한다. 그래서 D-171은 개선 순서를 "ROS 경계 → 노드 판단 추출 → 패키지 분리"로 못 박았고, 분리 기준 문서의 C1은 같은 결함을 "호스트 pytest가 읽을 수 없는 자리에 숨은 결정 → ROS-free 시블리 추출"로 판정한다. `translate.py`·`goal_tracker.py`·`display.py`·`reconcile.py`·`odometry.py`·`battery_policy.py`·`cmd_vel.py`·`save_map.py`가 그렇게 태어났다.

그럼에도 2026-09-24 시점에 브리지는 센서·증거 콜백 11곳(line/road/detection/camera/hitl/degraded/nav_twist/nav_path/nav_costmap/us_range/batt_state)에서 파싱·유효성 검사·승인/거부·서비스 라우팅을 여전히 인라인으로 계산하고 있었다. 파일은 757행으로 D-168의 600행 예산을 넘었고, SIZE_VERDICTS는 "2026-09-06 승인 무효, C2 재개"로 기록되어 있었다.

### Decision

1. **콜백을 판정(decide)과 적응(act)으로 나눈다.** 파싱·검증·승인/거부·서비스 라우팅·상태 미러링은 ROS 타입을 import하지 않는 시블리가 소유한다. 브리지 콜백에 남는 것은 노드 시계 읽기, `warn`/logger 주입, 발행·서비스 호출뿐이다. 구조(무엇을 등록하는가)는 `test_bridge_timers.py`가, 값(판정이 옳은가)은 시블리 시험이 각자 검증한다 — grep은 어느 쪽도 아니다.
2. **판정 반쪽은 `bridge/observation.py`에 모은다.** 센서·증거 콜백의 판정은 한 모듈의 함수군으로 둔다. 이미 자기 시블리를 가진 결정은 그 모듈의 함수로 확장한다(`reconcile.led`, `display.republish_due`, `goal_tracker.on_response/on_result`, `save_map.await_call`). 콜백 하나에 파일 하나를 새로 만들지 않는다.
3. **행수는 결과이지 사유가 아니다.** 757 → 590행으로 D-168 예산에 복귀한 것은 추출의 결과이고, 크기 자체는 결코 분리 사유가 되지 않는다(분리 기준 문서). 추출 대상 선정은 오직 C1 — "호스트 pytest가 읽을 수 없고 결정을 숨기는 자리" — 를 따랐다. 그래서 occupancy 판정(`_on_map`)처럼 텍스트 핀이 시블리 이전을 막는 자리는 그대로 브리지에 남아 있다.
4. **시블리 시험의 소유는 D-184가 통제한다.** 시블리은 ROS-free를 유지하고, 시험은 duck-typed 이중(double)로 서비스 호출을 녹음해 값을 단언한다. 실행 패키지(`core_features`·`navigation`·`control`) import는 행동 시험 소유의 동결 예외 목록이 허용할 때만 쓴다.

### Alternatives

- **인라인 유지 + ROS-SIM/DEVICE로만 검증:** 일상 회귀가 환경·시간 제약에 묶여 사실상 불가능하고, 잘못된 값은 실기에서야 발견된다. 기각.
- **콜백마다 신규 시블리 파일:** 역할 하나인 파일만 늘어나 D-168 승격 조건(가족 소유·제2역할·다수 소비자)과 어긋난다. 기각.
- **패키지 분리를 먼저:** D-171 순서 위반. 판정 추출이 먼저고, 패키지 분리는 결함 조건이 성립할 때만 한다. 기각.

### Transition / validation

- `24b6d4bb`(2026-09-24)로 착지: `observation.py` 신설(193행, 판정 함수 11개), 시블리 4종 확장, `test_bridge_observation.py` 신설(+445행)과 시블리 시험 4종 확장, `test_bridge_timers.py` 핀 갱신(구독·발행 블록 실제 줄번호), SIZE_VERDICTS에서 ros_bridge 항목 제거. 13 files, +1047/−237.
- 같은 날 말 DockingExecutor 추출로 582행까지 추가 감소. 이후 `c33f51a6`(감독 카메라 결함 폴백)이 같은 구조 위에서 `observation.py`를 확장(203행) — 원칙이 실제 기능 확장을 견디는 첫 사례다.
- 구현 커밋 시점에 이 ADR과 모듈 저널 기록이 없었다. 이 문서(2026-09-29)가 그 결정 기록을 소급 보존한다.

**Consequences:** 브리지 콜백에 값을 계산하는 코드가 다시 들어오면, 그 값은 호스트 시험에서 검증 불능이라는 것이 이 ADR의 판정 기준이 된다. 새 콜백의 판정은 `observation.py`(센서·증거) 또는 해당 시블리로, 브리지는 등록과 전달만. 행수 예산은 결과 지표로만 읽는다.

**References:** [분리 기준](../plans/2026-09-06-module-split-criteria.md), [D-168 구조 기준](D-168-ros-package-structure-standard.md), [D-171 개선 순서](D-171-control-structural-refactor-order.md), [D-184 행동 시험 소유](D-184-package-owns-its-behavior-tests.md), 구현 `24b6d4bb`·확장 `c33f51a6`.
