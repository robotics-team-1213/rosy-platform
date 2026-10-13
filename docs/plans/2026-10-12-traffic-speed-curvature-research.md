# 교통 감속과 차선 추종 곡률 조사

> 조사: 2026-10-12. ROSY 소스 기준: `32798ee0b`; effective-law 후보 비교: `45e92d326`. SOURCE 조사이며 제품 변경, Gazebo 재실행, 지도 완주 또는 DEVICE/FIELD 수용이 아니다.

## 확인한 차이

Nav2 Jazzy의 일반 경로 추종은 선속도 제약을 적용한 뒤 각속도를 `angular_vel = linear_vel * regulation_curvature`로 계산한다. 따라서 같은 목표 곡률에서 감속한 선속도로 각속도도 정한다. 회전 정렬 분기는 별도다. 해당 명령에 대한 충돌 검사가 이어진다. [공식 Jazzy 구현, 코드 239–279행](https://api.nav2.org/nav2-jazzy/html/regulated__pure__pursuit__controller_8cpp_source.html#l00239)

논문 §3 식 (7)도 조절된 선속도와 목표 곡률의 곱으로 각속도를 계산한다. 이는 ROSY가 Nav2를 사용한다거나 같은 안전 성능을 갖는다는 근거가 아니다. [Macenski 외, Regulated Pure Pursuit, 2023, §3](https://arxiv.org/html/2305.20026v1#S3)

공식 Jazzy 설정 문서는 곡률·장애물 근접에 따른 감속과 속도에 따른 lookahead를 설명한다. 제시된 예제 속도·거리 값을 작은 Pinky 지도에 그대로 옮길 근거는 없다. 요청받은 옛 `/jazzy/configuration/packages/configuring-regulated-pp.html`은 이번 조회에서 열리지 않았으며 현재 확인한 URL은 아래와 같다. [Jazzy 공식 설정 문서](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/controller_plugins/configuring_regulated_pp/)

ROSY의 `TrafficPolicyManager._evaluate()`는 ENFORCED의 FOLLOW/APPROACH/PROCEED에서 `(linear * scale, angular)`를 반환한다. stop-line APPROACH의 scale은 남은 정지 거리에서 계산한다. DISABLED/MONITOR_ONLY는 원 명령을, 다른 ENFORCED 상태는 `(0, 0)`을 반환한다. [manager.py, `_evaluate` 및 `_verdict`](../../middleware/control/drive/behaviors/traffic_policy/manager.py)

`apply_line_candidate()`는 static profile clip → traffic gate → `set_nav_twist(...preserve_curvature=True)` 순서다. 마지막 곡률 보존은 **이미 교통 gate가 바꾼** 명령의 비율을 보존하며, 원래 목표 곡률을 복원하지 않는다. 먼저 실행되는 static profile clip도 두 축을 각각 제한하므로 해당 제한이 활성화됐는지 구분해야 한다. [traffic_gate.py](../../middleware/core/gateway/core/bridge/traffic_gate.py), [CommandManager, `clip_line_candidate`](../../middleware/core/services/core_features/command/manager.py)

## 검증 가능한 추론

다른 제한·보정이 없는 일반 forward pursuit에서 목표 곡률을 `k = w/v`로 만들었다면, `0 < s < 1`인 교통 감속 뒤에는 `k_out = w/(s*v) = k/s`가 된다. 이는 코드와 비율식에서 도출한 추론이다. 예를 들어 `(v,w)=(0.08,0.16)`에 `s=0.5`를 적용하면 곡률이 `2`에서 `4 1/m`로 바뀐다. 이 예는 실행 로그가 아니다.

`45e92d326`의 effective-law 후보는 `error_for_k()`에서 실제 CORE cruise/gain/confidence law를 역산한다. `ExpectedPath`도 `DrivableSteer.pursuit_error`를 주입받는다. 이 역산은 CORE 기본 조향의 목표 비율을 맞추지만 이후 traffic 감속까지 포함하지 않으므로 current/held 양쪽에서 위 차이가 남을 수 있다. [drivable_steer.py](../../middleware/perception/vision/perception/drivable/drivable_steer.py), [drivable_keep.py](../../middleware/perception/vision/perception/drivable/drivable_keep.py), [ExpectedPath](../../middleware/perception/vision/perception/learned/expected_path.py) — 후보의 함수 인자는 지정 SHA로 대조한다.

우선 기존 교통 정책 회귀에서 같은 양의 forward `(v,w)`에 APPROACH/PROCEED scale을 적용하고 입출력 비율을 비교하면 이 효과를 재현할 수 있다. 계약이 곡률 보존을 요구하는지 결정한 뒤에만 수정안을 시험한다. gate의 HOLD/오래된 관측/지도 불일치 zero와 authority/lease/IR/scan/body/EStop 거절은 유지해야 한다.

다음 실제 Gazebo 기록은 같은 tick의 목표·평활 곡률, CORE line 후보 `(v,w)`, traffic mode/state/reason/linear_scale, global caps, 최종 CORE 명령을 묶어야 한다. `s<1`일 때에만 차이가 커지는지 확인한다. IR edge·lane cue·역방향 creep·pivot·lane arc·traffic HOLD는 일반 pursuit 비교에서 분리한다. stamp 없는 native cmd_vel을 가까운 clock으로 연결한 것만으로 정확한 camera frame 대응을 주장하지 않는다.

## 증거 한계

곡률 변화는 SOURCE 수준에서 확인했지만 기존 R29 또는 Gazebo leg 실패의 원인으로 확정하지 않았다. 실제 감속 활성 구간과 동시 입력·명령 기록, 정책의 의도된 계약, 비교 회귀가 아직 필요하다. 이 문서는 안전 gate 완화나 교통 정책 변경을 승인하지 않는다.
