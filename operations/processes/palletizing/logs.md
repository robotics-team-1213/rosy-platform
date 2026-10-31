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

## 2026-10-17 · fa22f99db · feat(palletizing): recipe/3 혼합 로더와 팔 베이스 둘을 아는 탐욕적 계획기 (D-781)

- 변경: `rosy_cell.recipe/3` 로더(`mixed_recipe.py`)와 Extreme Points 탐욕적 계획기(`mixed_planner.py`, 규칙 `mixed_rules.py`, Step·순서 `mixed_plan.py`, 팔·구역·도달 `mixed_cell.py`)를 더했다. 지지(`support_ratio_v1`), 위 하중, `gap`, 핑거 여유, 주입된 도달 판정, Step마다 `carry_z`를 지키고, `depends_on`은 지지·핑거 여유·같은 팔 순서만 담는다. 집는 자리마다 공급 순서를 낸다. `recipe/1`·`/2` 코드는 바꾸지 않았다.
- 증거: 원격 pytest(`operations/processes/palletizing/test`, 호환성, legacy Cell, 의존 경계) 228 passed, known_failures 0 new. 독립 검사기가 두 팔·한 팔(3층) 계획의 모든 Step을 확인했다.
- gate 변화: 없음. Fleet `cell_compiler` 연결, 공유 D-402 IK 도달 판정, 팔별 Action 변환, SIM은 후속이다.

## 2026-10-17 · f5ce2625a · fix(palletizing): recipe/3 carry_z와 도달 판정 보강 (D-781)

- 변경: `carry_z`는 기준 순서의 앞 Step이 아니라 그 Step을 기다리지 않는 모든 Step(다른 팔이 먼저 끝낼 수 있는 것)의 윗면으로 정한다. 도달 판정은 놓는 자세뿐 아니라 실제 집는 자세(집는 자리 높이 + 물체 높이 - grasp_depth, 놓는 yaw)와 두 자세를 `carry_z`로 올린 자세까지 본다. `alternates`는 `shared_band` Step에만 두고 대체 팔마다 집는 자리를 적는다. `upright_fixed`는 `yaw_deg`에 0이 없으면 로더가 거부한다. `support_ratio_v1`은 "넘게"로 읽는다(정확히 60 %는 불통과). 손으로 계산한 고정 사례(지지 비율, 위 하중, 핑거 띠, 두 층 탑의 `carry_z`)를 더했다.
- 후속: 팔별 Action 내용(각 팔 `base_in_cell` 좌표로 변환), Fleet `cell_compiler` 연결, 공유 D-402 IK 도달 판정, 팔레트가 여럿일 때 팔레트 사이의 핑거·`gap` 검사, 팔레트 좌표계 회전, `process_artifact_digest`에 계획기 버전 넣기, cell profile에서 핑거 치수 읽기, G1 SIM.
- 증거: 원격 pytest(palletizing/test, 호환성, legacy Cell, 의존 경계) 237 passed, known_failures 0 new.
- gate 변화: 없음.

## 2026-10-17 · uncommitted · feat(palletizing): recipe/3 팔별 Action 변환과 cell/3 작업대 문서 (D-781 §5)

- 변경: `mixed_submission.py`가 계획의 Step마다 주 팔과 대체 팔 각각의 `pallet.transfer/1.0.0` 입력을 그 팔의 베이스 좌표로 낸다(베이스 x·y만큼 옮기고 -yaw 회전, yaw는 cell yaw - 베이스 yaw를 (-pi, pi]로, z는 그대로, 9자리 반올림). 대체 팔은 자기 집는 자리에서 집는다. approach 높이는 한 팔 컴파일러처럼 윗면 + `approach_clearance_m`이고 그 Step의 `carry_z`로 자른다. `layer_index`는 지지 단계(팔레트 위 0, 그 위 1 + 받치는 상자의 최대 단계)다. `item`은 계약이 `box`·`slip_sheet`만 받으므로 `box`이고 sku는 Job 문서에 있다. Job 문서에 계획기 버전, 계획 digest, 변환 버전을 넣었다. `mixed_cell_doc.py`가 잠정 `rosy_cell.cell/3`(D-778 §1의 `arms[{role, instance_id, workcell_id, base_in_cell{calibration_revision, x, y, yaw}, zone_id, home}]`, 직사각형 `zones`, `pallet_frames`, `stations`, annulus `reach`)을 읽는다.
- 증거: 원격 pytest 결과는 이 브랜치 보고에 적는다.
- gate 변화: 없음. 후속: owner의 sku별 승인 형상과 계약의 sku item, 공유 D-402 IK 도달 판정, 팔레트 좌표계 회전, D-778 G0 cell 스키마 확정(변환 행렬, 다각형 구역, fixtures), 한 팔 recipe/3 Job.

## 2026-10-17 · uncommitted · feat(palletizing): recipe/3 Step 입력에 sku (D-781 §2)

- 변경: `mixed_submission.transfer_inputs`가 팔마다의 입력에 Step의 `sku`를 넣는다. `SUBMISSION_VERSION`을 `/2`로 올렸으므로 recipe/3 Job id가 바뀐다. recipe/3 로더는 sku를 grant 식별자 규칙(`^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$`)으로 받는다. recipe/1·/2는 바뀌지 않았다.
- 증거: 원격 pytest를 돌리지 못했다(실험실 시험 호스트 연결 불가).
- gate 변화: 없음.

## 2026-10-23 · 97d225c050 · refactor(palletizing): 공정 제출 검증의 단일 정본 이동 (D-849)

- 변경: 기존 `rosy.execution.site.cell_submission`의 타입·재컴파일·입력·marker·checkpoint 검증과 저장 문서를 `rosy.processes.palletizing.submission`으로 옮겼다. Fleet/gateway compiler의 `compile_submission`이 이를 연결하고 Fleet resolver는 주입된 제출 port를 소비한다. 옛 모듈·검증 사본은 제거하고 wire·원장·승인·장치 권한은 유지했다.
- 증거: `24002a33cb`의 새 경계 시험 RED 3 failed/기존 13 passed 뒤 `48b843e0ab` 대상 회귀 347 passed. 독립 리뷰가 지적한 설치 Fleet 증거 공백은 `46e730cf51`에서 wheel/sdist RED 2 failed를 확인하고 `97d225c050`에서 설치 Fleet/gateway·기존 설치 probe·compiler 22 passed로 보완했다. 첫 FULL의 샘플 digest와 축소 size unit 회귀를 고친 최종 `a5ab652723` FULL은 11170 passed/545 skipped, 5 subtests passed이며 두 로그 모두 NEW/known/flaky 0이다. [검증 기록](../../../docs/validation/process-submission-ownership-2026-10-23/result.md)에 원본 로그 hash와 적용 범위를 둔다.
- gate 변화: 없음. host 소스·설치 증거이며 ROS/Gazebo 동작·artifact·실물·현장 수용과 main 착지·push는 포함하지 않는다.

## 2026-10-29 · 0e808cd6be · refactor(palletizing): 앱과 Fleet의 완전한 컴파일 결과 공유

- 변경: 공정 소유 `compilation.py`가 단일 recipe의 문서 로딩·Job·PlanBundle·marker·operator checkpoint와 item geometry를 조립한다. gateway와 Fleet은 같은 계산을 호출한다. gateway가 누락하던 수동 간지 checkpoint 두 개를 보존한다. Fleet 설치 소스 digest·gateway 고정 digest·생성자 검증·carry_z 불일치 거절·recipe/3 경로·기존 제출 port는 유지했다. 기록 샘플의 process digest도 갱신했다.
- 증거: `c8b708861d` 원격 RED에서 일반 recipe는 일치하고 수동 간지만 checkpoint 누락으로 실패했다. `0e808cd6be` 전체 affected 선택은 12,598 passed/641 skipped와 5 subtests passed, 로그 세 개 모두 NEW/known/flaky 0이다. 테스트만 추가한 `171d88d7fa`에서 checkout 밖 wheel/sdist 두 경로의 수동 checkpoint·저장 문서·16 transfer도 통과했다. 두 차례 별도 읽기 전용 리뷰에서 지적 없음. [검증 기록](../../../docs/validation/cell-compilation-boundary-2026-10-29/result.md)에 SHA·명령·로그 hash·한계를 기록했다.
- gate 변화: SOURCE GO 유지. 선택 suite의 skip을 실행으로 세지 않으며 ROS-SIM/ARTIFACT HOLD, DEVICE/FIELD PARKED는 유지한다. main 착지·push·실물 수용은 포함하지 않는다.
