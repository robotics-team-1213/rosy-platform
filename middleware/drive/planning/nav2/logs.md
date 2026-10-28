# navigation logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [Device 검증 계획](../../docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md)과 `git log -- src/navigation`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the navigation harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python -m pytest test/test_nav2_hardware_slice.py test/test_footprint_profiles.py test/test_nav2_profile_limits.py test/test_nav2_bandwidth_contracts.py test/test_flask_launch_removed.py -q` 36 passed (2026-09-15 Windows, 미커밋 WIP 포함 작업 트리); `python -m pytest test/test_nav2_profile_limits.py -q` 5 passed
- gate 변화: 없음. SOURCE/LOCAL GO, ROS-SIM/ARTIFACT/DEVICE HOLD, FIELD PARKED를 처음 기록
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-17 · uncommitted · fix(nav): 좁은 통로에서 실제로 완주하게 만든 네 가지
- 변경: 전역 플래너를 NavFn → `nav2_smac_planner::SmacPlanner2D`, `allow_unknown: false`, 생성 맵 4종의 `free_thresh` 0.25 → 0.196, 새 맵 `rosy_maze`/`rosy_swarm_bench` 추가, `rosy_factory` 맵을 slam_nav 로 재작성(미지 1476 → 1016 셀)
- 증거: WSL ROS 2 Jazzy + Gazebo. `gz_multi robots:=2 mode:=nav world_name:=rosy_maze.world` (인자 없이 월드 프로필만)로 두 대가 4구간 뱀형 미로를 완주 — `rosy_01` ARRIVED (1.98, 2.19), `rosy_02` 는 폭 0.55 m 문을 지나 ARRIVED (2.44, -2.34), 305 s. 공장 단독 8/8 목표 ARRIVED. 호스트 시험 2994 passed, 54 skipped (기존 control 실패 2건은 무관)
- gate 변화: 없음. ROS-SIM 증거는 쌓였으나 gate 승격은 커밋 뒤 재실행으로 판정한다
- 결정: 없음
- 교훈: 네 가지가 각각 단독으로 전 구간 실패를 만들었고 증상이 모두 "경로를 못 만든다"로 같았다. (1) `free_thresh` 0.25 는 미지 픽셀 205(shade 0.196)를 자유로 읽어 맵 바깥을 뚫어 놓는다. (2) 그 상태에서 `allow_unknown: true` 면 플래너가 벽 너머 지름길을 고른다. (3) NavFn 은 전위장을 만들어 놓고 길고 구불구불한 통로에서 역추적에 실패한다. (4) 팽창 반경이 통로 반폭보다 작으면 통로 한가운데가 전부 cost 0 이라 경로가 최단으로 칸막이 끝을 스치고, pinky 는 벽면 4.7 cm 까지 붙어 끼인다. 넓은 방 시험으로는 넷 다 드러나지 않는다

## 2026-09-18 · uncommitted · fix(nav): 기동 경쟁과 좁은 방 여유를 실측으로 잡는다
- 변경: 두 코스트맵에 `initial_transform_timeout: 30.0`
- 증거: 2x1 m 데모룸에서 nav2 가 활성화 중 `map→base` TF 를 5.5 s 만 기다리고 포기해 `global_costmap` 활성화가 실패했고 `planner_server` 가 함께 죽었다 — 목표는 `REJECTED` 로 끝나고 로봇은 한 발도 못 뗐다. 그 TF 는 AMCL 이 첫 스캔을 처리한 뒤에 나오는데, RTF 0.3 인 기계에서는 그것이 5 s 를 넘는다
- gate 변화: 없음
- 결정: 없음
- 교훈: 지역화가 늦게 서는 것은 느린 기계의 정상 동작이다. 활성화 대기시간이 그보다 짧으면 스택이 통째로 죽고, 증상은 "목표가 거절됨" 이라 원인과 한참 떨어져 보인다

## 2026-09-18 · uncommitted · fix(nav2): 코스트맵이 라이다를 한 번도 듣지 않고 있었다
- 변경: `params/nav2_params.yaml` 의 관측 소스 토픽을 `scan` → `/scan` (지역·전역 둘 다), `navigation/frame_prefix.py` 가 네임스페이스 환경에서 `/scan` → `/{ns}/scan` 으로 재작성, 시험 2건(`test/test_nav2_hardware_slice.py`). 교행 한계 측정용 월드 `gz_sim/worlds/rosy_gauntlet.world` 와 맵 `map/rosy_gauntlet.{pgm,yaml}` 신규
- 증거: 코스트맵 플러그인의 상대 토픽은 **코스트맵 노드** 네임스페이스에서 풀린다. `ros2 node info /rosy_01/global_costmap/global_costmap` 이 `/rosy_01/global_costmap/scan` 을 구독하고 있었고 라이다는 `/rosy_01/scan` 에 냈다 — 아무도 발행하지 않는 토픽이라 장애물 레이어는 관측을 한 번도 받지 못했다. 같은 지점(0.5 m 앞에 선 다른 로봇)의 전역 코스트맵 비용이 **고치기 전 0**(주변 7x7 전부 0, 반면 서쪽 벽은 244) **→ 고친 후 254**. 지역 코스트맵(정적 레이어가 없어 비용=관측)은 비용>0 칸이 0개 → **963개**(최대 254). `/rosy_01/scan` 구독자 2 → 4
- 증상: `rosy_gauntlet.world` 에서 두 대를 통로 양 끝에 세우고 서로의 자리로 보내면 **폭 1.4 / 1.2 / 1.0 / 0.9 / 0.8 / 0.7 m 여섯 전부** 정면 충돌했다(중심 간 0.01~0.08 m, 라이다 최소 0.05 m). nav2 로그에는 플래너 실패도 복구 동작도 없다 — 그쪽에서 통로는 비어 있었기 때문이다. 폭을 아무리 넓혀도 달라지지 않는다
- 고친 뒤 같은 스윕(팽창 0.15): **1.4 m PASS**, 1.2 m 아래는 전부 FAIL — 다만 실패의 성질이 바뀌었다. 충돌 대신 `RegulatedPurePursuitController detected collision ahead!` 가 2742 회, `Controller patience exceeded` 96 회, spin/wait 복구 14 회가 남았다. 고치기 전 같은 스윕에는 이런 줄이 **하나도** 없었다
- gate 변화: 없음(커밋 뒤 재측정으로 판정)
- 결정: 없음
- 교훈: **이 결함은 조용하다.** 경고도 오류도 남기지 않고, 정적 맵만으로도 항법이 그럴듯하게 동작하므로 단독 주행 시험은 전부 통과한다. 드러나는 순간은 맵에 없는 것이 앞에 있을 때뿐이다 — 다른 로봇, 사람, 치우다 만 상자. 네임스페이스는 실기 기본값이 빈 문자열이라 `/scan` 이 맞고, 시뮬만 프레임 접두와 같은 자리에서 바꿔 준다. 규칙이 두 군데로 갈라지면 한쪽만 고쳐진다

## 2026-09-18 · uncommitted · test(nav2): 교행 한계는 팽창으로 움직이지 않는다
- 변경: 기록과 상수만. `gz_sim/config/worlds.yaml` 머리말에 지금까지의 팽창 값이 **눈먼 코스트맵 시절**에 맞춰졌다는 사실을 적었고, `fleet/server/bays.py` 의 `PASSING_WIDTH_M` 을 실측으로 1.2 → 1.4 로 올렸다(시험 1건)
- 증거: `rosy_gauntlet.world` 스윕을 팽창 0.15 와 0.08 두 번 돌렸다. 결과가 같다 — **1.4 m PASS, 1.2 / 1.0 / 0.9 / 0.8 / 0.7 m 전부 FAIL**. 팽창 0.08 에서도 `detected collision ahead` 3260 회, `Controller patience exceeded` 102 회로 실패 성질은 같다
- 분석: 기하학적 최소는 0.36 m(풋프린트 반폭 0.06 + 패딩 0.03, 벽-A-B-벽), 팽창을 완전히 존중해도 0.66 m 다. 실제 한계 1.4 m 와의 차이는 공간이 아니라 **협상**이다. 마주 오는 두 nav2 는 서로를 움직이는 장애물로만 보고, 대칭이라 둘 다 같은 쪽으로 피했다가 그 자리에서 다시 만난다
- gate 변화: 없음
- 결정: 없음
- 교훈: 좁은 통로의 교행은 파라미터로 풀리지 않는다. 팽창을 낮추면 벽에 더 붙을 뿐 상대를 비켜 가지는 못한다 — 누가 먼저 갈지 정해 주는 쪽(Fleet 양보)이 있어야 한다. 그리고 `PASSING_WIDTH_M` 처럼 "여기서는 Fleet 이 빠져도 된다"를 정하는 상수는 실측 없이 낮추면 안 된다. 1.2 로 두면 폭 1.3 m 통로에서 양보를 접고 두 대 다 선다

## 2026-09-20 · uncommitted · fix(nav2): keep non-composed nodes in one robot namespace

- 변경: the parent launch group retains namespace ownership and passes an empty child namespace to localization and navigation includes, preventing `/<robot>/<robot>` node names.
- 증거: isolated exact-map runtime showed map server, AMCL, planner, controller and behavior server active under `/codex_01`; the initial-pose seed completed. Contract coverage is in `test_gz_package_contract.py`.
- gate 변화: none. Stack startup is proven, but the exact-map unattended route and device execution remain HOLD.
- 교훈: switching composition modes changes which launch scope owns the namespace; the child cannot inherit and push the same namespace again.

## 2026-09-21 · uncommitted · feat(nav): add a real-hardware SLAM backend (D-144)

- 변경: `hardware.launch.py` now selects localization or mapping without requiring an existing map in SLAM mode. The mapping bringup composes Nav2 navigation with SLAM Toolbox while preserving CORE ownership of final `cmd_vel`; mapper frame/topic parameters remain robot-namespaced.
- 증거: hardware launch contracts, frame-prefix rewrites, readiness selection, safe map paths, and G5 evidence binding pass in the Windows test suite. Container package and launch inspection also passed.
- gate 변화: SOURCE/LOCAL refreshed only. ROS-SIM and DEVICE remain HOLD until their actual runtimes are exercised.
- 결정: D-144.
- 교훈: mapping is a navigation backend, not a new runtime mode; this keeps motor/LiDAR ownership unchanged while making persistence and readiness backend-specific.

## 2026-09-22

- 변경: `map/rosy_road.pgm` + `map/rosy_road.yaml` 추가 — `260919 MAP FILE.STL`(도로 회로 평면도)을 `gz_sim/scripts/stl_to_world.py` 로 벽 박스 월드로 바꾸고 `world_to_map.py --resolution 0.02 --seed 0.48,0.64` 로 만든 정답 맵이다. 사이트 2.81 x 1.27 m, 방-로터리-상하 통로-S 커브 단일 회로, 자유 면적 2.89 m2 단일 덩어리.
- 증거: 맵 덩어리 수 1(방/통로/링 전부 연결), `world_to_map.py` 출력 free=7199 occupied=1663. 플로우 검증 이미지로 도면과 대조.
- 한계: 외곽 프레임 밖 누수 free 152 셀(0.06 m2), 벽 관절 핀홀 — inflation 이 흡수하지만 SLAM 정합 비교용으로는 보강 필요. 차로 0.10~0.20 m 는 nav2 footprint QA 전에는 미션 보증 못 한다.
- gate 변화: ROS-SIM 새 맵 입력으로는 HOLD 유지(실측 런치 전). 시나리오 문서 `docs/plans/2026-09-22-rosy-road-yield-scenarios.md`.

## 2026-09-22 · uncommitted · navigation(launch): hardware 그래프의 IR 출처 명시
- 변경: `launch/hardware.launch.py` 의 line_follow include 위에 ir_sensor/range 단일 발행 주석 추가 — 이 그래프의 IR 출처는 control ir_adc_node 뿐이며 C++ sensor_adc 노드를 본 트리에서 시작하지 않는다. 코드 변경 없음(주석).
- 증거: `test/test_ir_source_exclusivity.py` 의 hardware 케이스 포함 4 passed (2026-09-22 Windows).
- gate 변화: 없음.
- 결정: 없음.
- 교훈: 없음.

## 2026-09-23 · uncommitted · docs(adr): D-182·D-184 Proposed를 navigation에 연결

- 변경: 정책 코드의 시뮬 리터럴 금지와 동작 시험의 패키지 소유를 navigation 진행 기록에 연결했다. launch와 시험 위치는 그대로다.
- 증거: ADR 기록. 실행 시험 없음.
- gate 변화: 없음.
- 결정: D-182, D-184 Proposed
- 교훈: 없음.

## 2026-09-25 · uncommitted · refactor(runtime): move navigation under src/runtime (D-231)

- 변경: src/runtime/navigation로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 runtime 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음

## 2026-09-27 · 804dda61 · fix(mapping): scope the occupancy map to the robot namespace

- Change: remap slam_toolbox /map and /map_metadata within the SLAM launch group.
- Local evidence: mapping contract and dashboard package tests passed on main. The prior web-drive worktree recorded an independent Pinky sensor probe with explicit map remapping; this integration did not repeat that probe or deploy the changed launch file.
- Gate: SOURCE/LOCAL only. Runtime map and physical G5 acceptance remain unverified.

## 2026-09-29 · uncommitted · feat(launch): Flask 시대 web_* 진입점 4종 삭제 (스코어카드 §6 과제 3)

- 변경: web_nav2/web_slam/gz_web_nav2/gz_web_slam.launch.xml 삭제 — Flask 자리에 core FastAPI를 띄우던 전환기 진입점으로 D-3 완료 뒤 역할이 끝났다. test/test_flask_launch_removed.py는 가드를 부재 단정으로 반전했다(4파일 부재 + 어떤 navigation XML도 core나 웹서버를 시작하지 않음 + CMake Flask 설치 금지 유지). test/architecture/test_module_structure.py의 KNOWN_UNDECLARED에서 (navigation, core) 엣지를 제거했다. line_follow include는 기본 false 옵트인으로 이미 완화되어 deploy 조립로 이전은 별도 과제로 보루(사용자 결정, 축소안).
- 증거: test_flask_launch_removed 3 passed, test_module_structure KNOWN_UNDECLARED 집합 동일성 통과(신규 위반 0), test_harness_contracts 54 passed(2026-09-29 Windows).
- gate 변화: 없음.
- 결정: web 표면은 core 단일(D-3·D-23). navigation XML은 Nav2/SLAM 조립만 담당한다.
- 교훈: 삭제 반전 가드는 존재 가드보다 강하다 — 부재를 단정하면 되살아나는 순간 잡힌다.

## 2026-10-01 · uncommitted · feat(launch): hardware.launch.py에 D-395 loc_assist 옵트인 (P2-3)
- 변경: `enable_loc_assist`(기본 false)로 control의 `loc_assist.launch.py`를 namespace·use_sim_time·map과 함께 포함한다. line_follow와 같은 navigation→control include 경로(KNOWN_UNDECLARED 기존 행). `nav2_params.yaml`의 `set_initial_pose`는 바꾸지 않았다.
- 결정: 기기 기본 꺼짐 — Pi 탐색 비용 미측정, CORE 결정 중계(lane B) 전, 기기 그래프에 `safety/pickup` 발행자 없음. 근거는 sensing logs 같은 날 항목.
- 증거: `src/runtime/sensing/test/test_loc_assist_launch.py`, `test/test_line_follow_runtime.py`, `test/test_control_launch_boundary.py`, `test/test_nav2_hardware_slice.py` 통과.
- gate 변화: 없음.

## 2026-10-11 · 291d03a9f · refactor: Nav2 Drive planning holder 이전

- 변경: D-626 control/drive/planning/nav2로 이동. navigation package/CMake/launch/config/map/RViz와 standalone/composed nav_cmd_vel 후보 경로를 유지했다. Docker 소스·manifest·물리 folder identity를 정렬했다.
- 증거: Nav2/native/structure 원격 440 성공, 최종 전체 architecture/harness/Safety 272 성공, 독립 source 리뷰. known_failures 0 NEW/0 known. logs는 이동 커밋에서 R100 보존.
- gate 변화: 없음. 실제 Jazzy colcon·launch·ARM64·장치 수용은 미확인.

## 2026-10-17 · uncommitted · D-783 native 원본 지도 identity RED 준비

- 변경: 기존 Python 원본 grid 계약에서 원격 생성한 golden 7개와 C++ gtest 6건으로 signed zero·raw equal-conversion 차이·두 원본 시각·strict geometry/shape/cell limit를 검사한다. 실제 native helper는 아직 없다.
- 증거: 실행 전이다. preliminary standalone fixture는 없는 helper를 참조하므로 먼저 setup RED를 확인한다. 이 단계는 실제 AMCL/StaticLayer producer나 R3의 전체 navigation/interfaces 빌드·수용을 대체하지 않는다.
- gate 변화: 없음. D-783/승인 실행 계획을 module metadata에 연결했다. native consumer·CORE admission·ARM64/DEVICE/FIELD는 미확인이다.

## 2026-10-17 · uncommitted · native grid·실제 AMCL·설치 graph 검증 기록

- 변경: revision별 setup/동작 결과와 독립 검토 수정, SDK/생성 provenance, 남은 전역/CORE·현장 수용을 [validation](../../../../docs/validation/station-native-map-amcl-2026-10-17/result.md)에 기록했다.
- 증거: 0034827d2 승인 AI 시험 PC에서 same-SHA interfaces→navigation native 빌드, 실제 gtest grid6+AMCL10 모두 PASS/0 SKIP, 설치 standalone GetState/namespace·초기 UNCONFIGURED 및 정상 종료 PASS, exit 0. 834d6bd02 source guard는 207 PASS/1 FAIL/0 SKIP이고 해당 ancestry 검사 실패는 이전 branch cb19bf69f에서 재현되며 main 8b60af26b는 PASS다.
- gate 변화: SOURCE GO→HOLD(미완료 전역/CORE·FULL CI, branch 이력 guard 실패를 명시). LOCAL GO는 검증한 native slice에 한정한다. ROS-SIM/ARTIFACT/DEVICE HOLD·FIELD PARKED 유지, 전체 목표 ACTIVE다. 장치 재탐색/이동/토크/재시작/배포/landing/push 없음.

## 2026-10-17 · uncommitted · native canonical grid identity helper

- 변경: 전용 safety root 아래 C++ 원본 grid 검증·ROSY-GRID-v1 SHA256·두 원본 시각 identity 비교를 구현했다. float32 resolution을 double로 승격하고 little-endian/signed-zero/raw int8를 보존한다. 지원 profile은 axis-aligned map과 최대 4194304 cells다. helper는 native 처리·운행 허가를 보고하지 않는다.
- 증거: a22e7c5fb의 승인 AI 시험 PC remote_sim은 Python golden 생성과 SDK/gtest 탐지를 통과한 뒤 없는 grid.cpp에서 setup RED exit 1이었다. 실제 gtest는 실행되지 않았다. 이 source commit 후 원격 compile/6건 실행을 확인한다.
- gate 변화: 없음. native AMCL/StaticLayer producer 및 R3의 최종 native navigation build/운영·장치 수용은 여전히 남아 있다.

## 2026-10-17 · uncommitted · 거절된 native configure의 fixture 자원 정리

- 변경: 실제 parent configure 실패는 UNCONFIGURED로 돌아가지만 생성된 plugin/TF 자원은 남는다. fixture는 이 경우 lifecycle 전이를 흉내내지 않고 실제 protected on_cleanup으로 자원을 정리한 뒤 parent를 해제한다. 정상 lifecycle와 production source는 그대로다.
- 증거: 00945893a 승인 AI native compile/link·실제 plugin load, 기존 16건/설치 smoke PASS. static 앞 9건 OK 뒤 unsupported disabled profile을 실제 거절하고 parent 해제 중 멈춰 CTest 180초 timeout, synthetic missing_result 1 error다. 전체 14건 실행/통과 증거가 아니다. 이번 좁힌 fixture 수정의 재실행은 아직 전이다. 같은 source 계약 검사는 207 PASS/1 FAIL/0 SKIP이며 기존 branch exception ancestry 실패가 유지된다.
- gate 변화: 없음. production 거절 후 운영 supervisor의 부분 구성 정리도 runtime factory 연결에서 별도로 다룬다.

## 2026-10-17 · uncommitted · 고정 costmap SDK의 exported target include 경로 사용

- 변경: SDK header 탐색에 실제 설치된 `nav2_costmap_2d::nav2_costmap_2d_core`의 INTERFACE_INCLUDE_DIRECTORIES를 추가했다. 기존 SHA pin은 유지하며 CMakeCache도 실패 artifact로 보존한다.
- 증거: 834d6bd02 최초 native 요청은 headroom 부족으로 미실행이었다. 승인 AI 시험 PC의 재요청은 interfaces/wire를 통과한 뒤 static header 탐색에서 실패했다. 읽기 전용 SDK 확인으로 header 존재·기존 SHA 일치와 exported core target의 정확한 include 경로를 확인했다. native 컴파일/10건 실행은 아직 미실행이다.
- gate 변화: 없음. source guard 원격 결과는 207 PASS/1 FAIL/0 SKIP이며 safety 예외 commit ancestry 한 건이다. 같은 검사는 수정하지 않은 main 8b60af26b에서 1 PASS, 이번 native 변경 이전 branch baseline cb19bf69f에서 1 FAIL이다. branch의 기존 이력 문제로 분리하며 현재 검사 전체 통과를 주장하지 않는다.

## 2026-10-17 · uncommitted · rejected configure 시험의 실제 TF callback 시작 동기화

- 변경: configure 직후 고유 map→base TF가 실제 parent buffer에 수신됐음을 확인하고 정리한다. 고정 sleep·내부 flag 쓰기·fake callback 없이 listener thread의 실제 실행을 확인하는 fixture 조건이며 production source는 바꾸지 않는다.
- 증거: f05023d376의 gdb-started 단독 거절 시험은 통과해 hang을 재현하지 못했다. 이어 debugger 없이 시작한 자기 시험 child가 멈춘 뒤 같은 parent PID에서 attach한 bounded 진단은 main의 TransformListener destructor→thread.join과 해당 worker의 Executor::wait_for_work/SingleThreadedExecutor::spin을 확인했다. 진단 child만 종료했고 ptrace 정책·현장 장치는 변경하지 않았다. 이 diagnostic exit0는 시험 수용이 아니다. 이번 fixture 수정은 아직 재실행 전이다.
- gate 변화: 없음. 즉시 생성된 listener의 시작/취소 경계에 관한 fixture 동기화이며, 운영 rejected-config 정리 해결이나 전체14건 통과를 주장하지 않는다.

## 2026-10-17 · uncommitted · 실제 AMCL producer RED 준비

- 변경: 실제 AMCL 클래스/DDS 지도·readback service를 쓰는 9개 native gtest와 같은 SHA interfaces→navigation opt-in 빌드/실행 경로를 추가했다. native 호출/실제 cells를 읽는 inspector는 consumer를 대체하지 않는다.
- 증거: canonical helper 8f749b1f9는 AI 시험 PC에서 compile/link 및 실제 gtest 6 PASS/0 FAIL/0 SKIP, remote_sim exit 0이다. AMCL producer/header/opt-in은 아직 없으므로 새 9건은 실행 전이며 setup 부재 RED를 먼저 확인한다.
- gate 변화: 없음. canonical helper는 지도 채택 ACK가 아니다. 실제 AMCL/StaticLayer 채택·CORE admission·물리 수용은 계속 미확인이다.

## 2026-10-17 · uncommitted · lifecycle SDK pin을 실제 Linux 원본 바이트로 교정

- 변경: 추가 lifecycle header pin이 Windows 캐시의 CRLF hash였던 오류를 교정했다. 기존 R3의 5개 pin/version은 유지한다.
- 증거: 6c918813c의 bounded placement 재요청 1은 미실행, 2는 실제 시작해 기존 5개 pin을 통과한 뒤 추가 lifecycle pin에서 실패했다. 읽기 전용 SDK 확인으로 model/AI의 Linux 원본 hash가 모두 1fedfbcc…이고 캐시와 줄끝 정규화 후 동일함을 확인했다. 실제 compile/native gtest는 아직 도달하지 않았다.
- gate 변화: 없음. 임의 SDK 허용이나 pin 우회 없이 실제 승인 SDK 바이트를 사용한다. 새 source revision으로 native 검증을 다시 요청한다.

## 2026-10-17 · uncommitted · 실제 static14건과 같은 SHA native30건 수용 기록

- 변경: 실제 전역 plugin·원본 full application/reset/retire와 fixture 정리/TF 동기화의 revision별 실패·진단·최종 검증을 [validation](../../../../docs/validation/station-native-map-static-2026-10-17/result.md)에 기록했다.
- 증거: 83db3b1da4 승인 AI 시험 PC에서 같은 SHA interfaces/native navigation 생성·compile/link, 실제 gtest grid6+AMCL10+static14=30 PASS/0 FAIL/0 ERROR/0 SKIP, 설치 AMCL 초기 graph/정상 종료 별도 PASS, exit0. source-sha/exit-code/세 XML을 직접 확인했다. source00945893a5 guard207 PASS/1 FAIL/0 SKIP/NEW1은 기존 branch exception ancestry 한 건이다.
- gate 변화: LOCAL GO는 검증한 native slice로 갱신한다. SOURCE HOLD(CORE 연결·운영 failed-config 정리·FULL CI·branch guard), ROS-SIM/ARTIFACT/DEVICE HOLD·FIELD PARKED를 유지한다. 현장 담당자는 나중에 확인 가능하며 전체 목표 ACTIVE다.

## 2026-10-17 · uncommitted · 설치된 standalone AMCL의 실제 기본 graph 검사 추가

- 변경: R3의 실제 설치 executable/기본 node graph 조건을 검사한다. 승인된 remote_sim의 격리 domain에서 설치 binary를 실행하고 실제 GetState service와 namespace, 초기 UNCONFIGURED와 해당 node의 velocity publisher 부재를 확인한 뒤 자신이 시작한 process만 종료한다.
- 증거: 새 검사는 아직 실행 전이다. 1f2b0f1e8의 context 수정본 원격 요청은 고정 SHA로 headroom 재시도 중이며 재시작하지 않았다. 이 검사는 이후 revision의 별도 native 실행에 포함한다.
- gate 변화: 없음. 초기 UNCONFIGURED graph는 실제 localization·접안·운영 admission 증거가 아니며 device를 구성/활성화하지 않는다.

## 2026-10-17 · uncommitted · 실제 global StaticLayer application RED 준비

- 변경: 실제 Costmap2DROS가 production plugin을 load하고 DDS 지도/readback, full/partial native application·reset/resize·clear service·footprint·callback 정리·profile 거절을 검사하는 14개 native 회귀와 원격 검증 경로를 추가했다. read-only test inspector만 callback/native 처리 수를 읽는다.
- 증거: 아직 실행 전이다. 새 plugin/등록/test target이 없는 현재 source에서 setup 부재 RED를 먼저 확인한다. 기존 16건과 설치 AMCL graph를 먼저 확인하고 static XML의 실제 14건·실패/skip 부재를 요구한다.
- gate 변화: 없음. 전역 static source·CORE/admission·실기 수용을 아직 입증하지 않는다.

## 2026-10-17 · uncommitted · opt-in 실제 AMCL original-map owner

- 변경: 기본 OFF native opt-in에 고정 SDK 검증과 standalone AMCL owner를 추가했다. 최초 subscription부터 private callback group이 소유하고 실제 handleMapMessage/원본 cells·geometry 확인 후에만 채택을 기록한다. 다른 raw/시각은 native 변경 전 instance를 폐기한다. 전체 parameter transaction을 pre-set에서 거절하고 비활성화/정리/파괴 전 폐기 및 executor join을 수행한다. 원본/instance/generation/build/config를 내부 readback으로 반환한다.
- 증거: 5d4b074a0의 remote_sim은 same-SHA interfaces/wire 생성·직렬화를 통과한 뒤 navigation이 아직 선언하지 않은 opt-in을 사용하지 않아 setup RED exit 1이었다. AMCL 9건은 미실행이다. 독립 source 검토에서 config 표시 문자열의 정밀도 손실과 cleanup race 검증 부재를 발견해 typed binary config/정밀도 회귀 및 실제 callback barrier로 보완했다. source commit 후 실제 고정 SDK 빌드/DDS/native 10건 및 grid 6건을 실행한다.
- gate 변화: 없음. 일반 launch는 유지하며 verified component를 등록하지 않는다. 전역 StaticLayer/CORE/운영 factory·전체 충전 주기·장치 수용은 아직 없다. upstream에서 각색한 wiring의 LGPL 고지/원문을 보존한다.

## 2026-10-17 · uncommitted · 첫 원본 지도의 실제 static application 소유자 구현

- 변경: pinned StaticLayer를 상속하고 첫 DDS 구독부터 원본을 보관한다. 실제 processMap 이후에도 pending이며 actual parent ACTIVE·fresh bounds·일치하는 전체 master window에 base updateCosts가 적용한 경우만 확인한다. master→layer 잠금, reset의 새 generation, 외부 resize/지도 변경의 영구 retire, 전체 parameter transaction freeze, private group/parent 정리 경계를 따른다. 기본 OFF opt-in에 plugin 등록/native 시험을 연결하고 upstream BSD 고지를 보존했다.
- 증거: 시험 전용 86c0e72da7의 승인 AI 원격 실행은 같은 SHA interface/native 빌드·기존 16건/설치 AMCL smoke PASS 후 static target/XML 부재로 exit 1이었다. 실제 static 동작 0건의 setup RED다. 새 source는 아직 compile·14건 실행 전이며 독립 검토 중이다.
- gate 변화: 없음. 확인 응답은 원본 static contribution만 기술하며 최종 inflated costmap/위치 수렴/로봇 geometry/이동 권한이 아니다. CORE·전체 lifecycle·현장 수용은 남아 있다.

## 2026-10-17 · uncommitted · native AMCL fixture의 ROS context 초기화 순서 교정

- 변경: 실제 gtest Environment에서 ROS context를 먼저 초기화하고 마지막에 종료한다. Harness의 executor 멤버가 생성된 뒤 constructor body에서 init하던 fixture 오류를 고쳤다. production source는 바꾸지 않았다.
- 증거: 834ba0a9d는 6개 SDK pin·same-SHA 빌드/provenance 및 C++ compile/link를 통과했다. 실제 gtest 총 16건 중 grid 6건과 typed config 1건 PASS, AMCL Harness 9건은 context-null guard condition 생성에서 실패했다. 이는 AMCL 동작 반례 9건이 아니며 source 직렬화 wire 검사와 분리한다.
- gate 변화: 없음. fixture만 수정한 revision에서 native 16건을 재실행한다. AMCL 채택·CORE/StaticLayer 및 실기 수용은 아직 입증되지 않았다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) D-783 native 원본 지도 identity RED 준비

- 변경: 기존 Python 원본 grid 계약에서 원격 생성한 golden 7개와 C++ gtest 6건으로 signed zero·raw equal-conversion 차이·두 원본 시각·strict geometry/shape/cell limit를 검사한다. 실제 native helper는 아직 없다.
- 증거: 실행 전이다. preliminary standalone fixture는 없는 helper를 참조하므로 먼저 setup RED를 확인한다. 이 단계는 실제 AMCL/StaticLayer producer나 R3의 전체 navigation/interfaces 빌드·수용을 대체하지 않는다.
- gate 변화: 없음. D-783/승인 실행 계획을 module metadata에 연결했다. native consumer·CORE admission·ARM64/DEVICE/FIELD는 미확인이다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native canonical grid identity helper

- 변경: 전용 safety root 아래 C++ 원본 grid 검증·ROSY-GRID-v1 SHA256·두 원본 시각 identity 비교를 구현했다. float32 resolution을 double로 승격하고 little-endian/signed-zero/raw int8를 보존한다. 지원 profile은 axis-aligned map과 최대 4194304 cells다. helper는 native 처리·운행 허가를 보고하지 않는다.
- 증거: a22e7c5fb의 승인 AI 시험 PC remote_sim은 Python golden 생성과 SDK/gtest 탐지를 통과한 뒤 없는 grid.cpp에서 setup RED exit 1이었다. 실제 gtest는 실행되지 않았다. 이 source commit 후 원격 compile/6건 실행을 확인한다.
- gate 변화: 없음. native AMCL/StaticLayer producer 및 R3의 최종 native navigation build/운영·장치 수용은 여전히 남아 있다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 실제 AMCL producer RED 준비

- 변경: 실제 AMCL 클래스/DDS 지도·readback service를 쓰는 9개 native gtest와 같은 SHA interfaces→navigation opt-in 빌드/실행 경로를 추가했다. native 호출/실제 cells를 읽는 inspector는 consumer를 대체하지 않는다.
- 증거: canonical helper 8f749b1f9는 AI 시험 PC에서 compile/link 및 실제 gtest 6 PASS/0 FAIL/0 SKIP, remote_sim exit 0이다. AMCL producer/header/opt-in은 아직 없으므로 새 9건은 실행 전이며 setup 부재 RED를 먼저 확인한다.
- gate 변화: 없음. canonical helper는 지도 채택 ACK가 아니다. 실제 AMCL/StaticLayer 채택·CORE admission·물리 수용은 계속 미확인이다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) opt-in 실제 AMCL original-map owner

- 변경: 기본 OFF native opt-in에 고정 SDK 검증과 standalone AMCL owner를 추가했다. 최초 subscription부터 private callback group이 소유하고 실제 handleMapMessage/원본 cells·geometry 확인 후에만 채택을 기록한다. 다른 raw/시각은 native 변경 전 instance를 폐기한다. 전체 parameter transaction을 pre-set에서 거절하고 비활성화/정리/파괴 전 폐기 및 executor join을 수행한다. 원본/instance/generation/build/config를 내부 readback으로 반환한다.
- 증거: 5d4b074a0의 remote_sim은 same-SHA interfaces/wire 생성·직렬화를 통과한 뒤 navigation이 아직 선언하지 않은 opt-in을 사용하지 않아 setup RED exit 1이었다. AMCL 9건은 미실행이다. 독립 source 검토에서 config 표시 문자열의 정밀도 손실과 cleanup race 검증 부재를 발견해 typed binary config/정밀도 회귀 및 실제 callback barrier로 보완했다. source commit 후 실제 고정 SDK 빌드/DDS/native 10건 및 grid 6건을 실행한다.
- gate 변화: 없음. 일반 launch는 유지하며 verified component를 등록하지 않는다. 전역 StaticLayer/CORE/운영 factory·전체 충전 주기·장치 수용은 아직 없다. upstream에서 각색한 wiring의 LGPL 고지/원문을 보존한다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 고정 costmap SDK의 exported target include 경로 사용

- 변경: SDK header 탐색에 실제 설치된 `nav2_costmap_2d::nav2_costmap_2d_core`의 INTERFACE_INCLUDE_DIRECTORIES를 추가했다. 기존 SHA pin은 유지하며 CMakeCache도 실패 artifact로 보존한다.
- 증거: 834d6bd02 최초 native 요청은 headroom 부족으로 미실행이었다. 승인 AI 시험 PC의 재요청은 interfaces/wire를 통과한 뒤 static header 탐색에서 실패했다. 읽기 전용 SDK 확인으로 header 존재·기존 SHA 일치와 exported core target의 정확한 include 경로를 확인했다. native 컴파일/10건 실행은 아직 미실행이다.
- gate 변화: 없음. source guard 원격 결과는 207 PASS/1 FAIL/0 SKIP이며 safety 예외 commit ancestry 한 건이다. 같은 검사는 수정하지 않은 main 8b60af26b에서 1 PASS, 이번 native 변경 이전 branch baseline cb19bf69f에서 1 FAIL이다. branch의 기존 이력 문제로 분리하며 현재 검사 전체 통과를 주장하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) lifecycle SDK pin을 실제 Linux 원본 바이트로 교정

- 변경: 추가 lifecycle header pin이 Windows 캐시의 CRLF hash였던 오류를 교정했다. 기존 R3의 5개 pin/version은 유지한다.
- 증거: 6c918813c의 bounded placement 재요청 1은 미실행, 2는 실제 시작해 기존 5개 pin을 통과한 뒤 추가 lifecycle pin에서 실패했다. 읽기 전용 SDK 확인으로 model/AI의 Linux 원본 hash가 모두 1fedfbcc…이고 캐시와 줄끝 정규화 후 동일함을 확인했다. 실제 compile/native gtest는 아직 도달하지 않았다.
- gate 변화: 없음. 임의 SDK 허용이나 pin 우회 없이 실제 승인 SDK 바이트를 사용한다. 새 source revision으로 native 검증을 다시 요청한다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native AMCL fixture의 ROS context 초기화 순서 교정

- 변경: 실제 gtest Environment에서 ROS context를 먼저 초기화하고 마지막에 종료한다. Harness의 executor 멤버가 생성된 뒤 constructor body에서 init하던 fixture 오류를 고쳤다. production source는 바꾸지 않았다.
- 증거: 834ba0a9d는 6개 SDK pin·same-SHA 빌드/provenance 및 C++ compile/link를 통과했다. 실제 gtest 총 16건 중 grid 6건과 typed config 1건 PASS, AMCL Harness 9건은 context-null guard condition 생성에서 실패했다. 이는 AMCL 동작 반례 9건이 아니며 source 직렬화 wire 검사와 분리한다.
- gate 변화: 없음. fixture만 수정한 revision에서 native 16건을 재실행한다. AMCL 채택·CORE/StaticLayer 및 실기 수용은 아직 입증되지 않았다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 설치된 standalone AMCL의 실제 기본 graph 검사 추가

- 변경: R3의 실제 설치 executable/기본 node graph 조건을 검사한다. 승인된 remote_sim의 격리 domain에서 설치 binary를 실행하고 실제 GetState service와 namespace, 초기 UNCONFIGURED와 해당 node의 velocity publisher 부재를 확인한 뒤 자신이 시작한 process만 종료한다.
- 증거: 새 검사는 아직 실행 전이다. 1f2b0f1e8의 context 수정본 원격 요청은 고정 SHA로 headroom 재시도 중이며 재시작하지 않았다. 이 검사는 이후 revision의 별도 native 실행에 포함한다.
- gate 변화: 없음. 초기 UNCONFIGURED graph는 실제 localization·접안·운영 admission 증거가 아니며 device를 구성/활성화하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) native grid·실제 AMCL·설치 graph 검증 기록

- 변경: revision별 setup/동작 결과와 독립 검토 수정, SDK/생성 provenance, 남은 전역/CORE·현장 수용을 [validation](../../../../docs/validation/station-native-map-amcl-2026-10-17/result.md)에 기록했다.
- 증거: 0034827d2 승인 AI 시험 PC에서 same-SHA interfaces→navigation native 빌드, 실제 gtest grid6+AMCL10 모두 PASS/0 SKIP, 설치 standalone GetState/namespace·초기 UNCONFIGURED 및 정상 종료 PASS, exit 0. 834d6bd02 source guard는 207 PASS/1 FAIL/0 SKIP이고 해당 ancestry 검사 실패는 이전 branch cb19bf69f에서 재현되며 main 8b60af26b는 PASS다.
- gate 변화: SOURCE GO→HOLD(미완료 전역/CORE·FULL CI, branch 이력 guard 실패를 명시). LOCAL GO는 검증한 native slice에 한정한다. ROS-SIM/ARTIFACT/DEVICE HOLD·FIELD PARKED 유지, 전체 목표 ACTIVE다. 장치 재탐색/이동/토크/재시작/배포/landing/push 없음.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 실제 global StaticLayer application RED 준비

- 변경: 실제 Costmap2DROS가 production plugin을 load하고 DDS 지도/readback, full/partial native application·reset/resize·clear service·footprint·callback 정리·profile 거절을 검사하는 14개 native 회귀와 원격 검증 경로를 추가했다. read-only test inspector만 callback/native 처리 수를 읽는다.
- 증거: 아직 실행 전이다. 새 plugin/등록/test target이 없는 현재 source에서 setup 부재 RED를 먼저 확인한다. 기존 16건과 설치 AMCL graph를 먼저 확인하고 static XML의 실제 14건·실패/skip 부재를 요구한다.
- gate 변화: 없음. 전역 static source·CORE/admission·실기 수용을 아직 입증하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 첫 원본 지도의 실제 static application 소유자 구현

- 변경: pinned StaticLayer를 상속하고 첫 DDS 구독부터 원본을 보관한다. 실제 processMap 이후에도 pending이며 actual parent ACTIVE·fresh bounds·일치하는 전체 master window에 base updateCosts가 적용한 경우만 확인한다. master→layer 잠금, reset의 새 generation, 외부 resize/지도 변경의 영구 retire, 전체 parameter transaction freeze, private group/parent 정리 경계를 따른다. 기본 OFF opt-in에 plugin 등록/native 시험을 연결하고 upstream BSD 고지를 보존했다.
- 증거: 시험 전용 86c0e72da7의 승인 AI 원격 실행은 같은 SHA interface/native 빌드·기존 16건/설치 AMCL smoke PASS 후 static target/XML 부재로 exit 1이었다. 실제 static 동작 0건의 setup RED다. 새 source는 아직 compile·14건 실행 전이며 독립 검토 중이다.
- gate 변화: 없음. 확인 응답은 원본 static contribution만 기술하며 최종 inflated costmap/위치 수렴/로봇 geometry/이동 권한이 아니다. CORE·전체 lifecycle·현장 수용은 남아 있다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 거절된 native configure의 fixture 자원 정리

- 변경: 실제 parent configure 실패는 UNCONFIGURED로 돌아가지만 생성된 plugin/TF 자원은 남는다. fixture는 이 경우 lifecycle 전이를 흉내내지 않고 실제 protected on_cleanup으로 자원을 정리한 뒤 parent를 해제한다. 정상 lifecycle와 production source는 그대로다.
- 증거: 00945893a 승인 AI native compile/link·실제 plugin load, 기존 16건/설치 smoke PASS. static 앞 9건 OK 뒤 unsupported disabled profile을 실제 거절하고 parent 해제 중 멈춰 CTest 180초 timeout, synthetic missing_result 1 error다. 전체 14건 실행/통과 증거가 아니다. 이번 좁힌 fixture 수정의 재실행은 아직 전이다. 같은 source 계약 검사는 207 PASS/1 FAIL/0 SKIP이며 기존 branch exception ancestry 실패가 유지된다.
- gate 변화: 없음. production 거절 후 운영 supervisor의 부분 구성 정리도 runtime factory 연결에서 별도로 다룬다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) rejected configure 시험의 실제 TF callback 시작 동기화

- 변경: configure 직후 고유 map→base TF가 실제 parent buffer에 수신됐음을 확인하고 정리한다. 고정 sleep·내부 flag 쓰기·fake callback 없이 listener thread의 실제 실행을 확인하는 fixture 조건이며 production source는 바꾸지 않는다.
- 증거: f05023d376의 gdb-started 단독 거절 시험은 통과해 hang을 재현하지 못했다. 이어 debugger 없이 시작한 자기 시험 child가 멈춘 뒤 같은 parent PID에서 attach한 bounded 진단은 main의 TransformListener destructor→thread.join과 해당 worker의 Executor::wait_for_work/SingleThreadedExecutor::spin을 확인했다. 진단 child만 종료했고 ptrace 정책·현장 장치는 변경하지 않았다. 이 diagnostic exit0는 시험 수용이 아니다. 이번 fixture 수정은 아직 재실행 전이다.
- gate 변화: 없음. 즉시 생성된 listener의 시작/취소 경계에 관한 fixture 동기화이며, 운영 rejected-config 정리 해결이나 전체14건 통과를 주장하지 않는다.

## 2026-10-19 · uncommitted · (origin #92 2026-10-17) 실제 static14건과 같은 SHA native30건 수용 기록

- 변경: 실제 전역 plugin·원본 full application/reset/retire와 fixture 정리/TF 동기화의 revision별 실패·진단·최종 검증을 [validation](../../../../docs/validation/station-native-map-static-2026-10-17/result.md)에 기록했다.
- 증거: 83db3b1da4 승인 AI 시험 PC에서 같은 SHA interfaces/native navigation 생성·compile/link, 실제 gtest grid6+AMCL10+static14=30 PASS/0 FAIL/0 ERROR/0 SKIP, 설치 AMCL 초기 graph/정상 종료 별도 PASS, exit0. source-sha/exit-code/세 XML을 직접 확인했다. source00945893a5 guard207 PASS/1 FAIL/0 SKIP/NEW1은 기존 branch exception ancestry 한 건이다.
- gate 변화: LOCAL GO는 검증한 native slice로 갱신한다. SOURCE HOLD(CORE 연결·운영 failed-config 정리·FULL CI·branch guard), ROS-SIM/ARTIFACT/DEVICE HOLD·FIELD PARKED를 유지한다. 현장 담당자는 나중에 확인 가능하며 전체 목표 ACTIVE다.
