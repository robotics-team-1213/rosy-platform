## 2026-11-27 · uncommitted · D-1082 Nav2 도로 trip 정지 복구

- 변경: trips/nav2_trip_recovery.py 추가, trip_runner._stop이 Nav2 도로 trip의 stall·navigation 정지를 복구로 바꾸고 trip_steps가 정지 확인 뒤 기존 step_nav2_route로 차선 복귀 경로를 다시 보낸다
- 증거: test_nav2_trip_recovery.py와 영향 묶음 원격 시험(PR 증거)
- gate 변화: 없음
- 결정: D-1082
- 교훈: 없음
