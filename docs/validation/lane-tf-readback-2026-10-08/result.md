# 차선 녹화용 TF·카메라 시각 읽기 전용 확인

2026-10-08, 소스 기준 로컬 `main` `d90f9167d`. 두 로봇의 설치 릴리스는 앞선 [준비 기록](../lane-capture-readiness-2026-10-08/result.md)에서 확인한 `2026.10.08-053`이다. `9fc0a761f`의 TF 녹화 변경은 로컬 소스에만 있으며 이 장치에 배포됐다는 증거는 없다. SSH BatchMode로 서비스의 ROS domain과 RMW 설정만 읽고, 해당 domain의 `rclpy` 노드로 토픽 이름·게시자·메시지를 구독했다. 장치 설정, 녹화 서비스, 주행 명령은 변경하지 않았다.

| 로봇 | `/tf` | `/tf_static` | 6초 카메라/동적 TF | 카메라 stamp에서 가장 가까운 `odom→base_footprint` TF stamp |
|---|---:|---:|---:|---|
| `rosy_26` | 게시자 2, 4초 19메시지 | 게시자 1, latched 1메시지 | 원본 카메라 49, 동적 TF 180 | 중앙 0.0094초, p95 0.0172초, 최대 0.0327초 |
| `rosy_60` | 게시자 2, 4초 19메시지 | 게시자 1, latched 1메시지 | 원본 카메라 48, 동적 TF 181 | 중앙 0.0096초, p95 0.0172초, 최대 0.0180초 |

관측한 TF 프레임 체인은 두 로봇 모두 각자의 `odom→base_footprint→base_link→front_camera_mount→front_camera_link`를 포함한다. 이 짧은 관측 창에는 `map→odom`이 없었고 `camera_info` 토픽도 목록에 없었다. 따라서 전역 `/tf`, `/tf_static` 구독을 추가한 Pilot 녹화 명령의 **토픽 이름은 실제 ROS 그래프와 일치**하지만, 지도 자세와 승인된 카메라 내·외부 보정 revision을 제공하지는 못한다. 표의 시각 간격은 정지 상태의 메시지 stamp 근접성일 뿐 센서 지연 보정, 움직일 때의 자세 오차, 지도 투영 정확도가 아니다. D-481의 지도 투영 라벨 게이트 6·7은 계속 열려 있다.

10/7 원본 207장에 대해서는 X: `lane-goal-20261008/1007-temporal-review/`에 `review-queue.csv`, `review-gallery.html`, `README.md`, `receipt.json`을 준비했다. 검증된 원본 목록 SHA-256은 `036c620b8379a9945216b552f2915774941ae7f5377052388489009a126ed5a0`, 대기열 SHA-256은 `2eb41bd266d3870d2d40c8faa58eed283b527292f4608fce89b75df5c221dbb5`, 갤러리 SHA-256은 `f43f9c081f6f933e13bb1ddf155436e464bc99b6963f03b8273149472999b9a8`이다. 124+83개의 원본 이미지 링크·해시·연속 frame index·증가하는 stamp를 확인했다. 사람의 물리 경계 ID·소실 원인·재출현·drivable 판정은 모두 비어 있으며 승인 사건은 0건이다. 이 사설 검수 대기열은 D-475의 225장 고정 평가 세트와 별개이고 픽셀 정답이 아니다.

다음 R0 녹화에서는 새 코드가 설치된 정확한 릴리스, MCAP 안의 실제 TF 메시지 수와 카메라 stamp 결합, 보정 revision, 사람 검수한 동일 경계를 확인해야 한다. 이 결과는 재생·SIM·실물 주행 수용을 대신하지 않으며 불확실한 경계는 STOP, 최종 `cmd_vel`은 CORE 단일 writer다.
