## D-579 자기개선 녹화 목표는 지도에 정착된 자세에서만 기존 goal 로 보낸다

**Status:** Accepted (2026-10-06, 사용자 지시: 목표를 만들고 시험한 뒤 실행. 소스 시험과 당일 장치 조회까지. 주행·학습 재실행·모델 전달은 이 결정의 수용이 아니다.)

### Context

Rosy Cam 은 실패가 일어난 자리를 보여 준다. 로봇 전면 카메라가 켜져 있으면 그 자리를 기존 녹화로 남겨 `recording_job` 이 catalog, autolabel, build, train 으로 읽을 수 있다. 그 고리는 이미 있다. 없는 것은 그 자리를 주행 목표로 보낼 조건이다.

D-463 은 점 목표를 `{x, y, yaw}` 로 유지하고, 스냅샷이 `LOCALIZED` 이며 `pose_frame` 이 지도일 때만 기존 goal 경로로 보낸다. 위치 블록이 없거나 바퀴 좌표이면 보내지 않는다. 천장 맞춤과 시야는 자세가 아니다. CORE 의 레거시 경로는 위치 상태가 비어 있을 때 목표를 허용할 수 있고, 그때의 좌표는 바퀴 원점이다. 자기개선 녹화는 그 레거시 허용을 쓰지 않는다.

모터 런타임의 `navigation.goal_navigation` 거절은 그대로다. 이 결정은 그 능력을 켜지 않는다.

### Decision

1. **목표의 뜻.** 자기개선 녹화 목표는 운용자가 Rosy Cam 으로 확인한 지도 좌표 한 점이다. 보내는 본문은 기존 `GoalRequest` `{x, y, yaw}` 다. 새 주행 API, 스케줄러, 저장소는 만들지 않는다.
2. **카메라를 먼저 본다.** `available` 이 참이고 `stale` 이 거짓일 때만 다음 검사를 한다. 아니면 `CAMERA_OFFLINE` 이고 goal 본문은 없다.
3. **지도 정착이 없으면 보내지 않는다.** `localization` 이 없거나, `state` 가 `LOCALIZED` 가 아니거나, `pose_frame` 이 `map` 이 아니면 `NOT_LOCALIZED` 다. 바퀴 원점, 오도메트리 좌표, 천장 시야, ArUco 시야로 좌표를 만들지 않고 `initialpose` 와 AMCL 을 쓰지 않는다.
4. **점이 있어야 한다.** 정착된 뒤에 x, y, yaw 가 유한한 수일 때만 `{x, y, yaw}` 를 돌려준다. 아니면 `GOAL_POINT_MISSING` 이다.
5. **보낸 뒤의 고리는 기존 것이다.** 녹화는 기존 recordings API, 회수는 정지 중 기존 harvest, 학습은 기존 `recording_job` 이다. 모델 전달과 로봇 활성화는 별도 결정이다. 이 함수는 명령을 보내지 않는다.

### 기존 결정과 관계

| 결정 | 관계 |
|---|---|
| D-427 | 학습은 기존 perception 학습 경로. 새 최상위 폴더 없음 |
| D-429 | 최종 주행 명령은 CORE Command Manager |
| D-395 · D-463 | 지도 `LOCALIZED` 만 목표로 보낸다. 레거시 빈 위치는 이 목표에서 거절 |
| D-360 · D-375 | 천장 화면은 자리의 단서이고 자세·목표가 아니다 |
| D-136 · D-373 | 회수와 저장소 규칙은 유지 |

### Consequences

호스트 시험은 `learning/training/perception/test/test_capture_goal.py` 다. 장치가 지도에 정착하기 전에는 이 결정으로 목표를 보내지 않는다. 모터 모드의 기존 능력 거절은 유지된다. Accepted 는 실차 주행이나 새 학습 실행이 아니다.

### 검증

- 카메라가 없거나 stale 이면 `CAMERA_OFFLINE`.
- 위치가 비었거나 `pose_frame` 이 `odom` 이면 점이 있어도 `NOT_LOCALIZED`.
- 지도 `LOCALIZED` 와 신선한 카메라와 유한한 점이 함께 있을 때만 기존 goal 본문을 돌려준다.
