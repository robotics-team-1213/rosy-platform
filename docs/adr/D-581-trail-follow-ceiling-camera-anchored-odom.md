## D-581 천장 카메라 기준 자취 따라가기 — Fleet이 리더를 팔로워의 odom 좌표로 옮겨 보내고, 팔로워는 자기 odom에서 자취를 다시 달린다

**Status:** Proposed (2026-10-10, 사용자 결정 "천장 카메라 기준". 구현은 feat/trail-fleet-anchored-frame, 호스트 단위 시험과 운동학 시험(참값 최대 편차 0.035–0.037 m, RMS 0.016–0.019 m)만이다. Gazebo SIM·DEVICE·현장 수용은 하지 않았다. 독립 리뷰 REQUEST CHANGES(H1–H3, M1–M6, L1–L5)를 같은 브랜치에서 반영)

잇는 결정: [D-559](D-559-leader-trail-follow-path-replay.md)(리더 자취 따라가기, 이 기록이 고친다) · [D-31](D-31-fleet.md)(릴레이는 바이트를 바꾸지 않는다, 이 기록이 고친다) · [D-494](D-494-fleet-trip-execution-m2-contracts.md) 3(Fleet map pose: 천장 sighting 기준, odom 다리) · [D-395](D-395-fleet-assisted-localization.md) · [D-562](D-562-ceiling-marker-id-equals-robot-number.md)(로봇 마커 id = 로봇 번호) · [D-575](D-575-ceiling-marker-seen-is-shown.md)(작은 마커 다시 읽기) · [D-550](D-550-fleet-robot-communication-contract.md)(규칙 M) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md) · [D-400](D-400-core-safety-policy-off-shadow-enforce.md). 폴더 구조는 바뀌지 않으므로 D-427 3항은 해당하지 않는다.

### Context

1. D-559 trail은 리더 표본의 `frame`이 `map`이고 팔로워 자신의 pose도 `map`일 때만 달린다. 그 전제는 두 로봇이 같은 맵에서 맞는 자기 위치(AMCL)를 갖는 것이다. Gazebo SIM은 AMCL로 통과했다.
2. 2026-10-09 23:45 현장의 rosy_40(8kcn)과 rosy_41(9dfk)은 모터 모드다. Nav2·AMCL이 없고 `map_id`는 없으며 보고 pose는 odom 원점 근처다. 리더 스트림은 `frame: odom`이고 팔로워 자신도 odom이라, trail은 `reference_frame_not_map`·`own_pose_not_map`으로 영원히 선다.
3. 현장에는 천장 카메라(Rosy Cam, Vision)가 있다. 마커로 로봇의 사이트 map pose를 낸다(`/api/fleet/tracking`: rosy_40은 MARKER, rosy_41의 41번 마커는 자주 놓친다). Fleet은 이미 그 sighting을 각 로봇 odom과 짝지어 map pose를 만든다(D-494 3 `map_pose.py`: 촬영 시각의 odom에 맞춰 기준을 잡고, 그 사이는 odom이 잇는다. LOCALIZED·DEGRADED·UNKNOWN).
4. 자취 재생에 필요한 것은 두 로봇이 **서로** 맞는 것이다. 팔로워가 자기 odom으로 달리면, 리더가 지난 점을 팔로워 odom으로 옮기기만 하면 된다. 그 변환은 Fleet만 계산할 수 있다(두 로봇의 천장 기준을 다 아는 곳).

### Decision

1. **Fleet이 TRAIL 대형에서만 참조 스트림을 만든다.** 리더의 `/ws/swarm/pose` 표본이 `frame: odom`이면 Fleet은 팔로워마다 그 표본을 그 팔로워의 odom 좌표로 다시 쓴다(`fleet/swarm/anchor.py`):
   `리더(팔로워 odom) = T_f⁻¹ · T_L · 리더 odom`, `T_r = map ← odom`(로봇 r의 D-494 3 추적기 기준: 천장 sighting과 촬영 시각 odom의 짝).
   보내는 표본은 `frame: odom`, `anchor: fleet`, `for_robot_id: <그 팔로워>`, `map_id`(천장 카메라 사이트 맵), `anchor_age_s`(두 기준 중 오래된 쪽)를 더한다. 주기는 리더 스트림 그대로(≥10 Hz)이고, 천장 기준 사이는 리더 odom이 잇는다. 기준을 쓰는 동안 Fleet은 두 로봇의 odom을 2 Hz로 다시 읽는다(trip 루프와 같은 `refresh(force_rest)`).
   - **D-31을 고친다.** 릴레이는 이 경우에만 바이트를 바꾼다. 이유: 두 로봇의 천장 기준을 아는 곳이 Fleet뿐이고, 변환을 로봇으로 보내면 팔로워가 리더의 T까지 받아 섞어야 한다(계약이 더 커진다). 리더가 `map`(또는 `frame` 없음)으로 보내는 프레임은 지금처럼 바이트 그대로다 — 로봇이 스스로 위치를 아는 경우는 D-559 그대로다.
   - **합성은 하되 반복은 하지 않는다**(D-31 원칙 유지). 리더 프레임 하나에 표본 하나다. 리더가 멈추면(프레임이 없으면) 아무것도 보내지 않고, 팔로워는 `stream_timeout_ms`로 선다(규칙 M의 한도 그대로, Fleet 대형은 `members`가 있으므로 D-559 4항대로 승계·follow 끝).
   - **기준이 없으면 침묵이 아니라 정지 표본이다**(리뷰 M3). 침묵은 로봇에서 "리더가 죽었다"로 읽혀 D-20 승계로 대형이 끝난다. 기준만 없는 것은 리더 상실이 아니므로, Fleet은 리더 프레임마다 그 팔로워에게 `anchor_hold: "<robot>:<이유>"`를 단 표본을 보낸다(좌표는 리더 odom 그대로이고 자취에 들어가지 않는다). 팔로워는 `anchor_withheld`로 서고 스트림은 산다. 기준이 돌아오면 이어 가되, 정지 표본마다 D-559 건너뜀 한도의 시계를 다시 시작하므로 긴 정지 사이 리더가 0.3 m 넘게 갔으면 직선으로 잇지 않고 `trail_lost`다. 리더가 정말 죽으면 리더 프레임이 없으므로 여전히 침묵이고 승계다.
   - **멈추는 이유를 보인다.** `GET /api/fleet/formation`의 `anchor.followers[팔로워]`가 `<robot>:no_map_pose|anchor_stale|map_pose_degraded|anchor_jump|map_id_differs|leader_odom_mismatch` 또는 null(쓸 수 있는 표본을 보내는 중)이고, 같은 이유가 `stream_evidence[팔로워].anchor_hold`에 붙는다 — 프레임은 흐르지만 팔로워는 서 있다.
   - **odom이 바뀌면 T를 버린다**(리뷰 H1). 추적기가 odom 끊김·급변(CORE·드라이버 재시작)으로 기준을 버리면(UNKNOWN, 또는 추적기 odom epoch 증가) 다듬은 T도 버리고, 새 odom에서 LOCALIZED가 될 때까지 멈춘다. DEGRADED 동결은 T를 만든 그 천장 기준(captured_at)이 그대로일 때만이다. 리더 스트림 odom이 추적기의 최신 odom에서 0.5 m/s × (그 odom의 나이) + 0.10 m보다 멀면 두 odom이 다른 프레임이므로 멈춘다(`leader_odom_mismatch`).
2. **어느 기준을 쓰나.** LOCALIZED만 T를 고친다. 천장 기준이 5 s보다 오래되면 멈춘다(0.15 m/s로 0.75 m, 바퀴 odom 어긋남 1–2 cm). DEGRADED(어긋난 sighting 뒤, 또는 확인 안 된 첫 기준)는 마지막 LOCALIZED 갱신 뒤 2 s까지 T를 얼린 채 보낸다 — 5 Hz 일관 sighting 두 개면 0.4 s에 돌아오고, 2 s odom 다리는 1 cm 아래다. 처음부터 DEGRADED이거나 2 s를 넘으면 멈춘다.
3. **T는 튀지 않는다.** 로봇마다 다듬은 T를 두고, 추적기의 새 T 쪽으로 1차 필터(시상수 1 s)로 옮기되 초당 0.05 m·5°를 넘지 않는다. 차이와 보정은 **로봇 위치에서** 잰다 — odom 원점이 5 m 떨어져 있으면 원점 기준 1° 회전은 로봇을 9 cm 옮긴다. 로봇 위치에서 0.20 m 또는 15°를 넘는 차이는 어긋남이 아니라 재지역화다: 그 로봇에 걸린 표본을 멈추고(자취를 순간 이동시키지 않는다) 경고 로그를 남긴다. 그 멈춤은 릴레이가 다시 열릴 때(reform 뒤 resume)까지 유지된다. 0.20 m는 D-559 `trail_lost` 0.30 m 아래, sighting 잡음과 몇 초 odom 어긋남 위다. 보정 걸음은 debug 로그, 잔차는 상태 `anchor.robots[*].residual_m|residual_deg`에 있다.
4. **CORE는 자기 몫의 odom 표본만 받는다.** trail 팔로워는 `anchor == "fleet"` **이고** `for_robot_id`가 자기 id **이고** `frame == "odom"` **이고** follow `source`가 `fleet`일 때만 그 표본을 자취에 넣는다. 그때 자기 위치는 상태 스냅샷의 `odom_pose`(같은 odom, 0.5 s 넘게 낡으면 `own_pose_stale`)이고 `own_pose_not_map` 판정은 하지 않는다. `anchor`가 있는데 조건이 맞지 않으면 `reference_anchor_invalid`로 선다. `anchor` 없는 리더 odom 표본은 지금처럼 `reference_frame_not_map`이다.
   - **한 자취에 프레임을 섞지 않는다.** 자취는 처음 쌓인 종류(map 또는 fleet)로 정해진다. 다른 종류 표본이 오면 `reference_frame_changed`로 서고 follow를 다시 걸 때까지 유지한다.
   - **map_id.** Fleet 기준 표본의 `map_id`는 천장 카메라 사이트 맵이고 자취는 로봇 odom에 있으므로, 로봇 자신의 `map_id`와 비교하지 않는다(로봇 맵 비교는 `anchor` 없는 표본에만 그대로). 두 로봇의 기준이 같은 사이트 맵인지는 Fleet이 본다(추적기는 활성 사이트 맵 sighting만 쓰고, 두 기준의 `map_id`가 다르면 `map_id_differs`로 멈춘다).
5. **안전은 그대로다.** D-422 몸체 정지, 스트림 단절 HOLD, SAF-004 클리핑·세션 `max_speed`, D-400 평가는 D-559와 같은 길이다. 새 HOLD 사유 세 개(`reference_anchor_invalid`, `reference_frame_changed`, `anchor_withheld`)는 `swarm.hold`로 한 번 알린다.
6. **`anchor`·`for_robot_id`는 길 찾기 검사이지 인증이 아니다**(리뷰 M4). `/ws/swarm/reference`는 operator 토큰이면 누구나 프레임을 넣을 수 있고, `anchor: fleet` 표본도 그렇다 — 지금 map 프레임 trail과 같은 신뢰 수준이다. 두 필드는 Fleet이 팔로워 A의 표본을 B에 잘못 보낸 것을 거르는 것이다. 후속 후보: 참조 프레임을 무장한 토큰에 묶는다(D-541 trip 임대와 같은 방식).
7. **API v1.176**(추가): §7.8 `anchor`·`for_robot_id`·`anchor_age_s`·`anchor_hold`, `swarm.hold` 사유 `reference_anchor_invalid`·`reference_frame_changed`·`anchor_withheld`, `swarm/state` `trail.anchor`, Fleet `formation.anchor`, `stream_evidence[*].anchor_hold`.

### Consequences

- 모터 모드 현장에서 AMCL 없이 trail이 달린다. 정확도는 "두 로봇이 천장 카메라 기준으로 서로 맞는 정도"다. 자취 점은 팔로워 odom에 박히므로, 팔로워가 그 점에 닿기까지(간격 0.5 m, 몇 초)의 odom 어긋남만 오차에 들어간다.
- 운동학 시험(두 로봇 odom 원점·방향 다름, 바퀴 odom 오차 ±3 %·±1 %, 천장 5 Hz·잡음 1 cm/1°·지연 150 ms, odom 2 Hz, Wi-Fi 50 ms, S자 2.9 m): 팔로워 참값 경로의 리더 참값 경로 최대 편차 0.035–0.037 m, RMS 0.016–0.019 m(시드 3개), 보낸 표본 335, 멈춘 표본 0, 끝 간격 0.49–0.51 m. 같은 시간 리더 odom 자체는 0.064 m 어긋났다 — 기준 없이 odom만으로는 이 어긋남이 그대로 자취에 들어간다.
- Fleet이 표본을 만들므로 Fleet 지연·중단이 곧 추종 중단이다(로봇이 스스로 위치를 알 때는 Fleet이 바이트만 옮긴다). 이 모드의 신선도 한도는 `stream_timeout_ms`(기본 1 s)와 위의 5 s·2 s다. CORE 자기 odom의 나이는 단조 시계로 잰다(벽시계가 chrony로 뒤로 가도 낡은 odom이 신선해 보이지 않는다, 리뷰 H2).
- 기준이 오래 없으면 대형은 RUNNING인 채 팔로워만 `anchor_withheld`로 서 있다. 운영자는 `anchor.followers`·`stream_evidence.anchor_hold`로 본다.
- 마커가 자주 사라지는 로봇은 trail을 자주 멈춘다. 9dfk(41번)는 스티커를 50 mm 이상으로 바꾸기 전에는 팔로워로도 리더로도 불안하다. 리더는 마커가 안정된 rosy_40을 권한다.

### Alternatives

- **팔로워 CORE가 T를 받아 스스로 변환한다.** 팔로워가 리더 T까지 알아야 하고 계약이 커진다. 다듬기·멈춤 판정이 로봇마다 흩어진다.
- **로봇에 천장 pose를 넣어 map pose를 만든다(D-395 결정 경로).** 모터 모드에는 map pose를 받을 위치 추정기가 없고, 그 길은 D-395 장치 항목으로 남아 있다.
- **Fleet이 각 로봇 map pose를 그대로 리더 표본(`frame: map`)으로 보낸다.** 팔로워도 자기 map pose가 있어야 하는데 모터 모드에는 없다. 팔로워 위치를 Fleet map pose로 주면 천장 지연(150 ms+)과 2 Hz odom이 20 Hz 조향 루프에 바로 들어간다.
- **T를 다듬지 않는다.** sighting마다 T가 1–2 cm·1–2° 튀고, 그 튐이 자취 꺾임이 된다.

### 열린 항목

1. **Gazebo SIM.** AMCL 없이 Gazebo 참값을 잡음·지연을 붙여 가짜 천장 sighting으로 Fleet에 넣는 SIM은 하지 않았다(이 브랜치에서 시간 안에 못 했다). D-559 증거 스크립트(`docs/validation/d559-trail-follow-sim-2026-10-09/`)를 이 모드로 바꾸는 것이 다음이다.
2. **현장 수용 점검표.** (a) 릴리스: CORE(두 로봇)·Fleet 모두 이 브랜치 포함. (b) 9dfk 마커 50 mm 이상, 리더 rosy_40. (c) 로봇마다 Fleet 명단(`robots.yaml`)의 `robot_id`와 CORE `identity.robot_id`가 같다 — 다르면 `for_robot_id`가 맞지 않아 팔로워는 `reference_anchor_invalid`로 선다. (d) 로봇–사이트 PC 시계 차이를 재서 0.1 s 이하임을 기록한다(`chronyc tracking` 또는 REST 왕복). 첫 지표는 팔로워 참값(천장 카메라 녹화)과 리더 경로의 편차, `anchor.followers` 멈춤 횟수, `residual_m` 분포다.
3. **천장 지연과 시계.** sighting과 odom의 짝은 로봇·사이트 시계가 0.1 s 안에 맞는다는 전제다(chrony, D-494 3). 어긋나면 회전 중 T가 틀어진다. 현장에서 잰 적이 없다. Fleet이 REST 왕복으로 로봇별 시계 차이를 추정해 0.1 s를 넘으면 `clock_skew`로 멈추는 것(리뷰 M5)은 상태 스냅샷에 로봇 시각 읽기가 없어 이번에 하지 않았다 — 그때까지는 2(d) 측정이 조건이다.
4. **Wi-Fi 지연과 스트림 끊김.** 리더 프레임이 1 s 넘게 끊기면 follow를 끝낸다(D-559 4항). 재무장은 운영자다.
5. 장치 수용(DEVICE)과 Safety-Review는 착지 전에 받는다. 이 기록은 `body_stop.py`·`command/manager.py`를 고치지 않는다.
