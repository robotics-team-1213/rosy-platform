## D-726 경로 사실 묶음과 호출자가 넘기는 차로 맥락

**Status:** Accepted (2026-10-12, source contract)

## Context

Fleet에는 경로를 만드는 자리가 넷이다. 칠해진 차로 그래프의 A*는 운행 계획이다. `/route`는 그 차로를 따라 짧은 점 하나를 기존 목표 경로로 보낸다. Nav2와 점유 격자 A*는 이 모터 런타임의 주행 경로가 아니다. 호출자는 목적지 말고 막힌 차로와 추가 비용을 계획에 넘길 자리가 없었고, 응답은 어느 계획기가 무엇을 받았는지 말하지 않았다. AI나 다른 시스템은 그 사실을 읽어야 후보를 낼 수 있다. Fleet이 정하고 CORE가 움직인다.

0.20 m 현은 링에서 차로 안에 남는다. 동쪽·서쪽의 긴 굽이에서는 그 현이 공칭 차체를 가져온 차로 밖으로 내보낸다. 이 단축은 `/route`의 점 목표만 해당한다. 차로 운행은 선을 따른다. D-557의 링 랩 기록 전에는 선 추종·차로 유지·Fleet 경로를 링 수정으로 바꾸지 않는다.

## Decision

`POST /api/fleet/robots/{robot_id}/trip`과 `POST /api/fleet/robots/{robot_id}/route`의 200 응답에 `context`를 더한다. `role`은 `fact`다. 이 객체는 명령이 아니다. `command`, `decision`, WAIT, YIELD, RESUME, ABORT, MANUAL을 담지 않는다.

`context`는 이 답을 만든 `planner`, 호출자가 채운 `supplied`, 그 계획기가 잡은 `holds`, 그리고 네 계획기의 목록 `planners`를 담는다. 각 계획기는 `id`, `live`, `motion`, `give`, `note`를 가진다.

- `lane_graph`: Fleet이 돌린다. 동작은 `line_follow`. 받는 값은 `to`, `via`, `arrive_yaw`, `speed_cap`, `blocked_edges`, `extra_cost`. `note`는 `plan_only`다. 계획은 로봇을 움직이지 않는다.
- `lane_step`: Fleet이 돌린다. 동작은 `short_point`. 받는 값은 `edges`. `note`는 `one_point_goal`이다. 짧은 점 하나를 기존 목표 경로로 보낸다.
- `nav2`: 이 런타임에서 돌리지 않는다. 동작은 `open_floor`. 받는 값은 `x`, `y`, `yaw`. `note`는 `not_this_runtime`이다.
- `grid`: 이 런타임에서 돌리지 않는다. 동작은 `occupancy`. 받는 값은 `goal`. `note`는 `not_this_runtime`이다.

trip의 선택 `blocked_edges`(차로 id, 최대 32, 중복 없음)와 `extra_cost`(차로 id당 0 이상의 유한한 초, 최대 32)는 그 계획에 들어간다. 활성 지도에 없는 id는 422 `TRIP_UNKNOWN_EDGE`와 `detail.edge`다. 막힌 차로 옆에 다른 차로가 있으면 그 경로를 반환하고, 남은 차로가 없으면 기존 422 `TRIP_NO_ROUTE`다. 빈 값은 지금과 같은 경로다. 차로 id는 그 차로의 양방향을 막거나 비용을 더한다. 재계획은 이 `blocked_edges`를 교통 차단과 합치고 `extra_cost`를 유지한다. `context`는 실행 plan 안이 아니라 그 옆에 기록한다.

`/route`의 다음 점은 0.20 m다. 그 현이 공칭 차체를 가져온 차로 밖으로 내보내면 점은 0.12 m까지 줄고, 장치 목표 공(0.10 m)보다는 길다. 남은 거리가 0.12 m 이하면 끝을 유지한다. `holds`는 `complete`, `step_m`, `chord_m`, `body_clear_m`, `body_inside`, `s_m`이다. 링의 0.20 m 현은 차체 여유 안이라 줄이지 않는다.

## Consequences

필드를 보내지 않는 기존 trip과 `/route`의 경로는 같다. `execute: true`는 501로 남고, 출발은 `POST /api/fleet/trips/{plan_id}/start`다. 신뢰할 자세, 차로 카메라, LOCALIZED, `goal_navigation` 거절은 그대로다. Nav2를 켜지 않고, 선 추종·차로 유지·자유 구간의 0.20 m 점을 바꾸지 않는다. 이 점 단축은 링을 달리게 하지 않는다. D-557의 모델 PC 랩 기록이 가리키기 전에는 그 링을 여기서 고치지 않는다. envelope 1.0과 CORE의 최종 속도 권한은 유지한다. 공유 API 문서는 v1.219다.
