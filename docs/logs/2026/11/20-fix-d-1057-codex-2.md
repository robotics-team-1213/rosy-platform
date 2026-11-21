## 2026-11-20 · uncommitted · fix: D-1057 Codex 2차 검토 반영

- 변경: 실행기가 CLI의 들여쓴 여러 줄 JSON을 `raw_decode`로 읽고 측정 슬롯·tier를 작업(dst_site, handoff tier)에 결속. `cell_zone_verification`은 layer/col/row 범위 검사, 놓기 전 상부·측면 프레임, 배치 뒤 촬영·공통 2 s 신선도, 상부 구역 미측정 거부(`cell_auto_evidence.pre_motion_frame`이 before 측면을 싣는다). Fleet bed 확인은 콘솔 상태 갱신마다 이동·지도 ID·버전 변경을 검사. ADR·API 문장 정정.
- 증거: 로컬 `test_omx_cell_zone_verification.py`(실제 cell_area_zones 판정 포함), `test_omx_cell_task_exec_measured.py`, `test_pipeline_evidence.py` 외 관련 파일.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
