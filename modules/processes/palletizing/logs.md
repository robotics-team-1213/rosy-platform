# palletizing logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.

## 2026-10-02 · 9da93450 · refactor: extract palletizing process with legacy imports

- 변경: 기존 Recipe/Cell/배치/적층/순서/Job 구현의 단일 정본을 `modules/processes/palletizing`으로 옮겼다. `rosy_cell`은 같은 타입·함수를 재수출한다. Job의 pick/place 쌍은 버전이 지정된 `pallet.transfer` PlanStep 하나로 바꾸고 `pallet_done`은 실행 스킬이 아닌 사이트 원장 표지로 보존한다.
- 증거: `rosy-palletizing` wheel SHA-256 `d915fae9793b46696954e4f7cc94a0fb8556ac3f47ffc921951c20360834c35a`; 설치 wheel 호환 11 passed, 기존 Cell 143 passed, Task 2 계약 매핑 7 passed, architecture 81 passed/1 skipped, combined cell/compat 154 passed. wheel 없는 환경에서 레거시 import 실패를 확인하고 설치 후 복구했다. known-failure 비교 0 new/0 known.
- gate 변화: SOURCE GO; ROS-SIM·ARTIFACT는 후속 검증 전 HOLD.

## 2026-10-02 · d9e70f71 · docs(test): refresh Task 3 evidence after latest-main sync

- 변경: main `cc76161f5` 통합 뒤 Task 3 검증 요약과 남은 gate를 갱신했다.
- 증거: 비선별 architecture suite 81 passed/1 skipped, quick tier 95 passed/24 기존 warnings. 두 known-failure 비교 모두 0 new/0 known; Wheel compatibility 11, Cell 143, 계약 매핑 7 passed.
- 경계: 이전 main에서 드러난 Fleet size-verdict budget 불일치는 후속 main 변경으로 해소됐다. ROS/Gazebo, 배포 artifact, 장치/현장 실행은 여전히 검증하지 않았다.
- gate 변화: SOURCE GO 유지; ROS-SIM·ARTIFACT HOLD, DEVICE·FIELD PARKED 유지.

## 2026-10-02 · c07896af · feat(palletizing): port C3b grasp depth and tool fingertip overhang (merge)

- 변경: C3b가 `rosy_cell`에 넣은 로직을 정본 모듈로 옮겼다(`cell.py`, `compiler.py`, `load.py`, `recipe.py`). `rosy_cell/*`는 main의 facade 그대로다. 옮긴 내용: 레시피 `box.grasp_depth`(0 ≤ d < height), `cell.yaml` 필수 `fingertip_overhang_m`, 상자 Step `target.z` = 윗면 − 깊이, `carry_z` 매달린 높이 = max(height − grasp_depth, 슬립시트, overhang), `grasp_depth > height − overhang` 컴파일 거절. `plan_bundle.py`는 Job을 다시 컴파일해 비교하므로 바뀐 Step z와 carry_z를 그대로 따른다. 새 skill 입력은 없다. 장치는 폭·깊이를 수락한 레시피 hash로 조회한다(D-402 보강).
- 증거: `test/test_platform_palletizing_compat.py` 14 passed(새 3개: 모듈의 깊이·overhang·carry_z, fingertip 거절, plan bundle 재컴파일). 기존 Cell 155 passed. 실행 경로는 설치 wheel 대신 `PYTHONPATH=modules/execution/src;modules/processes/palletizing/src;modules/world/src;modules/skills/api/src`.
- gate 변화: SOURCE GO 유지(wheel은 다시 빌드하지 않았다. ARTIFACT HOLD 그대로).
- 결정: `fingertip_overhang_m`는 `rosy_cell.cell/2`의 필수 필드가 됐다. 버전은 올리지 않았다. /2는 아직 배포되지 않았고 이 브랜치 밖에서 쓰인 적이 없기 때문이다.
