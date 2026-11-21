## 2026-11-20 · uncommitted · feat: D-1057 claim 때 owner 확인과 worker 결과 재전송

- 변경: Fleet `claim`이 등록된 owner가 아닌 주체를 원장 변경 전에 `OWNER_PRINCIPAL_NOT_REGISTERED`로 거부. worker(`cell_result_outbox.py`)가 전송 실패한 결과를 상태 파일에 보관하고 다음 폴링마다 팔 재실행 없이 같은 본문을 RUNNING·같은 lease일 때만 재전송. 안전 폴링·human-hold 분기는 그대로(그 아래 한 호출 추가).
- 증거: 로컬 `test_omx_cell_task_worker_refusal.py`(403 뒤·연결 끊김 뒤 재전송, lease 변경·종료 시 미재전송, 팔 재실행 없음), `test_pipeline_evidence.py` 외.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
