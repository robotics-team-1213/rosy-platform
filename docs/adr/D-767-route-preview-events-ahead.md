## D-767 경로 미리보기 — Fleet이 trip 주기마다 "몇 m 앞에서 무엇이 오는가"를 사건 목록 하나로 보내고, 로봇은 먼저 보여 주기만 한다

**Status:** Proposed (2026-10-15). 사용자 요청 "상황을 미리 주는것도 고려해야하지 않아? 몇초뒤 혹은 몇m 앞에서 어떻게 해야한다는 네비게이션". 사용자 결정: "ADR과 계획을 먼저 쓰고, 동료 세션과 토론하고, 승인 뒤에만 코드". 이 기록에는 코드가 없다. 계획은 [`docs/plans/2026-10-15-d767-route-preview-plan.md`](../plans/2026-10-15-d767-route-preview-plan.md)다. P0·P1은 움직임을 바꾸지 않는다. P2(미리 감속)와 P3(미리 무장)는 각각 **Safety-Review**를 받고 기본 꺼짐으로 연다.

잇는 결정: [D-550](D-550-fleet-robot-communication-contract.md)(네 종류, 시간 기준·순서, 운반 경로, 규칙 M) · [D-551](D-551-d525-signal-advice-delivery.md)(참고 전달의 본보기: 표시 먼저, 행동은 뒤에 Safety-Review·기본 꺼짐) · [D-517](D-517-multi-robot-lane-traffic.md) 4(통행권 `until_m`·`pose_stamp`·`leg_id`·`ttl_s`) · [D-760](D-760-fleet-motion-bounds-ride-through.md)(5 s 버티기, `seq`, `link_wait`, 개정 1–3) · [D-758](D-758-robot-held-site-anchor.md) 0단계(정확한 stamp로 odom 표본 찾기) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)·[D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(교차로·굽이 지시) · [D-754](D-754-bend-next-line-distance.md)·[D-759](D-759-bend-map-entry-heading.md)(굽이 필드) · [D-744](D-744-map-anchored-lane-arc.md)(지도 고정 호) · [D-525](D-525-virtual-signal-fleet-zone-gate.md)(가상 신호) · [D-573](D-573-crosswalk-stop-look-cross.md)(횡단보도) · [D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md) rev 6(차로 신호 `context.next`) · [D-531](D-531-route-context-to-lane-keeper.md)(CORE 경로 문맥) · [D-620](D-620-junction-fleet-signal-query.md)(교차로 신호 질의) · [D-763](D-763-fleet-work-kinds-composed-steps.md)(Fleet 작업 종류) · [D-766](D-766-size-limits-split-on-exceed.md)(줄 수 한도).
고치는 결정: 없다. D-550 2항 표에 참고 행 하나(경로 미리보기)를 더한다. P3b를 택하면 그때 D-550 2항을 고치는 개정이 따로 필요하다(Decision 9).

### Context

2026-10-15 main(`64d15df7e`) 코드를 읽은 결과다. 실행한 시험은 없다.

1. **로봇이 미리 아는 것은 거리 하나와 지시 하나뿐이다.**

   | 로봇이 아는 것 | 언제 | 근거 |
   |---|---|---|
   | 통행권 끝 `until_m` | trip 주기(0.5 s)마다. 통행권이 켜진 현장만 | `traffic/trip_authority.py:75-89`, 주기 `ledger/trip_ports.py:140`, `trip_runner.py:402,427-430` |
   | 다음 교차로 지시(`expect_in_m` 포함) | 장소 앞 `arm_distance_m` 0.6 m 안에 들어왔을 때 | `ledger/trip_runner.py:603`, `trip_ports.py:142`, `expect_in_m` = 그때 남은 거리 `trip_ports.py:325-343` |
   | 다음 굽이 지시(`bend_in_m`) | 호 시작점 0.6 m 안. 교차로 지시보다 먼저 | `trip_runner.py:649-678` |
   | D-525 앞 신호 | trip 주기마다, 표시만(D-551) | `traffic/trip_advice.py:47-63`, CORE는 결정 경로에서 읽지 않는다(`protocol/line_advice.py:1-6`) |
   | 횡단보도 | 로봇 카메라가 볼 때. Fleet은 보내지 않는다 | `line_follow/crosswalk/zone.py:1-9`, `crosswalk/gate.py:70-78` |
   | 차로 다음 지형 하나(`context.next`) | 차로 신호에 실을 때만(`guide_context` 기본 꺼짐) | `protocol/lane_cue.py:33-56`, `localization/lane_compliance.py:96` |

   (Fleet 경로는 `operations/fleet/fleet/`, CORE는 `middleware/drive/behaviors/line_follow/`, 계약은 `contracts/foundation/core_common/protocol/` 기준이다.)

2. **지시 슬롯은 하나다.** Fleet은 CORE가 기동 중이면 새 지시를 보내지 않는다(`trip_runner.py:681-685` `_core_busy`). 굽이 지시가 슬롯을 쥔 동안 그 뒤 교차로는 로봇에게 없다(`trip_runner.py:650-651`). 로봇은 "다음 다음"을 모른다.

3. **지시의 거리는 받은 순간부터 잰다.** 교차로 창은 받은 때의 odom 주행 거리에서 잰다(`recovery/junction/approach.py:100-111,177-191`). 통행권처럼 `pose_stamp`로 다시 재지 않으므로, 읽기→계산→전송 사이에 로봇이 간 거리가 오차가 된다. 교차로는 이 오차를 `expect_tol_m`을 넓혀 덮고(`trip_ports.py:350-365`, `SEND_ALLOWANCE_S` 0.2 s `:243`), 굽이는 거리를 앞당긴다: `lead = max_speed × (자세 나이 + 읽기→전송 + bend_send_s)`(`trip_ports.py:409-415`, `bend_send_s` 기본 0.01 `:182`). 같은 줄의 기록: 앞당김 없이 2 cm 늦게, +0.2 s로 2 cm 일찍 시작했다(Gazebo m16/m17, rosy-44 측정). CORE는 그 위에 `bend_tol_m`까지 일찍 넘겨받을 수 있다(`recovery/junction/bend.py:37,159-172`, `BEND_LEAD_M` 0.25). 지연을 추정해 빼는 방식이라 링크 지연이 바뀌면 다시 어긋난다.

4. **끊긴 동안 다음 사건을 모른다.** D-760 4항: `link_wait` 중에는 새 교차로 지시가 나가지 않는다. 로봇은 들고 있는 통행권(≤ 5 s, 0.10 m/s 상한에서 ≤ 0.5 m)으로 가지만, 그 안의 장소에 아직 지시가 없으면(0.6 m 무장 전) 지시 없는 교차로에서 `waiting`으로 선다(`recovery/junction/gate.py:333-339`). 안전하지만 링크가 돌아와도 한 번 더 서고 간다.

5. **REST 호출이 이미 많다.** trip 로봇 한 대에 0.5 s마다 임대 갱신, 자세 읽기, 교차로 상태 읽기, 교차로 POST 0–1, 통행권 POST, 참고 POST 0–1이 나가고(`trip_runner.py:417,448-555,430-431`), 차로 신호가 따로 2 Hz다(`server/lane_compliance_service.py:48,203-215`). D-760 Context 8은 로봇당 초당 약 20회로 쟀다. 사건마다 엔드포인트를 더하면 이 수가 사건 종류만큼 는다.

6. **미리보기 비슷한 통로가 이미 셋 있고 모두 한 가지만 본다.** D-551 신호 참고(신호 하나), D-511 `context.next`(바퀴 경로 `route: "lap"`의 다음 지형 하나, trip 구간·`leg_id` 없음, 차로 유지의 사전 정보), D-531 `route_context`(CORE가 쥔 지시에서 만든 1 s짜리 인식 문맥, 기본 꺼짐 `line_follow/route_context.py:9-50`). trip 경로를 따라 여러 사건을 순서대로 말하는 통로는 없다.

7. **문서가 코드와 다르다.** `protocol/lane_cue.py:7`과 `server/lane_compliance_service.py:213`은 횡단보도 구역이 통행권 `crosswalks[]`로 CORE에 간다고 적었지만 `LineAuthorityRequest`에 그 필드가 없다(`protocol/line_authority.py:34-49`). 이 기록은 그 길을 만들지 않는다. 두 주석은 P0에서 고친다.

8. **D-758 0단계는 착지했다.** 통행권·호·굽이의 stamp 조회는 스냅숏이 낸 stamp와 정확히 같은 odom 표본을 찾고(`line_follow/authority.py:34-36,64-75`), 같은 stamp 둘이나 벽시계가 뒤로 간 경우는 거절한다. odom 기록은 50 Hz로 4 s 이상이다(`authority.py:44`).

### Decision

**원칙.**
- 미리보기는 **참고**(D-550 2항)다. 로봇을 더 조심스럽게 할 수는 있어도 더 멀리, 더 일찍, 더 오래 움직이게 하지 못한다.
- 같은 사건을 두 곳에서 계산하지 않는다. 미리보기는 실제 지시를 만드는 Fleet 함수와 같은 함수로 만든다.
- 위치는 `pose_stamp` 자세에서 잰 경로 미터다. 로봇이 자기 odom으로 다시 잰다(D-517 4, D-550 3).
- 먼저 보고 재고, 그다음 보여 주고, 그다음에만 행동한다.

1. **종류: 참고. 허가가 아니다.**
   - 통행권 끝을 넘게 하지 않는다. HOLD·EXPIRED·NONE에서 출발·재개시키지 않는다. 어떤 TTL도 늘리지 않는다(통행권·임대·교차로 지시).
   - 교차로 지시를 대신하지 않는다. 미리보기에 `turn`이 있어도 지시가 없으면 로봇은 오늘처럼 그 장소에서 `waiting`으로 선다.
   - 로봇 자신의 감지(카메라 교차로·횡단보도, D-422 몸체 정지, IR 가드, LiDAR)가 최종이다. 미리보기와 감지가 다르면 감지가 이긴다. 미리보기에 없는 사건도 감지되면 오늘처럼 다룬다.
   - import-lint: `line_follow/authority.py`와 `recovery/junction/gate.py`는 미리보기 모듈을 import 하지 않는다(D-551 7항과 같은 시험). P3a가 열리면 gate.py의 예외는 그 단계의 Safety-Review가 정한다.

2. **계약(추가).** `POST /api/v1/line-follow/preview`(Operator, 통행권과 같은 토큰). 공유 schema는 새 모듈 `core_common.protocol.route_preview`, `extra="forbid"`.

   ```
   {
     preview_id:  str 1–160,
     leg_id:      str 1–128,          # 통행권과 같은 trip 구간 id ({trip_id}:{route_rev}:{FLEET_EPOCH})
     seq:         int ≥ 0,            # (로봇, 구간)마다 증가
     fleet_epoch: str 1–64,
     pose_stamp:  float > 0,          # CORE 스냅숏 odom_pose.stamp 그대로 (D-758 0: 정확한 표본)
     ttl_s:       0 < s ≤ 5,          # 통행권 MAX_TTL_S와 같은 상한
     map_version: int, route_rev: int,
     horizon_m:   0 < m ≤ 2,          # pose_stamp 자세의 앞 끝에서 이 거리까지는 사건이 빠짐없이 실렸다. 그 너머는 모름
     events: [                        # at_m 오름차순, 최대 8개
       { at_m:     float −0.5 – 2,    # pose_stamp 자세의 앞 끝 → 사건 지점, trip 경로를 따른 미터. 음수 = 이미 안
         kind:     turn|bend|arc|crosswalk|signal|stop|authority_end,
         place_id: str|null,
         params:   {...}              # 종류마다 아래 표, extra 금지
       }, ...
     ]
   }
   ```

   | `kind` | 지점(`at_m`) | `params` | 만드는 Fleet 함수(같은 것을 쓴다) |
   |---|---|---|---|
   | `turn` | 교차로 장소의 가로선(지시 `expect_in_m − pivot_past_line_m`과 같은 점) | `action`(left·right·straight·stop), `turn_deg`, `pivot_past_line_m` | `lane_action`, `turn_target`, `junction_fields` |
   | `bend` | 굽이 호 시작점(지시 `bend_in_m`의 점, 앞당김 없음) | `turn_deg`, `radius_m` | `next_bend`, `bend_fields`의 기하 |
   | `arc` | 차로 호(D-520) 시작점 | `curvature_1pm`, `length_m` | `exit_segment` |
   | `crosswalk` | 지도 구역 입구 | `zone_id`, `length_m` | site map 횡단보도 다각형(`site_map.py:196-212`) |
   | `signal` | 정지선 | `signal_id`, `approach`. 색과 남은 초는 싣지 않는다(D-551 참고가 맡는다) | `signal_ahead` |
   | `stop` | trip 끝, 운영자 보류 정지, `hold_back` 정지 | `reason`(trip_end·hold·hold_back) | `hold_back_m`, trip 끝 |
   | `authority_end` | Fleet이 같은 주기에 보낸 통행권 끝의 **복사본** | `authority_id` | `TripAuthority.body` |

   - 닫힌 집합이다. 새 종류는 ADR 행과 능력 판(`line_follow_preview` 값 2)으로 더한다. 속도 구역(`slow`)은 지도에 속도 구역이 생길 때 그 ADR이 더한다(지금 지도에 없다).
   - `authority_end`는 표시·비교용이다. CORE의 통행권 판정은 자기 통행권 저장소만 본다(1항 import-lint). 두 값이 다르면 CORE 통행권이 맞다.
   - `events: []`는 "horizon 안에 사건 없음"이다. 지운다는 뜻은 `horizon_m`이 함께 말한다.
   - 범위 밖·누락은 400 `VALIDATION_ERROR`. 차선 주행이 꺼져 있으면 409 `LINE_FOLLOW_NOT_ACTIVE`. 자세 검사는 통행권과 같은 규칙·이름(409 `AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`·`AUTHORITY_ODOM_STALE`). 응답 `{accepted: bool, reason?}`(`stale`·`duplicate`).

3. **범위(horizon).** Fleet은 `horizon_m = min(H_MAX, max(R + d_stop, v_top × T_keep))`로 정하고, 사건이 8개를 넘으면 9번째 사건 바로 앞에서 자른다.
   - `R + d_stop`: 로봇이 받은 통행권 끝 `R`까지 갈 수 있고 그 뒤 정지 거리 `d_stop`(블록 표가 쓰는 값)만큼 더 미끄러질 수 있다. 로봇이 정당하게 닿을 수 있는 곳의 사건은 빠지면 안 된다. 통행권이 꺼진 현장(`hold_back`)은 `R = 0`이다.
   - `v_top × T_keep`: trip 임대 `T_keep` 8 s(D-760 1항)는 Fleet 없이 로봇이 trip 안에 있을 수 있는 가장 긴 시간이다. 0.15 m/s면 1.2 m, CORE 상한 0.10 m/s면 0.8 m다. 5 s 버티기(K1) 동안 닿을 수 있는 사건을 덮는다.
   - `H_MAX` 2.0 m: 교차로 `expect_in_m`의 (0, 2], 굽이의 `MAX_AHEAD_M` 2(D-754)와 같은 값이다. 그 너머는 Fleet 지도 자세와 로봇 odom의 이월 오차(D-744 `ARC_ANCHOR_MAX_CARRY_M` 1.5)가 사건 위치를 쓸모없게 한다. `R + d_stop`이 2 m를 넘으면 `horizon_m`이 2이고, 로봇은 그 너머를 모른다는 것을 안다.
   - 8개: 현장 지도에서 가장 촘촘한 곳(W4–W3 0.58 m, 회전교차로 호 셋)에서 2 m 안의 사건은 6개를 넘지 않을 것으로 본다(재지 않았다. P0에서 잰다). 8을 넘으면 잘라도 `horizon_m`이 정직하다.

4. **키, 순서, 버림.**
   - 순서는 D-550 4항: 저장된 미리보기가 만료 전이고 같은 `leg_id`이면 `(pose_stamp, seq)`가 오래된 것은 `stale`, 같은 것은 `duplicate`로 버린다.
   - **새 `seq`는 목록 전체를 바꾼다.** 사건을 합치지 않는다.
   - **받을 때 odom으로 옮긴다.** CORE는 받은 순간 `pose_stamp`의 odom 표본을 찾고(D-758 0단계 `_odom_entry`, `authority.py:64-75`), 사건마다 `odom 경로 길이(표본) + at_m`을 저장한다. 그 뒤로는 지금 경로 길이와만 비교하므로 4 s odom 기록에 기대지 않는다(D-744가 받을 때 옮기는 이유와 같다). 경로 길이는 부호가 없어 후진하면 사건이 가까워 보인다. 참고에서는 조심스러운 쪽이다.
   - **버림**: `ttl_s`(받는 쪽 단조 시계, 통행권과 같은 차선 시계) 만료, `leg_id` 변경, 같은 구간에서 `map_version`이나 `route_rev`가 바뀜(새 값의 미리보기만 받는다), odom epoch·frame 변경, 받은 뒤 odom 경로가 `horizon_m`을 넘음, 모드 변경, E-stop. 버린 미리보기는 "모름"이다.
   - Fleet은 활성 지도 버전이 trip의 버전과 다르면(`lane_traffic.py:245-247`과 같은 조건) 보내지 않는다. 그동안 로봇의 미리보기는 `ttl_s`로 끝난다.

5. **노출.**
   - `GET /api/v1/line-follow`와 상태 스냅숏 `line_follow`에 선택 키 `preview {state: fresh|expired|none, seq, age_s, horizon_now_m, events: [{kind, in_m, place_id, params}]}`. `in_m`은 지금 odom으로 다시 잰 거리다. 받은 적이 없으면 키가 없다.
   - 관제 로봇 카드: 다음 사건 둘을 한 줄로("0.42 m 뒤 왼쪽 회전 · 0.95 m 뒤 횡단보도"). 문구는 "예고"이고 허가처럼 읽히지 않게 한다. 로봇 얼굴·LCD는 D-551 4항과 같이 뒤로 미룬다.
   - 기록: 버림마다 `preview_dropped{reason}` 계수, 구간마다 로그 한 줄.

6. **능력과 설정.**
   - CORE는 `rosy.controls/1` `base_velocity`에 `line_follow_preview: true`를 알린다(`protocol/controls.py:75-94` 꼴). 없으면 Fleet은 보내지 않는다.
   - Fleet 사이트 설정 `fleet.trip.route_preview: off | observe | send`(기본 `off`). `observe`는 만들고 기록·노출만 하고 보내지 않는다(P0). `send`는 능력이 있는 로봇에 보낸다(P1). 통행권·신호 참고 설정과 독립이다.

7. **Fleet 송신기(`PreviewSender`).**
   - 통행권과 **같은 trip 주기**에, 블록 표가 쓴 같은 `front_d_m`·`pose_stamp`로 만든다(`lane_traffic.py:280-293`). 미리보기·통행권·신호 참고가 같은 자세를 말한다.
   - **통행권을 늦추지 않는다.** 통행권 다음에 보내고, 그 로봇의 통행권 전송이 진행 중이거나 로봇이 한 단계 처리 중이면 그 주기는 건너뛴다(`trip_runner.py:428-431`의 신호 참고와 같은 자리). 자기 전송 자리 하나, 한도 1.0 s, 재시도 없음.
   - **바뀔 때만, 그리고 적어도 `ttl_s/2`마다.** "바뀜"은 같은 `pose_stamp` 기준으로 다시 잰 목록이 사건 집합·`params`·`horizon_m`에서 0.02 m 넘게 다를 때다. 로봇이 나아가는 것만으로는 다시 보내지 않는다(로봇이 odom으로 다시 잰다). Fleet은 `ttl_s` 5를 보내므로 변화 없는 구간은 2.5 s에 한 번이다. 로봇당 평균 초당 1회 이하를 목표로 P0에서 잰다.
   - 보내지 않는 때: 자세 점프로 UNKNOWN(`waiting_for: pose_jump`), `link_wait`(D-760 4), Fleet 재시작 뒤 `T` 5 s(D-760 5, 같은 이유로 그 사이의 계산을 믿지 않는다), 다른 지도 버전.
   - 로봇마다 보내는 쪽은 하나다(D-550 6). 이 단계는 REST만이다. 허브 하트비트 답은 페어링(D-550 11) 뒤 D-551 5단계와 같이 본다.
   - **일관성 기록.** 실제 교차로·굽이 지시를 보낼 때, 직전 미리보기의 같은 `place_id` 사건과 `action`·`turn_deg`·지점을 비교해 `preview_mismatch{kind}`를 센다. 0이 아니면 두 계산이 갈라진 것이다(원칙 2).

8. **기존 조각과의 관계.**

   | 조각 | 이 기록 뒤 |
   |---|---|
   | 교차로·굽이 지시(D-494·D-507·D-754·D-759) | P0–P2에서 그대로다. 0.6 m 무장, 슬롯 하나, 15 s 만료, 거절 규칙 모두 같다. 미리보기는 옆에서 관찰만 한다. 지시가 허가다 |
   | D-551 신호 참고 | **따로 둔다(권고).** 신호 색은 초 단위로 바뀌고 ttl 2 s로 자주 가야 하지만 미리보기는 사건이 바뀔 때만 간다. 합치면 미리보기가 신호 때문에 2 Hz가 되거나 신호가 늦는다. D-551은 Accepted이고 구현돼 있다. 미리보기의 `signal` 사건은 `signal_id`만 실어 표시가 둘을 잇는다 |
   | D-511 `context.next` | 그대로다. 바퀴 경로의 차로 유지 사전 정보이고 trip 구간을 모른다. 하나로 합칠지는 동료 질문 5 |
   | D-531 `route_context` | 그대로다. 미리보기를 인식 문맥으로 넘기지 않는다(동료 질문 4) |
   | D-620 교차로 신호 질의 | 그대로다 |
   | D-517·D-760 통행권 | 그대로다. 미리보기 `ttl_s` 상한이 통행권과 같아 미리보기가 통행권보다 오래 "산" 정보가 되지 않는다 |
   | D-550 규칙 M | 그대로다. 미리보기는 움직임을 시작하지 않으므로 규칙 M 평가기(D-760 6)가 세지 않는다 |
   | D-758 현장 기준 | 쓰지 않는다. `pose_stamp`와 odom 경로만 쓴다. D-758 2단계가 착지해도 미리보기의 뜻은 같다 |
   | D-763 작업 종류 | trip 하나의 구간 안에서만 만든다. 작업의 다음 단계(다음 trip)는 싣지 않는다(동료 질문 7) |

9. **행동은 뒤에, 따로, 기본 꺼짐.**
   - **P2 미리 감속.** 미리보기의 다음 사건이 감속이 필요한 종류(`turn` left·right·stop, `bend`, `crosswalk`, `stop`, `signal`)이면 그 지점에서 `v_event(kind)`(설정)가 되도록 일찍 천천히 간다. D-551 9항의 불변식을 그대로 따른다: 차선 결정의 마지막 `min` 클램프 한 번(`decision.linear = min(decision.linear, max(cap, v_floor))`), `v_floor` ≥ 측정한 바퀴 데드밴드(D-500), 같은 `leg_id`의 통행권이 FREE·HOLDING이고 만료 전일 때만(통행권이 꺼진 `hold_back` 로봇은 표시만), D-407 래치를 쓰지 않음, 몸체 정지 0은 0. 설정 `line_follow.preview_slowdown_enabled` 기본 false. 신호 참고의 9항 상한과는 둘 다 `min`이므로 더 낮은 쪽이 이긴다.
   - **P3a 지시의 거리를 미리보기로 다시 잰다.** 교차로·굽이 지시가 닿았을 때, 저장된 미리보기에 같은 `leg_id`·`place_id`·`action`(`bend`면 `turn_deg`)·`map_version`의 사건이 있고 fresh이면, CORE는 지시의 `expect_in_m`·`bend_in_m`(받은 때부터 잼) 대신 미리보기 사건의 odom 지점(`pose_stamp`에서 잼)으로 창과 굽이 시작점을 둔다. 허용치(`expect_tol_m`·`bend_tol_m`)는 지시 값 그대로다. 지시가 허가로 남고, 미리보기는 그 지시의 위치 오차만 줄인다. Fleet의 앞당김(`trip_ports.py:409-415`)은 P3a 능력이 있는 로봇에 0으로 보낸다. 설정 `line_follow.preview_anchor_enabled` 기본 false. Safety-Review.
   - **P3b 끊긴 동안 미리 무장(이 기록이 정하지 않는다).** 링크가 끊긴 동안 미리보기의 `turn`·`bend`를 지시처럼 무장해, 들고 있는 통행권 안에서 기동을 마치게 하는 것. 이것은 참고를 허가로 쓰는 것이라 D-550 2항 표를 고쳐야 한다. 조건 후보: 기동 전체(회전 축 + 전진 + `d_stop`)가 들고 있는 같은 `leg_id` 통행권 안, 미리보기 fresh, 끊긴 뒤 지시가 오면 지시가 이김. 동료 질문 3의 답과 P0–P2 증거를 보고 별도 개정으로 정한다. 그때까지 끊긴 로봇은 지시 없는 장소에서 오늘처럼 선다.

10. **단계.** 앞 단계의 끝난 기준을 넘어야 다음 단계를 한다. Gazebo는 이 노트북이 아니라 `tools/remote/remote_pytest.py --pick sim`이 고른 PC에서, 호스트 시험도 원격(D-584)에서 돈다.

    | 단계 | 무엇 | 끝난 기준 | 검토 | 되돌림 |
    |---|---|---|---|---|
    | P0 | Fleet만: 순수 빌더, `observe`, `/api/fleet/traffic`·trip 읽기에 미리보기, 관제 카드 표시, 예측 대 실제 기록, `preview_mismatch` | 아래 정확도 기준 + `preview_mismatch` 0 | 코드 리뷰 | 설정 `off` |
    | P1 | 계약·CORE 저장소·`GET /line-follow` 노출·능력, Fleet `send` | 호스트: 순서·버림·다시 재기·import-lint·성질 시험(모든 입력에서 통행권·교차로 판정이 미리보기 유무와 같다). Gazebo 2대 30분: 로봇이 다시 잰 `in_m`과 Fleet 예측의 차이가 P0 기준 안, 통행권 전달 p99가 미리보기 전보다 나빠지지 않음 | 코드 리뷰(움직임 없음) | Fleet `observe` |
    | P2 | 미리 감속(9항) | 호스트: D-551 9항 시험 목록 + 사건 종류마다 감속 시작점. Gazebo 2대 30분: 접촉 0, 블록 중복 0, 정체 판정 증가 없음. 장치 2대 10바퀴 | **Safety-Review** | 설정 false |
    | P3a | 지시 거리를 미리보기로(9항) | 호스트: 일치·불일치·낡음·다른 지도. Gazebo: 굽이 시작 오차의 p95가 오늘(앞당김 방식)보다 작음, 교차로 `junction_unexpected` 증가 없음. 장치 2대 10바퀴 | **Safety-Review** | 설정 false, Fleet 앞당김 복귀 |
    | P3b | 끊긴 동안 미리 무장 | 별도 개정(D-550 2항) | 사용자 결정 + Safety-Review | — |

    **P0 정확도 기준(재기 전에 정한다).** Fleet이 trip 주기마다 낸 미리보기의 사건 지점을, 그 사건이 실제로 일어난 때의 Fleet 지도 자세와 비교한다. "일어난 때"는 종류마다: `turn`·`bend`는 CORE 교차로 상태가 `approaching`·`bending`으로 바뀐 때 그 상태가 알린 선 거리, `crosswalk`는 Fleet `at_crosswalk`가 처음 참이 된 때, `authority_end`는 통행권 HOLDING `authority_end`, `stop`은 trip 끝 정지. Gazebo 2대 30분과 장치 2대 10바퀴에서:
    - 예측 때 1 m 안의 사건: 위치 오차 중앙값 ≤ 0.03 m, p95 ≤ 0.08 m(교차로 `expect_tol_min_m` 0.12와 굽이 최소 `bend_tol_m` 0.12보다 작아야 P3a가 뜻이 있다).
    - 1–2 m의 사건: p95 ≤ 0.15 m.
    - 놓침: 실제로 일어난 사건 가운데 직전 미리보기의 `horizon_m` 안에 있었는데 목록에 없던 것 ≤ 1%. 헛사건: 목록에 있었는데 경로 위에서 일어나지 않은 것(재계획·보류로 바뀐 경우 제외) ≤ 1%.
    - 송신: 로봇당 평균 초당 1회 이하.
    - 기준을 못 넘으면 P1을 하지 않는다. 표시는 그때도 P0 그대로 쓸 수 있다.

### Alternatives

| 대안 | 판단 |
|---|---|
| 로봇이 전체 경로(차로 그래프·지도)를 받아 스스로 앞을 계획한다 | 기각(지금). D-760 Alternatives "로봇이 지도·차로 그래프를 갖는다"와 같은 이유: 요구는 몇 초 앞이고, 지도 버전·재계획·블록 표를 로봇과 맞추는 비용이 크다. 로봇에 지도 자세가 없다(D-744·D-759 "CORE는 지도 자세를 갖지 않는다"). Fleet 없는 주행이 요구되면 D-758 2단계 뒤에 다시 본다 |
| 사건 종류마다 따로 민다(횡단보도 참고, 굽이 참고 …) | 기각. 엔드포인트·송신기·전송 자리·능력이 종류만큼 생기고 REST 호출이 그만큼 는다(Context 5). 종류 사이의 순서와 "이 거리 안에는 이것뿐"(`horizon_m`)을 말할 수 없다 |
| 통행권 메시지를 넓힌다(사건 목록을 `LineAuthorityRequest`에) | 기각. 허가와 참고가 한 schema에 섞인다(D-550 원칙, O4). Safety-Review를 받는 schema가 매번 자란다. 통행권이 없는 `hold_back` 현장은 받지 못한다 |
| D-551 신호 참고에 합친다 | 기각(권고). 8항 표 |
| D-511 `context.next`를 목록으로 넓힌다 | 기각. 바퀴 경로(`route: "lap"`)의 차로 유지 사전 정보이고 trip 구간·`leg_id`가 없으며, CORE 차로 유지 결정이 읽는 입력이라 참고만 따로 열 수 없다. 기본 꺼짐이다. 둘을 하나로 줄이는 것은 동료 질문 5 |
| 교차로·굽이 지시에 `pose_stamp`만 더한다 | **부분 후보.** 굽이 2 cm(Context 3)만 고친다면 이것이 더 싸다: 필드 하나, 앞당김 제거. 그러나 다음 다음 사건, 끊긴 동안의 앞, 표시는 고치지 못한다. P3a는 같은 효과를 미리보기로 낸다. 어느 쪽으로 2 cm를 고칠지는 동료 질문 1 |
| 허브 하트비트 답으로 보낸다 | 미룸. 현장은 페어링되지 않았고(D-550 확인 절) 1 Hz다. 페어링 뒤 D-551 5단계와 같이 본다 |

### Consequences

- 관제와 로봇 상태에 "몇 m 앞에서 무엇"이 처음으로 보인다(P0·P1). 움직임은 P2 전까지 바뀌지 않는다.
- trip 로봇마다 POST가 평균 초당 1회 이하로 는다. 통행권 p99를 미리보기 전후로 잰다(D-551 6항과 같은 관찰).
- 지시와 미리보기가 같은 함수에서 나오므로 `preview_mismatch`가 Fleet 계산 결함의 새 감지기가 된다.
- P3a가 열리면 굽이 앞당김 추정(`bend_send_s`)이 그 로봇에 필요 없다. 열리기 전에는 오늘 방식 그대로다.
- 끊긴 동안 로봇은 앞을 "보여" 주지만 그 정보로 움직이지 않는다(P3b 전). 링크가 돌아온 뒤 한 번 서고 가는 것은 그대로다.

### 위험

1. **크기 한도.** Fleet 쪽 새 코드는 지금 자리에 들어가지 않는다. `ledger/trip_runner.py` 901줄(D-766 측정표 898, 지금 판정 751 + 150 = 901로 여유 0), `ledger/trip_ports.py` 600줄(한도 그대로), `fleet/fleet/server/ledger` 단위 여유 0, `fleet/fleet/traffic` 단위 여유 약 1줄이다(`test/architecture/test_module_structure.py:314-315,343-344,497-498`). D-766 7(a)의 ratchet(`test/architecture/size_ratchet.txt`, 아직 없음)이 착지하면 이 값들이 천장이 되고 줄여야만 자란다. 그래서 P0은 (a) 새 크기 단위(예: `fleet/fleet/traffic/preview/`)에 빌더·송신기를 두고, (b) `trip_runner.py`의 배선 몇 줄은 같은 브랜치의 앞 커밋에서 그만큼 줄을 옮긴 뒤에 넣는다(D-766: 커밋마다 녹색, bisect). rosy-fc의 D-763 정리(trip 코드를 `server/trip/`으로 옮길 수 있음)와 순서를 맞춘다(동료 질문 6). CORE 쪽은 `line_follow` 최상위 단위 여유 약 100줄, `line_follow/cue` 약 140줄이라 새 `line_follow/preview/` 단위가 맞다.
2. **미리보기를 허가로 읽는 사람.** 관제에 "0.4 m 뒤 왼쪽"이 보이면 운영자가 로봇이 돌 것으로 믿을 수 있다. 문구는 "예고"이고 지시 상태(`armed` 등)를 옆에 같이 보인다.
3. **지도 오류가 두 번 보인다.** 지도 장소·호 반지름이 틀리면 미리보기와 지시가 같이 틀린다. 미리보기가 새로 만드는 오류는 아니지만 P3a 뒤에는 오늘의 앞당김 추정 대신 지도 거리가 그대로 위치가 된다. P3a 기준이 이것을 잰다.
4. **두 진실.** 원칙 2를 어기고 미리보기 전용 계산이 생기면 지시와 갈라진다. `preview_mismatch` 0을 P0·P1 기준으로 둔다.
5. **Pi 시계.** `pose_stamp`는 CORE 벽시계이고 정확한 표본 찾기(D-758 0)가 벽시계 튐을 막는다. 같은 stamp 둘, 뒤로 간 벽시계는 통행권과 같이 거절된다.

### Open — 동료 세션 질문

rosy-44(line_follow의 교차로·굽이·횡단보도·신호 규제와 Fleet `trip_ports` 담당):

1. 굽이 시작 2 cm(Context 3)를 무엇으로 고칠까: 지시에 `pose_stamp`를 더하기(싸다), P3a(미리보기로 다시 재기), 또는 둘 다? m16/m17 측정 기록이 P0 정확도 기준의 기점으로 쓸 만한가?
2. 사건 지점의 정의(2항 표)가 CORE가 쓰는 점과 같은가: `turn`은 가로선(`expect_in_m − pivot_past_line_m`), `bend`는 호 시작점, `crosswalk`는 지도 구역 입구(D-491의 카메라 구역이 아니라). P2에서 종류마다 `v_event`를 정하려면 `junction/approach.py`의 접근 감속, D-573 횡단보도 게이트의 `slow_from`, D-620 신호 대기와 겹치는 곳이 있는가?
3. P3b(끊긴 동안 들고 있는 통행권 안에서 미리보기의 회전을 무장)를 원하는가, 아니면 지시만 허가로 남기는 지금 선이 맞는가? 원하면 D-550 2항 개정을 같이 쓴다.
4. 미리보기를 D-531 `route_context`(인식 keeper의 거부 문맥)에 넣을 가치가 있는가? 지금 그 문맥은 쥔 지시 하나에서만 온다.
5. D-511 `context.next`와 미리보기가 모두 "다음 지형"을 말한다. trip 중인 로봇에는 `context.next`를 끄고 미리보기 하나로 줄일까?

rosy-fc(D-763 작업 종류, trip 코드를 `server/trip/`으로 옮길 수 있음):

6. `PreviewSender`와 빌더를 어디에 둘까(새 `traffic/preview/` 단위, 또는 옮겨 갈 `server/trip/`)? `trip_runner.py` 배선 몇 줄을 위해 먼저 줄을 옮기는 일과 D-763 이동의 착지 순서를 어떻게 맞출까?
7. 다단계 작업에서 다음 단계의 첫 구간 사건을 미리보기에 실어야 하는가, trip 하나 안에서 끝내는가?
8. D-763 trip 읽기(`work_read`)에 미리보기를 실어 관제가 한 곳에서 읽게 할까?

모두:

9. `H_MAX` 2.0 m와 사건 8개, `ttl_s` 5가 맞는가? 송신 목표 "로봇당 초당 1회 이하"가 D-760 8항의 호출 목표와 맞는가?
10. `protocol/lane_cue.py:7`, `server/lane_compliance_service.py:213`의 `crosswalks[]` 주석(Context 7)을 P0에서 고치는 데 이의가 있는가?
