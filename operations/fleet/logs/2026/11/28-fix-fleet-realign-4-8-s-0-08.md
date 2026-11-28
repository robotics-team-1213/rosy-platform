## 2026-11-28 · uncommitted · fix(fleet): 통과 정지선 속도 제한 제거·realign 지속 4틱/8 s/0.08

- 변경: speed_table(stop_place_ids) 실주행은 종착 정지선만 0.05 상한, 통과 정지선(S4 등)은 없음; trip_lane_realign PERSIST_TICKS 2→4, COOLDOWN_S 3→8, REALIGN_SLOW_MPS 0.05→0.08
- 증거: 패널 D:/DevTemp/nav2-passed-goals/panel-tight r1/r2: 통과 정지선 속도 단계 2.5회/m가 주시 거리를 0.09로 떨어뜨림, realign 0회; 원격 6개 파일 83 passed
- gate 변화: 없음, 실기 주행 확인 전
- 결정: 없음
- 교훈: 없음
