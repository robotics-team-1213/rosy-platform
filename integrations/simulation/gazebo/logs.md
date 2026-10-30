# gz_sim logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [군집 대형 슬라이스 결과](../../docs/plans/2026-09-08-swarm-formation-slice-results.md)와 `git log -- src/gz_sim`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the gz_sim harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python -m pytest src/gz_sim/test -q` 1 skipped (2026-09-15 Windows, ROS 2 `launch` 패키지 없어 `pytest.importorskip`로 전체 skip — 증거 아님)
- gate 변화: 없음. SOURCE/LOCAL/ROS-SIM을 HOLD로, ARTIFACT/DEVICE/FIELD를 N/A(aarch64에서 `return()`, Pi 이미지 미포함)로 처음 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-17 · uncommitted · feat(sim): host-contract for world_to_map
- 변경: CMake에 world_to_map.py install. harness functional에 test_world_to_map.py. SOURCE/LOCAL을 launch skip에서 정답 맵 시험으로 옮김
- 증거: `python -m pytest src/gz_sim/test/test_gz_package_contract.py src/gz_sim/test/test_world_to_map.py -q` 8 passed (2026-09-17 Windows)
- gate 변화: SOURCE HOLD→GO, LOCAL HOLD→GO. ROS-SIM HOLD 유지
- 결정: D-79 — launch skip은 증거가 아니다
- 교훈: 없음

## 2026-09-17 · uncommitted · feat(sim): 어려운 월드·정답 맵 생성기·맵을 만들며 주행하는 모드
- 변경: `worlds/rosy_maze.world`(뱀형 통로 + 0.55 m 문 + 막다른 주머니), `worlds/rosy_swarm_bench.world`(6x6 열린 방 + 비대칭 기둥), `scripts/world_to_map.py`(월드 기하 → nav2 점유 격자), `gz_multi` 에 `mode:=slam_nav`·`spawn_x/spawn_y`·`inflation_radius` 인자, 카메라 `always_on` 0 / 10 Hz, `test/test_world_to_map.py` 6건
- 증거: `python -m pytest src/gz_sim/test -q` 11 passed, 1 skipped (Windows). 실환경: `mode:=slam_nav` 로 공장을 주행하며 재매핑해 8/8 목표 ARRIVED, free 2808 → 3737 셀. 카메라 수정 전후 RTF 0.07 → 1.0 (단일 로봇, 같은 기계)
- gate 변화: 없음(커밋 뒤 재실행으로 판정)
- 결정: 없음
- 교훈: 좁은 통로 월드는 맵핑이 순환에 걸린다 — 맵이 없으면 nav2 를 못 쓰고, nav2 없이 몰면 벽에 끼고, 끼면 바퀴가 헛돌아 odom 이 폭주하고, 그 odom 으로 뜬 맵은 못 쓴다. `slam_nav`(맵 작성 + 주행)와 정답 맵 생성기가 각각 그 고리를 끊는다. 그리고 구독자 없는 1280x720 카메라 하나가 소프트웨어 렌더러에서 RTF 를 14배 깎았다 — D-34 가 말하는 "구독자가 없으면 보내지 않는다" 는 성능 문제이기도 하다

## 2026-09-18 · uncommitted · fix(sim): 월드 프로필이 간격을 주도록 하고 공장 팽창을 실측으로 올린다
- 변경: `gz_multi` 의 `spawn_spacing` 기본값 "1.5" → "" (비면 프로필 값), `worlds.yaml` 의 공장 `inflation_radius` 0.15 → 0.25, 데모룸 spawn (-0.5, 0) 간격 1.0
- 증거: 프로필에 `spawn_spacing: 1.0` 을 적어도 런치 기본값 1.5 가 항상 이겨, 2x1 m 데모룸에서 둘째 로봇이 x=1.0 — 벽 안쪽 — 에 spawn 됐다(정답 좌표 0.998). 공장 팽창 0.15 에서는 선반 사이를 지날 때 라이다 최소 거리가 0.08 m 까지 붙었고(풋프린트 반폭 6 cm), 0.25 에서는 같은 목표에 같은 정확도(오차 0.13 m)로 도착하면서 0.20 m 로 벌어졌다
- gate 변화: 없음
- 결정: 없음
- 교훈: 비어 있지 않은 런치 기본값은 프로필을 무력화한다. "인자가 없으면 프로필" 을 하려면 기본값이 비어 있어야 한다

## 2026-09-18 · uncommitted · feat(sim): lock ros_gz_bridge and seed spawn initialpose (D-114, D-115)

- 변경: `gz_multi` 는 domain_bridge/ROS_DOMAIN_ID 없음. `spawn_xy` 와 `seed_initialpose` 가 nav 모드에서 map 시드를 심는다.
- 증거: `python -m pytest src/gz_sim/test -q`
- gate 변화: 없음. ROS-SIM HOLD. pytest ≠ GO

## 2026-09-18 · uncommitted · feat(sim): pin Cyclone and keep images off gz_multi (D-117, D-118, D-120)

- 변경: gz_multi 환경에 rmw_cyclonedds_cpp 와 ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST. launch_sim image_bridge 는 기본 꺼짐.
- 증거: `python -m pytest src/gz_sim/test/test_gz_package_contract.py test/test_dds_rmw_contracts.py -q`
- gate 변화: 없음. ROS-SIM HOLD

## 2026-09-20 · uncommitted · fix(sim): stabilize exact-map Nav2 startup and corner geometry

- 변경: defer Nav2/SLAM startup by 15 wall-clock seconds, use non-composed Nav2 for constrained hosts, seed initial pose only in static-nav mode, apply reducing-only narrow-space controller settings, and replace the simulation rectangle with its padded circumscribed radius in both costmaps.
- 증거: exact map loaded with `map_id=occupancy:2646647774c5`, initial pose became fresh, lifecycle nodes became active, and the relevant simulation tests passed `11 passed in 31.69 s`. A repeat goal timed out under shared WSL load 60--90, so it is not a route pass.
- gate 변화: none. ROS-SIM full-route remains HOLD; the run proves startup/localization and exposes a prior yaw-dependent `Start occupied` corner case.
- 교훈: an orientationless global planner must not admit a pose that only the current rectangular yaw can occupy when the controller will need to rotate there.

## 2026-09-21 · uncommitted · feat(sim): finish exact-map live SLAM traversal

- 변경: 설치된 v2 world를 고르는 launch 경로, 52-point 관측 route, live scan 기반 적응 속도, 후방 여유와 본체 직경으로 계산하는 유연한 recovery, 전방위 회전 여유 fail-close, CORE `nav_cmd_vel` 입력, 2 cm live SLAM 저장/감사를 추가했다. 정확한 model-pose odom을 쓰는 sim에서는 scan matching/loop closing을 꺼 반복 벽 오정합을 제거한다.
- 증거: `final_22` 52/52, `13.754679 m`, 접근 가능한 unknown/occupied/outside `0/0/0%`, collision overlap false, 최소 본체 여유 `0.021789 m`, Fleet online. 좁은 구간 median `0.067975 m/s`, 열린 구간 median `0.122453 m/s`. CORE만 최종 `cmd_vel`을 발행하고 종료 시 `0/0`.
- gate 변화: ROS-SIM HOLD→GO(단일 로봇 exact-map live SLAM/CORE/Fleet 범위). 다중 로봇 동시 map과 실기기는 별도 범위다.
- 결정: 정답 world의 전체 픽셀을 요구하지 않고, 실제 본체가 도달 가능한 연결 구성공간의 완전성을 판정한다. 밀폐 포켓은 숨기지 않고 별도 비율로 기록한다.
- 교훈: Gazebo 정답 pose 위에 scan matcher를 중복 적용하면 반복 벽에서 유령 벽이 생길 수 있다. simulation 전용 설정과 실기기 설정을 분리해야 한다.

## 2026-09-21 · uncommitted · refactor(gz_sim): swarm_bench consumes fleet.bench only (D-148)
- 변경: scripts/swarm_bench.py 의 fleet 내부 직접 import 4건을 fleet.bench 경유로 교체. test/test_bench_boundary.py 2건 추가 — scripts/ 전체에서 fleet.swarm/formation 직접 import 금지 + swarm_bench 의 파사드 사용 검사.
- 증거: 결합도 평가(2026-09-19) §6 C등급 sim→site 내용 결합 해소. 텍스트 구조 검사라 ROS 오버레이 없이 검증된다.
- gate 변화: 없음

## 2026-09-21 · uncommitted · feat(sim): add semantic road scene and host closed loop (D-151)

- 변경: 측정된 16-wall 기본 맵은 그대로 두고 차선·정지선·횡단보도·신호등이 있는 파생 semantic YAML, Gazebo world, map preview를 추가했다. scene revision과 map identity를 검증한다.
- 증거: host synthetic camera simulation은 장면 정답을 detector에 넣지 않고 실제 perception-policy-command 경로로 red stop, green proceed, stale HOLD를 재현했다. 결과 JSON, montage, timeline, 관제 Chromium 캡처를 `docs/validation/semantic-road-2026-09-21/`에 보존한다.
- gate 변화: 기존 exact-map ROS-SIM GO는 유지하되 semantic 카메라 흐름 자체는 host 증거다. 실제 Gazebo camera/ROS graph를 새로 실행한 것으로 간주하지 않는다.
- 결정: D-151. semantic scene은 파생 asset이고 base mapping geometry를 변경하지 않는다.

## 2026-09-21 · uncommitted · fix(sim): canonicalize semantic scene hashes (D-151)

- 변경: text asset identity를 LF canonical bytes로 정의해 Windows CRLF checkout과 Linux checkout이 같은 scene/world/manifest hash를 사용하도록 했다.
- 증거: rebase 후 raw-byte test가 Windows에서 2건 실패하는 것을 재현했고, canonical builder·manifest 적용 후 semantic scene/simulation `26 passed`.
- gate 변화: 없음. 호스트 자산 재현성을 수정했으며 ROS-SIM/DEVICE/FIELD 증거를 승격하지 않는다.
- 결정: D-151 scene revision은 OS 줄바꿈과 무관한 동일 identity를 가져야 한다.

## 2026-09-21 · uncommitted · feat(sim): wire the semantic Gazebo camera to the CORE dashboard (D-152)

- Review hardening: package.xml now declares `ament_index_python`, `launch`, `launch_ros`, and `ros_gz_image`; the simulation CORE profile fixes the authenticated pull floor at 0.4 s.

- 변경: single-sim image bridge를 opt-in할 때 `/camera/image_raw`를 `camera/front`로 remap하고, semantic road world·line/road observers·CORE dashboard를 함께 띄우는 `semantic_road_dashboard.launch.py`를 추가했다. 다중 로봇 기본 image-off 계약은 유지한다.
- 증거: launch/package/bridge 계약과 Chromium dashboard `17 passed`; HOST-SIM screenshot과 6-frame GIF 보존.
- gate 변화: 기존 exact-map ROS-SIM GO는 유지한다. 새 semantic camera launch는 이 Windows 세션에서 실제 Gazebo로 실행하지 않았으므로 해당 프레임 gate는 HOLD다.
- 결정: D-152의 bounded preview 예외와 D-118의 기본 image-off를 함께 유지한다.

## 2026-09-21 · uncommitted · fix(sim): validate the actual Gazebo camera path headlessly (D-152)

- 변경: `description`을 명시적 런타임 의존성으로 선언하고 semantic dashboard의 Gazebo GUI를 선택 인자로 분리했다. 기본은 `gazebo_gui:=false`이며 `true`로 튜닝할 수 있다.
- 증거: clean dependency closure에서 12 packages build PASS. Actual Gazebo 8.11.0 loaded the installed `map_260905_traffic.world`; source/install SHA-256 matched. `/camera/front` produced a 640x360 `GAZEBO` frame and the production detector reported the stop line at confidence 0.814153. CORE held zero velocity with `stop_distance_unavailable` because no physically validated homography was active.
- 한계: this WSL host produced about 0.59-0.80 Hz camera and 0.36 Hz preview throughput. Continuous realtime preview, metric distance, physical Pinky Pro, braking, and FIELD acceptance remain HOLD.
- gate 변화: existing exact-map ROS-SIM GO remains unchanged. The actual Gazebo camera graph moves from untested to PASS, while sustained realtime preview and physical validation remain HOLD.
- 보존: `docs/validation/semantic-road-2026-09-21/gazebo_runtime_result.json` and `gazebo_camera_frame.jpg`.


## 2026-09-22

- 변경: `scripts/stl_to_world.py` 신규 — STL 평면도 선화를 벽 박스 월드로 변환한다. 벽/바닥 표시 구분은 묶음 extent(150 mm 미만 표시) + 뼈대에 붙은 짧은 선분 공간 묶음(입구 X자) + 명시적 영역(문 사다리)이다. `worlds/rosy_road.world` 신규 — 260919 MAP FILE.STL 1:1, 벽 박스 1102 개, 높이 0.30 m.
- 증거: 선분 1081 = 벽 1131 / 표시 492; world_to_map 로 free=7199 단일 덩어리 확인, 렌더 이미지로 도면 대조. 시도하고 버린 판정: 이중선 병합(오정합으로 프레임 붕괴), 둑 면적 시험(갈라놓기 벽을 전부 표시로 버림), 선분 탐침(자기 밴드 오염).
- 한계: 외곽 프레임 누수 152 셀, 관절 핀홀. 배율/두께는 --scale, WALL_HALF_MM 옵션.
- gate 변화: 월드 자체는 ROS-SIM 미실행 — launch 실측 전까지 HOLD 유지.

## 2026-09-24 · uncommitted · docs(sim): D-182 simulation actuation profile

- 변경: `config/simulation_actuation.yaml`이 파티션 `pinky_calmap227`과 도메인 227의 유일한 출처다. 안전 코드는 이 파일을 읽지 않는다.
- 증거: `test/test_policy_sim_literals.py` 통과 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: D-182 Accepted
- 교훈: 없음.

## 2026-09-24 · uncommitted · chore(sim): `navigation` exec_depend 중복 제거

- 변경: `package.xml`의 `<exec_depend>navigation</exec_depend>` 선언 2건 중 D-126 S4 주석 붙은 것은 유지하고, 맨 선언(24행)만 제거했다.
- 증거: 커밋 직전 `python -m pytest test/ -q` 초록 (2026-09-24 Windows).
- gate 변화: 없음.
- 결정: module-coupling-scorecard §6 과제 4.
- 교훈: 없음.


## 2026-09-24 · uncommitted · fix(ci): install python3-opencv for the lane live viewer

- 변경: `.github/workflows/ci.yml` Install colcon & tools 단계의 apt 목록에 `python3-opencv` 추가.
  `src/sim/gz_sim/scripts/lane_live_view.py`(650fad89/b1e69932)가 모듈 최상단에서 cv2를 import하는데
  러너에 OpenCV가 없어 gz_sim 단계가 수집 단계부터 죽었고, 그 뒤의 모든 gate(boot smoke, SaveMap 가드,
  deploy/release 계약)가 실행조차 되지 않은 채 main이 2026-09-24부터 계속 빨강이었다. 패키지 선택은
  io 이미지가 쓰는 `python3-opencv`와 같다.
- 증거: 실패 원문 `gh run view 35991296072 --log-failed` → `ModuleNotFoundError: No module named 'cv2'`
  (lane_live_view.py:44). D-197 머지 run 35977600574도 동일 단계 실패 — 빨강의 시작은 내 변경 이전이다.
  로컬 재현: Windows 러너에서 gz_sim suite는 ROS 의존으로 실행 불가 — CI 실행으로 검증한다(커밋 후 run 확인).
- gate 변화: 없음
- 결정: 없음
- 교훈: 모듈 최상단 cv2 import는 그 스크립트를 import하는 모든 시험의 선행 조건이 된다 — 시험 도구가
  없는 환경에서 수집 단계부터 죽으면, 그 뒤의 게이트들이 "통과"가 아니라 "미실행"으로 가려진다.

## 2026-09-24 · uncommitted · docs(adr): D-205 real lane mission transition order
- 변경: `docs/adr/D-205-real-lane-mission-transition-order.md` 추가(Proposed), `progress.md`의 `adrs`에 D-205. 코드 본문은 바꾸지 않았다.
- 증거: 문서 변경. 25° 세계의 이전 합격(교차로 3×12/12, 순회 3/3, 미션 4/4)은 ROS-SIM이고 장치 증거가 아니다.
- gate 변화: 없음.
- 결정: D-205 Proposed. P4에서 세계 revision을 올린다(프로필 카메라, 흰 무광 벽과 파란 테이프, 카펫, 실측 매트, GroundTruthLabeler·채점기·데이터셋 기록기). P5에서 같은 기준으로 다시 합격받는다.
- 교훈: 없음. 후속: `map_v2_fleet_lane.launch.py`의 line_observer `camera_x_offset_m` 0.034(참값 0.028481)는 코너 튜닝을 다시 잰 뒤 고친다.

## 2026-09-27 · uncommitted · fix(sim-ui): complete Gazebo viewer tab keyboard contract

- 변경: D-306의 Gazebo 전용 라이브 뷰어 탭에 패널 연결, 방향키·Home·End 조작, 선택 탭 포커스 순서와 보이는 포커스 링을 추가했다. 관측 데이터·제어 경로는 변경하지 않았다.
- 증거: 새 Chromium 브라우저 시험을 변경 전 실패, 변경 후 통과로 확인했다. 기존 viewer v2 계약과 합쳐 59 passed (Windows). 1280×800 라이브·지난 결과 캡처는 `X:\\DevTemp\\rosy-uiux-d306\\`에만 저장했고 가로 넘침·페이지 오류가 없었다.
- gate 변화: LOCAL 키보드 조작 근거를 추가했다. Gazebo 카메라·인지의 실제 실행과 DEVICE/FIELD 수용은 이 시험으로 증명하지 않는다.

## 2026-09-30 · faa60733 · D-359 US-002 레인 라이브 뷰 어둡게 고정 표시

- 변경: `scripts/lane_live_view.html`의 `<html>`에 `data-theme="dark" data-theme-pin="dark"`(자체 팔레트, tokens.css 비사용). `surfaces.yaml` `themes: [dark]`.
- 증거: `python -m pytest src/sim/gz_sim/test/test_lane_live_view.py -q` 통과.
- gate 변화: 없음.

## 2026-09-30 · aeb31356 · D-359 US-005 lane_live_view @media 범위 문법

- 변경: `scripts/lane_live_view.html` `max-width: 1000px/640px` → `(width <= 1000px)`·`(width <= 640px)`. 개발 도구라 세 단으로 옮기지 않고 surfaces.yaml `lane-live-view.breakpoints`에 이유와 함께 적었다.
- 증거: `test_lane_live_view.py`·`test_web_budgets.py` 통과.
- gate 변화: 없음.
## 2026-09-30 · uncommitted · feat(sim): map_v2_fleet real-profile world and Pinky camera launch (D-353 5)

- 변경: `launch/map_v2_fleet_real.launch.py` 추가. 320x240, 기울기 8°, hfov 1.0334 rad(fx 281.6), 렌즈 높이 0.067 m(`cam_mount_z` 0.05307), 8 fps로 `map_v2_fleet_real.world`(카펫 텍스처, 0.66 회색 테이프, 흰 0.30 m 벽, 파란 이음새 테이프)를 띄운다. line_observer는 `line_follow.yaml` 장치 기본값에 GAZEBO 선언 지오메트리(0.067 m, 8°, 1.0334 rad, x 0.03317 m)만 덮어쓴다. `launch_sim.launch.xml`에 `camera_hfov`, `cam_mount_z` 인자(기본 1.1519, 0.0495)를 추가했다. 기존 `map_v2_fleet_lane.launch.py`와 25° 월드는 바꾸지 않았다.
- 증거: `docs/validation/map-v2-fleet-real-profile-2026-09-30/result.md`. WSL 헤드리스 20자세 캡처와 실제 teleop 20장 비교에서 하단 회색 66.5 대 65.5, 벽 209 대 214, 테이프 186 대 192, 수평선 row ~80. `python -m pytest src/sim -q` 통과(Windows).
- gate 변화: ROS-SIM 외형 근거 추가. 이 월드에서의 차선 주행 합격과 DEVICE/FIELD 수용은 아직 없다.

## 2026-09-30 · uncommitted · docs(adr): pilot ADR 번호를 main 과 겹치지 않게 다시 매김
- 변경: main 이 D-346~D-353 을 다른 결정으로 먼저 썼다. 이 모듈 기록의 옛 번호는 다음으로 읽는다 — D-346→D-362(운전자 실시간 영상), D-347→D-342(수동 한도 계단), D-348→D-343(방·운전석), D-349→D-344(보조 자율), D-350→D-363(카메라 비율·설치 앱), D-353→D-364(차로 유지 인식·재생 벤치). 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/` 파일 이름·ADR Log 행·코드 주석·시험이 새 번호를 쓴다. D-342~D-344 는 main 의 harness 가 이 pilot 초안용으로 예약해 둔 번호다.
- gate 변화: 없음(번호만).

## 2026-09-30 · uncommitted · docs(adr): 운전자 실시간 영상 ADR 을 D-362 에서 D-368 로
- 변경: 다른 세션이 main 작업 트리에서 D-362(코드 유형별 파일 크기 예산)를 쓰고 있어, 이 모듈 기록의 D-362(운전자 실시간 영상, 옛 D-346)는 D-368 로 읽는다. 위 기록은 덧붙이기 전용이라 고치지 않는다.
- 증거: `docs/adr/D-368-pilot-live-driver-video.md`, ADR Log 행·코드·시험이 새 번호를 쓴다.
- gate 변화: 없음(번호만).

## 2026-10-01 · edca9b2e · feat(sim): 카메라를 URDF 사슬에 맞춘다 (D-397)
- 변경: `map_v2_fleet_real` `cam_mount_z` 0.05307 → 0.0495, 높이 0.067 → 0.06343(NOMINAL 프로필). `map_v2_fleet_lane` line_observer `camera_x_offset_m` 0.034 → 0.028481(25° URDF 사슬, dock observer와 같은 값).
- 증거: `test_map_v2_fleet_launch.py`, `test_map_v2_fleet_real_launch.py`, `test_urdf_nominal.py`.
- gate 변화: ROS-SIM HOLD — 랩을 다시 돌아야 한다.
- 결정: D-397 Proposed.

## 2026-10-01 · uncommitted · feat(omx): record SIM demonstrations and export LeRobot v3
- 변경: D-390 부록·API v1.69·Pilot 기록 패널·SIM 카메라·원본 recorder·오프라인 exporter. ROS 수락 전에 목표를 등록하고, recording I/O는 별도 writer로 분리.
- 증거: adapter/Pilot/network 259 passed, 28 skipped; quick tier 95 passed; Chromium recording retry/outcome/stale/dispose 1 passed; 실제 LeRobot 0.4.4 reader 3 passed. Gazebo 원본 15프레임 및 동일 원본 export 재독출 PASS. docs/validation/omx-demonstration-lerobot-2026-10-01/README.md 참조.
- gate 변화: 물리·ARTIFACT/FIELD 승격 없음. 짧은 SIM 시연/데이터 형식 증거만 추가.
- 결정: D-390 부록; D-18 typed API와 reference 동시 갱신.
- 교훈: LeRobot 0.4.4는 explicit timestamp를 거부; source ns를 int64로 유지. Windows shared recording mount는 프레임 누락을 만들 수 있으므로 Linux volume 사용.

## 2026-10-01 · uncommitted · fix(omx): fence recording closure and isolate storage faults
- 변경: 리뷰의 중요 문제 3개 해소 — recording 오류로 lease watcher 종료 금지, hidden 중 늦은 seat 획득 즉시 반납, 종료 저장 중 interruption을 manifest에 반영.
- 증거: 리뷰 수정 race/runtime/recorder 21 passed; Chromium 2 passed; 최종 adapter/foundation/assets/network 624 passed, 6 skipped. 최종 tree와 같은 해시의 실제 Gazebo 12프레임→LeRobot 재독출 PASS; 같은 실행 lease 만료 incomplete. 독립 리뷰 재검토 완료.
- gate 변화: 기존 gate 유지; DEVICE/FIELD 승격 없음.
- 결정: D-390 부록.
- 교훈: 파일 쓰기 완료 전 들어온 interruption과 logical closure 경계를 구분한다.
## 2026-10-01 · uncommitted · feat(sim): gz_multi nav 모드에 로봇별 loc_assist (D-395 P2-3)
- 변경: 인자 `loc_assist`(기본 true). `mode:=nav`에서 로봇마다 control의 `loc_assist.launch.py`를 namespace·sim 시간·map과 함께 Nav2와 같은 15 s 지연 묶음에 넣는다. seed_initialpose는 그대로이며 근거가 아니다(전원 투입 UNKNOWN). 카메라는 이 런치에 브리지되지 않아 사각형 관측은 없다. 파일 595줄(예산 600).
- 증거: `test_gz_multi_core.py`에 `loc_assist` 설정과 nav 모드 포함·끔 시험 추가. WSL에는 현재 패키지 이름으로 빌드된 작업공간이 없어 이 런치 그래프 시험은 skip(공유 share 없음) — 미검증으로 남긴다.
- gate 변화: 없음. ROS-SIM은 P2-8.

## 2026-10-02 · uncommitted · feat(sim): gz_multi 로봇별 스폰 자세·AMCL 시드 끔·월드 패키지 자원 경로 (D-395 S1)
- 변경: 인자 `spawn_poses`(`x,y,yaw_rad;...` 로봇별, 비면 지금처럼 spawn_x/y/spacing·yaw 0)와 `seed_initialpose`(기본 true; false면 정답 자세를 AMCL에 미리 주지 않는다, D-395 전원 투입 UNKNOWN). 스폰 yaw를 `create -Y`와 시드에 같이 넣는다. `world_profiles.parse_spawn_poses`·`world_share_parent`: package:// 월드(map_v2_fleet)의 `model://control/...` 메시는 colcon 기본(격리) 설치에서 description/.. 로 안 풀려 Gazebo가 월드를 못 읽었다 — 그 패키지 share 부모를 GZ_SIM_RESOURCE_PATH에 더한다. 파일 600줄(예산 600).
- 증거: WSL Jazzy `python3 -m pytest src/sim/gz_sim/test/test_gz_multi_core.py src/sim/gz_sim/test/test_world_profiles.py -q` 20 passed, 1 failed — 실패는 `test_nav_mode_starts_loc_assist_per_robot_unless_turned_off`로 기준(feat/d395-p2-integration 67cb5064) 파일에서도 같은 실패(0 == 2). 새 시험 3건은 `-Y` 제거·시드 조건 제거 변이에서 실패 확인. Windows `test_world_profiles.py` 10 passed. 실제 실행: S1 벤치에서 두 로봇이 지정 자세로 스폰(Gazebo 정답과 일치).
- gate 변화: 없음. ROS-SIM S1 결과는 `docs/plans/2026-10-02-d395-s1-bench-results.md`.
- 결정: 없음
- 교훈: 다른 패키지 자산을 쓰는 카탈로그 월드는 merge-install에서만 돌았다 — 격리 설치에서 한 번은 띄워 본다.

## 2026-10-02 · uncommitted · test(sim): loc_assist 포함 시험이 실제로 경로를 읽게 한다
- 변경: `test_gz_multi_core._loc_assist_includes`가 `launch_description_source.location`(실행 전에는 치환 객체의 repr 문자열)을 읽어 항상 0개를 세던 것을, 치환 목록을 perform해 경로로 비교하도록 고쳤다.
- 증거: WSL Jazzy `test_gz_multi_core.py` 11 passed(이전: 이 시험 1건 실패, 통합 브랜치 기준선에서도 실패). 변이: `if loc_assist:`를 `if False:`로 바꾸면 이 시험 실패.
- gate 변화: 없음
- 결정: 없음
- 교훈: 런치 그래프 시험에서 문자열 비교는 실행 전 값인지 먼저 확인한다 — repr에 대한 `endswith`는 언제나 거짓이다.

## 2026-10-02 · uncommitted · fix(sim): gz_multi Nav2 가 직진하지 않던 D-395 R4
- 변경: `gz_multi._nav_config` 두 곳. (1) 목표 판정 `xy_goal_tolerance` 를 min(·, 0.10) — sim 시험값 `min_lookahead_dist` 0.15 아래로. (2) 패딩 외접원(0.115 m)을 전역 비용지도(플래너)에만 넣고, 지역 비용지도(RPP 충돌 검사)는 장치 풋프린트를 그대로 둔다. `nav2_params.yaml`(장치)은 바꾸지 않았다. 파일 600줄(예산 600).
- 증거: 수정 전 열린 가운데에서 0.40 m 목표 — `cmd_vel_nav` 1043개 표본 모두 linear 0, 이동 0.001 m, "Failed to make progress". 0.15 m 안쪽 스캔 반환 0개, 로봇 주변 비용 0 → 자기 반사·이웃 가설 기각. Jazzy RPP 1.3.12 는 carrot 거리가 목표 허용오차보다 짧으면 목표 방향으로 제자리 회전만 한다. 수정 1만: 사각형 A 에서 "collision ahead", 0.013 m. 두 수정 후: 열린 가운데 1 m 목표 2/2 SUCCEEDED(0.93, 0.91 m 이동), 사각형 A 3/3 SUCCEEDED(0.26–0.30 m), 사각형 A 1회는 재계획 "Start occupied" 로 중단. WSL Jazzy, 로봇 1대, `core:=false` + 중계, GZ_PARTITION rosy_g4, ROS_DOMAIN_ID 97, 원시 `X:\DevTemp\rosy-g4\`. `test_gz_multi_core.py` 에 두 단언(수정 전 실패 확인), WSL `src/sim/gz_sim/test` 280 passed, 1 skipped.
- gate 변화: 없음
- 결정: 없음. 장치 기본값 변경 제안 없음 — 장치 값(lookahead 0.3 > 허용 0.25, 지역 정사각 풋프린트)은 이 문제가 없다.
- 교훈: RPP 의 lookahead 를 줄이면 목표 허용오차도 같이 봐야 한다 — carrot 이 허용오차 안이면 "도착"으로 보고 회전만 한다. 그리고 플래너용 보수적 풋프린트를 컨트롤러 비용지도에 같이 넣으면 벽 옆 출발이 막힌다.

## 2026-10-02 · d8f96fb8 · feat(sim): omx_cell_workcell world (Rosy Cell C3)

- 변경: `worlds/omx_cell_workcell.sdf`(탁자, 팔레트 2, 인피드 블록, 슬립시트 받침; world = OMX link0, step 2 ms, 카메라 없음)와 `omx_cell_workcell_sim_aid.sdf`(블록↔link5 DetachableJoint, 표시된 sim aid). 실행은 `deploy/robot/omx/run_cell_sim.sh`.
- 증거: docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md. 소프트웨어 렌더 카메라를 켜면 RTF 0.06, 끄면 0.3–0.95.
- gate 변화: 없음(gz_sim 다중 로봇 gate와 무관).
- 결정: D-402, D-403 §5.

## 2026-10-02 · uncommitted · feat(sim): gz_multi sim-only physics_step / real_time_factor / gpu (D-395 S2 rerun)
- 변경: `gz_multi_args.py`에 `physics_step`(빈 값 기본, 예 `physics_step:=0.005`), `real_time_factor`(빈 값 기본), `gpu`(기본 false) 인자. 물리 단계는 Gazebo가 읽기 전 월드 SDF 사본(`<bridge_dir>/physics_<world>`)의 `<physics>`만 바꾼다 — `set_physics` 서비스는 gz.msgs.Physics 전체를 받아 빠진 필드가 0이 된다. 단계 상한 0.01 s(IMU 100 Hz). `gpu:=true`는 서버 기동 전 `GALLIUM_DRIVER=d3d12`. 로봇 코드·센서 속도·샘플 수는 그대로. `d395_s2_bench.py`에 `--physics-step`, `--gpu`.
- 증거: WSL `glxinfo -B` 기본 llvmpipe(Accelerated: no), `GALLIUM_DRIVER=d3d12`에서 "D3D12 (AMD Radeon(TM) 860M Graphics)" GL 4.6 Accelerated: yes(EGL surfaceless 같음). WSL Jazzy `test_gz_multi_core.py` 20 passed, host `test_d395_s2_bench.py test_gz_multi_core.py` 16 passed/1 skipped.
- gate 변화: 없음(기본값 불변).
- 결정: 없음

## 2026-10-04 · uncommitted · fix(ui): 경로 뷰어의 미수신 거리

- 변경: 독립 lane viewer는 첫 경로 수신 전 완료 수/거리를 대기/미확인으로 표시한다. renderProgress(null)은 이전 거리·진행 막대·현재 key와 key 강조를 지우며 실제 측정 0은 유지한다. 공용 경로·framework를 추가하지 않았다.
- 증거: null 수명 원본 제공 1 passed (2.54s), 기존 키보드 탭과 경기 보드 2 passed (4.54s). X 제공 null 거리 정리 제거 변이가 이전 2.0m를 남겨 실제 단언 RED, 동일 원본 제공 GREEN·제품 SHA256 불변을 확인했다.
- gate 변화: SOURCE/LOCAL 읽기 전용 뷰어이며 Gazebo/장치/물리 gate는 움직이지 않는다.
- 결정: D-439 Task5. 미수신을 측정 0으로 표시하지 않는다.

## 2026-10-05 · uncommitted · feat(scripts): D-426 T5 sim base command watchdog

- 변경: `scripts/command_watchdog.py` 추가 — CORE와 별도 수명의 ROS 노드. 최신 cmd_vel을 구독·재발행하다 0.30 monotonic s 만료 시 base 입력을 0으로 만든다. CORE의 operational cmd_vel writer를 늘리지 않는다(재발행은 시뮬 base 입력에만). 순수 판정(`gate`)은 호스트 시험이 돌리고 rclpy 배선은 얇다. clock pause에도 만료 작동(판정은 monotonic). 시계 역행은 stale 명령이 아니라 0으로 처리.
- 증거: test/test_command_watchdog.py 8개 계약 — 무명령 즉시 0·신선 명령 통과·0.30 s 경계·clock pause 만료·시계 역행 0·CORE kill 경로 0.29/0.31 s 분기·--help·rclpy 부재 시 안내 후 exit 3.
- gate 변화: SOURCE/LOCAL(순수 판정). 실제 Gazebo 회차에서의 bridge 수명·프로세스 크래시 정지는 T6이 증명한다(bridge 자체 사망 시 actuator 정지 보장은 별도 한계).
- 결정: bridge는 CORE의 명령 흐름에 의존하지만 죽지 않는 한 CORE 사망을 0.30 s 안에 base 정지로 바꾼다(D-426 결정 5).

## 2026-10-05 · uncommitted · feat(launch): D-426 T1 run_spec — 검증 runner 소유 실행 입력

- 변경: `gz_multi.launch.py`에 `run_spec` 인자 추가(645→538줄, D-362 예산 유지를 위해 비-launch 부품을 `gz_multi_parts.py`로 분리 — 브리지 매핑·CORE 오버라이드·robots.yaml·run_spec 판독). 검증 runner(`tools/validation/fleet_gazebo/run.py`)가 run별로 만든 CORE 오버레이·robots.yaml·GZ_PARTITION을 런치가 그대로 소비한다 — 런치가 예약·토큰을 새로 만들지 않는다(불일치는 곧 READY 거절 사유). run_spec 이 없으면 기존 자체 생성 동작(임시 디렉터리·개발 토큰)이 그대로다. 필수 필드 누락·오버레이 부재는 즉시 실패.
- 증거: `test/test_gz_multi_run_spec.py` 3개(빈 spec 레거시·필드 누락 RuntimeError·로봇별 오버레이 부재/존재). Windows skip, Linux CI에서 실행. `test_gz_multi_core.py` 기존 회귀 통과(분리 후 `_core_config` 등 import 별칭 유지). 크기 판정 시험 통과(538 < 600).
- gate 변화: 없음(SOURCE). 실제 Gazebo 실행·ROS-SIM은 T6 회차 뒤.
- 결정: D-426 T1의 런치 절반. 예약·manifest·READY 판정은 runner 쪽 `preflight.py`(test/test_fleet_gazebo_run_contracts.py 12개).

## 2026-10-05 · uncommitted · fix(sim): D-426 T1 domain 적용과 예약 preflight

- 변경: runner 명세의 정수 ROS domain을 참여 프로세스 앞에서 적용하고 Gazebo/Fleet 안내 명령에 같은 환경을 넣었다. robots/prefix·명세 namespace와 CORE 오버레이의 identity/loopback API 포트 불일치는 거부한다. 명세 없는 기존 경로는 domain을 변경하지 않는다.
- 예약: 기존 run manifest의 결정적 profile을 검증하고 최대 256개 기록의 충돌 및 실제 loopback listener 점유를 확인한다. 손상된 기록은 실패하고 stale 기록은 보존한다. 계획 snapshot이며 수동 launch까지 유지되는 포트 lease·동시 planner 배타 예약의 증거는 아니다.
- 검증: 최초 누락 회귀 4 FAIL, 손상된 예약 회귀 4 FAIL을 실제 소스로 재현했다. 기존 전체 Gazebo 시험의 blanket ROS_DOMAIN_ID 금지는 D-114의 같은 run/여러 namespace 원칙을 유지하면서 명세 domain action으로 정확히 바꿨다. 최종 결과는 별도 영수증에 기록한다. ROS 의존 시험 skip은 CI에서 확인하며 실제 SIM/장치/주행은 실행하지 않았다.
- gate 변화: D-426 실제 ROS-SIM 수용은 계속 미검증이다. 기존 단일 로봇 회차 증거를 이번 다중 격리 수용으로 승격하지 않는다.

## 2026-10-05 · uncommitted · fix(sim): T5 명령·시계와 수동 SIM 경계

- 변경: watchdog의 비유한 시각·잘못된 만료·비유한/비평면/0.15 m/s·0.5 rad/s 초과 명령은 zero로 닫는다. 수동 `--sim-only` 동의, 격리 ROS domain 120~199·localhost·D426 partition, 실제 ROS context domain·namespace·remap 이후 topic을 command publisher 생성 전에 대조한다. CORE/hardware runtime mode를 SIM이라는 새 값으로 덮지 않는다. 명시 STEADY_TIME clock으로 50 ms timer를 만들고 logger에 완성된 문자열을 준다. 동시 3779 namespace 정규화와 bounded entrypoint 시험의 의도를 보존했다.
- 검증: 실제 순수 함수·합성 ROS port를 쓰는 원래 entrypoint 반례 8+10+2 FAIL을 재현했다. 원래 watchdog/scenario와 Fleet-loss 포함 최종 71 PASS(7.38s), owned flake8 0, known_failures 0 NEW다. 동의 없는 실행은 ROS import 전에 거부하고, 유효 SIM 동의 뒤 ROS dependency를 명시 차단한 별도 subprocess는 15 s 안에 안내·exit 3을 확인했다. 최초 관련 시험 파일명 오류와 중간 formatting 실패 로그를 보존했다.
- gate 변화: SOURCE/HOST callback wiring만. 실제 DDS·STEADY timer scheduling·Gazebo base 연결·pause 장애 주입·CORE kill·장치 publisher·실물 정지는 실행하지 않았다. 0.30 s 입력 expiry 판정과 50 ms polling·scheduling/물리 정지 지연은 구분하며 T5 회차 수용은 HOLD다.

## 2026-10-06 · uncommitted · feat(sim): Gazebo IMU·IR 바닥 광선과 sim_sensors

- 변경: `launch_sim.launch.xml sim_sensors:=true`(기본 false)가 둘째 bridge(`params/rosy_bridge_sim_sensors.yaml`: 모델 IMU `imu_raw`, IR 광선 셋)와 `scripts/sim_ir_floor.py`(장치 모양 `ir_sensor/range`, 바닥 2000 / 없음 0, 반사율 미모델)를 띄운다. `map_v2_fleet_real.launch.py`가 인자를 넘긴다. `config/sim_sensors_core.yaml`은 CORE overlay 조각(enforce, lidar/imu/ir, `simulation_sensors`)이다.
- 증거: `test/test_sim_sensors.py` 6 PASS. 모델 PC D-476 2차 실행(`docs/validation/d476-gazebo-model-pc-2026-10-06/result.md` 2차 절)에서 `/ir_sim/mid` 0.0127 m, `ir_sensor/range` [2000, 2000, 2000], `imu_raw` 확인.
- gate 변화: 없음. ROS-SIM 한 대 실행이며 장치·현장 수용이 아니다.

## 2026-10-06 · uncommitted · fix(sim): sim IR 값을 worker 유효 범위에 맞춤 (리뷰)

- 변경: `sim_ir_floor.py` 바닥 없음 값 0 → 100(`hazard.py on_ir`은 0 < v < 4000만 유효로 받아 0은 절벽이 아니라 무효 IR이었다). 세 채널이 모두 들어오기 전에는 프레임을 내지 않는다. 채널 순서를 장치 `ir_adc_node.py`([ch2, ch1, ch0] = 좌·중·우)에 시험으로 고정했다. `sim_sensors`는 단일 로봇 전용임을 launch 주석에 적었다.
- 증거: `test/test_sim_sensors.py` 9 PASS.
- gate 변화: 없음.
## 2026-10-07 · uncommitted · test(sim): D-495/D-498 교차로 회전 SIM 수용 (모델 PC)
- 변경: 제품 코드 변경 없음. 기록 `docs/validation/d495-junction-sim-2026-10-07/`(result.md, evidence). 하네스는 sim 전용 launch 사본(IR 보정만 더함, 페이로드 `line_follow.yaml` 그대로), `d495_sim_aux.py`(참값 자세 `d495/gt`, 도색 raster로 만든 IR `ir_sensor/range`, scan/odom 멈춤 주입, odom을 `/clock`이 stamp를 지난 뒤 냄), HTTP 전용 탐침 `d495_sim_probe.py`(trip, fault).
- 증거: 모델 PC `map_v2_fleet_real` keep 한 대, run 40개 요약. S3·S4·S8·S9 PASS, S5 부분, S1·S2 FAIL, S6 INCONCLUSIVE, S7 IR 중단 0회(점 IR 한계). 로봇 기본값(`recovery_local_enabled: true`, enforce 없음)에서는 차선 주행이 출발하지 않는다.
- gate 변화: 없음. ROS-SIM 한 대, 장치·현장 수용 아님.
- 결정: D-495 수용 점검표 S1–S6, D-498 S7–S9 (승격 전 남은 항목은 result.md 발견 1–9)
- 교훈: 끝난 launch가 남긴 bridge가 odom을 같은 stamp로 겹쳐 내면 CORE PoseTrail이 끊긴다. sim 실행 스크립트는 자기 `GZ_PARTITION`의 프로세스를 모두 끝낸 뒤 띄운다. 같은 호스트의 다른 sim과는 도메인·포트·world 파일 이름까지 나눈다.
## 2026-10-10 · uncommitted · fix(sim): SIM Fleet 공용 사이트 설정 (D-601 B)
- 변경: `config/fleet_sim_site.yaml`(`fleet.trip.lane_camera_check: false`)을 두고 SIM에서 Fleet을 띄우는 곳 여섯(`tools/run_fleet_sim.sh`, `tools/validation/fleet_gazebo/run.py`, `tools/sim/d395_s1_bench.py`, d407 `console.sh`, lap_fleet.py 둘)이 이 파일을 읽는다. SIM 런치는 road_observer를 띄우지 않아 CORE `vision/front/status`가 언제나 `available: false`다.
- 증거: `operations/fleet/test/test_fleet_sim_site_d601.py`(설정 적재, 여섯 곳 참조, 미리보기 없는 FakeRobot의 lane 계획 200).
- gate 변화: 없음. SIM 실주행 재확인은 하지 않았다.
## 2026-10-10 · 5aa301e83 · feat(sim): 카메라 SIM 런치가 앞 미리보기를 낸다 (D-605, D-601 B)
- 변경: `map_v2_fleet_lane`·`map_v2_fleet_real`과 d495_real·closed_loop 하네스 사본이 `sim_jpeg_relay.py`(gz_sim이 `tools/`에서 설치, `use_sim_time` 없음)를 띄운다. 카메라 SIM Fleet(d407 console.sh, lap_fleet.py 둘)은 `config/fleet_sim_camera_site.yaml`(`lane_camera_check: true`), `gz_multi` Fleet 셋은 `fleet_sim_site.yaml`(`false`). `run_fleet_sim.sh`·d407 `console.sh`의 글자 그대로 `
` 줄 이음(e789581de)을 고쳤다.
- 증거: 모델 PC `map_v2_fleet_lane`(domain 91, port 8199): `vision/front/status` `available: true`, `source GZ`, `age_ms` 41–150, sequence 157→176(약 5 fps). `GET /api/v1/traffic` `mode DISABLED` 그대로. 30 s CPU tick: 릴레이 18(코어 한 개의 0.6%), CORE 2780, gz 1602. `use_sim_time` 켠 릴레이는 20 s에 477 tick(약 24%)이었다. 테스트 `operations/fleet/test/test_fleet_sim_site_d601.py`.
- gate 변화: 없음. 카메라 SIM에서 Fleet lane trip 실주행은 하지 않았다.

## 2026-10-10 · bb6347eba · feat(sim): 곡률 학습 맵 선택

- 변경: map_v2_fleet_real.launch.py의 map_variant:=training-curved가 world와 lane_graph를 같은 파생 번들에서 선택한다. 기본 실행은 기존 실물 기준 맵이다.
- 증거: bb6347eba의 맵·그래프·런치 관련 모델 PC 원격 pytest 57 passed, known_failures 0 new/0 known. 시뮬레이터 실행·신호 준수·두 로봇 Fleet 수용은 아직 확인하지 않았다.
- gate 변화: 없음. 파생 맵의 ROS-SIM 수용은 별도다.

## 2026-10-12 · 785b46314 · feat(sim): 두 대 Gazebo의 공통 curved 맵 선택

- 변경: D-676 사용자 분담에 따라 Isaac은 한 대 학습·완주, 다른 PC의 Gazebo는 두 대 Fleet 검증으로 구분한다. gz_multi의 world_name:=map_v2_fleet_curved.world가 Isaac과 같은 training-curved/worlds/map_v2_fleet_real.world를 선택한다. 시각 차선 곡률만 바뀌므로 외곽 충돌 벽의 기존 occupancy map을 공유한다. 두 대는 분리된 spawn_poses를 명시한다.
- 증거: AI PC 원격 world_profiles 11개 PASS, known_failures0NEW. 함께 요청한 gz_multi Core/run-spec 모듈은 ROS launch import 조건이 있어 이 결과로 검증됐다고 주장하지 않는다. 두 로봇 native 실행·카메라·Fleet·완주·신호 수용은 아직 미확인이다.
- gate 변화: 없음. 이전 단일 로봇 ROS-SIM 결과를 새 curved 두 대 수용으로 승격하지 않는다.

## 2026-10-12 · 3c50387944 · feat(sim): D-676 camera 두 대 전용 launch

- 요청: 모델 PC Isaac 한 대 camera/RL, 다른 PC Gazebo 두 대 actual CORE/Fleet를 같은 curved 맵으로 검증한다.
- 변경: gz_multi는 image transport 없이 nominal camera geometry와 headless rendering만 선택한다. map_v2_fleet_multi_real 전용 launch가 runner-owned run_spec·모델 pointer를 받고 두 namespaced local image bridge·기존 line_observer·JPEG relay를 구성한다. camera Fleet은 fleet_sim_camera_site.yaml의 preview admission을 유지한다.
- 증거: 원격65pass1skip·D601/package16pass·known_failures0NEW. AI PC ROS Jazzy에서 두 namespaced 인식/미리보기 각3노드와 CORE2개 launch graph를 확인했다. ROS pytest 모듈은 skip이며 graph 확인이 native 실행을 대신하지 않는다.
- gate 변화: 없음. 초기 연결 구성이다. 신호/횡단보도 gate·Fleet 실행·두 대 주행/완주·RL 성공은 아직 미검증이다. 기본 gz_multi와 D-118 parameter bridge에는 생 Image를 추가하지 않았다.

## 2026-10-12 · 3c50387944 · test(sim): Gazebo 두 카메라·CORE 정지 상태 연결

- 변경: 제품 런타임 변경 없이 AI PC 신규 A16 환경의17개 colcon package를 빌드하고 전용camera launch로 두 로봇을 실제 headless 생성했다. 독립API·HOME·namespace·loopback DDS·run_spec를 사용하고 Fleet/주행 요청은 하지 않았다.
- 증거: rosy_01 image310/scan387/odom1137/line310/cmd1933, rosy_02도 센서/미리보기 수신, 각 LiDAR finite640·320x240 camera·CORE publisher1개·cmd 최대0·실제 odom속도0. 원본result/사진/log/cleanup은 private/isaac/results/gazebo-a16-stationary-two-camera에 보관했다. partition에 남은 own process13개를 종료하고 residual_after0을 확인했다.
- gate 변화: 없음. CORE runtime의 DOMAIN_ID_INVALID와 FOREIGN_NAMESPACE를 확인했다. runner run_spec120..199와 CORE Linux-safe0..101 계약이 모순이며 domain172는 ERROR다. 연결 증거일 뿐 Fleet runtime 준비/카메라 주행/교통/완주/RL 수용이 아니다. 서로다른 로봇namespace 진단과 domain allocator/validator를 계약·시험과 함께 바로잡아야 한다.


## 2026-10-12 · eae0f59da0 · fix(sim): CORE 범위와 Gazebo 예약 도메인 일치

- 변경: 검증 allocator·run_spec·sim-only watchdog 80..99, 일반 sim 20..79. CORE 0..101/localhost/partition/namespace/실제 context/monotonic expiry 유지. 기존 120..199 catalog는 거절하며 새 output_root가 필요하다.
- 증거: 관련 원격 87PASS1SKIP·known_failures 0NEW·독립 소스 안전 검토 차단 없음. 신규 17 packages 빌드 후 실제 headless Gazebo 두 CORE domain 80, 각 320x240 camera 311·finite640 LiDAR389·odom1143·최종 publisher 한 개·명령 0 확인. ROS ERROR가 사라지고 FOREIGN_NAMESPACE 경고는 유지. 자체 partition 종료 후 잔여 0.
- gate 변화: 정지 runtime 도메인 결함 해결. Fleet 서버·교통·주행·완주·카메라 RL 수용은 미완료. 당시 모델 PC의 Isaac 한 대 재시험은 7.6GB로 8GB 기준을 넘지 못해 SDK 기동 전 거절됐다. 이후 실제 학습은 Isaac 일지에 별도 기록한다.

## 2026-10-12 · ccc7905f2 · 공유 지도 NE/SW 진입 정합성

- 변경: lane_rules의 기존 TurnBan으로 NW·SE 재진입을 금지하고 두 lane_graph를 재생성했다. Fleet import·신호 접근로 검사가 금지를 보존하며 camera sim site는 cap1 roundabout과 NE·SW 신호 접근로를 설정한다. Isaac 경로는 reverse 도로로 합법적인 진입을 사용한다.
- 증거: 두 파생 지도의 접근로·cap1·신호 plan과 실제 routing successor, native 금지 경로 거절 회귀를 추가했다. 원격 시험과 독립 안전 리뷰 결과는 후속 기록한다. 실제 Fleet A18 readback은 이전 설정에서 signals=[]·링 분리 블록을 확인한 원인 증거이며 새 설정의 성공 증거가 아니다.
- gate 변화: 아직 없음. 새 경로 baseline/RL·네 실제 신호 표시 연결·CORE/Fleet 회전 연결·완주·교통/장애물·Gazebo 두 대·병렬 RL·실물 수용은 미완료다. 다른 경로의 R17/R21 수치를 개선 비교에 사용하지 않는다.

## 2026-10-12 · a3150e7669 · 공유 지도 진입 규칙 원격 검증

- 변경: NE·SW 진입/NW·SE 진출 규칙을 공유 지도·Fleet·native route에 반영했다. 독립 D-430 소스 리뷰를 통과했다.
- 증거: 관련 6개 원격 파일 135 PASS·exit 0·known_failures NEW 0. 현장 PC 격리 pytest이며 물리 주행은 없다. lint 일지 heading 3개를 수정한 후 0 errors·28 warnings. A19 소스 전송은 Broken pipe·exit 1, 후속 SSH 두 번 timeout으로 서버를 실행하지 않았다.
- gate 변화: SOURCE 회귀만 확인했다. 실제 신호 적재·네 표시·새 경로 baseline/RL·완주·교통 안전·두 대·병렬 학습은 미완료다. 다른 작업의 예약과 부분 전송 소스를 실행 승인으로 해석하지 않는다.

## 2026-10-12 · aea25e6c15 · 최신 main 통합과 실제 Fleet 설정 readback

- 변경: main 16e6fa373을 작업 브랜치에 통합했다. 기존 TurnBan·공유 지도·camera site 신호 설정을 실제 격리 Fleet 서버에서 적재 확인했다.
- 증거: 통합 후 관련 원격 135 PASS·exit 0·NEW 0, lint 0 errors·28 warnings. A20 source archive SHA 양쪽 일치. 실제 인증 readback에서 map_v2_fleet·두 TurnBan·roundabout cap1·sig_ring NE/SW 접근로·errors=[] 확인. runner exit 0, 종료 후 독립 PID 부재·ECONNREFUSED 확인. private 원본 네 파일 hash 대조 보관.
- gate 변화: SOURCE/설정 적재만 확인했다. 신호는 virtual occupancy, online 0/total 2이며 실제 CORE/Gazebo·grant·주행·네 표시·완주·병렬 RL 수용이 아니다. main 착지·push는 아직 하지 않았다.

## 2026-10-12 · a49a754e94 · 새 합법 경로 native 평가와 Gazebo 연결 준비

- 변경: 새 NE/SW 진입 ordered 경로를 기존 segmentation·CORE·frozen RL로 실제 headless 평가했다. 최신 main 통합 소스로 별도 Gazebo build/install과 두 CORE·실제 Fleet 연결 정지 시험을 준비했다.
- 증거: R23 source 7,337 파일 실행 전후 hash 검증, SDK exit 1, 네 heading baseline/eval 완주 0/8·진행 0m. 영상 8개 ffprobe·SHA·시각 증가, 무효 camera 명령 0·최종 정지·GPU 없음·독립 runner PID 부재 확인. private 원본 56개 hash 대조 보관. A21 ROS 17 패키지 빌드 exit 0; 실행 직전 공식 sim selector는 eligible 없음·exit 1이다.
- gate 변화: 완주/RL 개선은 HOLD다. trace의 lane_cue null·junction idle과 camera_target_unavailable을 기록했다. native Fleet 회전·공간/오차 승인·재획득과 두 대 실제 주행이 남았다. 정지 sensor/Fleet 연결 script는 준비·syntax 확인뿐이며 A21 SDK/CORE/Fleet 실행을 주장하지 않는다. 기존 안전 정지를 완화하지 않았다.

## 2026-10-12 · uncommitted · 두 카메라 도로 관측 연결과 A21 실제 정지 시험

- 변경: 두 namespace에 기존 road_observer_node를 연결하고 중복 preview relay를 제거했다. CORE와 map/scene 식별자를 맞췄다. simulation 지면 guard가 거절하는 GZ 값을 GAZEBO로 수정하고 실제 shared projection helper의 생성 회귀를 추가했다.
- 증거: A21 실제 두 CORE·Fleet online 2/2, 카메라·차선·scan·odom 수신과 namespace별 최종 cmd_vel publisher CORE 하나를 확인했다. 모든 명령·최종 odom 속도 0, 종료 후 소유 프로세스·포트 부재 확인. private 원본 39개 SHA 대조 보관. roslogs/latest 절대 symlink는 안전 추출에서 제외했다. 새 도로 연결의 원격 회귀·native 실행은 아직 미확인이다.
- gate 변화: 실제 정지 연결 증거만 추가했다. 위치 UNKNOWN, 설정 ENFORCED와 snapshot DISABLED 불일치로 교통 모드 수용은 보류다. 주행·도로 검출 정확도·신호 표시·완주·병렬 RL 개선은 미완료다.

## 2026-10-12 · 493894894 · 道路 관측 연결 원격 회귀

- 변경: 새 Gazebo 도로 관측 연결의 source 검토와 원격 계약 시험 결과를 기록했다.
- 증거: 독립 Safety-Review SOURCE APPROVE. AI PC의 committed HEAD 시험은 관련 네 파일 60 PASS·exit 0, known_failures 0 new·0 known이다. 실제 projection helper에 launch params를 전달한 회귀가 포함됐다. harness lint 0 errors·28 warnings.
- gate 변화: 원격 회귀만 통과했다. 실제 road/observation 수신·교통 endpoint 모드·preview 단일 발행과 주행 완주는 별도 미확인이다.

## 2026-10-12 · d9fbc11ce · A24 두 CORE 도로 관측과 교통 설정 readback

- 변경: 새 도로 관측 연결·기동 snapshot 수정을 포함한 소스를 격리 AI PC에서 빌드·실행했다. 최신 main 6c39ed8ae를 별도 통합해 f2c8b2e1f에서 관련 회귀를 다시 수행했다. 일지 충돌은 양쪽 기록을 보존하고 인덱스를 재생성했다.
- 증거: A24 source 7,337 파일 hash 확인, 17 ROS 패키지 build exit 0, native 정지 runner exit 0. online 2/2·로봇별 road/line/image 271건·preview publisher 하나·최종 CORE publisher 하나·명령/최종 odom 속도 0. 실제 교통 API와 snapshot ENFORCED 일치. 기존 named operator pin API로 실제 Gazebo 위치 등록 후 LOCALIZED 두 대를 확인했다. 독립 PID 부재·세 포트 ECONNREFUSED·private 원본 47개 SHA 대조. 통합 f2c8b2e1f의 원격 관련 278 PASS·exit 0·known_failures NEW 0.
- gate 변화: 도로 topic·정지 연결·활성 설정 증거만 추가했다. CORE 내부 valid 수신은 다음 sensors endpoint 확인이 필요하다. 첫 로봇 learned crosswalk 검출과 RGB road crosswalk=false의 차이, 둘째 containment uncertainty=null이 남았다. operator pin은 지속 카메라 위치 증거가 아니며 완주·교통 인식·grant·병렬 RL·실물 수용은 미완료다. A24 native는 main 통합 전 소스다.

## 2026-10-12 · 8226c122f8 · IR 바닥 ray의 동일 프레임과 신선도 보존

- 변경: 기존 sim_ir_floor 변환이 새 mid ray와 옛 좌우 ray를 합쳐 바닥 증거를 갱신하던 오류를 수정했다. 세 ray의 동일한 정규 timestamp·새 프레임·20Hz 한 주기 이내 source age를 확인하고 ROS clock timer에서 한 번만 발행한다. 입력 분류 함수·ADC 형식·바닥 거리·CORE motion gate는 유지한다.
- 증거: 원격 RED로 혼합 timestamp의 floor 갱신을 재현했다. 수정된 Gazebo 전체 회귀는 318 PASS/4 SKIP/terminal exit 0이고 독립 drive_review가 202c807dc 및 8226c122f8에 SOURCE APPROVE했다. 별도 AI PC R6 정지 실행의 기존 소스에서 두 로봇 각각 세 ray의 동일 시각 514/514 프레임과 실제 IR·IMU·scan, enforce 및 junction_turn capability를 확인했다. R6는 수정 helper 실행 증거가 아니다.
- gate 변화: SOURCE/원격 회귀와 실제 센서 연결 근거를 구분한다. R6의 첫 로봇 blocked=true는 유지했다. 새 helper의 실제 실행·유효 Fleet 통행권 아래 주행·완주·장치 수용은 별도 검증이 필요하다.

## 2026-10-12 · 45e92d326 · 실제 완주 기준 실행과 조향 설정 배선

- 변경: 단일 카메라 launch와 두 로봇 run_spec에서 observer가 해당 CORE와 같은 오버레이를 사용한다. 완주 기준은 docs/plans/2026-10-12-gazebo-lane-lap.md에 기록했다.
- 증거: 기준 소스 2e29bd118의 7,503 파일과 17 ROS 패키지를 새로 빌드했다. 실제 구간은 anchor age 10.244s에 최종 0.210783m에서 stopped였고 arrived가 아니다. 기억 목표 3프레임 후 off_line/closed를 관측했다. 종료와 소스 보존을 독립 확인했다. out_of_order count는 부수 진단이었다.
- gate 변화: 지도 완주는 HOLD다. 초기 pin은 지속 위치 관측이 아니며, SIM-only typed 위치 provider와 native 주행법칙 handover를 별도 검토 중이다. 단독 launch의 camera import 실패는 깨끗한 기준 소스에서도 재현됐다. 855eebc에서 시험 bootstrap을 고쳤고 재확인은 남았다.

## 2026-10-12 · 3bafbd232 · 두 카메라 실행의 원본·곡선 지도 선택

- 변경: multi_real의 map_variant는 기본 training-curved를 유지하고 원본 .을 선택할 수 있다. 기존 world catalog에 원본 real world를 등록하고 같은 선택값으로 실제 world와 두 observer의 lane_graph를 맞춘다. spawn·카메라 법칙·CORE 권한·모드·안전 기준은 유지한다.
- 증거: 원격 ROS Jazzy descriptor RED 3개로 선택자 누락을 재현했다. 커밋 3bafbd232의 관련 원격 계약 59개는 정상 자원 기준에서 통과했고 known_failures NEW 0이다. 실제 ROS 객체에서 기본값·두 world/graph 일치·잘못된 값 거절을 확인했다. 시험 로그는 X:/DevTemp/projects/rosy-platform/2026-10-12--150326--camera-effective-law--fe7d36/logs/map-variant-green3/run-1.txt이다.
- gate 변화: SOURCE/원격 계약 증거만 추가한다. 이 선택자로 실제 Gazebo 원본 주행·지도 완주·실물 수용은 아직 확인하지 않았다.

## 2026-10-12 · 2efcfe4b2 · 독립 Gazebo 시험의 CORE 설정 출처 고정

- 변경: Gazebo 시험만 수집할 때도 contracts/foundation을 소스 경로에 등록한다. 기존 관측 법칙 시험이 원격 venv에 설치된 CORE 패키지와 누락된 site-packages/config 기본 파일을 읽던 문제를 고쳤다. 제품 설정 로더와 시험 실행기의 동작은 바꾸지 않았다.
- 증거: 후보와 부모 5caaa8f8e의 전체 Gazebo 수집에서 동일한 설정 파일 누락 NEW 2를 재현했다. 수정 2efcfe4b2의 정상 AI PC 원격 전체 시험은 324 PASS/2 SKIP, terminal exit 0이다. 새 단언은 실제 config 모듈과 기본 YAML이 커밋된 foundation 출처임을 확인한다. 로그: X:/DevTemp/projects/rosy-platform/2026-10-12--150326--camera-effective-law--fe7d36/logs/map-variant-full2/run-1.txt.
- gate 변화: 독립 수집의 원격 회귀 증거를 추가했다. 실제 Gazebo 원본 맵 주행과 완주는 여전히 별도 검증 대상이다.

## 2026-10-12 · uncommitted · 시뮬 관찰 법칙은 core_common 의존으로 선언한다

- 변경: `gz_multi_parts.py`가 CORE line_follow 법칙을 읽으므로 `gz_sim/package.xml`에 `core_common` exec_depend를 선언했다.
- 증거: 착지 라운드의 원격 시험이 `test_every_cross_package_use_is_declared`와 `test_package_xml_covers_imports`를 NEW로 보고 멈췄다. 선언 뒤 재시험은 이 기록 다음에 돈다.
- gate 변화: 없음. 시뮬 완주와 실물 수용은 이 선언으로 승인하지 않는다.

## 2026-10-12 · uncommitted · 두 카메라의 횡단보도 거리 불확실성을 전달한다

- 변경: map_v2_fleet 두 learned line observer에 기존 crosswalk_uncertainty_enabled를 명시했다. 검출된 횡단 구역 또는 미검출 프레임의 lookahead 거리 오차를 기존 containment에 전달한다. 이 입력은 기존 조건부 구역 수용과 IR guard 유예에 사용되므로 보고만의 변경은 아니다. CORE 횡단 gate의 활성 여부·임계값·최종 명령 권한은 변경하지 않는다.
- 증거: 원격 RED에서 두 namespace 공통 parameter 누락을 재현했다(1 FAIL/2 PASS). 기존 GAZEBO 투영 오차는 경계 미검출 때도 존재하므로 초기 시험의 null 가정을 정정했다. 켜기 전후 lateral 오차 동일, 빈 경계 보존, crosswalk 유무별 finite positive along 오차를 검사한다. 수정 ac1a13865의 관련 원격 회귀는 AI PC에서 151 PASS, terminal exit 0, known_failures NEW 0으로 확인했다.
- gate 변화: 수용 등급은 그대로 HOLD이며, 입력 연결은 조건부 구역 수용에 영향을 준다. 유효 구역 수용·서행/정지 정책·보행자·Fleet·완주는 실제 두 로봇 실행에서 별도로 확인한다.

## 2026-10-12 · uncommitted · Validate optional ROS launch environment and normalized parameters

- 변경: The test helper treats additional_env=None as an empty mapping and uses evaluate_parameters for the normalized steering-law mapping. Runtime code is unchanged.
- 증거: CI 38239921624 gz-sim failed with TypeError. A native ROS replay then exposed KeyError in the parameter assertion. After both test fixes, AI PC Jazzy with the existing runtime venv passed 11 tests with 13 skips, exit 0, NEW 0. The remote_pytest transport and resource controls were retained; only its test shell sourced ROS and selected that existing interpreter. The ordinary ROS-free venv skipped this module.
- gate 변화: Stationary/native test evidence only; no driving acceptance.

## 2026-10-15 · cbf3ab55bd · restore native SIM profile and contract installation

- Change: declare the actual default robot profile as a runtime dependency. The remote runner reuses the release contract wheel installer inside its run scope and caches its wheel build prerequisites by requirements and recipe.
- Evidence: package regression RED then 42 passed/NEW 0; installer wiring RED 2 then 33 passed/NEW 0. Native build of 17 packages and real wheel import smoke succeeded; all three CORE robot_id responses matched. Swarm arming refused missing swarm.lead; a capability-ready rerun could not start above the SIM resource floor. Logs are under the X: gazebo-profile--7ab1db managed session.
- Gate: no promotion. Startup readback is not formation/HOLD, site-map, device or field acceptance. Full lab landing remains required.

## 2026-10-15 · 271f923283 · select the default profile in remote build composition

- Change: undo the generic package's robot-specific dependency after D-196/D-310 review. The remote runner reads DEFAULT_ROBOT for colcon's package selection and uses the existing contract installer. No literal backlog or failure guard change.
- Evidence: initial FULL completed 25944 passed, 1848 skipped and one NEW product-literal failure, so landing stopped. The corrected profile-selection/installer/literal/package regression passed remotely: 36 passed, exit 0, NEW 0. Initial full logs remain in the X: gazebo-profile--7ab1db session under logs/full-initial.
- Gate: unchanged. Native startup proof belongs to the earlier composition; the final composition still needs actual SIM and the landing-selected regression. No formation/HOLD, device or field acceptance claim.

## 2026-10-15 · 5eb721d11 · 두 로봇 Fleet+Gazebo 차선 trip을 커밋된 구성으로

- 변경: `map_v2_fleet_multi_real`에 로봇별 IR 바닥 ray·`sim_ir_floor.py`·SIM IR 교정(`gz_multi_parts.SIM_IR_CALIBRATION`: 바닥 2000 검정, 포화 4000 흰색)을 넣었다. `learned_paint_target` 기본은 `lane_marking`이고 `learned_lane_pointer`는 선택이다. `remote_sim.py`는 CORE에 없는 Fleet pin과 D-373 학습 런타임을 설치한다. 실행기는 `tools/sim/fleet_trips.py`(벤치 `fleet_trips`, D-725 native pose)다.
- 증거: AI PC run-4 PASS. 두 trip 모두 `arrived`, 10 s 뒤 장소에서 0.021/0.019 m, 이동 0.423/0.401 m, 남은 프로세스 0. 관련 원격 회귀 exit 0, NEW 0. run-1·2·3이 각각 출발 거절(`LANE_END_NOT_A_PLACE`), pass window 안의 짧은 trip, 이른 판정 표본을 드러냈고 실행기에서 고쳤다. 자세한 내용은 `docs/plans/2026-10-15-sim-multi-robot-trips.md`.
- gate 변화: 없음. SIM 증거다. 학습 페인트, bend가 있는 바퀴, DEVICE·FIELD는 아니다.

## 2026-10-19 · uncommitted · fix(gz_sim): recover OMX workcell layout fixtures

- 변경: Recover preserved OMX workcell model coordinates and SIM AID layout with the matching analytic clearance tests. Source worlds remain simulation fixtures.
- 증거: Committed remote layout regression tests are pending; no new Gazebo run is claimed.
- gate 변화: None; historical partial native simulation is not field acceptance.

## 2026-10-21 · uncommitted · 라이브 뷰어 색을 공용 토큰으로

- 변경: `lane_live_view.html`이 `/common/tokens.css`·`theme.js`·`components.css`·`ui.js`를 싣고, 자기 팔레트(주황 강조·회색 단계·웹폰트 이름) 대신 역할 변수가 공용 토큰만 가리킨다. 원시 색은 CSS·JS·인라인 style 어디에도 없다. 지도·궤적 그림은 SVG style의 CSS 변수로 칠해 테마가 바뀌면 다시 그리지 않아도 따라간다. `data-theme-pin`을 지워 사용자 테마를 따른다. 장식 glow·blur·맥동·흐름·전환 효과를 지웠고 탭은 공용 `ui-button kind="segment"`다. 오버레이 범례는 서버가 영상에 그린 고정 색이라 견본 대신 색 이름으로 적는다. `lane_live_view.py`는 `/common/<name>`을 web_common의 `shared-assets.json` 목록으로만 내준다(폴더를 훑지 않는다, 없으면 404).
- 증거: 정적 검사만 했다. 원시 색 정규식 0건, 인라인 스크립트 `node --check` 통과, 서버 `/common/` 허용·404(목록 밖 이름, `..`, `%2e%2e`)를 cv2를 대신한 평범한 Python으로 확인. pytest·브라우저·Gazebo는 이 노트북에서 돌리지 않았다(D-584).
- gate 변화: 없음. 화면 G2 확인과 원격 회귀가 남았다.

## 2026-10-29 · 61f475246c · 라이브 뷰어 간격과 긴 결과 배치

- 변경: 일반 간격·tag corner·행 focus를 기존 공용 토큰으로 정리하고 긴 결과의 표/상세 wrapping을 보완했다. 실제 handler와 공용 자산을 사용하는 합성 브라우저 fixture로 바꿨다. script/body·SVG style22개·데이터 기하는 유지한다.
- 증거: 긴 결과8 RED 후 전체26 browser pass/0 skip, 카드 경계8 pass. 공식 affected833 pass/28 skip·NEW0, 최종32장 독립 검토 범위 P1/P2없음. 정본: `docs/validation/sim-viewer-spacing-2026-10-29/result.md`. 실제 Gazebo 미션 실행과 구분한다.
- gate 변화: 없음. ROS·CORE·장치·FIELD·설치/배포 수용은 아니다. CE: 해당 없음 — 기존 clipping 교훈을 적용했으며 원인과 해결이 코드·회귀·검증 기록에 드러난다.
