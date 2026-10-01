## D-398 CORE 안전 정책은 off · shadow · enforce 세 모드로 켜고, 파라미터는 보정 저장소 하나에서 온다

**Status:** Proposed (2026-10-01, 설계 사용자 승인). 코드·설정 미변경. 장치 단계(그림자 실주행, 집행)는 각각 별도 사용자 승인.

잇는 결정:

- **D-47:** 센서 어댑터 보정 바인딩. 이 ADR은 `enabled: bool`을 `mode`로 바꾸고, 어댑터의 `calib_node` 레코드 경로를 D-47 addendum 저장소로 대체한다.
- **D-397:** URDF NOMINAL < 승인 레코드 < 운영자. 안전 정책 파라미터도 같은 순서를 따른다(D-397 "하지 않은 것" 둘째 항목을 닫는다).
- **D-66:** CORE 이미지 슬라이스. `control` 센서 워커를 포함하도록 개정한다.
- **D-149 / D-208:** 최종 `/cmd_vel` 발행자는 `core` 하나. 이 ADR은 그 원칙을 바꾸지 않는다.

### Context

`control.sensor_adapter`는 어느 로봇에서도 켜져 있지 않고, `rosy_default.yaml`의 "켜기 전까지 정지 상태" 주석과 달리 꺼져 있으면 CORE는 정책 없이 명령을 통과시킨다. 켜려면 1.4 cm/s 봉투, 부팅·끊김 때의 e-stop 래치, 저장소 두 개로 나뉜 보정, 이미지에 없는 워커, Gazebo에 없는 IR이 걸린다. 실기기 오탐을 모른 채 바로 집행하면 래치가 주행을 끊는다.

### Decision

1. **모드 세 개.** `control.sensor_adapter.mode: off | shadow | enforce`(기본 `off`). `enabled: true/false`는 `enforce/off`로 읽고, 둘을 함께 쓰면 거부한다. `shadow`는 판정을 계산·기록하되 출력·e-stop·모드를 바꾸지 않는다. `shadow` 구성 실패는 경고 후 `off`, `enforce` 구성 실패는 시작 거부.
2. **기록.** 그림자 판정은 상태 전이 때 `safety.shadow_verdict` 이벤트, `/robot/state`의 `safety_policy` 카운터, ROS `safety/shadow`(JSON 문자열, 녹화용)로 남는다.
3. **파라미터 출처 하나.** ROS-free 리졸버가 보정 7키(정적 씨앗·URDF NOMINAL < 승인된 D-47 저장소 레코드 < 운영자 overlay)와 봉투 2키(제품 프로필 < overlay)를 만든다. `lidar_yaw_offset`은 `core/lidar_mount.py`와 같은 해석을 쓴다. 봉투는 CORE 속도 상한보다 작을 수 없다. 저장소에 `imu_zero`·`cliff_ir`·`motion_sign` 종류를 더한다. 어댑터는 `calibration.*` 블록을 읽지 않는다.
4. **집행의 센서 끊김.** 첫 판정 전과 `stale_hold_s`(기본 2 s, (0, 5]) 미만 끊김은 HOLD(출력 0, 래치 없음, 자동 재개). 그 이상은 지금처럼 e-stop 래치.
5. **워커 이름** `core_safety_worker`. 레거시 `safety_node`와 겹치지 않는다.
6. **전환 게이트.** G-sim(Gazebo 랩·Nav2 주행에서 무장애 `stop` 0건, `eval_ms` p99 ≤ 10 ms) → G-dev(로봇별 실주행 그림자 30분, 판정마다 원인 분류) → G-enforce(오탐 0, 보정 레코드 승인, 사용자 승인). 집행은 로봇별.

### Consequences

- 기본(`off`) 동작은 바뀌지 않는다. 바뀌는 것은 주석과 상태 표시(`mode`, `off`로 자율주행 진입 시 경고 이벤트)다.
- CORE 이미지가 커진다(`control` 슬라이스). 그림자 평가는 최대 50 Hz로 CPU를 쓴다. 예산을 넘으면 20 Hz로 낮춘다.
- `calib_node` 레코드 형식은 어댑터 경로에서 빠진다. 어느 장치 설정도 그 경로를 켜지 않았다.
- `test_bridge_timers.py` 발행자 고정 목록이 5 → 6.

### Validation

설계와 시험 목록: [2026-10-01 CORE 안전 정책 그림자 설계](../plans/2026-10-01-core-safety-policy-shadow-design.md) 5절. 핵심은 `off`와 `shadow`의 출력이 같은 후보 열에서 비트 단위로 같다는 비간섭 시험이다. 호스트 pytest 통과는 장치·실주행 수용이 아니다.
