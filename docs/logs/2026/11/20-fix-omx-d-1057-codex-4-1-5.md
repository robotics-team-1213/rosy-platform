## 2026-11-20 · uncommitted · fix(omx): D-1057 Codex 4차 검토 1~5 (깊이 경로)

- 변경: 깊이 경로에서도 놓기 전후 변화·방향을 별도 증거로 요구, 바닥 패치별 검증(`floor_depth_mm`, 가림·덮개 거부, 깊이 좌표 여백), 층 식별 ±7 mm와 기존 안착 대역 분리, 셀별 top ROI 없으면 미검증, 구역 제안의 외삽 제거, 깊이는 Fleet 작업·floor 설정 때만 캡처·임시 디렉터리 정리·읽기마다 3 s 마감.
- 증거: 로컬 `test_omx_cell_depth_slots.py`(합성 오염·실제 프레임), `test_omx_cell_zone_verification.py` 외.
- gate 변화: 없음.
- 결정: 없음
- 교훈: 없음
