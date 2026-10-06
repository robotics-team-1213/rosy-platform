## D-490 관제 경로 계획기 구현 — `fleet/routing` 순수 모듈, 표준 라이브러리 A*, 설정·오류 코드·API·시험 기준

**Status:** Proposed (2026-10-06, 사용자 요청: "우리가 구현하는 ADR까지 함께 기록"). [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)의 구현 결정이다. [D-488](D-488-fleet-site-map-address-routes.md) M1의 계획기 부분이 이 ADR을 따른다.

### Context

D-489는 무엇을 푸는지 정했다: 차로 단위 상태, 시간 비용, A*, 출발·목표·경유지 규칙, 교차로 동작, 재계획. 이 ADR은 그것을 어디에, 어떤 모양으로 두고, 어떻게 시험하는지 정한다. Fleet 서버는 FastAPI이고, 이미지 의존성을 늘리지 않는다는 원칙이 있다(D-94 계열).

### Decision

1. **모듈 위치와 경계.** `operations/fleet/fleet/routing/`에 다음 파일을 둔다.
   - `graph.py`: 활성 `rosy.site_map/1`에서 차로(arc) 목록, 들어오는/나가는 인덱스, 접선, 길이를 만든다. 불변 객체이며 지도 버전 id를 갖는다.
   - `cost.py`: 차로 비용, 전이 각도 θ와 분류(`straight`/`left`/`right`/`uturn`), 휴리스틱
   - `planner.py`: A*(`heapq`), 결정적 동률 처리, 가상 출발/목표 상태
   - `snap.py`: 자세·좌표를 차로에 붙이기(D-489 5·6항)
   - `trip.py`: 경유지 구간 연결, 제외 규칙, 막힌 차로 진단, 결과 조립

   이 모듈들은 **순수**하다. 네트워크·DB·시계·FastAPI를 import하지 않는다. 서버(`server/trip_routes.py`)만 이를 부르고, 저장소에서 활성 지도를 읽고 로봇 스냅샷을 넘긴다. 외부 의존성은 표준 라이브러리뿐이다(networkx 없음).
2. **자료 구조.**
   - `Arc(id, edge_id, forward: bool, start_place, end_place, polyline, length_m, speed_cap_mps, drive_mode, robot_kinds, start_tangent, end_tangent)`. `two_way` 간선은 `edge_id` 하나에 `forward` 참·거짓 두 Arc가 된다.
   - 탐색 상태 = arc id. 가상 출발·목표는 `(arc id, s)`를 담는 특수 상태다.
   - `PlanRequest(map_version, robot_kind, drive_modes, max_speed_mps, start_pose, goal, via, arrive_yaw, speed_cap, blocked_edges, extra_cost)`
   - `Plan(segments[(edge_id, forward, s_from, s_to)], places[], actions[(place_id, action, theta_deg)], length_m, eta_s, map_version)`
   - `PlanError(code, detail)`
3. **설정.** 사이트 설정 `fleet.routing` 절에 다음 기본값을 둔다.
   - `turn_cost_s` 2.0
   - `uturn_cost_s` 6.0
   - `place_pass_cost_s` 0.5
   - `straight_max_deg` 20
   - `uturn_min_deg` 135
   - `heading_tol_deg` 60
   - `snap_width_factor` 2.0

   범위 밖 값은 기동 때 거절한다. 장소 종류에 `turnaround`를 더한다(D-488 1항 장소 종류 확장).
4. **오류 코드(HTTP 422, `{error:{code, detail}}`).** 기존 Fleet 오류 모양을 따른다.
   - `TRIP_START_OFF_MAP`
   - `TRIP_HEADING_CONFLICT`
   - `TRIP_OFF_MAP`
   - `TRIP_UNKNOWN_PLACE`
   - `TRIP_NO_ROUTE`(`detail.segment`, `detail.unblock_would_help`)
   - `TRIP_ARRIVE_YAW_UNREACHABLE`
   - `TRIP_NO_ACTIVE_MAP`
   - `TRIP_POSE_UNTRUSTED`(로봇 위치가 `LOCALIZED`가 아님)
5. **API 계약.** `POST /api/fleet/robots/{robot_id}/trip`. 이름 있는 operator 이상이고 감사 기록을 남긴다.
   - 본문: `{to: "<place id>" | {x, y, yaw?}, via?: ["<place id>"], arrive_yaw?, speed_cap?, execute?: false}`
   - 응답 200: `{plan_id, map_version, segments, places, actions, length_m, eta_s, expires_at}`
   - `execute`가 기본 거짓이면 계획만 돌려준다. 실행은 `POST /api/fleet/trips/{plan_id}/start`로 따로 한다. 같은 지도 버전이고 계획 뒤 30 s 안이어야 한다. 실행 경로는 D-488 M2 이후에 연다. M1은 계획 응답과 콘솔 미리보기까지다.
   - API Reference에 행을 더한다.
6. **성능 예산.** 차로 500개 그래프에서 계획 1회는 호스트 기준 p95 20 ms 이하로 한다. 시험이 이를 잰다. 그래프 객체는 활성 지도 버전마다 한 번 만들어 캐시한다.
7. **시험.**
   - **(a) 무작위 그래프 성질 시험:** 시드를 고정한 무작위 방향 그래프 200개에서 A* 비용 = 같은 상태 공간의 Dijkstra 비용이어야 한다(휴리스틱 admissible 확인).
   - **(b) 규칙별 단위 시험:** 일방, U턴 금지/`turnaround` 허용, 회전 금지, `arrive_yaw`, 경유지에서 U턴하지 않음, 좌표 붙이기 경계(폭 ×2), 출발 방향 충돌, 제외 규칙과 `unblock_would_help`, 결정적 동률(같은 입력 100회 같은 결과), 교차로 동작 부호(좌/우)
   - **(c) 골든 경로:** `map_v2_fleet` 가져온 지도에서 대표 장소 쌍 5개의 차로 순서를 고정한다.
   - **(d) API 시험:** 오류 코드, 권한, 감사 행
   - **(e) 성능 시험(6항)**
   - 결과는 `known_failures` 비교로 0 new여야 한다.
8. **로그.** 계획마다 `plan_id`, 지도 버전, 요청 요약, 결과 요약(차로 수·길이·시간·오류 코드)을 Fleet 감사에 남긴다. 로봇 토큰·좌표 원문 외의 비밀은 없다.

### 범위 밖

- trip 실행 상태기계와 로봇 지시 전송(D-488 M2), 다중 로봇 예약(후속 교통 ADR), 콘솔 지도 편집 UI의 세부(D-488 M1 콘솔 항목이 맡는다)

### Consequences

- 계획기는 지도·자세·설정만 받는 순수 함수라 콘솔 미리보기, 시험, 재계획이 같은 코드를 쓴다.
- 비용 상수는 사이트 설정이라 실차 데이터로 조정할 수 있고, 조정해도 코드는 바뀌지 않는다.
- 교통 층은 `blocked_edges`와 `extra_cost` 입력으로만 끼어든다.

### 구현 부록 (2026-10-07)

M1 구현과 독립 검토에서 정한 것이다. 원래 번호는 D-486이었고 main 번호 충돌로 D-490이 됐다. API Reference는 v1.111이다(v1.109·v1.110은 다른 가지가 먼저 썼다).

1. **오류 본문.** 4항의 `{error:{code, detail}}` 대신 Fleet의 FastAPI 오류 모양 `{"detail": {"code", "detail"}}`을 쓴다. 지도 API(`/api/fleet/site-map/*`)도 같은 모양이다. 스키마에 맞지 않는 초안은 422 `SITE_MAP_INVALID`이고 `detail.errors`에 필드 위치와 이유만 담는다(보낸 값은 되돌려 주지 않는다). 콘솔은 그 필드 오류를 보인다. 계획기의 예상하지 못한 실패는 같은 본문의 500 `TRIP_PLAN_FAILED`다(서버 결함이라 요청 거절인 422가 아니다, 재검토 L2). 맨 추적 내용은 내보내지 않고 지도 버전마다 한 번만 로그에 남긴다.
2. **자세.** 로봇 스냅샷 자세에 yaw가 없으면 `TRIP_POSE_UNTRUSTED`다.
3. **지도 버전.** M1에서 요청과 그래프의 지도 버전이 다르면 `TRIP_NO_ACTIVE_MAP`이다. M2의 `/trips/{plan_id}/start`는 계획 뒤 지도가 바뀌면 `TRIP_MAP_CHANGED`로 거절한다. 그때까지 `/start`와 `execute: true`는 501 `TRIP_EXECUTION_NOT_AVAILABLE`이다.
4. **활성화 검사.** 활성화는 그래프와 후속 차로 표를 미리 만들어 보고, 계획기가 쓸 수 없는 지도면 거절한다. 그래프와 표는 지도 버전마다 한 번 만든다.
5. **계획 기록 보존.** 계획과 거절(`UNKNOWN_ROBOT`, 자세 조회 실패 포함)은 모두 기록하고, 최근 1000건이면서 30일 안의 것만 남긴다.
6. **시험.** 7항 (a)는 계획기 코드를 쓰지 않는 교과서 Dijkstra와 비교한다(장소·좌표 목표, 경유지, 차로 추가 비용). (e)는 캐시를 채운 뒤 40회의 p95를 재고, 바쁜 호스트에서는 두 번까지 다시 잰다. 예산 20 ms는 그대로다.
