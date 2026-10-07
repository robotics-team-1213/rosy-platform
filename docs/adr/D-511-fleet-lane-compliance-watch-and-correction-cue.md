## D-511 Fleet은 Rosy Cam 지도 자세로 움직이는 모든 로봇의 차로 준수를 지켜보고, 벗어나면 주행을 끊지 않고 알리며 모드별로 보정을 지시한다 — 1차 방어는 로봇의 바닥 IR이다

**Status:** Accepted (2026-10-07, 사용자 수락: "수락, M0 시작"). 구현·SIM·DEVICE·FIELD 수용은 열려 있다. M2의 CORE 가장자리 신호는 구현 브랜치에서 Safety-Review를 받는다.

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
- M1에서 고칠 M0 판정 공백(리뷰 2026-10-08): (1) 일방 차로를 뒤로 가는 로봇(후진 복구)이 45° 방향 기준 때문에 UNKNOWN이 된다. 방향은 차로 선과 mod π로 비교하고, 양방향 차로에서만 진행 방향으로 동률을 가른다. (2) 45° 넘게 꺾여 벗어나는 로봇이 UNKNOWN이 되어 ACT 누적이 끊긴다. (3) 굽은 모서리 바깥으로 넘친 로봇이 앞 호의 끝과 다음 호의 시작 사이에 놓여 UNKNOWN이 된다(차선 추종이 넘치는 바로 그 자리). M0은 관측만 하므로 수용하지만 M2 신호 전에 반드시 닫는다.
