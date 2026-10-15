# OMX 실물 제어 소프트웨어 준비

날짜: 2026-10-15. 브랜치 `feat/omx-hardware-control`.
진단 v1 commit `4697df1b5`, namespace/초기화 보완 v2 commit `731c5ae61`.
목표는 [실물 제어 실행 계획](../../plans/2026-10-15-omx-hardware-control.md)의 G1/G2다.
**실물 제어·정지·보정·딸기 왕복 수용이 아니다.**

## 재현한 단절과 진단

현장 기본 환경은 Ubuntu 26.04.1, Python 3.14.4, ROS Lyrical이며 `/opt/ros/jazzy`는 Lyrical alias다.
기본 환경에는 controller manager 외에 벤더·trajectory/broadcaster·ROSY adapter 6패키지가 없었다.
같은 graph의 팔 Action은 없고 `/joint_states` publisher는 synthetic `joint_state_publisher`였다.
OpenRB 두 개의 OS device 접근은 가능하지만 follower/leader·실제 모터 상태를 확정하지 않았다.

`hardware_readiness.py --domain-id <workcell-domain> --namespace /`는 잠금 파일의 기대 distro,
필수 패키지, 정확한 namespace의 FollowJointTrajectory Action 타입과 publisher FQN을 읽는다.
serial open, controller start/activate, torque, goal, stop/rearm 명령은 없다.
3초 discovery에서 action/pub가 보이지 않았다는 결과는 다른 환경의 전체 장치 부재를 입증하지 않는다.
software positive에서도 motion=false이며 물리 provenance가 검증된 것으로 표시하지 않는다.

원격 RED 뒤 v1 GREEN을 확인했다. 독립 검토에서 초기화 실패의 traceback/exit1과
다른 cell의 Action/pub 혼합을 지적했다. 추가 RED 뒤 v2에서 구조화된 JSON/exit2,
정확한 namespace binding·FQN publisher·cleanup 실패 처리를 구현했다.
선택된 원격 회귀 60시험 통과, known_failures NEW 0. 모델/AI PC의 원격 시험이며 노트북 pytest는 없다.

## 고정 source의 native 비구동 build

기존 `fetch_sources.py`와 `stack.lock.yaml`을 재사용해 공식 allowlist의 immutable source 5저장소를
별도 workspace에 받았다. 설치된 Lyrical을 source한 프로세스에서 아래 8패키지를
`colcon build --executor sequential`, `CMAKE_BUILD_PARALLEL_LEVEL=2`, `BUILD_TESTING=OFF`로 빌드했다.

- open_manipulator_bringup, open_manipulator_description
- om_joint_trajectory_command_broadcaster, dynamixel_hardware_interface, dynamixel_interfaces
- dynamixel_sdk, dynamixel_sdk_custom_interfaces, robotis_interfaces

terminal 결과: **8 packages finished, 1min 29s**, exit 0. 경고/stderr는 있었다.
이후 committed ROSY `omx_adapter`도 별도 prefix에 빌드해 package discovery와 disabled profile CLI의 `{}`를 확인했다.
기본 ROS나 기존 camera unit의 source/env는 변경하지 않았다. 새 overlay는 해당 검증 shell에만 적용했다.

시스템 package install은 비대화형 sudo 인증이 없어 실행되지 않았다.
대신 apt download로 다음 정확한 버전을 받고 `dpkg-deb --extract`로 별도 prefix에만 풀었다.
시스템 설치·maintainer script 실행·service 활성화는 하지 않았다.

| 검증용 패키지 | 고정 버전 |
|---|---|
| joint_trajectory_controller | 6.9.0-1resolute.20260924.145600 |
| joint_state_broadcaster | 6.9.0-1resolute.20260924.145837 |
| control_toolbox | 6.4.0-1resolute.20260924.142824 |
| filters | 2.2.2-3resolute.20260915.080512 |

별도 AMENT/LD prefix로 패키지를 읽었고 trajectory controller와 Dynamixel plugin의 `ldd`는
각각 exit 0·missing libraries 빈 목록이었다. plugin 인스턴스·configure/activate는 실행하지 않았다.
build/link 성공은 ABI/lifecycle/실제 명령·정지 수용을 대체하지 않는다.

overlay의 새 진단: missing_packages=[], 기대 Jazzy/실제 Lyrical 불일치,
trajectory action 없음·hardware state source 없음·synthetic publisher 존재를 계속 거절했다(exit 2).
[overlay readback](evidence/overlay-readiness.json), [library 검사](evidence/native-link-inspection.json),
[package checksum manifest](evidence/overlay-packages.sha256).

## 실행하지 않은 것과 재개 조건

고정 벤더 plugin은 `on_activate`에서 torque enable을 수행한다.
초기화에도 torque 상태 처리/설정이 있어 단순 driver 시작을 비구동 probe로 보지 않았다.
소프트웨어 빌드 뒤에도 controller를 기동하거나 launch하지 않았다.
source lock/Jazzy 지원 계약·기존 disabled profile·SIM driver/API는 바꾸지 않았다.

남은 실제 입력은 follower 물리 역할, 하중/자세, ordered joints/한계, jaw·workspace·TCP/hand-eye,
독립 정지/처짐·전원·통신 장애 및 복구 수용이다. 이 값이 없으면 G3의 감독 측정이 필요하다.
그 뒤 실물 local owner/native instance와 별도 Fleet/Pilot hardware 계약을 구현·검증하고 G6을 수행한다.
이번 준비만으로 실물 제어 구조가 완성됐다고 보고하지 않는다.

원문 build/probe 자료는 비공개 X: 세션 `2026-10-15--042252--inference-integration--f27cbc`의
`logs/omx-hardware-*`, `evidence/omx-hardware-*`에 보관한다. 현장 workspace와 실제 계정/장치 ID는 공개하지 않는다.
