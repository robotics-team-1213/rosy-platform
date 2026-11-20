## 2026-11-21 · uncommitted · fix(site): 자동 트랙 보정이 고정 안 된 장소의 방향·이름·차로 설정을 지킴

- 변경: merge_pinned가 고정 안 된 장소는 x·y만, 차로는 polyline만 추적값으로 바꾸고 yaw·name·kind·속도·폭은 지금 지도 값을 지킨다. R v270에서 S1 yaw가 null로 바뀐 것을 보고 고쳤다.
- 증거: test_auto_track_calibration 새 시험 2개, R 설치 뒤 v271 자세 유지 확인
- gate 변화: 없음
- 결정: 없음
- 교훈: 없음
