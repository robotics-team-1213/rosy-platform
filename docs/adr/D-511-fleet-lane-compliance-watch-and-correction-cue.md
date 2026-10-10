## D-511 Fleet은 Rosy Cam 지도 자세로 움직이는 모든 로봇의 차로 준수를 지켜보고, 벗어나면 주행을 끊지 않고 알리며 모드별로 보정을 지시한다 — 1차 방어는 로봇의 바닥 IR이다

**Status:** Accepted (2026-10-07, 사용자 수락: "수락, M0 시작"). 개정 1(2026-10-10, 사용자 지시): Fleet 복귀 고리. 구현·SIM·DEVICE·FIELD 수용은 열려 있다. M2의 CORE 가장자리 신호는 구현 브랜치에서 Safety-Review를 받는다.

사용자 지시(2026-10-07): "rosy cam 으로 봐서 차선 준수했는지 체크하는 기능 넣어서 fleet에서 확인해서 하는게 더 맞겠는데? 우리가 차선 준수여부를 fleet에서 판단하고 있다가 이게 너무 넘어가면 이를 이야기해서 수정하게 하는게 좋겠는데?"

사용자 결정(같은 날): "보통은 우리가 ir 센서로 해서 넘지 않도록 하는게 우선이긴 한데 이런경우엔 우리가 주행에 방해가 되지 않도록 이를 알리고 보정을 지시하는게 fleet에선 맞을 것 같아. 모드를 생각해서 더 나눠서 해볼래". 선행 연결은 "D-497 지도 + sighting 연결부터"를 골랐다.

잇는 결정: [D-344](D-344-pilot-assisted-autonomy.md) §12(IR 가드) · [D-491](D-491-ir-guard-crosswalk-zone.md)(횡단보도 IR) · [D-422](D-422-line-follow-body-referenced-obstacle-stop.md)/D-424(몸체 기준) · [D-463](D-463-fleet-lane-route.md)(차로 경로) · [D-488](D-488-fleet-site-map-address-routes.md)(현장 지도) · [D-494](D-494-fleet-trip-execution-m2-contracts.md)(지도 자세, trip 루프) · [D-497](D-497-camera-lane-map-draft.md)(카메라 차선 지도 초안) · [D-493](D-493-fleet-console-map-first-layout.md)(예외 큐) · [D-507](D-507-lane-trip-leg-structure-and-site-floor.md)(차선 trip 구간) · [D-508](D-508-control-near-robot-video-as-numbers.md)(제어 고리 위치) · D-2(CORE만 최종 `/cmd_vel`) · D-430(안전 검토).

### Context

1. 2026-10-07 8kcn(`rosy_60`) 녹화 주행(`tools/capture/edge_drive.py drive`, CORE `CAMERA_LINE`을 Fleet trip 없이 직접 사용)에서 규칙 기반 추종이 흰 테이프 자체를 따라가 안쪽 차선 선 위로 올라탔다(녹화 `20261007T143038Z_rosy_60`, `20261007T143211Z_rosy_60`). IR 가드는 기본 꺼짐이었고 Fleet은 아무것도 몰랐다.
2. Fleet이 차로 이탈을 보는 곳은 trip 루프 하나다. 지도 자세가 호의 `width_m/2`를 넘으면 trip을 멈춘다(`operations/fleet/fleet/server/trip_runner.py` `_locate`). `/route`(D-463)는 `OFF_M = 0.08`, `meet/place.py`도 0.08을 쓴다. 기준이 셋이고 모두 몸체 폭이 아닌 중심점 기준이다.
3. 그 시각 `GET /api/fleet/robots/rosy_60/map-pose`는 `UNKNOWN`(`map_id: null`, sighting 0)이었다. 지도 자세에는 활성 현장 지도, 그 `map_id`와 같은 sighting 소스(로봇 표식·보정 revision), 로봇 odom이 모두 있어야 한다(`map_pose.py`, `sightings.py`, `sightings_config.py`). trip이 아닌 로봇은 1 Hz hub heartbeat만 받는다.
4. CORE가 밖에서 받는 입력 가운데 `CAMERA_LINE` 주행을 차로 가운데로 되돌리는 것은 없다. 있는 것은 모드 전환, 다음 교차로 지시(D-494 §4), 열린 stuck 사건의 결정, teleop이다. D-476 `set_bridge_route_hint`는 내부 함수이고 공개 API가 없다. 자유 주행/Nav2에는 D-463 경로 다음 점이 이미 보정 역할을 한다.
5. CORE `line_follow`의 IR 가드는 `lane_edge_left/right`에서 반대쪽으로 제한된 각속도(`ir_guard_turn` × `speed_scale`)를 더하고, `centre`에서는 `lane_departure`로 HOLD한다(`middleware/core/services/core_features/line_follow/manager.py`). 밖에서 온 가장자리 신호를 같은 가지로 넣으면 새 제어기 없이 보정할 수 있다.

### Decision

#### 1. 책임 순서

- **1차: 로봇의 바닥 IR(D-344 §12, D-491).** 선을 밟기 전에 로봇이 스스로 비킨다. 이 ADR은 IR 가드 기본값을 바꾸지 않는다.
- **2차: Fleet의 차로 준수 감시(이 ADR).** Rosy Cam 지도 자세로 늦게라도 전체를 본다. 주행을 끊지 않는 것이 기본이다. 알리고, 보정을 지시하고, 정지는 마지막 수단이다.
- Fleet은 제어 고리를 닫지 않는다(D-508, D-2). Fleet이 teleop이나 속도를 보내는 방식은 쓰지 않는다.

#### 2. 차로 준수 판정 하나

- 새 순수 모듈 `operations/fleet/fleet/localization/lane_compliance.py`가 (지도 자세, 활성 지도의 차로 그래프, `core_common.robot_body`)에서 **부호 있는 가로 편차**(호 접선 기준 왼쪽 +), **몸체 여유** `margin = width_m/2 − (|d| + body_half_width)`, 수준 `OK|WARN|ACT|UNKNOWN`을 낸다.
- 수준:
  - `WARN`: `margin < warn_margin_m`가 연속 `persist_n`회.
  - `ACT`: `margin < 0`(몸체가 차로 가장자리를 넘음)이 연속 `persist_n`회.
  - `UNKNOWN`: 지도 자세가 `LOCALIZED`가 아니거나 차로에 투영되지 않음. UNKNOWN은 이탈이 아니다(D-82 Law 0).
- 임계값은 현장 설정 `fleet.lane_compliance`에 둔다. 초기값은 SIM/현장 측정 후 정한다. 숫자를 코드에 박지 않는다(사용자 규칙: URDF 공칭 + 보정).
- trip 루프의 `_locate` 정지, `/route` `OFF_M`, `meet/place.py`가 이 판정을 쓰도록 맞춘다. 기준은 하나다.
- 감시 대상은 trip 여부와 관계없이 **움직이는 모든 로봇**이다(odom 변화가 있는 로봇). 감시 중에는 trip과 같은 `refresh`로 자세를 2 Hz 이상 읽는다. D-494 §3의 "arbitrated_pose는 trip 전용"을 이 감시로 넓힌다.

#### 3. 모드별 동작

| 모드 (누가 움직이나) | WARN | ACT | 정지 |
|---|---|---|---|
| MANUAL, Pilot teleop (사람) | 콘솔 예외 항목. CORE에 가장자리 신호 → Pilot HUD에 표시 | 콘솔 CRIT. HUD 경고 | 하지 않는다. 사람이 고리를 쥐고 있다 |
| `CAMERA_LINE` 직접(녹화 도구 등) | 콘솔 항목. 가장자리 신호(보정) | 가장자리 신호 유지 + 콘솔 CRIT | `ACT`가 `act_timeout_s` 넘게 이어지고 IR 가드가 꺼져 있거나 증거가 없을 때만 line-follow OFF(HOLD) |
| Fleet trip, 차선 구간 | 콘솔 + trip `detail`. 가장자리 신호 | 가장자리 신호 유지 | 지금의 trip 정지 규칙을 2항 판정으로 바꿔 유지(`ACT` + `act_timeout_s`) |
| Fleet trip 자유 구간, `/route`, Nav2 | 콘솔 항목 | D-463 다음 경로 점을 다시 보낸다(있는 경로) | 지금의 `ROUTE_OFF_LANE` 정지를 2항 판정으로 |

- IR 가드가 켜져 있고 증거가 신선하면 Fleet 정지는 하지 않는다. IR이 이미 판단하고 있다.
- 녹화 도구(`tools/capture/edge_drive.py`)는 CORE line-follow 상태에서 가장자리 신호와 수준을 읽어 로그에 남긴다. Fleet에 직접 붙지 않는다.

#### 4. 보정 지시 채널: CORE 가장자리 신호(lane cue)

- **새 CORE 입력**(이름·필드는 구현 때 API Ref에 고정): Fleet이 `{side: left|right, margin_m, expires_s ≤ 1.0}`를 보낸다. 운영자 권한이고 D-494 §4 교차로 API와 같은 좌석 규칙을 따른다.
- CORE는 이 신호를 IR `lane_edge_*`와 **같은 가지**로 처리한다. 반대쪽으로 `ir_guard_turn` × `speed_scale` 이하의 각속도를 더한다. 만료되면 즉시 사라진다.
- 신호는 **움직임을 만들지 않는다.** `CAMERA_LINE`이 이미 주행 중일 때만 조향에 더해진다. MANUAL에서는 조향에 쓰지 않고 상태(`line_follow`·robot state)에 실어 Pilot HUD가 보여 준다.
- IR이 반대 결론(`lane_edge` 반대쪽, `centre`)을 내면 IR이 이긴다.
- 결정→움직임 입력이므로 구현 브랜치는 D-430 `Safety-Review:` 를 받는다. API Ref 버전을 올린다(D-18).

#### 5. 선행 연결 (사용자 선택: D-497 지도 + sighting부터)

1. D-497 카메라 차선 지도 초안을 현장 지도로 들여와 활성화한다(`PUT /site-map/draft` → activate). 그 `map_id`를 기록한다.
2. 현장 sighting 설정(사이트 로컬 YAML, 저장소에 넣지 않음)에 Rosy Cam 소스를 두고 `robot_ids`, `map_id`(1의 것), `calibration_revision`, `robot_markers`를 채운다. 로봇 표식을 붙인다.
3. 로봇을 세워 둔 채 `GET /api/fleet/robots/{id}/map-pose`가 `LOCALIZED`가 되는지 본다. 이것이 감시의 입력 조건이다.

#### 6. 단계

- **M0:** 5항 연결 + 판정 모듈 + 콘솔 예외 항목(로봇 API 변경 없음). 녹화 주행을 다시 할 때 Fleet이 이탈을 보는지 확인한다.
- **M1:** 기준 하나로 합치기(trip·`/route`·`meet`), 감시 대상 확대(움직이는 모든 로봇).
- **M2:** CORE 가장자리 신호 API + Pilot HUD 표시 + 녹화 도구 로그. Safety-Review, SIM(Gazebo, 모델 PC), DEVICE.

### Consequences

- trip 밖의 주행도 Fleet이 차로 준수를 기록하고 알린다. 녹화 데이터에 "차로 안에서 찍힌 프레임" 표시를 붙일 수 있다.
- Rosy Cam 자세 지연(lease·전송 약 1 s 이내)이 있어 보정은 늦다. 그래서 IR이 1차이고, Fleet 보정은 IR이 꺼졌거나 놓친 경우의 2차다.
- 기준을 몸체 가장자리로 바꾸면 지금 trip이 통과하던 자세 일부가 WARN/ACT가 된다. SIM에서 다시 잰다.
- 새 CORE 입력은 안전 검토 대상이고, 만료·권한·IR 우선 규칙이 테스트로 고정되어야 한다.

### Open

- `warn_margin_m`, `persist_n`, `act_timeout_s` 초기값(현장 측정).
- 로봇 표식 방식과 Rosy Cam 인식 품질(현 아레나 조명).
- Pilot HUD 표시 문구(D-505 문구 규칙과 맞춘다).
- M1에서 고칠 M0 판정 공백(리뷰 2026-10-08): (1) 일방 차로를 뒤로 가는 로봇(후진 복구)이 45° 방향 기준 때문에 UNKNOWN이 된다. 방향은 차로 선과 mod π로 비교하고, 양방향 차로에서만 진행 방향으로 동률을 가른다. (2) 45° 넘게 꺾여 벗어나는 로봇이 UNKNOWN이 되어 ACT 누적이 끊긴다. (3) 굽은 모서리 바깥으로 넘친 로봇이 앞 호의 끝과 다음 호의 시작 사이에 놓여 UNKNOWN이 된다(차선 추종이 넘치는 바로 그 자리). (4) D-472 LED 확인 트랙에 아직 이동 방향이 없으면(`heading_source: none`) 방향 문 없이 가장 가까운 호를 쓴다. 그래서 어떤 차로에서 차로 폭 한 개 안에서 제자리 회전하는 로봇이 UNKNOWN이 아니라 ACT로 읽힐 수 있다. M0은 관측만 하므로 수용하지만 M2 신호 전에 반드시 닫는다.

### 개정 1 — 차로·지도 밖, 역주행을 Fleet이 알리고 되돌린다 (2026-10-10, feat/fleet-lane-return · feat/core-fleet-lane-cue)

사용자 지시(2026-10-10): "우리가 위치가 완전히 우리 맵에서 벗어날 경우 이를 fleet에서 이야기를 하고 그 다음 다시 돌아오게 해야 하고, 방향도 그렇고 이런 것들에 대한 부분을 우리가 알아서 해야지." 같은 날 "횡단보도에선 멈춘 다음 넘어가는 걸로 되어 있어", "너가 직접 ROSY CAM을 보면 알잖아".

1. **판정(Fleet, 순수 모듈 `lane_compliance.py` `classify`·`ReturnTracker`).** 입력은 M0과 같은 자세(지도 자세 `LOCALIZED`·`DEGRADED`, 없으면 D-472 LED 트랙)와 활성 현장 지도다.
   - `OFF_MAP`: 차로 전체의 외접 사각형을 `off_map_pad_m`(0.15 m) 넓힌 밖이거나, 움직이는 로봇을 `off_map_unseen_s`(3 s) 동안 놓을 수 없을 때.
   - 가장 가까운 차로 중심선까지 거리 `d`, URDF 몸 반폭 `b`(D-424), 테이프 반폭 `line_half_width_m`(0.0125 m, 칠한 선 실측)로 `ON_LANE`(`d + b ≤ w/2 − t`), `ON_LINE`(몸이 테이프에 걸침), `OFF_LANE`(그 밖).
   - 횡단보도 다각형 안은 `ON_LANE`이다. 건너는 중을 이탈로 세지 않는다(D-573).
   - `WRONG_WAY`: 몸 아래 모든 차로가 마지막 5 cm 이동 방향과 `180 − heading_gate_deg`(135°) 넘게 어긋날 때. 교차로에서는 90° 안의 차로가 늘 몸 아래에 있으므로 회전은 역주행이 아니다. 제자리 회전은 이동이 없어 역주행을 새로 만들지 않는다. 방향은 이동으로만 본다(D-587 표식 방향은 되돌릴 각도 `turn_deg`에만 쓴다).
   - 깜빡임 방지: 새 상태가 `return_persist_s`(1 s) 이어져야 바뀐다. `WRONG_WAY`는 그동안 `wrong_way_min_m`(0.10 m) 이상 움직여야 한다.
   - 결과는 `lane_compliance.return`에 싣는다: 상태, 차로 가운데가 로봇의 어느 쪽인지(`side`), 재진입점(차로를 따라 `entry_ahead_m` 앞) 방위, 차로 방향, `turn_deg`, 횡단보도 구역 `crosswalk_ahead {id, near_m, far_m, uncertainty_m, source: fleet_map, pose_age_s}`(base_footprint에서 차로를 따라 잰 가까운·먼 끝, 안이면 near < 0, `crosswalk_ahead_m` 0.6 m 안, 불확실성 `crosswalk_uncertainty_m` 0.035 m = D-587 보정 잔차 p90 0.018 m + 표식 높이 오차 최대 0.019 m).
2. **로봇에 알림.** `return_cue`(기본 켬)이면 `ON_LANE`이 아니거나 횡단보도가 앞에 있는 틱마다 Fleet이 `POST /api/v1/line-follow/lane-cue`(`ttl_s` 1.0)를 보낸다. 되돌아오면 `ON_LANE`을 한 번 보낸다. 그 경로가 없는 CORE는 404이고 60 s 뒤에 다시 묻는다. 4항의 "가장자리 신호"를 이 신호로 구체화한다.
3. **CORE(`fleet_lane_cue_enabled`, 기본 false, Pinky true).** CAMERA_LINE이 이미 달리는 틱에서, 앞 물체·IR 낡음·IR 가운데 정지를 지난 뒤에만 읽는다. 움직임을 시작하지 않는다.
   - `ON_LINE`·`OFF_LANE`: IR이 선을 못 볼 때(또는 꺼짐) `side`를 IR 가장자리 가지로 넣는다(4항 그대로). IR이 본 쪽이 이긴다.
   - `OFF_LANE`이고 재진입점이 45° 넘게 옆: 그쪽으로 제자리 회전한 다음 차로 유지가 이어 간다.
   - `WRONG_WAY`: `turn_deg`가 30° 안이 될 때까지 제자리 회전한다. 차로 0.185 m, 몸 회전 반지름 0.088 m(URDF)라 차로 안에서 돈다. 각도가 없으면 HOLD `fleet_wrong_way`.
   - `OFF_MAP`: HOLD `fleet_off_map`. 콘솔이 CRIT으로 알리고 사람이 판단한다(D-577 AI PC 제안 경로는 그 브랜치가 잇는다).
   - `crosswalk_ahead`: `pose_age_s` 전의 odom 자세에 `fleet_map` 구역 하나를 D-491 구역 목록에 넣는다(같은 id는 새 것으로 바꾼다). D-491 IR 쉼과 D-573 서고-보고-건너기가 카메라 구역과 같은 목록에서 이 구역을 쓴다. 카메라 구역이 흔들려도 건넌다.
   - IR, 몸 기준 정지, D-573 게이트, D-517 권한이 모두 이긴다. 결정→움직임 입력이므로 D-430 Safety-Review 대상이다.
4. **Fleet 막힘 해결(D-573 개정).** `lane_lost`·`no_motion` 막힘이고 로봇이 지도의 횡단보도 위이거나 앞 막대가 0.15 m 안이면 Fleet은 WAIT 대신 RESUME 한 번(규칙 `XW`)을 보낸다. 이미 `stuck_report_s` 동안 서 있었으므로 보기(`crosswalk_look_s`)는 지났고, CORE가 RESUME을 다시 검사하고 D-573 게이트가 다시 본다. 두 번째 막힘은 사람에게 간다(`restuck_after_resume`).
5. **콘솔.** 로봇 예외 한 줄: `차로 밖 — 차로로 복귀 지시`, `지도 밖 — 정지·확인 필요`, `역주행 — 돌아서기 지시`, `차선 위 — 안쪽으로 보정`(+ 왼쪽/오른쪽).
6. **녹화 검증(2026-10-10, Fleet D-594 경로, 현장 지도 v5).** p7은 `OFF_LANE` 91표본(truth.py 89 off와 같은 구간), p10은 7.7–133 s `OFF_LANE`(오른쪽 고리 안쪽)이다. p8은 오른쪽 고리를 시계 방향으로 돌아 10 s부터 `WRONG_WAY`이고, p10은 147–185 s `WRONG_WAY` 뒤 반시계로 돌아서 `ON_LANE`이다. 지도 v5의 방향(모든 고리 반시계, 위에서 본 오른손 좌표, 천장 영상이 거울상이 아님을 확인)을 기준으로 한 결과다. 현장 주행 방향이 지도와 반대라는 D-587 기록(2026-10-10)과 충돌하므로 **어느 쪽이 맞는지 사용자가 정한다.** 지도가 틀렸다면 고칠 곳은 지도 방향 하나다.

**열린 것.** Safety-Review(CORE 3항), SIM, DEVICE(두 Pinky), `off_map_pad_m`·`return_persist_s` 현장 값, 4항의 M1 판정 공백 가운데 (3)(굽은 모서리 바깥)은 `classify`가 끝점 투영을 허용해 닫았다.

### 개정 2 — 늘 주는 경로 안내(사전 정보), 지도 방향, 횡단보도 경로 정리 (2026-10-10)

사용자 지시(2026-10-10): "drivable이 잘못된 곳에 그려진다. 이게 이렇게 교착 상태나 이러면 바로 fleet으로 해서 판단하고 우리가 길을 잡아 주는 걸로 해야 할 것 같아. 우리가 조향 방향이나 기타를 기본적으로 어느 정도 알게 하는 게 좋을 것 같아. fleet에서 미리 알려 준다고 봐도 좋을 것 같아. 횡단보도나 기타 예상되는 방향에 대해서 미리 안내를 하는 것과도 같아."

1. **안내는 사전 정보다.** 움직임 명령이 아니고 CORE가 최종이다(D-2). 로봇이 움직이는 동안 2 Hz로 `lane-cue`를 보낸다(`ttl_s` 1.0). 새 필드 `guide {ahead_m (0.4), heading_ahead_deg, curvature_1pm, to_end_m, next_place_id, ring}`은 앞 0.4 m 차로 모양과 다음 장소까지의 거리다. 교차로 행동(좌·우·직진)은 trip이 있을 때 D-494 교차로 지시가 그대로 맡는다.
2. **자세 품질 문.** 안내는 `LOCALIZED`이고 sighting anchor가 `guide_anchor_max_s`(1.5 s) 안일 때만 낸다(D-587 위치 ±2–4 cm, 방향 ±3–5°, 지연 0.4–0.8 s; 위치 세션 2026-10-10). `DEGRADED`나 낡은 자세는 "지금 판단 안 함"이고 `OFF_MAP`이 아니다. 신호를 보내지 않으므로 CORE에서 1 s 뒤 사라지고 로봇은 지금처럼 달린다.
3. **역주행 방향은 D-587 표식 방향이 먼저다.** 방향이 있으면 그것으로 판정하고 이동 거리 조건 없이 1 s 뒤 바뀐다. 방향이 없을 때만 5 cm 이동 방향과 `wrong_way_min_m`을 쓴다.
4. **횡단보도 구역은 lane-cue로 보내지 않는다.** D-573에 따라 Fleet 지도 구역은 D-517 권한의 `crosswalks[]`(현장 지도 `rosy.site_map/1` 모양 `{id, polygon, approach, lanes, revision}`)로만 CORE의 구역 목록 하나에 들어간다(소유: D-573 브랜치). 개정 1의 `crosswalk_ahead`는 Fleet 판정과 콘솔에만 남는다. 개정 1 3항의 CORE 쪽 `fleet_map` 구역 저장은 하지 않는다.
5. **막힘 응답(D-577)은 해결기 소유 세션이 정한다.** 개정 1 4항의 `XW` 규칙은 main에 있고, 그 파일의 소유 세션이 옮기거나 바꾼다.

### 개정 3 — CORE lane-cue D-430 검토 반영 (2026-10-10, feat/core-fleet-lane-cue)

독립 Safety-Review는 REJECT였다. 고친 내용은 다음과 같다(재검토 대기, `fleet_lane_cue_enabled`는 계속 false).

1. 신호 판단은 IR 감시 뒤, 몸 정지(D-422) 앞에 둔다. 제자리 회전이면 의도 twist를 `(0, w)`로 두어 회전 원으로 잰다. 회전은 LOST 래치, D-364 NOMINAL 지면, 카메라 신선(FOLLOW) 조건을 모두 지난 뒤에만 낸다.
2. 회전은 `pose_stamp` 시점 odom yaw + 각도를 목표로 CORE가 odom으로 잰다. 10° 안이면 끝이다. 예산 |각도|+30°, 시간 |각도|/속도+2 s를 넘으면 래치 HOLD `fleet_turn_unconfirmed`. 같은 부호 2회·0.5 s 뒤에만 시작하고, 교차로 지시·arc·횡단보도 구역 중엔 시작하지 않는다.
3. OFF_MAP과 회전 중 신호 만료(`fleet_cue_lost`)는 래치 HOLD다(fail-closed). 같은 epoch의 ON_LANE/ON_LINE 신호, D-407 막힘 결정, 모드 변경만 푼다.
4. Fleet 현장 등록 토큰(D-555 3 자리)만 보낼 수 있다. `(fleet_epoch, seq)`는 만료와 무관하게 유지하고, `pose_stamp`가 1.5 s 넘게 오래되면 거절한다. 사건 `nav.lane_cue`.
5. 옆 신호는 |offset| ≥ 0.05 m가 같은 쪽 2회일 때만 쓰고 후진하지 않는다. **차로 밖 로봇을 선을 넘어 차로 안으로 들이는 것은 이 신호가 아니라 D-468 복귀의 몫이다.** 이 신호는 쪽을 알려 주고, 선 위에서는 IR이 이긴다.
6. Fleet은 403·404·500·501을 "받을 수 없는 로봇"으로 보고 60 s 동안 보내지 않는다.
