# Semantic Road Perception and Control Design

Date: 2026-09-21

## Goal

`map_260905_update_v2`를 보존한 채 차선, 정지선, 횡단보도, 동적 신호등이
보이는 파생 Gazebo 월드를 만들고, Pinky가 전면 카메라로 이를 인식해 교통
정책에 따라 정지·대기·재출발하도록 한다. 관제는 인식과 정책을 각각 확인하고
권한 범위 안에서 정책 및 시뮬레이션 신호를 조작할 수 있어야 한다.

## Decision

도로 장면, 인식, 정책, 명령, 관제를 분리한다. semantic map은 장면 생성과
정확도 평가의 정답이며 검출기 입력으로 사용하지 않는다. Control은 카메라에서
evidence만 만들고 CORE가 정책을 판단한다. CORE Command Manager는 계속 유일한
최종 `cmd_vel` 소유자다.

## Modules

### 1. `road_scene`

- 소유 위치: `src/core/control/map/map_260905_update_v2/semantic/`
- 원본 16개 벽과 occupancy map을 변경하지 않는다.
- `road_scene.yaml`에 lane polyline, stop line, crosswalk polygon/stripes,
  traffic signal pose/orientation/controlled zone을 기록한다.
- 생성기는 원본 월드에 collision 없는 1 mm 높이 visual을 추가한
  `map_260905_traffic.world`와 사람이 보는 semantic preview를 만든다.
- 신호등 기둥과 하우징에는 collision을 주되 도로 표식에는 collision을 두지
  않는다. 따라서 SLAM occupancy map과 주행 가능 geometry는 변하지 않는다.

### 2. `road_perception`

- 소유 위치: `src/core/control/control/sensing/road.py`
- OpenCV 고전 CV로 lane, stop line, crosswalk, traffic light를 독립 검출한다.
- 출력은 source timestamp, detection kind, normalized image location, estimated
  distance, confidence, signal ID hint/color를 포함한다.
- washed frame, 서로 모순되는 signal color, stale frame은 invalid evidence다.
- ROS observer는 `road/observation` JSON만 발행하고 motion topic을 발행하지 않는다.

### 3. `traffic_policy`

- 소유 위치: `src/core/core_features/core_features/traffic_policy/`
- 상태는 `DISABLED`, `FOLLOW`, `APPROACH`, `STOP_REQUIRED`, `WAIT_SIGNAL`,
  `PROCEED`, `HOLD`다.
- policy mode는 `MONITOR_ONLY`와 `ENFORCED`다. `ENFORCED`가 기본이며
  `MONITOR_ONLY`는 simulation/operator 시험에서만 선택한다.
- 적색과 황색은 정지한다. 녹색은 정지선·signal ID·신뢰도·freshness가 모두
  맞고 최소 정지 시간이 지난 뒤에만 재출발한다.
- signal evidence가 stale이거나 서로 충돌하면 `HOLD`로 정지한다.
- E-stop, stale stop, invalid evidence는 관제에서 해제할 수 없다.

### 4. `navigation_control`

- 기존 `LineFollowManager`가 만든 후보 Twist를 `TrafficPolicyManager`가 gate한다.
- 정책은 후보를 통과시키거나 선속도를 접근 속도로 낮추거나 zero Twist로 만든다.
- 정책은 직접 publish하지 않는다. 최종 명령은 기존 Command Manager safety
  clipping과 policy evaluation을 그대로 통과한다.
- mode 전환, mapping 시작, E-stop은 road session과 보관 evidence를 폐기한다.

### 5. `traffic_supervision`

- viewer는 현재 detection, confidence, age, active signal, policy state/reason,
  적용 policy revision을 볼 수 있다.
- operator는 정지 상태에서 `MONITOR_ONLY`/`ENFORCED`, 신뢰도, stale timeout,
  yellow handling, stop dwell을 stage/apply할 수 있다.
- simulation capability가 있을 때만 신호 상태를 RED/YELLOW/GREEN으로 바꾼다.
- 모든 변경은 actor, 이전/새 revision, 대상 signal ID를 event/audit에 남긴다.

## Data Flow

```text
semantic road YAML -> Gazebo visuals + evaluation truth
front camera -> road observer -> road evidence -> traffic policy
line observer -> line follow candidate ---------> traffic policy gate
traffic policy gate -> Command Manager -> safety -> sole cmd_vel publisher
state/events -----------------------------------> dashboard
dashboard operator action -> versioned policy or simulation signal controller
```

## Fail-closed rules

- perception payload validation 실패: 즉시 후보 명령 0, 상태 `HOLD`
- stale traffic evidence: 정지, 새 evidence만으로 자동 해제하지 않음
- red/yellow/green 동시 검출: 정지
- policy 변경 중 motion: 409 conflict
- semantic map ID와 runtime map ID 불일치: 정책 `HOLD`
- dashboard 연결 상실: active policy 유지, 안전 제한은 완화하지 않음

## Validation

1. semantic schema와 원본 벽 hash 불변 계약
2. 생성된 SDF의 차선·횡단보도·정지선·신호등 visual 계약
3. 합성 카메라 프레임에서 각 detector precision/negative case 시험
4. red/yellow stop, green dwell release, stale/conflict HOLD pure-policy 시험
5. line-follow 후보가 정책 gate를 우회하지 못하는 CORE 시험
6. viewer/operator/admin 권한 및 정지 중 apply 계약 시험
7. 폐루프 host simulation: lane follow -> stop line -> red wait -> green resume
8. Gazebo 카메라 실행에서는 semantic truth와 perception 결과를 분리 저장

## Acceptance boundary

ROS-SIM 합격은 Gazebo 렌더링, 카메라 perception, CORE policy, 단일 publisher,
관제 readback이 같은 run ID에서 확인될 때만 선언한다. 합성 프레임 시험이나
semantic truth 자체는 카메라 인식 증거가 아니다. 실제 Pinky Pro 카메라 노출,
장착 자세, 정지거리와 물리 신호 환경은 DEVICE/FIELD gate로 남는다.
