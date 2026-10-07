## D-498 교차로 제한 회전은 D-400 enforce가 아니어도 bridge와 같은 현장 근거(IR 가드 + 몸체 근접 정지 + 현장 수용 선언)로 허용한다

**Status:** Proposed (2026-10-07, 사용자 지시 "그렇게 처리해" — D-495 merge note 6항의 "회전에 bridge의 rev-1 근거를 줄지는 별도 ADR"). 기본값은 꺼짐이다. 현장 설정·SIM·DEVICE 수용은 별도다.

잇는 결정: [D-495](D-495-lane-junction-bounded-turn-and-junction-defaults.md)(교차로 제한 회전, 정직한 `junction_turn`) · [D-476](D-476-lane-loss-expected-road-bridge.md) rev 1(bridge는 IR 가드와 바닥 근거가 있어야 켠다) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md)(안전 정책 off/shadow/enforce, plan 3 전 enforce 금지) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 근접 정지) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(trip 실행)

### Context

1. D-495 구현 뒤 독립 검토(2026-10-07)에서 확인한 것: 회전 동작의 운동 근거(`_return_probe`/`return_sensor_allowed`)는 센서 어댑터가 `enforce`이고 LiDAR·IMU·IR을 모두 요구할 때만 참이다. D-400은 plan 3 전에 enforce를 금지한다. 그래서 오늘 모든 로봇은 `junction_turn: false`를 알리고, Fleet은 차선 trip을 거절한다(정직한 실패).
2. D-476 rev 1은 같은 문제를 bridge에서 이렇게 풀었다: bridge는 `ir_guard_enabled`가 켜졌고, 센서 어댑터가 `enforce`이거나 현장이 `bridge_site_no_dropoffs: true`(바닥이 떨어지는 곳이 없다는 현장 선언)일 때만 켜진다.
3. 회전은 제자리 회전과 최대 0.30 m 전진이다. bridge보다 이동 거리가 짧고, 모든 단계에서 D-422 몸체 근접 정지와 odom·시간 한도가 적용된다(D-495).

### Decision

1. **회전의 운동 근거는 둘 중 하나다.**
   - (a) 지금처럼 D-400 enforce 바닥 증명(`return_proof_configured`)
   - (b) **현장 근거**: 다음을 모두 만족한다.
     - `ir_guard_enabled: true`이고 IR 가드 판정이 신선하다(D-476 rev 1과 같은 판정)
     - D-422 몸체 근접 정지가 동작 중이다(설정과 신선한 장애물 근거)
     - 현장이 `junction_turn_site_accepted: true`를 선언했다(새 설정, 기본 `false`). 이 선언은 "교차로 회전 반경 안에 바닥이 떨어지는 곳이 없고, 차로 가장자리 밖으로 0.30 m 전진해도 안전하다"는 현장 책임자의 확인이다. bridge의 `bridge_site_no_dropoffs`와 따로 둔다. 같은 현장이면 둘 다 참으로 둘 수 있다.
2. **`junction_turn` 능력**은 (a) 또는 (b)가 성립할 때만 참이다. 판단 시점마다 다시 계산한다. IR 가드 판정이 낡으면 거짓이 된다. 정직한 실패는 그대로 유지한다.
3. **회전 도중**에 (b)의 근거가 사라지면(IR 가드가 `departure`/낡음, 근접 정지 근거 낡음) 기존 중단 규칙과 같게 `aborted`(사유 `turn_basis_lost`)로 멈춘다.
4. **기본값**은 `junction_turn_site_accepted: false`, `ir_guard_enabled: false`(그대로)다. 코드만으로는 아무 로봇에서도 회전이 켜지지 않는다. 켜는 순서는 다음과 같다.
   1. IR 보정(진행 중, 다른 세션)
   2. 현장 설정 오버레이(`~/.rosy/rosy.yaml` 또는 사이트 설정)에 `ir_guard_enabled: true`와 `junction_turn_site_accepted: true`를 둔다.
   3. 모델 PC SIM S1–S6
   4. 9dfk keep 모드 DEVICE D1–D6
5. **설정 검증**: `junction_turn_site_accepted: true`인데 `ir_guard_enabled: false`이면 설정을 거절한다(D-476 rev 1 bridge와 같은 방식). CORE가 시작하지 않으므로, 잘못된 현장 설정은 조용히 무시되지 않는다.

### 범위 밖

- IR 보정 절차와 IR 가드 판정 자체(D-491 IR 가드 작업). 분기 인식 출력(D-495 4항 후속). bridge 기본값.

### 검토한 대안

- **D-400 enforce를 회전에만 앞당겨 켜기.** D-400의 plan 3 전 enforce 금지와 충돌한다.
- **근거 없이 회전 허용.** 독립 검토에서 막은 경로다(motion_unconfirmed).
- **`bridge_site_no_dropoffs`를 회전에도 그대로 쓰기.** bridge(직진 연장)와 회전(차로 밖 전진 가능)은 확인할 바닥 범위가 달라서, 선언을 따로 둔다.

### Consequences

- 현장이 IR 보정을 끝내고 두 값을 켜면, enforce 없이도 9dfk 같은 차선 로봇이 지도 trip의 좌·우 교차로를 지날 수 있다. 실차 수용은 그 뒤다.
- 수용 기준 SOURCE:
  - (a)·(b) 각각에서 `junction_turn` 참
  - 근거 하나라도 빠지면 거짓
  - 회전 중 근거 상실 → `aborted turn_basis_lost`
  - 잘못된 설정 조합 거절
  - 기본값에서 거짓

### 구현 메모 (2026-10-07, feat/d498-junction-turn-site-basis)

1. **위치.** `core_features/line_follow/junction.py`의 `_turn_basis`가 근거를 돌려준다. 값은 `enforce`, `site`, 근거 없음 셋이다. `supports_junction_turn`과 회전 매 틱의 거절 검사가 이 함수를 같이 쓴다. 근거가 `site`이면 D-468 동작 확인(`_return_probe`)은 요구하지 않는다. 대신 회전·전진 twist마다 기존 D-422 몸체 간격 검사가 돈다. 이 검사는 현장 근거가 몸체 기하와 신선한 스캔을 요구하므로 항상 실행된다.
2. **IR 가드 판정.** 현장 근거는 판정이 신선하고 이탈(`centre`)이 아닐 때 성립한다. 낡음(`stale`)이나 이탈이면 성립하지 않는다. D-476 rev 1 bridge(`lane_bridge.py`)는 `clear`만 받는다. 회전에서는 `left`·`right`(옆 센서 밑의 차선)도 허용한다. 제자리 회전은 차선을 가로질러 돌기 때문이다. 결정 3항의 "IR 가드가 departure/낡음이면 중단"과 같다. 실기에서 교차로 가로선 위 회전이 `centre`를 자주 내면 D3에서 기록한다.
3. **신선도.** 스캔은 `clearance_stale_s`(0.5 s) 안이어야 한다. IR은 `stale_after_s`(0.3 s) 안이어야 한다.
4. **중단 사유.** 시작할 때의 근거를 기록한다. 현장 근거로 시작한 회전이 근거를 잃으면 사유는 `turn_basis_lost`다. enforce 근거로 시작했거나 근거 없이 시작하려 하면 지금처럼 `motion_unconfirmed`다.
5. **크기.** `core_features`는 15033(main)에서 15050으로 늘었다. 판정 14934에 +150을 더한 15084 안이다.
6. **API.** Reference v1.118이다. v1.117은 `fix/lane-play-stl-nominal`이 먼저 잡았다.

### 독립 안전 검토 반영 (2026-10-07)

검토 판정은 착지 가능(LAND)이다. 기본 설정에서는 회전하지 않는다. 현장 근거로 회전할 때 D-468 동작 확인을 건너뛰어도, D-422 몸체 검사가 매 틱 돌고 동작이 짧고 한정되어 있어 받아들일 수 있다.

1. **바닥 위험은 현장 선언이 전부 진다(M2).** IR 가드는 차로 이탈을 막는 울타리일 뿐이다. IR이 선을 못 보거나 신뢰도가 낮으면 `clear`로 읽히므로, 바닥이 떨어지는 곳 위에서도 `clear`가 나온다. IMU 기울기·충격 증거도 쓰지 않는다. 따라서 회전 원(반지름 0.088 m)과 최대 0.30 m 전진 범위의 바닥 안전은 `junction_turn_site_accepted`를 선언하는 현장 책임자가 진다.
2. **선언은 로봇 설정에 묶여 있다(M1).** 플래그는 로봇의 `~/.rosy/rosy.yaml`에 있다. 그래서 로봇이 다른 현장으로 옮겨 가면 선언도 같이 따라간다. `bridge_site_no_dropoffs`도 같다. 로봇이 현장을 떠날 때는 이 오버레이를 반드시 지운다(D8). 선언을 현장·지도 id에 묶는 방식은 후속으로 둔다.
3. **켜는 순서 보강(L1).** 4항 2단계에 `obstacle_mode: path`와 URDF 몸체 형상을 더한다. 기본 `sector` 모드에서는 스캔 점이 없어서 근거가 성립하지 않고, 회전 능력은 아무 설명 없이 거짓으로 남는다.
4. **능력 깜박임(L2).** IR이 선 위에 있거나(`centre`) 스캔이 늦으면 `junction_turn`이 잠깐 거짓이 될 수 있다. Fleet은 시작할 때만이 아니라 회전을 지시할 때도 이 판정을 따른다.
5. **체크리스트 추가.**
   - SIM S7: 현장 오버레이(IR 가드 켬, path 모드, `site_accepted` 켬, enforce 없음)로 좌·우·−150° 회전을 하고, IR이 교차로 선을 지나며 생긴 중단(`turn_basis_lost`·`lane_departure`) 횟수를 센다.
   - SIM S8: 회전 원 안과 전진 경로에 장애물을 두면, 다음 틱에 `near_stop`으로 중단하고 명령이 0이어야 한다.
   - SIM S9: 회전 중 IR이나 스캔이 낡으면 `turn_basis_lost`로 중단하고 명령이 0이어야 한다.
   - DEVICE D7: 현장 근거를 켜기 전에 IR 보정과 그 revision이 적용됐는지, `supports_junction_turn`이 keep 모드와 오버레이에서만 참인지 확인한다.
   - DEVICE D8: 현장 책임자가 지도의 모든 교차로에서 회전 원과 그 바깥 0.30 m를 직접 걸어 확인하고, 선언을 현장·지도 id와 함께 기록한다. 로봇이 현장을 떠나면 오버레이를 지운다.
   - DEVICE D9: 교차로 종류마다 회전 중 IR이 `centre`로 읽히는 빈도를 잰다.
