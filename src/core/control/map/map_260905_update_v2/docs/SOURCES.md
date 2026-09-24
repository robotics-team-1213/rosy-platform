# 출처와 판단 범위

검토일: 2026-09-20  
적용 대상으로 가정한 환경: ROS 2 Jazzy / Gazebo Sim Harmonic(8 계열)

이 문서는 **업로드 원본에서 직접 확인한 사실**, **외부 공식 문서·공개 구현**, **이 패키지의 시험 제안**을 구분합니다. 공개 저장소의 값은 사용자 프로젝트의 현재 실행값이 아닙니다.

## 1. 원본과 계산 결과

<a id="f1"></a>
### F1. 사용자 업로드 및 이전 맵 패키지

- 원본: [`../original/map_260905.world`](../original/map_260905.world)
- 원본 SHA-256: `8475464857322d71f6e492171419bf285e7bd034089b90ad59d6f106b0941072`
- 업데이트: [`../worlds/map_260905.world`](../worlds/map_260905.world)
- 변경 비교: [`../reports/world_changes.diff`](../reports/world_changes.diff)
- 정적 검사 결과: [`../reports/package_validation.json`](../reports/package_validation.json)
- 좌표 추출: [`../reports/wall_geometry.json`](../reports/wall_geometry.json)
- 지도 재생성 도구: [`../scripts/generate_map.py`](../scripts/generate_map.py)

16개 벽의 pose·box size를 계산해 외곽 2.715 × 1.265 m, 두께 10 mm, 높이 155 mm를 얻었습니다. 이는 **시뮬레이션 형상의 계산값**입니다. 실물이나 원본 CAD/STL을 측정·재검증한 값은 아닙니다.

기존 ZIP의 점유 지도와 이번 PGM의 SHA-256은 다음과 같습니다: `d23141945700bf9725bc0c2407425abffe4fa93b1167146bf8f259a35a4cd21c`

원본 주석에 기록된 과거 메시 문제와 STL 검증 이력은 작성자의 당시 설명입니다. 이번 작업에서 해당 STL이나 과거 런타임을 다시 확인하지 않았습니다.

## 2. Pinky 공개 구현 — 참고값

아래 URL은 `main` 브랜치입니다. 검토 시 웹에서 열람했으며 사용자 PC의 파일·설치 버전·실행값과 대조하지 않았습니다. **커밋을 고정한 소스 스냅샷을 첨부한 것은 아닙니다.** 웹 캐시와 이후 브랜치 변경 가능성이 있으므로 실제 적용 시 로컬 파일 해시와 설치 버전을 기록합니다.

<a id="p1"></a>
### P1. Pinky Nav2 참고 설정

[공개 nav2_params.yaml](https://raw.githubusercontent.com/pinklab-art/pinky_pro/main/pinky_navigation/params/nav2_params.yaml)

문서 비교표의 goal tolerance, progress checker, RPP, costmap, footprint, velocity smoother 참고값의 출처입니다. 이 파일 전체를 실제 로봇 설정으로 배포하거나 복사하지 않았습니다. 사용자 현재 설정을 받으면 먼저 차이를 확인해야 합니다.

<a id="p2"></a>
### P2. Pinky 시뮬레이션 launch

[공개 launch_sim.launch.xml](https://raw.githubusercontent.com/pinklab-art/pinky_pro/main/pinky_gz_sim/launch/launch_sim.launch.xml)

`world` 인자와 로봇 생성 위치 등의 참고 근거입니다. 패키지 내부에서 vendor launch를 수정하지 않았으며 설치본의 `--show-args`와 본문을 확인해야 합니다.

<a id="p3"></a>
### P3. Pinky 시뮬레이션 로봇·센서

[공개 pinky_gz.urdf.xacro](https://raw.githubusercontent.com/pinklab-art/pinky_pro/main/pinky_description/urdf/pinky_gz.urdf.xacro)

LiDAR 주기·노이즈와 Gazebo 구동 플러그인 설정의 참고 근거입니다. 사용 중인 전개 URDF, 실제 스캔 높이, 로봇 전체 collision 외곽을 확인한 자료는 아닙니다.

<a id="p4"></a>
### P4. Pinky ROS–Gazebo 브리지

[공개 pinky_bridge.yaml](https://raw.githubusercontent.com/pinklab-art/pinky_pro/main/pinky_gz_sim/params/pinky_bridge.yaml)

스캔·오도메트리·TF·시계·명령 연결을 검토할 때 사용하는 참고 자료입니다. 실제 remapping, namespace, mux, guard 및 모터 입력 경로는 프로젝트에서 별도 확인합니다.

## 3. Gazebo·SDFormat

<a id="g1"></a>
### G1. Gazebo Sim 8 — Physics engines

[Gazebo 공식 Physics engines 문서](https://gazebosim.org/api/sim/8/physics.html)

DART 기본 엔진, Physics 시스템의 `engine/filename` 지정, 엔진 로딩 점검 근거입니다. `physics type` 문자열만으로 실제 실행 엔진을 판정하지 않는 이유를 설명합니다.

<a id="g2"></a>
### G2. SDFormat 1.6 — Physics

[SDFormat 1.6 physics 스키마](https://sdformat.org/spec/1.6/physics/)

물리 프로파일 이름·type과 시간 설정의 형식·의미를 확인하는 근거입니다. XML 파싱 통과와 실제 `gz sdf`/플러그인 로딩 통과는 구분합니다.

<a id="g3"></a>
### G3. ROS–Gazebo 배포판 조합

[Gazebo Harmonic ROS 설치 문서](https://gazebosim.org/docs/harmonic/ros_installation/)

ROS 2 Jazzy와 Gazebo Harmonic 조합을 검토 기준으로 사용한 근거입니다. 사용자 설치 환경을 확인했다는 의미는 아닙니다.

## 4. Nav2 — 파라미터와 동작

가능한 항목은 `jazzy` 구현을 우선 참고했습니다. 아래 브랜치 링크도 이후 바뀔 수 있습니다. 최신 웹 문서에 새 파라미터가 있더라도 Jazzy의 선언과 의미를 먼저 확인합니다.

<a id="n1"></a>
### N1. NavFn planner tolerance

[NavFn 설정 문서](https://docs.nav2.org/configuration/packages/configuring-navfn.html)

`GridBased.tolerance`, `allow_unknown` 의미의 근거입니다. planner tolerance는 요청한 목표와 경로 끝점 사이의 허용범위이며, goal checker의 도착 판정과 구분합니다.

<a id="n2"></a>
### N2. SimpleGoalChecker

[Jazzy SimpleGoalChecker 구현](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_controller/plugins/simple_goal_checker.cpp)  
[SimpleGoalChecker 설정 문서](https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_goal_checker.html)

XY·yaw tolerance와 `stateful` 동작의 근거입니다. 설정한 tolerance 자체가 물리 위치 정확도 보증은 아닙니다. 최신 문서에만 있는 옵션은 이번 패치에 추가하지 않았습니다.

<a id="n3"></a>
### N3. Regulated Pure Pursuit — Jazzy

[Jazzy RPP 설명 및 파라미터 표](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_regulated_pure_pursuit_controller/README.md)  
[Jazzy RPP parameter_handler.cpp](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_regulated_pure_pursuit_controller/src/parameter_handler.cpp)  
[현재 RPP 웹 설정 문서](https://docs.nav2.org/configuration/packages/configuring-regulated-pp.html)

Jazzy의 `desired_linear_vel`, lookahead, collision prediction, cost distance/gain, inflation factor 연동의 근거입니다. 웹 최신 문서와 Jazzy의 파라미터 이름 차이에 유의합니다. 문서의 시험 후보 수치는 이 패키지의 제안이며 공개 구현의 권장 튜닝값을 인용한 것이 아닙니다.

<a id="n4"></a>
### N4. StaticLayer 해상도·크기 반영

[Jazzy StaticLayer 구현](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_costmap_2d/plugins/static_layer.cpp)

비-rolling 전역 costmap이 수신 지도 크기·해상도에 맞춰 조정되는 동작의 근거입니다. 실행 YAML의 `resolution`과 런타임 metadata를 따로 확인합니다.

<a id="n5"></a>
### N5. Inflation 비용 분포

[Inflation 설정 문서](https://docs.nav2.org/configuration/packages/costmap-plugins/inflation.html)

inflation radius와 cost scaling factor가 비용 분포에 관여한다는 근거입니다. 이 링크는 최신 문서이므로 Jazzy에 없는 신규 옵션을 추가하는 자료로 사용하지 않았습니다. inflation radius를 모든 상황의 하드 최소 이격거리로 취급하지 않습니다.

<a id="n6"></a>
### N6. SimpleProgressChecker

[SimpleProgressChecker 설정 문서](https://docs.nav2.org/configuration/packages/nav2_controller-plugins/simple_progress_checker.html)  
[Jazzy SimpleProgressChecker 구현](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_controller/plugins/simple_progress_checker.cpp)

`required_movement_radius`와 `movement_time_allowance`의 의미를 확인한 근거입니다. radius 축소는 진척 인정 조건을 바꾸므로 감속처럼 단순한 안전 강화로 해석하지 않습니다.

<a id="n7"></a>
### N7. 지도 읽기와 픽셀 분류

[Jazzy Map IO 구현](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_map_server/src/map_io.cpp)

origin·resolution·trinary threshold 및 이미지 행과 지도 Y축 처리의 근거입니다. 이번 지도는 벽과 양의 면적으로 겹치는 셀을 occupied로 분류하는 별도 재생성 정책을 사용합니다. 이 정책은 converter와 검사 보고서에 기록했습니다.

<a id="n8"></a>
### N8. 좌표 변환 구성

[Nav2 Transform 설정 가이드](https://docs.nav2.org/setup_guides/transformation/setup_transforms.html)

`map → odom → base → sensor` 역할과 TF 연결 확인의 근거입니다. 지도 파일은 TF 발행자나 위치 추정기를 대신하지 않습니다.

<a id="n9"></a>
### N9. Costmap·footprint

[Jazzy Costmap 2D 설정 문서](https://docs.nav2.org/jazzy/configuration_and_development/configuration_guide/core_servers/costmap_2d/)

footprint, robot radius, padding 등 검토 항목의 근거입니다. 현재 로봇 외곽 크기와 안전 여유를 정하는 근거는 사용자 실측·프로젝트 승인 기준이어야 합니다.

<a id="n10"></a>
### N10. 표준 Nav2 bringup 예시

[Jazzy bringup_launch.py](https://raw.githubusercontent.com/ros-navigation/navigation2/jazzy/nav2_bringup/launch/bringup_launch.py)

`map`, `params_file`, `use_sim_time`, `autostart` 인자의 근거입니다. 제공한 명령은 준비 단계의 예시이고 사용자 프로젝트의 실제 lifecycle·guard 연결을 대체하지 않습니다.

## 5. 시험 제안과 미확정 사항

본 패키지가 제안한 goal·planner tolerance, RPP 저속/추종거리, progress 반경 및 반복시험 횟수는 **시뮬레이션 평가용 시작점**입니다. 외부 기관의 안전 인증 기준이나 사용자 실기 운전 승인값이 아닙니다.

실제 footprint, minimum clearance, LiDAR freshness, 모터 watchdog, 정지 지연, 제동능력, 신뢰 가능한 스캔 출처, 명령 경로의 현재 값은 제공되지 않았습니다. `safety_review_template.yaml`에 `null`로 남겼습니다. `null`은 0 또는 비활성화를 뜻하지 않습니다.

정지거리 식, raster 오차 상한, 연결성 계산, 셀 수 비교는 각 문서에 명시한 가정에 따른 계산·설계 판단입니다. 실제 Gazebo와 ROS/하드웨어 실행 결과는 아닙니다.
