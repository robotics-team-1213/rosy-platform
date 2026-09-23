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

