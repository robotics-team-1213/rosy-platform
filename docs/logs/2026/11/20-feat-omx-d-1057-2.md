## 2026-11-20 · uncommitted · feat(omx): D-1057 오래된 보관 결과를 팔 없이 다시 측정해 재전송

- 변경: `cell_remeasure.py`와 `cell_result_outbox.resend_pending`의 `remeasure`: owner 증거가 50 s 이상 지났으면 보관한 놓기 전 프레임과 새 프레임, 러너 상태로 다시 측정해 새 본문을 보냄. 실패하면 `last_refusal`을 남기고 RUNNING 유지. 구역 측정이 놓기 전 프레임을 `zone-before`에 저장, 실행기가 재측정 맥락을 prep 폴더에 기록.
- 증거: 로컬 `test_omx_cell_task_worker_refusal.py`(오래됨·신선함·실패·lease 변경·실제 함수).
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
