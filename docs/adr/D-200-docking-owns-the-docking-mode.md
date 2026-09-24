## D-200 도킹은 DOCKING 모드와 전용 명령 슬롯을 쥔다 — 모든 도크 기종이 처음부터 끝까지 DOCKING에서 움직인다

**Status:** Accepted (2026-09-24). 이미 main에 구현돼 있고, 독립 리뷰가 APPROVED 했다. 이 ADR은 구현된 것을 기록한다.
잇는 결정:

- D-2: CORE의 cmd_vel 다중화기가 유일한 최종 `/cmd_vel` 발행자다.
- DNC-002·DNC-003: 도킹 우선순위와 도킹 API.
- 설계: [2026-09-23-lane-network-parking-design.md](../plans/2026-09-23-lane-network-parking-design.md) §4 "동작 모드".

**Context:**

1. **기본 기종의 도킹 주행은 우연히 바퀴에 닿았다.** 도킹 주행은 nav 슬롯을 썼다. 그 슬롯은 `NAVIGATION` 모드에서만
   바퀴에 닿으므로, 기본 기종의 도킹은 로봇이 마침 NAVIGATION일 때만 움직였다. 같은 슬롯을 Nav2 목표와 군집 목표가
   다퉜다.
2. **주차형 도크 기종**(`docking/parking_phases.py`, 기종 정의는 `docking/model.py`)은 오도메트리와 마커로 스퍼를
   주행한다. 차선 추종, Nav2, 군집 어느 것도 그 사이에 바퀴를 잡으면 안 된다.
3. **모드를 떠나는 길이 여럿이다.** API 모드 변경, 라인 추종, e-stop, 도킹 자신의 종료가 있다. 어느 길로 나가도 도킹
   주행이 남아 있으면 안 된다.
4. **사용자 결정 M1(2026-09-24 독립 리뷰):** 주차형만 게이트하지 않고 모든 도크 기종이 DOCKING을 쥔다.

**Decision:**

1. **도킹 전용 슬롯.** `CommandManager.set_docking_twist` / `clear_docking`
   (`src/core/core_features/core_features/command/manager.py`)이 도킹 슬롯을 쓴다. 도킹 슬롯은 `Mode.DOCKING`에서만,
   nav 슬롯은 `Mode.NAVIGATION`에서만 바퀴에 닿는다. e-stop이나 EMERGENCY 중에는 도킹 입력을 버린다.
   bridge의 도킹 실행기(`src/core/core/core/bridge/docking_executor.py`)의 `drive`/`stop`이 도킹 슬롯을 쓴다.
2. **Nav2 출력의 경로.** `route_nav_cmd_vel`(`src/core/core/core/bridge/docking_mode.py`)이 Nav2 `nav_cmd_vel`을 나눈다.
   - 라인 추종이 켜져 있으면 어디에도 쓰지 않는다.
   - `NAVIGATION`이면 nav 슬롯에 쓴다.
   - `DOCKING`이면서 도킹 상태가 `DOCKING`이고 단계가 `STAGING`일 때만 도킹 슬롯에 쓴다.
   - 그 밖(오래된 목표, 군집 목표)은 버린다.
3. **ModeMachine.** `transition(new, expect=)`는 잠금 안에서 확인과 변경만 한다. `expect`를 주면 그 모드에서만 바꾼다.
   `change_listeners`는 잠금을 푼 뒤 `(old, new)`로 불린다. 리스너 예외는 기록만 하고 호출자와 다른 리스너로 번지지
   않는다. `DOCKING → MANUAL`을 허용한다(MANUAL 3이 DOCKING 4보다 우선).
4. **CoreServices의 모드 이음새** (`src/core/core/core/services.py`).
   - `take_docking_mode`: `dock()`/`undock()`이 자기 검증 뒤, 상태나 실행기를 건드리기 전에 부른다.
     IDLE 또는 NAVIGATION에서 DOCKING으로 간다. NAVIGATION은 IDLE을 거친다. 먼저 Nav2 목표와 군집 세션을
     취소한다(`nav.cancel(source="docking")`). 각 단계는 `expect`로 기대한 모드에서만 커밋한다.
     MANUAL과 EMERGENCY는 `MODE_CONFLICT`로 거절하고 상태를 바꾸지 않는다.
   - `release_docking_mode`: 도킹 매니저가 자기 잠금 안에서, 종착 상태 변경과 같은 임계 구역에서 부른다(틱·취소·중단).
     `expect=DOCKING`으로 IDLE로 되돌린다. 이미 DOCKING을 떠났으면 아무것도 하지 않는다.
   - `leave_docking`(모드 리스너): DOCKING을 떠나는 모든 전이가 도킹을 먼저 접는다. EMERGENCY면 중단해
     `DOCK_FAILED`로, 그 밖이면 취소한다. 그리고 도킹 슬롯을 비운다.
5. **e-stop은 모드 리스너보다 먼저 걸린다.** `POST /safety/stop`은 `trigger_estop`으로 잠금을 건 뒤 EMERGENCY로
   전이한다. 리스너가 무엇을 하든 잠금 없는 EMERGENCY가 남지 않게 하려는 순서다.
6. **도킹 중 다른 주행 거절.**
   - Nav2 목표와 군집 이동 목표는 `DOCKING_ACTIVE`로 거절한다(DOCKING 모드이거나 도킹이 진행 중일 때).
   - 배터리 정책의 `RETURN_HOME`은 도킹이 진행 중이면 건너뛴다. 진행 중인 도킹이 곧 귀환이다.
   - 라인 추종 모드 변경(`PUT /line-follow/mode`)은 도킹·언도킹 중 `DOCKING_ACTIVE`로 거절한다.
7. **기능 활성화는 시뮬레이션 전용이다.** `docking.simulation_supported`와 `docking.seed` 오버레이는
   `runtime.mode: simulation`일 때만 읽는다. 장치의 `capabilities.yaml`은 `docking.supported: false` 그대로다.
8. **API 코드**(API & Protocol Reference **v1.20**): 409 `DOCKING_ACTIVE`, `MODE_CONFLICT`, `NO_ODOMETRY`,
   `LINE_FOLLOW_ACTIVE`. v1.20에서 `LINE_FOLLOW_ACTIVE`와 `NO_ODOMETRY`를 새로 만들었고, 내비게이션의
   `DOCKING_ACTIVE`가 400으로 나가던 것을 409로 고쳤다.

**Validation:**

- 시험: `src/core/core/test/test_docking_mode_ownership.py`, `test_docking_mode_release.py`,
  `test_mode_listener_isolation.py`, `test_bridge_docking_executor.py`, `test_docking_parking_wiring.py`,
  `src/core/core_features/test/test_docking_review_fixes.py`, `test_docking_parking.py`,
  `test_docking_parking_manager.py`, `test_docking_parking_phases.py`.
- Gazebo 미션(언도킹 → 전 차선 투어 → 주차) 4/4 통과. 주차 오차 1.4–2.3 mm, 방위 1.7° 이하.
  **25° 세계의 ROS-SIM 증거다. 장치 증거가 아니다**(D-199: 실물 카메라는 약 8°다). DEVICE: NOT RUN.
- 독립 리뷰 APPROVED.

**Consequences:**

- 도킹은 어떤 기종이든 DOCKING에서만 바퀴를 움직인다. Nav2·군집·라인 추종과 슬롯을 다투지 않는다.
- 운영자는 언제든 MANUAL로 도킹을 끊을 수 있다. 그때 도킹은 취소된다.
- 장치에서 도킹은 여전히 꺼져 있다. 켜려면 Pinky 프로필의 도킹 지원 판정과 실기 증거가 필요하다(설계 §7).
- 최종 리뷰가 남긴 후속 과제:
  - (MED) 라인 추종 `PUT`과 `dock()` 사이의 경합
  - 정지와 해제가 겹치면 잠금 없는 EMERGENCY가 남을 수 있다
  - `on_battery_level`이 잠금 없이 돈다
  - `cmd_vel_cycle` 오류 로그 폭주

**References:** 설계 [2026-09-23-lane-network-parking-design.md](../plans/2026-09-23-lane-network-parking-design.md),
[API & Protocol Reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md) v1.20, D-2, D-199.
