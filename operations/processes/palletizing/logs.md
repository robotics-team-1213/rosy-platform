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

## 2026-10-02 · uncommitted · feat(process): include taught home pose in transfer plan

- 변경: 각 `pallet.transfer/1.0.0` invocation에 셀의 robot-base `home_pose_base`를 포함해 D-403 Fleet grant가 현재 Cell 설정만으로 home/pick/place를 구성할 수 있게 했다.
- 증거: 재빌드한 `rosy-palletizing` wheel SHA-256 `86d3a46e17ebac9c944bd61cf189bc3f45ef2209bdf280511f6988305b908dfe`; 설치 wheel로 palletizing compatibility와 Cell submission 시험 17 passed.
- gate 변화: SOURCE GO 유지; 장치 실행·ROS-SIM·artifact/device/field 상태는 바꾸지 않았다.

## 2026-10-02 · c07896af · feat(palletizing): port C3b grasp depth and tool fingertip overhang (merge)

- 변경: C3b가 `rosy_cell`에 넣은 로직을 정본 모듈로 옮겼다(`cell.py`, `compiler.py`, `load.py`, `recipe.py`). `rosy_cell/*`는 main의 facade 그대로다. 옮긴 내용: 레시피 `box.grasp_depth`(0 ≤ d < height), `cell.yaml` 필수 `fingertip_overhang_m`, 상자 Step `target.z` = 윗면 − 깊이, `carry_z` 매달린 높이 = max(height − grasp_depth, 슬립시트, overhang), `grasp_depth > height − overhang` 컴파일 거절. `plan_bundle.py`는 Job을 다시 컴파일해 비교하므로 바뀐 Step z와 carry_z를 그대로 따른다. 새 skill 입력은 없다. 장치는 폭·깊이를 수락한 레시피 hash로 조회한다(D-402 보강).
- 증거: `test/test_platform_palletizing_compat.py` 14 passed(새 3개: 모듈의 깊이·overhang·carry_z, fingertip 거절, plan bundle 재컴파일). 기존 Cell 155 passed. 실행 경로는 설치 wheel 대신 `PYTHONPATH=modules/execution/src;modules/processes/palletizing/src;modules/world/src;modules/skills/api/src`.
- gate 변화: SOURCE GO 유지(wheel은 다시 빌드하지 않았다. ARTIFACT HOLD 그대로).
- 결정: `fingertip_overhang_m`는 `rosy_cell.cell/2`의 필수 필드가 됐다. 버전은 올리지 않았다. /2는 아직 배포되지 않았고 이 브랜치 밖에서 쓰인 적이 없기 때문이다.

## 2026-10-02 · uncommitted · feat(palletizing): `job_document(job)` (C4b G5)
- 변경: Job의 정본 JSON(`recipe_hash`, `cell_hash`, `carry_z`, `steps`)을 하나로 둔다. Rosy Cell 제안과 Fleet 재컴파일이 같은 바이트로 비교한다(D-403 §3).
- 증거: `src/site/fleet/test/test_cell_compiler.py`.
- gate 변화: 없음.

## 2026-10-04 · uncommitted · docs(palletizing): 앱 완료 목표를 현재 구현과 대조

- 변경: 현황 보고서와 D-446 목표 초안에서 정본 process 재사용, 전용 앱 흐름, 박스 전용 중간 수용과 슬립시트 후속 목표를 구분했다. 예전 grasp depth 미지원 설명과 현재 코드의 차이도 기록했다. process 코드는 바꾸지 않았다.
- 증거: 기준 main f32643ffd에서 복사·빌드한 설치 wheel로 compatibility·Cell·layout 174 passed, skip 없음. 슬립시트 거절도 의도된 시험이며 전체 적재 성공으로 해석하지 않는다.
- gate 변화: SOURCE GO 유지, ROS-SIM/ARTIFACT HOLD와 DEVICE/FIELD PARKED 유지. 목표 문서는 수용 승격 근거가 아니다.

## 2026-10-04 · uncommitted · feat(palletizing): 작업자 수동 간지 checkpoint

- 변경: `recipe/2`는 `handling: operator`인 palletize만 받는다. 간지는 별도 `OperatorSheetStep`으로 Job에 남기고, PlanBundle에는 상자 transfer만 넣는다. 층 높이에는 실제 간지 두께를 포함하며 간지 station과 held-item hang에는 넣지 않는다. 두꺼운 작업자 간지의 carry 회귀도 RED→GREEN으로 검증했다. 16상자 예제의 확인 경계는 다음 transfer 5/13, 기존 pallet ledger는 8/16이다. 첫 층 간지도 경계 1을 지원한다.
- 증거: SOURCE 경로로 process/호환성/submission/Fleet compiler/dependency 검사 210 passed; canonical owner/coordinator를 주입한 기존 compiler/runtime replay 검사 9 passed. `recipe/1`의 recipe/cell/Job hash와 checkpoint가 없는 저장 envelope는 이전 값 그대로다. 독립 Fleet guard 후보가 실제 출력의 경계 5/13 및 1/5/9/13과 checkpoint hash를 수락했다. X:에서 빌드·설치한 palletizing/execution wheel의 실제 import 경로를 검증하고 호환성·legacy 검사 169 passed 및 수동 16상자/경계 5/13 컴파일을 확인했다. ROS-SIM은 이번 변경에서 실행하지 않았다.
- gate 변화: 확인 metadata는 권한을 주지 않는다. Fleet의 durable checkpoint guard가 없으면 새 envelope는 거절된다. 작업자 안전 접근 증명·인증 확인 API·실제 간지 작업 수용은 HOLD이며 전체 목표 완료로 해석하지 않는다.
