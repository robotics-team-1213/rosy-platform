## 2026-11-20 · uncommitted · feat(omx): D-1057 슬롯 오버레이 도구와 Codex 3차 지적 수정

- 변경: `cell_slot_overlay.py`(읽기 전용)와 README 슬롯 설정 절. 깊이 프레임 연결, `verify_stack_outcome(strict_target=)`, `frame_receipt(timeout_s=)`와 프레임 대기 상한, `MapPoseService.add_update_listener`로 bed 확인을 자세 갱신마다 무효화.
- 증거: 로컬 `test_omx_cell_zone_verification.py`, `test_omx_cell_slot_overlay.py`, `test_pipeline_evidence.py`, `test_omx_cell_auto_pick.py`.
- gate 변화: 없음. 팔레트 z_gate는 보정 검사 때문에 UNKNOWN(알려진 공백).
- 결정: 없음
- 교훈: 없음
