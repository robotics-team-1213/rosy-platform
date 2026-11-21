## 2026-11-20 · uncommitted · fix(omx): D-1057 Codex 5차 검토 (깊이 경로 증거 강화)

- 변경: 배치 변화를 밝기·대비 정규화 상부 차이 + 깊이 상승 필수로, 방향을 깊이 블롭 주축으로. 바닥 패치 기록 깊이 ±4 mm와 공통 평면 대조, 슬롯 ROI 국소 엣지 정렬 검사. 버스트 프레임마다 단일 프레임과 같은 검사·순번 연속·시계 오프셋, 형식 재시도 포함 3 s 마감 하나. 비 Fleet 실행은 동작 전 측면 촬영 생략, RGB 읽기 마감 공유.
- 증거: 로컬 `test_omx_cell_depth_slots.py`(조명만 변경·동방향 오염·국소 정렬), `test_omx_cell_depth_burst.py`, `test_omx_cell_zone_verification.py`. 실제 셀 버스트가 새 검사를 통과함을 읽기 전용으로 확인.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
