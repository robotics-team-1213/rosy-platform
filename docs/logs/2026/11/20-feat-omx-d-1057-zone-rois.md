## 2026-11-20 · uncommitted · feat(omx): D-1057 셀 설정 zone_rois 덮어쓰기와 구역 제안 도구

- 변경: `verify_stack_outcome(_z_mm)`에 선택 인자 `zone_rois`, `cell_zone_verification`이 설정의 `zone_rois`를 검증(형식 오류는 unverified)해 넘김. `cell_zone_propose.py`(읽기 전용)와 README.
- 증거: 로컬 `test_omx_cell_zone_verification.py`, `test_omx_cell_zone_propose.py`. 실제 셀 프레임 한 쌍으로 제안 실행(결과는 조정 세션 확인 대기, 설정에 쓰지 않음).
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
