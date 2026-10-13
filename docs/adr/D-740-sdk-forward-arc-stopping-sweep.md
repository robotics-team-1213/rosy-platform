## D-740 SDK 게이트는 전진 호를 제자리 회전 원이 아니라 그 호의 정지 궤적으로 검사한다

**Status:** Proposed (2026-10-13, SOURCE 구현과 원격 단위 회귀). Gazebo 완주, ROS 생산자 시험, 실물 수용은 아직 없다.

## 배경

`control.sensor_adapter.mode: enforce`에서 SDK 게이트(`command_gate.evaluate_command`)는 `can_rotate`가 거짓이면 각속도를 0으로 만들고, 이동 중인 호가 바뀌면 `trajectory_changed`로 멈춘다. `can_rotate`는 제자리 회전 규칙이다. 가장 가까운 스캔 점이 회전 반경 + 여유(Pinky 0.09257 m) 밖에 있어야 참이다. 이 규칙이 전진 호에도 그대로 적용됐다.

`map_v2_fleet`의 차선 중심은 벽에서 116 mm다. 로봇이 중심에서 2 cm 벗어나면 모든 스캔에서 `can_rotate`가 거짓이 되고, 차선추종의 조향 명령(v>0, w≠0)이 전부 거절되어 벽에서 멀어지는 조향도 할 수 없다. Gazebo 실행은 y=0.529(벽 0.625)에서 정지했고 전방은 0.36–0.58 m 비어 있었다.

D-737이 CORE 쪽 몸 검사와 최종 명령의 곡률을 맞췄고, 이 결정은 그 문서가 남겨 둔 SDK raw 거절을 다룬다. 계산 함수 `forward_stopping_sweep_clearance`는 이 브랜치에 이미 있다([설계 메모](../plans/2026-10-13-camera-forward-stopping-sweep-design.md)는 `fix/gazebo-map-lap` 브랜치에 있다).

## 결정

1. 센서 어댑터는 `can_rotate`를 판단한 같은 스캔으로 `ForwardEvidence`를 만든다. 내용은 base_footprint 스캔 점, 스캔 완전성, 수신·원본 시각, 적용된 `RobotBody`, 프로필 속도 상한이다. 기존 `TranslationEvidence`와 같은 경로(`update_observations` → `GateSnapshot`)로 전달한다.
2. `CommandPolicy.evaluate`는 후보마다 따로 판단한다. 조건은 전부 만족해야 한다. (가) 기존 결과가 `trajectory_changed`이고 `can_rotate`가 거짓이다. (나) `can_rotate`만 참으로 바꿔 다시 평가하면 후보가 바뀌지 않고 `allow`다. (다) `linear > 0`이고 `angular != 0`이다. (라) 그 (linear, angular)의 정지 궤적 여유가 0보다 크다. 그때만 원래 twist를 그대로 허용한다.
3. 정지 궤적은 `v²/(2a) + margin_m`까지 같은 곡률의 모든 몸 자세를 쓸고, `sweep_pad_m`과 지연 동안의 이동·회전을 여유로 뺀다. 이전 명령의 상한(`previous_limits`)은 프로필 상한을 쓴다. 실제 발행 이력보다 보수적이다.
4. 증거가 없거나 형식이 틀리거나, 스캔에 모르는 방위가 있거나, 스캔 나이가 음수(시계 오류)이거나 0.5 s를 넘거나(계산 함수 자체는 0.2 s까지만 받는다), 후보가 프로필 상한을 넘거나, 여유가 0 이하이면 기존 결과를 그대로 둔다.
5. 생산자는 URDF 몸이 회전 판단의 기준일 때만 증거를 만든다. 학습된 회전 envelope, 커진 반경, 회전·직진 시험 중에는 만들지 않는다. `lidar_use_tf`가 꺼져 base_footprint 점이 없을 때도 만들지 않는다.

## 바뀌지 않는 것

- 제자리 회전(v=0)은 회전 원 규칙 그대로다. 전방이 막힌 호를 이 결정으로 제자리 회전으로 바꾸지 않는다(D-424 F는 `can_rotate`가 원래 참일 때만).
- 후진과 후진 호의 규칙.
- 전방 `obstacle`, cliff, tilt, pickup, E-stop, stale·unknown 스캔, bounded_motion 시험, 회전·직진 시험 영역, tracking 제한, `linear_limit`의 우선순위와 의미.
- 임계값, 잡음, 여유, 속도 상한. 새 설정 키·모드·API 필드는 없다.
- 스냅샷은 바꾸지 않는다. 허용은 후보 하나에만 유효하고 다음 후보로 넘어가지 않는다.
- `can_rotate` 토픽과 `/safety/motion_limits` 보고는 그대로다.

## 한계와 확인하지 못한 것

- 지연 여유가 크다. 여유는 `sweep_pad + (V + W·(reach + travel))·delay`이고 `delay ≥ 0.16 s`, Pinky `reach ≈ 0.095 m`다. 프로필 상한이 (0.10 m/s, 0.70 rad/s)이고 스캔 나이가 10 ms이면 약 41 mm라서, 벽과 나란한 호는 벽이 중심에서 약 98 mm 이상일 때만 허용된다. 상한이 (0.20, 0.80)이면 약 117 mm다. 벽 96 mm인 원래 Gazebo 정지 사례가 이 결정만으로 풀린다는 증거는 없다. 풀리지 않으면 `previous_limits`를 실제 발행 이력으로 좁히는 별도 결정이 필요하다.
- 벽에서 멀어지는 호는 뒤쪽 모서리가 벽 쪽으로 돈다. 곡률이 크면 멀어지는 호도 거절된다.
- 완전성은 기존 `rotation_scan_observed`(모든 빔이 범위 안에서 돌아옴)와 `rotation_reason is None`을 둘 다 요구한다. 열린 방향이 있거나 빔이 빠지는 실물 LiDAR에서는 증거가 자주 무효가 될 수 있다.
- 생산자 시험(`test_os_parameter_graph.py`)은 rclpy가 필요하다. 원격 시험 PC에서는 건너뛰었으므로 CI의 ROS 단계에서 확인해야 한다.
- Gazebo 같은 지도 반복과 실물 주행은 하지 않았다. 호스트 pytest 통과는 장치·현장 수용이 아니다.

## 개정 1 (2026-10-13, 같은 날)

사용자 결정(2026-10-13): Gazebo 차선 완주를 위해 SDK 여유를 줄여도 된다. 위 결정 3, 「바뀌지 않는 것」의 전방 `obstacle`, 한계의 coverage 조건을 다음으로 바꾼다. 나머지는 그대로다.

1. `previous_limits`는 프로필 상한이 아니라 후보 자신의 `(v, |w|)`다. 직전 명령이 후보보다 빠르지 않았다고 가정한다. 감속 중에는 이 가정이 틀리며, 그만큼 패딩이 부족하다(프로필 상한에서 후보 `(0.05, 0.05)`로 줄일 때 약 2 cm). CORE가 실제로 낸 직전 명령의 상한을 넘기는 것이 후속 과제다.
2. 호의 정지 궤적이 비어 있으면 직진 띠 기준의 LiDAR 전방 `obstacle`도 그 호에는 적용하지 않는다. 직진 띠는 그 호가 지나는 길이 아니기 때문이다. 초음파 전방 차단(`front_blocked_other`가 참이거나 모름), cliff, tilt, pickup, estop은 여전히 우선한다. 결과로 enforce에서 조향이 있는 차선 추종에는 `stop_distance`/`clear_distance`가 적용되지 않고 정지 궤적만 적용된다. 스캔을 정지 장면으로 보므로 움직이는 장애물에 대한 `stop_distance`의 여유는 없다.
3. coverage는 모든 빔이 반환됐는지(`lidar_rotation_observed`)만 본다. `lidar_rotation_reason`은 제자리 회전 원이 막혔을 때 채워지므로 이 증거가 필요한 바로 그때 증거를 무효로 만들었다(Gazebo run17: 여유 1.2 mm인데 무효).
4. 평가 중 snapshot이 교체되면 새 snapshot으로 한 번 더 판단한다. 두 번째에도 교체되면 기존처럼 거절한다. 이전에는 이 경우가 CORE의 `control:policy_failed` E-stop이 됐다(run19).

확인하지 못한 것: 몸 윤곽 안의 반사를 지운 방위를 coverage가 관측으로 세는지, 여유 임계 0 근처에서 허용과 거절이 번갈아 나오는지, 정지 궤적 계산 시간이 `evaluation_budget_s` 0.01 s 안인지. 독립 리뷰(2026-10-13)가 짚은 항목이며 장치 payload에 싣기 전에 닫는다.

## 개정 2 (2026-10-14) · 시계를 읽은 뒤 올라온 snapshot

Gazebo 한 바퀴 run56에서 굽이 통과가 `motion_unconfirmed`로 끝났다. 거절은 한 건이었다. CORE가 정책 시계를 읽은 값은 65036.852, worker가 그 뒤에 올린 snapshot의 `observed_at`은 65036.886이었다(0.034초 앞섬, `snapshot_future`). 차선 추종 틱 스레드가 시계를 읽고 물을 때까지 밀린 사이에 worker가 올린 것이다.

결정: 정책은 그대로 둔다. CORE의 승인 함수(`bind_lane_return_motion`)가 정책 시계를 따로 가질 때(`use_sim_time`) 센서 증명이 거절되면 시계를 새로 읽어 한 번 더 묻는다. 두 번째도 거절이면 거절이다. 몸 스윕 판정과 최종 명령 경로는 바뀌지 않는다.

버린 안: 정책 안에서 `observed_at`을 `now`로 삼아 다시 판정하는 안. 독립 검토(2026-10-14, code-reviewer)가 냈다. 그 시각에는 LiDAR 증거의 나이가 음수라 범퍼·전진 곡선·추적이 모두 막혀 실제 snapshot에서는 여전히 거절이고, 최종 경로는 `decision_valid`가 걸러 원인 기록만 `policy_invalid`로 바뀐다.

한계: 실물에서는 승인 함수가 틱의 차선 시계를 그대로 넘긴다(`policy_clock` 없음). 틱 도중 올라온 snapshot은 틱 시작 시각보다 늦으므로 같은 거절이 날 수 있고 이 개정은 거기에 닿지 않는다. 실물의 차선 시계가 정책 시계와 같은 단조 시계인지 확인한 뒤 물을 때 시계를 읽도록 고치는 일이 남아 있다. 확인한 것은 단위 테스트뿐이다.
