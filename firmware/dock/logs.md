# dock logs

추가만 한다. 형식: [module harness 설계](../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 [도킹 스테이션 설계](../docs/plans/2026-09-02-docking-station-design.md)와 `git log -- dock`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the dock harness pilot
- 변경: `progress.md`, `logs.md` 추가
- 증거: `PYTHONPATH=src/rosy_core;src/rosy_control;src python -m pytest test/test_dock_contract.py src/rosy_core/test/test_docking.py -q` 107 passed (2026-09-15 Windows). `dock` 경로는 `git status --short`가 비어 있어 HEAD `084b93c` 기준
- gate 변화: 없음. SOURCE/LOCAL GO(재실행), ROS-SIM HOLD(costmap 통합 intent-only), ARTIFACT N/A(ESP32 toolchain 없음, 빌드 미검증), DEVICE HOLD(물리 벤치 없음), FIELD PARKED를 스냅샷으로 남김
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-15 · uncommitted · docs(harness): hold unverified dock firmware instead of N/A
- 변경: 리뷰 반영. ARTIFACT를 HOLD로, `cmd`를 POSIX `:` 구분자로, `last_verified.commit`을 `uncommitted`로(증거 시험이 미커밋 WIP가 있는 `src/rosy_core`를 import)
- 증거: 미실행 — 기록 정정만. 시험 결과는 위 항목의 107 passed를 그대로 쓴다
- gate 변화: ARTIFACT N/A→HOLD (펌웨어 빌드는 적용 대상이지만 미검증)
- 결정: 없음
- 교훈: 없음

## 2026-09-25 · uncommitted · refactor(firmware): move dock under firmware/ (D-231)

- 변경: `firmware/dock/`로 이동, 동작 변경 없음 (D-231)
- 증거: 이 커밋의 도크 계약 시험
- gate 변화: 없음
- 결정: D-231
- 교훈: 없음
