# control logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [흡수 실행 계획](../../docs/plans/2026-09-12-rosy-control-absorption-plan.md), [흡수 결과](../../docs/plans/2026-09-12-control-absorption-results.md)와 `git log -- src/control`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the control harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_control_absorption_package.py -q` 6 passed; `PYTHONPATH=src/control:src python3 -m pytest src/control/test -q` 993 passed, 26 skipped, 2 failed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. SOURCE GO로, LOCAL은 실패 2건으로 HOLD로, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED로 스냅샷 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-15 · uncommitted · docs(harness): rerun control LOCAL with the Windows path separator
- 변경: `progress.md` LOCAL 증거와 다음 gate 정정
- 증거: 실패 2건 단독 재실행 2 passed(저장소 루트, 패키지 디렉터리 양쪽); Windows에서 `PYTHONPATH=src/control;src`로 `python -m pytest src/control/test -q` 995 passed, 26 skipped
- gate 변화: LOCAL HOLD→GO. 첫 실행 실패는 POSIX `:` 구분자와 병렬 시험 부하로 추정하며 코드 결함으로 재현되지 않음
- 결정: 없음
- 교훈: 없음

## 2026-09-17 · uncommitted · fix(sensing): stop writing RGB tuples into the BGR map raster
- 변경: S2 — `sensing/map_raster.py`가 계약을 `OCCUPANCY_RGB`로 선언하고 `OCCUPANCY_BGR`을 뒤집어 파생하도록. `WALL_THRESHOLD` 상수화. `web_node.py:render_png` docstring이 색 값을 되풀이하지 않고 출처를 가리키도록. `test_map_raster.py`가 하드코딩 튜플 5곳 대신 상수를 참조. 신규 `test/test_map_raster_color_contract.py` 3건
- 증거: `PYTHONPATH=src/control;src python -m pytest src/control/test -q` 998 passed, 26 skipped (2026-09-17 Windows, 미커밋 WIP 포함 작업 트리)
- gate 변화: 없음. LOCAL GO 유지하되 증거를 995→998로 갱신
- 결정: D-72 (Proposed) 이행 S2. concept 16 §6의 서버-클라이언트 래스터 색 계약을 시험으로 승격
- 교훈: RGB 튜플이 BGR 배열에 그대로 들어가 있었다. `cv2.imencode`가 3채널을 BGR로 읽으므로 PNG의 벽 색이 docstring이 약속한 #e1e0d9가 아니라 #d9e0e1로 나왔다 — 지도에서 면적이 가장 큰 색의 따뜻/차가움이 뒤집혀 있었고 주석만으로는 아무도 못 잡았다. 계약을 RGB로 적고 변환을 한 곳에 모아 같은 실수를 구조적으로 막았다

## 2026-09-17 · 8fdd8d2 · docs(control): D-77 diagnostic surface, CSS/JS token mirror
- 변경: dashboard.html 제목과 AGENTS.md를 진단 화면으로. `const T`가 :root hex와 같음을 시험
- 증거: `PYTHONPATH=src/control;src python -m pytest src/control/test/test_map_raster_color_contract.py test/test_control_launch_boundary.py -q`
- gate 변화: 없음. LOCAL GO. DEVICE HOLD
- 결정: D-77 — 운용자 콘솔은 CORE `/dashboard`
- 교훈: 없음

## 2026-09-18 · uncommitted · feat(control): camera/front publishes sensor-data QoS (D-119)

- 변경: camera_detect_node Image 퍼블리셔가 qos_profile_sensor_data. 구독과 맞춤.
- 증거: `python -m pytest test/test_dds_rmw_contracts.py -q`
- gate 변화: 없음. DEVICE PARKED

## 2026-09-20 · uncommitted · feat(safety): evidence-gated adaptive speed authorization

- 변경: add immutable geometry/sensor and motion-envelope candidate certificates, independent holdout promotion, conservative clearance braking, runtime drift downgrade, and a reducing-only numeric speed cap handed to CORE.
- 증거: focused Control tests `37 passed`; final Control gate `1038 passed, 26 skipped` after synchronizing the launch-test fixture with the declared empty web-port defaults; CORE package `895 passed, 11 skipped`.
- gate 변화: SOURCE and LOCAL GO for the pure policy and handoff. ROS-SIM/ARTIFACT/DEVICE/FIELD remain HOLD. No speed above `0.014 m/s` is enabled.
- 결정: calibration output is inert until a separate-session holdout promotes it, and an active envelope may reduce but never create motion authority.
- 교훈: geometric fit, sensor status, stopping evidence, runtime conditions, and final command authorization must remain separately auditable.

## 2026-09-20 · uncommitted · feat(control): replace fixed 8 cm escape cap with measured diameter bound

- 변경: the live escape proposal now carries the calibrated circumscribed diameter and searches only within that diameter and the independently measured straight corridor. Reverse wins equivalent choices, but front/rear evidence remains authoritative. Execution stops as soon as rotation clearance returns and refuses proposals missing the measured bound instead of falling back to 0.08 m.
- 증거: focused escape planner/executor/adapter tests `30 passed`; wider recovery/adaptive-speed/certificate/calibration set `102 passed`; final full Control gate `1038 passed, 26 skipped`; exact-map findings are recorded in `docs/validation/map-260905-update-v2-2026-09-20/result.md`.
- gate 변화: none. SOURCE behavior is covered; active CORE/Nav2 recovery integration, ROS-SIM complete traversal, DEVICE and FIELD remain HOLD.
- 교훈: a diameter is a maximum search envelope, not a commanded distance; every tick must shrink authority from current observed room and never expand an open episode.

## 2026-09-20 · uncommitted · feat(camera): add validated tunable ground homography

- 변경: add a ROS-free camera homography evaluator that recomputes fit and independent holdout residuals, binds processed image size/rotation/profile revision, requires physical validation evidence, and refuses board-relative X as robot lateral. Add bounded ROS tuning parameters, transient status, a session-only enable command, and diagnostic dashboard switch/read-only checks while preserving pinhole as the default.
- 증거: TDD focused `15 passed`; camera/web regression `161 passed, 10 skipped`; full Control from the required package cwd `1038 passed, 26 skipped`; launch-test fixture now supplies the two declared empty web-port defaults.
- gate 변화: none. SOURCE behavior is covered. ROS-SIM/DEVICE/FIELD remain HOLD because no complete ChArUco profile, independent Pinky Pro captures, measured-distance readback, or physical stopping trial was supplied.
- 결정: an approximate profile may be loaded and tuned but cannot become active; validation checks are node-owned and cannot be clicked through in the dashboard. Runtime tuning remains bounded ROS configuration, while the dashboard enable is intentionally session-only.
- 교훈: a low residual on calibration correspondences does not prove the image preprocessing contract, robot coordinate frame, unseen distances, or a physically locked camera mount.

## 2026-09-20 · uncommitted · feat(control): ArUco dock tag to relative pose (DNC-007)

- 변경: `control/sensing/dock_tag.py` 신규 — DICT_4X4_50 태그 검출 + solvePnP 상대포즈(x fwd/y left/yaw CCW). 미검출·他 태그는 None. 시험 `test/test_dock_tag.py` 5건(합성 고정: 거리·방위 부호·빈 프레임·他 ID·스펙 검증)
- 증거: `python -m pytest src/core/control/test/test_dock_tag.py -q` 5 passed. 전체 `src/core/control/test` 999 passed + 기존 환경 실패 4건(Windows subprocess/launch — clean tree 재현 확인, 본 변경 무관)
- gate 변화: 없음. ROS-SIM HOLD — 실물 도크·카메라 placement 실측 대기. SRS v1.1에 SAF-006/NAV-007/DNC-007 등록

## 2026-09-20 · uncommitted · feat(control): ArUco detector lifecycle + DockType tag spec (DNC-007)

- 변경: `control/sensing/dock_detector.py` 신규 — `ArucoDockDetector`(start/relative_pose/stop, 구조적 적합, core import 없음, D-64 준수). 관측에 confidence(재투영 오차 기반)+at(주입 시계) 추가. `core_features` `DockType`에 tag_family/tag_id/tag_size_m (all-or-nothing 검증, 없으면 검출기 선택 불가)
- 증거: control `test_dock_detector.py` 7건 + `test_dock_tag.py` 5건 = 12 passed (적색→녹색). core `test_docking.py` 103 passed, core 전체 895 passed·10 skipped
- gate 변화: 없음. 배선(factory 주입)은 vision 컨테이너 결정 후 — 미연결 상태의 어댑터는 죽은 코드가 아니라 계약이다

## 2026-09-20 · uncommitted · feat(dock): detector rides the sensor provider port (D-138)

- 변경: `control/sensor_provider.py`에 `make_dock_detector` (cv2 지연 import). `core_features` `select_detector` — aruco 명명+제원 완비+provider+프레임+기하가 다 있어야 실검출기, 아니면 빈 대본. `services.py` detector_factory가 `select_detector` 호출 (오늘은 항상 시뮬레이션, 동작 불변)
- 증거: provider 3건 + selection 6건 신규. core 전체 901 passed·10 skipped, control 도크 15건. flake8 신규 파일 무경고 (services.py E306 기존 건 제외)
- gate 변화: 없음. 카메라 프레임·기하 주입은 Task 5 실측 뒤 ros_bridge 몫

## 2026-09-20 · uncommitted · feat(control): lane error and loss tracker (NAV-007)

- 변경: `control/sensing/lane.py` 신규 — 하단 밴드 이진화+열 중심 횡오차(고전 CV, YOLO 없음), `LaneTracker`(3초 유예 후 정지 요구, 재목격 해제). `LANE_MAX_LINEAR_M_S = 0.10`. 시험 `test/test_lane.py` 10건(합성 차선: 중앙·좌우 부호·빈 바닥·추적·유예·상실·재획득·미목격)
- 증거: `test_lane.py` 10 passed (적색→녹색 — 밝기합/픽셀수 단위 혼동 1건은 구현 결함으로 적색 확인 후 수정). 전체 1019 passed + 기존 환경 실패 4건(본 변경 무관)
- gate 변화: 없음. 조향 소비(오차→각속도)와 nav.lane_lost 이벤트 배선은 노드 몫 — evidence까지만 닫힘

## 2026-09-21 · uncommitted · feat(mapping): complete the exact v2 Gazebo map

- 변경: `map_260905_update_v2`의 16개 벽을 직접 읽는 감사기가 점이 아닌 반경 `0.086 m` 본체의 spawn 연결 구성공간을 계산하고, 접근 가능한 곳의 unknown/occupied/out-of-raster 비율을 각각 판정한다. 실제 주행 경로는 밀폐 포켓을 제외한 모든 관측 포켓을 방문한다.
- 증거: Gazebo Harmonic `final_22`에서 52/52 waypoint, odom `13.754679 m`, 접근 가능한 unknown `0.0%`, occupied `0.0%`, 충돌 중첩 없음, 최소 표본 본체 여유 `0.021789 m`. CORE 단독 최종 `cmd_vel` publisher와 Fleet `online=true`, `map_id=occupancy:326966090e60`를 같은 실행에서 읽었다. 상세 수치는 `docs/validation/map-260905-update-v2-2026-09-21/result.md`.
- gate 변화: Control 전체 ROS-SIM은 HOLD 유지. 정확한 v2 월드의 mapping/CORE/Fleet 슬라이스는 GO지만, camera/calibration/safety-policy 전체 노드 그래프와 실기기는 이 실행이 증명하지 않는다.
- 결정: 전체 이미지 unknown 비율 대신 실제 본체가 도달 가능한 구성공간을 합격 기준으로 삼고, 밀폐 포켓 비율은 별도 공개한다.
- 교훈: 반복되는 얇은 벽에서는 scan matcher가 정확한 simulation odom을 잘못 굽힐 수 있다. 시뮬레이션에서는 live scan을 Gazebo model-pose odom에 직접 래스터화해야 재현 가능한 정답 비교가 된다.

## 2026-09-21 · uncommitted · feat(control): selectable IR and camera line following (D-143)

- 변경: CORE dashboard/API에서 `OFF`, `IR_LINE`, `CAMERA_LINE`을 배타적으로 선택한다. Control은 IR/영상 evidence만 발행하며 CORE manager가 adaptive speed와 조향을 만들고 기존 단일 `cmd_vel` 경로가 최종 중재한다. `rosy-io` 이미지와 hardware launch에 V4L2 camera fallback 및 Pinky 0x08 I²C ADC publisher를 연결했다.
- 안전: 원본 영상 header stamp 기반 stale, malformed/저신뢰/미검출 즉시 zero, 3초 loss latch, 모드 전환 상태 잠금, 0.10 m/s 별도 상한을 적용했다.
- 증거: 폐루프 운동학 simulation에서 3.5 cm 횡오차가 IR -0.03 cm, camera 0.006 cm로 수렴하며 stale/loss 정지 통과. 외부 IR calibration YAML, V4L2 exposure/white-balance 잠금 readback, mode/evidence revision 원자적 handoff를 추가했다. Control `1084 passed, 26 skipped`; CORE `955 passed, 11 skipped`; root `1008 passed, 13 skipped`; Fleet `332 passed, 5 skipped`; OMX `10 passed`; Games `101 passed`. `rosy-io:dev` 빌드와 이미지 내부 3개 line-follow executable, OpenCV 4.6.0, launch argument readback도 통과했다.
- gate 변화: SOURCE/LOCAL GO. ROS-SIM은 detector/manager 폐루프 증거만 추가되었고 전체 graph gate는 HOLD. ARM64 artifact, Pi camera/I²C readback, 물리 교정과 실제 차선 주행은 ARTIFACT/DEVICE/FIELD HOLD.
- 결정: D-143. 센서는 motion authority가 아니며 관제는 CORE API만 사용한다.

## 2026-09-21 · uncommitted · fix(control): legacy launches point at absorbed package names (D-149)
- 변경: robot.launch.py/wander.launch.py 의 pinky_imu_bno055 → imu_bno055(실행파일 main_node 그대로). 존재하지 않는 lcd_control/lcd_node 참조는 안내 로그로 교체( apps/emotion 이 흡수, CORE display/info 구독 노드로 별도 실행). dashboard_control/wander launch 에 "beside core" 금지 마커 추가. test/test_launch_contracts.py 2건 추가.
- 증거: 개명 이전 이름 참조는 현재 트리에서 깨진 launch 다. D-149: safety_node 를 시작하는 모든 launch 의 마커 계약(최소 1개 존재 검사 포함).
- gate 변화: 없음

## 2026-09-21 · uncommitted · feat(control): DetectionEvidence producer snapshot (D-137 T2)
- 변경: `control/control/detection_evidence.py` 신규 — 추론 패킷 1프레임 frozen 스냅샷(`TrackedEvidence` 패턴, 행동 어휘 없음). `capture()` 생산 측 전 필드 검증+ROS→모노톤 시계 변환, `evaluate()` 상태 판정만(fresh/empty/missed/stale/invalid — "없음"과 "놓침" 구분, 300ms D-136), `to_wire()` §6.1.1 재구성. 박스 규칙(원점 [0,1]·크기 (0,1]·프레임 수납)은 와이어 진실 `core_common.protocol.detections`와 동일 표현식. `inference_ms`(v1.11 additive)를 detections.py+API Ref §6.1.1에 추가. D-18 동기 시험이 스냅샷↔스키마를 묶음(시험 전용 import, D-64 생산 경계 유지). 중간에 schemas.py에 넣었다가 기존 detections.py 서브모듈 발견 후 되돌린 중복 정의 1건 있음
- 증거: `test_detection_evidence.py` 10건 신규 녹색 + core `test_protocol_schemas.py` 1건(inference_ms 선택성·음수/NaN 거절·왕복) 신규 녹색. control 전체 1094 passed·26 skipped, core 전체 972 passed·11 skipped (2026-09-21 Windows, PYTHONPATH)
- gate 변화: 없음. T1(CORE 정책 스냅샷 advisory 자리·단일 발행자·e-stop 해금 경로 계약)과 ROS-SIM 주입이 다음 순서 — 노드 기동은 T5까지 금지

## 2026-09-21 · uncommitted · docs(control): mark web_node debug surface and the map home (D-150)
- 변경: web_node.py 독스트링에 D-150 디버그 서피스 선언 추가(운영 launch/deploy 불가, 포트는 deploy 계약 테스트가 고정, 운용자 콘솔은 CORE /dashboard D-23). web/AGENTS.md 와 map/AGENTS.md 도 같은 계약으로 갱신 — map 은 캘리브레이션 기준 자산으로 격하, 운영 맵 홈은 navigation/map.
- 증거: python -m pytest test/test_control_launch_boundary.py -q 통과. 신규 deploy 포트 가드 포함 5종 계약 테스트 변이 증명 완료(망가뜨림→적색→복구→초록).
- gate 변화: 없음

## 2026-09-21 · uncommitted · feat(control): burst trigger gate — corroboration or operator (D-137 T4 순수 조각)
- 변경: `control/control/burst_gate.py` 신규 — 패킷당 1문항: 이 증거가 영상 버스트를 시작·유지할 수 있는가. D-137 §4(YOLO 단독 트리거 금지 — corroboration 또는 operator), D-136 §5(quality 저하는 evidence 무효로만 결합). operator_request 단축 → fresh+metric 교차만 트리거, 나머지는 vision_only/no_detection/vision_missed/vision_stale/vision_invalid 로 기각. 분당 FP 상한은 ROS-SIM 합의 전이라 의도적으로 없다(정해지면 송신 측 token bucket, D-136 §4). 대역폭 정책이지 motion 정책이 아니다 — 결코 cmd_vel 에 닿지 않는다.
- 증거: test_burst_gate.py 7건 녹색(operator 단축, 교차 트리거, vision_only 금지, metric 단독·부재 불가, missed≠부재, stale/invalid 불가, 입력 타입 검증). 인수인수 검증: control 전체 1101 passed·28 skipped, core 전체 976 passed·11 skipped (2026-09-21 Windows, 패키지 cwd/PYTHONPATH — 병렬 콘솔 세션 작업을 이 세션에서 검증·랜딩).
- gate 변화: 없음. FP 상한(ROS-SIM 합의 항목)과 T5(DEVICE)가 남아 있다.

## 2026-09-21 · uncommitted · feat(control): detect semantic road evidence (D-151)

- 변경: camera frame에서 차선·정지선·횡단보도·적색/황색/녹색 신호와 충돌을 검출하는 sensing-only observer를 추가했다. 수평 표식은 차선 중심 계산에서 제외하고, 정지선 거리는 검증된 ground model이 활성일 때만 발행한다.
- 증거: `map_260905_update_v2` synthetic camera closed loop가 `FOLLOW` → `APPROACH` → `STOP_REQUIRED` → `WAIT_SIGNAL` → `PROCEED` → stale `HOLD`를 통과했다. Control 통합 회귀 `1131 passed, 26 skipped`.
- gate 변화: SOURCE/LOCAL GO 유지. 실제 Gazebo camera topic graph, Pi camera/IR, 물리 homography·제동거리와 FIELD는 HOLD/PARKED 유지.
- 결정: D-151. Control은 evidence만 만들고 최종 주행 명령은 CORE가 중재한다.

## 2026-09-21 · uncommitted · feat(control): publish the bounded semantic camera preview (D-152)

- Review hardening: startup validates 0.2..2 FPS, 160..640 px, JPEG quality 40..90, and 512000 bytes; local monotonic limiting and BEST_EFFORT depth 1 are enforced.
- Latest evidence: integrated Control `1131 passed, 26 skipped`; Chromium dashboard `6 passed`.

- 변경: `road_observer_node`가 detector와 동일한 `camera/front` frame에 차선·횡단보도·정지선·신호 overlay를 그려 기본 2 FPS, 최대 폭 640, JPEG 품질 72로 `camera/preview/compressed`에 발행한다. 원본 detector 입력은 변경하지 않는다.
- 안전: hardware에서는 camera control 안정성이 유지돼야 detection evidence가 유효하다. simulation launch만 그 gate를 명시적으로 해제하며 preview 자체에는 주행 권한이 없다.
- 증거: host preview JPG/GIF와 browser panel은 HOST-SIM으로 명시했다.
- gate 변화: SOURCE/LOCAL 유지. 실제 CSI frame과 물리 보정은 DEVICE/FIELD HOLD다.

## 2026-09-21 · uncommitted · refactor(control): move cross-domain simulations to repository tools

- 변경: line-follow·semantic-road 통합 시뮬레이터를 `src/core/control/tools`에서 루트 `tools/`로 이동하고 직접 실행 경로와 문서 참조를 맞췄다. Control 생산 코드의 CORE import와 최종 operational topic 소유권을 AST/소스 경계로 고정했다.
- 증거: 시뮬레이터 CLI·회귀와 모듈 경계 10 passed.
- gate 변화: SOURCE/LOCAL GO 유지. 실제 ROS graph publisher 검증은 D-156 Proposed다.
- 결정: D-155. D-156은 launch/graph 증거 전 Proposed.

## 2026-09-22 · uncommitted · test(control): anchor subprocess children to the package root

- 변경: `test_calibration_spaces.py`와 `test_os_calibration_concurrency.py`가 자식 프로세스에 `cwd=PKG_ROOT`를 넘긴다. 저장소 루트에서 모듈을 합쳐 pytest를 돌려도 `tools.gz`·`control` 임포트가 실패하지 않는다. calibration_spaces CLI 자식은 `capture_output`으로 stderr를 실패 메시지에 남긴다.
- 증거: `python -m pytest src/core/control/test/test_calibration_spaces.py src/core/control/test/test_os_calibration_concurrency.py -q` 15 passed (2026-09-22 Windows, 저장소 루트)
- gate 변화: 없음. SOURCE/LOCAL GO 유지.

## 2026-09-22 · uncommitted · feat(sensing): D-162 장면 상황 프로파일+히스테리시스 매처 (T1/T2)

- 변경: `control/sensing/scene_context.py` 추가 — `SceneContextProfile`(RoadPerceptionConfig 필드 전체를 명시 기록+`profile_revision`), `SceneContextStore`(닫힌 context 집합 generic/lane_follow/stop_line/crosswalk, 중복 id·revision 거부, generic 필수, 미등록 id는 KeyError), `SceneContextMatcher`(우선순위 crosswalk > stop_line > lane_follow, enter/exit 프레임 히스테리시스, signal_conflict 프레임 계수 동결, reset). `test/test_scene_context.py` 27 시험 추가.
- 증거: `python -m pytest test -q` 1168 passed, 28 skipped (2026-09-22 Windows, 패키지 cwd). D-137/D-151/D-152 회귀 없음.
- gate 변화: 없음. SOURCE/LOCAL GO 유지, LOCAL evidence 문자열만 갱신. 노드 wiring(T3)과 CORE 수용(T5)은 미착수.
- 결정: D-162 Proposed — 학습된 장면은 설정이지 권한이 아니다. 프로파일은 인지 파라미터만 바꾸고 명령 권한은 CORE에 남는다.

## 2026-09-22 · uncommitted · feat(sensing): D-162 T3 scene context 노드 wiring + additive payload

- 변경: `road_observer_node`에 `scene_context_enabled`(기본 False)/`enter_frames`/`exit_frames`/`min_confidence` 파라미터 추가. 활성 시 프레임마다 matcher를 update하고 `road_observation_payload`가 additive `context`(id/confidence/profile_revision)를 실는다. 3필드는 all-or-none 검증이고 비활성 payload는 이전과 완전히 동일하다. 보정 명령(ground model 교체) 시 `matcher.reset()`으로 세션을 폐기한다. `config/line_follow.yaml`에 기본값(비활성) 기록. `sensing/scene_context.py`에 `default_scene_context_store()` 추가(v0 중립 프로파일 — 값은 제네릭과 동일, 튜닝은 DEVICE gate).
- 증거: `python -m pytest test -q` 1179 passed, 28 skipped (2026-09-22 Windows, 패키지 cwd). road/scene 관련 집중 시험 68 passed.
- gate 변화: 없음. SOURCE/LOCAL GO 유지, LOCAL evidence 문자열 갱신. CORE 수용(T5)과 ROS-SIM은 core 모듈 게이트다.
- 결정: context 전환은 검출 파라미터만 바꾼다 — 노드는 motion topic을 여전히 발행하지 않는다(wiring 시험 유지).

## 2026-09-22 · uncommitted · test(control): D-162 노드 그래프 ROS-SIM PASS (scene context 슬라이스)

- 변경: 없음(검증과 기록만). WSL2 Jazzy에서 control 패키지를 빌드하고 `road_observer_node`를 `scene_context_enabled:=true`로 기동, 합성 카메라 3페이스(lane→lane+stop line→lane+crosswalk, 10 Hz)를 발행하며 `/road/observation` 110건을 수집했다.
- 증거: `docs/validation/scene-context-control-node-2026-09-22/` — generic→lane_follow→stop_line→crosswalk 순서 전환, 리비전 결합(ctx-*-v1), payload `context` 필드 상시 존재, 그래프 내 twist 토픽 0, `/road/observation` publisher 1. VERDICT PASS(7/7).
- gate 변화: ROS-SIM HOLD 유지(전체 그래프+물리 센서는 여전히 미검증) — blocker에 D-162 슬라이스 통과를 명시.
- 결정: 합성 crosswalk 신뢰도가 0.5 근처라 프로브 파라미터는 `scene_context_min_confidence:=0.4`를 썼다. 운영 기본값(0.5) 변경이 아니라 시험 하네스 파라미터다.
- 교훈: 소스 문자열 검사(wiring 시험)는 "파라미터가 있다"만 증명한다. 실제 전환이 그래프에서 일어나는지는 20줄짜리 합성 퍼블리셔로도 증명된다 — 노드 레벨 ROS-SIM은 가볍게라도 돌릴 만하다.
## 2026-09-22 · uncommitted · test(control): D-162 Gazebo 실렌더링 검증 PASS — scene context 폴백 확인

- 변경: 없음(검증과 기록만). WSL2 Gazebo Sim 8.15에서 semantic_road_dashboard 헤드리스 실행, road_observer만 scene_context_enabled로 스냅샷 변경. 스폰→텔레포트 3회(x 0.10/0.45/0.80)로 시야를 바꾸며 관측 수집.
- 증거: `docs/validation/scene-context-gazebo-2026-09-22/` — 정지선 구간 stop_line 20/20·22/22, 표식 통과 후 generic 18/18·18/18(보수 폴백), 단일 옵저버 가드(publisher 1), payload context 필드 상시. phase0에서 정지선 conf 0.986·거리 0.167m — 2026-09-21 증거와 일치.
- gate 변화: 없음(ROS-SIM HOLD 유지 — 전체 그래프 주행은 기존 과제). D-162 슬라이스의 실렌더링 증거 추가.
- 결정: 텔레포트 기반 검증으로 주행 동역학은 미반영 — 주행 폐루프는 2026-09-21 증거가 커버.
- 교훈: 1차 실행에서 잔존 옵저버가 /road/observation을 오염시켰다(publisher 2). 그래프 검증 스크립트는 publisher 수 단정을 먼저 하라.

## 2026-09-22 · uncommitted · test(control): derive the deployed control closure and pin one sensor provider
- 변경: `test/test_control_deploy_closure.py` 추가. systemd 유닛·compose에서 launch include 사슬을 따라 배포되는 control 실행 파일을 도출하고, `rosy.sensor_provider:control` 등록자가 정확히 1개임을 검사한다. D-149 Validation에 정정 문단 추가.
- 증거: `python -m pytest test/test_control_deploy_closure.py -q` 4 passed. 변이 증명 3건(safety_node 편입, road_observer 제거, games에 두 번째 provider 등록 → 각각 적색 → 복구 → 초록).
- gate 변화: 없음. 배포 폐쇄의 control 실행 파일은 4개(ir_adc·camera_detect·line_observer·road_observer)이며 전부 증거 생산자다.
- 결정: D-149 정정(결정 불변), D-168 control 분리 설계 0단계.
- 교훈: 승격 근거로 쓴 "실행 파일 목록"을 사람이 적으면 한 개가 빠진다. 폐쇄는 include 사슬에서 도출해야 한다.

## 2026-09-22 · uncommitted · refactor(control): split web_node into ROS wiring and ROS-free web modules
- 변경: `web_node.py`(1,091줄)를 노드 배선(558)과 `web_state.py`(STATE·키·한계·/state.json 신선도, 82), `web_http.py`(라우팅·검증·중계 게이트, 304), `web_render.py`(지도 PNG·카메라 JPEG, 78), `web_map_control.py`(slam_toolbox 조작, 147)로 나눴다. 발행만 `WebNode.publish_text`/`publish_teleop`로 위임했고 나머지 코드는 원본과 동일하다(diff 확인). `test_web_http.py`가 실제 HTTP 요청으로 게이트·클램프·경계를 검사한다. 소스를 AST로 떼어 실행하던 `test_calibration_receiver.py`는 직접 import로 바꿨다.
- 증거: `python -m pytest src/core/control/test -q` 1284 passed, 28 skipped (2026-09-22 Windows). `test/test_module_structure.py` 등 구조 가드 27 passed — P6가 600줄 아래로 내려간 web_node 판정 삭제를 강제했다.
- gate 변화: 없음. ROS-SIM 스모크(WSL에서 web_node 기동·요청·토픽 확인)는 WSL 서비스 오류(E_UNEXPECTED)로 미실행.
- 결정: D-168 P6 `split` 판정 이행, control 분리 설계 1단계 중 web_node.
- 교훈: `/state.json` 신선도 판정은 이제 요청마다 시각을 한 번만 읽는다. 원본은 판정마다 `time.monotonic()`을 새로 불렀다(마이크로초 차이, 한 응답 안의 판정이 같은 시각 기준이 됨).

## 2026-09-22 · 4933fe0 · test(control): ROS smoke of the split web_node in WSL Jazzy
- 변경: 없음(검증과 기록만). 앞 항목에서 미실행으로 남긴 ROS 스모크를 `wsl --shutdown` 복구 후 실행했다.
- 증거: WSL Ubuntu ROS 2 Jazzy, 소스 트리 `python3 -m control.web_node`(colcon 설치 없이, html은 소스 폴백). 5개 web 모듈 import OK. `/state.json` 200(키 limits·map_control·planner_fresh·runtime_id·sensors·teleop_topic), 페이지 106,896바이트. `POST /wander stop` 200 → 리스너가 `/wander/cmd`에서 `'stop'` 수신. 교정 전 `POST /wander start` 409(게이트). `POST /teleop {x:0,z:0}` 200 → `/cmd_vel_raw`에서 `(0.0, 0.0)` 수신. `/cmd_vel` 발행자 0.
- gate 변화: 없음(control ROS-SIM은 전체 그래프 기준이라 HOLD 유지). web_node 분리의 중계 경로는 ROS에서 확인됐다.
- 결정: 없음
- 교훈: WSL 재시작 직후에는 `ros2 topic echo --once`가 발견 지연으로 빈 결과를 낸다. 발행자 수가 잡힐 때까지 기다린 뒤 요청해야 중계를 증명할 수 있다.

## 2026-09-22 · uncommitted · control(watch): graph guard matches the OS node names and cmd_vel ownership
- 변경: `control/watch.py` 테이블 현행화. REQUIRED 노드명 pinky_* -> bringup/sensor_adc/imu_bno055, FOREIGN 에서 pinky_* 4건 제거(브리지 트윈 parameter_bridge/image_bridge 유지), ALLOWED 의 /cmd_vel_raw 에 control_node 추가. EXCLUSIVE 값을 단일 문자열에서 허용 소유자 집합으로 바꾸고 /cmd_vel 소유자를 {core, safety_node} 로 확정 — inspect() 는 허용 집합에서 정확히 한 종류만 발행해야 하며 두 소유자가 동시에 발행하면 co_owner 인터럽트(D-38 병행 금지의 런타임 감시).
- 증거: `python -m pytest src/core/control/test/test_watch.py -q` 22 passed(신규 8건 계약/행위 시험 포함, test-first 적색 확인 후 초록). `python -m pytest src/core/control/test/ -q` 1292 passed, 28 skipped (2026-09-22 Windows). 근거 평가: Rosy 폴더 communication-protocol-report.md §3.2.1 및 docs/plans/2026-09-22-communication-protocol-remediation-plan.md T1.
- gate 변화: 없음. watch.py 순수 모듈 LOCAL GO 유지.
- 결정: 없음 — D-2/D-38/D-149 기존 결정을 감시 장치에 반영한 것.
- 교훈: 감시장치 테이블이 정책을 배반하면 오탐이 상수가 된다. 리네임(D-16) 시기에 감시 테이블이 함께 갱신되지 않아 6개월간 watch_node 가 현행 그래프에서 항상 인터럽트를 보고했다.

## 2026-09-22 · uncommitted · control(ir): ir_sensor/range 단일 발행 계약 고정
- 변경: `launch/line_follow.launch.py` 헤더에 ir_sensor/range 단일 발행 규칙 주석(ir_adc_node 가 이 launch 의 유일 IR 발행자, C++ sensor_adc 는 같은 버스의 레거시 벤치 판독기 — 병행 금지). `control/calib_node.py` 운영자 메시지 2건에서 구 패키지명 pinky_sensor_adc 제거 및 병행 금지 안내 추가. 계약 시험은 repo `test/test_ir_source_exclusivity.py`(T2).
- 증거: `python -m pytest test/test_ir_source_exclusivity.py -q` 4 passed(적색 3건 확인 후 초록). `python -m pytest src/core/control/test/ -q` 1292 passed, 28 skipped (2026-09-22 Windows). 근거: communication-protocol-report.md §3.2.1 이중 발행 항.
- gate 변화: 없음.
- 결정: 없음 — 문서화+계약 시험으로 마는 최소 조치. launch 상호배제 강제(한 노드가 다른 쪽 검사)는 필요 시 별도.
- 교훈: 없음.

## 2026-09-22 · uncommitted · control(tools): gz 벤치 도구 절대 토픽 발행 금지 (T12)
- 변경: tools/gz 6개 파일(calibration_mapping_rig·driver·localization_rig·measure_motion_contract·rendered_camera_adapter·rig_estop_probe)의 create_publisher 토픽에서 선행 / 제거 — 상대 이름은 namespace 없이 실행하면 전역으로 풀려 동일, 네임스페이스 안에서는 로봇 ns 로 바르게 풀린다(D-4). 구독은 실제 절대 대상(/pinky/rendered_camera, /tf)이 있어 그대로. 신규 가드 test_gz_tools_topics.py(전 파일 스캔). 부수: PowerShell 리라이트가 붙인 UTF-8 BOM 을 7파일에서 제거(rig_estop_probe 포함, system.py 포함).
- 증거: `python -m pytest src/core/control/test/test_gz_tools_topics.py test_rig_odometry_frames.py test_motion_contract_tool.py test_gz_obstacle_camera.py src/core/core/test/test_api.py -q` 62 passed (2026-09-22 Windows, 적색→초록).
- gate 변화: 없음.
- 결정: 없음 — D-4 준수. D-149 예외 목록에서 벤치 드라이버의 /cmd_vel 발행 제거.
- 교훈: Windows PowerShell 5 의 Set-Content -Encoding utf8 은 BOM 을 붙인다 — 파이썬 소스를 고칠 때는 [IO.File]::WriteAllText + UTF8Encoding($false) 를 쓰거나 편집 도구를 쓸 것.

## 2026-09-22 · uncommitted · control(qos): 센서 토픽 소비자 QoS SENSOR 통일 (T13)
- 변경: startup_calibration_node 의 ir_sensor/range·us_sensor/range·imu_raw 구독과 safety 노드의 us_topic·ir_topic 구독을 depth10(RELIABLE)에서 qos_profile_sensor_data 로 통일 — BEST_EFFORT 구독은 RELIABLE/BEST_EFFORT 발행 모두와 매칭되므로 호환성은 확대만 있다(D-119 소비자 측 완성). STEPS.txt 에 운영자 /estop 발행 시 transient_local QoS 예시 추가(latched 구독과 기본 발행은 영구 비매칭). 신규 가드 test_sensor_qos_unification.py 3건.
- 증거: `python -m pytest src/core/control/test/test_sensor_qos_unification.py test_configured_operation.py test_os_calibration_graph.py -q` 25 passed, 1 skipped (2026-09-22 Windows, 적색→초록). map 소비자 3정책 분할은 의도로 bridge/AGENTS.md 에 기록(T11).
- gate 변화: 없음.
- 결정: 없음 — D-119 완성.
- 교훈: 없음.

## 2026-09-23 · uncommitted · refactor(control): calibration_atomic builds no ROS messages (D-171 track 1)
- 변경: `calibration_atomic.py`에서 `std_msgs` import를 없애고, 기하 불일치 시 정지를 노드의 `stop_wander()`에 맡겼다(`stop_wander`는 다른 세션의 810dc41에 먼저 커밋됐다). `test_calibration_atomic.py`(실제 값 18개)를 추가했다. AST로 떼어 돌리던 `test_configured_operation.py`·`test_rotation_failure_capture.py`는 직접 import로 바꿨다. `KNOWN_ROS_LEAKS`는 16에서 15가 됐다. 흡수 때 빠진 `tools/gz/run_track260905.sh`를 이식했고, 참조 가드 `test_rig_script_references.py`를 추가했다.
- 증거: `python -m pytest src/core/control/test -q` 1310 passed, 28 skipped. 변이 3건(게이트 창, 적용 1.5 s, 기하 정지 제거) 각 적색. WSL Jazzy + Gazebo 8.11, ext4 복사본 rig: 분리 모드 기준본·후보본 모두 `ready`, 비상정지 음성 후보본 `failed`, 한 프로세스 모드는 기준본·후보본 모두 같은 게이트 신선도 실패(기존 결함).
- gate 변화: 없음(control ROS-SIM은 전체 그래프 기준 HOLD 유지).
- 결정: D-171 트랙 1 첫 모듈, D-171 규칙 (d) 개정(사용자 승인 2026-09-23).
- 교훈: 검증 규칙은 그 검증 경로가 실제로 돌아가는지 먼저 확인하고 세운다. 규칙을 쓴 뒤 첫 적용에서야 rig 스크립트가 없다는 것을 알았다.

## 2026-09-23 · uncommitted · test(control): calibration batch rig A/B before merging D-171 track 1
- 변경: 없음(검증과 기록만). 이번 묶음은 5c3dfc4(가드 경로), 4d0d2ee(`calibration_rotation`), 6e08de6(`calibration_relocation`)이다.
- 증거: WSL Jazzy + Gazebo 8.11, ext4 복사본, main `e8b2976` 대 브랜치. 분리 모드는 양쪽 모두 `ready`. 비상정지 음성은 브랜치 `failed`. 한 프로세스 모드 4회씩 돌린 실패 분포가 같다(게이트 신선도 3, 지도 TF 1). 최종 `/cmd_vel` 발행자는 항상 `safety_node`.
- gate 변화: 없음.
- 결정: D-171 (d) 충족, main 병합.
- 교훈: 타이밍에 흔들리는 모드의 A/B는 한 번이 아니라 분포로 본다. 시계 통일과 다중 스레드 실행기는 둘 다 한 프로세스 모드를 더 나쁘게 했다.

## 2026-09-23 · uncommitted · test(control): D-171 track 1 code held back; rig tools merged
- 변경: rig 비상정지 판정(실패 이유 확인)과 결정 탐침(`tools/gz/rig_decision_probe.py`)만 main에 병합한다. `goal_escape`·`safety.scale`·`evidence`·`gate`·`obstacles`·`hazard`·`bumper` 변환은 `refactor/d171-track1`에 보류한다.
- 증거: rig 분리 모드, 계측 없음. main 0/약 12. 트랙 1 트리들은 가장 작은 조합(`goal_escape`+`scale`, 최신 main 위)부터 간헐 실패했다(1/2, 묶음 전체 5/13 등, 평가 문서 §8.2 표). 결정 탐침으로는 실패 실행에서도 결정 흐름이 정상이다. 비상정지 음성 사례는 새 판정으로 "Emergency stop engaged" 실패, PASS.
- gate 변화: 없음.
- 결정: D-171 트랙 1 코드 보류(사용자 승인). 다음 과제는 rig 간헐 실패의 원인이다.
- 교훈: 한 번씩만 돌린 rig 이분 탐색이 틀린 원인을 지목했다. "검증된 부분"이라는 판단도 표본이 쌓이자 뒤집혔다. 타이밍에 흔들리는 검증 수단은 판정 전에 기준본의 실패율부터 잰다.

## 2026-09-23 · uncommitted · fix(control): dock tag detection works on the device's OpenCV 4.6

- 변경: `sensing/dock_tag.py`가 OpenCV 4.7에서 생긴 `cv2.aruco.ArucoDetector`만 불렀다. 실기 이미지는 Ubuntu 24.04의 `python3-opencv`(4.6, `package.xml` exec_depend)를 쓰고, 4.6에는 모듈 함수 `cv2.aruco.detectMarkers`만 있다. 그래서 실기에서는 도킹 인식기가 만들어진 뒤 매 프레임 `AttributeError`로 도크를 한 번도 보지 못했다(`select_detector`는 이미 성공했으므로 simulated로도 떨어지지 않는다). `_detect_markers()`가 있는 API를 `hasattr`로 골라 쓴다(4.6 모듈 함수 / 4.7+ `ArucoDetector`; 개발 PC의 5.0은 모듈 함수가 없다). 시험의 마커 생성도 `generateImageMarker`(4.7+) 없으면 `drawMarker`(4.6)를 쓴다.
- 증거: WSL Ubuntu 24.04 `python3-opencv` 4.6.0에서 도킹 관련 5개 시험 파일(control dock_tag·dock_detector·sensor_provider, games overhead, core docking): 이전 `dock_tag.py` 11 failed / 119 passed, 수정 후 130 passed. Windows OpenCV 5.0.0에서도 130 passed.
- gate 변화: 없음(실기 도킹 DEVICE 증거는 여전히 없다).
- 결정: 없음.
- 교훈: 개발 PC(OpenCV 5.0)와 CI(OpenCV 없음, 시험 건너뜀)가 모두 초록이어도 실기 apt 버전(4.6)에서는 깨질 수 있다. 실기와 같은 배포판 패키지로 한 번은 돌린다.

## 2026-09-23 · uncommitted · fix(control): rotation trial holds zero through its own evidence gap
- 변경: `calibration_rotation.py`. 정지(0 명령) 중인 회전 trial이 신선도 공백을 겪으면 최대 1 s 동안 0을 유지하고, 정지 자세를 확인하며 기다린다(`hold_freshness_lapse`). 끝점 등록 뒤에는 증거 장벽을 둔다. 새 decision과 새 scan이 들어오고 각각 0.1 s 이상의 신선도가 남아야 다음 구간을 시작한다. 등록과 해제 때는 `last_time`을 보정한다. 정지 자세 기준은 가장 최근의 유효한 odom 행이다. e-stop과 hazard는 대기하지 않는다(`rotation_hazard`로 분리, 메시지·순서는 그대로). 테스트: `test_rotation_freshness_hold.py` 19건 신규, `test_calibration_rotation_handoff.py` 스텁 1건 보정.
- 원인: `record_rotation_endpoint`가 `match_motion`을 tick 안에서 동기 실행한다. rig에서 0.3–0.6 s, 경합 없는 x86 코어에서 120–220 ms가 걸린다. 그동안 executor가 막혀 decision·scan·odom이 큐에 쌓인다. sim 시계는 `/clock` 콜백으로만 전진하므로 함께 멈춘다. 풀린 뒤에는 오래된 입력이 0.25 s 창 밖으로 거부되거나 invalid로 기록되고, 한 번의 검사 실패로 trial이 끝났다. 실기에서는 시계가 멈추지 않는다. 그 대신 `dt > 0.5` 검사와 0.25 s 창을 계산 시간 자체가 넘을 수 있다(Pi 측정은 HOLD).
- 증거: host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 1360 passed, 26 skipped. 뮤테이션 16종 모두 검출. WSL Jazzy + Gazebo 8.11, ext4 사본, 분리 모드. 최종본 11회 연속 `ready`. 같은 시간대 교차 실행(부하 5–29): 기준(main `ae99697`) 2/5, 회전 단계 실패 3. 수정본 5/5. 추적 계측(finish 호출 스택, 대기 거절 사유, tick 상태)으로 각 보완이 막는 경로를 확인했다. 독립 리뷰 3회에서 차단 이슈 없음.
- gate 변화: 없음(control ROS-SIM은 전체 그래프 기준 HOLD 유지, DEVICE/FIELD HOLD).
- 결정: 사용자 승인 2026-09-23("정지 중 짧은 대기"). 움직이는 trial, e-stop, hazard, wander 미정지는 이전처럼 즉시 실패한다.
- 교훈: main도 같은 비율로 흔들렸다. D-171 트랙 1 브랜치를 의심한 판단은 박스 부하(피어 세션의 Gazebo)와 시간대 차이를 코드 효과로 오인한 것이었다. 흔들리는 rig는 같은 시간대 교차 실행으로 보고, 실패는 발생 단계별로 센다. stderr 계측은 타이밍을 바꾸므로, 메모리 계수기를 쓰고 1 s마다 파일로 덤프한다.

## 2026-09-23 · uncommitted · docs(adr): D-183 Proposed — 감시 표를 제품과 단독으로 분리

- 변경: `control/watch.py`의 단일 표를 제품 표와 control 단독 표로 나누는 결정을 진행 기록에 연결했다. 표 내용은 바꾸지 않았다.
- 증거: ADR 기록. 실행 시험 없음.
- gate 변화: 없음.
- 결정: D-183 Proposed
- 교훈: 없음

## 2026-09-23 · uncommitted · perf(control): vectorise the calibration wall fit, bit for bit
- 변경: `sensing/wall_tracker.py`의 `_fit`을 numpy로 벡터화했다. 점 쌍 기울기는 행렬로, median은 `_median`으로 계산한다(짝수 개면 두 가운데 값의 평균, 결과가 0일 때만 안정 정렬로 ±0 부호를 `sorted()`와 맞춘다). 반환값은 모두 Python `float`/`int`다. `_segments`는 run마다 배열을 한 번 만들어 `_fit(array=...)`에 넘긴다. 테스트 `test_wall_tracker_equivalence.py`는 원본 `_fit`의 복사본(main `860a6740`)과 결과를 `repr`까지 비교한다.
- 원인: 부하가 높은 rig에서 calibration 노드의 `/scan` 콜백(`on_scan` → `WallTracker.update` → `_segments` → `_fit`)이 프로세스 CPU의 75%였다. scan당 `_fit` 약 130회, 경합 없는 x86 코어에서 27 ms, 부하 28에서 평균 130 ms. 큐가 쌓여 decision 체류가 324 ms까지 늘었고, 0.25 s 신선도 창을 넘어 translation 단계가 실패했다(평가 문서 §8.4 class B).
- 증거: 동등성 — 무작위 벽 3000, y가 거의 겹치는 쌍 1500, 부호 있는 0 3000, scan 60, tracker 연속 12회와 조각 병합 10회에서 `repr` 동일, 모든 값이 builtin 타입. 뮤테이션 8종 모두 검출. 속도: scan당 27.2 ms → 7.2 ms(4.0배, 같은 프로세스 교차 측정). host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과. rig 교차 A/B(부하 약 30): 기준 3/4, 최적화 1/4 통과. 최적화 쪽 실패 2건은 모두 calibration → safety 명령 전달 구간(357 ms, 305 ms)에서 늦었다. 이 구간은 이번 변경과 무관한 safety 프로세스 쪽이다. 이 부하에서 rig는 판정력이 없다(§8.4). 판정 근거는 host 동등성과 결정적 비용 측정이다. 독립 리뷰 1회, 지적(±0 부호) 반영.
- gate 변화: 없음(DEVICE/FIELD HOLD). Pi에서의 scan 콜백 시간은 미측정.
- 결정: 사용자 승인 2026-09-23("wall_tracker 최적화"). 동작은 바꾸지 않는다.
- 교훈: 부하 25–30 이상에서는 코드가 한가해도 OS 스케줄링 공백(약 340 ms)만으로 0.25 s 창을 넘는다. 이 영역의 rig 실패는 코드 판정에 쓰지 않는다. "비트 단위 동일"은 `==`가 아니라 `repr`로 확인해야 한다(-0.0 == 0.0).

## 2026-09-24 · uncommitted · feat(watch): D-183 product and standalone graph tables

- 변경: `watch.py`가 product와 standalone 표를 따로 둔다. 제품 `/cmd_vel` 소유자는 `core`만, 단독 control은 `safety_node`만이다. `watch_node`는 `graph_mode`로 하나를 고르고 기본은 standalone이다.
- 증거: `src/core/control/test/test_watch.py` 포함 57 passed, 10 skipped (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: D-183 Accepted
- 교훈: 없음

## 2026-09-24 · uncommitted · perf(control): vectorise OccupancyMap.inflate cell for cell (D-185 R1)
- 변경: `planning/gridmap.py`의 `inflate`를 numpy로 바꿨다. 분류는 `np.where`로 한다. 원판 오프셋은 원본과 같은 Python float 비교로 만들고, 오프셋마다 출발점 마스크를 슬라이스로 옮겨 OCC를 찍는다. 출발점은 원본의 `v < OCC_THRESH` 부정이라 NaN 셀도 팽창한다(보수적). 출발점이 없으면 바로 반환하고, 반경은 지도 크기까지만 돈다. 계산은 출발점의 경계 상자로 한정한다. 결과는 Python `int` 리스트이고 매번 새 지도다. 테스트 `test_inflate_equivalence.py`는 원본 복사본(main `631ff091`)과 비교한다.
- 원인: goal이 2 s마다 계획할 때 후보별·반경별로 지도 전체를 Python 이중 루프로 부풀렸다(host 200×200 48 ms, 400×400 128 ms, goal tick 평균 177 ms). D-185 조사.
- 증거: 동등성 — 무작위 지도 120개 × 반경 3종, 실제 크기 200×200, 지도보다 큰 반경, 음수·−0.0·NaN·inf 반경의 예외 유형, float·NaN·int8 데이터, 결과의 독립성. `repr` 수준에서 같고 모든 값이 builtin `int`다. 뮤테이션 6종 모두 검출. 속도: 200×200 48→6 ms, 400×400 128→22 ms, 희소 400×400(반경 6–40) 28–34→20–29 ms. host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과. 독립 리뷰 1회(차단 없음). NaN 출발점, 희소·큰 반경 퇴행, 테스트 공백을 반영했다.
- gate 변화: 없음. Pi 수치는 D-185 R8 전까지 HOLD.
- 결정: D-185 R1(사용자 승인 2026-09-24). 캐시 대신 벡터화했고, ADR에 구현 메모를 달았다.
- 교훈: 결과 동일 최적화도 입력 분포가 다르면 느려질 수 있다(희소 지도·큰 반경). 비용은 대표 입력과 극단 입력 모두로 잰다.

## 2026-09-24 · uncommitted · fix(control): a late rotation scan is stale, not missing
- 변경: `rotation_scan_sample(msg, valid, current)`가 유효하지만 0.25 s 창을 넘긴 scan의 내용을 `rotation_scan_late`에 보관한다. `rotation_clear`는 저장된 scan이 없고 기하 프로필이 있을 때, 그 내용을 `calibration_rotation_clearance`에 나이 무한대로 넣는다. 그래서 구조 결함은 여전히 `invalid_scan`이 되고, 구조가 정상인 늦은 scan만 `stale_scan`(정지 중 1 s 대기)이 된다. 진단에는 `scan_stored: False`를 붙인다. `on_scan`은 유효성과 0.25 s 창을 따로 넘긴다. 패키지 크기 판정(D-168 P6)은 재판정했다. split 판정은 그대로 두고 기준을 28,159줄에서 28,315줄로 바꿨다.
- 원인: rig 실행 prof-r2-1에서 끝점 등록 stall(0.445 s) 뒤 큐에서 나온 scan이 `stamped(.25)`에 걸렸다. 그 scan이 `rotation_scan = None`으로 저장돼 `missing_scan_or_geometry`가 났고, 이 사유는 대기 대상이 아니라서 정지 중인 trial이 즉시 실패했다(`hold_refused` 기록). c67437d1 회전 대기 수정의 잔여 경로다.
- 증거: 테스트 신규 8건(늦은 scan의 사유·구조 검사·부재·기하 없음·trial 대기·시작 전 대기·표시 해제, `on_scan` 배선). 뮤테이션 6종 모두 검출. host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과. 독립 리뷰 1회(차단 없음)에서 나온 지적을 반영했다. 구조 검사 우회, 배선·표시 해제·시작 전 경로의 테스트 공백, 진단 정보가 그것이다.
- gate 변화: 없음(DEVICE/FIELD HOLD).
- 결정: 사용자 승인 2026-09-24("고침"). 시작 전(trial 없음) 단계에서 늦은 scan 하나로 재배치를 시작하던 경로가 이제 1 s 관측 대기 뒤 실패로 끝난다. 재배치는 저장된 scan이 없으면 쓸 수도 없었다.
- 교훈: 사유 문자열 하나가 "없음"과 "늦음"을 함께 담으면, 대기 정책이 그 둘을 구분하지 못한다. 판정 입력은 원인별로 분리해 기록한다.

## 2026-09-24 · uncommitted · test(repo): control 패키지 크기 재판정 (D-168 P6, lane-network 병합)

- 변경: `test/test_module_structure.py` `SIZE_VERDICTS["control"]` 기준을 28,315줄에서 **31,249줄**로 바꿨다. 판정은 `split`(P1a, `docs/plans/2026-09-22-control-package-split-design.md`) 그대로다. 예산(10,000줄)과 재성장 허용(+150)은 건드리지 않았다.
- 원인: feat/lane-network-junctions 가 control 생산 코드에 순증 **+2,934줄**을 더했다(main 28,315 → 병합 31,249). 내역: `sensing/` 신규·변경 +2,531(`paint_localizer` 380·`route_camera` 372·`route_hybrid` 319·`route_map` 296·`lane_boundaries` 279·`lane_debug` 194·`lane_coverage` 175·`lane_route` 161·`dock_observer` 96, `dock_tag` +83, `lane_bev` +35), 관측 노드 +250(`dock_observer_node` 102, `line_observer_node` +148), `map_v2_fleet/scripts` +293, `setup.py` +1.
- 증거: `_over_budget()` 실측 control 31,249 / 하위 `sensing` 7,397. 재판정 뒤 `python -m pytest test/test_module_structure.py test/test_module_scorecard.py -q` 15 passed (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: split 판정 유지. 증가분 대부분은 ROS-free leaf `sensing/*`이며 분리 설계가 떼어낼 `control_sensing` 단위에 그대로 들어간다(분리 후 그 단위도 10k 예산 안). 새 600줄 초과 파일은 없다(`lane_bev` 646 = accept 611+150 안). 기준 이동 폭(+2,934, 허용의 약 20배)이 main 선례(+156)보다 훨씬 크므로 독립 리뷰에서 확인받는다. split 미일정 상태는 바뀌지 않았다.
- 교훈: 없음

## 2026-09-24 · uncommitted · docs(control): control 패키지 크기 결정 기록 (D-168 P6, lane-network 병합)

- 변경: 없음(기록만). `SIZE_VERDICTS["control"]` 31,249줄 split 판정은 그대로다.
- 증거: 없음(결정 기록).
- gate 변화: 없음.
- 결정: 2026-09-24 control 31,249줄은 이번 병합에서 기록만 하고, 패키지 분리는 인식 재설계(docs/plans/2026-09-24-perception-architecture-design.md P1~P3)에서 실행한다 — 사용자 결정 2026-09-24
- 교훈: 없음

## 2026-09-24 · uncommitted · tools(control): rig environment guard marks overloaded runs invalid (D-185 R4)
- 변경:
  - `tools/gz/rig_environment.py`를 새로 만들었다. `record`는 2 s마다 loadavg, CPU 압력(PSI), 파티션별 Gazebo 세션 수를 기록하고, 부모가 사라지면 끝난다. `judge`는 순수 함수이고 결과를 `environment.json`으로 쓴다.
  - `run_track260905.sh`는 세션 간 잠금 `/tmp/rosy-gazebo.lock`을 잡는다(`RIG_GZ_LOCK_WAIT`, 대기 초과 시 종료 코드 4). 기록기는 잠금 fd를 닫고 띄우고, 통과·실패 판정 전에 환경을 판정한다. 무효면 통과·실패를 "not counted"로 표시하고 종료 코드 3, 판정기가 비정상 종료하면 그 종료 코드를 그대로 낸다. 환경 파일은 실행마다 지우고 보관하며, HUP도 정리 경로를 탄다.
  - `track_run_monitor.py`가 `elapsed_wall_s`를 기록한다.
  - `run_calibration_spaces.py`는 `outcome()`으로 3·4를 집계에서 빼고, 잠금 대기를 30 s로 제한한다.
  - control 패키지 크기는 split 판정을 유지한 채 기준을 28,315줄에서 28,476줄로 재판정했다.
- 원인: 2026-09-23/24 rig에서 피어 세션의 Gazebo가 부하를 25–30까지 올렸다. 한가한 노드도 CPU를 약 340 ms 기다렸고, 한 실행은 시뮬 속도가 0.01배였다. 이런 실행의 통과·실패는 코드와 무관했다(평가 문서 §8.4).
- 증거:
  - 테스트 18건: 판정 규칙, 워밍업, 기준 초과 비율과 PSI 보고, 요청 대비 속도, 증거 부족 시 판정 보류, 같은 파티션의 Gazebo 중복, 가짜 `/proc`의 세션 집계, 잘린 JSONL 줄, 부모가 사라질 때 기록기 종료, 스크립트 배선, 러너 결과 분류.
  - host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과.
  - WSL smoke 2회: 평균 부하 16.13에서 무효 판정과 종료 코드 3, 표본 147개. 수정 후에는 `elapsed_wall_s` 기록, 실행 뒤 기록기 0개, 잠금 해제를 확인했다. 판정 heredoc은 유효·무효 × 통과·실패 네 경우를 가짜 결과로 실행해 확인했다.
  - 독립 리뷰 1회(변경 요청)의 HIGH 2건과 MEDIUM 4건을 반영했다. HIGH는 실제 실패를 무효로 덮는 문제와 떨어져 나온 기록기가 잠금을 무는 문제였다.
- gate 변화: 없음(rig 도구).
- 결정: D-185 R4(판정 기준은 사용자 승인 2026-09-24: PSI 기록 후 보정해서 전환). 다른 Gazebo 실행기의 잠금 채택은 단계적이다.
- 교훈: 환경 가드도 판정기다. 증거가 없을 때 "무효"로 판정하면 실제 결함을 가린다. 속도 증거가 없으면 판정을 보류하고, 부하 증거가 없을 때만 무효로 둔다.

## 2026-09-24 · uncommitted · tools(control): Pi hot-path and node CPU measurement tool (D-185 R8)
- 변경:
  - `tools/device/hotpath_measure.py`를 새로 만들었다. ROS 없이 돈다. 하위 명령은 둘이고, 각각 JSON 보고서 하나를 쓴다(`schema_version` `rosy.control.hotpath_measure/1`).
  - `bench`: `wall_tracker._segments`(720-ray 벽 scan), `scan_motion.match_motion`(180점 box-room 두 개, 10° 회전), `OccupancyMap.inflate`(200×200, 벽, 반경 5셀)의 median·p90·max(ms)를 잰다. 입력은 동등성 테스트의 생성기와 같은 형태다. platform, Python·numpy 버전, `/proc/cpuinfo`의 CPU 모델, `/proc/device-tree/model`을 함께 기록한다.
  - `watch`: setup.py 진입점 이름(또는 `-m control.<node>`)으로 control 노드 프로세스를 찾는다. 간격마다 `/proc/<pid>/stat` utime+stime 차분으로 CPU%, VmRSS, loadavg, PSI `some avg10`을 기록한다. 재시작된 프로세스(starttime 변경)는 첫 표본의 CPU%를 None으로 둔다.
  - 보고서의 `evidence.device`는 `/proc/device-tree/model`이 Raspberry Pi일 때만 참이다. host 실행은 "not device evidence"로 표시한다.
  - 실기 절차는 모듈 docstring과 device 검증 계획 문서의 2026-09-24 checkpoint에 적었다.
  - control 패키지 크기(D-168 P6)는 split 판정을 유지한 채 기준만 28,476줄에서 28,868줄로 재판정했다.
- 원인: D-185가 Pi 수치를 R8 전까지 HOLD로 두었다. `match_motion`의 Pi 소요 시간(평가 문서 §8.3), scan 콜백 점유율(§8.4), goal tick 비용(R1)을 실기에서 잴 도구가 없었다.
- 증거:
  - 테스트 11건(`test_hotpath_measure.py`): stat 파싱(comm 안의 공백·괄호), 두 표본의 CPU%, PSI·loadavg·VmRSS 파싱, 가짜 `/proc`의 프로세스 매칭(grep 제외), 진입점 이름과 setup.py 일치, 가짜 `/proc`의 watch 표본, 보고서 스키마와 증거 등급, 통계, bench smoke(세 키, `match_motion` 입력 수락).
  - host `python -m pytest src/core/control/test/ test/test_module_structure.py test/test_control_ros_edge.py -q -p no:cacheprovider` 통과.
  - host bench(Windows x86, 증거 아님): `_segments` median 7.7 ms, `match_motion` 80 ms, `inflate` 6.5 ms. WSL `watch` smoke에서 실제 `/proc`의 loadavg·PSI·CPU 모델을 읽었다(노드 없음).
- gate 변화: 없음. Pi 실행은 HOLD다. 이 세션에는 하드웨어가 없고, Pi 수치는 기록하지 않았다.
- 결정: D-185 R8. 도구만 만들었고, 실기 실행과 R1–R3 전후 비교는 남는다.
- 교훈: 측정 보고서가 스스로 증거 등급을 밝혀야 host 수치가 실기 수치로 인용되지 않는다.

## 2026-09-24 · uncommitted · feat(control): opt-in EventsExecutor via ROSY_EXECUTOR (D-185 R3)

- 변경:
  - `control/executor_choice.py`: `ROSY_EXECUTOR` 해석(`single` 기본, `events`, 그 밖은 ValueError), executor 생성, spin.
  - 14개 노드 `main()`의 `rclpy.spin(node)`를 `executor_choice.spin(node, rclpy)`로 바꿨다. try/finally 정리는 그대로다.
  - `events`는 executor의 native `spin()`(add_node → spin → remove_node)을 쓴다. rig도 `make_executor(rclpy, executor_kind())`로 같은 선택을 따른다.
- 원인: 2026-09-24 domain-228 실험에서 구독 15개인 한가한 노드가 SingleThreadedExecutor로 코어의 50–58%, EventsExecutor로 15%를 썼다. Jazzy에서 EventsExecutor는 실험 기능이라 opt-in으로 둔다.
- 증거:
  - 테스트 7건: 기본·single은 이전 호출과 동일, events는 native 루프, spin 예외에도 remove_node, 알 수 없는 값 거부, 두 종류 생성, 14개 진입점이 모두 선택기를 거침(AST).
  - host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 1404 passed.
  - 독립 리뷰 1회(COMMENT, 차단 없음). WSL 탐침으로 SIGINT·SIGTERM·sim-time 타이머·다른 스레드 `call_async`가 두 방식에서 같음을 확인했다. MEDIUM 3건 중 rig와 다른 spin 루프는 고쳤고, ADR 표현과 FATAL 로그 줄은 ADR에 적었다. LOW 중 calib_node import 형식은 고쳤다. 다른 스레드 종료 예외와 잘못된 값의 늦은 실패는 기본 경로를 바꾸지 않으려고 기록만 했다.
- gate 변화: 없음(기본값 불변). rig A/B와 실기 측정 전까지 R3는 미완료.
- 결정: D-185 R3(행동 변경 승인: 사용자 2026-09-24 "나머지도 ralph 로 해서 바로 끝까지 처리").
- 교훈: 측정 경로와 제품 경로가 같은 루프를 돌아야 A/B가 제품을 말한다. `rclpy.spin(node, executor=...)`은 executor의 native 루프가 아니다.

## 2026-09-24 · uncommitted · perf(control): exact footprint sweep prefilter (D-185 R5)
- 변경:
  - `control/footprint_sweep.py`의 `footprint_sweep_clearance`가 시간 샘플 다각형을 먼저 모두 만든 뒤 `_clearances`로 한꺼번에 계산한다. 다각형은 원본과 같은 식(`hull@R+shift`)으로 샘플마다 만든다.
  - `_clearances`는 먼 점을 증명적으로 뺀다. 샘플마다 꼭짓점 평균 c, 최원 꼭짓점 거리 R로 원판 하한 `|p-c|-R`을 구하고, 하한이 가장 작은 점의 정확한 clearance U에 대해 하한이 `max(U,0)+1e-6`을 넘는 점만 뺀다. 증명과 가드(좌표 ≤1e3, 변 ≥1e-6, c가 모든 변 직선에서 1e-3·R 이상 안쪽)는 docstring에 적었다. 가드를 못 넘으면 원본 경로다.
  - 남은 점이 적으면(점 수×샘플 ≤4096) 샘플을 쌓은 broadcast 한 번으로, 많으면 원본 `_clearance`를 샘플마다 부른다. 쌓은 계산도 원소별 연산 순서는 원본과 같다.
  - `footprint_translation_limits`는 `_travel_candidates`로 호출당 한 번 후보를 줄인다. 이 함수에서 나가는 것은 `clearance > margin` 비교뿐이므로, 이동 끝까지 포함하는 원판(c, R+maximum) 하한이 `margin+1e-6`을 넘는 점은 결과를 바꿀 수 없다. 이후 비교는 원본 `_clearance` 그대로다.
  - `_hull`·`_clearance`는 그대로 두었다(`straight_escape`가 쓴다).
- 원인: sim rig의 safety 20 Hz tick이 `footprint_sweep_clearance`(17 샘플 × 모든 점 × 변)와 `footprint_translation_limits`(최대 2×10 이분 탐색)를 부른다. host에서 sweep 호출당 720점 12 ms, 1440점 31 ms였다. `bounded_motion`은 sim 전용이라 rig 여력 회복이 목적이다(D-185 조사).
- 증거:
  - 동등성 `test_footprint_sweep_equivalence.py`(원본 복사본 main `89001aad`, 5건): sweep 900건, translation 500건, Pinky 팔각형 360/720/1440점 × 명령 18종, 이동 축 위 결정 점 160건, `straight_escape` 보조 함수. `repr` 비교와 반환 타입(builtin float/tuple/None) 검사. 분기 도달을 단언한다(명령 무효·기하 무효·비유한·hull 내부·충돌·여유, translation 무효·정지·전량·이분·혼합).
  - 뮤테이션 9종 모두 검출(scratchpad `mut_r5.py`, 파일 바이트 복원 확인).
  - 속도(같은 프로세스 교차 25회 중앙값, Pinky 팔각형, v=.01 w=.05 horizon .8): sweep 방 360/720/1440점 7.4→1.9, 11.1→3.0, 21.3→5.5 ms, 근접 잡동사니 8.5→1.8, 12.0→1.9, 22.8→3.9 ms. translation 방 1.9→1.1, 2.9→1.3, 5.2→2.0 ms, 잡동사니 13.9→5.9, 19.5→6.3, 39.0→8.3 ms. 최악(모든 점이 0.15 m 원 위라 거의 못 뺌) sweep 6.7→7.0, 11.1→9.9, 20.9→19.7 ms.
  - host `python -m pytest src/core/control/test/ test/test_module_structure.py test/test_control_ros_edge.py -q -p no:cacheprovider` 1403 passed, 26 skipped. 패키지 크기 기준은 넘지 않아 바꾸지 않았다.
- gate 변화: 없음(sim 전용 경로).
- 결정: D-185 R5(E, 결과 동일). 발견: 원본은 명령 인자가 numpy 스칼라(`np.float64` horizon 등)면 `np.float64`를 반환한다. 결과 동일 조건이라 이 타입도 그대로 두었다. 가드 조건을 끈 뮤테이션은 코퍼스에서 살아남는다. 가드는 증명의 전제이며, 관측 가능한 반례는 만들지 못했다.
- 교훈: 벡터화는 캐시 크기를 넘으면 오히려 느려진다(모든 점을 쌓은 17×1440×8 broadcast가 루프보다 1.8배 느렸다). 증명적 제외로 계산량을 먼저 줄이고, 남은 양에 따라 경로를 고른다. 비교만 나가는 함수는 값이 아니라 비교 결과를 보존하는 더 강한 제외가 가능하다.

## 2026-09-24 · uncommitted · perf(control): R5 review fixes for the footprint prefilter guards (D-185 R5)
- 변경: 독립 리뷰 APPROVE(MEDIUM 1, LOW 3)를 반영했다. `_travel_candidates` 가드를 maximum ≥ 1e-3으로 올렸다. `_clearances` 가드에 `np.isfinite` 검사를 넣었다. 두 docstring의 반올림 논증을 |e|·|p−q|·r/R 기준으로 고쳤다.
- 원인: 이분 탐색이 이동 변을 maximum/1024까지 줄이므로 1e-6 문턱에서는 방향 반올림 여유가 증명되지 않았다(1e-3에서 약 1e4). Python `max`는 NaN을 버리므로 좌표 크기 가드가 NaN을 통과시킬 수 있었다.
- 증거: 가드 경계 코퍼스 2건 추가. 좌표 1e3·변 1e-6·내접비 1e-3 근처 다각형, 문턱 U+{1e-6,1.5e-6,2e-6}의 점, maximum 1e-3 경계 위·아래, margin±1e-12의 장애물을 쓴다. stacked·샘플별 경로 모두에서 점 제외가 일어남을 단언한다. host 테스트 1405 passed, 26 skipped. 뮤테이션 9종 모두 검출.
- gate 변화: 없음(sim 전용 경로).
- 결정: D-185 R5. 실제 사용값(.03, .12)은 새 문턱 위라 비용 변화가 없다.
- 교훈: 증명의 가드는 반복으로 줄어드는 양(이분 탐색 변 길이)의 최솟값으로 잡는다.

## 2026-09-24 · uncommitted · chore(control): D-168 P6 size re-judge after R3/R5/R8 (D-185)

- 변경: `test/test_module_structure.py`의 control 크기 기준을 28,868줄에서 29,037줄로 바꿨다. 판정은 split 그대로다.
- 원인: R3(executor 선택기), R5(동등성 테스트 대상 코드), R8(계측 도구)이 main에서 합쳐져 기준+150줄을 넘었다. 늘어난 줄은 rig·계측 도구와 사전 필터의 증명 주석이며, deploy closure는 바뀌지 않았다.
- 증거: 병합 후 `test_size_verdicts_are_well_formed_and_current`가 29,037줄로 실패했고, 재판정 뒤 통과했다.
- gate 변화: 없음.
- 결정: D-168 P6 재판정 규칙(성장 150줄 초과 시 재판정), D-185
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(control): latest-only subscriptions keep depth 1 (D-185 R2)

- 변경: calibration·wander·goal_escape·web의 최신 값 구독 12개를 KEEP_LAST depth 1로 바꿨다. `test/subscription_scan.py`와 `test_latest_only_subscriptions.py`가 대상 목록과 depth를 고정한다.
- 원인: depth 10 구독은 executor가 밀릴 때 옛 결정·한계값을 차례로 처리했다. 판정은 항상 마지막 값만 쓰므로 옛 값 처리는 비용이고, 늦게 도착한 옛 값이 잠깐 현재 값처럼 보일 수 있었다.
- 증거:
  - host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과.
  - 독립 리뷰 1회 반영.
  - rig 교차 A/B(ENV:VALID만): 기준본 3/3, R2 4/4 `ready`. 과부하(평균 부하 20–35)로 무효가 된 6회는 세지 않았다. CPU 중앙값 411% 대 428%, 차이 없음.
- gate 변화: 없음.
- 결정: D-185 R2(범위: 사용자 승인 2026-09-24 "제안 범위대로", 위험·can_reverse 포함).
- 교훈: 환경 가드가 없었다면 이번 A/B의 첫 10회 중 9회가 판정에 섞였다. 유효 실행만 세니 양쪽 모두 전부 통과였다.

## 2026-09-24 · uncommitted · tools(control): opt-in throttled /clock relay for the rig (D-185 R6)

- 변경:
  - `tools/gz/clock_relay.py`: gz `/clock`을 `SubscribeOptions.msgs_per_sec`로 줄여 ROS `clock`에 다시 낸다. `--check`는 ROS 없이 빈도를 검사한다.
  - `run_track260905.sh`: `RIG_CLOCK_HZ`가 있으면 bridge의 `/clock`을 빼고 relay를 띄운다. 잠금 전 검사(종료 코드 2), manifest `clock_hz`.
- 원인: Gazebo가 physics step마다 `/clock`을 내서 rig 노드마다 초당 수백 번 깨어났다. bridge에는 빈도 옵션이 없다.
- 증거:
  - 테스트 5건: 빈도 검사, RTF 대비 하한, `--check` 종료 코드, 시계 값 복사, 스크립트가 unset일 때만 per-step `/clock`을 bridge에 넣음.
  - host `python -m pytest src/core/control/test test/test_module_structure.py test/test_control_ros_edge.py` 통과.
  - 독립 리뷰 1회(변경 요청): HIGH 1(D-4 절대 토픽)과 MEDIUM 3(잘못된 값의 늦은 실패, manifest 누락, RTF 대비 하한)을 반영했다. SIGTERM 잡음과 스크립트 시험 강화(LOW)도 반영했다.
  - WSL: 100 Hz 요청 시 약 88 Hz 전달(리뷰 탐침). rig A/B ENV:VALID: bridge 3/3, relay 2/3, rig 노드 CPU 446%→202%. relay 실패 1회는 slam_toolbox lifecycle 응답 유실이다.
- gate 변화: 없음(rig 도구, 기본값 불변).
- 결정: D-185 R6.
- 교훈: 기본 경로를 건드리지 않는 opt-in 도구도, A/B 기준으로 쓰기 전에 실패 분포를 따로 확인해야 한다.

## 2026-09-24 · uncommitted · docs(control): D-185 R3 rig A/B and R7 single-process root cause

- 변경: 코드 변경 없음. R3 rig A/B와 R7 원인 조사 결과를 D-185에 기록했다.
- 원인: R3는 기본값 전환 전에 rig 근거가 필요했다. R7은 2026-09-22부터 원인이 미해결이던 한 프로세스 모드 결함이다.
- 증거:
  - rig(WSL Jazzy + Gazebo, ext4 복사본, 콜백 profiler, 모든 실행 평균 부하 16 미만)에서 R3를 비교했다. main `ROSY_EXECUTOR=single` 3/3, `events` 3/3 `ready`. rig 노드 CPU 중앙값은 440%에서 176%로 줄었다.
  - R7 한 프로세스 모드: `c67437d1^1` 1/3 실패("Fresh final safety command evidence required", sim 19.0 s, 게이트 나이 최대 0.247 s). `76181f00^1` 3/3, main 3/3 `ready`.
  - 오래된 트리는 `environment.json`을 쓰지 않는다. 그 실행의 유효성은 대기열이 기록한 부하(8–9)로 판단했다.
- gate 변화: 없음.
- 결정: D-185 R3·R7. R3 기본값 전환은 실기 측정 뒤 별도 결정.
- 교훈: 증폭 모드에서만 보이던 결함이 분리 모드 flake와 같은 원인일 수 있다. 수정 전후 트리를 나눠 돌려야 원인을 좁힐 수 있다.

## 2026-09-24 · uncommitted · docs(control): first device bench of the D-185 hot paths (R8)

- 변경: 코드 변경 없음. `tools/device/hotpath_measure.py bench`로 Pinky(Raspberry Pi 5)에서 D-185 전후를 쟀다.
- 원인: R1과 wall_tracker 벡터화의 효과는 지금까지 host 수치뿐이었다.
- 증거:
  - `rosy-pinky-e4us`, release 005, `/tmp` 사본(old `c67437d1^1`, new `75c69277`, 도구는 같은 main 파일). 50회, 번갈아 2회씩 돌렸다. 보고서 `evidence.device`는 true다.
  - median: `_segments` 21.2→9.1 ms, `inflate` 47.8→6.5 ms, `match_motion` 약 68→약 69 ms(변화 없음). 합성 입력은 실제 경로를 탔다(segments 1, accepted, grown).
  - 측정 뒤 로봇 `/tmp` 사본과 임시 키 사본은 지웠다.
- gate 변화: 없음. `watch`와 R3 실기 비교는 남았다.
- 결정: D-185 R8.
- 교훈: 운영자 키에 `CodexSandboxUsers` 권한이 붙으면 OpenSSH가 키를 거부한다. 원본은 그대로 두고 권한을 좁힌 임시 사본을 쓴 뒤 지웠다.
## 2026-09-24 · uncommitted · fix(control): ir_adc_node holds the I2C-1 bus lock per cycle (D-192)
- 변경: `ir_adc_node`의 세 채널 읽기를 `/dev/i2c-1` descriptor의 `flock(LOCK_EX)` 안에서 한다. bringup `rosylib.Battery`가 같은 MCU(0x08)의 채널 4를 다른 프로세스에서 읽는다
- 증거: `python -m pytest src/core/control/test src/hardware/bringup/test/test_adc_ownership.py test/test_ir_source_exclusivity.py -q` 통과(2026-09-24 Windows)
- gate 변화: 없음
- 결정: D-192 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · test(control): ir_adc_node bus lock is a behaviour test (D-192 review)
- 변경: fake fd·fake `fcntl` 위에서 `_ADCReader.read_channels`를 돌려 잠금이 세 채널의 쓰기·대기·읽기 전체를 덮고 실패 때도 풀리는지 본다
- 증거: `python -m pytest src/core/control/test/test_ir_adc_lock.py -q` 통과(2026-09-24 Windows)
- gate 변화: 없음
- 결정: D-192 Proposed
- 교훈: 없음

## 2026-09-24 · uncommitted · fix(control): web_common share lookup moves to the node edge (merge of origin/main)
- 변경: `web_http._web_common_dir()`가 `ament_index_python`을 import하던 것을 `web_common_dir(share)` 순수 함수로 바꾸고, `web_node`가 share를 찾아 `node.web_common_dir`로 넘긴다. 로컬 D-194(구 D-187) 커밋과 origin의 D-171 ROS-edge 시험이 합쳐지며 드러난 위반이다
- 증거: `python -m pytest test/test_control_ros_edge.py src/core/control/test/test_web_http.py -q` 14 passed (2026-09-24 Windows)
- gate 변화: 없음
- 결정: D-171, D-194

## 2026-09-24 · uncommitted · test(repo): control 크기 기준 재측정 (main 재병합)

- 변경: `SIZE_VERDICTS["control"]` 기준을 31,249줄에서 **32,106줄**로 바꿨다. 판정은 `split` 그대로다. 같은 병합에서 `sim/gz_sim/scripts/lane_live_view.py`(709줄, live viewer v2)에 accept 판정을 추가했다.
- 원인: main 재병합(672834e7까지)으로 main 쪽 control 증가분(main 기록 29,037)이 합쳐졌다. 브랜치 순증은 이전 기록과 같다.
- 증거: `_over_budget()` 실측 control 32,106. `python -m pytest test/test_module_structure.py -q`에서 남은 실패 1건(`test_every_cross_package_use_is_declared`, `web_http.py → web_common`)은 main에서도 똑같이 실패한다. 이 브랜치와 무관하다.
- gate 변화: 없음.
- 결정: 사용자 결정 2026-09-24를 따른다(기록만 하고, 분리는 인식 재설계 P1~P3에서).
- 교훈: 없음

## 2026-09-24 · uncommitted · docs(adr): D-199 camera perception contracts and backends
- 변경: `docs/adr/D-199-camera-perception-contracts-and-backends.md` 추가(Proposed), ADR Log 표 D-199 행, `progress.md`의 `adrs`에 D-199. 실물 영상 기준선 `docs/validation/perception-real-video/2026-09-24/baseline.md`와 스틸 3장을 추가했다. 인식 설계 문서에 D-199 링크 한 줄. 코드 본문은 바꾸지 않았다.
- 증거: 실물 영상 7개(4981프레임) 재생, REAL VIDEO REPLAY host only, DEVICE: NOT RUN. `centre` BOTH 13% · ONE 36% · MEMORY 14% · STOP 37%, 장치 기본 `line` 모드가 22%의 프레임에서 벽으로 조향, `road.py` 정지선 89.5%. 재생 스크립트는 저장소 밖이고 정답이 없다.
- gate 변화: 없음. 이전 25° 세계의 시뮬 합격은 장치 증거가 아니다.
- 결정: D-199 Proposed. 두 층 계약(`perception/evidence`, `perception/frame`), 교체 가능한 백엔드, 공통 GroundProjector·SceneTracker, 프로필 revision fail-closed, 기존 관측 토픽은 파생 출력으로 유지. control 분할(32,106줄)은 P1–P3 안에서 실행한다.
- 교훈: 없음

## 2026-09-24 · uncommitted · docs(adr): D-205 real lane mission transition order
- 변경: `docs/adr/D-205-real-lane-mission-transition-order.md` 추가(Proposed), ADR Log 표 D-205 행, `progress.md`의 `adrs`에 D-205. D-199·D-200에 see-also 한 줄, 인식 설계 문서에 D-205 링크 한 줄. `harness.yaml`의 `adr_gaps`에 D-201–D-204(concept 16과 역할 화면 설계가 먼저 쓴 번호)를 선언했다. 코드 본문은 바꾸지 않았다. 앞 커밋에서 프로토타입 스크립트를 `tools/perception/prototype/`에, 카메라 프로필 초안을 `docs/validation/perception-real-video/2026-09-24/camera_profile_draft.json`에 두었다.
- 증거: 옮긴 `replay.py` + `analyze.py`가 이 트리에서 기준선을 재현했다(4981프레임, `centre` BOTH 13.0 · ONE 36.0 · MEMORY 14.3 · STOP 36.7, `line` 벽 조향 22.4%, 정지선 89.5%). REAL VIDEO REPLAY, host only; DEVICE: NOT RUN.
- gate 변화: 없음.
- 결정: D-205 Proposed. P0 실측 → P1 계약 → P2 재생 도구 → P3 새 RuleBackend·SceneTracker → P4 현실화한 Gazebo → P5 재합격 → P6 장면 요소 주행 반영, 단계마다 게이트. 장치 주행은 P3·P5 통과 뒤. control 분할은 P1–P3 안에서.
- 교훈: 없음. 후속: line_observer `camera_x_offset_m` 0.034(참값 0.028481), 주점 규약 `W/2` 대 `(W-1)/2`, `MOTION_ALONG_SIGMA_PER_M` 0.10 과신.

## 2026-09-24 · uncommitted · docs(validation): P0 track measurement sheet (D-205)
- 변경: `docs/validation/perception-real-video/2026-09-24/p0_track_measurements.md` 추가. D-205 P0 실측 항목 8개(차선 간격·테이프 폭·횡단보도 막대·링 지름·매트 외곽·벽 높이·렌즈 높이·렌즈 앞 오프셋)를 측정 방법·참고값(CAD/영상 추정)·기입란과 함께 정리했다. 게이트(재생 BEV 차선 간격 ±5 mm) 절차와 측정 뒤 프로필 확정·보관 규칙(이 폴더에 revision으로 두고 `src/robots/pinky_pro/config/`는 D-196 PR #36 이후)을 적었다.
- 증거: 없음(측정 대기). 코드와 프로필 본문은 바꾸지 않았다.
- gate 변화: 없음.
- 결정: P0 시작. 실측값이 오면 확정 프로필(revision `measured-<날짜>`)을 만들고 `camcal/bevfinal.py`로 게이트를 잰다.
- 교훈: 없음.

## 2026-09-24 · uncommitted · docs(adr): D-206 P0 measurement procedure and profile custody
- 변경: `docs/adr/D-206-p0-measurement-procedure-and-profile-custody.md` 추가(Proposed). ADR Log 표 D-206 행, `progress.md`의 `adrs`에 D-206, D-205 끝에 see-also 한 줄. 측정 기록지의 오타(축척 퇴개→퇴화)를 고쳤다. 코드 본문은 바꾸지 않았다.
- 증거: 절차 결정이라 게이트 증거는 없다(측정 대기). 기록 형태는 `test/test_harness_contracts.py`·`test/test_network_topology_contracts.py`로 확인한다.
- gate 변화: 없음.
- 결정: D-206 Proposed. 측정 표준은 기록지, 확정 프로필 revision은 `measured-YYYY-MM-DD`, 게이트는 `camcal/bevfinal.py`의 c-c 세 지점(0.2/0.3/0.5 m)이 실측 ±5 mm, `src/robots/pinky_pro/config/`은 D-196(PR #36) 머지 뒤 만든다.
- 교훈: 없음.

## 2026-09-24 · uncommitted · docs(validation): P0 lens height reading 63 mm (tentative)
- 변경: 측정 기록지 B-7행에 렌즈 높이 잠정치 63 mm(2026-09-24 1회 판독)를 기입했다. 코드와 프로필 본문은 바꾸지 않았다.
- 증거: 사용자 판독 1회. 초안 67 mm보다 낮고, 초안의 "CAD 차선 185 mm → 높이 63.7 mm" 앵커와 일치하는 방향이다. 확정은 1번(차선 간격)·3번(막대 피치) 실측 뒤 fx·높이 합동 재맞춤(D-206 결정 2)으로.
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음.
