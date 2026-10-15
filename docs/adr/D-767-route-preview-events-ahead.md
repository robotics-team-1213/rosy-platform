## D-767 앞 사건을 미리 안다 — 교차로·굽이 지시의 거리는 Fleet이 본 odom 표본에서 재고, 경로 미리보기는 Fleet이 먼저 만들어 보이고 재며, 로봇에는 사용자가 원할 때만 차로 신호에 실어 보낸다

**Status:** Accepted (2026-10-15, 개정 1 같은 날). 사용자 결정 2026-10-15: A부(지시에 `pose_stamp`) 진행, B부는 P0(Fleet이 만들어 보이고 잰다)만 진행하고 P1·P2는 P0 수치를 보고 정한다. P3b는 미룬다. 사용자 요청 "상황을 미리 주는것도 고려해야하지 않아? 몇초뒤 혹은 몇m 앞에서 어떻게 해야한다는 네비게이션". 사용자 결정: "ADR과 계획을 먼저 쓰고, 동료 세션과 토론하고, 승인 뒤에만 코드". 개정 1은 독립 critic(REVISE, HIGH 3·MEDIUM·MINOR)과 rosy-44·rosy-fc의 답을 넣은 것이다(맨 끝 표). 이 기록에는 코드가 없다. 계획은 [`docs/plans/2026-10-15-d767-route-preview-plan.md`](../plans/2026-10-15-d767-route-preview-plan.md)다. A부(시각 붙은 지시)와 B부 P2(미리 감속)는 각각 **Safety-Review**를 받고 기본 꺼짐으로 연다. B부 P1(로봇에 보내기)은 사용자가 P2를 원한다고 정한 뒤에만 한다.

잇는 결정: [D-550](D-550-fleet-robot-communication-contract.md)(네 종류, 시간 기준·순서, 운반 경로, 규칙 M) · [D-551](D-551-d525-signal-advice-delivery.md)(표시 먼저, 행동은 Safety-Review·기본 꺼짐, 9항 `min` 클램프) · [D-517](D-517-multi-robot-lane-traffic.md) 4(`pose_stamp`로 다시 재기) · [D-760](D-760-fleet-motion-bounds-ride-through.md)(5 s 버티기, `link_wait`, 8항 공유 상태 읽기) · [D-758](D-758-robot-held-site-anchor.md) 0단계(정확한 stamp로 odom 표본 찾기) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)·[D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(교차로·굽이 지시) · [D-754](D-754-bend-next-line-distance.md)·[D-759](D-759-bend-map-entry-heading.md)(굽이 필드, `map_entry.odom_stamp_s`) · [D-744](D-744-map-anchored-lane-arc.md) · [D-491](D-491-ir-guard-crosswalk-zone.md)·[D-573](D-573-crosswalk-stop-look-cross.md)(횡단보도 구역과 게이트) · [D-525](D-525-virtual-signal-fleet-zone-gate.md) · [D-620](D-620-junction-fleet-signal-query.md) · [D-531](D-531-route-context-to-lane-keeper.md)(CORE→인식 경로 문맥) · [D-763](D-763-fleet-work-kinds-composed-steps.md)(`server/trips/`) · [D-766](D-766-size-limits-split-on-exceed.md)(줄 수 한도).

고치는 결정:
- **D-507 3항(2026-10-08 "창은 주행 거리로 비교") 과 D-507 굽이 보충(`bend_in_m`)**: A부가 켜진 로봇에서는 거리를 지시를 받은 때가 아니라 지시에 실린 `pose_stamp`의 odom 표본부터 잰다. 필드의 뜻(장소·호 시작점까지의 차로 거리)과 범위는 그대로다.
- **D-754 5항·D-507 굽이 보충의 Fleet 앞당김**: A부가 켜진 로봇에는 앞당김(`bend_send_s`)과 지연 여유(`SEND_ALLOWANCE_S`)를 쓰지 않는다.
- **D-511 rev 6 `LaneContext`**(B부 P1에서만): trip 중인 로봇의 차로 신호 `context`에 trip 사건 목록을 싣고, 그 로봇에는 `context.next`를 보내지 않는다.
- 고치지 않는 것: D-550(B부 미리보기는 2항의 "위 표에 없는 Fleet→로봇 데이터는 모두 참고다"에 들어간다. 허가 판정 코드는 미리보기를 읽지 않는다. 3항), D-531(9항: 이 기록은 `route_context`를 바꾸지 않는다), D-551.

### Context

2026-10-15 main(`64d15df7e`) 코드를 읽은 결과다. 실행한 시험은 없다. Fleet 경로는 `operations/fleet/fleet/`, CORE는 `middleware/drive/behaviors/line_follow/`, 계약은 `contracts/foundation/core_common/protocol/`를 줄여 쓴다.

1. **로봇이 미리 아는 것.**

   | 로봇이 아는 것 | 언제 | 근거 |
   |---|---|---|
   | 통행권 끝 `until_m` | trip 주기(0.5 s)마다. 통행권이 켜진 현장만 | `operations/fleet/fleet/traffic/trip_authority.py:75-89`, 주기 `operations/fleet/fleet/server/ledger/trip_ports.py:140`, `operations/fleet/fleet/server/ledger/trip_runner.py:402,427-430` |
   | 다음 교차로 지시(`expect_in_m`) | 장소 앞 `arm_distance_m` 0.6 m 안 | `trip_runner.py:603`, `trip_ports.py:142`. `expect_in_m` = 그때 로봇의 차로 투영점에서 장소까지(`trip_ports.py:325-343`) |
   | 다음 굽이 지시(`bend_in_m`) | 호 시작점 0.6 m 안. 교차로 지시보다 먼저 | `trip_runner.py:649-678` |
   | D-525 앞 신호 | trip 주기마다, 표시만(D-551) | `operations/fleet/fleet/traffic/trip_advice.py:47-63` |
   | 횡단보도 | 로봇 카메라가 볼 때. Fleet은 보내지 않는다 | `line_follow/crosswalk/zone.py:1-9`, `crosswalk/gate.py:70-78` |
   | 바퀴 경로의 다음 지형 하나(`context.next`) | 차로 신호에 실을 때만(`guide_context` 기본 꺼짐) | `protocol/lane_cue.py:33-56`, `operations/fleet/fleet/localization/lane_compliance.py:96` |

2. **지시 슬롯은 하나다.** Fleet은 CORE가 기동 중이면 새 지시를 보내지 않는다(`trip_runner.py:681-685` `_core_busy`). 굽이 지시가 슬롯을 쥔 동안 그 뒤 교차로는 로봇에게 없다(`trip_runner.py:650-651`).

3. **지시의 거리는 받은 순간부터 잰다.** 교차로 창은 받은 때의 `trail.odometer`에서 잰다(`line_follow/recovery/junction/approach.py:100-111`, 선 = `expect_in − pivot − (odometer − 받은 때 odometer)` `:168`). 읽기→계산→전송 사이에 로봇이 간 거리가 오차다.
   - 교차로는 그 오차를 허용치로 덮는다: `expect_tol_m`에 `max_speed × (자세 나이 + 읽기→전송 + SEND_ALLOWANCE_S 0.2 s)`가 들어간다(`trip_ports.py:243,350-365`).
   - 굽이는 거리를 앞당긴다: `lead = max_speed × (자세 나이 + 읽기→전송 + bend_send_s)`(`trip_ports.py:409-415`, `bend_send_s` 기본 0.01 `:182`). 같은 줄의 기록: 앞당김 없이 2 cm 늦게, +0.2 s로 2 cm 일찍(Gazebo m16/m17). rosy-44(2026-10-15): 0.2 s 앞당김은 이미 뺐고 현장 값은 `bend_send_s`로 둔다. m16/m17 안쪽 12–22 mm, m18 뒤 중심 ±7 mm.
   - 정확한 고침은 이미 반쯤 있다. Fleet은 굽이 지시의 `map_entry.odom_stamp_s`로 지도 자세가 묶인 odom 시각을 이미 보낸다(D-759, `trip_runner.py` `_step_lane`·`bend_fields`). CORE는 그 시각의 표본을 정확히 찾는다(D-758 0단계, `line_follow/authority.py:64-75,180-197`).

4. **끊긴 동안 다음 사건을 모른다.** D-760 4항: `link_wait` 중에는 새 교차로 지시가 나가지 않는다. 0.6 m 무장 전 장소에 닿으면 로봇은 `waiting`으로 선다(`line_follow/recovery/junction/gate.py:333-339`). 안전하다. 그 정보로 움직이게 하는 것(B부 P3b)은 이 기록이 하지 않는다.

5. **REST 호출이 이미 많다.** trip 로봇 한 대에 0.5 s마다 임대 갱신, 자세 읽기, 교차로 상태 읽기, 교차로 POST 0–1, 통행권 POST, 참고 POST 0–1(`trip_runner.py:417,448-555,430-431`), 차로 신호가 따로 2 Hz다(`operations/fleet/fleet/server/lane_compliance_service.py:48,203-215`). D-760 Context 8은 로봇당 초당 약 20회로 쟀다.

6. **D-531 `route_context`는 Fleet→로봇 통로가 아니다.** CORE gateway가 **자기가 쥔 지시 하나**에서 만들어 인식 keeper에 주는 ROS 토픽 `line/route_context`다(D-531 1·2항). 필드는 한 장소(`seq`·`place_id`·`map_id`·`kind`·`ahead_m` 창·`lane_turn_deg`·`curvature_1pm`), 수명 ≤ 1 s(`protocol/route_context.py:40`), 5 Hz, keeper는 거부(HOLD 쪽)로만 쓴다(4항). keeper는 문맥의 `seq`를 관측에 실어 돌려주고 CORE는 그것이 **지금 쥔 지시의 seq**와 다르면 관측을 무효로 한다(3항). D-531 1항은 "새 Fleet 필드는 없다"이고 설정 `route_context_enabled` 기본 false다.

7. **Fleet→로봇 참고 통로로 이미 있는 것은 차로 신호다.** D-511 `POST /api/v1/line-follow/lane-cue`는 Fleet 현장 등록 토큰만 받고(`middleware/core/api/core_api_web/api/v1/line_follow.py:391-397`), 2 Hz, `ttl_s` ≤ 2, `pose_stamp`, `seq`, `fleet_epoch`를 갖는다(`protocol/lane_cue.py:59-71`). rev 6 `LaneContext`는 바퀴 경로(`route: "lap"`)의 다음 지형 하나(`next`)를 싣는다.

8. **문서가 코드와 다르다.** `protocol/lane_cue.py:7`과 `operations/fleet/fleet/server/lane_compliance_service.py:213`은 횡단보도 구역이 통행권 `crosswalks[]`로 간다고 적었지만 `LineAuthorityRequest`에 그 필드가 없다(`protocol/line_authority.py:34-49`).

9. **크기.** `trip_runner.py` 901줄은 판정 751 + 150에 닿아 있고(`test/architecture/test_module_structure.py:314-315`), D-766 ratchet 뒤에는 천장이다. `trip_ports.py`는 600줄이다. D-763 조각 4가 trip 코드를 `operations/fleet/fleet/server/trips/`(2,272줄 단위)로 옮기는 중이다(rosy-fc). D-766: Fleet 부모가 2,000줄을 넘으므로 새 작은 크기 단위는 만들 수 없고(새 단위 ≥ 1,000줄), 기존 단위 안의 새 파일은 된다.

### Decision

**원칙.**
- 거리는 Fleet이 계산한 자세의 odom 시각부터 잰다(D-517 4, D-550 3). 지연을 추정해 빼지 않는다.
- 미리보기는 **참고**다. 로봇을 더 조심스럽게만 할 수 있다. 허가를 읽는 CORE 코드는 미리보기를 읽지 않는다(D-550 2항).
- 먼저 Fleet에서 만들고, 보이고, 독립된 참값으로 잰다. 로봇에 보내는 것은 그다음이고, 쓸 곳(P2)이 정해질 때만이다.

#### A부 — 시각 붙은 지시 (따로 작은 브랜치, Safety-Review)

1. **필드.** `POST /api/v1/line-follow/junction`에 선택 최상위 필드 `pose_stamp`(float > 0, CORE 벽시계, 스냅숏 `odom_pose.stamp`)를 더한다. 뜻: 이 지시의 `expect_in_m`과 `bend_in_m`은 그 stamp의 odom 표본에서 Fleet이 본 자세로부터 잰 거리다. 값은 같은 주기의 `map_entry.odom_stamp_s`(D-759)·통행권 `pose_stamp`와 같다. 각 필드의 기준점은 그대로다(`expect_in_m`은 로봇의 차로 투영점, `bend_in_m`은 지금처럼). 바뀌는 것은 시간 기준뿐이다.
2. **CORE.** 받을 때 `_odom_entry`(D-758 0, 정확한 표본)로 그 표본을 찾고, 같은 표본의 **교차로 주행 거리계** 값 `trail.odometer_at(표본)`을 창·굽이 통과의 기준으로 둔다(지금은 받은 때의 `trail.odometer`). 통행권의 `_odom_log` 경로 길이(`path_m`)와 교차로의 `trail.odometer`는 다른 누적기이므로 섞지 않는다. 표본은 `_odom_entry`로 찾고 거리는 `trail`로 잰다. 두 누적기가 같은 표본에서 같은 시각을 가리키는지는 구현 시험이 고정한다.
3. **못 쓰면 오늘의 기준.** 표본이 없거나(`no_sample`), 2 s보다 오래됐거나(`stale`), CORE 시계보다 0.05 s 넘게 앞서거나(`future`), 같은 stamp 둘(`ambiguous`), odom epoch·frame이 다르면(`epoch`) 지시는 거절하지 않고 받은 때를 기준으로 쓴다. 상태 `line_follow.junction.distance_basis: stamp|receipt`와 `distance_basis_reason`에 남긴다. 상수는 D-744·D-759의 `ARC_ANCHOR_MAX_AGE_S` 2, `STAMP_TOL_S` 0.05 그대로다.
4. **능력과 Fleet.** CORE는 `base_velocity`에 `lane_instruction_stamp`(설정 `line_follow.instruction_stamp_enabled` 기본 false와 묶음)를 알린다. Fleet은 이 능력이 참인 로봇에 `pose_stamp`를 싣고, 그 로봇의 `bend_in_m`에서 앞당김을 빼며(`lead` = 0), `expect_tol_m`에서 읽기→전송·`SEND_ALLOWANCE_S` 항을 뺀다(자세 나이·dead reckoning·드리프트 항은 남는다). 받은 때 기준으로 떨어진 경우는 앞당김 없는 오늘의 오차(2 cm 늦음 꼴)이고 `bend_tol_m` 최소 0.12 안이다.
5. **검토.** 교차로 게이트 경로라 **Safety-Review**. 이것이 개정 전의 P3a를 대신한다. 미리보기와 관계없다.

#### B부 — 경로 미리보기

6. **P0: Fleet만.** `operations/fleet/fleet/server/trips/trip_preview.py`(D-763 조각 4 뒤의 `server/trips/` 단위, rosy-fc)가 trip 로봇마다 미리보기를 만들고, 기록하고, 관제에 보인다. 로봇에 보내지 않는다.
   - **내용.** `{leg_id, seq, pose_stamp, map_version, horizon_m, events[{s_m, at_m, kind, place_id, params}]}`. `s_m`은 trip 경로 위 절대 위치, `at_m = s_m − s_front`(블록 표의 앞 끝 `front_d_m`과 같은 기준, `operations/fleet/fleet/traffic/lane_traffic.py:280-293`). 지시와 비교할 때는 앞 끝과 차로 투영점의 차이(로봇 몸 앞 끝 거리)를 명시적으로 더하거나 뺀다.

     | `kind` | 지점(`s_m`) | `params` | 새 코드인가 |
     |---|---|---|---|
     | `turn` | 교차로 장소(회전 축) | `action`(left·right·straight·stop), `turn_deg`, `line_before_m`(가로선은 `s_m − line_before_m`; D-507 `pivot_past_line_m`, 갈래는 0) | 장소 위치·`line_past`·`turn_target`은 있는 기하. 다음 구간들로 넘어가며 찾는 것은 새 코드 |
     | `bend` | 굽이 호 시작점(앞당김 없음) | `turn_deg`, `radius_m` | `next_bend`는 지금 구간만 본다(`operations/fleet/fleet/server/ledger/trip_ports.py:384-392`). 여러 구간을 보는 것은 새 코드 |
     | `arc` | 차로 호(D-520) 시작점 | `curvature_1pm`, `length_m` | `exit_segment` 기하 |
     | `crosswalk` | **CORE가 쓰는 앞쪽 경계**(D-491 near, D-573 `s_wait` 전) | `zone_id`, `length_m` | **새 코드**: site map 다각형(`operations/fleet/fleet/site_map.py:196-212`)을 trip 경로에 투영하는 함수가 없다 |
     | `signal` | 정지선 | `signal_id`, `approach`(색은 D-551 몫) | `signal_ahead`는 하나만 준다. 경로 위 여럿은 새 코드 |
     | `stop` | trip 끝, 운영자 보류, `hold_back` 정지 | `reason` | `hold_back_m`, trip 끝 |
     | `authority_end` | 이 주기에 보낸 통행권 끝의 복사본 | `authority_id` | `TripAuthority.body` |

   - **같은 것은 기하뿐이다.** 지시 필드 함수(`junction_fields`·`bend_fields`)는 지금 자세·앞당김에 기대고 2 m 넘으면 거절하므로 미리보기에 쓰지 않는다. 미리보기는 그 함수들이 쓰는 기하(장소 위치, 선 위치, 호 시작·반지름, 출구 호)를 같이 쓴다.
   - **범위.** `horizon_m = min(2.0, trip 끝까지, max(R + d_stop, v_top × 8 s))`, 사건 8개에서 자른다. `R`은 받은 통행권 끝(`hold_back`이면 0), 8 s는 trip 임대 `T_keep`(D-760 1). 2.0은 `expect_in_m`의 (0, 2]·D-754 `MAX_AHEAD_M`과 같다.
   - **자세.** D-760 8항 공유 상태 읽기에서 `max_age_s`를 말하고 받는다. `trip_preview.py`를 `operations/fleet/test/test_shared_state_read.py`의 `PERIODIC`에 넣는다.
   - **보이기.** `/api/fleet/traffic` 로봇 행과 관제 로봇 카드 한 줄("예고: 0.42 m 왼쪽 회전 · 0.95 m 횡단보도"). 다단계 작업의 다음 단계는 싣지 않는다. D-763 `work_read`에는 넣지 않는다(rosy-fc).
   - **일관성.** 지시를 보낼 때 같은 `place_id` 사건의 `s_m`과, 지시를 만든 자세의 `s`에 **앞당김 전** 거리를 더한 값을 비교한다. 같은 그래프·같은 지도라 허용치는 0.005 m(3자리 반올림 두 번)다. 넘으면 `preview_mismatch{kind}`.

7. **P0 정확도 — 재기 전에 정한 기준. 참값은 Fleet 지시와 독립이다.**
   - **Gazebo(원격 `--pick sim`, 2대 30분).** 참값: 시뮬레이터의 로봇 참 자세와 world 파일의 장소·선·횡단보도·호 위치. 예측 때 `at_m`과, 로봇이 그 사건 지점(앞 끝 기준)을 지난 순간 참 자세로 잰 그동안의 경로 길이를 비교한다.
     - 오차 p95 ≤ 0.03 + 0.05 × `at_m`(m). 0.05/m는 Fleet `ODOM_DRIFT_PER_M`(`trip_ports.py:240`)이다. 2 m에서 0.13 m다.
     - 놓침(참값 사건이 그때 `horizon_m` 안인데 목록에 없음) ≤ 1%, 헛사건(목록에 있는데 경로 위에 없음, 재계획·보류 제외) ≤ 1%.
   - **장치(2대 10바퀴, 사용자가 말한 뒤).** 참값: 로봇 자신의 카메라 목격. 교차로·굽이는 목격 때의 `junction_ahead_m` + 미리보기 `pose_stamp` 표본에서 그 목격 표본까지의 odom 경로, 횡단보도는 CORE 횡단보도 구역의 앞쪽 경계(odom). 로봇 기록에서 오프라인으로 맞춘다.
     - 오차 p95 ≤ 0.10 + 0.05 × `at_m`(m). 0.10은 카메라가 한 선을 읽는 퍼짐(`CORRIDOR_HALF_M`, D-754 4항), 0.05/m는 같은 드리프트다.
     - 놓침·헛사건 ≤ 1%.
   - 천장 카메라(Rosy Cam) 자세는 참값으로 쓰지 않는다. 해상도(약 0.12 m)가 기준보다 거칠다.
   - 기준을 못 넘으면 미리보기는 관제 표시로만 남는다.

8. **P1: 로봇에 보내기 — 사용자가 P2를 원한다고 정한 뒤에만.** P1은 로봇 화면에 같은 것을 다시 보이는 것 말고는 쓸 곳이 없다. 표시가 목적이면 P0의 관제 표시로 된다. 그래서 P1은 P2(미리 감속)를 하기로 사용자가 정할 때 그 준비로만 한다.
   - **통로: 차로 신호(D-511)의 `context`.** trip 중인 로봇에는 `LaneContext`의 trip 변형을 싣는다: `route: "trip"`, `leg_id`, `seq`, `pose_stamp`(미리보기 자체의 것), `map_version`, `horizon_m`, `events`(≤ 8, 6항 꼴, `s_m` 대신 `at_m`). 이 로봇에는 `next`를 싣지 않는다(rosy-44: trip에서는 미리보기가 `context.next`를 대신한다). 바퀴 경로(`route: "lap"`)는 그대로다.
   - **왜 이 통로인가.** 이미 있는 Fleet→로봇 참고 통로이고, Fleet 전용 자격만 받고, `pose_stamp`·`seq`·`ttl_s`가 있다. **새 REST 호출이 없다**: 2 Hz 차로 신호에 실려 간다. 바뀐 미리보기는 다음 신호(≤ 0.5 s)에 실린다. 계약은 `rosy.controls/1` 능력 `lane_cue_trip_context`로 연다.
   - **수명.** 차로 신호의 `ttl_s`(≤ 2)를 따른다. 끊기면 2 s 안에 "모름"이다. 끊긴 동안 미리보기로 움직이지 않으므로(P3b 없음) 더 길 이유가 없다. 만료한 미리보기는 아무것도 보이지 않는다.
   - **CORE 저장.** 받을 때 `_odom_entry`로 `pose_stamp` 표본을 찾아 사건마다 odom 지점을 둔다. 같은 `leg_id`에서 `(pose_stamp, seq)` 순서(D-550 4). 새 `seq`는 목록 전체를 바꾼다. 버림: `ttl_s`, `leg_id` 변경, `map_version` 변경, odom epoch·frame 변경, 모드 변경, E-stop. `GET /line-follow`에 `preview`를 보인다.
   - **D-531 `route_context`에 싣지 않는다(rosy-44 제안의 답).** `route_context`는 Fleet이 닿는 통로가 아니라 CORE→인식 ROS 토픽이고(Context 6), 한 장소·≤ 1 s·지금 쥔 지시의 `seq`로 관측을 되맞추는 계약이다. 지시 없는 미리보기 사건을 넣으면 (a) D-531 1항 "새 Fleet 필드는 없다"를 깨고, (b) 3항의 seq 되맞춤이 지시 없는 사건에 대해 정의되지 않으며, (c) keeper의 거부 규칙(B9 `bend_expected` 등)이 Fleet 미리보기만으로 켜져 D-531 6항의 434프레임 규칙을 다시 열어야 한다. 그래서 운반은 차로 신호가 하고, CORE가 저장한 미리보기를 `route_context`의 입력으로 쓸지는 D-531의 별도 개정이 정한다.
   - **대안(차로 신호 쪽이 거절하면).** 개정 전의 전용 엔드포인트 `POST /api/v1/line-follow/preview`(trip 주기, 바뀔 때 바로 + `ttl_s/2` 유지, `ttl_s = min(5, 이 주기에 보낸 통행권 ttl)`, 옛 로봇은 2 s). REST 호출이 로봇당 초당 1회 이하로 는다.
   - **import-lint.** `line_follow/authority.py`와 `line_follow/recovery/junction/gate.py`가 미리보기 저장소나 그 schema를 import 하면 시험이 실패한다. 성질 시험: 모든 입력에서 통행권 상태와 교차로 게이트 결정이 미리보기 유무와 같다.

9. **P2: 미리 감속(Safety-Review, 기본 꺼짐).** 다음 감속 사건(`turn` left·right·stop, `bend`, `crosswalk`, `stop`)의 지점에서 `v_event(kind)`가 되도록 `cap = sqrt(v_event² + 2·a·max(0, in_m − margin))`를 낸다.
   - **마지막 `min` 클램프 하나.** `decision.linear = min(decision.linear, max(cap, v_floor))`. CORE의 교차로 접근 감속(`slow_from`), 횡단보도 `v_cross`, D-551 9항 신호 상한과 모두 `min`이다. 더하지 않는다. 0은 0으로 남는다(D-422 몸체 정지, HOLD).
   - **신호 대기는 뺀다.** `signal` 사건과 D-620 신호 대기는 정지이고 감속 대상이 아니다.
   - D-551 9항 불변식 그대로: `v_floor` ≥ 측정한 바퀴 데드밴드(D-500), 같은 `leg_id` 통행권이 FREE·HOLDING이고 만료 전일 때만(`hold_back`은 표시만), D-407 래치를 쓰지 않는다. 설정 `line_follow.preview_slowdown_enabled` 기본 false.
   - 이 클램프는 허가 판정이 아니다. 명령을 낮출 뿐이고, 통행권·교차로 게이트 코드는 이것을 읽지 않는다(D-550 2항 "더 조심스럽게만").

10. **P3b: 끊긴 동안 미리보기로 무장 — 미룬다.** 참고를 허가로 쓰는 일이라 D-550 2항 개정이 먼저다. rosy-44: "지금은 아니다". 그때까지 끊긴 로봇은 지시 없는 장소에서 오늘처럼 선다.

11. **단계.** 앞 단계의 끝난 기준을 넘어야 다음 단계를 한다. Gazebo와 호스트 시험은 원격이다(D-584).

    | 단계 | 무엇 | 끝난 기준 | 검토 | 되돌림 |
    |---|---|---|---|---|
    | A | 시각 붙은 지시(1–5항) | 호스트: 0.2 s 늦게 닿은 지시의 굽이 시작이 0.005 m 안, 떨어짐 사유 각각, 설정 꺼짐 = 오늘. Gazebo: 굽이 시작 오차가 m18 기준(±7 mm)보다 나쁘지 않고 `junction_unexpected` 증가 없음. 장치 2대 10바퀴 | **Safety-Review** | 설정 false, Fleet 앞당김 복귀 |
    | P0 | Fleet 미리보기(6항), 관제 표시, 정확도 기록 | 7항 기준, `preview_mismatch` 0 | 코드 리뷰 | 설정 `off` |
    | P1 | 차로 신호 trip 변형, CORE 저장·표시 | **사용자가 P2를 원한다고 정함** + P0 통과. 호스트: 순서·버림·다시 재기·import-lint·성질 시험 | 코드 리뷰(움직임 없음) | Fleet이 trip 변형을 싣지 않음 |
    | P2 | 미리 감속(9항) | 호스트: D-551 9항 시험 목록 + 종류별 감속 시작점 + `slow_from`·`v_cross`와 `min`. Gazebo 2대 30분 접촉 0·블록 중복 0·정체 판정 증가 없음. 장치 2대 10바퀴 | **Safety-Review** | 설정 false |
    | P3b | 끊긴 동안 무장 | D-550 개정 | 사용자 결정 | — |

    A와 P0은 서로 다른 파일이라 같이 갈 수 있다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 로봇이 전체 경로를 받아 스스로 앞을 계획한다 | 기각(지금). D-760 Alternatives와 같은 이유: 요구는 몇 초 앞이고 지도·재계획·블록 표를 로봇과 맞추는 비용이 크다. CORE는 지도 자세를 갖지 않는다(D-744·D-759) |
| 사건 종류마다 따로 민다 | 기각. 엔드포인트·송신기·능력이 종류만큼 생기고 REST 호출이 는다(Context 5). "이 거리 안에는 이것뿐"을 말할 수 없다 |
| 통행권 메시지에 사건 목록을 싣는다 | 기각. 허가와 참고가 섞인다(D-550 원칙, O4). `hold_back` 현장은 받지 못한다 |
| D-551 신호 참고에 합친다 | 기각. 신호 색은 자주, 미리보기는 바뀔 때만 간다. D-551은 구현돼 있다 |
| D-531 `route_context`로 운반한다 | 기각(8항): Fleet이 닿는 통로가 아니고, 지시 없는 사건이 seq 되맞춤과 keeper 거부 규칙에 맞지 않는다 |
| 미리보기로 지시의 거리를 다시 잰다(개정 전 P3a) | 기각(critic HIGH-1·2, rosy-44). 미리보기 지점은 최대 2.5 s·2 m 묵어 드리프트 약 0.10 m(0.05/m)로 시각 붙은 지시보다 나쁘다. 허가 판정 코드가 참고를 읽게 되어 D-550 2항과 어긋난다. A부가 같은 일을 지시 자신의 stamp로 10–20줄에 한다 |
| 미리보기 전용 엔드포인트(개정 전 2항) | 차로 신호 쪽이 거절할 때의 대안(8항). REST 호출이 는다 |
| 허브 하트비트 답 | 미룸. 현장은 페어링되지 않았다(D-550 확인 절) |

### Consequences

- A부가 켜진 로봇은 굽이·교차로 거리에서 링크 지연 추정이 없어진다. 사이트마다 `bend_send_s`를 맞추던 일이 없어진다.
- 관제에 "몇 m 앞에서 무엇"이 보인다(P0). 로봇 움직임은 P2 전까지 바뀌지 않는다.
- P1이 열리면 trip 로봇에는 `context.next` 대신 사건 목록이 간다. 새 REST 호출은 없다.
- `preview_mismatch`가 Fleet 기하 결함의 새 감지기가 된다.
- 끊긴 동안 로봇은 그 정보로 움직이지 않는다(P3b 전). 링크가 돌아온 뒤 한 번 서고 가는 것은 그대로다.

### 위험

1. **크기.** `trip_runner.py`(901)는 ratchet 천장이다. 배선 한 줄은 같은 커밋에서 실제 줄 하나 이상을 비워 갚는다(문장 합치기 금지, rosy-fc). `trip_ports.py`(600)에는 아무것도 더하지 않는다: A부의 Fleet 변경(앞당김 0, 허용치 항 빼기)은 줄을 늘리지 않는 꼴로 하거나 줄을 옮긴 뒤에 한다. B부 코드는 `server/trips/trip_preview.py` 새 파일 하나다(`traffic/`에 두면 `traffic → trips` import가 방향을 뒤집는다). D-763 조각 4 착지와 main 병합이 먼저다. CORE 쪽 새 저장소는 `line_follow` 최상위(여유 약 100줄)나 `line_follow/cue`(약 140줄) 안의 파일로 한다.
2. **미리보기를 허가로 읽는 사람.** 관제 문구는 "예고"이고 지시 상태(`armed` 등)를 옆에 보인다.
3. **지도 오류.** 장소·호 반지름이 틀리면 미리보기와 지시가 같이 틀린다. P0 참값 비교가 이것을 드러낸다.
4. **두 누적기(A부 2항).** `_odom_log` 경로와 `trail.odometer`의 표본 시각이 어긋나면 기준이 틀린다. 같은 표본을 가리킴을 시험으로 고정하고, 못 찾으면 받은 때 기준(오늘)으로 떨어진다.
5. **Pi 시계.** `pose_stamp`는 CORE 벽시계다. 정확한 표본 찾기(D-758 0)가 벽시계 튐을 막고, 같은 stamp 둘이나 뒤로 간 벽시계는 받은 때 기준으로 떨어진다.

### Open — 사용자에게 남은 것

1. **P2(미리 감속)를 원하는가?** 원하지 않으면 B부는 P0(관제 표시와 측정)에서 멈추고 P1도 하지 않는다.
2. A부를 B부와 별개로 먼저 해도 되는가(지금 굽이 오차는 m18 뒤 ±7 mm로 이미 작다. 이득은 현장마다 `bend_send_s`를 맞추는 일을 없애는 것이다)?
3. P1의 통로를 차로 신호 trip 변형으로 할지, 전용 엔드포인트로 할지(8항). D-511 담당 세션의 동의가 필요하다.
4. 저장한 미리보기를 D-531 `route_context`의 입력으로 쓸지는 D-531 개정으로 따로 정한다. 지금 열지 않아도 되는가?

### 개정 1 (2026-10-15) — critic REVISE와 rosy-44·rosy-fc 답 반영

| 지적·답 | 고친 곳 |
|---|---|
| HIGH-1 P3a가 D-550 2항(51행)과 "고치는 결정: 없다"에 어긋남 | P3a 삭제. 거리 문제는 A부(지시 자신의 stamp). 「고치는 결정」을 D-507 3항·굽이 보충, D-754 앞당김, D-511 rev 6으로 바로 씀 |
| HIGH-2 더 싼 고침이 반쯤 있음(`map_entry.odom_stamp_s`, `_odom_entry`), 미리보기 지점은 드리프트로 더 나쁨 | A부 1–5항, Alternatives 행 |
| HIGH-3 P0 기준이 순환(Fleet 지시가 일어난 때를 정함)이고 천장 카메라 해상도보다 촘촘함 | 7항: Gazebo 참 자세, 장치는 로봇 카메라 목격 + odom. Rosy Cam은 참값에서 뺌. 기준을 거리에 비례하게 |
| MEDIUM "같은 함수"는 기하뿐 | 6항 표 「새 코드인가」, "같은 것은 기하뿐이다" |
| MEDIUM `preview_mismatch`가 앞당김 뺀 점과 비교 | 6항: 앞당김 전, 허용치 0.005 m |
| MEDIUM 기준점 변환 | 6항(`at_m` 앞 끝 대 `expect_in_m` 투영점), A부 2항(`_odom_log` 대 `trail.odometer`) |
| MEDIUM ttl, "바뀜"의 뜻, 크기 등록 | 8항(차로 신호 ttl, 대안의 `min(5, 통행권 ttl)`), 계획의 "바뀜" = 사건 집합·절대 위치·params, 위험 1 |
| MINOR horizon을 trip 끝에서 자름, `route_rev` 규칙 삭제(`leg_id`에 들어 있음), 전체 경로, pivot 식 | 6항 범위, 8항 버림, Context 1, 6항 `turn`(`line_before_m`) |
| rosy-44: 2 cm는 일부 고쳐짐, 정확한 고침은 지시의 stamp, P3a 불필요, 기준 m16/m17·m18 | Context 3, A부, P3a 삭제 |
| rosy-44: 횡단보도 지점 = CORE 앞쪽 경계 | 6항 표 |
| rosy-44: P2는 `slow_from`·`v_cross`와 `min`, 신호 대기 제외 | 9항 |
| rosy-44: P3b 지금 아님 | 10항 |
| rosy-44: 새 통로 대신 `route_context` | 8항: 조사 결과 실을 수 없음(Context 6), 차로 신호 통로를 최소 대안으로 |
| rosy-44: trip에서는 미리보기가 `context.next`를 대신 | 8항 |
| rosy-fc: `server/trips/trip_preview.py`, 새 작은 단위 불가, `trip_ports.py` 추가 없음, `trip_runner.py` 한 줄은 실제 줄로 갚음, 조각 4 뒤 main 병합 | 6항, 위험 1, 계획 |
| rosy-fc: 다음 단계 미리보기 없음, `work_read`에 넣지 않음, 공유 상태 읽기 `max_age_s`·`PERIODIC` | 6항 |
| rosy-fc: 바뀔 때 + `ttl/2` 유지, 만료는 아무것도 안 보임 | 8항(대안 경로), 계획 |
| 조정자: P1은 사용자가 P2를 원할 때만 | Status, 8항, 11항, Open 1 |
