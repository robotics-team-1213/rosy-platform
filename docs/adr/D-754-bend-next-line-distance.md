## D-754 굽이 통과가 넘겨주는 목격은 지도가 가린다 — Fleet이 꼭짓점에서 다음 교차로 선까지의 거리를 `next_line_in_m`으로 보낸다

**Status:** Proposed (2026-10-14). 방향은 사용자 결정 "경로는 지도에서 오고, 인식은 한 표다"를 따른다. 범위는 아래 Decision 1–4항뿐이다. SOURCE 구현과 호스트 시험까지이며 SIM·DEVICE 수용은 열려 있다. SIM에서 W1→SW와 W3의 실제 값을 확인한 뒤 Accepted로 올린다.
**Date:** 2026-10-14

잇는 결정: [D-507](D-507-lane-trip-leg-structure-and-site-floor.md) 보충(지도 굽이의 odom 통과, 8항 넘겨주기, 9항 굽이 자신의 바깥선) · [D-744](D-744-map-anchored-lane-arc.md)(같은 사용자 결정의 앞 걸음, 필드·능력을 더하는 방식).

## Context

1. D-507 보충 8항: 굽이 통과 중에 잡힌 교차로 목격에 잰 선 거리(`junction_ahead_m`)가 있고 그 선이 아직 앞에 있으면, CORE는 그 목격을 다음 교차로로 넘기고 `waiting`(HOLD)으로 선다.
2. 추종기는 굽이 자신의 바깥 테이프도 교차로 선으로 읽는다. 9항은 진입 방향에서 읽은 경우를 모양으로 걸렀다(Gazebo run53: `junction_transverse` 0.318 m, 선이 꼭짓점 0.097 m 너머). 선 지점이 진입 축에서 꼭짓점을 넘었고 출구선을 따라 `CORRIDOR_HALF_M`·(1 + 1/tan|turn|) 안이면 넘기지 않는다(90°에서 0.10 m).
3. Gazebo map_v2_fleet run55(2026-10-13/14)에서는 호 가운데에서도 읽혔다. 굽이 W3(90°, 꼭짓점 약 (−1.2689, 0.5094), 서쪽으로 들어가 남쪽으로 나감)에서 추종기가 자세 약 (−1.231, 0.471, yaw −2.31 rad), 곧 47° 돈 자리에서 `junction_fork` 0.17 m를 냈다. 선 지점은 꼭짓점에서 출구선을 따라 0.164 m로 9항의 0.10 m 밖이다. 그래서 넘겨졌고 CORE는 `waiting`으로 섰다. Fleet은 trip당 3번뿐인 지도 표결 `straight`(map-clear) 하나를 여기에 썼다.
4. 정당한 경우인 굽이 W1(바로 뒤가 교차로 SW)도 모양이 같다. 호 가운데에서 잡히고 선 지점은 출구선을 따라 0.29–0.45 m다. 모양만으로는 둘을 가를 수 없다.
5. 지도는 가른다. W3 뒤의 다음 교차로 장소는 1 m 넘게 떨어져 있고, W1 뒤는 가깝다. Fleet은 trip의 남은 구간과 장소를 이미 갖고 있다.

## Decision

1. **굽이 지시에 선택 필드 하나.** `POST /api/v1/line-follow/junction`의 `action: bend`에 `next_line_in_m`을 더한다. 뜻은 굽이 장소(꼭짓점)에서 이 trip이 굽이 다음에 닿는 교차로 장소의 가로선까지, 차로를 따라 잰 거리다. 범위는 0 이상 2 이하의 유한한 수(`MAX_AHEAD_M`, 추종기가 재는 선 거리의 상한과 같은 값)이고 2는 "2 m 이상"이다. 범위 밖이거나 `bend`가 아닌 지시에 있으면 400 `VALIDATION_ERROR`다. 없거나 null이면 모름이고 동작은 오늘과 줄 단위로 같다(9항의 모양 규칙).
2. **능력 `lane_bend_next_line`.** CORE는 `controls`의 `base_velocity`에 `lane_bend_next_line`을 알린다. 값은 `lane_bend`와 같다. Fleet은 이 능력이 참인 로봇에만 필드를 보낸다.
3. **CORE는 필드가 있으면 지도 거리로 가린다.** 넘겨줄지 정하는 자리(`bend.py::_bend_step`의 `reacquiring`)에서 목격의 선 지점(목격을 닻 둔 odom 자세에서 그 yaw로 `junction_ahead_m` 앞)을 구하고, 꼭짓점에서 출구선을 따라 잰 거리 `out`을 구한다. 9항과 같은 계산이라 두 규칙이 한 함수(`_bend_line`)를 쓴다. `|out − next_line_in_m|`이 허용치 안이면 넘기고(`waiting`), 밖이면 넘기지 않는다. 넘기지 않으면 9항과 똑같이 목격을 지우고 통과는 `idle`로 끝난다. 필드가 있으면 9항의 모양 규칙과 60° 문턱은 쓰지 않는다. 지도가 판단한다.
4. **허용치.** `bend_tol_m + crosswalk_range_error_fraction × junction_ahead_m + CORRIDOR_HALF_M`. 세 항은 각각 다음을 덮는다.
   - `bend_tol_m`: 꼭짓점을 odom에 놓은 오차. Fleet이 `bend_in_m`을 아는 오차와 같은 값이다(D-507 보충 2항, 최소 0.12 m).
   - `crosswalk_range_error_fraction × junction_ahead_m`: 추종기가 잰 선 거리의 오차. 가로선 띠(`_centre_on_cross_line`)가 이미 쓰는 설정이다(기본 0.05).
   - `CORRIDOR_HALF_M`(0.10 m): 한 선을 읽은 거리가 프레임마다 퍼지는 폭이다(Gazebo에서 SW 선 하나가 0.29–0.45 m로 읽혔다). 가로선 위의 점은 어디든 출구선 방향 거리가 같으므로 옆 밀림을 덮는 항이 아니다(독립 검토 2026-10-14).

   run55 값으로는 0.12 + 0.05 × 0.17 + 0.10 = 0.229 m다. W3의 `out` 0.164 m는 1 m 넘는 지도 거리와 0.8 m 넘게 달라 넘겨지지 않는다.
5. **Fleet이 보내는 값.** `trip_ports.bend_fields`: 꼭짓점에서 굽이 호 끝까지 `bend_radius_m · tan(|turn|/2)`, 거기서 trip의 남은 구간을 따라 간선 끝 장소가 처음 나오는 구간 끝까지의 경로 거리, 그 장소에서 차로 방향으로 처음 만나는 칠한 선까지(`line_past`, 교차로 지시의 `pivot_past_line_m`을 정하는 같은 함수. 선을 못 찾으면 0)를 더한다. 0과 2 사이로 자른다. 굽이 장소는 간선을 나누지 않으므로 다음 굽이는 건너뛴다. 남은 경로에 간선 끝 장소가 없으면(차로 중간의 출발 장소에서 끝나는 trip) 보내지 않는다.

## 바뀌지 않는 것

- 굽이 지시의 다른 필드와 범위, 통과의 상태·경로·상한·운동 허가(D-422, `motion_admitted`), 넘겨준 뒤의 `waiting`과 기대 창 판정은 그대로다.
- `next_line_in_m`이 없는 지시, 능력이 없는 로봇, 굽이 장소가 없는 지도의 동작은 그대로다.
- Fleet의 지도 표결(map-clear)과 `junction_unexpected` 규칙은 그대로다. 이 결정은 그 표결을 쓸 일을 줄일 뿐이다.
- CORE는 지도 자세를 갖지 않는다. 받은 거리 하나를 자기 odom의 굽이 경로에 대어 볼 뿐이다.
- 상태 필드를 더하지 않는다. 어느 규칙이 걸렀는지는 지시에 필드가 있었는지로 안다(Fleet trip 기록의 `junction_fields`).
- envelope `protocol_version`은 그대로다. API Reference는 additive로 한 판 올린다(v1.222).

## 한계

1. 필드가 없으면 모름이다. 옛 Fleet, 능력 없는 로봇, 경로 끝의 굽이는 9항 그대로이고 run55의 경우도 그대로 넘겨진다.
2. 값은 Fleet 지도의 차로 거리다. 지도의 장소·차로·굽이 반지름이 틀리면 판단도 틀린다. 굽이 뒤 차로가 다시 휘면 차로 거리와 출구선을 따라 잰 직선 거리가 달라진다.
3. 굽이 자신의 선이 읽히는 자리(출구선을 따라 0.10–0.17 m)에서 허용치 안에 실제 교차로 선이 있으면 둘을 가르지 못하고 넘긴다. run55 허용치 0.229 m로는 `next_line_in_m`이 약 0.39 m 이하일 때다. 그때는 오늘처럼 `waiting`으로 서고 Fleet의 다음 지시와 기대 창이 판단한다.
4. 갈래 목격(`junction_fork`)은 칠한 선이 아니라 장소 점을 잰다(`_in_window`의 pivot 0). 그래서 갈래 목격은 지도의 선 거리보다 `MAX_PIVOT_PAST_LINE_M`(0.30 m)까지 짧아도 맞는 것으로 본다(검토 반영). 그만큼 갈래 목격의 구분은 느슨하다: 다음 선이 0.30 m + 허용치보다 가까우면 굽이 자신의 선을 읽은 갈래 목격과 갈리지 않는다.
5. 검토 반영(2026-10-14, code-reviewer): (1) 필드가 있어도 9항의 모양에 맞고 지도의 선이 그 범위 밖이면 버린다. 자세 허용치가 넓을 때(`bend_tol_m` 0.15–0.30) 가까운 교차로 앞 굽이에서 9항이 거르던 경우가 다시 넘어가지 않게 한다. (2) Fleet은 다음 장소의 칠한 선을 찾지 못하면 필드를 보내지 않는다(장소 거리를 대신 보내면 `junction_fields`의 반폭 가정과 0.10 m 어긋난다). (3) 걸려 있는 굽이 지시의 갱신은 `next_line_in_m`도 새 값으로 바꾼다. 실제 지도에서 Fleet이 W1과 W3에 보내는 값은 아직 계산해 보지 않았다.
5. 허용치의 세 항은 기존 값에서 가져온 시작값이다. SIM과 장치에서 다시 잰다.
6. 꼭짓점 위치는 9항과 같이 `bend_tol_m`과 odom 오차를 그대로 가진다.

## 검증

- SOURCE(모델 PC 원격 pytest, 이 노트북 아님): `test_junction_bend.py`에 지도 거리가 먼 호 가운데 목격(90° 0.17 m, 60° 0.4 m)이 `idle`로 끝남, 필드 없는 같은 목격은 예전처럼 `waiting`, 지도 거리가 맞으면 `waiting`이고 허용치 밖이면 `idle`, 진입 방향에서 읽은 선도 지도 거리로 가림, 범위 밖 값 거절, 능력. `test_line_junction_api.py`·`test_capabilities_controls.py`에 400과 능력. `test_trip_bend.py`에 능력 있는 로봇의 거리, 능력 없는 로봇의 지시 그대로, 차로 중간에서 끝나는 trip은 보내지 않음.
- SIM: 열림. run55 구간(W3)과 W1→SW를 `lane_bend_next_line` 로봇으로 다시 달려 W3에서 map-clear를 쓰지 않는지, W1→SW가 그대로 넘겨지는지 본다. 실제 지도에서 Fleet이 보내는 두 값은 아직 재지 않았다.
- DEVICE: 열림.
