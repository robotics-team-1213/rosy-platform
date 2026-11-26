## 2026-11-27 · uncommitted · pr0-confirm-idempotency-gates

- 변경: charge-bays-view, trip-replan, omx-inspector, cell-real2sim(-actions/-views), cell-pipeline-panel에 확인 대화상자·namedReason setOffBy·Idempotency-Key·propose=false 적용(비상정지·작업취소 1클릭 유지), D-766 한도 여유 확보를 위해 charge-bays-model.js를 web/cell/로 이동, test_web_dialog_contract.py 핀 갱신
- 증거: test_web_dialog_contract·test_module_structure·ui_preflight.py·rosy_harness lint 통과
- gate 변화: test_web_dialog_contract PINNED_CONFIRMS 갱신 (charge-bays-view 1->3, trip-replan 1 추가)
- 결정: 없음
- 교훈: 없음
