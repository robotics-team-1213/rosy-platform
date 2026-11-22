## 2026-11-22 · uncommitted · feat(fleet): Pinky 작업 Fleet trip 배차 및 start_guard·취소 정합성 (D-1060)

- 변경: `sitemap/pipeline_pinky_dispatch.py`를 추가해 `ROSY_FLEET_PINKY_TASK_DISPATCH=1`(기본 꺼짐)일 때 QUEUED Pinky 작업을 `trip_plan` → `TripRunner.start(..., start_token, start_guard)`로 한 번만 배차하고 이름 있는 운영자 요청(`requester_named`)만 허용한다. `SENDING` 중 취소는 확정 전까지 `confirmed: false`를 유지해 `LINK_LOST` 역행과 경합을 막고, 다건 tick 재확인·`runner is None` 가드·`TRIP_NOT_RUNNING` 정산을 보강했다(D-1060, API v1.435).
- 증거: `operations/fleet/test/test_pinky_task_dispatch.py` 단위 및 실제 `TripRunner`·`TripAdmission`·FastAPI E2E 시험, 원격 pytest 0 new, `rosy-contract-review` APPROVE. 실물 미실시.
- gate 변화: SOURCE (D-1061 조각 전환 및 main 병합).
- 결정: D-1060
- 교훈: none
