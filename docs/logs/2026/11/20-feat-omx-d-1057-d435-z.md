## 2026-11-20 · uncommitted · feat(omx): D-1057 D435 깊이 상대 높이를 독립 Z 기준으로 (사용자 결정)

- 변경: `cell_depth_slots.py`(점유·층을 같은 깊이 프레임의 바닥 평면 대비 상대 높이로), `_current_frame_calibration_checks`·`perceive_slot_z_mm`·`verify_stack_outcome(_z_mm)`에 선택 인자(`depth_reference`, `slot_roi`, `floor_rois`, `after_depth`), `zone_rois.floor`. 실제 셀 프레임(test/fixtures/omx_zone_cal_1120)으로 시험. ADR 2-2절.
- 증거: 로컬 `test_omx_cell_depth_slots.py`, `test_omx_cell_zone_verification.py`, `test_omx_cell_auto_pick.py` 등.
- gate 변화: 없음. 실물 수용은 별도(zone_rois·floor는 아직 셀 설정에 없음).
- 결정: 없음
- 교훈: 없음
