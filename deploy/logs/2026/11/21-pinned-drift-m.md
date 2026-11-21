## 2026-11-21 · uncommitted · 자동 궤적 보정 저널에 pinned_drift_m 추가

- 변경: rosy-auto-track-calibration이 매 실행 JSON 줄에 고정 장소와 궤적 점 사이 거리(pinned_drift_m)를 출력한다. 지도·동기화는 바꾸지 않는다
- 증거: test_auto_track_calibration.py 신규 시험 통과(기존 service_principal 시험 1건은 ModuleNotFoundError로 변경 전부터 실패)
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
