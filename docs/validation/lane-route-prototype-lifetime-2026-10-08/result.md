# 정적 경로 시제품의 실행 중 Gazebo 조건 폐기

[초기 진입 제한](../lane-route-prototype-admission-2026-10-08/result.md)은 ROS 노드 시작 때 `route_a/b/ab`의 시뮬레이션 조건을 검사한다. `camera_ground_source`와 `allow_simulation_ground`는 실행 중 바뀔 수 있으므로, 이미 만든 follower가 조건 변경 뒤에도 남는 틈을 별도로 확인했다. 이 후속 수정은 route 모드의 **유효 카메라 프레임마다** Gazebo 지면 출처·simulation ground 허용·sim time을 다시 검사한다. 하나라도 깨지면 follower를 폐기하고 관측 없음으로 닫으며, 값을 되돌려도 재생성하지 않는다. 다른 모드와 CORE의 최종 명령 발행은 수정하지 않았다.

호스트 AST 관측 콜백 테스트는 먼저 재현됐다: Gazebo 조건의 첫 프레임에서 후보가 나온 뒤 `camera_ground_source=NOMINAL`로 바꾼 다음 프레임에도 기존 후보가 계속 나와 **1 failed**. 첫 수정에서는 지면 생성이 `ValueError`를 내면 follower 폐기 검사 전에 빠지는 것도 실패 테스트로 확인했다. 조건 검사를 지면 생성 앞으로 옮긴 뒤 같은 테스트와 기존 진입 조건 10건이 **11 passed**, `test/known_failures.py` **0 new**였다. 원시 로그는 `X:/DevTemp/lane-goal-20261008/route-admission-lifetime-{red,green,ground-error-red,ground-error-green}.txt`에 있다.

모델 PC 전용 `~/rosy_lfstop_ws`에서 바뀐 `control`을 다시 빌드했다(`colcon`: 1 package finished). [독립 ROS 노드 확인 스크립트](evidence/route_admission_lifetime_probe.py)에 앞선 [Gazebo 설정](../lane-route-prototype-admission-2026-10-08/evidence/route_admission_sim.yaml)을 주어 domain 106에서 시작했다. 영상은 모터나 실제 카메라가 아닌 스크립트 내부의 320×240 일정 밝기 프레임이다.

| 단계 | ROS 파라미터 변경 결과 | follower readback |
| --- | --- | --- |
| Gazebo 설정으로 초기화 | 시작 | `RouteCameraFollower` |
| 지면 출처를 `PINKY`로 변경하고 유효 프레임 1개 처리 | `successful=True` | `NoneType`, 폐기 경고 |
| 지면 출처를 `GAZEBO`로 되돌리고 프레임 1개 처리 | `successful=True` | 계속 `NoneType` |

원시 로그 `X:/DevTemp/lane-goal-20261008/route-admission-lifetime-probe.txt`의 SHA-256은 `1ee76bbd3e44e0ab593efd93c4cd22fd63748c395575d530c9ef4d6719a7d6a4`다. 실제 ROS 노드의 파라미터 변경과 follower 폐기는 확인했지만, 이 테스트는 주행 명령 수용이나 Gazebo 폐루프, 하드웨어 판별을 시험하지 않았다.

**판정: 시작 뒤 시뮬레이션 조건 상실 시 관측 폐기 PASS.** 설정값 자체는 실제 장치를 증명하지 않는다. 세 시뮬레이션 값을 물리 로봇의 대체 설정에 함께 주는 행위까지 막으려면 장치 신원과 활성 Fleet 지도·신선한 지도 자세를 별도 권한으로 연결해야 한다. 그 전에는 정적 경로 시제품을 운영 차선 추종으로 수용하지 않는다.
