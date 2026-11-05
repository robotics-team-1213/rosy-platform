# omx_transfer logs

추가만 한다. 형식: [module harness 설계](../../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
등록 전 이력은 `git log -- integrations/robots/omx`를 본다.

## 2026-10-27 · uncommitted · refactor(harness): register omx_transfer as a control wheel module

- 변경: `progress.md`, `logs.md` 추가, `harness.yaml` 등록, `AGENTS.md`에 harness 기록 안내 추가. 동작 변경 없음.
- 증거: 원격 시험 PC에서 `test/test_platform_omx_transfer_provider.py` 25 passed, 0 skipped.
- gate 변화: 신규 기록. SOURCE GO, 나머지 gate는 등록 시점에 평가하지 않아 PARKED.
- 결정: D-61, D-168
- 교훈: 없음

## 2026-11-05 · 348778e549 · feat(learning): 검수 SmolVLA의 이동 후 오프라인 재적재

- 변경: 정책 자산 검증을 공용 learning contract에서 재사용하고 client wheel 의존성을 정확 pin으로 결속했다. 기본 실행 허용 목록은 ACT로 유지한다.
- 증거: [검증 기록](../../../docs/validation/omx-smolvla-reviewed-cycle-2026-11-05/result.md). source0e82c4fafa의 실제 SmolVLA6/12관절 합성 학습·모델 이동·빈 cache 오프라인·bench runner 적재/추론2 passed, ACT 정본 SDK 왕복2 passed, 각각 exit0/NEW0. bc81a33cad는 CI pin과 독립 SDK 시험 import root 수정이며 모델 loader source는 같다.
- gate 변화: 없음. 합성 연결을 DEVICE/FIELD 수용으로 올리지 않는다. FULL의 최종 결과와 독립 리뷰 한계는 위 기록을 따른다.
- CE: 해당 없음 — 기존 learner/test venv 분리 교훈 적용. 새 거부 조건은 코드·회귀·README에 남는다.
