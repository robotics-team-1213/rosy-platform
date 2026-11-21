## 2026-11-20 · uncommitted · fix(fleet,omx): D-1057 검토 7차

- 변경: 설정 파일의 `_commissioning` 무시(이번 실행 인자만), 검토된 작업은 입회 표시가 와도 검토 경로, 재전송은 원래 증거가 유효한 동안 `/complete`만(409 이미 기록됨은 이어서 전송, 재측정은 65 s 뒤), 적재함 확인은 claim에서 lease에 묶고 무효 때 422 `BED_CONFIRMATION_INVALID`·RUNNING 작업 재확인 허용. ADR D-1057 2-7절과 API v1.next 절을 맞춤.
- 증거: 로컬 `test_pipeline_evidence.py`·`test_omx_cell_task_worker_refusal.py`·`test_omx_cell_envelope.py`·`test_omx_cell_task_exec_measured.py`와 `rosy_harness.py lint`. 원격 시험은 조정 세션.
- gate 변화: 없음. 가드 한계는 그대로이고 실물 인터록은 만들지 않았다.
- 결정: 없음
- 교훈: 없음
