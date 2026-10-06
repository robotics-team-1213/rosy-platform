## D-474 로봇은 주의점 정지선에서 멈추고 Fleet의 구역 허가를 받아 진입하며, 출구 표시를 지나면 점유를 푼다

**Status:** Accepted (2026-10-06, 사용자 설계 승인 — 바닥 표시 카메라 감지, 출구 표시로 해제, Fleet이 허가를 보내는 방식. 구현·SIM·DEVICE·FIELD 별도)

잇는 결정: [D-151](D-151-.md)(도로 증거 gate) · [D-384](D-384-road-state-estimator-and-road-behaviour.md)(도로 상태·행동, stop_and_go) · [D-426](D-426-fleet-gazebo-end-to-end-conformance.md)(구간 예약·점유) · [D-438](D-438-fleet-stuck-resolver-rules-model-human.md)(Fleet 판단 루프).

### Context

사용자 요구(2026-10-06): 로봇이 주의점에 오면 Fleet에 로타리 점유 여부를 확인하고, 비어 있을 때만 들어간다.

main의 현재 상태:
- CORE `traffic_policy`는 카메라 정지선 증거로 `stop_and_go`(정지 → dwell → 진입)를 한다. Fleet에 묻지 않는다(`core_features/traffic_policy/manager.py` `_verdict`).
- Fleet `server/traffic_reservations.py`는 FREE→RESERVED→OCCUPIED→RELEASING→FREE 저장소다. 호출하는 경로가 없다.
- 정지선 인식기(`middleware/perception/control/sensing/perception/road.py`)는 단선과 이중선을 구분하지 못한다. 실물에서는 거리 추정이 꺼져 있고(`camera_homography_enabled: false`) 흰 벽을 정지선으로 오인한다.
- Fleet→로봇은 REST, 로봇→Fleet은 상태 조회와 FleetAgent 이벤트뿐이다. 로봇이 묻고 Fleet이 답하는 메시지는 없다.

### Decision

1. **구역은 사이트 설정으로 선언한다.** Fleet `--zones <file>`이 `zones: [{zone_id, map_id, capacity}]`를 읽는다. v1은 `roundabout` 하나, 수용 1대다. 로봇은 구역 ID를 설정 `traffic_policy.zone_id`로 안다. 여러 구역은 마커 ID가 생길 때 별도 결정한다.
2. **바닥 표시는 두 종류다.** 차선을 가로지르는 흰 단선은 진입 주의점(`caution`), 간격을 둔 두 줄의 이중선은 출구(`exit`)다. 인식기는 정지선에 `kind: caution | exit`를 붙인다. 이 필드는 `road/observation` → `RoadEvidence.stop_line_kind`로 이어지며, D-18에 따라 API Reference·공유 schema·생산자/소비자 시험과 같은 커밋에서 확정한다.
3. **CORE에 `junction_rule: fleet_grant`를 더한다.**
   - `caution` 선 앞 `stop_distance_m`에서 STOP_REQUIRED가 되면 요청 ID를 만들고 `WAIT_GRANT`로 멈춘다. 상태는 `GET /api/v1/traffic`의 `zone_wait: {zone_id, request_id, since}`로 보인다.
   - 진입은 유효한 허가가 있을 때만 PROCEED다. 허가가 없거나, 만료됐거나, 요청 ID·구역·세대가 다르면 HOLD를 유지한다. 기다린 시간이 길어도 스스로 진입하지 않는다.
   - 선을 넘어 정지선이 보이지 않게 되면 `zone_state: INSIDE`가 되고 이벤트 `traffic.zone_entered`를 낸다.
   - `exit` 선을 보면 `traffic.zone_exited`를 내고 `INSIDE`를 끝낸다. 출구 선은 정지시키지 않는다.
   - E-stop·모드 변경·reset은 대기와 허가를 버린다. `INSIDE` 기록은 버리지 않는다(Fleet이 해제를 판단).
4. **허가는 Fleet이 CORE REST로 보낸다.** `POST /api/v1/traffic/zone-grant` 본문 `{zone_id, request_id, grant_id, expires_at}`. 운용자 역할이 필요하다. 만료는 발급 후 5초이며, 로봇은 선을 넘는 순간 다시 검사한다.
5. **Fleet 판단 루프.**
   - 기존 로봇 상태 조회에서 `zone_wait`를 보면 예약 저장소에 요청한다. 구역이 FREE이고 대기열의 첫 번째면 RESERVED로 바꾸고 허가를 보낸다. 아니면 요청 시각 순서로 줄을 세운다.
   - `traffic.zone_entered`(또는 상태의 `INSIDE`)를 보면 OCCUPIED, `traffic.zone_exited`를 보면 FREE로 바꾸고 다음 대기 로봇에 허가를 보낸다.
   - 허가를 보냈는데 만료 전에 진입이 확인되지 않으면 RESERVED를 풀고 다시 판단한다. 로봇이 아직 선 앞에서 기다린다는 것이 상태로 확인될 때만 푼다.
   - 시간 만료나 링크 상실로 OCCUPIED를 풀지 않는다(D-426 3항). 점유 로봇과 연결이 끊기면 UNKNOWN으로 두고, 그동안 다른 로봇에게 허가하지 않는다.
6. **운용자 해제.** 콘솔 구역 패널은 상태·점유 로봇·대기열을 보여 주고, 이름 있는 운용자가 사유를 적어 해제할 수 있다. 해제는 감사 기록에 남는다.
7. **인식 전제는 실물에서 따로 맞춘다.** 실물에서는 보정 저장소의 카메라 높이·pitch로 homography를 켜고, 정지선 탐색을 차선 영역 안으로 제한해 벽 오인을 줄인다. 이 전제가 통과하기 전에는 실물 `traffic_policy`를 ENFORCED로 두지 않는다. `map_id`는 사이트 지도(`map_v2_fleet`)와 맞춘다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 로봇이 FleetAgent EVENT로 묻고 응답에 허가 | 로봇마다 Agent 토큰 등록이 필요하고 응답 계약이 바뀜. 기각 |
| 로봇이 Fleet REST를 직접 호출 | 새 인증 방향·자격이 생김. 기각 |
| 지도 좌표로 주의점 판단 | 실물 위치추정이 아직 없음. 기각(사용자 선택) |
| 주행 거리나 시간으로 해제 | 미끄러짐·구역 안 정지에 약하고 D-426과 충돌. 기각 |

### Acceptance

- 단위: 인식기 단선·이중선·벽 음성 사례, `fleet_grant` 상태 전이(허가 없음·만료·다른 요청·E-stop), Fleet 루프(대기열 순서, 진입 미확인 해제, UNKNOWN 유지, 운용자 해제).
- Gazebo: 모델 PC 또는 관제 PC에서 실행한다(이 노트북에서 실행하지 않는다). `map_v2_fleet` 월드에 로타리 진입 단선 4개와 출구 이중선 4개를 그린다. 1대: 멈춤 → 허가 → 진입 → 출구 해제. 2대: 두 번째 로봇은 첫 로봇이 나갈 때까지 대기하고, 두 로봇이 동시에 구역 안에 있는 순간은 0이다. 음성: Fleet 정지 시 로봇은 계속 멈춰 있다.
- 실물: 7항 전제 통과 후 9dfk 1대로 멈춤·허가·진입·해제를 기록한다. 2대 실물 수용은 두 번째 로봇이 연결된 뒤 별도로 한다.

**References:** `middleware/core/services/core_features/traffic_policy/manager.py`, `middleware/perception/control/sensing/perception/road.py`, `operations/fleet/fleet/server/traffic_reservations.py`, `contracts/foundation/config/rosy_default.yaml` `traffic_policy`.
