## D-205 실물 차선 미션으로의 전환: 시뮬레이션 현실화, 인식 재작업, 재합격 순서

**Status:** Proposed (2026-09-24). D-199 설계 [2026-09-24-perception-architecture-design.md](../plans/2026-09-24-perception-architecture-design.md)의
사용자 검토를 기다린다. 이 ADR은 차선 네트워크 작업의 다음 단계를 실행 순서와 단계별 게이트로 정한다.
다른 세션이 이 문서만 읽고 이어받을 수 있게 인계 절차도 함께 적는다. 잇는 결정:

- D-2: CORE만 최종 `/cmd_vel`을 발행한다.
- D-136·D-137: 영상은 증거만 낸다. 보조 검출 계약은 `DetectionEvidence`와 `ModelRegistry`다. 추론 가속은 Hailo를 전제로 한다.
- D-186: 스크립트와 수집 데이터는 주인 폴더에만 둔다.
- D-196(예약, PR #36): 로봇은 장치의 조합이다. 기종 설정은 `src/robots/pinky_pro/config/`에 둔다.
- D-199(Proposed): 카메라 인식은 두 층의 고정 계약과 교체 가능한 백엔드로 나눈다.
- D-200(Accepted): 도킹은 DOCKING 모드와 전용 명령 슬롯을 쥔다.

**Context:**

1. **local main에 있는 것(2026-09-24).**
   - route_ab(A+B 혼합)로 교차로를 지나고 순회한다.
   - 전 차선 순회(coverage tour)가 있다.
   - 주차는 CORE 도킹으로 한다(D-200).
   - 하네스: `src/sim/gz_sim/scripts/junction_harness.py`, `coverage_harness.py`, `mission_harness.py`.
   - 라이브 뷰 v2: `src/sim/gz_sim/scripts/lane_live_view.py`(포트 28183, 읽기 전용).
2. **Gazebo 결과는 25° 세계의 ROS-SIM이다.** 이 세계는 실물 로봇과 다르다. 장치 증거가 아니다.
   - 교차로 3회 × 12/12, 최대 오차 35 mm.
   - 순회 3/3, 최대 36.7 mm, 종료 오차 4.5 mm 이하.
   - 미션(언도킹 → 순회 → 주차) 4/4. 주차 오차 1.4–2.3 mm, 방위 1.7° 이하.
3. **실물 카메라는 시뮬 카메라와 다르다.** `data/teleop/learning/`의 수동 주행 영상에서 추정했다
   ([카메라 프로필 초안](../validation/perception-real-video/2026-09-24/camera_profile_draft.json)).

   | 항목 | 실물(추정) | 현재 Gazebo |
   |---|---|---|
   | 기울기 | 약 8° | 25° |
   | 좌우 화각 | 약 59.3°(fx 약 281.6) | 66° |
   | 렌즈 높이 | 약 67 mm | 60 mm |
   | 해상도 | 320x240, 8 fps | 320x180 |
   | 벽 | 흰 벽, 테이프보다 밝다 | 청회색 |
   | 바닥 | 카펫 | 균일한 바닥 |

4. **실물 매트는 CAD와 약 10% 다르다.** 사용자가 잰다. 실측값은 대기 중이다.
5. **현재 인식은 실물 로봇을 주행할 수 없다.** 실물 영상 재생 결과다
   ([기준선](../validation/perception-real-video/2026-09-24/baseline.md), REAL VIDEO REPLAY, host only; DEVICE: NOT RUN).
   - 벽을 차선으로 받는다. 벽을 BOTH, 신뢰도 1.00으로 보고한 프레임이 있다.
   - 장치 기본 `line` 모드는 22%의 프레임에서 벽으로 조향한다.
   - 고정 문턱 180이 실물 테이프(회색값 169–201)를 조각낸다.
   - `centre` 모드는 37%의 프레임에서 STOP이다.
   - `road.py`는 89.5%의 프레임에서 정지선을 보고한다.
6. **시뮬에서도 인식이 약하다.** Gazebo route_ab 순회에서 CORE가 받은 인식은 BOTH 12% · ONE 73% · MEMORY 16%다.
   원인은 `lane_bev.py`의 좌우 배정에서 라벨이 뒤바뀌는 것과, 왼쪽 선 하나로 시작하는 경로가 없는 것이다.

**Decision:**

1. **실행 순서는 P0 → P6이다. 각 단계는 게이트를 통과해야 다음으로 간다.**

   | 단계 | 할 일 | 게이트 |
   |---|---|---|
   | **P0 실측** | 사용자가 잰다. 차선 간격(중심 간), 테이프 폭, 횡단보도 막대 크기와 간격, 링 지름, 렌즈 높이, 바퀴 축 기준 렌즈 앞 오프셋, 매트 외곽 크기, 벽 높이. 카메라 프로필을 revision과 함께 경로에 매이지 않는 로더 위치에 저장한다. D-196의 `src/robots/pinky_pro/config/`에 맞는 자리다 | 재생 BEV의 차선 간격이 실측값 ±5 mm 안 |
   | **P1 계약** | D-199 계약을 구현한다. `perception/evidence`, `perception/frame`, `CameraProfile`, `FrameSource`, `ModelRegistry` 확장. ADR 후속 처리 | 계약 시험 |
   | **P2 재생 기준선** | ROS 없는 `perception_replay` 도구를 저장소에 둔다. 7개 텔레옵 영상에서 Context 5의 기준선 숫자를 재현한다. `tools/perception/prototype/`을 대체한다 | 기준선 재현 |
   | **P3 새 RuleBackend + SceneTracker** | 벽 밑선 아래 바닥만 보는 마스크, 적응형 또는 상대 문턱, 선 폭 필터 15–40 mm, 좌우 일관 라벨, 양쪽 모두 한 줄 시작, 폴리라인 맞춤, 장면 요소 | 텔레옵 재생에서: 벽 조향 0% 프레임. 고른 경계가 벽이면 신뢰도 ≥0.85의 BOTH 없음. STOP이 기준선 37%보다 훨씬 낮음. 정확한 수치는 P2 기준선 뒤 사용자와 정한다 |
   | **P4 현실화한 Gazebo 세계(revision++)** | 프로필에서 온 카메라, 흰 무광 벽과 파란 테이프, 카펫 질감, 실측 매트. `GroundTruthLabeler`, 채점기, 데이터셋 기록기(`data/perception/`, D-186 규칙) | BOTH ≥ 기하 상한의 80%. 경계 횡오차 중앙값 ≤10 mm. 두 수치는 사용자와 확인한다 |
   | **P5 추종기가 `PerceptionFrame`을 읽는다** | 현실화한 세계에서 이전과 같은 기준으로 다시 합격받는다 | 교차로 3회 36/36, ≤40 mm, 역주행 0. 순회 3/3, 정지 없음. 미션 주차 ≤20 mm / 5°, 3/3 |
   | **P6 장면 요소를 주행에 반영** | 코너 감속, 횡단보도 서행 등. 하나씩 따로 승인받는다 | 요소별 승인 |

2. **장치 주행은 P6 뒤에 한다.** Pinky 실기 주행은 P3과 P5가 모두 통과한 뒤에만 한다. 장치 합격 계획은 따로 쓴다.
3. **사용자가 정할 물리 결정이 둘 남아 있다.**
   - **주차 마커를 다시 정한다.** 낮은 25° 쐐기는 "25° 카메라는 6 cm 위를 보지 못한다"는 전제로 골랐다.
     실물 카메라는 약 8°이고 벽도 본다. 그래서 전제가 틀렸다. P0 뒤에 선택지를 낸다.
   - **학습 모델을 어디서 돌릴지 정한다.** Pi CPU인지 Hailo인지(D-136·D-137).
4. **이어받는 후속 과제.**
   - D-200 리뷰에서 온 것(core):
     - (MED) 라인 추종 `PUT`과 `dock()` 사이의 경합
     - 정지와 해제가 겹치면 잠금 없는 EMERGENCY가 남을 수 있다
     - `on_battery_level`이 잠금 없이 돈다
     - `cmd_vel_cycle` 오류 로그 폭주
   - 이전 리뷰에서 온 것:
     - `src/sim/gz_sim/launch/map_v2_fleet_lane.launch.py`의 line_observer `camera_x_offset_m`이 아직 0.034다.
       참값은 0.028481이다(같은 파일의 dock_observer). `src/sim/gz_sim/test/test_map_v2_fleet_launch.py`와 `src/core/control/test/lane_sim.py`,
       `src/core/control/test/test_lane_corner.py`도 0.034를 쓴다. 바꾸기 전에 코너 튜닝을 다시 잰다.
     - 주점 규약이 다르다. `camera_ground.py`는 `W/2`, `dock_observer.py`는 `(W-1)/2`다.
     - `paint_localizer.py`의 `MOTION_ALONG_SIGMA_PER_M` 0.10은 바퀴 배율 미끄럼에서 과신이다. 제대로 고치려면
       횡방향 SPREAD 정지와 5% 순회 드리프트 셀을 둔다.
     - API & Protocol Reference 오류 표가 `LINE_FOLLOW_ACTIVE`·`NO_ODOMETRY`를 "(v1.18)"로 적었다. 변경 이력은 v1.20이다.
   - control 패키지 분할(크기 판정 32,106줄, `split`)은 사용자 결정대로 P1–P3 안에서 실행한다.

**Validation:**

- 지금 확인한 것: 저장소에 옮긴 프로토타입(`tools/perception/prototype/realrun/replay.py` + `analyze.py`)을 이 트리에서
  7개 영상 4981프레임에 돌려 기준선을 그대로 재현했다. `centre` BOTH 13.0 · ONE 36.0 · MEMORY 14.3 · STOP 36.7,
  `line` 벽 조향 22.4%, `road.py` 정지선 89.5%. REAL VIDEO REPLAY, host only; DEVICE: NOT RUN.
- 각 단계의 합격은 위 표의 게이트로 받는다. 25° 세계의 이전 합격은 어느 게이트의 증거로도 쓰지 않는다.
- 이 ADR은 Proposed다. D-199 설계를 사용자가 검토한 뒤 P1을 시작한다. P0 실측은 그 전에 받아도 된다.

**Consequences:**

- 다음 세션은 P0 실측을 받으면서 P1(계약)과 P2(재생 도구)를 시작할 수 있다. P3 게이트 수치는 P2 뒤에 정한다.
- 장치 주행은 P3과 P5를 통과하기 전에는 하지 않는다. 이전 시뮬 합격만으로 Pinky를 주행하지 않는다.
- 카메라 프로필 초안은 추정값이다. P0 전에는 어떤 게이트의 기준으로도 쓰지 않는다.
- `tools/perception/prototype/`은 검토 전 프로토타입이다. P2 도구가 들어오면 지운다.

**인계: 작업 방법**

- ROS 머신은 WSL Ubuntu다. 워크스페이스는 `/rosy_mapv2_ws`(HOME=/).
- 빌드(WSL):
  `colcon build --symlink-install --packages-select control core core_features core_api_web core_common gz_sim`
- 하네스 사용법은 각 스크립트의 docstring을 본다. 모두 다음 인자로 돈다.
  `--domain 57 --graph install/control/share/control/map/map_v2_fleet/lane_graph.yaml`
- 증거는 `/rosy_mapv2_ws/evidence/`에 둔다. 라이브 뷰:
  `lane_live_view.py --evidence /rosy_mapv2_ws/evidence --port 28183`
- 함정:
  - `wsl -- bash -lc '...$VAR...'`는 변수를 너무 일찍 펼친다. 스크립트 파일을 쓴다.
  - `pkill -f` 패턴은 자기 셸에도 걸린다. `[x]yz` 꼴로 쓴다.
  - `pkill 'gz sim'`을 전역으로 쓰지 않는다. 다른 세션이 Gazebo를 돌린다.
  - `/mnt/x`에서 rsync하면 멈출 수 있다. `/mnt/f`의 worktree에서 rsync한다.
  - `record_debug` mp4는 mpeg4다. 브라우저용은 ffmpeg libx264로 변환한다.
  - 결과의 `clock_step_s`가 1 s를 넘으면 다시 돌린다.
  - 부하가 있으면 `BOOT_S`는 150 s다.
- 교훈: `docs/solutions/`의 2026-09-24 문서 넷.
  - [시뮬 벽시계 점프와 선 신선도 시계](../solutions/logic-errors/sim-wall-clock-step-and-line-staleness-clock-2026-09-24.md)
  - [OpenCV 4.6 ArUco 검출기 파라미터 segfault](../solutions/runtime-errors/opencv-4-6-aruco-detector-parameters-segfault-2026-09-24.md)
  - [시뮬 인식을 튜닝하기 전에 녹화 영상으로 실물 카메라를 잰다](../solutions/workflow-issues/measure-the-real-camera-from-recorded-video-before-tuning-sim-perception-2026-09-24.md)
  - [손으로 유도한 카메라 마운트가 기울어진 관절 안의 오프셋을 빠뜨린다](../solutions/logic-errors/camera-mount-derived-by-hand-drops-offsets-inside-pitched-joint-2026-09-24.md)
- 프로토타입 도구: [`tools/perception/prototype/`](../../tools/perception/prototype/README.md). Windows에서 `python`으로 돈다.

**References:** 설계 [2026-09-24-perception-architecture-design.md](../plans/2026-09-24-perception-architecture-design.md),
[주차 설계](../plans/2026-09-23-lane-network-parking-design.md),
[실물 영상 기준선](../validation/perception-real-video/2026-09-24/baseline.md),
[카메라 프로필 초안](../validation/perception-real-video/2026-09-24/camera_profile_draft.json),
[API & Protocol Reference](../reference/ROSY%20API%20%26%20Protocol%20Reference.md) v1.20, D-2, D-136, D-137, D-186, D-196, D-199, D-200.
