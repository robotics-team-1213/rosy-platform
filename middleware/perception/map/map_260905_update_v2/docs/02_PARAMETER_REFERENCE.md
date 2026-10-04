# MAP 260905 파라미터 기준표

v2 / 2026-09-20

**이 문서의 시험값은 작은 실습 트랙을 위한 시작 제안입니다. 실제 로봇의 안전값·최적값·보장 정확도가 아닙니다.** 제공된 패치는 부분 설정이며, 실제 전체 YAML에 검토 후 병합해야 합니다.

## 1. 상태 구분과 적용 우선순위

| 표시 | 처리 |
|---|---|
| 확정(파일) | 업로드된 XML에서 확인한 값. 실물까지 확정한 것은 아님 |
| 출력 정책 | 이번 점유 지도 생성에서 선택한 값 |
| A — 기본 | 기본 시뮬레이션 복사본에 적용 |
| B — RPP 선택 | 별도 lookahead·제동 검토 후 적용 |
| C — Progress 선택 | 진척도 오판 시험 후 적용 |
| 유지/미확정 | 이 패키지가 새 값을 지정하지 않음 |

우선순위는 **실제 로봇·프로젝트 안전 기준 → 사용 중인 package/plugin 구현 → 후보값**입니다. 공개 저장소 기본값은 현재 우리 프로젝트 설정값으로 간주하지 않습니다. [P1, N3](SOURCES.md#p1)

## 2. 월드·점유 지도

| 항목 | 값 | 상태·의미 |
|---|---:|---|
| 벽 개수 | 16 | 확정(파일) |
| 벽 두께 | 0.010 m | 확정(파일). 원본 주석 0.005 m와 달랐음 |
| 벽 높이 | 0.155 m | 확정(파일), Z=0~0.155 m |
| 외곽 | 2.715 × 1.265 m | 좌표 계산. 형상 변경 없음 |
| `max_step_size` | 0.001 s | 원본 유지 |
| `real_time_factor` | 1 | 원본 유지. 목표 배율 |
| `real_time_update_rate` | 1000 | 원본 유지. 실제 달성 주기 보장 아님 |
| engine filename | `gz-physics-dartsim-plugin` | v2에 명시. 로드 로그 확인 필요 |
| 지도 `resolution` | 0.005 m/cell | 출력 정책 |
| 지도 크기 | 600 × 300 | 3.0 × 1.5 m 범위 |
| 지도 `origin` | `[-1.5, -0.75, 0.0]` | 출력 정책. 로봇 spawn과 별개 |
| `negate` | 0 | 픽셀 반전 없음 |
| `occupied_thresh` | 0.65 | 출력 정책 |
| `free_thresh` | 0.196 | 205 픽셀이 unknown으로 유지되도록 한 정책 |
| outside-track | unknown | 외부 100×100 m 바닥을 모두 주행 구역으로 내보내지 않음 |

근거: [F1, G1, G2, N7](SOURCES.md#f1). 지도 분류에서 중간 회색을 free로 바꾸면 트랙 외부 처리 의미가 달라지므로 임의로 threshold를 바꾸지 않습니다.

## 3. A — 기본 시뮬레이션 패치

비교값은 검토 시 열람한 공개 Pinky YAML 값입니다. 라이브 노드에서 측정한 값이 아닙니다. [P1](SOURCES.md#p1)

| 파라미터 | 공개 비교값 | 이번 후보값 | 의미·적용 조건 |
|---|---:|---:|---|
| `general_goal_checker.xy_goal_tolerance` | 0.25 m | **0.03 m** | goal checker의 위치 허용오차. 원본이 더 작으면 유지 |
| `general_goal_checker.yaw_goal_tolerance` | 0.25 rad | **0.10 rad** | 약 5.7°. 원본이 더 작으면 유지 |
| `GridBased.tolerance` | 0.5 m | **0.02 m** | 요청 goal과 planner 경로 끝점의 허용 차이. 원본 0도 유지 |
| `GridBased.allow_unknown` | true | **false** | 기준 지도 바깥 unknown으로 경로를 만들지 않음 |
| local costmap `resolution` | 0.05 m | **0.01 m** | 1 cm 격자. 원본이 더 작으면 유지 |
| global costmap `resolution` | YAML상 0.05 m | **0.005 m** | 기준 지도 해상도와 일치시킴 |
| global `track_unknown_space` | true | **true** | unknown을 unknown으로 유지 |
| 표준 Nav2 노드 `use_sim_time` | 노드/launch에 따라 다름 | **true** | 시뮬레이션용 복사본에서만 지정 |
| map_server `yaml_filename` | launch가 지정 | 이번 지도 절대경로 | 파일만 준비. 노드는 실행하지 않음 |

### Goal 오차 해석

`0.03 m`를 썼다고 실제 위치 정확도 3 cm가 보장되는 것은 아닙니다. Localization·센서·격자·주행 오차가 별도로 있고, planner 끝점 허용범위와 goal checker의 대상도 다릅니다. 단순히 두 허용범위가 겹쳐 작동해도 요청 goal 대비 오차가 한 값만큼으로 제한되는 것은 아닙니다. 실제 요청 goal에 대해 최종 위치·각도 오차를 별도로 평가합니다. [N1, N2](SOURCES.md#n1)

`SimpleGoalChecker.stateful`은 원본 유지입니다. 상태 기억 동작 때문에 위치 판정을 통과한 뒤 최종 회전 단계의 XY 재검사가 달라질 수 있으므로, 결과 측정으로 보완합니다. [N2](SOURCES.md#n2)

### 전역 resolution 해석

비-rolling global costmap의 static layer는 수신 지도에 맞춰 크기·해상도를 조정할 수 있습니다. 설정 YAML 비교와 실제 costmap metadata 확인을 구분합니다. 이 업데이트는 **전역 costmap이 원래 반드시 5 cm였다는 전제**로 만든 것이 아닙니다. [N4](SOURCES.md#n4)

## 4. B — RPP 선택 시험값

**Jazzy의 RPP 파라미터 이름은 `desired_linear_vel`을 사용합니다.** 최신 문서에 보이는 `max_linear_vel` 등 이름을 Jazzy 설치본에 그대로 적용하지 않습니다. 실제 설치된 버전과 파라미터 선언을 확인합니다. [N3](SOURCES.md#n3)

| 파라미터 | 공개 비교값 | 후보·처리 | 주의사항 |
|---|---:|---:|---|
| `desired_linear_vel` | 0.20 m/s | **0.10 m/s 이하** | 원본이 더 낮으면 유지. 최종 모터 명령 제한과는 별개 |
| `use_velocity_scaled_lookahead_dist` | true | true | 속도 비례 lookahead 사용 |
| `lookahead_dist` | 0.60 m | **0.20 m** | scaled 모드가 꺼진 경우의 고정값. 현재 후보에서는 보통 비활성 값 |
| `min_lookahead_dist` | 0.30 m | **0.15 m** | 줄이면 추종·충돌 예측 범위 모두 재검토 |
| `max_lookahead_dist` | 0.90 m | **0.30 m** | 긴 선회·구간별 heading 거동 확인 |
| `lookahead_time` | 1.5 s | **1.5 s** | `clamp(|v|×시간, min, max)` 관계를 관찰 |
| `rotate_to_heading_angular_vel` | 1.0 rad/s | **0.40 rad/s 이하** | 제자리 정렬용 목표. 모든 회전의 절대 상한이 아님 |
| `min_approach_linear_velocity` | 0.05 m/s | **0.03 m/s 이하** | 정밀 접근 시험. 실제 최저 안정 주행속도는 미확인 |
| `regulated_linear_scaling_min_speed` | 0.05 m/s | **0.03 m/s 이하** | 감속 시 속도 하한. 낮게 둘수록 항상 안정적인 것은 아님 |
| `use_regulated_linear_velocity_scaling` | false | **true** | 곡률 기반 속도 조절을 시험 |
| `use_cost_regulated_linear_velocity_scaling` | true | **true** | 비용 기반 근접 감속 사용 |
| `cost_scaling_dist` | 0.60 m | **min(원본값, 실제 local inflation_radius)** | inflation 범위 밖에서 거리 비용을 추론하지 않도록 정합 |
| `cost_scaling_gain` | 1.5 | **min(원본값, 1.0)** | 작을수록 더 감속하는 방향. “크면 더 감속”으로 해석하지 않음 |
| `inflation_cost_scaling_factor` | 3.0 | **실제 local cost_scaling_factor와 동일** | 고정된 3.0을 무조건 복사하지 않음 |
| smoother `max_velocity` | `[0.25,0,1.5]` | **최대 `[0.10,0,0.50]`** | 원본의 더 작은 상한 유지. 각 단위 m/s, m/s, rad/s |
| smoother `min_velocity` | `[-0.25,0,-1.5]` | **최소 `[-0.10,0,-0.50]`** | 기존에 허용하지 않던 음의 속도를 새로 허용하지 않음 |

공개 비교값: [P1](SOURCES.md#p1). 의미와 parameter key: [N3](SOURCES.md#n3). 수치 후보는 이 패키지의 제안이며 vendor 권장값이나 주행 시험 결과가 아닙니다.

준비 도구는 속도 상한을 min, 음의 하한을 max로 병합해 더 느린 기존 제한을 확대하지 않습니다. 접근·조절 최저속도도 후보 목표속도보다 커지지 않게 제한합니다. 이 병합은 실제 구동계의 안전을 판정하는 알고리즘은 아닙니다.

### 비용 감속 정합 예시

기존 local inflation이 `0.15`, factor가 `3.0`, RPP cost distance가 `0.60`이라면:

```yaml
# 아래는 이 조건에서 도출되는 예시. 실제 base 값에 따라 달라집니다.
cost_scaling_dist: 0.15
inflation_cost_scaling_factor: 3.0
cost_scaling_gain: 1.0
```

local `inflation_radius` 자체는 변경하지 않습니다. 이미 더 작은 cost distance 또는 gain을 사용하면 그대로 유지합니다. 실제 필요한 물리 이격은 별도 안전 기준으로 평가합니다. [N3, N5](SOURCES.md#n3)

### 속도 상한을 확인할 위치

`desired_linear_vel`은 RPP의 요청값이고, smoother 제한은 해당 smoother를 통과할 때에만 적용됩니다. Teleop·recovery·별도 제어기·ROS bridge가 이를 우회하면 최종 속도가 달라질 수 있습니다.

따라서 controller output→smoother→guard/mux→simulator/모터 입력의 실제 경로와 최종 `/cmd_vel`을 확인합니다. 본 패키지는 mux·motor driver·vendor Gazebo DiffDrive의 설정을 수정하지 않습니다. [P3, P4](SOURCES.md#p3)

## 5. C — Progress checker 선택 시험

| 파라미터 | 공개 비교값 | 처리 |
|---|---:|---|
| `progress_checker.required_movement_radius` | 0.50 m | 후보 **0.05 m**, 이미 더 작은 값이면 유지 |
| `progress_checker.movement_time_allowance` | 10.0 s | **원본 그대로 유지**. 패치에서 덮어쓰지 않음 |

이동 반경을 작게 하면 진척으로 인정하기가 쉬워집니다. 이는 정지·끼임 판정을 느슨하게 만들 수 있으므로 별도 승인이 필요합니다. 정지 상태의 localization 흔들림으로 5 cm 반경을 넘어서면 실제로 움직이지 않았는데 진척으로 보일 수 있습니다. [N6](SOURCES.md#n6)

제자리 회전이 진행으로 인정되는지 역시 사용한 checker 구현에 따라 구분해야 합니다. timeout을 늘려 해결하기 전에 로봇 동작·checker 방식·허용할 회전 단계를 검토합니다. 이 패키지는 다른 progress checker로 교체하지 않습니다.

## 6. 자동으로 변경하지 않는 항목

| 항목 | 이번 처리 | 이유 |
|---|---|---|
| `footprint`, `robot_radius`, `footprint_padding` | 유지 | 실제 로봇·적재 외곽 필요 |
| local/global `inflation_radius` | 유지 | 단순히 통로를 열기 위한 축소 금지 |
| inflation `cost_scaling_factor` | 유지 | 기존 비용장 형상을 임의 변경하지 않음 |
| `use_collision_detection` | 유지, RPP 시험은 기존 true 필수 | 비활성화를 해결책으로 사용하지 않음 |
| `max_allowed_time_to_collision_up_to_carrot` | 유지 | 원본 시간을 줄이지 않음. lookahead 간접 영향은 별도 검토 |
| `transform_tolerance` | 유지 | TF 오류를 허용시간 확대로 숨기지 않음 |
| controller `failure_tolerance` / `costmap_update_timeout` | 유지 | 연산·데이터 지연을 임의 완화하지 않음 |
| smoother `velocity_timeout` | 유지 | command watchdog 새 값 지정 안 함 |
| `max_accel`, `max_decel`, `max_angular_accel` | 유지 | 실제 제동 특성·구동기 검증 필요 |
| 센서 노이즈·주기·range·height 필터 | 유지 | world 변경과 센서 모델 변경을 섞지 않음 |
| obstacle layer enable/marking/clearing | 유지 | 검출·삭제 로직을 끄지 않음 |
| LiDAR 출처·freshness·최소 이격·E-stop | 미확정, 실제 원본 유지 | 사용자 현재 안전설정 미제공 |

준비 도구는 다수 보호 키를 전후 비교하지만, 프로젝트의 모든 사용자 정의 안전키를 이해하는 것은 아닙니다. 별도 안전설정 파일 해시와 실제 runtime dump를 함께 대조합니다.

## 7. 실행 시 다시 확인할 값

아래는 변경을 제안하는 표가 아니라 **측정·기록 대상**입니다.

| 대상 | 공개 자료 또는 이번 문서 기준 | 현장 확인 |
|---|---|---|
| controller frequency | 공개 YAML 20 Hz | 실제 loop deadline·지연·명령 발행주기 |
| local costmap update | 공개 YAML 5 Hz | obstacle 반영지연·CPU 부하 |
| global costmap resolution | 입력 지도 5 mm | static layer 로딩 후 metadata |
| scan update | 공개 Gazebo 모델 10 Hz | 메시지 수신주기와 stamp 간격 |
| scan noise | 공개 모델 σ=0.02 m | 현재 센서 모델의 실제 noise 설정 |
| robot spawn Z | 공개 launch 0.1 m | 정착 후 자세·scan 유효 상태 |
| LiDAR scan plane Z | 사용자 현재 모델 미확인 | 현재 URDF·TF·실측과 벽 높이 대조 |
| runtime package version | Jazzy/Harmonic 검토 대상 | 실제 설치버전·vendor commit 기록 |

근거: [P1, P2, P3](SOURCES.md#p1). 표에 없는 안전 임계값을 임의로 보충하지 않습니다. 요구값이 확정되기 전에는 해당 안전시험을 PASS로 처리하지 않습니다.
