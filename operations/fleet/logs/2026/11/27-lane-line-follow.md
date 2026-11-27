## 2026-11-27 · uncommitted · 유턴이 있는 운행은 유턴 뒤 lane 간선을 카메라 line_follow로 실행

- 변경: turnaround UTURN까지 Nav2, 이후 lane 간선은 CAMERA_LINE으로 재입회하고 free·정밀 정차는 기존 실행. 카메라 불가면 이유 코드가 있는 fleet_hold. 마지막 stop 하나에 나가는 방향 yaw. free→lane 재시작, hold 재개, 재계획·zone 목적지 연장, 모호한 PUT의 취소·재시작 처리
- 독립 검토 반영: 유턴 강제 뒤 능력 검사·Nav2 조건 재계획(재계획에 유턴이 없으면 원래 모드로 복원), free 미지원 명시 거절. cue 전송 오류(408·429·5xx·연결 오류)는 연속 3회/2초로 유예하고 500/501 미배선은 5초 mute로 0.5초 재시도를 막으며 명시 거절은 즉시 hold, 수락 증거는 2초(주기 4배) 만료하되 정지 중 ON_LANE은 해제 cue 1회만 보내고 수락 상태를 유지. 유턴 전 Nav2 거절·취소·stall은 재개 가능한 hold. `TRIP_LANE_CUE_PENDING`, `TRIP_NAVIGATION_ABORTED`, `TRIP_STALL` 콘솔 오류 문구 추가 및 `test_trip_uturn_review.py` 유턴 픽스처(`finish` kind `junction`)·`_strict_named_stop`·`check_cue`(stale/UNSEEN) 회귀 시험 추가.
- 증거: `test_trip_uturn_review.py`, `test_trip_uturn_lane.py`에 회귀 시험 추가. `python3 -m py_compile`·`node --check` 통과, `python3 tools/harness/rosy_harness.py lint`: 0 error(s). 커밋 없음.
- CORE 확인: `line_follow/cue/lane_cue.py:set_lane_cue`는 비활성 때도 cue·seq·debounce를 저장하나 TTL 뒤 소비되지 않고, `manager.py:_tick_locked`는 OFF 때 정지 반환, `set_mode`는 cue 초기화. 기존 GET `/line-follow`에는 cue 지원을 무동작 판정할 필드가 없으므로 프로브 유지. 로봇 동작 검증은 미실행.
- 이전 분기: feature 전 `binding_id`는 precision 또는 bound_nav2에서만 생겼으므로 `elif binding_id`의 precision=None·bound_nav2=False는 도달 불가. 현재 precision 조건 유지, 명시 Nav2+precision 거절은 계획 계산 앞으로 이동.
- gate 변화: SOURCE=GO
- 결정: 없음
- 교훈: 없음
