## 2026-11-20 · uncommitted · feat(omx): D-1057 깊이 다중 프레임 중앙값 (측정 개선만)

- 변경: `cell_depth_slots.capture_depth_frames`(한 스트림 N장, 3 s 마감)와 `median_depth`(과반 유효 픽셀), `cell_zone_verification._depth_after`가 `depth_frames`(기본 5)를 씀. 판정 범위·허용 오차 불변. 실제 셀 25프레임으로 표준편차 감소를 측정해 ADR 표에 기록.
- 증거: 로컬 `test_omx_cell_depth_burst.py`, `test_omx_cell_zone_verification.py`, `test_omx_cell_depth_slots.py`. 읽기 전용 촬영(팔·서비스·설정 무변경).
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
