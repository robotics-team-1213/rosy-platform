## 2026-11-20 · uncommitted · feat(pipeline): D-1057 셀 S는 상단 카메라 판정만으로 RELEASED (사용자 결정)

- 변경: Fleet 완료 검사·worker·`cell_task_exec`가 `cell_s`일 때만 basis `top_camera_only_target_zone` 수용. 셀 S 상단 판정은 before/after 프레임·auto_roi 구역·2 s 신선도 요구. ADR D-1057 2-1절.
- 증거: 로컬 `test_pipeline_evidence.py`(셀 S 통과·셀 AB 거부), `test_omx_cell_zone_verification.py`, `test_omx_cell_task_exec_measured.py`.
- gate 변화: 없음. 실물 미실시.
- 결정: 없음
- 교훈: 없음
