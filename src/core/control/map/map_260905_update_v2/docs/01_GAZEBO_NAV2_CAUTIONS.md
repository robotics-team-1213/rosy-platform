# Gazebo·Nav2 적용 주의사항 및 절차

버전: v2 / 2026-09-20  
적용 대상: MAP 260905, Gazebo Sim Harmonic / ROS 2 Jazzy 검토 프로파일

## 1. 이번 업데이트의 범위

이 패키지는 **업로드된 월드를 기준으로 환경 파일을 정리하고, 기존 프로젝트의 주행 설정을 검토할 수 있게 만든 자료**입니다.

원본의 모든 정적 모델과 16개 벽 형상을 유지했습니다. 바꾼 것은 월드 주석, 물리 프로파일 이름·엔진 지정, 도면의 설명, 문서와 검토 도구입니다. 로봇 URDF·vendor launch·실기 안전설정은 제공되지 않아 수정하지 않았습니다. 월드의 실제 변경은 `../reports/world_changes.diff`로 확인할 수 있습니다. [F1](SOURCES.md#f1)

이 문서의 숫자는 세 종류입니다.

| 구분 | 의미 |
|---|---|
| 원본에서 확인 | 업로드된 월드의 실제 XML 값 |
| 계산·출력 정책 | 좌표 계산 또는 이번 지도 생성 시 선택한 값 |
| 시뮬레이션 시험 제안 | 실행 전 검증이 필요한 튜닝값. 안전 인증값·성능 보장값 아님 |

공개 Pinky 저장소 값은 비교 자료이며, 현재 우리 설치본의 실제 파라미터와 같다고 가정하지 않습니다. [P1](SOURCES.md#p1)

## 2. 치수는 ‘모델 치수’와 ‘실물 치수’를 구분합니다

| 항목 | 원본 주석 | 원본 형상으로 계산한 값 |
|---|---:|---:|
| 외곽 | 2.710 × 1.260 m | 2.715 × 1.265 m |
| 벽 두께 | 0.005 m | 0.010 m |
| 벽 높이 | 0.155 m | 0.155 m |

이번에는 **형상을 임의로 5 mm로 바꾸지 않았습니다.** 새 주석에 시뮬레이션 형상 치수를 기록하고, 원본 주석과 차이가 있었음을 남겼습니다. 실측·CAD/STL이 없으므로 어느 값이 실물에 맞는지는 확정하지 않았습니다. [F1](SOURCES.md#f1)

모델 외곽은 X `[-1.3575, 1.3575]`, Y `[-0.6325, 0.6325]` m입니다. 선택 구간의 벽 표면 간격은 오른쪽 외곽 `0.289950 m`, 오른쪽 내부 `0.285000 m`, 왼쪽 외벽과 X자 끝의 국소 간격 `0.272196 m`입니다. 이는 전체 주행 경로의 최소 여유 폭 판정이 아닙니다. 계산 내역은 `../reports/validation_report.json`에 있습니다.

**실물이 다르다는 것이 확인되면:** 물리 기준을 먼저 확정하고 world→점유 지도→도면을 함께 재생성합니다. 점유 지도만 넓히거나 벽 픽셀만 지워서 통과시키지 않습니다.

## 3. Gazebo 엔진 설정

업데이트된 월드에는 다음 설정이 있습니다.

```xml
<plugin filename="gz-sim-physics-system"
        name="gz::sim::systems::Physics">
  <engine>
    <filename>gz-physics-dartsim-plugin</filename>
  </engine>
</plugin>

<physics name="track_1ms" type="dart">
  <real_time_update_rate>1000.0</real_time_update_rate>
  <max_step_size>0.001</max_step_size>
  <real_time_factor>1</real_time_factor>
</physics>
```

Gazebo Sim의 엔진 지정은 Physics 시스템의 engine 설정이 핵심입니다. `type="dart"`는 명시한 엔진과 표현을 맞추기 위한 것이며, 이 속성만으로 로드 엔진을 판정하지 않습니다. DART를 찾지 못하면 설치·플러그인 경로를 확인하고, 다른 엔진으로 조용히 바꾸지 않습니다. [G1, G2](SOURCES.md#g1)

`0.001 s`와 실시간 배율 목표 `1`은 원본 값을 보존한 것입니다. `1000`이 적혀 있어도 실제 모든 처리 루프가 1 kHz를 달성한다는 보장이 아닙니다. 실제 `/clock` 진행, real-time factor, 제어주기, 센서주기를 기록해야 합니다. [G2](SOURCES.md#g2)

벽의 `<surface><friction><ode>…` 값도 보존했습니다. 태그 이름이 `ode`라는 이유만으로 전체 시뮬레이터가 ODE로 동작한다고 판단하거나, 해당 속성이 DART에서 어떻게 적용되는지 검증하지 않고 마찰 성능을 확정하지 않습니다.

기존 GUI 카메라 설정은 그대로입니다. Harmonic에서 원하는 초기 시점이 적용되지 않으면 GUI 설정을 따로 검토합니다. 카메라 시점 문제와 물리 충돌 문제를 혼동하지 않습니다.

## 4. 지도 입력과 좌표

`maps/map_260905.yaml`과 PGM만 Nav2 입력으로 사용합니다. 치수선·제목·원점 표시가 들어간 `review/`의 PNG/SVG는 입력 지도가 아닙니다.

지도는 `600 × 300`, 해상도 `0.005 m/cell`, 원점 `[-1.5, -0.75, 0.0]`입니다. 원점은 이미지의 왼쪽 아래가 world 좌표에서 놓이는 위치이지, 로봇 생성 위치가 아닙니다. 픽셀은 벽 `0`, 트랙 내부 빈 공간 `254`, 트랙 외부 unknown `205`로 출력했습니다. 이는 world 전체 바닥을 주행 가능 영역으로 취급하지 않기 위한 출력 정책입니다. [F1, N7](SOURCES.md#n7)

셀과 벽 박스가 양의 면적으로 겹치면 occupied로 표시합니다. 얇은 벽을 없애지 않기 위한 보수적 래스터화입니다. 경계는 최대 한 셀 대각선 수준의 범위 내에서 바깥쪽으로 표현될 수 있습니다. 5 mm 격자의 한 셀 대각선은 약 7.1 mm입니다. 이 격자 효과와 로봇 footprint padding은 서로 다릅니다.

전역 static layer를 쓰는 비-rolling costmap은 수신 지도의 크기·해상도에 맞춰 재설정될 수 있습니다. **기존 YAML에 전역 resolution이 0.05라고 적혀 있다는 이유만으로, 실제 전역 costmap도 계속 5 cm라고 단정할 수 없습니다.** 실행 후 `/global_costmap/costmap`의 metadata를 확인합니다. [N4](SOURCES.md#n4)

좌표 연결은 다음 역할을 분리합니다. [N8](SOURCES.md#n8)

```text
map → odom → base_footprint / base_link → LiDAR frame
```

지도 로딩만으로 localization이 생기지는 않습니다. AMCL 또는 SLAM 등 `map→odom` 공급자를 하나로 정하고, 생성 pose·초기 위치·map/world 정렬을 대조합니다. 원점을 맞추려고 임의의 정적 `map→odom`을 동시에 추가하지 않습니다.

## 5. ‘벽이 없는 곳’과 ‘갈 수 있는 곳’은 다릅니다

X자 아래 삼각형은 벽이 없지만 외부 주행 구역과 연결되지 않은 공간입니다. 해당 영역을 흰색으로 유지한 것은 물리 형상을 보존한 것이며, 통행 허용을 뜻하지 않습니다. world·지도 모두에서 구멍을 새로 만들지 않았습니다. [F1](SOURCES.md#f1)

테스트 목표 예시는 `(-0.7518, -0.54)` m입니다. 로봇이 주행 구역에서 시작했다면 그 공간으로 들어가는 경로가 나오지 않아야 합니다. 실제 로봇 footprint가 그 목표 pose에 놓일 수 있는지도 별도 확인합니다.

NavFn의 goal tolerance와 goal checker의 tolerance는 서로 다른 값입니다. 경로 끝점이 요청 지점과 다를 수 있으므로, 액션 결과의 `SUCCEEDED`만 보지 말고 **요청 goal 대비 최종 위치·자세 오차**를 직접 기록합니다. 이 구분은 벽 근처 목표와 고립 영역 시험에서 특히 중요합니다. [N1, N2](SOURCES.md#n1)

## 6. Footprint와 안전 기준

실제 로봇의 footprint와 안전 임계값은 이번 업로드에 없습니다. 아래 항목을 임의로 정하지 않았습니다.

- 실제 footprint, robot_radius, padding, 최소 벽 이격
- 실기 LiDAR 출처 판정, scan freshness, command watchdog, 정지 지연 기준
- 실제 braking 성능, 적재물·돌출물의 외곽

`config/robot.yaml` 등 프로젝트의 승인된 안전 원본이 있다면 그 값과 해시를 먼저 기록합니다. `safety_review_template.yaml`의 null은 **미확정**이며, 0이나 사용하지 않음이 아닙니다.

직선 통로의 1차 검토는 `로봇 폭 + 좌우 여유 ≤ 통로 폭`이지만, 코너에서는 방향에 따른 외곽 변화와 전체 회전 궤적을 검사해야 합니다. URDF의 collision 형상과 Nav2 footprint가 서로 다른지, local/global의 published footprint가 서로 다른지도 확인합니다. [N9](SOURCES.md#n9)

Inflation은 장애물 주위의 비용 분포입니다. inflation 반경 자체가 모든 방향에서 보장되는 하드 최소 이격거리는 아닙니다. 통과시키려고 footprint를 줄이거나 collision detection을 끄는 조정을 하지 않습니다. [N5, N9](SOURCES.md#n5)

## 7. Lookahead는 추종 성능뿐 아니라 충돌 예측과도 연결됩니다

RPP에서 lookahead를 줄이면 코너 추종이 좋아질 가능성이 있지만, 충돌 예측이 carrot까지로 제한되므로 검사하는 공간도 줄어들 수 있습니다. **충돌 예측 시간 파라미터를 유지했다는 사실만으로 안전 여유가 유지되었다고 결론 내릴 수 없습니다.** [N3](SOURCES.md#n3)

직선 등속 접근을 단순화한 검토식은 다음과 같습니다. 이는 별도 안전 제어기를 대체하지 않습니다.

```text
필요 정지 여유 ≈ v × 관측·통신·제어 지연 + v² / (2 × 검증된 감속도)
                 + 위치·격자 오차 여유 + 프로젝트에서 승인한 추가 여유
```

대략적인 예측 길이는 직선에서 `min(v × 예측시간, 실제 carrot 거리)`로 생각할 수 있으나, 곡선·회전에서는 실제 footprint 투영 궤적으로 검사해야 합니다. 시뮬레이션을 일시정지하거나 센서 입력을 지연시킨 시험도 포함합니다.

RPP 선택 패치는 `--ack-lookahead-reviewed`를 요구합니다. 이 옵션은 검토 사실을 표시하는 절차일 뿐, 실제 제동거리나 하드웨어 분리를 검증하는 장치가 아닙니다.

## 8. 센서와 실기/시뮬레이션 분리

벽은 Z `0~0.155 m`입니다. 현재 사용하는 로봇의 실제 스캔면이 이 범위 안에 있어야 벽을 감지할 수 있습니다. 앞선 설명의 공개 모델 높이 참고값을 실측값으로 사용하지 말고, 현재 전개된 URDF·TF와 안정적으로 바닥에 놓인 자세로 다시 확인합니다. [F1](SOURCES.md#f1)

공개 Pinky 시뮬레이션 참조 설정에는 scan `10 Hz`, Gaussian 표준편차 `0.02 m`가 있고, launch의 로봇 생성 Z는 `0.1 m`입니다. 이는 사용자 현재 설치본을 확인한 값이 아닙니다. 바닥에 정착하기 전 스캔과 정착 후 스캔을 구분하고, 5 mm 지도 해상도를 5 mm 센서 정확도로 해석하지 않습니다. [P2, P3](SOURCES.md#p2)

실기와 시뮬레이션은 각자의 domain·namespace·Gazebo partition·명령 경로를 명시적으로 관리합니다. namespace나 ROS domain 구분만으로 보안·물리 분리가 완성되었다고 간주하지 않습니다. bridged topic과 최종 모터 명령 수신자를 확인해야 합니다.

특히 실기 모드의 LiDAR guard는 시뮬레이션 스캔을 허용하도록 약화시키지 않습니다. `frame_id` 문자열만으로 실제 하드웨어 출처를 증명하지도 않습니다. 검증용 입력 주입은 모터가 격리된 시험 환경에서만 수행합니다.

시뮬레이션 시간이 멈췄을 때 ROS 시간 기반 timeout도 멈출 수 있다는 점을 고려해야 합니다. 실기 모터가 실수로 연결된 상태에서 시뮬레이션의 `/clock`에 정지 보호를 의존하지 않습니다. 별도의 실기 정지·watchdog 요구사항을 유지합니다.

이번 패키지는 실기 guard 코드를 구현하거나 수정한 것이 아닙니다. 이 항목들의 검증 완료도 주장하지 않습니다.

## 9. 파라미터는 단계별로 준비합니다

| 단계 | 적용 내용 | 제외되는 내용 |
|---|---|---|
| A: 기본 패치 | Goal/Planner 허용오차, 지도·costmap 설정, 기존 표준 Nav2 노드의 sim time | 속도·lookahead·progress 변경 |
| B: RPP 선택 시험 | 저속 목표, lookahead, 비용 감속 관계, smoother 상·하한 | footprint·inflation·collision horizon 시간·watchdog 변경 |
| C: Progress 선택 시험 | 작은 트랙용 이동 반경 제안 | 기존 movement_time_allowance 변경 |

기본 패치도 실기 승인 설정은 아닙니다. 원본이 더 작은 goal tolerance나 로컬 resolution을 사용하면 준비 도구가 그 작은 값을 유지합니다.

지원하는 구조는 namespacing 전의 표준 Nav2 YAML과 문서에 표시한 plugin ID입니다. plugin 이름·구조가 다르면 도구는 실패하도록 만들었습니다. DWB·MPPI 등의 설정에 RPP 값을 자동으로 끼워 넣지 않습니다. 동작의 세부 내용은 [파라미터 기준표](02_PARAMETER_REFERENCE.md)를 확인합니다.

## 10. 준비·실행 명령

아래는 Ubuntu 터미널 기준이며 실제 설치환경에서 실행합니다. 이 작업 환경에서는 실행하지 않았습니다.

### 10.1 환경과 원본 기록

압축을 푼 패키지 루트에서:

```bash
export MAP_PKG="$(pwd)"
export BASE_NAV2="/absolute/path/to/your/nav2_params.yaml"

# ROS 작업 환경은 기존 프로젝트의 절차대로 source합니다.
echo "$ROS_DISTRO"
gz sim --versions
ros2 pkg prefix pinky_gz_sim
ros2 pkg prefix nav2_bringup

mkdir -p "$MAP_PKG/docs/validation/runtime"
sha256sum "$BASE_NAV2" > "$MAP_PKG/docs/validation/runtime/base_nav2.sha256"

# 실제 안전 원본이 있는 경우 별도로 해시를 기록합니다.
# sha256sum /your/project/config/robot.yaml
```

실기와 다른 ROS_DOMAIN_ID·필요한 GZ_PARTITION을 **프로젝트에서 확인 후** 정하고, 모든 시뮬레이션 터미널에 동일하게 설정합니다. 이 문서는 임의의 고정 domain 번호를 배정하지 않습니다.

### 10.2 정적 검사와 변경 예정값 확인

```bash
python scripts/validate_bundle.py
python -m unittest discover -s tests -v

# 기본값: 보고서만 출력. 파일 저장·ROS 노드 실행 없음.
python scripts/prepare_sim_params.py --base "$BASE_NAV2"
```

기존의 full YAML이 없으면 공개 vendor YAML로 대체해 실기용 설정처럼 사용하지 않습니다. 실제 프로젝트 파일이 준비될 때까지 설정 적용을 보류합니다.

### 10.3 기본 시뮬레이션 YAML을 새 파일로 저장

footprint 검토·실기 분리 확인을 마친 뒤:

```bash
python scripts/prepare_sim_params.py \
  --base "$BASE_NAV2" \
  --output "$MAP_PKG/local/nav2_sim_core.yaml" \
  --write --ack-simulation-only --ack-footprint-reviewed
```

기존 경로에 덮어쓰지 않습니다. 새 YAML 옆에 `.review.json`이 생기며 원본 해시·실제 변경 목록이 기록됩니다. YAML 내 주석은 병합 파일에서 유지되지 않을 수 있으므로 원본을 보관합니다.

### 10.4 월드·로봇 실행

```bash
# 실제 Gazebo SDFormat parser 검사. 이 패키지의 XML 파싱 검사와 별도입니다.
gz sdf -k "$MAP_PKG/worlds/map_260905.world"

# world 인자 지원 여부는 현재 설치본에서 먼저 확인합니다.
ros2 launch pinky_gz_sim launch_sim.launch.xml --show-args

ros2 launch pinky_gz_sim launch_sim.launch.xml \
  world:="$MAP_PKG/worlds/map_260905.world"
```

위 vendor launch 사용법은 공개 소스의 `world` 인자를 근거로 한 예시입니다. 설치본과 다르면 해당 launch를 확인합니다. 이와 동시에 다른 `gz sim` 서버를 같은 world·partition으로 중복 실행하지 않습니다. [P2](SOURCES.md#p2)

월드만 검사하는 별도 상황에서는 `gz sim -v 4 …`를 사용할 수 있으나, 이는 로봇·bridge·Nav2를 함께 띄우는 명령이 아닙니다.

### 10.5 Nav2 실행 준비

이미 프로젝트가 Nav2를 띄우면 그 launch의 map·params 입력을 바꿉니다. 두 번째 Nav2 stack이나 map_server를 추가 실행하지 않습니다.

기존 프로젝트 launch를 쓰지 않는 별도 시험에서의 표준 Nav2 bringup 예시:

```bash
ros2 launch nav2_bringup bringup_launch.py \
  map:="$MAP_PKG/maps/map_260905.yaml" \
  params_file:="$MAP_PKG/local/nav2_sim_core.yaml" \
  use_sim_time:=true \
  use_composition:=false \
  autostart:=false
```

`autostart=false`는 준비용입니다. 표준 노드를 구성·활성화하는 절차는 프로젝트의 lifecycle 관리 방식에 맞춰 진행합니다. 이 명령만 실행하면 곧바로 주행 준비가 끝나는 것은 아닙니다. [N10](SOURCES.md#n10)

### 10.6 실제 적용값·토픽 확인

```bash
ros2 node list
ros2 topic info /scan -v
ros2 topic info /clock -v
ros2 topic info /cmd_vel -v

ros2 param get /controller_server use_sim_time
ros2 param get /controller_server general_goal_checker.xy_goal_tolerance
ros2 param get /planner_server GridBased.tolerance
ros2 param get /local_costmap/local_costmap resolution

ros2 param dump /controller_server > docs/validation/runtime/controller_server.yaml
ros2 param dump /planner_server > docs/validation/runtime/planner_server.yaml
ros2 param dump /local_costmap/local_costmap > docs/validation/runtime/local_costmap.yaml
ros2 param dump /global_costmap/global_costmap > docs/validation/runtime/global_costmap.yaml

ros2 topic echo /map --once --field info
ros2 topic echo /global_costmap/costmap --once --field info
ros2 run tf2_ros tf2_echo map base_footprint
```

namespace·노드 이름이 다르면 실제 graph에 맞춰 바꿉니다. lifecycle이 아직 configure되지 않았다면 plugin 파라미터나 토픽이 준비되지 않을 수 있습니다.

`use_sim_time`은 준비 도구가 다루는 표준 Nav2 블록 외에 robot_state_publisher, RViz, SLAM, 별도 guard와 관련 노드도 확인해야 합니다. 외부 launch 재작성으로 값이 덮어써지는지도 dump로 확인합니다.

### 10.7 RPP·Progress 추가 시험

우선 쓰기 없이 변경 내용을 봅니다.

```bash
python scripts/prepare_sim_params.py \
  --base "$BASE_NAV2" --rpp-trial --progress-trial
```

정지거리와 lookahead 검토를 마친 경우에만 새 RPP 파일을 만듭니다.

```bash
python scripts/prepare_sim_params.py \
  --base "$BASE_NAV2" \
  --output "$MAP_PKG/local/nav2_sim_rpp_trial.yaml" \
  --rpp-trial --write \
  --ack-simulation-only --ack-footprint-reviewed --ack-lookahead-reviewed
```

Progress 변경까지 승인하면 `--progress-trial --ack-progress-reviewed`를 추가합니다. **이동 반경을 줄이는 것은 작은 움직임도 진척으로 인정하는 변경**이므로, 정지 상태의 위치 추정 흔들림이 진척으로 오인되지 않는지 먼저 시험합니다.

각 단계는 이전 결과를 보관한 후 하나씩 비교합니다. 병합 파일을 바꿨는데 동작이 다르면 parameter dump·launch 경로·hash부터 확인합니다.

## 11. 성능·검증 구분

로컬 costmap이 3 × 3 m라고 가정하면, 해상도를 0.05→0.01 m로 바꿀 때 셀 수는 3,600→90,000으로 25배가 됩니다. 이것이 CPU 사용량이 정확히 25배라는 뜻은 아니지만 측정이 필요합니다. 카메라·센서·costmap·물리 성능을 함께 기록합니다.

작은 지도에서 주행 성공했다는 결과와 SLAM 성능은 다릅니다. 이 지도는 **world에서 만든 기준 지도**입니다. SLAM 시험에서는 별도로 수집한 센서 지도를 이 기준에 정렬해 비교하고, 생성 지도와 기준 지도 데이터를 섞어 성능이 좋아 보이게 만들지 않습니다.

## 12. 중단·복구 조건

필수 plugin 로드 실패, 예상 밖 motor publisher, source/clock 혼선, 지도/scan의 지속적 어긋남, 침투·관통, 보호기준 위반이 보이면 시험을 중단합니다. timeout·footprint·inflation을 완화해 우회하지 않습니다.

원복은 저장한 기존 launch·Nav2 YAML과 `original/map_260905.world`를 사용합니다. 도구가 원본을 덮어쓰지 않으므로 새 파일 참조만 되돌릴 수 있습니다. 안전 관련 설정·실기 guard의 원본 해시도 전후 동일한지 확인합니다.
