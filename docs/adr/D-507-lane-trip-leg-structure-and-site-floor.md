## D-507 차선 trip의 한 구간은 CORE가 "추종 → 접근 → 회전 축 → 회전 → 재획득" 상태 기계로 실행하고, Fleet은 지도에서 그 구간의 기대(교차로 위치·회전 축·허용 오차·지도 id)만 준다 — 현장 근거는 지도 하나에 묶인 바닥 선언 하나로 합치고, D-468은 이탈의 양의 증거가 있을 때만 연다

**Status:** Accepted (2026-10-07, 사용자 결정). 구현·SIM·DEVICE 수용은 열려 있다. 사용자 지시: "되도록 해야지. 그걸 고민해서 해야지 더 고민해서 처리하도록 구조 잡아볼래?". 사용자 결정(2026-10-07):
- `recovery_local_enabled` 로봇 기본값은 켜 둔 채, D-468 차선 복귀도 D-498처럼 현장 근거(IR 가드 + D-422 몸체 정지 + 현장 선언)로 허용한다.
- 7항 **수락**: D-468은 이탈의 양의 증거(`ready` corridor에서 `margin + uncertainty_m < 0`)가 있을 때만 연다. 증명하지 못하면 `recovery_local_enabled: false`일 때처럼 동작한다.
- 9항 **수락**: `bridge_site_no_dropoffs`와 `junction_turn_site_accepted`를 `line_follow.site_floor_map_id` 하나로 바꾼다. 옛 키가 있으면 CORE가 시작을 거부한다. 별칭은 두지 않는다.
- 6항 **변경**: 초안은 현장 근거로 뒤로 가지 않는다고 했다. 사용자는 현장 근거의 후진을 허용하기로 골랐다. 6항 (c)와 9항이 그 조건이다.
- 7항 **개정**(2026-10-08 사용자 결정): 이탈은 (1) `ready` corridor에서 `margin + uncertainty_m < 0`, 또는 (2) 추종 중 자세 불연속·연속성 epoch 변경, 또는 (3) 증명된 차로 안이지만 체크포인트 차로가 아님에서 연다. 구현 커밋 `ab4e27e9c`의 (2)·(3)을 그대로 둔다.

나머지 항(1–5, 8, 10, 11)은 이 ADR 전체 수락에 따른다. 10항은 safety 모듈 변경이라 구현 브랜치에서 Safety-Review를 받는다. 실차 이동은 아래 수용 절차를 따른다.

잇는 결정: [D-495](D-495-lane-junction-bounded-turn-and-junction-defaults.md)(제한 회전) · [D-498](D-498-junction-turn-site-basis.md)(회전 현장 근거, M1 후속을 이 ADR이 정한다) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(교차로 지시 API, trip 루프) · [D-476](D-476-lane-loss-expected-road-bridge.md) rev 1(bridge 현장 근거) · [D-468](D-468-local-lane-departure-return.md)(이탈 복귀, 이 ADR이 개정) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)(몸체 기준 정지, 이 ADR이 기억 규칙을 개정) · [D-500](D-500-measured-motion-response-and-clearance-budget.md)(정지 성능, 결정 12 후진 규칙) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md)(plan 3 전 enforce 금지, 그대로) · [D-489](D-489-fleet-route-planning-concept-and-algorithm.md)/[D-490](D-490-fleet-route-planner-implementation.md)(지도 θ, 장소 고정) · [D-491](D-491-ir-guard-crosswalk-zone.md)(IR 가드) · [D-18](D-18-rosy-core.md)(CORE가 유일한 최종 `cmd_vel` 발행자)

### Context

1. D-495/D-498 교차로 SIM(`docs/validation/d495-junction-sim-2026-10-07/result.md`, 모델 PC, ROS-SIM 한 대)은 회전 자체(9건 오차 −4.08…+2.75°)와 장애·근거 상실 중단(S5·S8·S9)은 통과했다. 그러나 지도 trip은 끝까지 가지 못했다. 원인은 셋으로 나뉜다.
   - **코드 결함(이 ADR과 무관하게 고친다).** odom 원본 시각이 CORE 시계보다 1 ms 앞서면 PoseTrail이 지워진다(발견 2). CAMERA_LINE 선택 직후의 회전이 첫 odom을 기다리지 않고 `aborted odom`이다(발견 3). 재획득 실패 `unresolved`가 실행된 지시로 기록되지 않는다(발견 4). 서 있는 로봇의 D-422 기억 래치(발견 8)는 기억 규칙의 개정이라 이 ADR 10항에 둔다.
   - **구조 결함(이 ADR).** 로봇 기본값으로는 CAMERA_LINE이 출발하지 않는다(발견 1). 회전을 "교차로를 처음 본 자리"에서 해서 우회전은 벽에, 좌회전은 재획득 실패에 닿는다(발견 6, 재획득 0/9). 지도에 없는 굽이를 교차로로 보고 아무도 주지 않는 지시를 기다린다(발견 5).
   - **인식 결함(버그 수정 브랜치, 증거 먼저).** 굽이의 `junction_fork` 오감지와 `flipping`(발견 5), 차로 중심에서 약 0.05 m 왼쪽으로 달려 bridge가 무장되지 않음(발견 7).
2. **발견 1의 실제 원인은 바닥 근거만이 아니다.** D-468은 추종 단계에서 차로 안을 증명하지 못하면(근거 `ready`가 아니거나 여유가 기준 미달) 첫 프레임에 이탈을 연다. 260919 트랙의 실제 여유는 한쪽 21–23 mm(STL)이다. G-16 수정(`fix/g16-lane-slope-error`) 뒤에도 재생 여유는 21.5/22.0 mm이고 정직한 투영 불확실도는 22.9/13.7 mm다. 불확실도 상한 15 mm(`LaneReturnEvidence.MAX_UNCERTAINTY_M`)와 침식 뒤 여유 ≥ 0 기준을 이 트랙에서는 계속 만족할 수 없다. 그러므로 복귀 동작에 현장 근거를 주는 것만으로는 로봇이 추종하지 않고, 이탈 → 복귀 탐색을 되풀이한다. "증명 못 함"과 "이탈을 봄"을 나눠야 한다.
3. **회전 축의 기하.** keeper는 가로선이 앞 0.45 m(`JUNCTION_AHEAD_M`) 안에 들어올 때 감지하고 그 자리에서 선다(SIM: 가로선 0.11–0.35 m 앞). 들어오는 차로와 나가는 차로의 중심선이 만나는 점(Fleet 지도에서 장소 점, D-490이 polyline 끝을 장소에 고정)은 그보다 가로선 너머 나가는 차로 폭의 절반만큼 더 앞이다. 그 점보다 앞에서 돌면 나가는 차로 중심에서 옆으로 그 거리만큼 벗어난 채 출발한다.
4. **현장 선언이 셋으로 갈라지려 한다.** bridge `bridge_site_no_dropoffs`, 회전 `junction_turn_site_accepted`, 그리고 차선 복귀에 셋째가 필요해진다. 셋 다 로봇 설정에 묶여 로봇이 현장을 옮기면 따라간다(D-498 검토 M1). 현장 책임자가 걷는 바닥은 하나다.
5. Fleet은 지도의 장소, 차로 폭(`width_m`), 들어오고 나가는 θ, 지도 id(`SiteMap.map_id`)를 안다. CORE는 지도를 모른다. 인식(keeper)은 가로선까지 거리를 이미 계산하지만(`lane_keep_junction._across_path`) 내보내지 않는다.
6. **후진의 근거.** D-468 역추적(`retrace`)은 체크포인트 뒤의 측정 경로를 뒤로 되짚는다. 오늘 한도는 체크포인트 뒤 5 s 안, 한 목표점 0.15 m 안, 0.03 m/s 이하, 측정 경로를 따라서만이다(`lane_return.py`). Pinky의 LiDAR는 360°라서 D-422 몸체 sweep은 뒤 방향 twist에도 계산된다. IR 가드는 앞에만 달려 있어 뒤쪽 바닥은 보지 못한다. D-500 결정 12(Proposed)는 후진의 공간 근거(뒤쪽 LiDAR 띠, 되돌아가기 조건)를 정하고, odom만으로는 근거가 되지 않는다고 한다. 실기 카펫에서는 제자리 회전 odom yaw가 몇 배 틀린 관찰이 있다(D-500 Context, 9dfk).

### Decision

1. **한 구간(leg)의 상태 기계와 주인.** 상태는 CORE `line_follow.junction.state`로 보인다.

   | 단계 | 무엇 | 주인 | 근거·한도 |
   |---|---|---|---|
   | `follow` | 차선 추종(keeper, IR 가드, D-476 bridge, D-468 복귀) | CORE + 인식 | 기존 |
   | `armed` | 다음 장소의 지시를 미리 받음(장소 앞 `arm_distance_m` 0.6 m) | Fleet이 보내고 CORE가 보관 | D-494 5항 |
   | `stopping` | 감지(기대 창 안) → 정지 확인 | CORE | D-495 L1 |
   | `approaching` (새) | 진입 방향으로 회전 축까지 odom 직진 | CORE | 이 ADR 4항 |
   | `turning` | 회전 축에서 제자리 회전 | CORE | D-495 1(a), M6, R2 |
   | `advancing` | `advance_m` 직진 | CORE | D-495 1(b) |
   | `reacquiring` | 차선 재획득 N프레임 | CORE + 인식 | D-495 M5 |
   | `follow` | 다음 구간 | CORE | — |
   | `unexpected` (새) | 기대 창 밖 감지 → HOLD, 지시는 그대로 `armed`로 남김 | CORE가 멈추고 Fleet이 trip을 끝냄 | 이 ADR 3항 |

   Fleet은 기하와 순서만 정한다. 모든 twist는 지금처럼 CORE 매니저 틱 안에서 만들어져 같은 generation·evidence revision으로 CommandManager에 간다(D-18).

2. **Fleet → CORE 교차로 지시 계약 추가.** `POST /api/v1/line-follow/junction`에 선택 필드 넷을 더한다. 네 필드가 모두 없으면 오늘 동작 그대로다(옛 Fleet 호환). `map_id`가 있고 기대 창이 없을 때의 주행 지시는 아래 보충 계약을 따른다.
   - `map_id`(문자열): 이 지시를 계산한 지도. 9항의 선언과 다르면 이 지시의 동작은 현장 근거를 쓰지 않는다.
   - `expect_in_m`((0, 2]): 보낼 때 로봇 자세에서 장소까지 차로를 따른 거리(Fleet 지도 자세).
   - `expect_tol_m`((0, 0.30]): Fleet이 장소 위치를 아는 오차(지도 자세의 진행 방향 오차 + 장소 고정 허용치 `ENDPOINT_TOL_M`). Fleet 설정·자세 진단에서 나온다.
   - `pivot_past_line_m`([0, 0.30], `left`/`right`만): 감지된 가로선에서 회전 축(장소 점)까지 거리. Fleet은 나가는 차로의 `width_m / 2`로 보낸다(장소는 나가는 차로 중심선 위에 있다, D-490). 상한 0.30은 D-495 `MAX_ADVANCE_M`과 같은 값이다.
     - (2026-10-08 사용자 결정, SIM 발견 1–2) keeper가 재는 가로선은 회전교차로 입구나 T자에서 나가는 차로의 **먼 쪽 경계**일 수 있다. 260919 SW spoke에서는 회전교차로 바깥선이 입구에서 끊겨 있어 안쪽 선(0.402 m)을 쟀고, 장소 점은 0.296 m였다. 그래서 `pivot_past_line_m`은 부호 있는 값이고 범위는 [−0.30, 0.30]이다. Fleet은 지도에서 접근 방향으로 장소 너머 처음 만나는 칠한 선을 찾아 그 선에서 장소 점까지의 부호 있는 거리를 보낸다(장소가 선 너머면 양수, 선 앞이면 음수). 칠한 선은 차로들의 합집합 경계로 본다(각 차로는 중심선 둘레 `width_m` 띠). 그래서 차로 입구는 선을 끊고 섬은 선을 남긴다. 창을 보낼 때는 로봇 진행 방향으로, 아니면 장소에서 차로 방향으로 찾는다. 0.30 m 안에 선이 없으면(곧게 지나감, 네거리) 오늘처럼 나가는 차로 `width_m / 2`를 보내고 그 장소에는 창을 보내지 않는다. 기대 창의 기대 가로선은 그대로 `expect_in_m − pivot_past_line_m`이다. 칠한 선은 `drive_mode: lane` 차로만으로 본다(`free` 차로는 테이프가 없다). keeper와 지도 모형이 재는 선은 테이프 중심이다.
     - 알려진 한계: (1) 창을 보내지 않는 장소(창 범위 밖, 15° 넘는 굽이)에는 음수 pivot을 보내지 않는다. 창이 없으면 CORE가 map_id가 있는 주행 지시의 감지를 거절한다(3항 보충). 이전에는 어떤 감지든 받아 잘못 잰 선과 음수 pivot으로 짧게 돌 위험이 있었다. 그래서 그 장소는 가로선 감지 시 HOLD한다. 선을 찾지 못한 장소만 예전 가까운 경계 모형의 `width_m / 2`를 보낸다. (2) Fleet이 선을 찾는 방향(창이 있으면 보낼 때의 로봇 진행 방향)과 CORE가 목표를 잡는 진입 yaw는 굽은 접근에서 다를 수 있다. 그 차이만큼 회전 축이 장소에서 벗어난다.
   - 능력 `junction_pivot: true`(CORE가 위 필드를 받는다는 표시)가 없는 로봇에는 Fleet이 이 필드를 보내지 않는다.
   - CORE의 기대 창은 받은 자리의 진행 방향으로 곧게 내다본 점이므로, 장소 앞에서 차로 방향이 15°보다 많이 바뀌면 Fleet은 `expect_in_m`·`expect_tol_m`을 보내지 않고(`map_id`·`pivot_past_line_m`만 보낸다), 경로를 따라가는 기대 창은 뒤의 일로 둔다. 아래 보충 계약에 따라 이 지시는 가로선 감지 시 HOLD하며, 창 있는 지시가 새로 오기 전에는 회전하지 않는다.

3. **기대 창과 굽이.** 지시를 받을 때 CORE는 받은 자리의 odom 자세와 진행 방향으로 기대 가로선 점(`expect_in_m − pivot_past_line_m`, 갈래면 `expect_in_m`)을 odom 좌표에 둔다. 감지마다 측정 가로선 점(감지 자세 + `junction_ahead_m`)과 기대 점의 거리가 `expect_tol_m` 안이면 이 지시의 교차로다.
   - **2026-10-08 보충:** `map_id`가 있는 `straight`·회전 지시에서 기대 창이 빠지면 어떤 가로선 감지도 이 장소의 선으로 확인할 수 없다. CORE는 `junction_unexpected`로 HOLD하고 지시는 `armed`로 보존한다. Fleet은 trip을 중단한다. `map_id`도 없는 옛 지시는 기존 동작을 유지하고, `stop`은 원래 기대 창을 쓰지 않는다. 이 보충은 B9 게이트 켬 SIM에서 굽이 앞 조기 회전 2/6을 막는 안전 경계일 뿐이며, 나머지 4/6의 경계 소실이나 실제 굽이 통과를 해결하지 않는다. Fleet의 경로를 따르는 기대 창과 경계 공백 접근 근거가 생기기 전에는 B9 게이트를 켜지 않는다.
   - 창 밖 감지(지도에 없는 굽이, 다른 교차로)는 지시를 쓰지 않는다. HOLD `junction_unexpected`이고 지시는 `armed`로 남는다. 그래서 장소 바로 앞의 굽이에서 회전 지시가 쓰이는 일이 없다.
   - 지시가 없는 감지는 지금처럼 `waiting`이다. Fleet trip 루프는 로봇이 `waiting` 또는 `unexpected`이고 다음 장소가 `arm_distance_m`보다 멀면 10 s(`junction_wait_s`)를 기다리지 않고 trip을 `stopped(junction_unexpected)`로 끝낸다. 운영자에게 자리(지도 자세)와 keeper 사유를 보인다.
   - 굽이를 교차로로 보는 keeper 오감지는 인식 결함이다. 버그 수정 브랜치에서 증거(SIM 카메라 기록)로 고친다. keeper에 경로 맥락(예 `line/route_context`)을 주는 계약은 그 수정 뒤에도 굽이 HOLD가 남을 때 따로 정한다.

4. **회전 축까지 접근(`approaching`).** `left`/`right` + `turn_deg` 지시가 있고, 감지가 `junction_ahead_m`을 실었고, `pivot_past_line_m`이 왔으면 정지 확인 뒤 접근한다.
   - 목표: 접근을 시작할 때의 가장 최근 신선한 감지로 측정 가로선 점을 다시 잡고, 진입 방향(D-495 N1의 진입 yaw)으로 `pivot_past_line_m`(갈래면 0) 더 간 점. 서 있는 로봇의 최근 감지가 처음 감지(멀고 움직이는 중)보다 정확하다.
   - 운동: 진입 yaw를 붙잡는 직진, 속도는 D-495 전진과 같은 `0.5·min(max_linear, 수동 선속도 한도)`, 거리는 odom, 시간 한도 `거리/속도 + STEP_MARGIN_S`. 매 틱 6항의 운동 허가와 D-422 몸체 sweep을 거친다. 중단 규칙은 D-495 전진과 같다(odom 낡음·끊김, 모드 변경, 근거 상실, `near_stop`, 시간 초과, 새 지시).
   - 접근 뒤 정지 확인(D-495 L1)을 다시 하고 회전한다. 회전 목표는 그대로 `진입 yaw + turn_deg`(N1)다.
   - `junction_ahead_m`이나 `pivot_past_line_m`이 없으면 접근 거리 0(오늘 동작)이고 상태에 `pivot_basis: stop_point`를 보인다. 있으면 `pivot_basis: map`이다.
   - (2026-10-08 사용자 결정) `pivot_past_line_m`이 음수면(2항 개정, 측정 선이 먼 쪽 경계) 목표는 측정 가로선 앞이다. CORE는 지금처럼 측정 선 + pivot을 진입 방향으로 잡는다. 그 목표가 로봇 자리이거나 뒤면 접근 거리 0이고 그 자리에서 회전한다. 뒤로 가지 않는다. 직진 통과 띠의 옆 반폭은 pivot이 양수일 때만 그 값이고, 아니면 D-491 통로 반폭이다.
   - (2026-10-08 사용자 결정) 회전 목표는 나가는 차로를 따라 `advance_m` 앞 점으로의 현(chord) 방향이다. Fleet이 회전 축(장소 점)에서 나가는 차로 polyline의 `advance_m` 지점까지의 방향과 진입 접선의 차이(감쌈)를 `turn_deg`로 보내고, 같은 `advance_m`(D-495 기본 0.10)을 지시에 함께 보낸다. 직진 전진이 차로 중심선 위에서 끝난다. 곧은 차로에서는 현이 접선이라 그대로다. 직진·좌·우 분류는 접선 각으로 하고, 150° 한도와 부호(좌 +, 우 −)는 보내는 각으로 보고, `advance_m`은 나가는 차로 길이를 넘지 않는다. CORE 변경은 없다. 근거: SIM 3/3b차에서 260919 ring(r≈0.25 m) 접선 조준은 전진 끝에서 ring 접선과 22–31° 어긋났고 NE는 6/6 차선을 잃었다.
   - 재획득에서 못 찾으면 지금처럼 `unresolved`다. 재획득 탐색(제자리 ±30° 훑기)은 접근 뒤 SIM에서 실패가 남을 때만 별도 결정으로 더한다.

5. **인식 계약 추가.** `line/keep_debug`가 교차로 사유를 낼 때 `junction_ahead_m`(base_footprint x, m)을 함께 싣는다. `junction_transverse`는 진로를 가로지르는 가로선까지 거리(`_across_path`), `junction_fork`는 벌어지는 가지의 가까운 끝 x다. 사유가 없으면 싣지 않는다. 교차로 판정을 `line/observation`으로 옮기는 일은 그대로 D-495 4항 후속이다.

6. **운동 허가는 한 함수, 근거는 둘(사용자 결정: 현장 근거 후진 허용).** D-468 복귀(역추적 포함), D-476 bridge, D-495 접근·회전·전진은 CORE의 한 운동 허가 `motion_admitted(now, linear, angular, kind)`를 쓴다.
   - (a) **enforce**: D-400 enforce 워커의 바닥·공간 증명(`return_sensor_allowed`). 지금 그대로다.
   - (b) **site**: 다음을 모두 만족한다.
     - 9항의 선언이 있고, 동작을 연 지시가 `map_id`를 실었다면 같다.
     - `ir_guard_enabled`이고 IR 판정이 신선하고 교정돼 있다. 판정 허용 값은 동작마다 다르다. bridge는 `clear`만(D-476 rev 1 그대로), 접근·회전·전진은 `centre`가 아닐 때(D-498 그대로), D-468 복귀는 `centre`도 받는다(복귀는 선을 밟은 채 시작하고, 방향은 D-468 차로 기하가 정한다).
       - (2026-10-08 사용자 결정) 접근과 `straight` 통과 중에는 카메라가 잰 가로선 띠 안에서만 `centre`를 받는다. 띠는 감지 자세 + `junction_ahead_m`에 odom으로 고정하고, 진입 방향으로 테이프 폭과 D-491의 거리·odom 오차 비율만큼만 넓힌다. 그 띠 밖에서는 어디서나 `centre`가 지금처럼 동작을 멈추고, 회전 중에는 띠를 쓰지 않는다.
     - `obstacle_mode: path`, URDF 몸 기하(`body_stop_known`), `clearance_stale_s` 안의 스캔이 있고, 그 twist의 D-422 몸체 sweep이 재출발 간격보다 크다.
   - (c) **site 근거의 후진.** 선속도가 0보다 작은 twist도 (b)로 허가한다. 초안은 이를 금지했으나 사용자가 허용을 골랐다. 조건은 (b) 전부에 더해 다음이다.
     - 후진은 D-468 역추적뿐이다. 다른 동작(bridge, 접근, 회전, 전진, 복귀 접근·정렬)은 site 근거로 뒤로 가지 않는다.
     - 역추적은 기존 D-468 한도 안에서만 움직인다. 체크포인트 뒤 5 s 안, 측정 경로를 따라서만(되짚는 거리 ≤ 체크포인트 뒤 실제로 지난 거리), 한 목표점 0.15 m 안, 0.03 m/s 이하. 이 ADR은 한도를 늘리지 않는다.
     - 그 후진 twist의 D-422 몸체 sweep(뒤 방향)이 재출발 간격보다 크다. LiDAR가 360°라서 뒤쪽 공간 근거는 이 sweep이다. 스캔이 `clearance_stale_s`보다 낡으면 sweep이 낡은 것이고 후진하지 않는다.
     - **뒤쪽 바닥 근거는 선언뿐이다.** IR 가드는 앞에 달려 있어 뒤쪽 바닥을 보지 못한다. IR 판정이 신선해야 한다는 조건은 남지만, 뒤쪽 바닥에 대해서는 아무 증거도 주지 않는다. 뒤쪽 바닥 위험은 9항 선언이 전부 진다(D-498 M2와 같은 구조). 그래서 9항 선언이 후진 경로의 뒤쪽 바닥을 명시적으로 덮는다.
     - **D-500 결정 12와의 관계.** D-500 12는 후진의 공간 규칙이고, 이 항은 후진의 바닥 근거다. 둘 다 필요하다. D-500 12가 착지하기 전에는 위 D-422 뒤 방향 sweep이 공간 근거다. 착지한 뒤에는 역추적이 D-500 12((a) 뒤쪽 LiDAR 띠가 `stop_gap(reverse)` 너머까지 빔, 또는 (b) 되돌아가기 조건)도 만족해야 하고, 둘 중 더 엄격한 쪽이 이긴다. D-500 12처럼 odom만으로는 후진 근거가 되지 않는다.
     - **카펫 odom yaw 위험(9dfk).** 역추적은 odom PoseTrail을 되짚는다. 카펫에서 odom yaw가 틀리면 되짚는 경로가 실제로 지나온 바닥에서 옆으로 벗어날 수 있다. 이 벗어남은 위 거리·시간 한도와 9항 선언의 차로 바깥 0.30 m 안에 묶인다. DEVICE에서 역추적 끝 자세는 odom이 아니라 독립 기준(LiDAR 벽 정합)으로 판정한다.
   - 근거를 잃으면 동작은 지금처럼 중단한다(회전 `turn_basis_lost`, 복귀 `lane_return_motion_unconfirmed`, bridge `lane_bridge_motion_unconfirmed`). 역추적 중 뒤 방향 sweep이 재출발 간격 아래로 떨어지거나 낡으면 그 틱에서 멈추고 D-468의 다음 폴백(탐색 또는 Fleet 요청)으로 간다.
   - 능력 `junction_turn`은 (a) 또는 (b)가 성립할 때만 참이다(D-498 2항 그대로).

7. **D-468은 이탈의 양의 증거가 있을 때만 연다(D-468 개정, 사용자 수락).** 추종 단계에서 이탈을 여는 조건은 하나다. 신선하고 `ready`인 corridor에서 `margin + uncertainty_m < 0`, 곧 불확실도를 로봇 쪽에 유리하게 다 줘도 몸이 경계 밖이다. 지금 이미 추종 중인 로봇이 떠나는 조건과 같은 규칙을 첫 프레임에도 쓴다.
   - 근거가 `ready`가 아니거나(낡음, 불확실도 미상·초과, 한쪽 경계만, 몸 기하 없음) 여유가 엄격 기준 미달이지만 위 조건은 아니면, D-468은 동작하지 않는다. 상태에 `lane_return_containment: unknown`을 보인다. 그 틱은 오늘의 추종 경로(keeper, IR 가드, 손실 시계 → LOST)가 가진다. 이것은 `recovery_local_enabled: false`일 때와 같은 동작이다.
   - 체크포인트(역추적 기준점)는 지금처럼 엄격 기준(`_normal`, 3프레임)에서만 잡는다.
   - 효과: 로봇 기본값(`recovery_local_enabled: true`)에서 CAMERA_LINE이 출발한다. 증명된 이탈에서만 D-468이 서고, 6항 근거가 있으면 돌아오고, 없으면 HOLD다.
   - (2026-10-08 사용자 결정) 이탈은 (1)에서, 또는 (2)나 (3)에서 연다. (1) 신선하고 `ready`인 corridor에서 `margin + uncertainty_m < 0`(위 본문). (2) 추종 중 자세 불연속(PoseTrail이 받지 않는 odom 표본: frame 변경, 시각 역행 또는 0.5 s 넘는 간격, 0.02 m + 0.2·dt 넘는 이동, 0.1 rad + dt 넘는 회전)이나 자세 연속성 epoch 변경. (3) 자세가 신선하고 차로 안이 증명됐지만 그 차로가 체크포인트 차로가 아님. 셋 다 이탈의 양의 증거다. (1)은 불확실도를 로봇 쪽에 다 줘도 몸이 경계 밖이라는 측정이다. (2)는 차로 안이라는 증명과 체크포인트가 기대던 자세 기준이 끊겼다는 측정이다. 끊긴 뒤에는 이전 증명을 이어 쓸 수 없고, 점프 뒤 보이는 차로를 같은 차로로 받을 수도 없다(역추적 경로와 후보는 무효가 되고, 복귀는 새 corridor 검증으로만 한다). (3)은 몸이 어떤 차로 안에 있지만 그 차로가 출발한 차로가 아니라는 측정, 곧 옆 평행 차로로 넘어갔다는 증거다. 반대로 근거가 없음(차로가 안 보임, 낡음, 불확실도 미상, 몸 기하 없음)은 이탈의 증거가 아니다. 알려진 한계(SIM·DEVICE에서 확인한다): 체크포인트는 |heading| ≤ 0.12 rad일 때만 새로 잡히고 `Corridor.matches`는 체크포인트 경계를 직선으로 늘여 15 mm 안만 같은 차로로 보므로, 굽은 차로에서는 같은 차로를 (3)으로 읽어 이탈을 열 수 있다.
   - (2026-10-08 사용자 결정, 결과) D-476 bridge가 차로를 다시 보지 못한 채 끝나면 D-468은 역추적하지 않는다. 보이지 않는 차로는 이탈의 증거가 아니므로 그 틱은 오늘의 손실 경로(손실 시계 → LOST, `camera_reselection_required`)가 가진다. IR `lane_departure` 틱도 D-468이 서는 것(`lane_return_containment_unconfirmed`)이 아니라 오늘의 IR 정지(`lane_departure`)다. 역추적은 (1)–(3)으로 이탈이 열린 뒤에만 6항 근거 아래에서 한다. API Ref v1.134.

8. **원본 시각 허용치는 하나.** odom·영상·감지의 원본 시각이 CORE 시계보다 앞선 정도의 허용치는 상수 하나 `SOURCE_FUTURE_TOLERANCE_S`(0.1 s, 지금 `manager.observe`의 값)다. 그 안이면 나이를 0으로 본다. 넘으면 그 표본을 버린다(PoseTrail은 지우지 않는다. 끊김은 실제 불연속에서만).

9. **현장 바닥 선언은 지도 하나에 하나(사용자 수락).** `bridge_site_no_dropoffs`와 `junction_turn_site_accepted`를 지우고 `line_follow.site_floor_map_id`(문자열 또는 null, 기본 null) 하나로 바꾼다.
   - **뜻.** 현장 책임자가 지도 `map_id`의 모든 차로·교차로와 그 바깥 0.30 m(회전 원, 전진, 접근, bridge, 복귀, 역추적 후진이 닿는 범위)를 걸어서 확인했고, 떨어지는 곳·구멍·턱이 없다. 이 범위는 로봇 뒤쪽 바닥, 곧 D-468 역추적이 되짚는 후진 경로의 바닥을 명시적으로 포함한다. IR 가드는 앞쪽 바닥 끝도 보지 못하고(D-498 M2, 이번 SIM 발견 9) 뒤쪽 바닥은 아예 보지 않으므로, 바닥 위험은 앞뒤 모두 이 선언이 진다.
   - **걷기 기록(D-498 D8 갱신).** D8 체크리스트에 뒤쪽 바닥 항목을 더한다. 현장 책임자는 차로마다 양방향으로 걷고, 차로 밖 0.30 m 띠를 로봇이 뒤로 갈 수 있는 쪽까지 확인하며, 지도 id·걸은 사람·날짜를 기록한다.
   - **검증(CORE 시작 거부).** null이 아니면: `SiteMap.map_id` 형식(`^[A-Za-z0-9_.-]{1,64}$`)이고 기본값 `site`가 아니어야 한다. `ir_guard_enabled: true`, `obstacle_mode: path`, URDF 몸 기하가 모두 있어야 한다. `bridge_enabled: true`는 enforce 또는 이 선언이 있어야 한다(`check_bridge_floor_basis`가 이 키를 본다). 지운 두 키가 겹에 있으면 새 키 이름을 담은 오류로 시작을 거부한다. 조용히 무시하지 않고, 별칭으로 읽지도 않는다.
   - **지도 묶기.** CORE 능력에 `site_floor_map_id`를 보인다. Fleet은 이 값이 활성 지도의 `map_id`와 다른 로봇의 `lane` trip을 `TRIP_SITE_FLOOR_MISMATCH`로 열지 않는다. 지시마다 `map_id`를 실어 로봇 쪽에서도 다시 맞춘다(2항). Fleet 없이 운영자가 고른 CAMERA_LINE은 로봇 선언을 그대로 쓴다. 로봇이 현장을 떠나면 이 키를 지운다(D-498 D8 그대로).

10. **D-422 기억은 몸 밖의 점만 둔다(D-422 개정).** `range_min` 아래로 사라진 점의 기억은 URDF 몸 윤곽 밖에 있는 점만 남긴다. 윤곽 안의 점은 이미 몸이 있는 자리라서 정지로 피할 수 있는 물체가 아니고, 잡음 또는 접촉이다. 안팎 판정은 점이 기억에 들어갈 때 한 번만 한다. 이미 기억한 점은 뒤에 오도메트리가 몸 안에 두어도(접촉) 계속 막는다. Pinky(LiDAR `range_min` 0.05 m, LiDAR에서 몸 끝까지 최소 0.0565 m)에서는 지금 기억되는 점이 모두 윤곽 안이다. 그래서 이 개정으로 서 있는 로봇의 `obstacle_ahead`(`clearance_source memory`, `body_gap 0`) 래치가 사라진다. `range_min`이 몸 밖까지 닿는 LiDAR에서는 기억이 지금처럼 동작한다. 이 항은 safety 모듈이라 Safety-Review를 받는다.

11. **IR 직각 교차.** 코드를 바꾸지 않는다. DEVICE D9에서 잰다. 결과가 나쁘면 9항 선언 문구만 다시 본다.

### 범위 밖

- 분기 인식 출력과 가지 추종(D-495 4항 후속). 교차로 판정의 `line/observation` 이전.
- D-400 enforce(plan 3 전 금지 그대로). D-500 정지 성능 기록과 결정 12 자체의 구현(6항 (c)는 그것이 착지하면 따른다), 카펫 위 odom yaw 미끄럼 보정.
- D-468 역추적 한도의 변경. 역추적 외 동작의 후진.
- 여러 로봇의 교차로 예약. `free`(Nav2) 구간.

### 검토한 대안

- **D-468 복귀에 현장 근거만 주기(이탈 판정은 그대로).** 이 트랙의 여유 21–23 mm 대 불확실도 14–23 mm에서는 근거가 `ready`가 되지 않아 첫 프레임에 이탈이 열린다. 로봇은 추종 대신 탐색 회전과 Fleet 요청을 되풀이한다. 사용자 결정의 목적(기본값으로 주행)을 이루지 못한다.
- **`recovery_local_enabled` 기본값을 다시 끄기.** 사용자 결정(D-495 개정 2, 이번 결정)과 어긋난다. 7항은 증거가 없을 때 그 동작과 같아지므로 끄는 것의 이점을 그대로 갖는다.
- **세 개의 현장 플래그 유지, 또는 옛 키를 새 키의 별칭으로 읽기.** 같은 바닥을 세 번 선언하고, 로봇에만 묶인다(M1). 별칭은 지도 id 없이 선언을 이어 가므로 묶기를 비켜 간다. 하나로 합치고 옛 키는 시작 거부로 드러낸다.
- **현장 근거로는 뒤로 가지 않기(초안).** D-468 역추적이 enforce 또는 D-500 12 착지 뒤에만 움직인다. 그동안 증명된 이탈은 앞·제자리 복귀가 안 되면 HOLD로 끝난다. 사용자는 선언이 뒤쪽 바닥을 덮고 역추적 한도와 뒤 방향 sweep으로 묶는 쪽을 골랐다.
- **Fleet 지도 자세의 남은 거리로 접근 거리를 정하기.** 지도 자세의 진행 방향 오차가 cm 단위로 묶이지 않는다. 카메라가 잰 가로선 거리는 국소 측정이다. Fleet은 기하(폭의 절반)와 허용 오차만 준다.
- **bridge 무장 조건 완화.** 흔들리는 진행 방향을 직선 연장의 근거로 쓰게 된다. 원인(차로 중심 편향, 발견 7)을 인식에서 고친다.
- **Fleet이 접근을 목표점이나 속도로 보내기.** D-18 위반이다.
- **keeper에 경로 맥락 토픽을 바로 주기.** 새 노드 간 계약이 필요하고, 굽이 오감지가 인식 버그 수정으로 사라질 수 있다. 수정 뒤 SIM에 남을 때 정한다.
- **멈춘 자리에서 돌고 `advance_m`을 늘리기.** 회전 원이 안쪽 벽에 닿는 것(SIM 우회전 `near_stop`)과 나가는 차로에서 옆으로 벗어나는 것을 고치지 못한다.

### Consequences

- 로봇 기본값과 현장 오버레이(IR 가드, path, URDF 몸, `site_floor_map_id`)만으로 차선 로봇이 지도 trip의 좌·우·직진 교차로를 지날 수 있는 구조가 된다. 실차 수용은 그 뒤다.
- 선언이 없는 로봇은 이탈에서 HOLD하고(복귀 없음), 교차로 회전·bridge를 하지 않는다. Fleet은 그 로봇의 좌·우 `lane` trip을 열지 않는다(D-495 3).
- 옛 키 `bridge_site_no_dropoffs`·`junction_turn_site_accepted`를 둔 현장 오버레이는 이 변경이 착지한 뒤 CORE가 시작하지 않는다. 배포 전에 현장 오버레이를 새 키로 옮긴다.
- 현장 근거로 D-468 역추적이 뒤로 움직인다. 뒤쪽 공간은 LiDAR 360° D-422 sweep이 막고, 뒤쪽 바닥은 선언만이 막는다. 역추적은 짧고(체크포인트 뒤 5 s, 0.03 m/s 이하) 지나온 측정 경로만 되짚는다.
- 교차로 접근은 차선이 안 보이는 직진(가로선 앞 최대 0.45 m + 0.30 m)이다. IR 가드·D-422·시간 한도 안에서만 움직인다.
- 실기 카펫에서 제자리 회전 odom yaw가 몇 배 틀린 관찰(D-500 Context)이 있다. 회전·접근·역추적은 odom에 기댄다. DEVICE 회전·역추적 판정은 독립 기준(LiDAR 벽 정합)으로 한다.
- 수용 기준:
  - SOURCE: 기대 창 안·밖 감지, 창 밖에서 지시 보존, 접근 거리(가로선 + 절반 폭, 갈래 0, 필드 없음 0), 접근 중단 규칙, 운동 허가 한 함수의 두 근거와 동작별 IR 허용 값, 현장 근거 후진(역추적만 허가, 다른 동작의 후진 거절, 뒤 방향 sweep 미달·낡음에서 거절, 역추적 한도 그대로), D-468 양의 증거(미증명 → 추종, `margin + u < 0` → 이탈), 선언 검증과 옛 키 거절, Fleet 필드 전송·능력 확인·`TRIP_SITE_FLOOR_MISMATCH`·`junction_unexpected` 즉시 정지, D-422 몸 안 점 버림, 원본 시각 허용치.
  - SIM(모델 PC, 이 노트북 아님): 로봇 기본값 + 현장 오버레이로 `map_v2_fleet_real` 출발(60 s에 0.5 m 이상), 증명된 이탈(차로 중심에서 0.04 m, yaw 0.2 rad로 놓음)에서 복귀(역추적 포함)로 `tracking` 복귀, 선언 null이면 HOLD만, 로봇 뒤에 상자를 둔 역추적은 `near_stop`으로 멈춤, SW spoke 좌 60·우 −110·−150 재획득 9/9와 벽 `near_stop` 0, 굽이 15회 진입에서 회전 지시 소비 0, 좌·우·직진·마지막 `stop` trip 한 바퀴, S5–S9 재실행.
  - DEVICE(9dfk, 사용자 승인): D1–D9(D-495, D-498) + 접근 뒤 회전 축 위치(장소 점과 거리), 역추적 끝 자세(LiDAR 벽 정합, odom 아님), 선언 기록(지도 id, 걸은 사람, 날짜, 뒤쪽 바닥 확인).

### 구현 기록

- 10항 (2026-10-08, `fix/d422-memory-outside-body`): 구현은 `35945410f`·`32f98d98b`(main, `body_stop._remember_near` 한 곳: 진입 때 URDF 윤곽 엄격 안쪽 점은 버리고, 이미 기억한 점은 몸 안으로 들어가도 유지). 독립 safety 검토(oh-my-claudecode code-reviewer, opus, 읽기 전용) 결론은 **APPROVE WITH NOTES**, HIGH·CRITICAL 없음: C1 사각 원판(LiDAR에서 0.05 m)이 Pinky 몸 안에 6.5 mm 이상 여유로 들어가 몸 밖 장애물을 숨기지 않는다. 기억을 읽는 곳(틱, junction, lane_bridge, motion_admit 전진·후진)이 한 저장소를 읽는다. 시험 77건 통과. MEDIUM 2건(몸 안 진입 점의 접촉 처리, C1 원판이 몸 안이라는 전제)은 이 브랜치의 시험으로 고정했다. 두 커밋은 trailer 없이 main에 들어가서 검토 내용을 `tools/harness/safety_review.py` EXEMPT에 적었다. 이 기록의 착지는 사용자 결정이다. SIM(모델 PC, `docs/validation/d422-memory-outside-body-sim-2026-10-08/result.md`): 수정 전 B9 묶음 19 run 중 7 run이 기억 래치(42.9–86.2 s)였고, 이 코드로 같은 출발 22 run은 래치 0, memory 정지 사건 0이다. 상자 4회는 모두 lidar로 멈추고 닿지 않았다(주행 중 0.08 m 앞에 놓으면 0 지시까지 0.15–0.17 s, 최소 간격 0.048 m). 10항 수용 상태: SOURCE·SIM 통과. DEVICE(D9 근거리 0.06–0.12 m, 실기 C1이 `range_min` 위에서 무효를 내는지)는 열려 있다. Pinky에서는 이 개정으로 D-422 기억이 사실상 쓰이지 않는다.

## 구현 메모: B9 굽이 규칙은 경로가 굽이를 기대할 때만 (2026-10-08, perception 쪽, fix/keep-bend-not-fork)

- keeper 입력 `LaneKeeper.update(..., bend_expected=False)`를 새로 둔다. 이 값이 참이고 corner turning이 켜져 있을 때만 B9 규칙이 돈다: 굽이 규칙(`lane_keep_bend`), 가파른 선의 가까운 끝 편 정하기, 이어진 조각의 편 상속, 가까운 순서, fork 끝-시작 연속성. 기본값(거짓)이면 keeper는 B9 이전과 같다. 실물 라벨 434프레임(124745Z·133221Z)에서 main과 결정이 0프레임 다르다. corner turning은 장치 기본으로 켜져 있어서 이 게이트가 될 수 없다. 장치 검토에서 corner turning만으로 켠 B9는 HOLD → 주행 29프레임 중 맞은 것이 0이었다.
- 참은 Fleet이 이 자리에 굽이를 기대한다고 보낼 때만이다. B10–B12가 main에 들어온 뒤(2026-10-08) 확인한 결과, 지금 계약으로는 이것을 표현하지 못한다. 그래서 B9은 keeper 쪽 입력과 기본값만 둔다. 빠진 것은 다음과 같다. (1) Fleet `trip_ports.junction_fields`는 교차로 장소에만 붙는다. `_straight_ahead`는 장소 앞에서 차로가 15°(`MAX_WINDOW_BEND_DEG`) 넘게 꺾이면 기대 창을 내지 않는다(경로를 따르는 창은 나중 일). 굽이 자체를 장소 종류 `bend`로 보내는 필드가 없다. (2) CORE 지시(`core_common.protocol.controls`, `api/v1/line_follow`, `recovery/junction_approach.py`)에 굽이 기대 필드와, odom에서 그 창 안에 있는지 보는 상태가 없다. API 참조 판 올림이 필요하다. (3) CORE에서 perception(`line_observer_node`)으로 가는 경로 문맥 통로가 없다. 지금 CORE는 `line/observation`과 `line/keep_debug`를 읽기만 한다. 새 노드 간 계약(예 `line/route_context`, TRANSIENT_LOCAL)은 이 ADR의 「검토한 대안」이 미룬 것이라 ADR 보충이 필요하다. (4) `line_observer_node`가 그 값을 `LaneKeeper.update(bend_expected=...)`로 넘기는 배선. (5) 게이트를 켠 SIM에서는 굽이 앞 차로 경계가 안 보이는 구간에서 HOLD → LOST가 난다(`docs/validation/lane-keep-bend-sim-2026-10-08`). 그 구간은 B11 접근(odom 직진)이나 기대 창 안에서만 `bend_ahead` 직진을 허락하는 규칙이 메워야 한다.
- 게이트가 켜져도: 굽이 중심선이 경로와 만나는 점이 `CORNER_LOOKAHEAD_M`보다 멀면 차로의 자기 목표를 굽이 선의 경로 교차점에서 반폭을 뺀 거리 안으로 당긴다(`bend_ahead`, 평활 뒤에도). 차로 쪽 경계가 없으면 HOLD다. 65°를 넘는 굽이 선은 교차로 규칙에도 가로선으로 넘긴다(교차로는 닫힌 쪽으로 실패). 증거: `docs/validation/lane-keep-bend-sim-2026-10-08`.
