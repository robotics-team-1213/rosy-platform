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

## 2026-10-02 · d8f96fb8 · feat(sim): omx_cell_workcell world (Rosy Cell C3)

- 변경: `worlds/omx_cell_workcell.sdf`(탁자, 팔레트 2, 인피드 블록, 슬립시트 받침; world = OMX link0, step 2 ms, 카메라 없음)와 `omx_cell_workcell_sim_aid.sdf`(블록↔link5 DetachableJoint, 표시된 sim aid). 실행은 `deploy/robot/omx/run_cell_sim.sh`.
- 증거: docs/validation/rosy-cell-gazebo-c3-2026-10-02/README.md. 소프트웨어 렌더 카메라를 켜면 RTF 0.06, 끄면 0.3–0.95.
- gate 변화: 없음(gz_sim 다중 로봇 gate와 무관).
- 결정: D-402, D-403 §5.
