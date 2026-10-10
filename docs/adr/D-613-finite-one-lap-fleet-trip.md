## D-613 관제에서 정하는 유한 한 바퀴 Fleet trip

**Status:** Proposed (2026-10-10, 사용자 목표: 두 로봇 각각 한 바퀴 후 원위치 정지; SOURCE 구현 후보, 현장 수용 전)

### Context

D-517의 `repeat: true`는 계속 도는 운행이다. 현장 `map_v2_fleet` v5에는 `kind: start` 장소가 없고 양쪽 고리의 `W_mid`, `E_mid`가 `kind: stop`이다. 기존 관제 반복 버튼은 이 지도에서 비활성이고, 한 바퀴 후 자동 정지라는 목표와도 맞지 않는다. 일반 유한 trip의 `to`·`via`는 출발 위치가 운영자가 고른 복귀 장소인지 보증하지 않는다.

### Decision

1. 관제는 정지 가능한 두 장소를 출발·복귀 장소와 경유 장소로 고른다. `POST /trip`에 `to: start_at`, `via: [other]`, `repeat: false`, `start_at: place_id`를 보낸다. Fleet은 기존 지도 A* 계획, 별도 시작 승인, D-517 교통 블록, D-494 정지·재계획을 재사용한다. 두 로봇은 각각 독립된 plan/trip이다.
2. `start_at`은 선택 필드다. 있을 때는 유한 trip이고, `to`와 같으며, 다른 `via`가 있어야 한다. 계획 때와 시작 직전에 `LOCALIZED` 지도 자세가 그 장소에서 0.05 m 이내여야 한다. 아니면 `TRIP_START_PLACE_MISMATCH`로 거절한다. D-517의 구역 규칙이 최종 정지를 다른 곳으로 옮겨야 하면 `TRIP_START_PLACE_MOVED`로 거절한다. 필드가 없는 기존 요청은 그대로 동작한다.
   - 시작 직전 선택된 첫 경로 구간의 중심선 거리와 D-424 Pinky Pro 공칭 몸 반폭 합이 그 구간 반폭을 넘으면 `TRIP_START_BODY_OUTSIDE_ROUTE`로 거절한다. 지원하는 차체 치수가 없거나 이동할 계획 구간이 없으면 각각 `TRIP_BODY_UNKNOWN`, `TRIP_NO_ROUTE`로 거절한다. 이 검사는 시작 명령을 보내기 전에 실행한다.
3. Fleet과 CORE가 주행·안전 권한을 갖는다. AI PC의 계획 경로 이탈 분석은 별도 그림자 사실로 검증한 뒤 연결하며 직접 로봇을 움직이지 않는다. 현장 설치 전에는 `rosy_40`의 `junction_turn:false`와 두 로봇의 주행·정지 근거를 해결해야 한다. 능력 광고를 강제로 참으로 바꾸지 않는다.
   - 관제는 교착 여부와 관계없이 열린 trip이 있으면 기존 `/api/fleet/ai`를 조회한다. 같은 로봇·trip·지도 버전의 최신 `trip_route_check`가 유효 시간 안의 `OFF_ROUTE`일 때 예외 큐에 허용 경계 초과 거리를 경고한다. 새 `ON_ROUTE`·`UNKNOWN`, 만료, trip 종료는 경고를 지운다. 이 표시는 주행 명령을 만들지 않는다.

### Consequences and evidence

`W_mid`와 `E_mid`처럼 차선의 끝이 아닌 이름 있는 장소도 유한 trip의 도착점이다. 계획의 마지막 `actions[].place_id`에 선택한 장소 ID를 보존하고, Fleet은 그 ID로 마지막 차선의 `stop_after_m` 정지 명령을 보낸다. 반복 lap은 기존의 차선 끝 장소 기준을 유지한다. 좌표만 지정한 차선 중간 목적지는 안전한 정지 장소로 승격하지 않아 `LANE_END_NOT_A_PLACE`로 거절한다. 두 유한 trip의 분리된 출발·정지와 기존 반복 lap은 원격 시험으로 확인하고, 실제 정지 거리는 DEVICE·FIELD에서 검증한다.

API reference v1.199의 Fleet `/trip` 요청과 시작 거절이 추가된다. CORE API·envelope 1.0은 바뀌지 않는다. SOURCE·원격 호스트 테스트·Gazebo·DEVICE·FIELD는 별도 증거다. 두 로봇 `arrived`와 실제 원위치 정지, 독립 경계·간격 측정 전에는 목표를 완료로 표기하지 않는다.

현장 경로 재계산에서 중심이 차선 안이어도 차체가 먼저 경계를 넘는 표본이 확인됐다. Pinky Pro의 열린 trip view에 D-424 공칭 `body_half_width_m`를 실어 AI PC의 그림자 경로 사실이 `width_m/2 - body_half_width_m`를 한도로 쓰게 한다. 반폭이 없으면 `UNKNOWN`이다. Fleet trip의 중심 기준 정지는 D-511 M1 변경 전까지 그대로이므로 이 그림자 사실이나 호스트 시험을 차체 이탈 방지 증거로 취급하지 않는다.
