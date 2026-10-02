# rosy_cell logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-10-01 · uncommitted · feat(cell): rosy_cell package scaffold

- 변경: ament_python 패키지 `rosy_cell`(`src/site/cell`), schema id 상수.
- 증거: `python -m pytest src/site/cell/test -q` 1 passed
- gate 변화: SOURCE HOLD 시작.

## 2026-10-01 · 014acdf6 · feat(cell): rosy_cell 코어와 리뷰 수정

- 변경: ROS-free 코어 모듈 `geometry`(3점 Frame, `from_base`), `load`(Box, Pallet), `pattern`(grid, split, mirrored), `stack`(층, 슬립 시트), `sequence`(먼 쪽 우선 순서), `fields`(필드 이름을 밝히는 타입 읽기), `recipe`, `cell`, `compiler`(Job of `pick`/`place`/`pallet_done` Step, 로봇 베이스 좌표).
- 리뷰 수정: 레시피 `approach` 삭제, 적재 순서는 티칭한 팔레트 좌표계에서 로봇 베이스로부터 먼 박스부터; 디팔레타이즈는 팔레트 순서까지 역순; `split_block` 빈 방향 열 제외; NaN/inf·bool·문자열 숫자·큰 정수·잘못된 컨테이너·모르는 키를 `RecipeError`/`CellError`로 거절하고 문제를 모아 보고; 슬립 시트 두께 양수; 중복 팔레트 좌표계 거절; `max_tilt_deg: 0` 허용; 로봇 베이스가 팔레트 바닥 영역 안이면 컴파일 거절; `CellConfig` 매핑 읽기 전용; 해시가 파싱 값 기준(0 ≠ 0.0)임을 문서화. D-401 갱신.
- 증거: `python -m pytest src/site/cell/test -q -p no:cacheprovider` 123 passed; `test/architecture` 76 passed 1 skipped, `known_failures` 0 new; harness lint 0 error(s). Windows, ROS-free; Motion Intent, IK, 도달성 없음.
- gate 변화: SOURCE HOLD → GO.

## 2026-10-01 · c0900cff · feat(cell): rosy_cell.cell/2 with home and kinematics_revision, compiler.carry_z

- 변경: schema `rosy_cell.cell/2`. 필수 `home`(수직하향 TCP 포즈 x/y/z/yaw)와 `kinematics_revision`; `/1`은 `schema` 문제로 거절(조용한 업그레이드 없음). `Pose`를 `cell.py`로 옮기고 compiler가 다시 내보낸다. `CellConfig.home`, `.kinematics_revision`은 내용 해시에 들어간다. `compiler.carry_z(recipe, cell)` = 모든 팔레트 전체 적재 높이(네 모서리를 팔레트 좌표계로 base z 변환, 기울기 반영)와 레시피가 쓰는 스테이션 z 중 최댓값 + 박스 높이 + `approach_clearance_m`; home은 제외. `Job.carry_z` 추가, 모든 Step의 `approach_z <= carry_z`를 CompileError로 확인. 픽스처 `cell_demo.yaml`을 /2로.
- 증거: `python -m pytest src/site/cell/test -q -p no:cacheprovider` 140 passed. 손 계산: 스택 상단 0.042 + 박스 0.02 + 여유 0.05 = 0.112.
- gate 변화: SOURCE GO 유지(증거 123 -> 140).

## 2026-10-01 · 13614bc0 · fix(cell): carry_z runs the compile checks, reject padded kinematics_revision

- 변경: `carry_z(recipe, cell, *, tol_m)`가 `_check`를 먼저 돌려 알 수 없는 frame/station을 KeyError 대신 CompileError로 거절한다(`compile_job`은 `_check`를 한 번만 실행). 앞뒤 공백이 있는 `kinematics_revision`은 CellError. D-401 §2에 `cell/2` 안내 한 줄.
- 증거: `python -m pytest src/site/cell/test -q -p no:cacheprovider` 143 passed; harness lint 0 error(s).
- gate 변화: SOURCE GO 유지(증거 140 -> 143).

## 2026-10-02 · 9da93450 · refactor: extract palletizing process with legacy imports

- Change: Recipe/Cell/Job source moved to the `modules/processes/palletizing` wheel. Existing `rosy_cell` imports only re-export canonical types and functions.
- Evidence: installed wheel compatibility 11 passed; Cell suite 143 passed. SOURCE remains GO. No MoveIt/IK, Motion Intent, or reachability behavior was added.
- Gate: SOURCE GO; ROS-SIM remains HOLD.

## 2026-10-02 · 52ef7f91 · feat(cell): OMX sim demo cell/recipe for C3

- 변경: `examples/omx_sim/cell.yaml`(cell/2, home (0.12, 0, 0.12), 프로필과 같은 `kinematics_revision`)과 `recipe.yaml`(2 팔레트 × 2층 × 4블록 40×30×30 mm 20 g + 슬립시트 2장, grid, gap 15 mm). 저장소 루트 `test/test_cell_omx_sim_layout_contract.py`가 Job 18 transfer 전부를 OMX 해석 플래너로 계획하고 Gazebo 월드 포즈와 대조한다(rosy_cell과 omx_adapter는 서로 import하지 않는다).
- 증거: layout contract 6 passed(변이 확인: 슬립시트 z 0.002, 월드 팔레트 x +0.01 각각 실패); cell suite 143 passed.
- gate 변화: ROS-SIM HOLD 유지(C3 증거 추가, C6 아님).
- 결정: D-402 §5 도달 실측, D-403 §2.
- 교훈: Step z는 물건 윗면인데 OMX-F TCP는 손가락 끝이라 파지 깊이를 실을 자리가 필요하다(C4). 탁자 위 슬립시트(z 0.002)는 프로필 TCP 바닥 0.005 아래라 거절된다.

## 2026-10-02 · a31ebde1 · feat(cell): per-item grasp_depth (C3b B1)

- 변경: 레시피 `box.grasp_depth`(선택, 0 ≤ d < height, 없으면 0 = 윗면). 상자 Step `target.z` = 윗면 − `grasp_depth`, `approach_z` = 윗면 + clearance, `carry_z` 매달린 높이 = max(`height − grasp_depth`, 슬립시트 두께). 데모 레시피 15 mm. C3b B3(cb58f71f)에서 데모 인피드 yaw를 π/2로 돌렸다(cell.yaml·두 월드).
- 증거: cell suite 150 passed(새 시험: 깊이만큼 낮은 상자 Step, 같은 approach_z, carry_z = 0.042 + 0.012 + 0.05, 슬립시트가 더 두꺼우면 그것이 매달린 높이); layout contract 5 passed(상자 transfer 전부 계획, 슬립시트는 `GRIPPER_WIDTH_INVALID`).
- gate 변화: 없음. ROS-SIM은 omx_adapter의 C3b 단일 transfer 증거.
- 결정: D-401 보강(2026-10-02, C3b). 깊이는 셀 공구가 아니라 물건에 둔다.
- 교훈: 레시피 gap 15 mm(20 mm도)는 Gazebo의 실제 손가락 폭보다 좁아, 층을 채우면 나중 배치가 이웃을 민다. gap 검증에 공구 폭이 들어가야 한다(C4/C6).
