## 2026-11-20 · uncommitted · fix(fleet,omx): D-1057 검토 8차

- 변경: worker 재전송은 60 s 이상 65 s 미만엔 보내지 않고 보관, 만료 계열 422(`OWNER_EVIDENCE_MEASURED_AT_INVALID`)는 보관 후 재측정; claim은 적재함 확인 결속을 원장 변경 앞에서 한 `now`로 판정해 실패면 거부. ADR D-1057 2-8절.
- 증거: 로컬 `test_pipeline_evidence.py`·`test_omx_cell_task_worker_refusal.py`와 lint. 원격 시험은 조정 세션.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
