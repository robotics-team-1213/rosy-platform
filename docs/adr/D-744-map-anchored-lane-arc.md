## D-744 차로 호(D-520)의 원은 로봇이 선 자리가 아니라 지도에 놓는다 — Fleet이 원 중심과 자세 쌍을 `exit_segment.map_anchor`로 보내고 CORE가 odom에 옮긴다

**Status:** Accepted (2026-10-13, 사용자 결정 "경로는 지도에서 오고, 인식은 위치를 고친다"). 범위는 아래 Decision 1–6항(호의 원을 지도에 고정)뿐이다. 「방향」 절은 이 ADR이 정하지 않는다. SOURCE 구현과 호스트 시험까지이며 SIM·DEVICE 수용은 별도다.
**Date:** 2026-10-13

잇는 결정: [D-520](D-520-map-guided-ring-arc-following.md)(호 주행, `exit_segment`, 2026-10-09 개정의 odom 원 추종) · [D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(교차로 지시 필드) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3항(Fleet 지도 자세) · [D-517](D-517-multi-robot-lane-traffic.md) 4항(`pose_stamp`와 같은 시계).

## Context

1. D-520 개정(2026-10-09)의 호는 odom에 놓은 원을 따른다. 그 원은 호가 열릴 때 로봇 자신의 자세로 놓는다(`lane_arc.py::_open_arc`). 중심은 `(x − sin(yaw0)/κ, y + cos(yaw0)/κ)`이고 `yaw0`는 회전 목표각이다. CORE는 자기 지도 자세를 모르므로, 제자리 회전이 끝난 자리가 원 위라고 가정한다.
2. Gazebo 측정(2026-10-13, map_v2_fleet 회전교차로, 반지름 0.25 m): 회전은 ring 바깥 2 cm, 접선에서 약 10° 어긋난 채 끝났다. 이어진 호 세 개(1.2 m) 뒤에 로봇은 차로에서 5 cm 벗어나 ring을 나갔고 차로를 다시 잡지 못했다. IR 보정은 몸이 약 6 cm 벗어난 뒤에야 작동한다. 원을 잘못 놓으면 호 제어기(`e_r`, `e_th`)는 그 잘못된 원을 정확히 따른다.
3. Fleet은 로봇의 지도 자세를 안다(D-494 3항, `MapPose`). 그 자세는 odom 표본 하나에 묶여 있고 `odom_stamp`가 그 표본의 시각이다. Fleet은 `exit_segment`를 만들 때 이미 차로 polyline에 원을 맞추므로 지도 좌표의 원 중심도 갖고 있다.

## Decision

1. **지시에 지도 고정점을 싣는다.** `POST /api/v1/line-follow/junction`의 `exit_segment`에 선택 필드 `map_anchor`를 더한다.

   | 필드 | 단위 | 뜻 |
   |---|---|---|
   | `centre_x_m`, `centre_y_m` | m, 지도 좌표 | 그 구간에 맞춘 원의 중심 |
   | `pose_x_m`, `pose_y_m`, `pose_yaw_rad` | m, rad, 지도 좌표 | Fleet이 본 로봇의 지도 자세 |
   | `odom_stamp_s` | UTC epoch 초 | 그 지도 자세가 묶인 odom 표본의 시각 |

   `odom_stamp_s`는 CORE가 odom을 받은 때의 CORE 벽시계다. 스냅숏 `odom_pose.stamp`, D-517 4항 `pose_stamp`와 같은 값이다. 여섯 값은 모두 유한한 수여야 하고 `odom_stamp_s`는 0보다 크다. 어기면 400이다.
2. **능력 `lane_arc_map_anchor`.** CORE는 `controls`의 `base_velocity`에 `lane_arc_map_anchor`를 알린다. 값은 `lane_arc`와 같다. Fleet은 이 능력이 참이고, 이번 주기에 로봇을 찾은 지도 자세가 LOCALIZED이며 `odom_stamp`가 있을 때만 `map_anchor`를 보낸다. 그 밖에는 지시가 오늘과 같다.
3. **CORE는 받을 때 odom으로 옮긴다.** CORE는 지시를 받은 때 자기 odom 기록에서 `odom_stamp_s`의 표본을 찾는다. 찾은 odom 자세와 지도 자세 쌍으로 map→odom 강체 변환을 만들고, 원 중심을 odom으로 옮겨 지시와 함께 둔다. 받을 때 옮기는 이유는 CORE의 자세 기록이 짧기 때문이다(약 2 s). 지시는 장소 0.6 m 앞에서 오고 제자리 회전이 그 뒤에 있어, 호가 열릴 때는 그 표본이 기록에 없다.
4. **호가 열릴 때 그 원을 쓴다.** `_open_arc`는 옮겨 둔 중심을 호의 `centre`로 쓰고, `yaw0`는 지금 자세에서 그 원의 접선으로 둔다. 그 뒤는 D-520 개정의 제어기 그대로다. 로봇이 원에서 벗어나 있으면 `e_r`·`e_th` 보정이 원 위로 당긴다. 이어지는 `straight`(앞 호의 원을 물려받는 가지)도 새 고정점이 있으면 그것을 쓰고, 없으면 오늘처럼 앞 원을 물려받는다. 물려받은 적분항은 그대로 둔다.
5. **실패하면 오늘의 원이다.** 아래 가운데 하나라도 해당하면 자세로 놓는 오늘의 원을 그대로 쓴다. 지시는 거절하지 않는다.
   - `map_anchor`가 없거나 값이 유한하지 않다.
   - 받은 때 `odom_stamp_s`가 2 s보다 오래됐거나 CORE 시계보다 0.05 s 넘게 앞선다(`ARC_ANCHOR_MAX_AGE_S`, D-517의 `STAMP_TOL_S`).
   - 그 시각의 odom 표본이 기록에 없거나, 그 표본의 odom epoch·frame이 지금과 다르다.
   - 받은 뒤 호가 열릴 때까지 odom epoch·frame이 바뀌었다.
   - 받은 뒤 호가 열릴 때까지 odom 전진 거리가 1.5 m를 넘는다(`ARC_ANCHOR_MAX_CARRY_M`, Fleet이 sighting 사이를 odom으로 잇는 한도 `fleet.map_pose.max_dead_reckon_m`과 같은 값).
   - 호가 열릴 때 로봇이 그 원에서 0.075 m 넘게 떨어져 있다(`ARC_MAX_RADIAL_M`, 호가 `lane_arc_edge`로 멈추는 같은 한도).
6. **기록.** `GET /api/v1/line-follow`와 스냅숏의 `line_follow.arc`에 `map_anchor_used`(bool)를 더한다. 그 호가 지도 고정 원으로 열렸을 때만 참이다.

## 바뀌지 않는 것

- `exit_segment`의 네 필드와 범위, 호 제어기의 이득과 한도, IR 한 번 보정, D-422 sweep, `motion_admitted`, 호 끝의 처리, 멈춤 사유는 그대로다.
- `map_anchor`가 없는 지시의 동작은 줄 단위로 같다(호 off golden 포함).
- CORE는 여전히 지도 자세를 갖지 않는다. 받은 쌍 하나로 원 하나를 odom에 옮길 뿐이고, 그 변환을 다른 판단에 쓰지 않는다.
- CORE가 최종 `/cmd_vel`의 유일한 발행자다. Fleet은 명령을 내지 않는다.
- envelope `protocol_version`은 그대로다. API Reference는 additive로 한 판 올린다.

## 한계

1. 원의 정확도는 Fleet 지도 자세의 정확도다. 천장 카메라 sighting 사이는 Fleet도 odom으로 잇는다.
2. 받은 때부터 호가 열릴 때까지(접근 0.6 m 이내와 제자리 회전)는 CORE의 odom으로 잇는다. 제자리 회전에서 odom yaw가 틀리면 원 중심이 로봇 둘레로 `r·오차`만큼 돈다(D-520 Context 7). 오늘의 원도 odom의 목표각으로 놓으므로 같은 한계다. 줄지 않을 뿐 늘지 않는다.
3. 2 s와 1.5 m는 근거 있는 시작값이다. SIM과 장치에서 다시 잰다.
4. 호스트 시험은 운동학 고리다. Gazebo와 장치 수용은 이 ADR의 증거가 아니다.

## 방향 (이 ADR이 정하지 않는다)

아래 둘은 같은 사용자 결정의 다음 걸음으로 적어 둘 뿐이다. 각각 별도 ADR이 정한다.

- (a) **차 안의 paint-map 위치 추정.** 로봇이 본 바닥 선을 지도에 맞춰 CORE에 지도 자세를 준다. 그러면 교차로는 지도에서 오고, keeper의 교차로 sighting은 한 표가 된다.
- (b) **지도 차로 중심선 추종.** 경로 추종의 기준을 지도 차로 중심선으로 둔다. 차로 변경은 차로 후보 관측 계약으로 받고, IR 가드와 Fleet의 차로 이탈 검사에는 「허가된 경계 넘기」 문맥을 준다.
