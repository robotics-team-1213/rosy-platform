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
