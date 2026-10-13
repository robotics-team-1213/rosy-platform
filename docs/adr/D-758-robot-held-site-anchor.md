## D-758 로봇이 드는 현장 기준 — Fleet은 로봇마다 지도←odom 짝 하나를 보내고, 로봇은 자기 odom으로 현장 자세를 잇는다

**Status:** Proposed (2026-10-14, 사용자 요청 "Fleet과 로봇이 위치·방향을 주고받는 구조를 군집 제어와 주행까지 생각해 정리". 코드는 없다. 이 기록은 방향·계약 초안·단계이고, 단계마다 따로 착지한다. 1단계 그림자 측정 전에는 어떤 소비자도 이 값을 쓰지 않는다)

잇는 결정: [D-744](D-744-map-anchored-lane-arc.md)(호 하나를 위한 지도 짝, 이 기록이 넓힌다) · [D-581](D-581-trail-follow-ceiling-camera-anchored-odom.md)(Fleet이 리더 표본을 팔로워 odom으로 다시 쓴다, 2단계가 고친다) · [D-559](D-559-leader-trail-follow-path-replay.md) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3(Fleet MapPose) · [D-752](D-752-canonical-world-map-pose-consumers.md) · [D-550](D-550-fleet-robot-communication-contract.md)(종류·만료·규칙 M) · [D-20](D-20-swarm-fleet.md)·[D-21](D-21-.md)·[D-31](D-31-fleet.md)(폐루프는 로봇, peer 소스 거부 — 그대로) · [D-395](D-395-fleet-assisted-localization.md)·[D-546](D-546-recovery-manoeuvre-signals-and-fleet-pose-request.md)(AMCL 자세 주입 — 그대로, 별도 경로) · [D-463](D-463-fleet-lane-route.md)·[D-511](D-511-fleet-lane-compliance-watch-and-correction-cue.md)·[D-517](D-517-multi-robot-lane-traffic.md)(차로·교통은 Fleet — 그대로) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)·[D-400](D-400-core-safety-policy-off-shadow-enforce.md)·[D-430](D-430-safety-as-a-separate-concern.md). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

2026-10-14 코드와 ADR을 읽은 결과다.

1. **같은 사실이 기능마다 다른 모양으로 간다.** 현장 로봇은 모터 모드라 지도 자세가 없다. 지도 위 위치는 천장 카메라를 가진 Fleet만 안다(`rosy.world.state.projections.map_pose`: 로봇 r의 `T_r = map ← odom`). 그래서 Fleet이 기능마다 지도 계산을 대신하고 결과를 보낸다.

   | 기능 | Fleet이 보내는 것 | 로봇이 하는 것 |
   |---|---|---|
   | D-744 호 | 지도 원 + 지도 자세 + `odom_stamp_s` | 그 시각의 자기 odom을 찾아 map→odom을 **한 번** 만들고 버린다 |
   | D-581 자취 | 리더 표본을 팔로워마다 그 팔로워 odom으로 다시 쓴 것(10 Hz) | 받은 점을 자취에 넣는다. 변환은 갖지 않는다 |
   | D-511 차로 신호 | 차로 대비 상태·돌 각도 + `pose_stamp` | odom 기록에서 `pose_stamp`의 yaw를 찾아 다시 잰다 |
   | D-517 통행권 | `until_m` + `pose_stamp` | `pose_stamp` 뒤 주행 거리로 다시 잰다 |

   넷 다 "로봇의 odom 시각 하나에 지도 값 하나를 묶는다"는 같은 일이고, 넷 다 만료·odom 끊김·튐 처리를 따로 가진다.
2. **D-744가 이미 필요한 계산을 한다.** `AuthorityMixin._place_map_anchor`가 시각으로 odom 표본을 찾고, 나이 2 s·같은 epoch·이월 1.5 m 한도 안에서 변환을 만든다. 단 "그 변환을 다른 판단에 쓰지 않는다"로 막아 두었고, 「방향」 (a) "CORE에 지도 자세를 준다"를 다른 ADR로 미뤘다. 이 기록이 그 ADR이다.
3. **D-581은 현장 경로와 시뮬레이션 경로가 다르다.** Gazebo는 AMCL `map` 프레임 자취(D-559)로 통과했다. 현장은 `anchor: fleet` 경로를 타는데, 이 경로는 호스트 단위·운동학 시험뿐이다. Fleet은 리더 표본마다 팔로워 수만큼 변환을 계산하고, 두 로봇 odom을 2 Hz로 다시 읽고, 리더 스트림 odom과 추적기 odom이 같은 프레임인지 따로 검사한다(`leader_odom_mismatch`).
4. **D-581이 기각한 대안은 이 기록과 다르다.** (a) "팔로워 CORE가 T를 받아 스스로 변환한다 — 팔로워가 리더 T까지 알아야 한다": 리더가 자기 기준으로 현장 자세를 내보내면 팔로워는 자기 T만 있으면 된다. (b) "로봇에 천장 pose를 넣는다 — 천장 지연 150 ms+와 2 Hz odom이 20 Hz 조향 루프에 들어간다": 자세가 아니라 **짝**을 보내면 로봇은 자기 odom(센서 주기)으로 잇고, 천장 지연은 짝의 나이일 뿐 루프에 들어가지 않는다. (c) "다듬기·멈춤 판정이 로봇마다 흩어진다": 맞는 지적이다. 그래서 다듬기는 Fleet에 둔다(Decision 3).
5. **로봇 쪽 사실.**
   - `pose`는 map TF가 있으면 map, 2 s 없으면 odom이다(`ros_bridge.py`, `odom_owns_pose`). 스냅숏 `Pose`에는 프레임 필드가 없고 `localization.pose_frame`으로만 나간다.
   - `odom_pose.stamp`는 CORE가 odom을 받은 벽시계다. 시각이 붙은 odom 기록은 차선 추종 관리자 안에만 있다(`line_follow/authority.py`, 200개).
   - 스냅숏에 odom 세대 번호가 없다. bringup이 재시작해 odom이 0으로 돌아가면 Fleet은 속도 한도 위반으로만 알아챈다.
   - 자취 추종은 CommandManager NAVIGATION 슬롯에 20 Hz로 `(v, ω)`를 쓴다. offset 추종과 `navigation/goal`은 Nav2 `NavigateToPose`라 모터 모드에서 돌지 않는다.
   - 모터 모드는 `swarm.follow/lead`를 코드에서 끈다(`core_common/domain/capabilities.py`). D-581은 모터 모드 현장을 전제하는데, 현장 로봇이 그 능력을 어떻게 얻는지는 이번에 찾지 못했다(Open 1).
   - CORE에는 차로 그래프도 현장 지도도 없다.

### Decision

**원칙.** Fleet은 로봇이 **어디 있는지**를 알려 주고, 그것으로 **무엇을 할지**는 기능 계약이 정한다. 로봇이 스스로 계산할 수 있는 것은 로봇이 계산한다. 지도 지식(차로, 통행 순서, 경로)이 필요한 계산은 Fleet에 남는다.

1. **현장 기준(site anchor) 하나.** Fleet은 로봇마다 그 로봇의 기준 짝만 보낸다.

   | 필드 | 뜻 |
   |---|---|
   | `map_pose {x, y, yaw}` | `odom_stamp_s` 시각에 로봇이 있던 현장 지도 자세 |
   | `odom_stamp_s` | Fleet이 스냅숏 `odom_pose.stamp`에서 읽어 그대로 돌려주는 CORE 시각(D-550 4) |
   | `map_id`, `map_version` | 천장 카메라 현장 지도 |
   | `anchor_epoch` | 기준이 이어지는 동안 같은 값. 재지역화·odom 재시작·지도 교체에서 바뀐다 |
   | `seq`, `fleet_epoch`, `ttl_s`(≤ 5) | D-550 4의 순서·만료. `ttl_s`는 CORE 단조 시계 |
   | `source` | `sighting` \| `operator_pin`(D-593) |

   - 짝으로 보낸다(변환 행렬이 아니다). 로봇은 자기 odom 기록에서 그 시각의 표본을 찾아 변환을 만든다(D-744와 같은 계산). 기록에 그 시각이 없거나 odom 세대가 다르면 거절한다. 시계는 로봇 자신의 것만 비교한다.
   - **종류는 허가다**(D-550 2). 만료하면 현장 자세는 "없음"이고 그것을 쓰던 움직임은 선다. 그래서 REST로만 보낸다(`PUT /api/v1/localization/site-anchor`, 계획 행). 허브 하트비트 답에 싣지 않는다.
   - 능력 플래그 `rosy.controls/1` `site_anchor` 뒤에 둔다. Fleet은 플래그가 없는 로봇에 보내지 않는다.
   - Fleet은 MapPose가 LOCALIZED일 때만 보낸다. DEGRADED·UNKNOWN이면 보내지 않고 만료에 맡긴다. 주기는 trip 루프의 odom 갱신과 같은 2 Hz에서 시작한다(Open 3).

2. **로봇은 현장 자세(site pose)를 따로 든다.** `site_pose = T ∘ odom`을 odom이 올 때마다 계산한다.
   - 스냅숏에 `site_pose {x, y, yaw, map_id, anchor_epoch, anchor_age_s}`를 **새 필드로** 더한다. `pose`를 덮어쓰지 않는다. AMCL이 있는 로봇의 `pose`(로봇 맵)와 현장 자세(현장 지도)는 다른 출처로 남는다(D-395 2026-10-10 개정과 같은 줄).
   - TF `map → odom`을 내보내지 않고, AMCL·`initialpose`에 넣지 않고, Nav2에 주지 않는다. D-463 5·D-494 3의 "로봇 AMCL에 들어가지 않는다"는 그대로다.
   - **안전 정지에 들어가지 않는다.** 바닥 IR, D-422 몸체 정지, 스트림 단절 HOLD, E-stop은 이 값을 읽지 않는다. 이 값은 조향 목표를 놓는 데만 쓴다.
   - 쓰는 기능은 이름으로 연다(아래 4·5). 열지 않은 기능은 이 값을 보지 못한다.
   - 선행: 시각 붙은 odom 기록을 차선 추종 관리자에서 StateManager로 옮겨 같이 쓴다. 스냅숏 `odom_pose`에 `epoch`(odom이 끊기거나 0으로 돌아가면 증가)를 더한다. 이 둘은 D-581·D-744에도 그대로 이득이라 0단계로 먼저 한다.

3. **다듬기와 튐 판정은 Fleet에 둔다.** D-581 3의 규칙(1차 필터 시상수 1 s, 로봇 위치 기준 초당 0.05 m·5° 한도, 0.20 m·15° 넘으면 재지역화)을 `fleet/swarm/anchor.py`에서 꺼내 기준 송신기가 쓴다. 로봇은 받은 짝을 그대로 쓴다.
   - 재지역화면 Fleet은 `anchor_epoch`를 바꾼다. 로봇에서 epoch가 바뀌면 그 전에 쌓은 현장 좌표 값(자취, 놓아 둔 호)은 이어 쓰지 않는다: 쓰던 기능은 자기 사유로 선다.
   - 그래서 로봇 쪽 새 판정은 셋뿐이다: 만료, epoch 바뀜, odom 시각 못 찾음.

4. **군집 제어.**

   | 항목 | 지금 | 이 기록 뒤 |
   |---|---|---|
   | 리더 스트림 | 모터 모드면 `frame: odom` | 현장 기준이 살아 있으면 `frame: site` + 현장 `map_id` (추가 값). 없으면 지금과 같다 |
   | Fleet 릴레이 | TRAIL이면 팔로워마다 다시 쓴다(D-581) | 바이트 그대로(D-31 원래 규칙) |
   | 팔로워 자취 | Fleet이 자기 odom으로 옮겨 준 점 | `site` 표본을 받는 순간 자기 T로 odom에 옮겨 자취에 넣는다. 자취는 지금처럼 odom에 박힌다 |
   | 팔로워 N대 | Fleet이 표본마다 N번 변환 | 각자 한 번 |
   | 리더 승계(D-20) | 새 리더 기준으로 Fleet이 다시 계산 | 새 리더가 자기 현장 자세를 내보낸다. 팔로워는 달라지는 것이 없다 |
   | 기준이 잠깐 없음 | 리더 프레임마다 `anchor_hold` 정지 표본 | 팔로워는 자기 기준 만료로 선다(`site_pose_expired`). 리더 기준이 없으면 리더가 `frame: odom`으로 떨어지고 팔로워는 `reference_frame_changed` |

   - 폐루프는 지금처럼 팔로워 CORE에 있다(D-20). peer 소스는 여전히 거부한다(D-21·D-31): 스트림은 Fleet 릴레이를 지나고, Fleet이 죽으면 `stream_timeout_ms` 1 s 안에 선다. **Fleet 없는 군집은 이 기록의 목표가 아니다.**
   - 한 자취에 프레임을 섞지 않는 규칙(D-581 4)은 `site`에도 같다.
   - **모터 모드 offset 대형(LINE·V·GRID)은 열리지 않는다.** offset은 Nav2 목표라서다. 현장 자세가 있으면 "리더 자취를 옆으로 밀어 놓은 길"을 같은 pure pursuit로 따라가는 슬롯 추종을 만들 수 있지만, 새 제어기라 다른 ADR이다.
   - 대형 전체 정지(FOR-004), 가장 느린 로봇에 맞추기, 슬롯 배정(FOR-002)은 Fleet 그대로다.

5. **주행.**

   | 기능 | 바뀌나 | 이유 |
   |---|---|---|
   | D-744 호의 지도 짝 | 3단계에서 든 기준을 쓴다 | 같은 계산이다. 기준이 없는 로봇은 지금의 한 번짜리 짝을 그대로 쓴다 |
   | D-511 차로 신호, D-607 방향 비교 | 아니오 | 차로 그래프가 Fleet에만 있다. `pose_stamp` 방식 그대로 |
   | D-517 통행권·교통, D-463·D-489 경로 | 아니오 | 순서·간격·경로는 Fleet이 정한다 |
   | D-494 교차로 지시 | 아니오 | |
   | trip `free` 구간, `navigation/goal` | 아니오 | Nav2가 있어야 한다. 모터 모드에서 Fleet이 준 짧은 길(D-463의 다음 점들)을 현장 자세로 따라가는 주행은 자취 추종과 같은 제어기를 쓸 수 있으나 다른 ADR이다 |
   | D-395·D-546 위치 결정 | 아니오 | AMCL 로봇의 자세 주입과 스캔 검증은 그대로다. 현장 기준은 AMCL을 고치지 않는다 |

   주행에서 지금 바뀌는 것은 호 하나다. 나머지는 "로봇이 지도를 갖지 않는다"가 유지되는 동안 Fleet 계산이 맞다.

6. **규칙 M과 인증.** 현장 기준을 쓰는 움직임은 `ttl_s`(≤ 5 s)로 한도가 있다. 기준 `PUT`은 Fleet 전용 토큰만 받는다(D-541 trip lease 주인 규칙과 같은 방식). D-581 6의 "operator 토큰이면 누구나 넣을 수 있다"를 이 경로에는 두지 않는다(Open 2).

7. **단계.** 앞 단계가 증거를 내야 다음 단계를 한다. D-581의 현장 수용은 이 기록을 기다리지 않는다.

   | 단계 | 무엇 | 끝난 기준 | 되돌림 |
   |---|---|---|---|
   | 0 | 스냅숏 `odom_pose.epoch`, odom 기록을 StateManager로 | Fleet 추적기가 epoch로 기준을 버린다. 기존 D-744·D-517·D-511 시험 그대로 통과 | 필드 무시 |
   | 1 | 계약 + CORE가 현장 자세를 들고 스냅숏에 낸다. **쓰는 기능 없음**. Fleet이 로봇 `site_pose`와 자기 MapPose의 차이를 기록 | 실제 로봇 두 대, 주행 10분: 차이의 최대·RMS, 만료 횟수, 거절 사유 분포. 수치 기준은 측정 뒤 이 ADR 개정으로 정한다 | 플래그 끔 |
   | 2 | 자취가 `frame: site`를 받는다. Fleet은 능력 플래그로 대형마다 경로를 고른다 | 원격 Gazebo 2대 + 장치: D-581 경로와 같은 시나리오에서 편차 비교. **Safety-Review**(swarm 관리자·`core/drive/docking.py`) | 대형을 D-581 경로로 |
   | 3 | D-744 호가 든 기준을 쓴다. D-581 다시 쓰기 제거 | 2단계 현장 수용 뒤 | 한 번짜리 짝 |
   | 뒤 | 모터 모드 슬롯 추종, Fleet 길 따라가기 | 다른 ADR | — |

### Alternatives

| 대안 | 판단 |
|---|---|
| 지금대로(기능마다 Fleet이 계산) | 로봇이 2대이고 Fleet이 늘 있으면 동작한다. 기각하는 이유는 기능이 늘 때마다 만료·튐·odom 끊김 처리를 또 만들고, 현장 경로가 시뮬레이션에서 본 경로와 달라지기 때문이다. 1단계 측정이 나쁘면 이 대안으로 남는다 |
| 지도 자세 스트림을 로봇에 민다 | D-581 대안과 같다. 천장 지연과 전송 주기가 조향 루프에 들어간다. 짝이면 들어가지 않는다 |
| CORE가 `map → odom` TF를 내고 AMCL 없이 Nav2를 돌린다 | offset 대형과 `navigation/goal`이 한 번에 열린다. 기각(지금): 모터 모드에 Nav2를 올리는 비용, Nav2가 천장 기준을 AMCL처럼 믿게 되는 것, D-463 5·D-494 3을 뒤집는 것. 모터 모드 자유 주행이 필요해지면 다시 본다 |
| 로봇에서 천장 관측과 odom을 EKF로 합친다 | D-395가 범위 밖으로 둔 것. 다듬기가 로봇마다 흩어진다(D-581의 지적) |
| 로봇끼리 직접(peer) | D-21 재검토 조건(20대 이상, Fleet 지연 200 ms 초과, Fleet 없는 군집 요구)이 아직 없다 |
| 차로 그래프를 로봇에 내려 로봇이 차로 신호를 계산 | 지도 배포·버전 맞춤이 새로 생긴다. 현장 자세가 검증된 뒤의 일이다 |

### Consequences

- Fleet→로봇의 "위치" 계약이 하나가 된다. 새 기능은 현장 자세를 읽고, 만료·epoch·odom 끊김을 다시 만들지 않는다.
- 자취 따라가기의 현장 경로가 릴레이 바이트 중계 + 팔로워 변환으로 돌아가 D-559 구조와 같아진다. Fleet의 표본별 다시 쓰기, 2 Hz 교차 odom 읽기, `leader_odom_mismatch` 검사가 없어진다.
- 로봇이 처음으로 현장 지도 좌표를 든다. 잘못 쓰이면 위험하므로 안전 정지에서 떼어 두고, 쓰는 기능을 이름으로 열고, 2단계에 Safety-Review를 건다.
- 천장 카메라가 로봇을 놓치면 5 s 안에 그 로봇의 현장 자세가 사라지고 그것을 쓰던 움직임이 선다. 지금 D-581과 같은 한도다. 마커가 자주 사라지는 로봇(rosy_41)은 여전히 불안하다.
- Fleet이 죽으면 기준도 스트림도 끊긴다. 군집은 지금과 같은 시간 안에 선다.
- 주행은 호 하나만 바뀐다. 차로 신호·통행권·경로는 그대로 Fleet 계산이다.
- 단계가 끝날 때까지 D-581 경로와 새 경로가 같이 있다.

### Open

1. 모터 모드 로봇의 `swarm.follow/lead`: 코드는 끄고 D-581은 켜진 것을 전제한다. 현장 프로필이 어떻게 여는지 확인한다(0단계 전에).
2. 기준을 보내는 주체의 인증: Fleet 전용 토큰을 어떻게 묶는가(D-541 방식 재사용 여부).
3. 송신 주기와 `ttl_s`: 2 Hz·5 s에서 시작하되 1단계 측정으로 정한다. 로봇 odom 기록 길이(200개)가 짝의 나이를 덮는지 본다.
4. AMCL이 있는 로봇(하드웨어 모드)에서 `site` 프레임과 로봇 `map`이 같은 지도일 때 어느 쪽을 리더 스트림에 싣는가. 지금 제안은 AMCL `map`이 있으면 그것을 쓰고 `site`는 그림자로만 둔다.
5. Pi에 RTC가 없어 CORE 벽시계가 튈 수 있다. odom 기록 조회를 단조 시계 기준으로 바꿀지 0단계에서 정한다.
