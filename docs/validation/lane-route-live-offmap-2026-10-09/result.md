# 경로 이탈 후 실제 SIM 카메라 재관측

**판정: 경로 이탈 관측 차단 PASS, 차선 추종 수용 HOLD.** 2026-10-09 KST. 모델 PC의 격리 ROS 2/Gazebo에서 `route_a`를 실행했다. 이는 시뮬레이션 전용 정적 `west:r → ring_s:f` 경로이며 운영 `keep` 모드나 실물 로봇이 아니다.

## 입력과 실행

- 전용 작업공간: 모델 PC `~/rosy-ml/scratch/lane-route-gap-live-20261009/`, ROS domain 139, Gazebo partition `rosy_lane_route_gap139`, CORE API 포트 8139. 기존 B9 소스 archive SHA-256 `1934f941668a9a5e273e0bfb592c796837ebff124d92fed906807a374fe50d0b`를 복사하고 **`route_camera.py`만** 로컬 `main`의 `917ad4e89` 내용(SHA-256 `272f8e146550da2c1067d473705964c74ec1c001b1d7f998d25e5e6407befcbc`)으로 바꿨다. 따라서 전체 현재 `main` 이미지 시험이 아니다.
- 기존 [정적 경로 launch](../lane-route-terminal-ros-sim-2026-10-08/evidence/d495_real.launch.py)의 `HERE`만 격리 디렉터리로 바꿨다(SHA-256 `d2f96b031a5b19c7a98e3da872f6953426cee12453e51298d1e3d5380d31542c`). `colcon build --symlink-install --packages-up-to gz_sim core control description`는 시스템 Python과 깨끗한 CMake cache에서 16개 패키지 완료. 시작 자세 `(-1.15,-0.511,0)`, 카메라 320×240·8 Hz, CORE `CAMERA_LINE`, 미리 보낸 `left:60`으로 100초 기록했다.
- [CORE/GT 요약](evidence/route-summary.json): 이동 거리 0.4738 m, 교차로 완료 0건, 마지막 `HOLD/obstacle_ahead` at GT `(-0.739,-0.525,-0.111)`. 849개 상태 표본은 `TRACKING/tracking` 62, `HOLD/obstacle_ahead` 774, `RECOVERING/stuck_back_off` 8, `OFF/mode_off` 5개였다. 원본 `route_run/log.jsonl`은 격리 작업공간에 남겼고 SHA-256은 `e4a449c0a093f716513e328a57af79439431aefba12d596d4ca528122adb172a`다. 이 실행은 기존 B9의 약 3.5초 경계 공백 위치까지 도달하지 못했다.

## 카메라 장면이 바뀐 경로 이탈 반례

위 실행 뒤 CORE를 `OFF`로 둔 채 [관측 스크립트](evidence/offmap_probe.py)로 Gazebo 로봇을 경로 위 `(-1.15,-0.511,0)`, 북쪽 80 mm `(-1.15,-0.431,0)`, 원위치 순서로 놓았다. 매 위치에서 약 3초 동안 `d495/gt`, `camera/front`, `line/observation`을 구독했다. [원본 관측 요약](evidence/offmap-probe.json)의 동일 위치에 대응하는 `CAMERA_LINE` 표본은 아래와 같다.

| 실제 위치 | 대응 표본 | 첫/마지막 `visible` | 마지막 confidence |
|---|---:|---|---:|
| 경로 위 | 24 | true / true | 1.0 |
| 북쪽 80 mm | 24 | false / false | 0.0 |
| 원위치 복귀 | 23 | false / false | 0.0 |

이는 직전 저장 영상의 좌표만 바꾼 반사실 시험과 달리, 각 위치에서 새 카메라 프레임을 받으며 `route_a`가 이탈 뒤 자동 재잠금하지 않은 결과다. 초/말 표본 사이 모든 표본의 가시성은 저장하지 않았으므로 표 전체가 24/24 등의 연속 거절률은 아니다. 이탈 시험 때 CORE는 `OFF`였으므로 **실제 명령 차단 시험으로 해석하지 않는다**. 시험 뒤 해당 partition 프로세스와 API 포트가 종료된 것을 확인했다. 다른 시뮬레이터는 건드리지 않았다.

다음 문제는 별개다. 정적 경로 주행은 장애물 근거에서 HOLD했고 교차로와 B9 경계 공백을 통과하지 못했다. 이 원인을 카메라 경계 기억으로 돌리거나 60 mm를 현장 허용 오차로 승인하지 않는다. 10/6·10/7 원본의 사람 승인 동일 물리 경계 ID·가림 원인·재출현·보이는 도로면 정답은 0건이며, 운영 학습/주행·실물 수용은 HOLD다. 불확실한 경계는 STOP, 최종 `/cmd_vel`은 CORE 단일 권한이다.
