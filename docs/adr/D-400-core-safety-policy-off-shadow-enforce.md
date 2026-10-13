## D-400 CORE 안전 정책은 off · shadow · enforce 세 모드로 켜고, 파라미터는 보정 저장소 하나에서 온다

**Status:** Proposed (2026-10-01, 설계 사용자 승인; 계획 1 소스 반영 — 기본 off, 어느 로봇에서도 켜지 않음; 그림자 실주행·집행은 로봇별 별도 승인)

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

### Implementation note (plan 1, 2026-10-01)

계획 1(호스트 검증 가능한 그림자 모드)의 구현 요약이다. SOURCE만이고 기본은 `off`다. 그림자는 어느 로봇에서도 켜지 않았다. 상태는 Proposed로 둔다.

**설정과 모드**

- 기본 yaml(`rosy_default.yaml`)은 `mode`를 두지 않는다(주석만, 없으면 off). 값이 있으면 옛 overlay의 `enabled:`와 deep-merge되어 "not both"로 CORE가 시작하지 못한다. `enabled`는 `mode`에서 계산되는 property다. `stale_hold_s`(기본 2 s)를 더했다(reserved: consumed by enforce HOLD in D-400 plan 3; no effect yet).
- 설정 오류는 모든 모드에서 시작을 막는다: 잘못된 `mode`, overlay 키·타입·범위 오류, `shadow` + `control_policy_required`. 설계 3.1의 "그림자 구성 실패 → off"는 **그림자 워커 시작 실패**(센서 공급자, 워커 검증)만 뜻한다. 이 경우 `mode_effective: off`, `mode_error`는 "예외 종류: 메시지"다. 팩토리 인자는 명시적이라 프로그래밍 오류(오타)는 모든 모드에서 TypeError로 드러난다.
- `enforce`는 은퇴한 `calibration.required: true` 블록을 설정 오류("retired")로 거부한다(D-47의 "보정되었거나 시작 거부"를 조용히 잃지 않는다). `shadow`/`off`는 경고 후 무시한다. `configured_mode`도 `calibration` 키를 뺀 뒤 해석한다.

**판정과 기록**

- `SafetyManager.check_decision`(사유 문자열)과 `decision_valid`(bool)를 분리해 `shadow`와 `enforce`가 한 규칙을 쓴다. 그림자는 `disposition`으로 분류하므로 정책의 stop 사유가 `policy_failed`여도 stop으로 센다.
- `ShadowLog`(ROS-free, `core_features/safety/shadow.py`): 락으로 API 스레드 동시 읽기를 막는다. 이벤트는 판정 단위 전이(verdict 키)로 내고, 같은 판정이 명령 중 이어지면 1 s마다 반복하며, 이벤트 사이 최소 0.2 s 간격을 둔다(allow↔limit 50 Hz 흔들림이 EventBus 1000칸을 밀어내지 않게). 간격 때문에 못 낸 변화는 `suppressed`로 센다. `dropped_events`, `suppressed_events` 카운터가 있고, 시계가 거꾸로 가면 첫 기록으로 취급한다. 페이로드 키는 `{verdict, reason, source, t, commanded, output, limited, suppressed}`다. `commanded`는 프로필 클립 뒤 값, `t`는 CORE monotonic 초다.
- 그림자와 집행 바인딩은 상호 배타다(`bind_policy`에서 검사, 그림자 이중 바인딩 거부). `shadow_evaluate`는 어떤 예외도 밖으로 내지 않고 `shadow_record_errors`로 센다.
- **그림자 평가는 `CommandManager.announce_pending`에서 바퀴 출력 뒤에 한다.** `_policy_output`은 후보만 저장한다. 정책 평가 비용이 출력 지연이 되지 않는 더 강한 비간섭 형태다. `announce_pending`은 워치독 알림을 먼저 내고 각 발행을 따로 보호한다(`announce_errors`).
- `policy_off` 이벤트는 `navigation`과 `docking` 출처에서, 모드 진입마다 재무장되어 첫 0 아닌 출력에서 한 번 낸다. 라인 추종은 `policy_required` 없이 시작하지 않으므로 해당 없다.

**파라미터와 워커**

- `safety_params.py` 리졸버: LiDAR 각은 line_follow 값, 봉투는 CORE 속도 상한((선속, 각속) 쌍), overlay 허용 키는 워커 기본값 여섯 키 + 봉투 두 키 + `cliff_enable`(Gazebo는 IR이 없다) + `lidar_use_tf`. 워커의 선언 타입·상한(선속 (0,1], 각속 (0,3])을 검사하고, 프로필 상한이 이 범위를 넘으면 shadow/enforce 시작을 거부한다(Pinky 0.2/0.8은 해당 없음). revision은 파라미터만으로 계산한다. `enforce`도 봉투와 LiDAR 각을 받는다.
- 워커는 `lidar_use_tf`(기본 True)인 동안 `lidar_yaw_offset`을 쓰지 않고 TF(= URDF NOMINAL 180°)를 쓴다. `sources`에 "unused while lidar_use_tf"로 적었다. 라인 추종(승인 레코드)과 안전 정책(TF)의 LiDAR 정면을 하나로 만드는 일(TF를 승인 레코드로 다듬거나 워커가 값을 쓰게 하기)은 계획 2에서 Gazebo의 TF 존재를 확인한 뒤 한다.
- 새 저장소 레코드 종류(`imu_zero`, `cliff_ir`, `motion_sign`)는 계획 3이다. 그때까지 여섯 키는 워커 기본값이다.

**상태와 API**

- `StateSnapshot.safety_policy`(`SafetyPolicyStatus`)와 `StateManager.set_safety_policy_provider`. API v1.71(main이 v1.70이라 +1). `mode`·`mode_effective`·판정 값은 소문자 평문 문자열(설정 값과 같음, Enum 아님)로, 캐싱 규칙의 예외로 문서화했다. `last_stop`·`eval_ms`는 타입 모델이고 여분 키는 무시한다. 공급자 실패는 null이며 예외 종류가 바뀔 때 한 번 로그한다. 오래된 Fleet hub가 새 값 때문에 heartbeat 전체를 버리지 않게 하려는 것이다.
- `node.py` 조립 순서: LiDAR 해석 → 안전 파라미터 → 어댑터 → 바인딩 → 상태 공급자.

**해석 주의와 한계**

- 속도 맹목: 봉투를 올리면 빠른 명령이 정책에 닿지만 워커의 정지/해제 거리는 속도에 비례하지 않는다. 속도에서의 그림자 `allow`는 그 속도로 집행해도 안전하다는 증거가 아니다. G-sim·G-dev 판정 기준에 반영한다.
- enforce는 CORE 속도 상한 봉투(Pinky 0.2 m/s·0.8 rad/s, 이전 워커 기본 0.014/0.10의 약 14배)를 받는다. 워커의 정지/해제 거리는 속도에 비례하지 않으므로, 계획 3이 정지 거리를 속도에 맞추거나 enforce용 봉투를 되돌리기 전에는 enforce를 켜지 않는다.
- `control_sensor_adapter.py`에 죽은 D-47 로더 경로가 남아 있다(`_load_required_calibration`, `calibration_loader`, `calibration_revision`/digest, `bound_parameters`, `lidar_mount` `adapter_parameters`). `api/v1/line_follow.py`의 `calibration_revision` 의존(D-313)과 함께 지운다. 되살리지 않는다.
- **D-313 IR 라인 추종 대체 경로는 계획 3까지 쓸 수 없다.** `api/v1/line_follow.py`가 `adapter.calibration_revision`을 요구하는데 어댑터가 보정 블록을 더 이상 읽지 않아 항상 None이고 `IR_FALLBACK_NOT_READY`가 된다. 어느 로봇도 어댑터를 켜지 않아 현장 영향은 없다. 계획 3의 저장소 레코드가 이 값을 대신해야 한다.
- 남은 LOW 항목(Task 5 리뷰): 준비 상태 경합으로 한 tick 동안 브리지가 0으로 만든 후보에 대해 그림자 판정이나 `policy_off`가 기록될 수 있다(감사 기록에만 영향, 출력은 그대로). 후보 슬롯은 위치 기반 튜플이다.
- 호스트 pytest 통과는 장치·ARM64 이미지·실주행 수용이 아니다. G-sim, G-dev, G-enforce는 모두 열려 있다.

### 개정 (2026-10-14): 4항 집행 HOLD 구현, 답 시간 상한

4항은 계획 1에서 `stale_hold_s` 키만 두고 쓰지 않았다. 그래서 enforce는 0이 아닌 명령에 판정이 없으면 원인을 가리지 않고 바로 `control:<사유>` e-stop을 래치했다. Gazebo 차로 주행 run59(2026-10-14, 부하가 걸린 공유 PC)는 교차로 접근 중 `control:policy_invalid`로 끝났고, 같은 프로세스에서 34–77 ms 스케줄 지연이 여러 번 보였다. 이 개정은 4항을 enforce 경로에 구현하고, 답 시간 상한의 근거를 다시 적는다. 상태(Status)와 전환 게이트(6항)는 바꾸지 않는다. enforce를 켜는 일은 여전히 로봇별 승인이다.

**끊김으로 치는 것.** 근거나 답이 제때 없는 경우만이다.

- 평가기가 아직 묶이지 않았다(`policy_unavailable`).
- 정책에 지금 쓸 관측이 없다: `snapshot_missing`, `snapshot_future`, `snapshot_expired`, `snapshot_changed`. 평가기는 이때 `PolicyObservationUnavailable`(`ValueError`의 하위)을 낸다(`policy_failed`). 메시지 문자열로 가리지 않는다.
- 형식이 맞고 요청과 일치하는 판정이 시간 조건만 어겼다(`policy_invalid`): 답이 상한보다 늦었거나, `request.now` 또는 `request.now + elapsed`가 `[observed_at, expires_at]` 밖이다. `decision_fault`가 `timing`과 `malformed`를 가른다. `decision_valid`와 `check_decision`의 결과는 그대로다.

**바로 래치하는 것(전과 같다).** `stop` 판정(늦게 온 `stop`도), 형식이 틀리거나 요청과 맞지 않는 판정(명령 id·출처·revision 불일치, 유한하지 않은 값, lease 폭 범위 밖, 잘못된 disposition·reason), 평가기의 다른 예외, 평가 중 평가기나 revision이 바뀐 경우, 유한하지 않거나 음수인 경과 시간(시계 고장), `actuation_*` 검사 실패. 끊김인지 확실하지 않은 경우는 래치 쪽에 두었다.

**HOLD 동작.**

- `SafetyManager.bind_policy`·`bind_control_policy`가 `stale_hold_s`를 받는다. 기본 0은 전과 같이 모든 무판정이 바로 래치다. 센서 어댑터는 enforce로 묶을 때 설정값(기본 2 s, (0, 5])을 넘긴다. shadow와 off는 넘기지 않는다.
- 끊김이 시작된 시각을 정책 시계(`_policy_clock`)로 기억한다. 끊김 나이가 `stale_hold_s`보다 작은 동안 `evaluate_candidate`는 None과 함께 `policy_hold`를 세우고, `CommandManager._policy_output`은 `trigger_estop`과 모드 전이 없이 0을 낸다. 유효한 판정이 오면 끊김 기록을 지우고 그 틱부터 재개한다.
- 끊김 나이가 `stale_hold_s`에 닿으면 다음 무판정에서 전과 같은 `control:<사유>`로 래치한다. 정책 시계가 거꾸로 가도 래치한다.
- 속도 0 명령은 전과 같이 정책에 묻지 않는다. 묻지 않으므로 끊김을 끝내지 못한다. 끊김 뒤 0 명령으로 2 s를 넘기고 다시 0이 아닌 명령을 냈는데 첫 평가가 또 끊김이면 바로 래치한다. 래치 뒤 해제해도 끊김 기록은 유효한 판정이 한 번 나올 때까지 남는다.
- 진단 로그(`Control policy failed ...`)는 끊김이 열릴 때 한 번, 래치할 때 한 번만 낸다. HOLD 중 50 Hz로 내지 않는다.

**답 시간 상한.** `decision_valid`의 `elapsed ≤ 0.01`은 6항 G-sim의 성능 게이트(`eval_ms` p99 ≤ 10 ms)에서 온 숫자였고 안전에서 유도한 값이 아니었다. 이제 이름 있는 상수 `POLICY_ANSWER_BUDGET_S = 1/50 s`다. 근거는 `_policy_output`을 부르는 루프의 주기다. CORE의 유일한 `/cmd_vel` 타이머가 50 Hz(`ros_bridge.py`의 `create_timer(1.0 / 50.0, self._publish_cmd_vel)`, D-2, `test_bridge_timers.py`가 고정)이고, 답은 자신이 판정한 틱에 적용되어야 한다. 근거의 나이 조건(`observed_at ≤ now ≤ now + elapsed ≤ expires_at`, lease 폭 ≤ 0.5 s)은 바꾸지 않았다. 그림자도 같은 규칙을 쓰므로 10–20 ms 답은 이제 `unavailable`이 아니라 판정으로 기록된다. G-sim 게이트의 `eval_ms` p99 ≤ 10 ms는 그대로다.

**표시.** `policy_reason`은 HOLD 중에도 사유를 갖는다. `/robot/state`의 `safety_policy.hold` `{count, reason}`(enforce에서만, API v1.223)가 HOLD로 답한 끊김의 수와 가장 최근 사유를 싣는다. 새 이벤트 종류는 만들지 않았다. 래치는 전과 같이 `safety.estop`의 `source`로 보인다.

**하지 않은 것.**

- `evaluate_candidate`의 actuation 총 예산(`elapsed ≤ 0.01`, `actuation_stale_or_over_budget`)은 그대로다. 시뮬 전용 경로이고 제품 코드에서 `bind_simulation_actuation`을 부르는 곳이 없다. 이 사유는 끊김으로 치지 않는다.
- 어댑터 설정은 `stale_hold_s` 0을 받지 않으므로(0, 5]), 어댑터로 묶은 enforce는 항상 HOLD가 켜진다. 끄는 설정은 두지 않았다.
- 워커의 정지 거리와 봉투 문제(계획 1의 "해석 주의와 한계")는 그대로다. HOLD는 근거가 없는 동안 0을 내는 것이라 그 문제를 넓히지 않는다.

**검증.** 호스트 단위 시험만이다(`test_safety_decision_check.py`, `test_control_absorption_safety.py`, `test_control_policy_link.py`, `test_control_sensor_adapter.py`, `test_safety_policy_status.py`). SIM(Gazebo 차로 주행 재실행)과 DEVICE는 하지 않았다. 34–77 ms 지연이 실제로 HOLD 한두 틱으로 끝나는지는 Gazebo에서 확인해야 한다.
