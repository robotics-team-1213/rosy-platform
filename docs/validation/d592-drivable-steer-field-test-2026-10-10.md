# D-592 drivable 조향 실물 시험 (경로 A) — 2026-10-10

[D-592](../adr/D-592-drivable-steering-field-test-pc-loop.md)의 첫 실물 기록이다. 로봇은 9dfk(rosy_41), 릴리스는 2026.10.09-069다. 현장에 사람이 있었다(D-574). 도구는 `tools/capture/drivable_steer.py`이고, 조향 계산 단위 시험은 `tools/capture/test/test_drivable_steer.py`다. 로봇에서 돌린 코드는 브랜치 `feat/drivable-steer-field-test`의 커밋 19971dd7b다.

## 같은 날 사용자 결정 (ADR 개정에 기록)

- **모델.** 2026-10-10 사용자가 모델을 `v13-drivable-20261010-86c86e7f`에서 팀의 crop128 모델 `lane-seg-20261010-71edcb6d`로 바꿨다. model.onnx sha256은 `71edcb6d00006c73…`이고, 클래스는 background, lane_left, lane_right, crosswalk, speed_bump, drivable의 6개다. 입력은 1x3x240x320 RGB /255이고, 그래프 안에서 112–239행을 자른다. 로봇의 `/var/lib/rosy/models/lane-seg-20261010-71edcb6d`는 `rosy-camera` 그룹 전용이라 읽을 수 없었다. 그래서 같은 sha256 파일을 `~/d592/model`에 복사해 썼다. 도구는 시작할 때 sha256을 다시 확인한다.
- **루프 호스트.** 사용자는 "모델 PC에서 확인하는 건 학습을 위한 부분"이라고 했다. 기본 호스트는 로봇 자신이고, 로봇에서 지연 한도를 못 지킬 때만 Fleet(현장 PC)을 쓴다. 모델 PC는 현장 주행 런타임 호스트가 아니다.
- **갈래.** drivable 영역이 갈래로 나뉘면 가장 오른쪽 갈래를 따른다(우측통행, D-384 결정 2).

## 주행 전 진단

사용자는 "전혀 못 움직인다"고 했다. 두 로봇을 점검한 결과, CORE 경로에는 주행을 막는 것이 없었다.

| 항목 | 9dfk | 8kcn |
|------|------|------|
| rosy-core, rosy-io, rosy-camera | active | active |
| CORE mode / E-stop | IDLE / false | IDLE / false |
| runtime / drive / teleop | motor / ready / ready | motor / ready / ready |
| 수동 한도(`/safety/state`) | 0.15 m/s, 0.6 rad/s | 0.06 m/s, 0.3 rad/s |
| line-follow, 다른 지휘자 | OFF, 없음 | OFF, 없음 |
| 0.03 m/s 1.5 s nudge(`edge_drive.py`) | odom 약 4.5 cm 이동 | odom 약 4.4 cm 이동 |

두 로봇 모두 API teleop으로 움직였다. "못 움직인다"의 원인은 이 점검에서 재현되지 않았다. 콘솔/Pilot 화면 경로는 확인하지 않았다.

## 루프 배치 (로봇 vs Fleet)

| 경로 | 프레임 원천 | 측정 |
|------|-------------|------|
| 로봇 위 | ROS `/<ns>/camera/front` (sensor_msgs/Image) | 약 8 Hz, 받는 시점 나이 약 15 ms (8kcn) |
| 로봇 위 | ONNX Runtime 1.30, crop128, 9dfk | 스레드 기본 227 ms, 1개 225 ms, **2개 171 ms**, 3개 196 ms, 4개 247 ms (p50, 정상 부하) |
| 로봇 밖 (현장 PC, 노트북) | 운전자 MJPEG `/vision/front/stream?overlay=false` | 1–2 fps, 촬영 간격 0.5–1.0 s, 전송 약 100 ms. 시계 차는 1 ms 미만(chrony)이다 |

로봇 밖 경로는 원본 프레임이 프리뷰 속도로 제한된다. 추론 전에 이미 프레임 나이가 0.6–1.1 s가 될 수 있어 0.5 s 한도를 지킬 수 없다. 현장 PC에는 ONNX Runtime도 없다(현장 PC에는 ML 패키지를 두지 않는다). 그래서 현장 PC 추론 시간은 재지 않았다. **루프는 로봇 위에서 돌렸다**(`--source ros --threads 2`).

## 조향 규칙 (도구 그대로)

- 아래 40% 띠에서 drivable 영역을 만든다. `lane_bounded_drivable`에 D-576 경계를 적용하고, crosswalk·speed_bump는 지나갈 수 있는 칠로 둔다. 선 안쪽 절반을 더하고, 40 px 미만 조각은 버린다. lane_marking으로 대체하지 않는다.
- 8-연결 성분이 둘 이상이면 무게중심 x가 가장 오른쪽인 성분을 고른다.
- 오차 e = (무게중심 x − 중앙) / 반폭이고, 양수는 오른쪽이다. w = clip(−0.6·e, ±0.4)이고, w가 양수면 좌회전이다(REP 103). v = 0.03 m/s다.
- 멈춤 조건은 아래와 같다. 하나라도 걸리면 0을 보내고, `--drive`이면 그 주기에서 끝내고 IDLE로 돌린다.
  - `drivable_low`: 띠 비율이 0.10 미만
  - `stale`: 명령 시점의 프레임 나이가 0.5 s 초과
  - `guard`: RobotBody LiDAR 앞 띠 gap이 0.5 s 이동 거리와 정지 거리의 합보다 작음, 알 수 없는 띠, 또는 스캔이 0.5 s 넘게 낡음
  - `time_cap`: 60 s
- CORE teleop watchdog(500 ms)과 CORE 몸체 정지는 그대로다. 주기는 0.15 s다.

## 계산만 하는 모드 (D-592 3항)

| 실행 | 위치 | 주기 | 추론 p50/p95 | 명령 시점 프레임 나이 p50/p95 | 띠 비율 p50 | 오차 → w |
|------|------|------|--------------|-------------------------------|-------------|----------|
| dry1 (스레드 기본) | 고리 안쪽 선 앞, 바깥을 봄 | 104 | 263 / 312 ms | 423 / 518 ms (10주기 stale) | 0.98 | −0.016 → +0.010 |
| dry2 (2스레드) | 고리, 섬 선을 거의 밟음 | 100 | 182 / 235 ms | 368 / 452 ms | 0.35 | +0.62 → −0.37 |
| dry3 (2스레드) | 고리, 섬이 오른쪽 | 111 | 164 / 199 ms | 310 / 398 ms | 0.93 | −0.07 → +0.04 |

**부호 확인.** dry2는 중앙 아래 열이 섬 안쪽에 있었다. 영역 씨앗이 섬 안쪽 drivable 칠로 잡혀 오차가 +0.62이고, 명령은 우회전(w −0.37)이었다. dry3은 섬 선(lane_right)이 오른쪽 아래에 있고, 영역이 왼쪽으로 조금 치우쳐 오차 −0.07, 좌회전(+0.04)이었다. 두 경우 모두 "영역이 있는 쪽으로 돈다"와 맞다. 오버레이로 확인했다(증거 폴더의 `*_ov.jpg`). 스레드 2로 바꾼 뒤 stale는 0회였다.

## 실주행 drive1

- 조건: 0.03 m/s, |w| ≤ 0.4, 60 s 상한, `--record`(CORE 녹화 `20261009T213528Z_rosy_41`, 12 s), 천장 녹화(`ceiling_record.py`, 274장)를 함께 돌렸다.
- 결과: 10.6 s, 52주기, 모든 teleop 200. 추론 p50 162 ms / p95 203 ms, 프레임 나이 p50 259 ms / p95 350 ms였다. odom 이동은 0.31 m, 순 yaw −0.23 rad(오른쪽)이다.
- 경로(천장 녹화): 고리의 왼쪽 위에서 섬을 오른쪽에 두고 고리를 따라 오른쪽으로 갔다. 이어 고리 바깥쪽 위 오른쪽 출구 쪽의 speed_bump 칠을 지나, 바깥 선 앞에서 섰다.
- 멈춤: `drivable_low`. 띠 비율이 0.42에서 0.18, 다시 0.02로 떨어졌다. 가로지르는 선(lane_left)이 띠 아래를 덮었고, 그 선 전에 섰다. 마지막 두 주기에는 갈래가 2개로 나왔다. 가드 거절, stale, 사람 개입은 없었다. 끝난 뒤 mode는 IDLE이었다.

## 확인하지 못한 것과 한계

- 고리 곡선을 따라 돈 것이 아니다. 섬 선 한쪽만 보이는 넓은 바닥에서는 무게중심이 열린 쪽으로 쏠려, 출구 쪽으로 곧게 나갔다. 이는 띠 무게중심 방식의 한계로 보인다.
- 가장 오른쪽 갈래 규칙은 성분이 끊어질 때만 작동한다. Y자로 이어진 한 덩어리(고리와 출구)는 갈래로 보지 않는다. drive1에서도 출구를 고른 시점에는 성분이 하나였다.
- 8kcn은 진단과 프레임 원천 측정만 했다. 주행하지 않았다.
- 현장 PC 추론 지연은 재지 않았다(ONNX Runtime 없음).
- 9dfk의 LiDAR 전방각은 URDF 기본값 180°를 썼다. 로봇에는 PC 보정 저장소가 없기 때문이다.
- 한 번, 10.6 s, 0.31 m를 달린 것은 차선 추종 수용이 아니다(D-378 R2 단계의 첫 기록).

## 증거

`X:\DevTemp\d592-steer\`에 다음을 남겼다.

- `dry1_9dfk.log`, `dry2_9dfk.log`, `dry3_9dfk.log`, `drive1_9dfk.log`: 주기별 JSON 행
- `dry2/`, `dry3/`, `drive1/`: 오버레이, `drive1/ceil_strip.jpg`
- `d592_ceil_drive1/`: 천장 녹화

로봇 쪽 원본은 9dfk의 `~/d592/runs/<run>/`(`cycles.jsonl`, `frames/`, `summary.json`)에 있다. 단위 시험은 원격 pytest로 돌렸다. `tools/capture/test`에서 22 passed였고, `known_failures` 결과는 0 new다(`X:\DevTemp\d592-steer\run-1.txt`).
