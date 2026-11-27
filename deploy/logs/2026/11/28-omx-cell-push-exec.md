## 2026-11-28 · uncommitted · feat(omx): the Fleet worker runs a push through the cell job API and completes it on measured displacement (D-1083)

- 변경: `cell_area_job_spec.py` push에 `machine_ids`(`cell-task-worker`, 정지 증명은 그대로 측정, `cancellable` 아님), `cell_job_worker.py`의 push 엄격 허용 목록(정확히 10개 키, mm 5..20), `cell_push.py`/`cell_push_measure.py`(밀기 뒤 같은 블롭 검출로 `displacement`와 접힘 판독용 `park`), `cell_task_motion.run_push`·`push_evidence_ok`와 `cell_task_exec`·`cell_task_worker`(`capabilities: ["motion","push"]`, 증거 없이 종료 코드만으로 완료하지 않음), `rosy push`는 `rosy pick`과 같은 도구. `CELL_MOTION_NOT_EXECUTABLE`은 알 수 없는 종류·A/B 밖에만.
- 증거: remote_pytest `test_omx_cell_push.py`·`test_omx_cell_job_worker.py`·`test_omx_cell_task_motion.py`·`test_omx_cell_task_worker_refusal.py`·`test_rosy_cli_motion.py` — 실행 기록은 구현 보고서. 실물 수용 없음
- gate 변화: 없음(정지 증명·경로 비어 있음·어두운 프레임·사이트 거절 등 셀 가드는 그대로, 밀기 완료 측정이 새로 생김). 밀기는 협조적 취소가 없다
- 결정: D-1083
- 교훈: 없음(셀 수용 전)
