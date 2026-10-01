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

## 2026-09-24 · uncommitted · fix(core,robots): clear error for a missing robot package; ship robots in docker/ci (D-196 review)

- 변경: `README.md`·`CLAUDE.md` 빌드 예시를 `--packages-up-to core pinky_pro`로 — CORE가 읽는 로봇 프로필이 이제 `pinky_pro` 패키지에 있다(D-196).
- 증거: 문서만. WSL Jazzy에서 같은 선택으로 빌드 8 packages finished (2026-09-24).
- gate 변화: 없음
- 결정: D-196 Proposed
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

## 2026-09-25 · uncommitted · refactor(control): camera and lane evidence under sensing/perception

- 변경: 카메라·차선·도로·장면 모듈을 `control/sensing/perception/`으로 이동. 라이다·차체·도크 태그는 `sensing/`에 남김. import 경로를 같이 고침.
- 증거: `python -m pytest src/core/control/test/test_perception_folder.py src/core/control/test/test_lane.py src/core/control/test/test_camera.py src/core/control/test/test_road_perception.py src/core/control/test/test_scene_context.py src/core/control/test/test_line_modes.py test/test_module_structure.py -q` 131 passed (2026-09-25 Windows).
- gate 변화: 없음
- 결정: D-209, D-228
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(runtime): move control under src/runtime (D-231)

- 변경: src/runtime/control로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-29 · uncommitted · web-surface-hardening: PARKED web_node 루프백·Origin 고정

- 변경: `web_node`는 `bind_host`(기본 127.0.0.1, `config/web.yaml`·docstring에 문서화) 위에서만 듣는다. `Access-Control-Allow-Origin: *`를 지우고 페이지 출처(127.0.0.1·localhost·요청 Host 이름 + page port)에만 CORS를 답한다. 다른 출처 Origin의 POST는 403. `web_common_dir()`의 없는 `core/web_common` 대체 경로를 `src/hmi/web`로 고치고 `/common` 목록은 `manifest.json`에서 읽는다.
- 증거: `python -m pytest src/runtime/sensing/test -q` 1665 passed 78 skipped(단독 실행). `test_web_http.py` 16 passed.
- gate 변화: 없음. 진단 전용(D-150/D-253) 경계 그대로.
- 결정: D-150, D-253.

## 2026-09-29 · uncommitted · feat(traffic): 무신호·관측 융합 폐루크 호스트 시뮬레이션

- 변경: `tools/sim/simulate_semantic_road.py`의 결정론적 합성 카메라 폐루프에 시나리오 2종을 추가했다 — `stop_and_go`(무신호 선언: 정지+dwell 후 `PROCEED/unsignalized_proceed`, 신호 관측 시 `HOLD/signal_unexpected`)와 D-337 관측 융합(카메라 신호 미관측 + `SignalHeadEvidence` 주입: `signal_unknown` 무한 대기 → `PROCEED/signal_green`(signal_source_kind=fused), 불일치 `HOLD/signal_source_conflict`). 폴러 전송은 가짜 없이 정책 계층에서 주입하고 전송 계약은 기존 `test_observer_source.py`가 담당한다. 상태 타임라인 SVG는 표본 수에 맞춰 높이가 늘어난다.
- 증거: `docs/validation/semantic-road-stop-and-go-2026-09-29/` — `SEMANTIC_ROAD_HOST_SIM_PASS`, 표 3종·result.json·SVG·montage·preview. `test_semantic_road_simulation.py` 신규 단언(무신호 진입·선언 충돌·융합 3단·fused 표기) 포함 2 passed, flake8 clean.
- gate 변화: 없음. HOST-SIM 한계 그대로 — 실물 Gazebo 폐루프(WSL), 관측 서비스 실HTTP, DEVICE/FIELD는 T5 벤치 회차가 소유한다.



## 2026-09-29 · uncommitted · feat(control): image-space two-boundary lane keeper ('between' mode)
- 변경: `lane.py`에 `LaneBetweenKeeper`·`detect_lane_between` 추가. 아래쪽 띠의 여러 행에서 기준 열 왼쪽·오른쪽의 가장 가까운 밝은 런을 찾아 두 안쪽 가장자리의 중점을 목표로 삼는다. 한쪽만 보이면 그 가장자리에서 학습한 차선 폭(행별 EMA, 기본은 화면 폭의 0.6)의 절반만큼 안쪽을 목표로 삼는다. 기준 열은 직전 목표를 따라간다. 지면 평면이 필요 없다. `line_observer_node`에 `camera_lane_mode: between`과 파라미터 `camera_between_roi_top_fraction`(0.6), `camera_between_lane_width_fraction`(0.6, 읽기 전용)을 추가했다. 기본값 `line`은 그대로다.
- 증거: `python -m pytest src/runtime/sensing/test/ -q` 1670 passed, 78 skipped (2026-09-29 Windows). 새 `test_lane_between.py` 10건이 한쪽 선만 보일 때 `detect_lane_error`는 선 위를 가리키고 `between`은 차선 안쪽을 가리키는 것을 확인한다.
- gate 변화: 없음. 실물 주행 확인 전이다.
- 결정: 없음.
- 교훈: 실물 로봇은 homography가 꺼져 있어 지면 평면이 필요한 차선 모드를 못 쓰고, `line` 모드의 밝은 화소 중심은 경계선이 하나만 보이면 그 선 위로 조향한다.

## 2026-09-30 · uncommitted · fix(structure): declare imu_bno055 exec_depend

- 변경: package.xml에 `<exec_depend>imu_bno055</exec_depend>` 추가 — KNOWN_UNDECLARED에서 (control, imu_bno055) 제거. KNOWN_DIRECTION에는 유지(방향 위반은 코드 이동이 필요하므로).
- 증거: test_module_structure 33 passed.
- gate 변화: 없음.
- 결정: 선언은 정직한 절반 — 전체 해소는 bringup 조립로 이전(별도 과제).
- 교훈: 없음.

## 2026-09-30 · faa60733 · D-359 US-002 진단 페이지 어둡게 고정

- 변경: `web/diagnostic.html`의 `<html>`에 `data-theme="dark" data-theme-pin="dark"`. 자체 `color-scheme: dark`는 고정 표면이라 둔다.
- 증거: 레지스트리 `theme:` 규칙 0건. `test_map_raster_color_contract.py::test_the_javascript_mirror_agrees_with_its_own_css_token`은 이 변경 전(960a76f2, US-001 이름 변경)부터 `muted` 키로 빨갛다 — 이 항목과 무관하며 열린 문제로 남긴다.
- gate 변화: 없음.

## 2026-09-30 · f637c1cd · D-359 US-003 진단 페이지 JS 사본 키를 --ink-quiet에 맞춤

- 변경: `web/diagnostic.html` `const T`의 `muted` 키를 `inkQuiet`로(사용처 1곳 `T.inkQuiet`), `test_map_raster_color_contract.py` 별칭에 `inkQuiet → ink-quiet`. 시험 뜻(JS 사본 = 같은 파일 CSS 토큰)은 그대로다. PARKED 표면이라 그 밖은 고치지 않았다.
- 증거: `python -m pytest src/runtime/sensing/test/test_map_raster_color_contract.py -q` 3 passed(US-002 항목의 열린 문제 해소).
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 진단 표면 @media 범위 문법

- 변경: `web/diagnostic.html` `max-width: 1279px/900px` → `(width <= 1279px)`·`(width <= 900px)`(같은 뜻). PARKED라 값은 옮기지 않고 surfaces.yaml `control-diagnostic.breakpoints`에 이유와 함께 적었다.
- 증거: `test_map_raster_color_contract.py` 통과, `test_responsive_tiers.py` 통과.
- gate 변화: 없음.

## 2026-09-30 · 79787e7a · D-371 US-010 진단 정지 세 버튼에 data-always-live

- 변경: `web/diagnostic.html`의 비상정지 `정지`, `주행 정지`, 수동 조종 `정지`에 `data-always-live`. 진단 페이지는 ui.js를 실으므로 `test_stop_always_live.py` 계약 대상이다. PARKED 표면이라 그 밖은 고치지 않았다.
- 증거: `python -m pytest src/hmi/web_common/test/test_stop_always_live.py -q` 통과.
- gate 변화: 없음.
## 2026-09-30 · uncommitted · feat(perception): D-356 인식 학습 루프 섀도 백엔드·녹화·도구

- 변경: `perception/learned/`(manifest·lane_mask·runner·shadow)와 공유 `image_frame.py`, `learned_lane_node`(+`launch/learned_lane.launch.py`), `recording.py`+`record_session`(콘솔 스크립트 2개) 추가. 개발자 쪽 `tools/perception/{dataset,model,training}`(추출·사전 라벨·데이터셋 빌드·발행·ONNX 내보내기·접수·전달/롤백)과 `tools/perception/test`. 학습 노드는 섀도 전용이라 명령 필드가 없고 `executor_choice.spin`으로 돈다. `hotpath_measure.NODE_NAMES`와 executor 선택 시험 개수를 새 진입점에 맞췄다.
- 증거: 전체 sensing 스위트 1741 passed 80 skipped(신규 진입점 반영 뒤 실패 2건 수정: executor 선택·hotpath 이름 계약); `tools/perception/test` 94 passed 8 skipped(2026-09-30 Windows).
- gate 변화: 없음. SOURCE/LOCAL만 다룬다. 노드 그래프·Pi 실행은 HOLD.
- 결정: D-356 Proposed(섀도 전용; 주행 활성화는 D-205 P3 뒤 별도).
- 교훈: 새 콘솔 스크립트는 `hotpath_measure.NODE_NAMES`와 `test_executor_choice`의 진입점 개수 계약을 함께 건드린다. 전체 스위트를 돌려야 잡힌다.

## 2026-09-30 · uncommitted · fix(perception): D-356 리뷰 수정·수치 인터프리터 명기

- 변경: 바로 위 D-356 기록의 수치 인터프리터 명기 — sensing 전체 1741 passed 80 skipped와 `tools/perception/test` 94 passed 8 skipped는 시스템 Python 3.14.5 실측. 리뷰 수정: `recording.py`에 `CAMERA_TOPIC`·`SIDE_TOPICS` 공유 상수와 `bag_command(namespace=)`, `record_session --namespace`, `hotpath_measure.NODE_NAMES`에서 `record_session` 제외(노드가 아닌 `ros2 bag record` 래퍼; 시험은 `NON_NODE_SCRIPTS`를 뺀다), `learned_lane_node.main`이 `line_observer_node.main`과 같은 종료 패턴.
- 증거: venv Python 3.12.14에서 learned·image_frame·recording·executor_choice·hotpath 시험과 `tools/perception/test` 204 passed 2 skipped; 시스템 Python 3.14.5에서 `tools/perception/test`+hotpath+recording 133 passed 10 skipped(2026-09-30 Windows).
- gate 변화: 없음. SOURCE/LOCAL만.
- 결정: D-356 Proposed 유지.
- 교훈: 없음.

## 2026-09-30 · uncommitted · feat(ros-sim): camera 슬라이스 통과 — 무장치 부팅 결함 1건 발견·수리 (27def3de)

- 변경: WSL2 Jazzy에서 control을 현재 트리(27def3de)로 재빌드해 두 노드를 살아있는 그래프로 검증했다. (A) camera_detect_node 무장치 부팅 — 카메라 실패 로그 후 1 ms 만에 `camera_detect ready`, 발행자 9종+보정 구독 그래프 형성. (B) line_observer_node camera 모드 — 합성 레인 5단계(중앙→좌→우→무선→와시드) 133건 관측, 레짐 순서·오차 부호(−0.503/+0.497)·불변식 전부 PASS. 두 그래프 모두 twist 토픽 0개, line/observation 발행자 1개(D-38 sensing-only 유지). 검증 중 OpenCV auto 백엔드의 GStreamer 경로가 무장치 실패에 5–13 s 걸리고 invalid-context hang을 내는 결함을 발견, `_OpenCVCamera`를 CAP_V4L2로 고정해 수리(커밋 27def3de, 호스트 시험 30 passed).
- 증거: docs/validation/control-camera-line-ros-sim-2026-09-30/ (콘솔·node info·JSONL·검증 출력·격리 로그). VERDICT: PASS (0 problems).
- gate 변화: ROS-SIM HOLD 유지 — blocker에 camera 슬라이스 통과 기록. 남은 것: calibration/planning/safety-policy 그래프, Gazebo 폐루프, 물리 센서.
- 결정: 없음.
- 교훈: "컨테이너에서 재실행"이 실제로 노드를 띄우는 순간 잠복 결함이 드러난다 — 이 결함은 3개월(흡수 후) 동안 아무도 무카메라로 노드를 켜보지 않아서 못 본 것이다. ROS-SIM 게이트의 존재 이유다.

## 2026-09-30 · uncommitted · feat(control): 공칭(NOMINAL) 지면과 차선 녹화 재생 벤치(D-353)
- 변경: `config/camera_nominal_pinky_pro.yaml`(실물 녹화 4981 프레임으로 추정한 OV5647 기하 — fx 281.6, 피치 8°, 높이 0.067 m, 지평선 80.3 행). `camera_ground.nominal_ground_plane`(NOMINAL 출처 + 허용 플래그 두 겹, 프레임 크기로 비례, 종횡비 다르면 거부). `line_observer_node` 에 `allow_nominal_ground`·`nominal_camera_profile_path`(읽기 전용), 지면 모드 관측에 `ground: NOMINAL` 표시 — CORE 는 운전자 확인(hold) 없이는 멈춘다(`nominal_ground_requires_driver`). `tools/lane_replay.py` 녹화 재생 벤치.
- 증거: 벤치 기준값(목표가 흰 선 위인 비율) — pilot 녹화 307 프레임: line 0.512, between 0.135, centre(공칭 지면·기억 없음) 비가시 0.99. 원본 teleop 576 프레임: line 0.247, between 0.109, centre 비가시 0.865. `test_nominal_ground.py` 10 passed.
- gate 변화: SOURCE 진행(실물 카메라 지면 모델·벤치). centre 가 실물 영상에서 거의 늘 비가시 — 인식 v2 가 벤치에서 먼저 통과해야 한다.

## 2026-09-30 · uncommitted · feat(control): 지면 기하 차로 유지기 'keep' 모드(D-353 §2)
- 변경: `perception/lane_keep.py` 의 `LaneKeeper`. 매 프레임(오도메트리 없음) 바닥 전용 흰색 마스크(지평선 아래, 벽 밑변 아래, 행별 카펫 기준 대비 적응 임계, 채색·오버레이 제외) → lane_bev 조감 격자 → RANSAC 직선. 옆이 같이 밝은 선(벽 쐐기·덩어리)과 진행 방향과 65° 넘게 어긋난 가로 표시(정지선·횡단보도)는 경계에서 뺀다. 좌·우는 영상 행이 아니라 앞 0.22 m 에서 지면 선의 횡오프셋 부호(base_link y, 왼쪽 +)로 가른다. 목표는 차로 폭(0.6-1.6배)만큼 떨어진 가장 가까운 좌·우 경계의 가운데 선을 앞보기 0.25 m 에서, 한쪽만이면 그 선을 반폭 안쪽으로 옮긴 선, 없으면 None(HOLD). error = -목표 y / 반폭(양수 = 오른쪽 조향). `last` 에 경계·가로 표시·목표(m, 화소)·전략(both/left_only/right_only)을 담는다. `line_observer_node` 에 `camera_lane_mode: keep`(지면 `self._ground`, `ground: NOMINAL` 표시). `tools/lane_replay.py` 에 `keep` 검출기와 `on_paint_rate`(검출기 자신의 목표점이 바닥 칠 위인 비율) 추가 — 기존 `on_line_rate` 는 하단을 가로지르는 정지선이면 어느 열이든 걸리고 벽 화소를 센다.
- 증거: 벤치(공칭 지면) pilot 307 프레임 on_line/on_paint/none — line 0.512/0.399/0.16, between 0.135/0.118/0.202, centre -/-/0.99, keep 0.102/0.015/0.332(비가시 증가분은 대부분 장애물 상자·벽 정면 프레임). teleop 576 프레임 — line 0.247/0.218/0.03, between 0.109/0.126/0.158, centre 0.038/0.026/0.865, keep 0.042/0.071/0.094. 새 `test_lane_keep.py` 11 passed, `pytest src/runtime/sensing/test/ -k "lane or ground or observer"` 293 passed, 12 skipped (2026-09-30 Windows).
- gate 변화: SOURCE 진행(녹화 재생 벤치에서 keep 이 line·between 보다 목표-선 위 비율이 낮다). 실물 주행·가제보 확인 전이다.
- 결정: D-353
- 교훈: 공칭 지면에서는 좌·우 경계가 ±20° 까지 벌어져 보여(주행 중 피치) 원점까지의 수직 거리는 믿을 수 없고, 보이는 범위 안의 한 거리에서 잰 횡오프셋이 안정적이다.

## 2026-09-30 · uncommitted · docs(adr): pilot ADR 번호를 main 과 겹치지 않게 다시 매김
- 변경: main 이 D-346~D-353 을 다른 결정으로 먼저 썼다. 이 모듈 기록의 옛 번호는 다음으로 읽는다 — D-346→D-362(운전자 실시간 영상), D-347→D-342(수동 한도 계단), D-348→D-343(방·운전석), D-349→D-344(보조 자율), D-350→D-363(카메라 비율·설치 앱), D-353→D-364(차로 유지 인식·재생 벤치). 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/` 파일 이름·ADR Log 행·코드 주석·시험이 새 번호를 쓴다. D-342~D-344 는 main 의 harness 가 이 pilot 초안용으로 예약해 둔 번호다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · feat(control): 'keep' 폐루프 가제보 주행 — L 모서리 회전(선택)과 한쪽 flank 시험(D-353 §5)
- 변경: `perception/lane_keep.py` — (1) 모서리 회전 `corner_turning`(노드 `lane_corner_turning`, 실물 기본 false, real-profile sim launch 는 true): 앞을 가로지르는 선이 한쪽은 바깥 차로선에서 끝나고 다른 쪽으로 차로 밖까지 뻗으면 다음 차로의 바깥 경계로 보고, 반폭 안쪽 중심선을 열린 쪽으로 앞보기 0.12 m 에서 추종(그보다 멀면 직진). 방향은 프레임 수로 잠그고(자세 없음), 돌기 시작하면 직진으로 돌아가지 않으며, 잠금 중에는 열린 쪽으로 35° 넘게 기운 선도 모서리 선이고 이런 선은 잠금을 소모만 한다. (2) flank 시험을 한쪽 기준으로 — 양쪽 flank 가 다 밝거나(각 0.225×core) 합이 0.6×core 를 넘을 때만 blob(횡단보도 막대 옆 차로선이 살아남는다). `tools/lane_replay.py` 에 `keep_corner` 검출기와 `--keep-bright`. 하네스 `docs/validation/map-v2-fleet-keep-2026-09-30/`(keep_run.py, make_video.py, run_sim.sh, result.md).
- 증거: real-profile sim(ROS_DOMAIN_ID 53, CORE 8093, sim 전용 장애물 정지 0.10/0.14 m) 폐루프 — 서쪽 직선은 모든 run 에서 횡오차 최대 3.4 mm, A8 1.531 m(좌하 L 모서리·하단 직선·셰브런 굽이 통과, 횡오차 평균 25.3/최대 84.5 mm, 모서리 안쪽 자름), 회전교차로 앞에서 LOST. 녹화 벤치(keep 기본) pilot on_line/on_paint/none 0.102/0.015/0.332 → 0.083/0.015/0.332, teleop 0.042/0.071/0.094 → 0.043/0.070/0.080(on_line 한 프레임 악화, 눈부심 곡선 f_00121). `test_lane_keep.py` 18 passed (2026-09-30 Windows). 영상·궤적 `X:\DevTemp\rosy-pilot-evidence\2026-09-30-sim-keep\`. DEVICE: NOT RUN.
- gate 변화: ROS-SIM 진행 — keep 직선 차로 유지 통과, L 모서리·60° 굽이 통과(안쪽 자름), 회전교차로·분기 실패(fail-closed). 한 바퀴 미달.
- 결정: D-353. 모서리 회전은 실물에서 끈 채로 둔다(벤치 on_line 지표가 모서리 프레임에서 나빠지고 실물 검증 전).
- 교훈: 모서리 로직은 2 fps 표본으로는 재현되지 않았다 — 매 카메라 프레임(8 fps)을 저장해 오프라인으로 같은 순서로 재생하자 잠긴 방향 뒤집힘이 그대로 재현됐다. L 모서리에서 둘레 벽이 base_link 앞 ~0.2 m 라 장치 기본 장애물 정지(0.20 m)에 걸린다.

## 2026-09-30 · uncommitted · docs(adr): 운전자 실시간 영상 ADR 을 D-362 에서 D-368 로
- 변경: 다른 세션이 main 작업 트리에서 D-362(코드 유형별 파일 크기 예산)를 쓰고 있어, 이 모듈 기록의 D-362(운전자 실시간 영상, 옛 D-346)는 D-368 로 읽는다. 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/D-368-pilot-live-driver-video.md`, ADR Log 행·코드·시험이 새 번호를 쓴다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · feat(ros-sim): planning 슬라이스 통과 — goal_node 합성 지도·TF 그래프 검증

- 변경: goal_node를 WSL2 Jazzy 살아있는 그래프에서 검증했다. 합성 2×2 m 점유 격자(미지 사분면으로 프론티어 형성) + TF map→odom→base_link + explore→stop 명령. 프론티어 골 발견(1.19,1.59, route 0.65m), 실경로 9건 + 문서화된 빈-Path 취소 11건, 스톨 감지·탈출 기계 작동, 정지 확인, 그래프 twist 토픽 0개(advisory-only). VERDICT: PASS (0 problems).
- 증거: docs/validation/control-goal-planning-ros-sim-2026-09-30/ (JSONL·콘솔·토픽 목록·검증 출력). 초기 검증기가 취소 Path를 위반으로 오판했으나 이는 "침묵은 정지 명령이 아니다"의 문서화된 메커니즘 — 검증기를 계약에 맞게 수정한 뒤 판정했다.
- gate 변화: ROS-SIM HOLD 유지 — blocker에 planning 슬라이스 통과 기록. 남은 것: calibration(병행 세션 진행 중)·safety-policy 그래프, Gazebo 폐루프, 물리 센서.
- 결정: 없음.
- 교훈: 검증기의 오판은 노드 소스의 의도 주석(_clear_route "Revoke old routes immediately; silence is not a stop command")과 대조해야 한다 — 계약 문서가 검증기보다 위다.

## 2026-09-30 · 7e467a4b · feat(control): 읽기 전용 IR 차선 교정 도구와 좌·우 부호 확인

- 변경: `control/sensing/perception/ir_calibration.py`(순수) — 카펫·왼쪽·가운데·오른쪽 네 자리 표본에서 채널별 중앙값 끝점, MAD 잡음, ADC 끝(0·4095) 비율, `min_span`·잡음 6 배 분리, 테이프 둔 센서가 가장 크게 움직였는지(채널 순서), `detect_ir_line` 되읽기 부호(카펫 = 선 없음, 왼쪽 ≤ −0.3, 가운데 |e| < 0.3, 오른쪽 ≥ +0.3)를 검사하고 통과 때만 관측 노드 YAML(실수형)과 CORE `ir_calibration_revision` 을 찍는다. `tools/device/ir_line_calibrate.py` — run/capture/compute/check, rclpy 는 표본 수집 때만 import, 구독만 한다.
- 증거: 새 `test/test_ir_calibration.py` 9 passed — 합성 표본(잡음·이상치) 끝점, 노드와 같은 해시, 역극성 허용, 분리 부족·잡음·빠진 단계·레일 고정·좌우 뒤바뀜 거절, CLI compute 오프라인 (2026-09-30 Windows).
- gate 변화: SOURCE 진행. DEVICE: NOT RUN(로봇 부재) — 절차 `docs/deployment/pinky-pro-ir-line-calibration-runbook.md`.
- 결정: D-344 §12 보강.

## 2026-09-30 · 6f00a74d · fix(camera): 기기 IR 교정 덮어쓰기 파일을 line_observer 에 싣는다

- 변경: 실물 `line_observer_node` 는 `rosy-camera`(`camera_preview.launch.py`)에서 돌며 패키지 `config/line_follow.yaml` 만 읽었다 — `/etc/rosy/line_follow.yaml` 에 교정을 써도 닿지 않았다(그 파일은 Compose·내비게이션 그래프만 읽음). 파일이 있으면 패키지 기본 뒤에 덧읽는다. `test/test_native_systemd_contract.py` DECLARED_READS 에 rosy-camera 의 그 경로를 선언.
- 증거: 선언 전 `test_declared_paths_account_for_every_write_root_in_the_program[rosy-camera.service]` 빨강, 선언 뒤 `test_camera_image_stack.py test_native_systemd_contract.py` 129 passed, 1 skipped (2026-09-30 Windows).
- gate 변화: SOURCE. 실물 재시작 확인 전.
- 결정: D-344 §12 보강.

## 2026-09-30 · uncommitted · fix(camera,control): IR 교정 덮어쓰기를 전용 경로·검증으로, 도구 문턱 인자(검토 반영)

- 변경: 덮어쓰기 경로를 `/etc/rosy/ir_calibration.yaml` 로 분리(`/etc/rosy/line_follow.yaml` 은 내비게이션 그래프용 전체 설정). 새 `control/ir_overlay.py` 가 모양(관측 노드 블록 하나, IR 교정 키만, 실수형, 켜면 `IRLineCalibration` 통과)을 검사하고 `camera_preview.launch.py` 는 통과할 때만 싣고 `LogInfo` 로 loaded/skipped 이유를 남긴다 — 잘못된 파일이 관측 노드를 재시작 반복에 빠뜨리지 않는다. `compute_ir_calibration` 은 `min_span` 을 0.1 로 반올림해 찍힌 값과 해시가 같다. CLI 에 `--min-white/--min-contrast/--edge-error`, `check` 는 `--black/--white` 한쪽만이면 거절하고 둘 다 있으면 `--session` 이 필요 없다. 시스템 계약 `rosy-camera` 프로그램 목록에 `ir_overlay.py` 를 넣어 선언한 읽기 경로가 실제로 검사된다.
- 증거: 새 `test/test_ir_overlay.py`(없음·정상·잘못된 7종·도구 출력이 곧 유효 덮어쓰기·launch 문자열) + `test_ir_calibration.py` 추가 3개 → 23 passed. `test/test_native_systemd_contract.py` 는 선언을 비우면 빨강, 되돌리면 초록 (2026-09-30 Windows).
- gate 변화: SOURCE. 새 모듈이 설치 이미지에 들어가야 실물에서 쓰인다(릴리스 필요).
- 결정: D-344 §12 보강.

## 2026-09-30 · 40757d69 · fix(camera): 교정 검사기를 import 못 해도 덮어쓰기만 건너뛴다(재검토 R4)

- 변경: `control/ir_overlay.py` 가 `lane.py` 지연 import 의 ImportError 를 잡아 "skipped: cannot check the calibration" 을 돌려준다 — launch 가 멈추지 않는다.
- 증거: `test_ir_overlay.py` 에 import 실패 시험 추가, `test_ir_overlay.py test_ir_calibration.py` 24 passed (2026-09-30 Windows).
- gate 변화: SOURCE.
- 결정: D-344 §12 보강.

## 2026-09-30 · uncommitted · fix(control): keep v2 — 경계 추적과 벽 밑 테이프(D-364 addendum)
- 변경: `perception/lane_keep.py` — (1) 직전 프레임 경계를 기억해(오도메트리 없음) 이어지는 경계(6 cm·20° 안)는 반대쪽으로 8 cm 넘게 넘어가기 전까지 좌·우를 이어받고, 한쪽만 보이면 이어지는 경계를 먼저 고른다(fc2a81dc). 목표 이동 제한은 시도 후 뺐다. (2) 벽 줄기가 밝기 계단(3×3 평균, 3 행 사이 V 16)에서도 끝나 벽 밑 테이프가 남고, 벽 판정 밝기를 바닥 10 백분위 기준으로도 묶어 화면을 채운 벽도 찾는다(2d947c18). `test_lane_keep.py` 18 → 23.
- 증거: 녹화 재생 벤치(공칭 지면, keep 기본) on_line/on_paint/none/jump — pilot 0.083/0.015/0.332/0.016 → 0.019/0.014/0.319/0.007, teleop 0.043/0.070/0.080/0.047 → 0.040/0.066/0.078/0.024. real-profile sim 폐루프: edge_left 출발 1.531 m → 3.496 m(V1A, 다만 SW 진입로 뒤 회전교차로 남쪽을 가로질러 off-lane 2, 동쪽 고리 안쪽으로 흐름), B1 0.509 → 1.326 m(off-lane 1), C1 0.509 m LOST → 2.001 m 이지만 x 0.20 분기에서 ±1 진동 후 둘레 벽에 붙음(off-lane 1). `pytest src/runtime/sensing/test -k "lane or ground or observer or keep"` 364 passed, 18 skipped (2d947c18, 2026-09-30 Windows). 영상·궤적 `X:\DevTemp\rosy-pilot-evidence\2026-09-30-sim-keep-v2\`. DEVICE: NOT RUN.
- gate 변화: SOURCE 진행(실물 녹화 벤치 전 지표 개선). ROS-SIM 한 바퀴 미달 유지 — 분기에서 fail-closed 가 깨졌다(C1), 모서리 자르기·원호 미해결.
- 결정: D-364 addendum(새 번호 없음). 모서리 회전은 실물에서 계속 끈다.
- 교훈: 같은 저장 프레임의 4 fps 오프라인 재생과 8 fps 라이브가 모서리 잠금에서 다른 답을 냈다(V1C). 폐루프 로그에 전략(`strategy`)이 없으면 라이브를 재현할 수 없다.

## 2026-09-30 · uncommitted · fix(control): keep 2차 — 모서리 모드 분기 fail-closed, 라이브 재생, 끊김 뒤 초기화(D-364 addendum 2)
- 변경: `perception/lane_keep.py` — 모서리 회전이 켜진 경우만: 양쪽 차로선이 보이면 모서리를 찾지 않음, 열린 쪽 경계가 모서리 선 너머로 이어지면 잠그지 않음, 분기 보류(`junction_transverse`·`junction_fork`·`flipping`, 뒤집힘은 양쪽이 보일 때까지 유지), 모서리 명령 |error| ≤ 0.6(b92ea954, fd4fad93). 공통: 보류·`washed`·`no_ground` 에서 추적 경계·조향 기록을 버리고, `line_observer_node` 가 첫 keep 프레임·스탬프 간격 0.5 s 초과·역행·카메라 제어 게이트 뒤 `reset()`(6bda7d0f). 노드가 `line/keep_debug`(판단 묶음, 관측 전용)를 내고 `keep_run.py` 가 `keep.jsonl`·`--all-frames` 를 남긴다. 시험 23 → 32.
- 증거: V1C 원인 — 8 fps 라이브 프레임을 1차 코드로 재생하면 라이브와 같은 프레임에서 `both` 위에 `corner_left` 잠금이 재현됨. 폐루프 off-lane: V1A 2 → R3A 0, V1B 1 → R3B 0, V1C 1 → R3C 0(대신 거리 3.50/1.33/2.00 → 0.70/0.29/0.67 m, 분기·굽이 앞 HOLD→LOST, R3A 는 모서리 뒤 벽 `obstacle_ahead`). 벤치(keep 기본) pilot 0.019/0.014/0.319/0.007, teleop 0.040/0.066/0.078/0.024 — 1차 HEAD 와 같음. 규칙을 실물 기본에도 넣으면 pilot none 0.537, teleop 0.288 이라 넣지 않음. `pytest src/runtime/sensing/test -k "lane or keep"` 302 passed, 17 skipped (2026-09-30 Windows). DEVICE: NOT RUN.
- gate 변화: ROS-SIM — 모서리 모드가 분기에서 fail-closed(off-lane 0). 한 바퀴 미달 유지, 셰브런 거짓 보류(R3B).
- 결정: D-364 addendum 2(새 번호 없음). 실물 모서리 회전은 계속 끔.
- 교훈: 폐루프 원인은 라이브와 같은 프레임 순서로 재생해야 보인다 — 4 fps 표본은 모서리 잠금이 걸린 몇 프레임을 빼먹어 반대 답을 냈다. 순간이동 벤치에서는 노드 상태가 이전 위치를 기억한다.

## 2026-09-30 · uncommitted · feat(recording): 녹화기가 LiDAR `scan` 도 기록한다(D-379)

- 변경: `control/recording.py` `RECORD_TOPICS` 에 `scan` 을 더했다. D-379 자동 라벨(`tools/perception/dataset/autolabel.py`)이 LiDAR 반사점을 카메라 영상에 투영해 벽을 라벨하는데, LiDAR 는 벽은 보고 바닥 테이프는 못 보므로 벽/차선 구분의 기준이 된다. `session.json` 의 `topics` 와 `bag_command` 에 그대로 반영된다. 이 기록기는 아직 장치에 배포되지 않았다.
- 증거: `test/test_recording.py` 에 `test_record_topics_include_the_lidar_for_wall_labels` 추가, `test_recording.py` 25 passed (2026-09-30 Windows). `feat/d373-learning-loop-lap2` 가 같은 줄을 `record_topics()` 로 바꿨으므로 병합 때 `scan` 을 그 함수에 옮겨야 한다.
- gate 변화: SOURCE. 장치 반영 없음.
- 결정: D-379 부록(2026-09-30).

## 2026-10-01 · uncommitted · refactor(control): keep 앞단을 lane_keep_lines.py 로 분리(파일 예산)
- 변경: `perception/lane_keep.py`(698 행, 예산 600)에서 바닥 흰색 마스크·조감도 선 맞춤(`floor_white_mask`·`extract_lines` 와 그 상수)을 `lane_keep_lines.py` 로 옮겼다. `LaneKeeper` 는 상태(쪽 추적·짝짓기·모서리·HOLD)만 남는다(541 행). 옛 이름은 lane_keep 에서 다시 내보내 호출·시험은 그대로다. control 크기 판정 36861 로 재판정.
- 증거: `pytest src/runtime/sensing/test -k "lane or keep or observer"` 336 passed; 실물 세션 재생 keep 수치가 분리 전과 같다(on_line 0.149 / on_paint 0.052 / none 0.095 / jump 0.007).
- gate 변화: 없음(동작 불변).

## 2026-10-01 · uncommitted · feat(sensing): D-373 두 번째 바퀴 — 캡처·스냅샷·상태·압축 카메라·launch 스위치·wall·scan
- 변경: 이 브랜치 커밋 기준, main 병합 5e76dbe7·a4454366 뒤 상태.
  - 압축 카메라: `camera_detect_node`가 `publish_compressed`일 때 같은 프레임을 JPEG으로 `camera/front/compressed`에 낸다(5681cca7). 로봇 밖으로 나가지 않는다(D-136).
  - 상태 토픽: `learned_lane_node`가 `perception/learned/status`(latched, 1 Hz)에 모델·`last_error`·프레임 수·`skip_ratio`·`latency_ms_p50`을 낸다(5681cca7, 73e8b1b0). 2cedf136: 추론 빈도 상한 `max_rate_hz`(기본 3.0)·`threads`(기본 2), 상한으로 건너뛴 프레임은 `frames_rate_limited`로 따로 세고 `skip_ratio`는 과부하만.
  - 캡처 트리거: `capture_trigger.py`(ROS 없음)·`capture_trigger_node` — |error_delta| ≥ 0.35 또는 한쪽만 차선을 보는 상태가 3프레임 연속이면, 또는 `capture/request`면 스냅샷을 요청한다. 자동 쿨다운 30 s, 운영자 5 s(53a4f94a, dcc479e3).
  - 스냅샷 녹화: `recording.py` snapshot 모드와 `record_session --snapshot` — 압축 카메라·부수 토픽 60 s를 메모리 링버퍼(15,360,000 B)에 두고 호출마다 세션 폴더와 `session.json`(사유·두 판단값)을 남긴다(53a4f94a).
  - launch 스위치: `camera_preview.launch.py`의 `learned_shadow`·`capture`(기본 꺼짐, `ROSY_LEARNED_SHADOW`·`ROSY_CAPTURE`에서 `true`/`false`만)와 `learned_max_rate_hz`(`ROSY_LEARNED_MAX_HZ`)(1df022b6, 20d80b3c, 2cedf136). 병합에서 main의 IR 교정 overlay·`LogInfo`와 합쳤다.
  - wall role: `wall` 화소는 차선 목표에서 빠지고 섀도 결과에 `wall_fraction`(가까운 띠 비율)으로 나간다(28b905fa).
  - scan 부수 데이터: `SIDE_TOPICS`에 `scan`(693d5d33). 병합에서 main의 `RECORD_TOPICS`(scan 추가)와 한 정의로 합쳤다: `RECORD_TOPICS = record_topics()`.
  - 학습 런타임 prefix: `learned/runner.py`가 `onnxruntime` import 직전에 `/opt/rosy/learned-perception/site-packages`(`ROSY_LEARNED_SITE`)를 `sys.path` 끝에 붙인다(d2d6ac1f).
- 증거: `src/runtime/sensing/test` 호스트 pytest(Windows), WSL Jazzy `test_camera_preview_launch.py` 25 passed(2026-10-01). 장치 증거는 없다.
- gate 변화: SOURCE. ROS-SIM·DEVICE HOLD 유지 — 섀도·스냅샷·수거의 장치 실행과 상한 뒤 CPU는 미측정.
- 결정: D-373 결정 2·3·4·9, 결정 1 개정(d2d6ac1f).
- 교훈: 병합이 dict 리터럴에 같은 키 둘을 남기면 뒤의 것이 앞을 조용히 덮는다(`test_native_systemd_contract` `DECLARED_READS`). 충돌 없는 자동 병합도 자료 구조 키를 다시 본다.

## 2026-10-01 · 79b7681a · feat(sensing): 카메라 외부 파라미터 단계와 바퀴 오도메트리 맞춤 (D-47 부록)
- 변경: 시동 보정에 정지 카메라 단계(`calibration/cmd` `camera_extrinsic`, `calibration_camera.py`)를 넣었다 — 움직이지 않고 LiDAR 벽 접지선·0.155 m 벽 윗선을 영상 밝기 경계에 맞춰 피치·롤(관측될 때만 높이)을 맞추고 `<result>.camera_candidate.json` 과 저장소 후보 레코드를 쓴다. 적용하지 않는다. ROS 없는 맞춤은 `sensing/perception/camera_extrinsic.py`, 바퀴 반지름·간격은 `sensing/odometry_fit.py`(구간 첫 스캔 기준 점-선 ICP, 오도메트리로 시드하지 않음). `line_observer_node` 의 NOMINAL 프로파일은 승인된 `camera_profile` 레코드가 있으면 그것을 쓰고 출처를 로그에 남긴다(`calibrated_values.py`). package.xml 에 core_common 의존 추가.
- 증거: `test_camera_extrinsic.py`(합성 벽 장면: 피치·롤 복원, 한 시점으로는 높이가 안 갈린다는 것, 정지·이동 중단·시간 초과, 후보만 저장) · `test_odometry_fit.py`(ICP, 360° 피벗 풀림, 거울 오도메트리 무관, 장착 yaw 무관 직진 길이, 바퀴 LS) · `test_calibrated_values.py` 통과(2026-10-01 Windows). 실물 오프라인: D-379 트랙 세션에서 yaw 180/181.9 → 피치 11.2°, 롤 −1.5°, 높이 0.0575 m, 190 은 점수 1/3.
- gate 변화: SOURCE. 장치 반영 없음.
- 결정: D-47 부록 2026-10-01.

## 2026-10-01 · 00cdb647 · fix(sensing): calibration_store_root 선언 (M4)
- 변경: 시동 보정 노드가 카메라 단계가 읽는 `calibration_store_root` 를 선언한다(미선언이면 rclpy 가 단계 끝에서 예외).
- 증거: test_camera_extrinsic.py 14 passed — 믹스인이 읽는 모든 파라미터가 노드 소스에 선언돼 있는지 AST 로 확인 (2026-10-01 Windows).
- gate 변화: 없음.

## 2026-10-01 · fff5825f · feat(perception): D-384 도로 상태 추정기와 섀도 노드
- 변경: (커밋 59fbd3bf부터 fff5825f까지) ROS-free `sensing/perception/road_state.py`(EKF [d, φ, κ, w], 게이트 벽·NIS·점프·쌍 폭, ≤3 가설과 새 획득 때만의 오른쪽 동점 규칙, 저하 사다리와 CORE lost_after_s 시계, 재획득) + `road_state_model.py`(측정·파라미터·어댑터, 124745Z에서 맞춘 R). 섀도 `road_state_node.py`가 `perception/road_state`(RELIABLE depth 1 TRANSIENT_LOCAL)만 낸다 — 명령 없음. R1은 line_observer keep 모드가 필요하다. 재생 도구는 `tools/perception/road_replay.py`
- 증거: `test/test_road_state.py` 87 passed, `tools/perception/test/test_road_replay.py` 31 passed (2026-10-01 Windows). R0 재생 124745Z(보정 외부 파라미터): NIS 평균 regime별 통과, coast survival 1.0, on_paint·직선 |err|·NIS 꼬리는 아직 불합격
- gate 변화: SOURCE/LOCAL GO. ROS-SIM·DEVICE HOLD(노드 WSL 빌드·스모크 없음). R2는 validated_on_curves 전 금지
- 결정: D-384 Proposed (rev 3)
- 교훈: 멈춘 로봇의 같은 화면을 매 프레임 새 증거로 넣으면 비평행 쌍이 곡률로 흡수돼 φ가 뒤집힌다 — 움직인 화면만 새 증거다

## 2026-10-01 · edca9b2e · feat(control): 기하 기본값을 URDF NOMINAL로 (D-397)
- 변경: `lidar.py` `MOUNT_YAW_DEG` 10 → 0(NOSE_YAW π), `robot.yaml`/`auto_calib.yaml` `lidar_yaw_offset`·`scan_yaw_offset` 3.316 → π. `body.ROTATION_RADIUS` 0.083이 `.083` 리터럴을, `URDF_RADIUS`가 `.076` 리터럴을 대신한다(값 그대로). road_state `ir_x_m` 0 → 0.0295, `ir_half_span_m` 0.012 → 0.020. line_observer `camera_*_override`(NaN = 없음) 운영자 층.
- 증거: sensing 전체 스위트, `test_urdf_nominal.py` 소비자 드리프트, `test_lane_keep.py`(stray 기준 30 → 25°, 짝 < 5°).
- gate 변화: SOURCE/LOCAL. DEVICE HOLD — 전방 섹터 10° 회전, 시작 캘리브레이션 인증서 무효(재실행), 기기 calib 스냅샷의 190° 확인 필요.
- 결정: D-397 Proposed.

## 2026-10-01 · uncommitted · feat(map): map_v2_fleet 바닥 기준 사각형 2개를 맵 데이터와 sim 월드에 기록 (D-395 개정 1)
- 변경: `map/map_v2_fleet/lane_rules.yaml`에 `reference_squares`(A·B, 중심·크기·색·출처·불확실성), `scripts/build_world.py`가 두 월드(`map_v2_fleet`, `map_v2_fleet_real`)에 평평한 시각 전용 패치(충돌 없음, 페인트 위 z 0.002/0.0025)를 생성, README 한계에 AMCL 180° 모호성 해소 단서 기록. 좌표는 영상 유래 ±3 cm, 테이프 실측 대기. `lane_graph.py`는 새 키를 무시한다(`lane_graph.yaml` 불변).
- 증거: `test_map_v2_fleet_reference_squares.py`(신규; 필드, 180° 회전 최소 거리 ≥ 0.3 m = 0.40 m, 월드 일치·충돌 없음), `test_map_v2_fleet_scene.py`(생성기 출력 = 체크인 월드), dock_marker·lane_graph·track_world·gz_map_export 통과.
- gate 변화: SOURCE/LOCAL. ROS-SIM 미실행(Gazebo에서 렌더 확인 안 함), DEVICE 해당 없음.
- 결정: D-395 Proposed(개정 1).

## 2026-10-01 · uncommitted · feat(map): 기준 사각형에 방향 축 `heading_axis_deg`
- 변경: `map_v2_fleet/lane_rules.yaml`의 `reference_squares`에 `heading_axis_deg`(A 90, B 0, 영상 유래)를 더했다. 사용자 결정: 사각형 위 로봇은 길을 따라 놓이고 앞뒤는 정하지 않는다. 시험이 축 값과, 축 방향으로 중심에서 0.3 m 넘게 벗어나 앞뒤가 LiDAR로 갈리는지를 확인한다.
- 증거: test_map_v2_fleet_reference_squares.py.
- gate 변화: 없음(SOURCE, 이 키를 읽는 코드는 아직 없다).

## 2026-10-01 · uncommitted · refactor(localization): 전역 탐색을 후보 목록·발자국 마스크·시드 정밀화로 나눔 (D-395 1단계)
- 변경: `sensing/localization.py`에 `valid_beams`, `apart`(0.18 m / 0.3 rad), `GLOBAL_OFFSETS`, `MapAgreement.clear_poses/refine/global_results`를 꺼냈다. `global_match`는 같은 계산을 거쳐 같은 답을 낸다. 대칭 맵에서 유일하지 않다고 버리던 후보를 D-395 후보 목록이 쓰게 하려는 준비다.
- 증거: `test_localization_search.py`(신규 6), `test_localization.py`의 기록된 Gazebo 모서리 시험(유일 해·2 cm) 그대로 통과, `test_localization_gate.py`.
- gate 변화: 없음(SOURCE). 노드 동작 불변.
- 결정: D-395 Proposed(설계 승인, 1단계 호스트 전용).

## 2026-10-01 · uncommitted · feat(localization): 거울상까지 모든 자세 후보를 내는 순수 모듈 (D-395 1단계)
- 변경: `sensing/loc_candidates.py` — `global_candidates`(유일하지 않아도 거절하지 않고 서로 다른 가설을 최대 4개, 적합도 ≥ 0.9, 최고점에서 0.05 안), `slot_candidates`(기준 사각형마다 축·축+180°를 10 cm / 20° 안에서 정밀화, 적합도로 방향을 고름, 개정 2), `merge`, 회전 장착(스캔 0° = 후방)을 거치는 base↔sensor 변환. 시험 도우미 `test/loc_world.py`는 체크인된 `map_v2_fleet.pgm`을 2 cm로 읽고 LiDAR를 광선 투사한다.
- 증거: `test_loc_candidates.py` 9 passed — 대칭 트랙에서 참 자세와 거울상이 함께 나옴, 사각형 A(−90°)·B(0°) 위 로봇은 슬롯 후보 하나와 맞는 방향, 슬롯 밖은 슬롯 후보 없음, 기록된 Gazebo 스캔(독립 픽스처)에서 참 자세 2 cm.
- gate 변화: 없음(SOURCE/LOCAL). 노드 배선 없음.
- 결정: D-395 Proposed(설계 승인, 1단계 호스트 전용).

## 2026-10-01 · uncommitted · fix(localization): 슬롯 탐색 비용 상한과 리뷰 지적 (D-395 1단계 작업 2)
- 변경: `slot_candidates`가 지도 전체 `clear_poses`를 만들지 않고 슬롯 상자 칸만 발자국 검사한다. 두 탐색이 `clear=`로 한 번 만든 마스크를 함께 쓸 수 있다. 전역 탐색 비용(지도 칸 × 72 방향)은 2단계에서 Pi로 재고 풀링 격자나 시간 예산으로 묶는다는 요구를 모듈 설명에 적었다. 기준을 넘는 형제 정밀화를 버리지 않고, 잘못된 `reference_squares`는 사각형 id를 단 ValueError, `distinct`는 창 밖에서 멈춘다. `footprint_clear` 창이 부풀린 반경(+res/√2)을 덮지 못하던 결함도 고쳤다.
- 증거: test_loc_candidates.py, test_localization_search.py, test_localization.py, test_localization_gate.py 35 passed, 1 skipped.
- gate 변화: 없음(SOURCE, 호스트 전용).

## 2026-10-01 · uncommitted · feat(localization): 지도에 없는 LiDAR 물체를 base_link 물체로 묶음 (D-395 4.2절)
- 변경: `sensing/loc_objects.py` `unmapped_objects` — 지도 벽(`near`)으로 설명되지 않는 반환을 6 cm 간격으로 묶어 중심을 base_link (앞, 왼쪽)으로 낸다. 대칭 맵에서는 거울 가설도 같은 반환을 설명하므로 목록은 가설과 무관하다. 스캔은 고리라서 ±π 이음매(뒤집힌 마운트에서는 로봇 정면)에 걸친 물체를 하나로 합친다(계획에 없던 보강).
- 증거: `test_loc_objects.py` 4 passed(빈 트랙 0개, 다른 로봇 1개·8 cm 안, 정면 이음매 1개, 거울 가설에서 같은 목록).
- gate 변화: 없음(SOURCE/LOCAL).

## 2026-10-01 · uncommitted · feat(localization): 주입 뒤 3 s 스캔/지도 검증 (D-395 7항)
- 변경: `sensing/loc_verify.py` `InjectionCheck` — 0.5 s 안정 뒤 새 스캔마다 적합도 ≥ 0.85가 3 s 유지되면 통과, 한 번이라도 낮거나 스캔이 0.5 s 끊기면 즉시 실패(`fit_low`/`stale_scan`). 출처와 무관하게 같은 관문이다. 한계: 대칭 맵에서는 거울상도 같은 적합도라 이 검증이 거울 주입을 못 거른다. 그래서 LOCALIZED에는 비대칭 단서가 따로 필요하다(loc_state).
- 증거: `test_loc_verify.py` 5 passed.
- gate 변화: 없음(SOURCE/LOCAL).

## 2026-10-01 · uncommitted · feat(localization): UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT 상태 기계 (D-395 5절, 개정 3)
- 변경: `sensing/loc_state.py` `LocalizationStateMachine` — 전원 투입은 항상 UNKNOWN, 후보가 오면 새 request_id로 CANDIDATES, 결정은 같은 id·받은 뒤 `ttl_s`(5 s) 안·후보 인덱스 또는 직접 좌표 하나만 받고, 사람 결정이 아니면 비대칭 단서(`square`/`paint`/`peers`/`slot`) 하나 이상이 있어야 한다(`no_asymmetric_cue`). `InjectionCheck` 통과 시 LOCALIZED(`cancel_nav_goal`), 검증 실패(`inject_rejected`)·픽업·적합도 1 s 지속 하락(`fit_drop`)·Fleet 감시는 SUSPECT. 자율 주행은 LOCALIZED만. 계획의 절대 시각 `expires_at`은 개정 3에 따라 수신 기준 `ttl_s`로 바꿨다.
- 증거: `test_loc_state.py` 19 passed.
- gate 변화: 없음(SOURCE/LOCAL).

## 2026-10-01 · uncommitted · feat(perception): 가설 자세별 페인트 점수 (D-395 7절, D-375)
- 변경: `sensing/perception/paint_hypothesis.py` `paint_score` — 카메라의 바닥 페인트 점(base_link)을 가설 자세로 지도에 놓고 페인트 입자 필터와 같은 거리 점수(exp(−평균 거리/5 mm), 3 cm 상한)를 낸다. 점이 10개 미만이면 None(증거 없음).
- 증거: `test_paint_hypothesis.py` 7 passed — map_v2_fleet 여섯 자세에서 참 > 0.9, 거울 < 0.1.
- gate 변화: 없음(SOURCE/LOCAL). 실제 카메라 차선 마스크 연결은 2단계.

## 2026-10-01 · uncommitted · feat(perception): 기준 사각형 HSV 검출기, 출력 계약 고정 (D-395 개정 1 6항)
- 변경: `sensing/perception/reference_square.py` — 출력 계약 `SquareObservation(bearing_rad, range_m, confidence)`(base_link, 왼쪽 +), `SquareDetector` 프로토콜, 규칙 백엔드 `HsvSquareDetector`(파란 중심 연결 요소 + 둘레 빨간 고리 비율, 거리는 지면 평면에서 중심 행). 지면 평면이 없으면 결과 없음, 신뢰 거리 밖이면 방위만. 학습 클래스 `reference_square`가 같은 `detect(bgr, ground)` 뒤로 바꿔 들어올 수 있다. sensing·perception AGENTS 표에 D-395 모듈 행 추가.
- 증거: `test_reference_square.py` 11 passed — 합성 영상(카펫·벽·11.8° 피치), 0.3–0.6 m에서 방위 3°·거리 3 cm, 카펫·흰 페인트·고리 없는 파랑·중심 없는 빨강은 0개. 합성 영상은 검출기와 같은 믿음이므로 실제 프레임 1장도 돌렸다: 8kcn 20260930T133221Z 프레임 78(320×240, 피치 11.2°, 높이 0.0627 m 가정)에서 1개, 방위 왼쪽 10.2°, 거리 0.43 m, 신뢰 0.91. 한 장이라 가시 거리·조명 범위는 여전히 미검증(2단계 P2-8).
- gate 변화: 없음(SOURCE/LOCAL).
