# Control Camera·Line Observer ROS-SIM (2026-09-30)

판정: **PASS** — control(sensing)의 camera 계열 두 노드를 살아있는 ROS 2 Jazzy
그래프에서 검증했다. 이 실행 중 **실제 제품 결함 1건을 발견·수리했다**
(`27def3de`: `_OpenCVCamera` GStreamer 백엔드가 무카메라 부팅을 죽인다).

## 방법

- WSL2 Ubuntu 24.04, ROS 2 Jazzy. 트리는 `git archive HEAD`(commit `27def3de`)
  를 `/root/rosy-0930`에 전개, `colcon build --packages-up-to control`
  (web_common·imu_bno055·control 3패키지, 42 s).
- **Smoke A — camera_detect_node 무장치 부팅 그래프**: 카메라 장치 없이 14 s
  실행. 우아한 강등(에러 로그 → 탐지 중단 → 노드 생존)과 발행 그래프 형성을
  본다. 타임아웃 종료 시의 `ExternalShutdownException`은 SIGTERM 시점의
  executor 종료 예외로 부팅 증거와 무관하다.
- **Smoke B — line_observer_node camera 모드 합성 레인**: 320×240 BGR8 합성
  프레임을 `/camera/front`에 10 Hz로 5단계(중앙→좌→우→무선→전면 밝음) 3 s씩
  발행. `require_camera_controls_stable:=false`. `line/observation` JSONL을
  수집해 페이즈 순서·payload 불변식을 단언한다.

## 결과

| 항목 | 결과 | 근거 |
|---|---|---|
| cameraDetect 부팅 | 카메라 실패 로그 → `camera_detect ready`까지 **1 ms** (V4L2 백엔드 고정 후) | `evidence-camera/camera-node-console.log` |
| camera 그래프 | `/camera/{cliff,blocked,side,front,observation,telemetry,controls,debug,calibration/status}` 발행자 9종 + `/camera/calibration/cmd` 구독 형성 | `evidence-camera/camera-node-info.txt` |
| line 레인 관측 | 133건, 레짐 순서 centre → left → right → none, **VERDICT: PASS (0 problems)** | `evidence-line/verify-output.txt`, `line-observation.jsonl` |
| 레인 오차 부호 | centre −0.003 → left −0.503 → right +0.497 → none (error None, conf 0.0), 신뢰도 1.0 | `line-observation.jsonl` |
| sensing-only 불변식 | 두 그래프 모두 twist/cmd_vel/velocity 토픽 **0개** | `camera-twist-count.txt`, `line-twist-count.txt` |
| 단일 evidence 발행자 | `line/observation` Publisher count 1 (line_observer_node) | `evidence-line/line-observation-info.txt` |

### 발견·수리한 결함 (isolation)

무장치 부팅에서 OpenCV auto 백엔드(Ubuntu은 GStreamer 우선)가 장치 실패에
5–13 s(콜 스타트) 걸리고, 실패 경로의 GStreamer 스레드가 init 중 shutdown과
만나 invalid-context traceback + 프로세스 hang을 냈다. 백엔드를
`cv2.VideoCapture(device, cv2.CAP_V4L2)`로 고정해 밀리초 실패·GStreamer
완전 회피로 수리(`27def3de`). 격리 로그: `evidence-camera/isolation-*.log`.

## 한계

- 합성 프레임은 레인 기하만 가진다 — 조명·왜곡·노출 변화, 실물 OV5647,
  물리 카메라 지연은 DEVICE/FIELD 계층이다.
- camera_detect_node는 무장치 강등 경로만 검증했다(프레임 처리 경로가 아님).
  프레임 발행 경로는 실물 또는 Gazebo 카메라가 필요하다.
- 이 실행은 control ROS-SIM HOLD 중 **camera 슬라이스**(camera_detect 부팅
  그래프 + line_observer camera 모드)만 닫는다. calibration·planning·
  safety-policy 전체 그래프, Gazebo 폐루프는 별도로 남는다
  (2026-09-22 D-162 road_observer 슬라이스와 같은 구조).
- run-smoke 본편의 `ros2 topic list`(camera 그래프)가 8 s 시점에 빈 목록을
  반환했다(discovery 타이밍). 노드의 엔드포인트는 `camera-node-info.txt`가
  확정 증거다.
