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

