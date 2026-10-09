# 정적 경로 시제품의 ROS 관측 노드 진입 제한

증거 등급: **SOURCE·호스트 pytest·모델 PC ROS 노드 초기화**. 코드 commit `89af5983f`의 두 수정 파일을 모델 PC 전용 작업공간에 빌드했다. 실제 로봇 배포·실물 주행·현장 수용이 아니다. [시작 오차 반례](../lane-route-start-disagreement-2026-10-08/result.md)의 오프라인 −40 mm는 지도 중심선 편차 60.0 mm로 40 mm 목표를 넘으며 주행했다. 반대 ROS-SIM 장면의 0 m 정지는 카메라 미검출 결과일 뿐 정적 `route_start`의 위치 권한을 검증하지 않는다.

`route_a/b/ab`는 첫 odom을 선언 `route_start`에 고정하고 이후 절대 위치로 교정하지 않는 시제품이다. 일반 운영 설정은 `camera_lane_mode: line`이고 운영자 오버레이도 `route_*`를 거절하지만, 대체 전체 설정이나 직접 ROS 인자로는 시제품 모드를 고를 수 있었다. `line_observer_node._build_route_follower()`에서 **GAZEBO 지면 출처·`allow_simulation_ground=true`·`use_sim_time=true`가 동시에 있어야** follower를 만든다. 이 조건이 없으면 node는 구동을 유지하되 `CAMERA_LINE` 후보를 내지 않는다. 조건은 기존 Gazebo 지면 투영의 허용 판정과 같은 순수 함수를 재사용한다. 다른 차선 모드나 CORE의 최종 `/cmd_vel` 발행 경계는 바꾸지 않았다.

호스트에서 실패 테스트를 먼저 확인했다(금지 조건 9 실패, 허용 조건 1 통과). 수정 뒤 해당 10건이 통과했고, `test_camera_ground.py`·`test_line_observer_wiring.py`·`test_route_camera.py`·`test_route_hybrid.py`·`test_route_map.py`는 **181 passed**, `test/known_failures.py` **0 new**였다. 원시 로그는 `X:/DevTemp/lane-goal-20261008/route-admission-{red,green,related}.txt`에 있다.

모델 PC의 전용 `~/rosy_lfstop_ws`에 수정한 `control` 소스 두 파일을 넣고 `colcon build --packages-select control --symlink-install`을 수행해 1 package가 빌드됐다. 같은 `west:r → ring_s:f`와 `route_start=(-1.15,-0.511,0)`을 넣은 [물리 카메라형 설정](evidence/route_admission_physical.yaml)과 [Gazebo 설정](evidence/route_admission_sim.yaml)을 [ROS 노드 확인 스크립트](evidence/route_admission_probe.py)로 각각 초기화했다. `ROS_DOMAIN_ID=105`의 독립 노드이며 카메라·모터·로봇에는 연결하지 않았다.

| 설정 | `_route_follower` readback | 경고 |
| --- | --- | --- |
| `PINKY`, simulation ground false, sim time false | `NoneType` | route prototype requires Gazebo simulation ground and clock |
| `GAZEBO`, simulation ground true, sim time true | `RouteCameraFollower` | route 거절 경고 없음 |

원시 확인 로그 `X:/DevTemp/lane-goal-20261008/route-admission-probe.txt`의 SHA-256은 `01bb10701aca4b2b27aa5fcc51fa554ba2ed435a15b5f5db405ccf8f00edc987`이다. 이는 follower 생성 여부만 검증하며 Gazebo 폐루프나 CORE 명령 수용을 다시 실행한 결과가 아니다.

**판정: 시제품 경로의 기본 물리 카메라 진입 제한 PASS, 운영 차선 추종 HOLD.** 이 조건은 설정에 따른 실험 모드 제한이며 실제 하드웨어 판별·위치 정확도 증명이 아니다. 실제 경로 주행으로 승격하려면 활성 Fleet 지도 버전과 신선한 `LOCALIZED` 지도 자세로 시작을 승인하고 실행 중 재검증해야 한다. 10/6·10/7 동일 물리 경계 사람 검수, 벽/분기 음성, 40 mm 곡선 목표, D-520 통합 폐루프, 실물 R1/R2도 별도 관문이다.
