## D-759 굽이 통과(D-507 보충)의 진입 직선은 로봇이 향한 쪽이 아니라 지도의 차로 방향으로 놓는다 — Fleet이 차로 방향과 yaw 쌍을 `map_entry`로 보내고 CORE가 odom으로 옮긴다

**Status:** Proposed (2026-10-14, 소유자와 맞춘 방향 "경로는 지도에서 오고, 인식은 표만 던진다"). SOURCE 구현과 호스트 단위 시험까지다. SIM·DEVICE 수용은 열려 있고, 이 ADR은 그 통과를 주장하지 않는다.
**Date:** 2026-10-14

잇는 결정: [D-507](D-507-lane-trip-leg-structure-and-site-floor.md) 보충(지도 기반 굽이 통과, `bend`) · [D-744](D-744-map-anchored-lane-arc.md)(차로 호의 지도 고정, 자세 쌍과 odom 시각) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3항(Fleet 지도 자세) · [D-517](D-517-multi-robot-lane-traffic.md) 4항(`pose_stamp`와 같은 시계).

## Context

1. D-507 보충의 굽이 통과는 odom 경로를 따른다. 경로는 닻 `(x, y, yaw, travel)`에서 시작한다. 닻은 카메라가 곧게 추종하던 마지막 틱의 로봇 자신의 odom 자세다(`bend.py::_bend_armed`). `_start_bend`는 그 yaw를 따라 남은 거리만큼 직선을 긋고, 그 뒤에 호와 나가는 직선을 잇는다. CORE는 지도 자세를 모르므로 "곧게 추종하던 로봇이 향한 쪽이 차로 방향"이라고 가정한다.
2. Gazebo 측정(2026-10-14, map_v2_fleet, 정책 enforce, run56·run62·run63·run64, 모두 굽이 W3). W4와 W3은 0.58 m 떨어져 있다. W4를 나온 로봇은 차로 안쪽으로 5 cm 치우쳐 있었고 추종기가 되돌리는 중이었다. W3 통과가 넘겨받은 틱(W3 꼭짓점 0.42 m 앞)에 로봇 yaw는 2.764 rad, 차로 방향은 π였다. 21.6° 어긋나 벽을 향했다(차로 중심에서 벽까지 0.116 m). 경로는 그 방향으로 0.2 m를 갔다. 로봇은 중심을 벽 쪽으로 2.2 cm 넘어 21° 벽을 향한 채 섰고, SDK 전방 호 sweep(`trajectory_changed`, can_rotate false)과 CORE 몸 sweep이 모두 호를 거절했다. 통과는 `motion_unconfirmed`로 끝났고 trip이 끝났다. 기록의 자세 `(x, y, yaw)`: armed `(-0.825, 0.455, 2.96)` → 넘겨받음 `(-0.847, 0.461, 2.764)` → aborted `(-1.021, 0.531, 2.777)`.
3. 시제품(run66). 시뮬레이터 overlay에서 W3·W2·W1의 닻 yaw를 지도의 차로 방향으로 바꿨다(로봇 yaw가 그 방향에서 44° 안일 때). Fleet이 센 16바퀴 동안 굽이 중단이 없었다. 그 전에는 2–3바퀴였다. **이 시제품은 시뮬레이터에서 odom 좌표가 지도 좌표와 같다는 점에 기댔다. 이 ADR의 구현이 아니고, 이 구현의 증거도 아니다.** 방향을 지도에서 가져오면 이 실패가 사라진다는 것만 보였다.
4. Fleet은 로봇의 지도 자세와 그 자세가 묶인 odom 표본의 시각(`odom_stamp`)을 안다(D-494 3항). 굽이의 호 시작점에서 차로가 향하는 방향도 지도에서 안다. D-744가 차로 호의 원에 대해 같은 재료(자세 쌍 하나)로 같은 일을 이미 한다.

## Decision

1. **굽이 지시에 지도의 진입 방향을 싣는다.** `POST /api/v1/line-follow/junction`의 `action: bend`에 선택 객체 `map_entry`를 더한다.

   | 필드 | 단위 | 뜻 |
   |---|---|---|
   | `yaw_rad` | rad, 지도 좌표 | 굽이의 호 시작점에서 차로가 향하는 방향(진입 직선의 방향) |
   | `pose_yaw_rad` | rad, 지도 좌표 | Fleet이 본 로봇의 지도 yaw |
   | `odom_stamp_s` | UTC epoch 초 | 그 지도 자세가 묶인 odom 표본의 시각 |

   `odom_stamp_s`는 D-744 1항과 같은 값이다(CORE가 odom을 받은 때의 CORE 벽시계, 스냅숏 `odom_pose.stamp`). 세 값은 모두 유한한 수여야 하고 두 yaw는 ±6.2832 안, `odom_stamp_s`는 0보다 크다. 어기거나 `bend`가 아닌 지시에 실으면 400이다(매니저는 `ValueError`). 위치는 싣지 않는다. 방향만 옮기는 데에는 yaw 쌍이면 된다(한계 1).
2. **능력 `lane_bend_map_entry`.** CORE는 `controls`의 `base_velocity`에 `lane_bend_map_entry`를 알린다. 값은 `lane_bend`와 같다. Fleet은 이 능력이 참이고, 이번 주기에 로봇을 찾은 지도 자세에 `odom_stamp`가 있을 때만 `map_entry`를 보낸다(D-744 2항과 같은 조건). 그 밖에는 지시가 오늘과 같다.
3. **CORE는 받을 때 odom으로 옮긴다.** 지시를 받은 때 자기 odom 기록에서 `odom_stamp_s`의 표본을 찾고(D-744 3항의 조회를 `_odom_at_stamp`로 꺼내 같이 쓴다), 차로 방향을 odom으로 옮겨 지시와 함께 둔다: `entry = wrap(odom_yaw(odom_stamp_s) + yaw_rad − pose_yaw_rad)`. 받을 때 옮기는 이유는 D-744와 같다. CORE의 자세 기록은 짧고(약 2 s), 지시는 호 시작점 0.6 m 앞에서 온다. `armed` 중의 재전송(만료 연장)은 둔 방향을 바꾸지 않는다. 재전송은 오늘도 `bend_in_m`을 바꾸지 않는다.
4. **넘겨받을 때 닻의 방향을 그 방향으로 바꾼다.** `_start_bend`는 닻의 yaw(곧게 추종하던 마지막 틱의 로봇 yaw)가 둔 방향에서 30° 안이면 닻의 yaw를 둔 방향으로 바꾼다. 닻의 위치와 `travel`은 그대로다. 그 뒤는 오늘과 같다. 진입 직선, 호, 나가는 직선(`target = entry + turn`)이 모두 그 방향에서 나온다. D-507 보충 9항(굽이 자신의 바깥선)은 닻의 yaw를 진입 축으로 읽으므로 같은 축을 쓴다. `bend_in_m`, `bend_tol_m`, 앞당김 창(0.25 m), 중단 규칙, D-422 sweep, `motion_admitted`는 바뀌지 않는다.
   - 30°는 새 숫자가 아니다. 이 모듈이 "이 방향은 그 차로의 방향이다"라고 받아들일 때 이미 쓰는 한도 `REACQUIRE_HEADING_RAD`다(굽이·회전 뒤 재획득, 통과 끝의 교차로 감지). 측정한 21.6°를 8.4° 여유로 포함한다. D-744의 25°(`ARC_ANCHOR_MAX_HEADING_RAD`)는 제자리 회전 끝 오차 10°에 맞춘 값이라 여유가 3.4°뿐이다. 시제품의 44°는 근거가 되는 기존 상수가 없어 쓰지 않는다.
   - 한도를 넘으면 지도 yaw가 틀렸거나 로봇이 차로를 잃은 것으로 보고 오늘의 닻을 쓴다.
5. **실패하면 오늘의 닻이다.** 아래 가운데 하나면 로봇 자신의 yaw로 놓는 오늘의 닻을 그대로 쓴다. 지시는 거절하지 않는다.
   - `map_entry`가 없다(`none_sent`).
   - 받은 때 `odom_stamp_s`가 2 s보다 오래됐거나(`stale`) CORE 시계보다 0.05 s 넘게 앞선다(`future`). D-744의 `ARC_ANCHOR_MAX_AGE_S`, `STAMP_TOL_S` 그대로다.
   - 그 시각의 odom 표본이 기록에 없다(`no_sample`). 그 표본의 odom epoch·frame이 지금과 다르다(`epoch`).
   - 받은 뒤 넘겨받을 때까지 odom 경로 길이가 1.5 m를 넘는다(`carry`, D-744의 `ARC_ANCHOR_MAX_CARRY_M`). 받은 뒤 odom epoch·frame이 바뀌면 굽이 통과 자체가 오늘처럼 `odom`으로 중단된다.
   - 넘겨받을 때 닻의 yaw가 둔 방향에서 30° 넘게 어긋나 있다(`heading`).
6. **기록.** `GET /api/v1/line-follow`와 스냅숏의 `line_follow.junction`에 `map_entry_used`(bool)와 `map_entry_reason`(string 또는 null)을 더한다. `map_entry_used`는 그 통과의 닻이 지도 방향으로 놓였을 때만 참이다. `map_entry_reason`은 쓰지 않은 까닭 `none_sent`·`stale`·`future`·`no_sample`·`epoch`·`carry`·`heading` 가운데 하나다. 썼으면 null이고, 방향을 두었지만 아직 넘겨받지 않은 `armed`에서도 null이며, `bend`가 아닌 지시에서는 늘 false와 null이다. 지시가 끝나 `idle`이 되면 값도 기본으로 돌아간다.

## 바뀌지 않는 것

- `map_entry`가 없는 지시의 동작은 줄 단위로 같다. 기존 굽이 시험은 고치지 않았다.
- 닻의 위치, `bend_in_m`·`bend_tol_m`·`bend_radius_m`의 뜻과 범위, 경로 추종(pure pursuit), 거리·시간 상한, `off_path` 0.06 m, 중단 사유는 그대로다.
- CORE는 여전히 지도 자세를 갖지 않는다. 받은 yaw 쌍 하나로 방향 하나를 odom에 옮길 뿐이고, 그 값을 다른 판단에 쓰지 않는다.
- CORE가 최종 `/cmd_vel`의 유일한 발행자다. Fleet은 명령을 내지 않는다.
- envelope `protocol_version`은 그대로다. API Reference는 additive로 v1.224다.

## 한계

1. **방향만 옮긴다. 횡 위치는 지도에서 오지 않는다.** 경로는 닻의 위치를 지나 차로와 나란히 놓인다. 로봇이 차로 중심에서 옆으로 벗어나 있던 만큼(측정 사례는 안쪽 5 cm) 경로도 그만큼 벗어난 채 굽이를 돈다. 그 오프셋을 닫는 항은 넣지 않았다. 넣으려면 호 시작점의 지도 위치와 자세 쌍의 위치가 더 필요하고, `bend_in_m`의 odom 이동 거리 규칙과 `off_path` 한도를 함께 다시 정해야 한다. 별도 결정으로 둔다.
2. **Fleet 지도 yaw의 오차가 그대로 경로 방향의 오차다.** 전에는 로봇 yaw의 어긋남이 그 자리에 있었다. 오차 δ는 호 시작점에서 `남은 직선 × sin δ`의 횡 오차가 된다(0.2 m에서 5°면 1.7 cm). 천장 카메라 sighting 사이는 Fleet도 odom으로 잇는다.
3. 받은 때부터 넘겨받을 때까지는 CORE의 odom yaw로 잇는다. 그 사이의 odom yaw 표류는 걸러지지 않는다. 1.5 m 한도는 D-744의 시작값을 그대로 가져온 것이고 굽이에 대해 따로 재지 않았다.
4. 30° 검사는 넘겨받는 틱의 로봇 yaw가 아니라 닻의 yaw(곧게 추종하던 마지막 틱)와 한다. 닻은 넘겨받기 전 최대 0.25 m(앞당김 창) 앞의 자세일 수 있다. 그 사이에 로봇이 더 돌았으면 경로와 몸의 방향 차는 30°보다 클 수 있고, 그때는 오늘처럼 pure pursuit와 `off_path`가 판단한다.
5. 풀지 못한 `map_entry`는 조용히 오늘의 동작이 된다. 운전자에게 따로 알리지 않고 `map_entry_reason`에만 남는다. 측정한 실패는 그 경우 그대로 다시 날 수 있다.
6. `odom_stamp_s`는 CORE 벽시계다. D-744 한계 6(시계가 뛰는 경우)이 그대로 적용된다.
7. 호스트 시험의 rig는 운동학 고리다. 추종기의 조향, 벽, SDK sweep은 없다. 측정 사례는 "넘겨받을 때 yaw가 21.6° 어긋남"만 옮겼다.

## 검증 상태

- **SOURCE·호스트 단위 시험만 했다.** `middleware/core/services/test/test_junction_bend.py`(측정 사례: `map_entry`가 있으면 진입 직선이 차로 방향이고 통과 끝이 나가는 직선에서 2 cm 안, 없으면 오늘처럼 로봇 yaw를 따라 벽 쪽으로 6 cm 넘게 벗어남; yaw 쌍으로 옮기기; 29°는 쓰고 31°는 `heading`; `stale`·`future`·`no_sample`·odom 재시작·`carry`; 잘못된 객체 거절; 9항 축), `middleware/core/gateway/test/test_line_junction_api.py`·`test_capabilities_controls.py`(400, 기록, 능력), `operations/fleet/test/test_trip_bend.py`(능력과 `odom_stamp`가 있을 때만 실음, 값은 호 시작점의 차로 방향과 찾은 자세의 yaw 쌍).
- **SIM: 열려 있다.** 이 구현으로 Gazebo map_v2_fleet 한 바퀴를 돌리지 않았다. run66은 다른 코드(3항)다.
- **DEVICE: 열려 있다.**
