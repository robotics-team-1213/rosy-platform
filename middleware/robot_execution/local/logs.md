# execution_local logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
등록 전 이력은 `git log -- middleware/robot_execution/local`를 본다.

## 2026-10-27 · uncommitted · refactor(harness): register execution_local as a control wheel module

- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가. 동작 변경 없음.
- 증거: 원격 시험 PC에서 `middleware/robot_execution/local/test` 276 passed, 0 skipped.
- gate 변화: 신규 기록. SOURCE GO, 나머지 gate는 등록 시점에 평가하지 않아 PARKED.
- 결정: D-61, D-168
- 교훈: 없음

## 2026-11-05 · 348778e549 · fix(learning): 공용 학습 계약 wheel pin 정합

- 변경: learning contract의 정확 pin을0.1.16으로 맞췄다. 설치 검사·owner session·HOLD 동작은 변경하지 않았다.
- 증거: [검증 기록](../../../docs/validation/omx-smolvla-reviewed-cycle-2026-11-05/result.md). 이전 정확 pin과 새 wheel의 충돌은 실제 원격 venv pip check에서 재현했고 수정 후 설치·아키텍처 회귀를 확인했다. 최종 FULL 결과는 위 기록을 따른다.
- gate 변화: 없음. 기존 SOURCE GO와 나머지 PARKED를 유지한다.
- CE: 해당 없음 — 의존성 metadata와 설치 회귀가 원인·수정을 설명한다.
