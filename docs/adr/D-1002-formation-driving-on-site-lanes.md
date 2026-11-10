## D-1002 현장 차로에서 편대 주행 — 리더는 Nav2 trip, 팔로워는 FOR-004 TRAIL 추종, Fleet은 둘을 미션 하나로 묶고 차로 적합성만 더한다

**Status:** Proposed (2026-11-09, 사용자 목표 "Fleet R이 관리하는 여러 Pinky가 현장 지도에서 Nav2로 편대 주행". 설계 토론(설계자·비평자 2안 대립)과 Fleet 구현, Gazebo SIM 시나리오 `tools/sim/formation_lane.py`까지. SIM 실행 결과는 §검증에 적는다. 실물 기체는 꺼져 있고 실주행은 사용자 결정 뒤다. DEVICE·현장 수용 없음)

잇는 결정: [D-20](D-20-swarm-fleet.md)(Fleet은 지정·릴레이·중단 판단, 추종 계산은 로봇) · [D-31](D-31-fleet.md)(릴레이는 바이트를 바꾸지 않는다) · [D-559](D-559-leader-trail-follow-path-replay.md)(리더 자취 따라가기, SIM 2대 최대 편차 0.066 m) · [D-581](D-581-trail-follow-ceiling-camera-anchored-odom.md)(천장 카메라 기준 자취) · [D-517](D-517-multi-robot-lane-traffic.md)(로봇마다 trip 하나, 9항 로드맵 "리더를 팔로워가 따라가는 것부터") · [D-763](D-763-fleet-work-kinds-composed-steps.md) 7(TRIP 단계 장부 `POST /api/fleet/trip-jobs`) · [D-875](D-875-swarm-api-and-safety-lifecycle-boundary.md)(FOR-004 안전 수명 주기) · [D-18](D-18-rosy-core.md)(CORE만 최종 `cmd_vel`) · [D-986](D-986-navigation-approval-flow-and-motion-fingerprint.md)(항법 승인; 형제 작업 B가 현장 지도 Nav2 trip을 만든다).

### Context

1. 편대의 부품은 이미 있다. Fleet `fleet/swarm`의 FOR-004 세션(무장 → 릴레이 → 감시 → HOLD/ABORT)은 리더 pose 스트림을 팔로워에 넘기고, 팔로워 CORE가 `swarm/follow`로 Nav2 moving goal(COLUMN) 또는 20 Hz 자취 재생(TRAIL, D-559)을 스스로 계산한다. 스트림이 끊기면 팔로워는 SWM-004로 혼자 선다. 팔로워의 `nav.stuck`·`safety.estop`·`swarm.aborted`는 세션을 HOLD로 바꾸고 리더 항법을 취소한다(`session_lifecycle._apply_policy`). D-559 SIM(두 대)에서 자취 편차 최대 0.066 m, 릴레이 5 s 끊김 뒤 1.2 s 안에 HOLD, 접촉 0을 쟀다.
2. 없는 것은 세 가지다. (a) 편대가 콘솔 세션일 뿐 Mission 장부에 없다(`formation_control.py`에는 `mission_id`가 없다). (b) 리더가 현장 지도 경로를 받는 길이 편대에 묶여 있지 않다 — 콘솔은 리더에 Nav2 목표 하나를 따로 내린다. (c) 차로 폭 검사가 없다. `geometry.slots()`는 `MIN_SPACING` 0.4 m만 본다. LINE·V·GRID·CIRCLE은 옆 자리가 있어 1.22 m 차로(world_261026 2.44 × 1.22 m)에 몸체 약 0.2 m 두 대가 나란히 서야 하는데, Nav2 팽창 반경(0.15–0.2 m)을 빼면 비용 0 폭은 약 0.8 m라 옆 로봇을 치명 장애물로 본다.
3. 설계 토론(2026-11-09). 설계자는 A안(리더 Nav2 trip + FOR-004 팔로워)을, 비평자는 B안(로봇마다 독립 Nav2 trip, Fleet 시간·블록 통행권으로 간격, 릴레이 없음)을 들었다. C안(Fleet이 가상 강체 자리를 계산해 로봇마다 Nav2 목표를 흘려보냄)은 둘 다 기각했다 — Fleet이 사실상 `cmd_vel` 상류가 되고 D-20이 이미 기각한 중앙 방식이다. 비평자의 유효한 지적은 셋이다. 차로 폭 검사가 없다, 세션과 Mission이 묶이지 않았다, SIM 증거는 "간격 허용오차"의 정의(경로 거리·참값·이동 중만)와 리더 급정지·팔로워 상실 주입이 있어야 오도하지 않는다.

### Decision

**원칙.** 안전은 로봇이 혼자 지킨다(CORE만 `cmd_vel`, SWM-004 자체 HOLD, D-422 몸체 기준 정지). Fleet은 묶고, 거절하고, 기록한다. Fleet이 죽거나 링크가 끊기면 팔로워는 스트림 시한에 서고 리더는 자기 trip 끝에서 선다.

1. **A안을 택한다.** 편대 주행 = 리더의 보통 trip(현장 지도 Nav2 trip은 형제 작업 B의 인터페이스, 오늘은 D-763 7 TRIP 단계 장부) + FOR-004 팔로워 세션. B안의 블록 통행권(D-517)은 편대가 아니라 다른 편대·단독 로봇과의 교통 층으로 남는다. 간격 정밀도(블록 단위)와 리더 정지를 팔로워에 알릴 길이 없는 점에서 편대 주행의 답이 아니다. 추종 계산은 로봇 탑재 그대로다.
2. **차로에서는 한 줄 대형만 연다.** `fleet.server.formation_mission.lane_fit`가 무장 전에 거절한다(`FORMATION_LANE_UNFIT`). 허용 대형은 COLUMN·TRAIL, 팔로워 1–3대. 간격 하한은 `max(MIN_SPACING, 몸체 0.20 + max_speed × HOLD_LATENCY 1.5 s + 여유 0.10)`이다. 0.18 m/s면 0.57 m, 0.26 m/s면 0.69 m. 1.5 s는 D-559에서 잰 1.14–1.20 s에 여유를 둔 값이다. LINE·V·GRID·CIRCLE은 개활지 콘솔 조작(`/api/fleet/formation/start`)에만 남고 미션으로는 열지 않는다.
3. **편대 미션 한 건 = 리더 trip 장부 행 하나.** `POST /api/fleet/formation/mission {leader, members[2–4], formation: TRAIL|COLUMN, spacing?, max_speed?, steps: [{to, via[]}]}`(이름 있는 운영자). 순서는 (1) 차로 적합성, (2) 팔로워 무장(`formation_start`, D-20 릴레이), (3) 리더 trip job 생성(`create_trip_job`, D-763 7 TRIP, `one_person`). 리더 job이 거절되면 무장을 되돌린다 — 무장된 팔로워가 오지 않을 리더를 기다려서는 안 된다. 장부 행의 `mission_id`가 편대 미션의 이름이고 `GET /api/fleet/formation/mission`이 `{mission_id, leader, members, formation, spacing, spacing_floor, state RUNNING|ENDED, end_reason, formation_status}`를 돌려준다. 편대 미션은 사이트에 하나다(`FORMATION_ACTIVE`). `POST /api/fleet/formation/mission/stop`은 세션을 풀고 리더 항법을 취소한다. 새 프로토콜 스키마는 없다(요청 모양은 Fleet 라우트 모듈의 것이고 `steps`는 기존 `TripJobStep`).
4. **끝나는 길은 둘뿐이고 둘 다 장부에 남는다.** (a) 팔로워 상실(`safety.estop`·`nav.stuck`·`swarm.aborted`, 스트림 단절) → FOR-004 HOLD → 릴레이 정지 + 리더 `navigation/cancel` → 리더 trip이 취소돼 TRIP 장부 행이 HOLD가 된다 → 편대 미션이 `ENDED(end_reason=세션 사유)`로 닫히고 세션을 정리한다. (b) 리더 도착(`arrived`) → 행 `GOAL_CONFIRMED` → 편대 미션 `ENDED(leader_job_ended)`, 세션 정리. 감시 신호는 장부 행 상태(`READY`·`RUNNING`·`ACTION_SUCCEEDED`가 아니면 끝)다. lease 항목(`lease.jobs`)은 HOLD 뒤에도 사람이 재개·취소할 때까지 남으므로 신호가 아니다(독립 검토 H1, 2026-11-09). `mission/stop`도 FOR-004 정지와 같이 리더 trip을 끝내고 그 job은 HOLD로 사람에게 간다(D-763 rev 2 Q3). 재개는 운영자만 한다(FOR-004 규칙). Fleet 프로세스가 죽으면 릴레이가 멈춰 팔로워가 SWM-004로 서고 리더는 trip lease 끝(D-494 규칙 M)에서 선다.
5. **배포 프로필.** TRIP 단계 장부가 열린 프로필(`simulation`, `device_trial`)에서만 라우트가 선다. 닫힌 프로필에는 `app.state.formation_mission = None`이다.

### 계약 (로봇 쪽 동작)

| 상황 | 팔로워 | 리더 | Fleet |
|---|---|---|---|
| 정상 | 스트림 ≥5 Hz로 자취 재생, 간격 = spacing × 순위, `max_speed` 한도 | Nav2 trip | 릴레이·감시·기록 |
| 리더 급정지 | 자취 끝까지 가서 간격 유지하며 정지(D-559) | 정지 | 변화 없음(RUNNING) |
| 릴레이·Fleet 단절 | `stream_timeout_ms` 뒤 자체 HOLD, 속도 0 | trip lease 끝에서 정지 | 복귀 뒤 운영자 재개 |
| 팔로워 상실(E-stop·막힘) | 그 로봇은 이미 서 있음 | `navigation/cancel`(FOR-004) | HOLD → 장부 HOLD → 미션 ENDED |
| 리더 도착 | 자취 끝에서 정지 | `arrived` | 미션 ENDED, 세션 정리 |

### Consequences

- Fleet 쪽에 더하는 것은 모듈 하나(`formation_mission.py`, 차로 적합성·구성·감시)와 라우트 셋이다. 세션·릴레이·추종·장부는 손대지 않는다.
- 편대 미션의 이력은 리더 TRIP 장부 행으로 읽는다. 팔로워별 이벤트는 세션 상태(`formation_status`)에 있고 장부에는 사유 한 줄(`end_reason`)만 남는다 — 팔로워별 장부 행이 필요해지면 그때 D-403 식 단계로 넓힌다.
- 간격 하한이 속도에 묶여, 0.6 m 대형은 팔로워 한도 0.2 m/s까지만 열린다. 더 빠르면 간격을 넓혀야 한다.
- TRAIL은 Nav2 계획기를 거치지 않으므로 팔로워는 리더의 나쁜 길(회피·회복 회전)도 그대로 되밟는다. 팔로워의 안전은 D-422 몸체 기준 정지뿐이다. 차로 교차로의 넓은 회전은 아직 시험하지 않았다.

### Alternatives

- **B. 독립 Nav2 trip 편대(비평자 안).** 로봇마다 trip, Fleet이 시간·블록 통행권으로 간격. 장점은 팔로워도 Nav2 계획기 안에 있다는 것. 단점은 간격이 블록 단위라 "편대"가 아니고, 1.22 m 차로에서 앞 로봇을 치명 장애물로 봐 BLOCKED·회복 회전이 반복되며, 리더 정지를 뒤에 전할 길이 없다. D-517 교통 층으로 남긴다.
- **C. 가상 강체(Fleet이 자리 목표 계산).** D-20이 기각한 중앙 방식. Fleet 정체 시 Nav2가 마지막 목표를 계속 쫓는다. 기각.
- **A′. 편대 전용 단계 종류 `FORMATION_TRIP`을 장부에 추가.** 팔로워별 행과 grant가 생기지만 dispatcher·receipt 경로를 새로 짜야 한다. 오늘은 리더 TRIP 행 하나로 충분하다.

### 검증 (Validation / Transition)

- 호스트: `operations/fleet/test/test_formation_mission.py`(차로 적합성, 무장 → job 순서, job 거절 시 무장 되돌림, 리더 job 종료 → 미션 ENDED, 중복 거절), 기존 `test_server_formation.py`·`test_server_app.py`·`test_boundaries.py`. 시험 PC에서만 돈다(D-584).
- SIM: `tools/sim/formation_lane.py` — gz_multi(`map_v2_fleet_real`, 로봇마다 Nav2+AMCL+CORE, 헤드리스) 2–4대. 실제 Fleet 경로(`fleet.bench` `FormationSession(TRAIL)`)로 무장하고 리더는 동쪽 도로의 북동 굽이를 지나는 Nav2 목표 셋을 달린다. 주입 둘: 목표 2 도중 리더 `navigation/cancel`(8 s), 목표 3 도중 마지막 팔로워 E-stop. Gazebo 참값(`dynamic_pose/info`)으로 채점한다. 합격선: 리더 이동 중 팔로워 경로 간격 오차 p95 ≤ 0.10 m·최대 ≤ 0.15 m(D-559 최대 0.066 m에 여유, 몸체 반폭), 두 중심 최소 거리 ≥ 0.30 m(몸체 0.2 m 접촉 대용), 리더 정지 8 s 뒤 전원 속도 < 0.01 m/s, 팔로워 상실 뒤 1.5 s 안에 전원 정지와 세션 HOLD. `result.json`의 `checks`가 판정이다.
- SIM 실행 기록은 [`docs/validation/formation-lane-sim-2026-11-09/result.md`](../validation/formation-lane-sim-2026-11-09/result.md)에 둔다. 2026-11-09 세 번의 실행은 환경 결함 셋(모델 PC 소프트웨어 렌더 segfault, CORE만 보는 준비 판정, 루프백 CycloneDDS 설정 누락)을 고쳤고 **주행·채점 구간에는 이르지 못했다.** 간격·접촉·정지 지연 수치는 아직 없다. 실행하지 못한 항목은 "미실행"이고 깨끗한 결과로 적지 않는다.
- 전환: 실물은 (1) 형제 작업 B의 현장 지도 Nav2 trip이 `trip-jobs`로 들어오고, (2) D-986 항법 승인이 있는 기체 2대, (3) 사용자가 실주행을 결정한 뒤 `device_trial` 프로필에서 0.6 m·0.12 m/s부터다. 그 전까지 이 기록은 SIM 증거다.

### References

`operations/fleet/fleet/server/console/formation_mission.py`, `operations/fleet/fleet/server/app.py`, `operations/fleet/test/test_formation_mission.py`, `tools/sim/formation_lane.py`, `operations/fleet/fleet/swarm/session_lifecycle.py`, `middleware/drive/behaviors/swarm/manager.py`, `docs/validation/d559-trail-follow-sim-2026-10-09/result.md`.
