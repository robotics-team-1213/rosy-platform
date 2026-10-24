## D-853 Learning VLM 판단은 닫힌 질문의 사람 정답과 모델 비교를 평가 전용으로 둔다

**Status:** Proposed (2026-10-23). 사용자 지시로 `tools/vlm_label_sheet.py`의 일회용 정적 시트를 Rosy Learning 작업 도구로 옮긴다. 이 ADR은 결정만 게시한다. 화면·저장소 구현과 호스트 시험은 후속 변경이며, 정답 품질·모델 PC 운영·질문 기준값 채택은 별도 증거다.

**Related:** [D-459](D-459-pinky-persistent-label-review-application.md), [D-461](D-461-task-first-workspace-compositions-and-learning-ux.md), [D-469](D-469-review-web-revalidation-and-guidance.md), [D-475](D-475-human-reviewed-fixed-eval-truth.md), [D-478](D-478-review-app-explicit-trusted-network-bind.md), [D-514](D-514-object-pixel-review-taxonomy-and-scenarios.md), [D-538](D-538-review-studio-workflow.md), [D-542](D-542-human-guided-review-workspace-ux.md).

### Context

닫힌 질문 VLM 판단 실험(`docs/plans/2026-10-23-vlm-fast-judge-design.md`, T1)은 질문별 사람 정답이 있어야 모델의 일치율과 기준값을 정할 수 있다. 정적 시트는 진행 저장·동시 작업·버전 충돌·평가 계산이 없고, 모델 답이 정답 화면에 섞이면 사람 판단을 끌어당긴다.

### Decision

1. `review_app.py`의 작업 도구 `/learning/vlm`(VLM 판단)을 둔다. 같은 workspace SQLite에 `vlm_items`·`vlm_model_answers`·`vlm_labels`·`vlm_label_events`를 두고 사진은 `<state>/vlm/images/<sha256>`에 한 번 복사해 매 응답 전 hash를 다시 확인한다.
2. 정답은 사람만 단다. 정답 달기 응답과 화면에 모델 답을 보내지 않는다. 저장은 `version` 낙관적 잠금이며 충돌은 409다. `labelled`는 모든 질문의 답이 필요하고 `excluded`는 판단 불가를 뜻한다.
3. 평가는 `labelled` 사진만으로 계산한다. 일치율·balanced accuracy·혼동표·모순 답 수는 측정값이며 모델 답을 승인하거나 정답으로 바꾸지 않는다(D-514, D-542).
4. 이 정답은 평가 진실이며 객체·픽셀 검수 결정, export, 인식 학습 자료로 들어가지 않는다(D-475의 취지). 운영 검수와 섞지 않도록 별도 `--empty-eval` state에서 운영한다.
5. 질문 문장·선택지는 가져오기 요청이 가져온다. learning은 `tools/`를 import하지 않으며, `tools/vlm_question_bench.py --dump-questions`가 같은 question_set의 JSON을 만든다. 같은 question_set에 다른 문장이 오면 거절한다.
6. 권한은 기존 앱을 따른다. 협업에서는 정답 저장에 edit가 필요하고, 서버 파일 경로를 읽는 가져오기는 `/api/import`처럼 거절해 서버의 CLI로만 한다. 로컬 비협업에서는 다른 저장처럼 actor가 null이다.

### Consequences

- 정적 시트 `tools/vlm_label_sheet.py`는 새 정답 작업에 쓰지 않는다. 파일 정리는 별도 변경이다.
- 현장 사진 보관 경로([D-610](D-610-ai-first-problem-resolution.md))는 바꾸지 않는다. 모델 PC에 이미 있는 벤치 사진만 가져온다.
- 화면·경로·저장소 세부는 구현이 게시될 때 `learning/curation/perception/docs/review-app.md`에 둔다.

## Amendment by D-857 (2026-10-24)

§2 「정답은 사람만 단다」는 임시·확정 두 단계로 바뀐다. 모델 합의·토론으로 만든 답은 「임시」로 표시하고 학습 자료·질문 보정에만 쓴다. 승격 평가에는 사람이 단 답 또는 사람이 확인한 답(확정)만 쓴다. §3 「지표는 승인이 아니다」와 §4 별도 평가 state는 그대로다. [D-857](D-857-rosy-learning-product-definition.md)
