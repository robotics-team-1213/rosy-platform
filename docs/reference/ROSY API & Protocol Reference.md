# ROSY API & Protocol Reference
## 공유 인터페이스 계약서

**Document ID:** ROSY-API-REF-001
**Version:** v1.112
**Status:** Approved
**대상 독자:** rosy_core 개발자, rosy_fleet 개발자, 외부 SDK·AI·연동 시스템

> **거버넌스:** 본 문서는 로봇(rosy_core)과 Fleet(rosy_fleet)이 **공유하는 유일한 인터페이스 계약**이다.
> 본 문서의 변경은 양측 합의 + 문서 버전 업을 통해서만 가능하며(일방 변경 금지), 구현은 본 문서에 명시된 스키마를 임의로 확장하지 않는다.
> 구현 시 본 문서를 OpenAPI(YAML)로 기계 판독 가능하게 유지하는 것을 원칙으로 한다(계약 테스트의 원천).

**관련 문서:** ROSY-CORE-SRS-001 / ROSY-FLEET-SRS-001 / ROSY-ADR-001 / ROSY-PLN-001

---

# 1. 버저닝 및 폐기 정책

### D-468 추가 차선 경계 증거 (v1.106)

내부 `line/observation`의 CAMERA_LINE 증거는 optional `containment`를 포함할 수 있다.
원본 영상 `stamp`와 1us 이내로 일치하는 `stamp`, `geometry_id`,
`ground_source`(NOMINAL/CALIBRATED/GAZEBO), optional `uncertainty_m`와
`boundaries`(0~2개)를 보낸다. 각 경계는 `side`(left/right), `slope`,
`intercept_m`, 실제 관측 구간 `observed_x_min_m`/`observed_x_max_m`를 갖는다.
좌표는 base footprint 기준 x 전방/y 좌측, 직선 y=slope*x+intercept_m이다.
CALIBRATED는 실제 승인된 calibration이 있을 때만 사용한다. unknown uncertainty는
null이며 임의의 안전 여유로 대체하지 않는다. 누락/단일 경계로 전체 차체 containment를
증명할 수 없고 관측 구간 밖으로 무제한 외삽하지 않는다. 명령 필드는 없다.
기존 관측 메시지와 공개 mode/route는 보존한다. 이 계약의 추가는 자동 복구 활성화나
장치/현장 수용을 뜻하지 않는다.

### API-001 경로 버저닝

모든 REST API는 버전을 포함한다.

```text
/api/v1/...
```

Breaking Change 발생 시 `/api/v2/...`로 분리한다.

### API-002 변경 분류

| 분류 | 예 | 정책 |
|---|---|---|
| Additive | 신규 엔드포인트, 응답에 신규 선택 필드 추가 | 버전 유지, 버전 노트 기록 |
| Breaking | 필드 제거/이름 변경, 의미 변경, 필수화 | 신규 major 버전 |
| Corrective | 문서가 틀리게 적혀 있던 것을 구현과 맞춤 (payload 키명, 심각도, 발신자) | 버전 유지, 버전 노트에 **양쪽 값을 모두** 기록 |

소비자는 알 수 없는 응답 필드를 무시해야 한다(Must Ignore 원칙).

Corrective 는 Additive 의 종류가 아니다. 문서대로 짜놓은 소비자는 이미 깨져 있었고, 정정은
그것을 알려 주는 것이다 — 그래서 어느 쪽으로 고쳤는지(문서를 고쳤는지 코드를 고쳤는지)와
틀리게 적혀 있던 값이 무엇이었는지를 모두 적는다. 버전 노트에 `A(≠B)` 로 쓴 것이 그것이다.

### API-003 폐기(Deprecation) 정책

- 폐기 예정 엔드포인트는 응답 헤더 `Deprecation: true` + `Sunset: <date>`와 버전 노트로 사전 공지한다.
- 폐기까지 최소 **2개 마이너 릴리스 또는 6개월** 유지한다.
- Fleet은 로봇 `api_versions`(Capability)를 확인하여 버전별 호출 경로를 선택할 수 있어야 한다.

> **상태 (v1.16)**: `Deprecation`/`Sunset` 헤더는 아직 구현되지 않았다 — 폐기 대상이
> 생기는 첫 시점에 구현과 함께 유효해진다. 현재 폐기 예정 엔드포인트는 없다.

### API-004 원천 일관성

본 문서와 구현 OpenAPI 간 불일치 발견 시 본 문서를 우선하고, 수정은 합의 후 양측에 동시 반영한다. 계약 테스트(Implementation Plan §테스트)가 불일치를 회귀 차단한다.

---

# 2. 인증 및 권한

### AUTH-101 토큰

- `Authorization: Bearer <token>` (REST). 쿠키는 쓰지 않는다.
- WebSocket: 연결 뒤 첫 메시지 `{"type": "auth", "token": "<token>"}` (v1.19). 2 s 안에 오지 않거나 틀리면 4401.
  첫 메시지를 기다리는 소켓은 출발지 호스트마다 4 개, 전체 64 개까지이고(2 s 안에 첫 메시지), 넘으면 수락 전에 닫는다(Starlette는 수락 전 close를 HTTP 403으로 보낸다). 열린 소켓은 30 s 마다 토큰을 다시 보고,
  회수·로그아웃·만료됐으면 4401 로 닫는다.
  `?token=<token>` 쿼리도 한 릴리스 동안 받는다(v1.19 기준 폐기 예정 — URL 은 프록시·기록에 남는다).
- 토큰은 sha256 다이제스트로만 저장한다. 레코드에는 `source`(`card` \| `manual` \| `pair-physical` \| `pair-admin` \| `legacy`)와
  `expires_at`(없으면 만료 없음)이 있다. 만료된 토큰은 401 이고, 다음 저장 때 목록에서 지워진다(D-193).
- 장치 기본값에는 토큰이 없다. 장치 모드(`ROSY_DEPLOYMENT=device`)의 CORE 는 평문 레거시 항목과 공용 개발 토큰
  `rosy-dev-*` 를 어디서 오든 거부하고 `auth.credentials_refused` 를 낸다. 토큰이 0 개여도 API 는 뜨고 모든 인증 요청은 401 이다.
- 로그인 코드(D-193): 로봇 화면·콘솔의 8자 일회용 코드를 `POST /api/v1/auth/pair` 로 이 브라우저 전용 만료 토큰으로 바꾼다(§5.1).
- Fleet 접속용 로봇 토큰은 사용자 토큰과 분리한다(페어링, §7).

### AUTH-102 권한

| Role | 조회 | 제어 | 관리 |
|---|---|---|---|
| Viewer | 상태·맵·센서·이벤트 | — | — |
| Operator | 조회 | Navigation·Teleop·Stop·Mission | — |
| Administrator | 조회 | 제어 | 설정·ROS·네트워크·Robot ID·Update·페어링·토큰 |

예외: `POST /api/v1/safety/stop`은 모든 Role 허용(E-Stop은 누구나).

**토큰 capability (v1.72, D-395 P2-5).** 역할 위에 이름 붙은 쓰기 권한을 둔다. 경로는 "operator 이상" 대신 필요한 capability 를 말한다. 지금은 역할에서 정해진다(`core_api_web.api.grants`).

| capability | 뜻 | Viewer | Operator | Administrator |
|---|---|---|---|---|
| `NAVIGATE` | 사람이 로봇 위치·목표를 정한다 (`localization/initialpose`, `source: human` 결정) | — | ✓ | ✓ |
| `LOCALIZE_ASSIST` | Fleet 위치 확정 서비스가 후보를 읽고 결정·의심을 보낸다 (§5.3, §7.9) | — | ✓ | ✓ |
| `STUCK_DECIDE` | 열린 막힘에 답한다 (`POST /line-follow/stuck/decision`, D-438, v1.91). 역할 `stuck_resolver`(순위 viewer, 이 권한만 가짐)는 Fleet 판단기 전용이다. `stuck_resolver` 가 `MANUAL` 을 고르면 403 `FORBIDDEN` "MANUAL is a human decision (D-438)" 이고 막힘은 열려 있다 | — | ✓ | ✓ |

Fleet 의 로봇 토큰은 operator 토큰이다(`robots.yaml` 의 `token`, 또는 operator 가 아니면 거부하는 D-361 등록). 그래서 `LOCALIZE_ASSIST` 를 가진다. 없으면 403 `FORBIDDEN`, `detail: {capability}`.

### AUTH-103 브라우저 직접 접속 없음 — CORS 미제공 (v1.16 additive)

이 API 는 CORS 헤더를 제공하지 않는다. 소비자는 ① 로봇 로컬 대시보드(동일
출신 정적 자산), ② 서버 간 클라이언트(Fleet·Games), ③ 브라우저라면 자기
출신에서 프록시 하는 웹 앱만 해당한다. 브라우저가 로봇 API 를 직접 fetch
하는 구성은 계약 밖이며 `same-origin` 정책에서 조용히 실패한다.

---

# 3. 에러 응답 표준

### ERR-101 형식

```json
{
  "error": {
    "code": "CAPABILITY_NOT_SUPPORTED",
    "message": "docking is not supported on this robot",
    "detail": { "capability": "docking" }
  }
}
```

### ERR-102 에러 코드 카탈로그

| code | HTTP | 의미 | 발신 |
|---|---|---|---|
| `VALIDATION_ERROR` | 400 | 요청 스키마 위반 | 로봇/Fleet |
| `ROBOT_MUST_BE_STOPPED` | 409 | staged 주행 정책 적용 전에 IDLE/EMERGENCY, 0 속도, line-follow OFF 조건이 충족되지 않음 | 로봇 |
| `UNAUTHORIZED` | 401 | 토큰 없음/무효 | 로봇/Fleet |
| `FORBIDDEN` | 403 | 권한 부족 | 로봇/Fleet |
| `NOT_FOUND` | 404 | 리소스 없음 | 로봇/Fleet |
| `MODE_CONFLICT` | 409 | 현재 모드에서 수행 불가 (예: MANUAL 중 NAV goal) | 로봇 |
| `EMERGENCY_ACTIVE` | 409 | E-Stop 활성 상태 | 로봇 |
| `NAVIGATION_ACTIVE` | 409 | 이미 진행 중 (재정의 필요 시 cancel 먼저) | 로봇 |
| `WAYPOINT_EXISTS` | 409 | Waypoint 이름 충돌 | 로봇/Fleet |
| `CAPABILITY_NOT_SUPPORTED` | 501 | 로봇이 미지원하는 기능 (CAP-003) | 로봇 |
| `CAPABILITY_WITHHELD` | 409 | 로봇이 지원하지만 현재 런타임이 보류한 기능. `detail: {capability, reason}`의 이유는 `GET /system/capabilities`의 `withheld.reasons`와 같다. 미지원 판정(501)이 우선한다 | 로봇 |
| `MAP_MISMATCH` | 409 | Goal의 map_id 불일치 (MAP-002) | 로봇 |
| `MAPPING_ACTIVE` | 409 | 매핑 세션 중 명령 거부 (NAV-005) | 로봇 |
| `DOCKING_ACTIVE` | 409 | 도킹/언도킹이 주행을 쥐고 있다 (DNC-003, §8.1 DOCKING > NAVIGATION) | 로봇 |
| `NOT_LOCALIZED` | 409 | D-395 로봇이 `LOCALIZED` 가 아니거나 `pose_frame` 이 `odom` 이어서(Fleet 신뢰 규칙과 같다) 자율 주행 시작을 거부함: `navigation/goal`·`home`(`/do` 포함), `line-follow/mode`(OFF 제외), `docking/dock`, `swarm/follow`. 검사와 시작은 `LOCALIZED` 이탈 정지와 같은 잠금 안에서 순서가 정해진다. 내부 시작도 같다: 저배터리 자동 도킹은 대기로 남았다가 `LOCALIZED` 로 돌아오면 이어 가고, SAF-005 `RETURN_HOME` 은 보낼 수 없는 귀환으로 보아 e-stop 으로 올린다. `detail: {state, pose_frame, reason}`. `localization` 이 `null` 인 로봇(D-395 이전)에는 적용하지 않는다 (v1.72) | 로봇 |
| `STALE_REQUEST` | 409 | `POST /localization/decision` 의 `request_id` 가 로봇의 열린 요청이 아님을 CORE 가 이미 안다. 열린 요청이 없을 때 `candidate` 결정도 같다 (v1.72) | 로봇 |
| `NO_CANDIDATES` | 404 | `GET /localization/candidates` — 로봇이 `CANDIDATES` 가 아니거나 열린 요청의 보고가 아직 없음 (v1.72) | 로봇 |
| `localized` · `busy` · `estop` · `path_not_clear` · `calibration_lease` · `unsupported` | 409 | `POST /localization/mission` 거부(D-395 P2-7, v1.73, 계약 §2 의 소문자 코드): 로봇이 이미 `LOCALIZED`; 미션·MANUAL·NAVIGATION·도킹·line-follow·swarm·Nav2 목표가 바퀴를 쥐고 있거나 로봇의 3 s 주입 검사가 도는 중(`reason: checking`); e-stop; 신선한 LiDAR 가 없거나 정면 부채꼴(±20°)이 0.25 m 보다 가까움(`nudge_forward`·`lane_to_stopline`); 다른 토큰의 보정 lease; 아직 없는 종류(`to_square`, 후속) | 로봇 |
| `CALIBRATION_ACTIVE` | 409 | 다른 토큰이 보정 세션 lease 를 쥐고 있어 구동 쓰기를 거부함: `teleop`, `/mode`(IDLE 제외), `line-follow/mode`(OFF 제외)·`hold`, `navigation/goal`·`home`, `docking/dock`·`undock`, `swarm/follow`. 멈추기만 하는 것(`safety/stop`, `/mode` IDLE, line-follow OFF, 각종 cancel)은 막지 않는다. `detail: {session}` 은 `GET /calibration/session` 의 세션과 같다. `POST /calibration/session` 이 이미 세션이 있을 때도 같은 코드 (D-321 부록, v1.68). D-395 경로 `POST /localization/decision`·`suspect` 에서는 같은 코드를 **423** 으로 낸다(v1.72, 계약 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §2) | 로봇 |
| `LINE_FOLLOW_NOT_HELD` | 409 | `POST /line-follow/hold` 인데 운전자 확인(`hold_s`) 세션이 없음 (v1.63) | 로봇 |
| `STUCK_ID_MISMATCH` | 409 | `POST /line-follow/stuck/decision` 의 `stuck_id` 가 지금 열린 막힘이 아님(늦은 답·이미 닫힌 막힘·막힘 없음). 늦은 답이 다음 막힘에 쓰이지 않게 한다 (D-407, v1.74) | 로봇 |
| `STUCK_DECISION_REFUSED` | 409 | 막힘 답을 지금 실행할 수 없음 — `RESUME`: 경로 띠 안 물체가 `obstacle_stop_m` 안이거나 scan 이 `clearance_stale_s` 보다 오래되었거나 LiDAR 정지를 쓰는데 scan 이 없음; `BACK_AND_RETRY`: 로컬 복구 꺼짐·시도 소진·뒤 여유 부족·LiDAR 사각·몸 기하 미설정·scan stale; `YIELD`: 구간이 없거나 유한하지 않음·거리 밖(0.05–2.0 m)·회전이 π 를 넘음·회전 여유 없음(`turn_blocked`)·보정 중·몸 기하 미설정·scan 없음·scan stale·선속도 한도 0. 앞에 동료가 있는 것만으로는 거절하지 않는다. 메시지에 사유 (D-407, v1.74; YIELD 는 D-453, v1.95) | 로봇 |
| `LINE_FOLLOW_ACTIVE` | 409 | 라인 추종이 켜져 있어 도킹/언도킹을 시작하지 않음 — `line-follow/mode` 를 `OFF` 로 먼저 (v1.18) | 로봇 |
| `IR_FALLBACK_NOT_READY` | 409 | 카메라 고장 상태, IR 라인 증거 최신성, 보정 revision, 또는 센서 안전 정책을 만족하지 못함 | 로봇 |
| `NO_ODOMETRY` | 409 | 오도메트리가 없어 언도킹 후진 거리를 잴 수 없음 (v1.18) | 로봇 |
| `RECORDING_BUSY` | 409 | Pilot 로봇 녹화가 진행 중이거나 manifest 해시를 끝내는 중(`stopping`) — 동시 녹화는 1개, 그동안 시작·수신 불가 (D-411, v1.83) | 로봇 |
| `RECORDING_NOT_ACTIVE` | 409 | 정지할 녹화가 없음 (`POST /recordings/active/stop`, D-411, v1.83) | 로봇 |
| `ROBOT_MOVING` | 409 | 녹화 수신은 정지 중에만: 살아 있는 MANUAL 입력 없음·NAVIGATION/DOCKING 아님·line-follow OFF·신선한 0 속도(또는 E-Stop; 0 은 인코더 틱 잡음 바닥 선 0.005 m/s·각 ≈0.0265 rad/s 이하, D-411 부록 17). MANUAL 모드 자체는 막지 않는다 (D-411, D-136 §6, v1.83) | 로봇 |
| `RECORDING_NOT_FOUND` | 404 | 없는 녹화 id, 안전하지 않은 id, manifest 없음·무효, manifest 와 다른 크기·폴더 밖·일반 파일 아닌 멤버 (D-411, v1.83) | 로봇 |
| `RECORDING_QUOTA_FULL` | 507 | 받지 않은(fetched 아님) 녹화로 전용 쿼터의 예비분까지 찼다 — 받아 가면 정리 대상이 된다 (D-411, v1.83) | 로봇 |
| `RECORDING_DISK_FULL` | 507 | 녹화 디스크의 빈 공간이 512 MiB 이하라 시작을 거부함 (D-411, v1.83) | 로봇 |
| `RECORDER_UNAVAILABLE` | 503 | 카메라 유닛 녹화기의 상태가 없거나 3 s 넘게 낡음, 서비스 무응답, 저장 디렉터리 없음·쓰기 불가, rosbag2 기동 실패 (D-411, v1.83) | 로봇 |
| `ROBOT_OFFLINE` | 503 | 대상 로봇 미접속 | Fleet |
| `HW_PROBE_UNAVAILABLE` | 503 | 장치 점검 요청 파일을 쓰지 못함 (`POST /host/hardware/refresh`, D-247) | 로봇 |
| `HW_TEST_COOLDOWN` | 429 | 부저·램프 시험을 10초 안에 다시 요청함 (`POST /host/hardware/test`, D-247 6, v1.23) | 로봇 |
| `HW_TEST_UNAVAILABLE` | 503 | 부저·램프 시험 요청 파일을 쓰지 못함 (`POST /host/hardware/test`, v1.23) | 로봇 |
| `HW_CONFIRM_UNAVAILABLE` | 503 | 들림·보임 기록을 쓰지 못함 (`POST /host/hardware/confirm`, v1.23) | 로봇 |
| `HW_CONFIRM_NO_TEST` | 409 | 그 장치를 `done`으로 5분 안에 끝낸 시험이 없는데 들림·보임을 답함 — 시험 없음·`busy`·`unavailable`·`failed`·다른 장치·5분 초과 (`POST /host/hardware/confirm`, v1.23) | 로봇 |
| `SSH_INVALID` | 422 | D-418 공개키(허용 종류·한 줄·base64)·라벨(`^[a-z0-9][a-z0-9._:-]{0,47}$`)·`expires_days`(1..365)·`minutes`(1..60)가 계약과 맞지 않음. `detail.fields`. root 도우미도 같은 규칙으로 다시 검사한다 (`/host/ssh/...`, v1.89) | 로봇 |
| `SSH_LABEL_EXISTS` · `SSH_KEY_EXISTS` · `SSH_KEYS_FULL` | 409 | D-418 같은 라벨이나 같은 공개키가 이미 있음, 또는 관리 키가 이미 32개 (`POST /host/ssh/keys`, v1.89) | 로봇 |
| `SSH_KEY_NOT_FOUND` | 404 | D-418 그 라벨의 관리 키가 없음 (`DELETE /host/ssh/keys/{label}`, v1.89) | 로봇 |
| `SSH_ACCESS_UNAVAILABLE` | 503 | D-418 root `rosy-ssh-access`가 10 s 안에 답하지 않았거나(요청은 거둬들인다), 요청 파일을 못 썼거나, 적용에 실패함(`chpasswd`·`sshd -t`·만료 타이머·파일 쓰기 실패, `keys.json` 손상 — 비밀번호는 켜지지 않은 채로 되돌린다) (`/host/ssh/...`, v1.89) | 로봇 |
| `COMMAND_TIMEOUT` | 504 | 명령 추적 타임아웃 (PRT-004) | Fleet |
| `PAIRING_INVALID` | 401 | 페어링 토큰 무효/만료 | Fleet |
| `IDEMPOTENCY_CONFLICT` | 409 | 동일 key·다른 내용 | Fleet |
| `INTERNAL_ERROR` | 500 | 내부 오류 | 로봇/Fleet |

---

# 4. 공용 데이터 모델

### 공용 Enum

| Enum | 값 |
|---|---|
| `mode` | `IDLE`, `MANUAL`, `NAVIGATION`, `DOCKING`, `EMERGENCY` |
| `navigation_state` | `IDLE`, `PLANNING`, `NAVIGATING`, `ARRIVED`, `CANCELED`, `FAILED`, `BLOCKED` |
| `health` | `OK`, `WARNING`, `ERROR`, `UNKNOWN` |
| `severity` | `info`, `warning`, `error`, `critical` |
| `command_priority` | 1=EMERGENCY, 2=SAFETY, 3=MANUAL, 4=DOCKING, 5=NAVIGATION, 6=FLEET, 7=IDLE |
| `fleet_policy` | `STOP`, `HOLD`, `RETURN_HOME`, `CONTINUE` |
| `dock_state` | `UNDOCKED`, `DOCKING`, `DOCKED`, `CHARGING`, `UNDOCKING`, `DOCK_FAILED` (v1.5 additive, DNC-004) |
| `line_follow_mode` | `OFF`, `IR_LINE`, `CAMERA_LINE` (v1.10 additive, D-143) |

**대소문자 표 (v1.16 additive)**: 위 표에서 UPPER 그룹(모드·내비·도킹·전원)은
`UPPER_SNAKE`, lower 그룹(심각도·배터리·프레즌스·군집 역할·참조 소스)은
`lower_snake`다. 두 관례가 공존하는 것은 역사적 사실이고 이 표가 계약이다 —
신규 enum 은 자기 그룹의 관례를 따르고, 소비자는 대소문자를 그대로 비교한다.
(ROS `power/mode` 토픽은 예외로 소문자 값을 실으며 JSON 과 다르다.)
`safety_policy.mode`·`mode_effective`·`safety.shadow_verdict.verdict` 는 소문자이고
config `control.sensor_adapter.mode` 와 같은 문자열이다(D-400). 일반 문자열이며 enum 검증을
하지 않으므로 값을 더하는 것은 additive 다.

### 좌표·계측

```json
{ "pose": { "x": 1.82, "y": 3.21, "yaw": 0.73 },
  "velocity": { "linear": 0.12, "angular": 0.0 },
  "battery": { "percent": 81, "voltage": 11.9 } }
```

`yaw`는 radian. 타임스탬프는 UTC ISO 8601.

`battery.percent` 와 `battery.voltage` 는 `number | null` 이다. `null` 은 아직 읽은 값이 없다는
뜻이다(CORE-only 처럼 배터리 출처가 없는 런타임 포함). 결측은 0% 가 아니다 — 소비자는 `null` 을
0 으로 바꿔 경보를 내지 않는다(D-82 Law 0, v1.18).

---

# 5. Robot REST API 카탈로그

로봇(rosy_core)이 제공하는 엔드포인트. Base: `http://<robot-host>:8080`

## 5.1 System

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/system/info` | Viewer | IDN-003. `caller_role`(v1.18 additive) — 이 요청 토큰의 역할(`viewer`\|`operator`\|`administrator`). 대시보드는 이것으로 관리 패널을 가르고, 권한 밖 경로를 찔러 보지 않는다. `robot_name` 은 오버레이에 이름이 없고 기본값(`Rosy 01`)뿐이면 프로비저닝 신원(`ROSY_DEVICE_NAME`, 없으면 `Rosy NN` ← `ROSY_ROBOT_NUMBER`)에서 온다 |
| PUT | `/api/v1/system/info` | Admin | IDN-003 (payload: `{robot_id?, robot_name?}`) — 로컬 오버레이에 영속 |
| GET | `/api/v1/system/capabilities` | Viewer | CAP-001. 지킬 수 있는 것만 광고한다(D-32) — §9.1 `withheld`, `runtime`(v1.21), `controls`(v1.87, D-411): `rosy.controls/1` `{schema, items[]}` — Pinky는 adapter `provides`의 `drive`(manifest가 없으면 `teleop`)에서 `base_velocity` 하나. 스키마 정본 `core_common.protocol.controls` |
| GET | `/api/v1/system/runtime` | Viewer | ROS-102 — 호스트 OS/CPU/RAM/디스크/온도 + 읽기 전용 ROS 그래프 스냅샷 |
| GET | `/api/v1/system/tokens` | Admin | SEC-101 — `{id, role, label, created_at, legacy, expires_at, source, current, last_used_at}`. `current` 는 호출자 자신의 토큰, `last_used_at` 은 CORE 가 켜진 뒤 마지막 인증 시각(메모리, 없으면 null). 만료된 토큰은 빠진다. 토큰에서 유도된 값은 싣지 않는다 |
| POST | `/api/v1/system/tokens` | Admin | SEC-101 (payload: `{role, label?, token?}`) — `token` 을 비우면 서버가 생성해 응답에 **단 한 번** 싣는다. 직접 정하면 16자 이상. 응답은 `Cache-Control: no-store`. 만료가 있는 호출자(페어링 세션)는 403 — 만료 없는 토큰을 만들 수 없다(D-193 보안 리뷰) |
| DELETE | `/api/v1/system/tokens/{id}` | Admin | SEC-101 — 호출자 자신의 토큰(400)과 만료 없는 마지막 administrator(409) 는 거부. 만료가 있는 administrator 는 세지 않는다(D-193). 만료가 있는 호출자가 만료 없는 administrator 를 지우려 하면 403 |
| PATCH | `/api/v1/system/tokens/{id}` | Admin | SEC-101 (payload: `{label}`, 64자 이하) — 이름표만 바꾼다. 응답은 목록 항목 한 개. 없거나 만료된 id 는 404 (v1.19) |
| POST | `/api/v1/auth/pair` | 없음 | D-193 (payload: `{code, label?}`, 본문 1 KiB 이하, 넘으면 413) — 로그인 코드 `ABCD-EFGH`(하이픈·대소문자 무시) → `201 {id, token, role, label, source, expires_at}`, `Cache-Control: no-store`. 원문 토큰은 이때 한 번만 싣는다. 출발지는 RFC 1918·루프백만(그 밖 403), IP 마다 60 s 5회·전체 60 s 30회(넘으면 429 + `Retry-After`). 형식이 아닌 코드는 400, 틀리거나 만료·사용된 코드와 발급된 코드가 없는 경우는 모두 같은 401 이다. 한 코드에 틀린 시도가 5회 쌓이면 코드를 폐기하고, 그 5번째 요청의 401 만 `error.detail = {"burned": true}` 를 싣는다(대시보드가 새 코드를 받으라고 안내한다) 토큰 수명은 `auth.pairing.token_lifetime_hours`(기본 operator·viewer 168 h, administrator 24 h, 설정해도 168 h 를 넘지 않는다) — 만료 없는 토큰은 나오지 않는다 |
| GET | `/api/v1/auth/whoami` | Viewer | D-193 — `{id, role, label, source, created_at, expires_at}`. 대시보드가 역할을 추측하지 않고 묻는다 |
| GET | `/api/v1/ui/surfaces/{surface}` | Viewer+ | D-263/D-265/D-283 — 역할별 화면 매니페스트. `console`/`setup`/`device`; 해당 화면 최소 역할보다 낮으면 403, 인증 실패 401, 미등록 화면 404. 응답은 현재 역할이 열 수 있는 기반 화면 목록과 현재 화면의 CAP-001·inventory 필터 패널, 구조 revision이다. console act 패널은 선택형 `action_group` (`drive`, `docking`, `line_follow`)을 담을 수 있으며, capability가 없거나 `not_provided` inventory인 panel과 그룹은 응답에서 생략한다. 메뉴는 패널 수와 독립이다. REST 응답 모델 `UiSurfaceManifest`; Fleet envelope `protocol_version`은 1.0 유지 |
| POST | `/api/v1/auth/logout` | Viewer | D-193 — 호출자 자신의 `pair-*` 토큰을 지운다(204). 다른 출처의 토큰은 409 — 설정 화면에서 회수한다 |
| POST | `/api/v1/auth/enrollment-codes` | Admin | D-193 (payload: `{role}`, 기본 `operator`) — 다른 기기용 로그인 코드 `201 {code, code_id, role, expires_in_s}`, 5분, CORE 메모리에만. 역할은 호출자 이하(넘으면 403). 이 코드로 받은 토큰의 출처는 `pair-admin` 이고 만료는 발급자 토큰의 만료를 넘지 않는다. 발급자 토큰이 회수·만료되면 코드도 무효다 |

## 5.2 Robot 상태·센서

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/robot/state` | Viewer | CORE-001 — payload는 §6.1과 동일 |
| GET | `/api/v1/robot/pose` | Viewer | §12 센서 |
| GET | `/api/v1/robot/battery` | Viewer | §12 |
| GET | `/api/v1/robot/velocity` | Viewer | §12 |
| GET | `/api/v1/sensors` | Viewer | §12 |
| GET | `/api/v1/sensors/{lidar\|imu\|ultrasonic\|battery\|encoder\|motor}` | Viewer | §12 |
| GET | `/api/v1/power` | Viewer | PWR-001 (절전 모드·프레즌스·샘플링 주기) |
| GET | `/api/v1/power/health` | Viewer | 전원 정책·절전 blockers·wake 제약·배터리 age/신선도/충전 확인·health 조회. 읽기 전용이며 깨우지 않음 |
| POST | `/api/v1/power/wake` | Operator | PWR-004 (원격 웨이크 — 정보 화면 표시) |
| POST | `/api/v1/power/mode` | Operator | PWR-001 (payload: `{mode: ACTIVE\|IDLE\|STANDBY}`) |

`GET /sensors`·`GET /sensors/{type}` 의 숫자 값 가운데 유한하지 않은 값(`inf`·`-inf`·NaN)은 JSON 에 없으므로 `null` 로 나간다. LiDAR `ranges` 의 반환 없는 빔(+inf)과 NaN 이 `null` 이며, 값이 있는 빔과 구분된다(`robot_body.scan_view` 와 같이 반환 없음 = 알 수 없는 구간). 필드 이름·형식은 그대로이고 CORE 내부 표본은 inf 를 유지한다.

`GET /power/health` 응답은 공유 `core_common.protocol.power_health.PowerHealthResponse` 계약이다. `power`는 기존 `PowerStatus`, `health`는 진단 요약이며 조회가 idle timer나 wake를 변경하지 않는다.

| 영역 | 필드와 해석 |
|------|-------------|
| `battery` | `evidence`: missing/fresh/stale; `sample_age_s`, `stale_after_s`(5초), `level`, `percent`, `filtered_voltage`. 낡은 전압·잔량은 마지막 관측값이며 현재 측정으로 사용하지 않는다. |
| 충전·종료 | `charging_state`: confirmed/unconfirmed. 전압과 충전 확인이 모두 5초 이내일 때만 confirmed; `charging_evidence_age_s`와 `charging_latched`는 마지막 확인의 age와 기존 정책 latch를 구분한다. `shutdown_armed`는 정책 조건, `shutdown_request_written`는 sentinel 기록이며 실제 OS 종료 완료가 아니다. |
| 잔여 시간 | `remaining_runtime_s`는 null, `remaining_runtime_reason`는 current_and_capacity_not_measured. 전류·용량 측정 없이 시간을 추정하지 않는다. |
| `policy` | `sleep_blockers`: power_policy_disabled/robot_mode_not_idle/information_hold; `deepest_available_mode`는 ACTIVE 또는 STANDBY 정책 상한(`deepest_mode_basis=policy_target`). 물리 절전 인증이나 POST 권한·보정 lease 허용을 뜻하지 않는다. `idle_after_s`, `standby_after_s`는 정상 설정(기본 600/1800초), `effective_idle_after_s`, `effective_standby_after_s`는 현재 적용 기준이다. warning은 60/300초, critical/deep은 30/120초 기본이며 정상 기준과 min을 취한다. `battery_alert` 포함. |
| 깨우기 | `wake_sources`는 api/proximity/contact/activity/battery_level_change 정책 처리기(`wake_sources_basis=policy_supported_not_hardware_verified`). contact는 초음파 거리 임계값이며 별도 접촉 스위치 확인이 아니다. `api_wake_requires_running_os=true`, `os_halt_remote_wake=not_verified`. |
| LiDAR | `lidar_standby_stop_enabled`는 설정이며 `lidar_state_basis=policy_intent`. 실제 모터 정지 증거와 구분한다. |
| 권고 | `recommendation`: 배터리 missing/stale이면 restore_battery_telemetry; fresh 경고이면 charge_and_conserve; fresh 정상은 normal_idle_policy. 권고는 자동 운전·종료 명령이 아니다. |

## 5.3 Navigation·SLAM

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/navigation/goal` | Operator | NAV-001 (`{x,y,yaw}` 또는 `{waypoint}`; 선택적 `correlation_id`는 Fleet dispatch 시도 ID와 실행 이벤트를 잇는 추적 메타데이터). 기능 보류 시 모드 전이 전에 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/navigation/cancel` | Operator | NAV-002 |
| POST | `/api/v1/navigation/home` | Operator | NAV-003. 기능 보류 시 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| GET | `/api/v1/navigation/state` | Viewer | NAV-004 |
| GET | `/api/v1/navigation/path` | Viewer | MAP-003 |
| GET | `/api/v1/line-follow/perception` | Viewer | 저장된 `paint_source`(threshold / denoise / learned), `camera_lane_mode`, 서명·해시 확인 `model_ready`와 `model_revision`. 별도 `applied_paint_source`는 실제 최신 keeper 프레임의 threshold / denoise / learned / denoise_fallback 또는 null; `applied_source_age_s`는 monotonic 수신 나이(2초 이내), `applied_model_revision`은 실제 사용한 learned mask의 producer revision(없으면 null). stale·malformed·설정 불일치·재시작 전 증거는 null. 운전 모드와 독립이며 물체 검출이나 주행 허가가 아니다. |
| PUT | `/api/v1/line-follow/perception` | Administrator | `{paint_source: threshold\|denoise\|learned}`만 허용. IDLE·line-follow OFF·보정 비활성, Host Agent가 fresh 정지 및 active mission 부재를 재확인. 기존 기하 보존, learned는 고정 signed model pointer 검증, camera만 재시작·실패 복구. `applied: true`는 설정/서비스 적용이며 live 추론이나 실제 주행 성공이 아니다. |
| GET | `/api/v1/line-follow` | Viewer | D-143 — 선택 모드, 상태, 증거 신뢰도·나이, 최종 선속도·각속도와 사유. `clearance_m`(정면 LiDAR 최소 거리, 없으면 null)과 정지 사유 `obstacle_ahead`·`obstacle_sensor_stale`·`driver_released` (D-344, v1.63). IR 이탈 감시(`line_follow.ir_guard_enabled`)가 켜지면 추종 사유 `lane_edge_left`·`lane_edge_right`(경계 반대로 비킴)와 정지 사유 `lane_departure`·`lane_guard_stale` (D-344 §12, v1.63). 공칭 지면(`ground: NOMINAL`) 카메라 증거는 `hold_s` 세션이 없으면 `nominal_ground_requires_driver` 로 멈춘다 (D-364 §3, v1.63). 정지 사유 `limit_level_too_low`(수동 한도 L1 미만)·`angular_limit_zero`(각속도 한도를 읽을 수 없음) (D-344 §13, feat/device-prep, v1.64). 몸 기준 정지(D-422, v1.84: `obstacle_mode: path` + 로봇 패키지 URDF 몸 기하)에서는 `body_gap_m`(의도한 차선 호를 따라 몸 윤곽이 닿기까지의 거리, 없으면 null)·`stop_gap_m`(그 속도의 정지 간격)·`clearance_source`(`lidar`·`memory`(LiDAR `range_min` 아래로 사라져 기억한 반환)·`ultrasonic`·`odometry_lost`(바퀴 값 적분 실패 — 다음 스캔까지 정지), 아무것도 없으면 null)가 오고 `clearance_m` 은 `body_gap_m` 과 같은 몸 간격이다. 그 밖에는 세 필드 모두 null |
| PUT | `/api/v1/line-follow/mode` | Operator | D-143 — `{mode: OFF\|IR_LINE\|CAMERA_LINE, hold_s?}`. 소스는 상호 배타적이며 변경 즉시 이전 증거와 명령을 폐기. 도킹/언도킹 중에는 409 `DOCKING_ACTIVE` (v1.18). 요구 능력은 구동(`mobility.move`)이다 — Nav2 가 없는 `motor` 런타임에서도 켜진다(D-344 §7, v1.63). `hold_s`(0 < s ≤ 2)를 주면 운전자 확인 세션이다: `POST /line-follow/hold` 가 그 안에 계속 와야 하고, 끊기면 CORE 가 스스로 OFF(`reason: driver_released`)로 내리고 바퀴 명령을 지운다(D-344 §8, v1.63). OFF 가 아닌 모드는 D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/line-follow/hold` | Operator | D-344 §8 — 운전자가 "진행"을 누르고 있다. 활성 `hold_s` 세션의 만료를 `hold_s` 만큼 미룬다. 세션이 없으면 409 `LINE_FOLLOW_NOT_HELD` (v1.63) |
| POST | `/api/v1/line-follow/stuck/decision` | `STUCK_DECIDE` (operator·administrator·`stuck_resolver`, D-438 v1.91) | D-407 §2 / D-453 — `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT\|YIELD}`. `YIELD` 는 선택 필드 `yield_m`·`yield_turn_rad` 가 둘 다 있어야 하고, 다른 결정에 그 필드가 있으면 400 `VALIDATION_ERROR`. 한 답은 한 구간이다. CORE 는 회전을 확인한 뒤 그 거리만 앞으로 기어 가고, 끝나면 `YIELDED` 로 서며 차선 추종을 재개하지 않는다. 다음 `YIELD` 가 다음 구간이다. 열린 막힘(`GET /line-follow` 의 `stuck`)에 대한 관제 답. `WAIT` 그대로 HOLD·로컬 복구 안 함; `RESUME` 앞물체 정지를 한 번 풀어 `obstacle_stop_m` 까지 접근 허용·LOST 해제 후 차선 추종 재개; `BACK_AND_RETRY` 짧은 후진과 재판단을 즉시(로컬 복구가 켜져 있어야 함); `MANUAL` 차선 추종 OFF + MANUAL(D-342 한도); `ABORT` 차선 추종 OFF + IDLE. 응답은 line-follow 상태 + `outcome`(`hold\|back\|resume\|manual\|idle\|yield`). `RESUME`·`BACK_AND_RETRY`·`MANUAL`·`YIELD` 는 보정 lease 를, `RESUME`·`BACK_AND_RETRY`·`YIELD` 는 E-Stop 을 지킨다. `MANUAL`·`ABORT` 의 모드 전이는 `POST /mode` 와 같다(`MANUAL` 은 navigation·swarm 취소, `mode.changed`). 409 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`·`CALIBRATION_ACTIVE`·`EMERGENCY_ACTIVE`. 운용자 Fleet 경로의 다섯 단어와 추가 필드 422 는 그대로다 (v1.74, YIELD 는 v1.95) |
| GET | `/api/v1/traffic` | Viewer | D-151 — 교통 인식 증거, 정책 판정, active/staged 설정과 simulation signal capability readback |
| POST | `/api/v1/traffic/policy/stage` | Operator | D-151 — 정책 모드·revision·거리·dwell·신뢰도 기준을 검증해 검토본으로 저장. 활성 정책은 바꾸지 않음 |
| POST | `/api/v1/traffic/policy/apply` | Operator | D-151 — IDLE/EMERGENCY이고 line-follow가 꺼져 있으며, fresh 0 속도 또는 E-stop으로 정지가 증명된 경우에만 staged 정책을 원자 적용 |
| PUT | `/api/v1/traffic/simulation/signal` | Operator | D-151 — 명시적 simulation capability에서만 `{colour: RED\|YELLOW\|GREEN}` 허용. 실제 장치에서는 501 |
| GET | `/api/v1/vision/models` | Viewer | D-423: 로봇 학습 모델 상태(작업별, 읽기 전용) `{tasks:[{task,slot,model_revision,last_error,frames_inferred,latency_ms_p50,signed,age_s,stale}]}` (`signed`: 노드가 서명을 확인했으면 true/false, 아니면 null; lane_seg 는 경고만이라 false 일 수 있다). `lane_seg`/`shadow` 는 `perception/learned/status`, `object_det`/`active` 는 `perception/learned/object_det/status` 에서 온다. CORE 는 포인터 파일을 읽지 못하므로 노드가 없는 슬롯은 빠진다. `no-store`. 교체(promote/rollback)는 운영자 CLI(`rosy_ml`)만 — CORE 쓰기 API 없음 |
| GET | `/api/v1/vision/front/status` | Viewer | 최신 front camera preview의 available/stale, source, frame, 크기, overlay, sequence 메타데이터. 원본 영상은 상태 WebSocket에 싣지 않음 |
| GET | `/api/v1/vision/front/frame` | Viewer | D-152 fresh 최신 JPEG 한 장. `Cache-Control: no-store`, `Content-Encoding: identity`; 없거나 stale이면 404 `CAMERA_FRAME_UNAVAILABLE` |
| GET | `/api/v1/vision/front/stream` | Operator | D-368 (v1.102) 운전자 전용 MJPEG 스트림. `multipart/x-mixed-replace; boundary=frame`, `?overlay=`(기본 true, `false`면 raw pair). 파트 헤더 `X-Rosy-Camera-{Sequence,Source,Captured-At}`. 조종 소유권은 가장 최근 수락된 teleop 토큰(D-460, 임대 없음): 운전자 아님 409 `CAMERA_STREAM_NOT_DRIVER`, 동시 하나만 409 `CAMERA_STREAM_BUSY`, 다른 토큰의 teleop 수락으로 열린 스트림이 끝난다. 인증은 헤더만(D-193). 관전자·관제 화면은 기존 0.4 s 폴링을 그대로 쓴다 |
| POST | `/api/v1/vision/front/evidence` | Operator | 카메라 화면에서 만든 JPEG 스크린샷 또는 WebM/MP4 녹화를 로봇 SD에 저장. 길이 접두 JSON 메타데이터 뒤에 바이너리 미디어를 전송; 성공 시 `VisionEvidenceRecord`(201) |
| GET | `/api/v1/vision/front/evidence` | Operator | 저장된 카메라 증거의 최신 목록(`VisionEvidenceList`, 최대 50건) |
| GET | `/api/v1/vision/front/evidence/{id}` | Operator | 저장 미디어 다운로드. 24자리 불투명 id만 허용; 없으면 404 |
| POST | `/api/v1/localization/initialpose` | Operator (`NAVIGATE`) | 초기 자세 `{x, y, yaw}`, 응답 `{accepted: true}` 그대로. D-395 로봇(`localization` 이 null 아님)에서는 `/initialpose` 를 직접 쓰지 않고 `LocalizationDecision(source: human, pose)` 로 `localization/decision` 에 보내, 로봇의 3 s 검증을 거친다. `request_id` 는 열린 요청이 있으면 그것, 없으면 `human-<ms>`. D-395 이전 로봇은 예전처럼 `/initialpose` 를 쓴다 (v1.72) |
| GET | `/api/v1/localization/candidates` | `LOCALIZE_ASSIST` | D-395 P2-4 — 최신 `CandidateReport`(§7.9, `robot_id` 는 CORE 신원). `CANDIDATES` 가 아니거나 열린 요청의 보고가 없으면 404 `NO_CANDIDATES` (v1.72) |
| POST | `/api/v1/localization/decision` | `LOCALIZE_ASSIST` (+`NAVIGATE` for `source: human`) | D-395 P2-4 — 본문 `LocalizationDecision`(§7.9). 로봇에 보냈으면 202 `{request_id}`. 열린 요청이 아니면 409 `STALE_REQUEST`, 보정 lease 중 비소유자는 423 `CALIBRATION_ACTIVE`, 스키마 위반 400, D-395 이전 로봇은 501. `source: human` 이면 `localization.initialpose` 를 낸다 (v1.72) |
| POST | `/api/v1/localization/suspect` | `LOCALIZE_ASSIST` | D-395 P2-4 — `{reason}`(1–64자, 예: `fleet_monitor`)를 로봇 `localization/suspect` 로. 202 `{accepted: true}`, lease 중 423, D-395 이전 로봇 501 (v1.72) |
| POST | `/api/v1/localization/mission` | `LOCALIZE_ASSIST` | D-395 P2-7 — `{kind, max_distance_m, max_time_s, target}`. CORE 가 스스로 아주 느리게 움직인다(Fleet 은 바퀴를 몰지 않는다, D-2·D-369). 로봇이 `LOCALIZED` 가 아닐 때만. `kind`: `rotate_in_place`(오도메트리로 최대 한 바퀴, 0.3 rad/s, `max_distance_m` 무시, 전체 스캔에 0.20 m 안 반사가 있으면 `path_not_clear`), `nudge_forward`(오도메트리로 0 < `max_distance_m` ≤ 0.10 m, 0.03 m/s, 정면 0.25 m 안에 물체가 들어오거나 정면 ±20° 를 잴 수 없으면 — 유효 빔 5 개 미만, 또는 inf·NaN·`range_min` 미만 빔이 30 % 초과, self-mask 반사는 빼고 — 거부·끝), `lane_to_stopline`(카메라 line-follow 를 이 미션에 한해 `LOCALIZED` 관문 없이 켜고 0.04 m/s 로 제한, 정지선 0.12 m 안·거리·시간에서 끝, 0 < `max_distance_m` ≤ 1.0), `to_square`(409 `unsupported`: map 프레임 없이 사각형까지 가는 차선 경로가 아직 없다, 후속). `0 < max_time_s ≤ 120`. 움직임은 NAVIGATION 모드의 nav 슬롯으로 들어가 50 Hz 최종 중재(`select_output`: e-stop·readiness·속도 제한·제어 정책)를 그대로 거친다. 202 는 `GET` 과 같은 본문(`state: running`). 끝: `done`·`stop_line`·`localized`(→ `state: done`), `timeout`·`obstacle`·`obstacle_sensor_stale`(모든 종류, LiDAR 0.5 s 끊김)·`odometry_stale`·`lane_lost`·`estop`·`cancelled`(모드가 NAVIGATION 을 떠남: MANUAL·IDLE·line-follow OFF)·`error`(→ `aborted`). 끝나면 바퀴 명령을 지우고 IDLE 로 돌아가며, ROS `localization/mission` `{kind, state, reason}` 으로 로봇 sensing 노드가 바로 다시 탐색한다. 거부 409 코드는 §ERR-102, 범위 위반 400, D-395 이전 로봇 501, 구동 능력 없음 501, readiness HOLD 503 (v1.73) |
| GET | `/api/v1/localization/mission` | Viewer | D-395 P2-7 — `{kind, state, reason}`; `state`: `idle`(아직 없음, `kind`·`reason` 은 `null`) \| `running`(+ `elapsed_s`, `travelled_m`, `turned_rad`) \| `done` \| `aborted` (v1.73) |
| POST | `/api/v1/slam/start` | Operator | NAV-005 — 추종 세션이 주행을 쥐고 있으면 409 `NAVIGATION_ACTIVE` |
| POST | `/api/v1/slam/stop` | Operator | NAV-005 |
| POST | `/api/v1/slam/save` | Operator | NAV-005 (응답에 `map_id`) |
| POST | `/api/v1/slam/reset` | Operator | NAV-005. **미구현** — 어느 런타임에도 slam_toolbox 리셋이 없어 항상 `501 CAPABILITY_NOT_SUPPORTED`. 맵핑 세션이 없으면 `400 VALIDATION_ERROR` (D-32) |

## 5.4 Map·Waypoint

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/map` | Viewer | MAP-003 (응답에 `map_id` 포함) |
| GET | `/api/v1/map/costmap?scope=global\|local` | Viewer | MAP-003 |
| GET | `/api/v1/waypoints` | Viewer | WPT-002 |
| POST | `/api/v1/waypoints` | Operator | WPT-002 |
| PUT | `/api/v1/waypoints/{name}` | Operator | WPT-002 |
| DELETE | `/api/v1/waypoints/{name}` | Operator | WPT-002 |

## 5.5 제어·안전

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/teleop` | Operator | §11. 기능 보류 시 409 `CAPABILITY_WITHHELD`. 다른 토큰의 보정 세션 중 409 `CALIBRATION_ACTIVE` (v1.68) — owner 의 teleop 은 D-342 한도 안에서 그대로 동작 |
| POST | `/api/v1/mode` | Operator | `{mode: MANUAL\|NAVIGATION\|IDLE}`. 다른 토큰의 보정 세션 중 MANUAL·NAVIGATION 은 409 `CALIBRATION_ACTIVE`, IDLE 은 멈춤이라 허용 (v1.68) |
| POST | `/api/v1/swarm/follow` | Operator | SWM-002 `{target_robot_id, distance, lateral, max_speed, stream_timeout_ms, source, members}`. `source: fleet(기본)\|peer(예약, D-21 — 요청하면 501)`. `members` 는 대형 명단을 `robots.yaml` 순서로 — 비어 있으면 리더 승계를 하지 않고, 있으면 리더 상실 시 `swarm.succession` 을 낸 뒤 follow 를 끝낸다. `max_speed` 는 SAF-004 상한을 넘으면 400 이고, 추종 구간 동안 실제 상한으로 적용된다 — Nav2 가 무엇을 내보내든 `cmd_vel` 은 이 값으로 클리핑된다(D-31). 적용 중인 값은 `GET /safety/state` 의 `limits.session_linear` 에 보인다. 미지원 로봇은 501 `CAPABILITY_NOT_SUPPORTED` (SWM-005/CAP-003), 도킹/언도킹 중에는 409 `DOCKING_ACTIVE`, 맵핑 세션 중에는 409 `MAPPING_ACTIVE`, E-Stop 중에는 409 `EMERGENCY_ACTIVE`. 추종 중 `POST /navigation/cancel` 이나 MANUAL 전환은 대형을 끝내고 `swarm.aborted` 를 낸다 |
| POST | `/api/v1/swarm/cancel` | Operator | SWM-002 |
| GET | `/api/v1/swarm/state` | Viewer | SWM-006 — `{role, formation, active, holding, target_robot_id, source, max_speed, map_mismatch, stream_age_s}`. `map_mismatch` 는 거부 중인 리더의 `map_id` 다. 상태 스냅샷의 `swarm` 필드는 그중 `role`·`formation`·`active` 다 |
| GET | `/api/v1/calibration/session` | Viewer | D-321 부록 (v1.68) — `{session: Session\|null}`. `Session` = `{id, kind, label, owner: {id, role, label}, started_at, ttl_s, elapsed_s, remaining_s}`. `owner.id` 는 `GET /auth/whoami` 의 `id` 와 같은 불투명 토큰 id |
| POST | `/api/v1/calibration/session` | Operator | `{kind, label?, ttl_s?}` → 201 `{session}`. 모드가 IDLE·MANUAL 이 아니거나 navigation·도킹·line-follow·swarm 이 돌고 있으면 409 `MODE_CONFLICT`. `kind` 는 `^[a-z][a-z0-9_]{0,31}$`(알려진 값 `drive`·`camera`·`imu`·`ir`·`lidar`·`odometry`), `label` ≤ 80자(비면 `kind`), `ttl_s` 5–300(기본 30). 호출 토큰이 owner 가 된다. 세션은 로봇당 하나 — 이미 있으면(같은 토큰이어도) 409 `CALIBRATION_ACTIVE` + `detail.session` |
| POST | `/api/v1/calibration/session/{id}/heartbeat` | Operator | owner 만. `ttl_s` 를 다시 채운 `{session}`. 다른 토큰 403 `FORBIDDEN`, 없거나 만료된 id 404 `NOT_FOUND`. `ttl_s` 안에 heartbeat 가 없으면 세션은 만료되고 `calibration.session_expired` 가 한 번 발행된다 |
| DELETE | `/api/v1/calibration/session/{id}` | Operator | owner 또는 Admin(걸린 lease 강제 해제). 끝난 `{session}`. 그 밖의 토큰 403, 없는 id 404 |
| POST | `/api/v1/safety/stop` | Viewer↑ | SAF-001 (누구나). 보정 세션 중에도 막지 않는다 |
| POST | `/api/v1/safety/release` | Admin | SAF-001 |
| GET | `/api/v1/safety/state` | Viewer | SAF-001. `fleet_loss_policy` 와 선택 필드 `fleet_link` (SAF-003, D-419, v1.86) `{configured, connected, lost, timeout_s, applied, correlation_id, disconnected_s, held_goal}` — `configured` 는 FleetAgent 가 돌고 있는가(승인된 `pairing_token` + 주소), `lost` 는 이번 단절에서 정책을 적용했는가, `applied` 는 실제로 한 것(`STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`·`NONE`), `held_goal` 은 `HOLD` 가 보관한 `{correlation_id, x, y, yaw}`(재접속 이벤트 뒤 비움). 서비스가 없으면 `null` |
| PUT | `/api/v1/safety/limits` | Admin | SAF-004 — `{manual_linear?, manual_angular?}` 는 프로필 최대값으로 clamp. SAF-005 배터리 임계값 `{battery_warning_percent?, battery_critical_percent?, battery_deep_percent?, battery_critical_policy?}` 과 `{fleet_loss_policy?}` 도 같은 경로로 받는다. 임계값은 `0 < deep < critical < warning <= 100` 을 만족해야 한다. `fleet_loss_policy` 는 `STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`(`CONTINUE_CURRENT_NAVIGATION` 은 `CONTINUE` 로 저장), 그 밖은 400. `RETURN_HOME` 을 받으면 응답에 선택 필드 `warning`(문자열) — 사이트 Fleet 이 죽으면 이 정책의 로봇이 Fleet 교통정리 없이 동시에 home 으로 간다 — 을 싣고 로그에 경고를 남긴다(거절하지 않음). 판정 시간 `safety.fleet_loss_timeout_s`(기본 5.0, 4–60 s, `1 + fleet.heartbeat_reply_timeout_s + 1` 이상)와 하트비트 답 시한 `fleet.heartbeat_reply_timeout_s`(기본 2.0, 0.5–10 s)는 설정 파일 전용이고, Fleet 링크가 설정된 로봇에서 어기면 CORE 가 기동하지 않는다(Fleet 없는 로봇은 경고 후 기본값) (D-419) |

## 5.6 이벤트·진단·관리

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/events?since_seq=N&types=...` | Viewer | EVT-003 |
| GET | `/api/v1/diagnostics` | Viewer | DIAG-001 — `{health, components}`. `health` 는 최악값 롤업, 수집 전이면 `UNKNOWN` |
| GET | `/api/v1/diagnostics/{component}` | Viewer | DIAG-001 — 모르는 이름은 404. `/metrics` 의 `rosy_diagnostics_health` 와 같은 출처다 |
| GET | `/api/v1/logs/audit` | Admin | LOG-001 — `{events, log}`. `log` 은 `{writable, write_failures, write_failures_total, prune_failures, prune_skipped, serialize_failures, last_write_error, last_prune_error, last_skip_reason, last_serialize_error, dir_sync_failures, last_dir_sync_error}`: 기록이 멈추어 있으면 짧은 목록과 구분되지 않으므로, 이 로그를 믿어도 되는지 함께 답한다. `write_failures` 는 **연속** 실패(지금 쓸 수 있는가), `write_failures_total` 은 부팅 이후 누적이라 되돌아가지 않는다. `prune_failures` 는 기록이 아니라 보존 정리가 실패한 횟수다 — 기록은 남고 있으나 파일이 30 일보다 길게 자라는 중이라 경보 기준이 다르다. `serialize_failures` 는 이벤트 `data` 가 JSON 이 될 수 없어 그 값을 `repr` 로 바꿔 남긴 횟수다(기록은 남았다 — 발행한 쪽의 결함). `dir_sync_failures` 는 정리의 바꿔 끼우기는 끝났는데 그 뒤 디렉터리 fsync 가 실패한 횟수다(정리 실패가 아니다 — 정전이 이름 바꾸기를 되돌려도 옛 파일이 남는다). 사유는 채널별로 나누어 남기며(하나로 두면 정리 실패가 디스크 부족이라는 사유를 덮어쓴다) 성공했다고 지우지 않는다. 스키마로도 JSON 으로도 읽을 수 없는 줄은 삭제하지 않고 감사 로그 옆 `audit.jsonl.quarantine` 으로 바이트 그대로 옮긴다 |
| GET | `/metrics` | 내부/모니터링 | OBS-101 (Prometheus 형식, 토큰 면제는 배포 정책). `rosy_audit_write_failures_consecutive` 가 0 이 아니면 LOG-001 감사 기록이 남지 않고 있다 |
| GET | `/api/v1/ros/nodes\|topics\|services` | Admin | **미구현** — ROS-102. 그래프 스냅샷은 `/api/v1/system/runtime` 이 제공한다 |
| POST | `/api/v1/ros/publish` | Admin + 설정 ON | **미구현** — ROS-102. D-2(단일 퍼블리셔)와 충돌하므로 구현 시 별도 ADR 필요 |
| POST | `/api/v1/docking/dock` | Operator | DNC-003 (미지원 시 501). body: `{"dock": "dock_1"}` — 도크가 1개면 생략 가능. 409: `DOCKING_ACTIVE`(이미 진행 중), `LINE_FOLLOW_ACTIVE`, `MODE_CONFLICT`(DOCKING 모드를 쥘 수 없음 — MANUAL 등), `EMERGENCY_ACTIVE` |
| POST | `/api/v1/docking/undock` | Operator | DNC-003. 409: `NOT_DOCKED`, `LINE_FOLLOW_ACTIVE`, `NO_ODOMETRY`, `MODE_CONFLICT`, `EMERGENCY_ACTIVE` |
| POST | `/api/v1/docking/cancel` | Operator | DNC-003 |
| GET | `/api/v1/docking/status` | Viewer | DNC-003 — **capability 무관 항상 200**, `supported` 포함 |
| GET | `/api/v1/docking/docks` | Viewer | DNC-005 |
| GET | `/api/v1/docking/types` | Viewer | DNC-005 도크 유형·검출기 설정 목록 조회 |
| POST | `/api/v1/docking/types` | Admin | DNC-005 도크 기종 등록. v1.18 선택 필드(생략 시 기존 충전 도크 동작): `tag_id`, `tag_size_m`, `staging`(기본 true), `approach`(`bearing` 기본 \| `pose`), `settle`(`agent` 기본 \| `pose`), `tag_offset_m`, `acquire_creep_m`, `backoff_m`, `undock_turn_rad` — 주차형 도크 (docs/plans/2026-09-23-lane-network-parking-design.md) |
| POST | `/api/v1/docking/docks` | Admin | DNC-005 도크 개체 등록 |
| DELETE | `/api/v1/docking/docks/{id}` | Admin | DNC-005 |
| POST | `/api/v1/docking/docks/{id}/teach` | Operator | DNC-005 teach-by-docking |

## 5.7 Host (Host Agent 릴레이)

CORE 는 이 경로의 호스트 작업을 직접 실행하지 않고 unix 소켓으로 Host Agent 에 넘긴다(`docs/reference/rosy-host-agent-contract.md`). 네트워크·릴리스 조회에서 에이전트가 없으면 HTTP 200과 `available:false`, 사유, `evidence.evidence:"disconnected"`를 돌려준다.
파괴적 명령은 `{confirmed: true}` 와 `idempotency_key` 를 받는다.

v1.42: `GET /api/v1/host/network`와 `/release`는 기존 `{available,ok?,code,detail,recovery,data}`에 `evidence:{evidence,observed_at,age_s,stale_after_s,reason}`을 추가한다. `evidence`는 `fresh`·`delayed`·`disconnected`·`unavailable` 중 하나이며 CORE가 Host Agent의 해당 조회 완료 UTC `observed_at`을 검증해 판정한다. `age_s`는 CORE 응답 시각에서 원본 시각을 뺀 초, 임계는 15초다. 원본 시각이 없거나 잘못됐거나 미래이면 `unavailable`이며 `data:null`이다. 소켓 미연결·타임아웃은 `disconnected`, 유효하지만 15초 초과한 조회는 `delayed`다. `available`은 소켓 응답 여부를 뜻하므로 `available:true`여도 증거가 `unavailable`일 수 있다. 화면은 `fresh`일 때만 네트워크·릴리스 작업을 허용한다. 이 증거는 상태 조회 완료 시각이며 POST 적용 readback이나 물리 결과가 아니다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/host/network` | Viewer | NET-001 — 현재 모드와 도달성. SSID 는 싣되 PSK 는 절대 싣지 않는다 |
| POST | `/api/v1/host/network/apply` | Admin | NET-001 (payload: `{profile_id, confirmed, idempotency_key?}`) — 등록된 NetworkManager 프로파일로 전환. PSK 는 호스트에 남고 CORE 에 들어오지 않는다 |
| GET | `/api/v1/host/release` | Viewer | OPS — current/previous/staged 와 마지막 실패 사유 |
| POST | `/api/v1/host/release/install` | Admin | OPS — 서명 검증된 릴리스 설치 |
| POST | `/api/v1/host/release/rollback` | Admin | OPS — previous 로 복귀 |
| POST | `/api/v1/host/release/clear-hold` | Admin | OPS — RECOVERY HOLD 해제 |
| GET | `/api/v1/host/commissioning` | Viewer | HWA-001 — runtime mode 와 hardware 재승인 사유. v1.22 `motion_reason`: 로봇이 왜 못 움직이는지 한 문장(D-247 7, 권한 문구와 구별). hardware 모드는 `""` |
| GET | `/api/v1/host/hardware` | Viewer | D-247 — 보드 장치 관측. Host Agent가 아니라 root `rosy-hw-probe`가 쓴 `/run/rosy-boot/hardware.json`을 엄격히 읽는다. `{available, schema:1, measured_at, age_s, stale(600 s 초과), boot_id, devices:[{id, label, bus, state, evidence, product, held_by?, source?}], detail}`. `state` ∈ `ok`·`no_response`·`bus_missing`·`driver_missing`·`needs_human`·`not_measured`. `held_by` 행은 CORE가 토픽 신선도로 판정해 덮고 `source:"topic"`을 단다. 결과가 없으면 200 `{available:false, detail:"장치 점검 결과가 아직 없습니다", devices:[]}`. v1.23: `test`(마지막 부저·램프 시험 `{request_id, action, state ∈ done·busy·unavailable·failed, detail, finished_at}` 또는 `null`), 그리고 `needs_human`인 `buzzer`·`lamp` 행은 기록된 답으로 덮는다 — 들림·보임이면 `ok`·근거 `사람 확인: <이름> <시각>`, 아니면 `no_response`·`사람 확인: 들리지 않음/보이지 않음 · …`, 둘 다 `source:"human"`. 다른 상태의 행은 덮지 않는다 |
| GET | `/api/v1/host/status-summary` | Viewer | D-260 5 (v1.25) — 운용 화면 요약줄. 부팅 표시와 같은 규칙표(`core_common.robot_state`)를 `/run/rosy-boot/boot-status.json`(엄격히 읽음; 없으면 CORE가 응답 중이므로 `CORE_READY`로 보고 `boot.available:false`), `GET /host/hardware`와 같은 덮기를 거친 장치 행, 배터리(채널이 fresh일 때만)와 SAF-005 경고 임계, runtime mode에 적용한다. `{state ∈ booting·failed·caution·ready_held·ready, label(부팅 중·실패·주의·준비됨 — 못 움직임·준비됨), reason, state_line, motion_reason, runtime_mode, boot:{available, stage}, devices:{available, stale, ok, total, problems:[{id, label, state, product}]}, battery:{percent, voltage, warning_percent, low}, temperature_c, todos:[{id, text, device?}]}`. 우선순위 실패 > 주의 > 준비됨 — 못 움직임 > 준비됨, CORE_READY 전은 부팅 중. 할 일은 급한 순서 |
| POST | `/api/v1/host/hardware/refresh` | Admin | D-247 — `/run/rosy/hw-probe.request`를 써서 `rosy-hw-probe.path`가 probe를 다시 돌리게 한다. 10초 안의 재요청은 `{accepted:false}`. 요청 파일을 못 쓰면 503 `HW_PROBE_UNAVAILABLE` |
| POST | `/api/v1/host/hardware/test` | Admin | D-247 6 (v1.23, payload: `{device: "buzzer"\|"lamp"}`, 다른 키 거부) — `/run/rosy/hw-test.request` `{action, request_id, requested_at, by}`를 써서 root `rosy-hw-test`가 부저를 150 ms×3 울리거나 램프를 빨강·초록·파랑 1 s씩 켜게 한다. subprocess 없음. 200 `{accepted:true, request_id, device, detail}`. 10초 안 재요청은 429 `HW_TEST_COOLDOWN`, 요청 파일을 못 쓰면 503 `HW_TEST_UNAVAILABLE`. 결과는 `GET /host/hardware`의 `test` |
| POST | `/api/v1/host/lamp/identify` | Operator | D-472, `{color:"blue"\|"amber"}`. CORE는 식별 요청만 기록하고 `rosy-face`가 IDLE·E-Stop 해제·주의 없음일 때 단독으로 1 s 켬→1 s 끔→1 s 켬을 구동한다. 200 `{accepted:true, request_id, color, state:"pending_visual_confirmation"}`는 영상상 식별 성공을 뜻하지 않는다. 기존 `HW_TEST_COOLDOWN`/`HW_TEST_UNAVAILABLE` 거절을 공유한다. |
| POST | `/api/v1/host/hardware/confirm` | Admin | D-247 6 (v1.23, payload: `{device: "buzzer"\|"lamp", observed: bool}`, 엄격한 bool) — 사람의 답을 `{observed, by(토큰 id), label, at}`로 CORE 상태 디렉터리 `~/.rosy/hw-confirmations.json`(0600, 원자적 교체)에 기록한다. `rosy-hw-test`의 마지막 결과가 같은 장치·`state:"done"`·5분 안에 끝난 것이어야 하며, 아니면 409 `HW_CONFIRM_NO_TEST`. 기록에는 그 시험의 `request_id`가 함께 남는다(파일에만, 응답·카드에는 싣지 않음). 장치마다 마지막 답 하나. 200 `{recorded:true, device, observed, by, label, at}`. 쓰지 못하면 503 `HW_CONFIRM_UNAVAILABLE` |

---

## 5.8 로봇 SSH 접속 (D-418, v1.89)

관리자가 로봇에 SSH로 들어갈 길을 연다. 모든 경로는 **Admin** 전용이다. CORE는 비특권이라(D-161) 직접 적용하지 않는다: `/run/rosy/ssh-access.request`(`{schema:1, request_id, action, requested_at, answer_by, by, ...}`; `answer_by`는 CORE가 기다리기를 멈추는 epoch 초)를 쓰면 root `rosy-ssh-access.path`가 도우미를 깨우고, 도우미가 형식·개수·만료를 **따로 다시 검사**한 뒤 적용하고 `/run/rosy/ssh-access.response`(root:rosy-core 0640)에 답한다. CORE는 그 답을 **최대 10 s** 기다리고(다른 요청의 잠금 대기까지 합한 한 기한), 읽자마자 지운다. 답이 없으면 503 `SSH_ACCESS_UNAVAILABLE`이고 요청 파일은 거둬들인다. `POST /password`가 시간 초과면 CORE가 기다리지 않는 `password_off` 요청을 남기고, 도우미도 `answer_by` 1 s 전을 넘긴 비밀번호는 답에 싣지 않고 되돌린다. 아직 처리되지 않은 그 `password_off`는 덮어쓰지 않고 기한 안에서 처리되기를 기다린다. 답 파일을 못 쓰면 켠 비밀번호를 다시 끈다. 본문이 JSON이 아니면 400 오류 봉투이고 도우미까지 가지 않는다. 시각은 모두 UTC `YYYY-MM-DDTHH:MM:SSZ`. 스키마: `core_common.protocol.schemas`의 `Ssh*` 모델.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/host/ssh/host-keys` | Admin | `{hostname, host_keys:["<type> <base64>", ...]}` — `/etc/ssh/ssh_host_*_key.pub`의 공개키(주석 제외). 등록 도구가 첫 접속 전에 `known_hosts`를 쓴다(TOFU 없음). CORE가 직접 읽는다 |
| GET | `/api/v1/host/ssh/keys` | Admin | `{keys:[{label, type, fingerprint("SHA256:…"), added_at, expires_at, added_by}]}` — 관리 키 목록. 만료가 지난 키는 도우미가 정리하며 `history.jsonl`에 `expire`로 남긴다 |
| POST | `/api/v1/host/ssh/keys` | Admin | payload `{public_key:"<type> <base64> [comment]", label, expires_days:1..365}`, 다른 키 거부. 허용 종류 `ssh-ed25519`·`sk-ssh-ed25519@openssh.com`·`ecdsa-sha2-nistp256\|384\|521`. 라벨 `^[a-z0-9][a-z0-9._:-]{0,47}$`(팀 키 `team:<name>`, 기기 `dev:<name>`). **201** `{label, fingerprint, expires_at}`(만료는 분 단위로 내림). 422 `SSH_INVALID`, 409 `SSH_LABEL_EXISTS`·`SSH_KEY_EXISTS`·`SSH_KEYS_FULL`(32개). `added_by`는 요청한 토큰의 라벨(없으면 토큰 id) |
| DELETE | `/api/v1/host/ssh/keys/{label}` | Admin | **204**. 없는 라벨 404 `SSH_KEY_NOT_FOUND` |
| POST | `/api/v1/host/ssh/password` | Admin | payload `{minutes:1..60}`. **200** `{user:"rosy", password:"<temporary-password>", expires_at}`, `Cache-Control: no-store`. 값의 형식은 접두어 `rosy-` 뒤에 하이픈으로 나눈 4자 세 묶음이다. 비밀번호는 AP 비밀번호와 같은 헷갈리지 않는 31자(`abcdefghjkmnpqrstuvwxyz23456789`)로 `secrets`가 만들고 `chpasswd`(stdin)로 적용한다. 이 응답과 shadow 밖 어디에도(기록·로그·상태 파일) 남지 않는다. 다시 부르면 새 비밀번호·새 만료. LCD에는 아직 보이지 않는다(후속) |
| GET | `/api/v1/host/ssh/password` | Admin | `{enabled: bool, expires_at: "<Z>"\|null, lock_pending: bool}` — 비밀번호는 싣지 않는다. `lock_pending`은 `usermod` 잠금이 실패해 거부 drop-in이 막고 있고 재시도를 기다리는 중 |
| DELETE | `/api/v1/host/ssh/password` | Admin | **204** — 지금 끈다 |

- **관리 키 파일:** `/var/lib/rosy/ssh/authorized_keys`(0644, `keys.json`에서 매번 다시 만든다). 줄 형식 `expiry-time="YYYYMMDDHHMMZ" <type> <base64> rosy-managed:<label>` — 만료는 sshd가 직접 강제한다. sshd는 drop-in `/etc/ssh/sshd_config.d/50-rosy-managed-keys.conf`(`Match User rosy` 안의 `AuthorizedKeysFile .ssh/authorized_keys /var/lib/rosy/ssh/authorized_keys`)로 `rosy` 계정에만 이 파일을 읽는다. `/etc/ssh`는 D-388 이미지 층 밖이라 도우미가 설치·유지한다.
- **메타데이터·감사:** `/var/lib/rosy/ssh/keys.json`·`password.json`·`history.jsonl`(root 0600). 사건: `add`, `revoke`, `expire`, `password_on`, `password_off`(`reason: requested|expired|boot|late|undelivered` — `late`는 `answer_by` 안에 답하지 못해 되돌림, `undelivered`는 답 파일을 못 써서 되돌림), `password_deny`(`usermod` 잠금 실패: 거부 drop-in과 재시도).
- **임시 비밀번호:** 켜면 `/etc/ssh/sshd_config.d/60-rosy-temp-password.conf`에 `Match User rosy Address 10.0.0.0/8,172.16.0.0/12,192.168.0.0/16` → `PasswordAuthentication yes`, `MaxAuthTries 3`, 이어서 `Match User rosy` → `PasswordAuthentication no`(사설 대역 밖은 전역 설정과 상관없이 거부). `sshd -t`가 거부하면 되돌리고 503. 끄기(요청·만료·부팅)는 shadow 필드를 `*`로 먼저 잠그고, drop-in을 지우고, 실행 중인 `ssh.service`를 다시 읽힌다. 만료 검사는 비밀번호가 켜진 동안만 도는 `rosy-ssh-password-expire.timer`(30 s)이고(타이머가 안 켜지면 비밀번호도 켜지 않는다), 부팅 때마다 `rosy-ssh-access-boot.service`가 `sockets.target`·`ssh.socket`·`ssh.service`보다 먼저 끈다(`DefaultDependencies=no`; `ssh.socket`이 켜진 Ubuntu 24.04에서 순서 순환이 없다). 끄기는 다른 정리(키 기록 손상 등)보다 먼저, 따로 돈다. `usermod`가 잠그지 못하면 `Match User rosy` → `PasswordAuthentication no` drop-in으로 sshd가 거부하게 하고 타이머가 잠금을 다시 시도한다. 비밀번호 만료는 벽시계(`expires_at`)나 부팅 시계(`CLOCK_BOOTTIME` 기한과 boot id) 중 먼저 오는 쪽이다. 키 만료는 시계와 지금까지 본 가장 늦은 시각(`clock.json`) 중 늦은 쪽으로 판단한다(RTC 없는 Pi가 과거 시각으로 부팅해도 만료가 되돌아가지 않는다). 시계보다 2일 넘게 앞선 기록은 앞서 간 시계로 보고 버린다. 그래서 시계가 마지막 기록보다 2일 넘게 뒤처진 채로 부팅하면 기록도 버려지고, NTP가 맞출 때까지 키 만료는 뒤처진 시계로 센다(sshd의 `expiry-time`도 같은 시계를 쓴다). NTP 동기는 `timedatectl show -p NTPSynchronized`로 본다. timedated가 커널의 `STA_UNSYNC`를 읽으므로 이미지의 chrony에서도 맞다. 도우미가 직접 `adjtimex`를 부르지 않는 까닭은 단위의 seccomp 필터(`@system-service`, `ProtectClock=true`)가 그 호출을 SIGSYS로 죽이기 때문이다. 동기되면 기록은 시계로 맞춘다. 비밀번호는 boot id를 읽지 못하면 켜지 않는다(503).

---

## 5.9 OMX-AI Gazebo Pilot 전용 API (D-390, v1.70)

오류는 ERR-101의 `{error:{code,message,detail}}` 형식이다. 스키마 오류는 400 `VALIDATION_ERROR`, 인증 없음은 401 `UNAUTHORIZED`, 조종권·상태 충돌은 409 `MODE_CONFLICT`로 돌려준다.

이 경계는 격리된 개발용 Gazebo 컨테이너에서만 제공한다. CORE/Fleet 토큰, 실물 OMX profile, Fleet Action UDS 권한과 분리된다. `/pilot` 정적 화면과 아래 API는 같은 origin이다. 브라우저 명령은 단일 `ArmCommandOwner`를 거쳐 `/arm_controller/follow_joint_trajectory`로 간다.

| Method | 경로 | 요청/응답 |
|---|---|---|
| GET | `/api/v1/sim/omx/target` | 공개 `{kind:"omx_sim",simulation:true,instance_id,joints,gripper,camera,recording,controls}`; `controls`(v1.87 additive, D-411 B)는 §9.1 `rosy.controls/1` — SIM은 `joint_jog` 하나(`id:"arm"`, 관절별 한계 = 고정된 vendor URDF 범위(`omx_f_kinematics.yaml`) ∩ SIM owner 허용 범위, `max_step_rad` 0.05, `duration_s` 0.4 = 각 요청에 보낼 목표 길이, `command:"bounded_goal"`; 이전 목표가 끝난 뒤에만 다음 목표, 100 ms 스트림 없음, D-390 §2). D-411 C부터 그리퍼는 `joint_jog`에서 빠지고 따로 `gripper` 항목(`id:"gripper"`, `joint`, `open`·`closed` = 셀 프로필 `gripper.open`·`gripper.closed`(1.0·0.0 rad), `presets{open, half, close}` — `half`는 가운데, `readback:["position","grasp"]`, `max_velocity` = 셀 프로필과 URDF 그리퍼 속도 중 작은 값(0.5 rad/s))이 된다. SIM owner 허용 범위는 모든 관절(팔·그리퍼)이 `deploy/robot/omx/sim/cell_profile.yaml` 범위 ∩ URDF 범위다(실물 한계 아님, URDF에 없는 관절은 서버 기동 오류). `joint_jog`에 알리는 범위는 그 허용 범위를 양쪽에서 `start_state_tolerance_rad`(0.02 rad)만큼 줄인 것이다 — 알린 끝을 조금 넘어 멈춰도 readback이 허용 범위 안이라 owner가 HOLD(`joint_state_limit`)를 걸지 않는다. 조그는 알린 범위 밖으로 더 나가는 목표를 409 `joint_limit`으로 거절하고, 범위 밖에서 안쪽으로 돌아오는 목표는 받는다. 시뮬레이션 전용이며 실물 OMX를 열지 않는다; Pinky CORE에서는 404 |
| POST | `/api/v1/sim/omx/pair` | 로컬 콘솔의 10분 유효 일회용 `{code}` → `{token}`; 성공 201, 재사용 403 |
| GET | `/api/v1/sim/omx/whoami` | Bearer → `{role:"operator"}` |
| POST/PUT/DELETE | `/api/v1/sim/omx/seat[/{seat_id}]` | 단일 조종권 취득·1초 간격 갱신·반납. lease 10초; 만료/반납 시 진행 목표 취소 요청. 취소 ACK는 정지 증거가 아니다 |
| GET | `/api/v1/sim/omx/state` | `{instance_id,ready,owner_state,owner_reason,action_server_ready,state_sequence,joint_age_ms,positions,active_goal,gripper}`. 신선한 관절 상태와 action server가 없으면 `ready:false`(목표 실행 중에도 `ready:false`·`owner_state:"active"`). `gripper`(v1.87, D-411 C) `{joint, position, state, open, closed, hold_target}`(`hold_target` = 끝난 그리퍼 목표 뒤 팔 목표가 그리퍼 칸에 보낼 명령 값, 없으면 `null`) — `state` ∈ `open`·`closed`·`holding`·`moving`·`unknown`. `unknown` = 관절 상태가 낡았거나 owner HOLD, 마지막 그리퍼 목표가 `UNKNOWN_HOLD`. `moving` = 그리퍼 목표 진행 중이거나 최근 0.5 s 안에 위치가 0.005 rad 넘게 변함. `closed` = 위치가 `closed`에서 0.05 rad 이내. **`holding`** = 닫기 목표(`closed`에서 0.05 rad 이내인 목표)가 `SUCCEEDED`로 끝났는데 위치가 `closed`에서 0.05 rad 넘게 떨어져 멈춤 — 손가락이 무언가에 걸렸다는 시뮬레이션 위치 판정이며 쥠 힘 증거가 아니다(D-390 §5). 그 밖은 `open` |
| POST | `/api/v1/sim/omx/goals` | `OmxSimJog` → `OmxSimGoal`, 202. 같은 `request_id`·동일 payload는 멱등; 다른 payload는 409 |
| POST | `/api/v1/sim/omx/gripper` | v1.87, D-411 C. `OmxSimGripperGoal` → `OmxSimGoal`, 202. 그리퍼만 절대 위치로 옮기는 목표 하나(팔 관절은 현재 readback). 조그와 같은 seat·instance·만료·단일 진행 목표·HOLD 규칙, 같은 영수증 공간(같은 `request_id`를 조그와 그리퍼가 함께 쓰면 409). 위치가 알린 범위(허용 범위에서 0.02 rad 안쪽) 밖이면 409 `gripper_limit`, `|position − readback| − 0.05 rad > max_velocity × duration_s`이면 409 `gripper_velocity_limit`(0.05 rad는 클라이언트가 목표를 잰 readback과 접수 시 readback의 차이를 받는 여유), 그리퍼 목표를 받지 않는 서버는 409 `gripper_not_configured`. 진행·취소는 `/goals/{command_id}` 경로 그대로 |
| GET | `/api/v1/sim/omx/goals/{command_id}` | 비동기 goal readback. 미등록 404 |
| POST | `/api/v1/sim/omx/goals/{command_id}/cancel?seat_id=...` | 취소 요청. `CANCEL_REQUESTED`는 정지 완료가 아니다 |

`OmxSimJog` 필수 필드: `instance_id`, `seat_id`, `request_id`, `joint`, `delta_rad`(0이 아니며 절댓값 ≤0.05 rad), `duration_s`(0.1~1.0), `state_sequence`, `expires_at_ms`. 명령은 현재 관절 상태에서 해당 관절만 상대 이동하며 모든 관절의 현재 값을 함께 보낸다. 최근 5초 안에 Pilot API가 제공하지 않은 sequence, 6초보다 먼 만료 시각, 이미 만료된 요청, 범위 초과, 진행 중 goal, HOLD는 거부한다. ROS는 새 sequence를 계속 발행하므로 제출 시점에는 가장 최근의 신선한 관절 상태를 사용한다. `OmxSimGoal.state`는 `LOCAL_ACCEPTED`, `ROS_ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, `CANCEL_REQUESTED`, `CANCELED`, `UNKNOWN_HOLD` 중 하나다. `LOCAL_ACCEPTED`는 ROS 수락이 아니고, action의 `SUCCEEDED`는 물리적 정지나 목표 도달의 독립 증거가 아니다. schema 정본은 `core_common.protocol.omx_sim`이다.

`OmxSimGripperGoal`(v1.87, D-411 C) 필수 필드: `instance_id`, `seat_id`, `request_id`, `position`(유한한 rad, 절대값), `duration_s`(0.2~2.0), `state_sequence`, `expires_at_ms`. 다른 필드는 거부한다. SIM owner의 목표 길이 상한은 2.0 s다(`OmxSimJog`는 스키마가 1.0 s까지만 받는다). 그리퍼 목표가 `SUCCEEDED`로 끝난 뒤의 팔 조그는 그리퍼 칸에 readback 대신 명령 값을 보낸다(readback을 보내면 쥔 물체를 놓는다). 닫기 목표가 닫힘에 못 미쳐 멈춘 경우(`holding`)에는 **멈춘 위치에서 닫힘 쪽으로 `gripper.preload`(셀 프로필 0.05 rad)만큼** — 닫힘 자체가 아니다(위치 제어에서 닫힘을 명령하면 멈춘 오차 전체로 누른다). 이 값은 목표가 끝난 순간의 readback(없으면 그 뒤 첫 신선한 readback)으로 고정되어 조그마다 더 조여지지 않으며 닫힘을 넘지 않는다. 컨트롤러는 SUCCEEDED 뒤 그 목표의 마지막 점(닫힘 쪽 목표 = 멈춘 오차 전체)을 계속 명령하므로, 서버는 쥐고 있음이 된 닫기 직후 owner가 비면 그리퍼 목표만 `hold_target`으로 옮기는 목표 하나(`command_id` `hold-<닫기 id>`)를 스스로 낸다 — 쉬는 동안의 조임과 팔 조그 중의 조임이 같아진다. 그동안 `owner_state`는 `active`다. ROS 실패·시간 초과로 끝난 그리퍼 목표는 `UNKNOWN_HOLD`(`reason` `terminal_status_<status>_result_<code>`)이며 `holding`으로 읽지 않는다. Pilot은 한 번에 목표 하나를 보내며, 길이는 `거리 / (0.9 × max_velocity)`를 올림해 0.2–2.0 s 안으로 맞추고(0.9는 readback 흔들림 여유), 2.0 s로 못 가는 거리(0.5 rad/s에서 0.9 rad 넘게)는 2.0 s에 닿는 곳까지만 보낸다(다시 누르면 마저 간다). `max_velocity`가 없는 서버에는 전체 행정을 2.0 s로 보고 비례한다. 열림 % 슬라이더는 손을 뗄 때 목표 하나만 보낸다.

v1.70 추가 경로(모두 Bearer 인증):

| Method | 경로 (`/api/v1/sim/omx` 아래) | 요청/응답 |
|---|---|---|
| GET | `/camera` | `{available,fresh,capture_time_ns,sim_time_ns,age_ms,camera_identity,width,height}` |
| GET | `/camera/frame` | 신선한 RGB 프레임의 JPEG, `Cache-Control:no-store`; 결측/오래됨 409 |
| GET | `/recordings` | `OmxSimRecording`: `{status,episode_id,task,task_outcome,frame_count,issues}` |
| POST | `/recordings` | 소유 조종권 `{seat_id,task}` → 기록 상태, 201; 신선한 영상/관절/명령 소유자 필요 |
| POST | `/recordings/{episode_id}/stop` | 소유 조종권 `{seat_id,outcome:success\|failure\|unspecified}` → 기록 상태 |
| GET | `/recordings/{episode_id}/manifest` | 원본 manifest; 미등록/잘못된 UUID 404; 서버 파일 경로 없음 |

기록은 10 simulation FPS 영상과 그 시각 이전 50 ms 이내의 관절 상태, ROS 수락 UUID가 있는 절대 목표(rad)를 묶는다. 영상 신선도 2초와 현재 관절 스트림 신선도 0.5초는 별도다. 지연 영상은 과거 상태와 pair하며 미래 상태를 사용하지 않는다. 프레임 누락/시계 역행/취소/HOLD/조종권 반납·만료/서버 종료/미선택 결과는 `incomplete`이며 export를 거부한다. `success`는 운용자가 지정한 과제 결과이며 Action 성공과 구분한다. 기록은 최대 3000프레임, 저장 위치는 서버 설정으로만 지정한다. 행의 목표 길이는 0.1~2.0 s다. v1.87(D-411 C): 그리퍼 목표를 받는 서버의 에피소드는 출처에 `gripper_joint`를 두고 모든 행에 `action.gripper`(그 행 `action`의 그리퍼 칸과 같은 절대 목표 rad)를 남기며, LeRobot export에 `action.gripper` 특성(`float32`, `(1,)`, `["position_rad"]`)을 더한다. `gripper_joint`가 없는 이전 에피소드는 그대로 검증·export된다. LeRobot 0.4.4 오프라인 변환은 `omx_sim_ros`/rad를 유지하고, 영상 시간축은 index/fps, 실제 Gazebo 시각은 int64 source 필드와 원본 해시로 보존한다. 업로드·학습·정책 실행 API는 없다. 실물 OMX 명령을 이 경로로 보내거나 `omx.disabled.yaml`을 켜서는 안 된다.

## 5.10 Pilot 로봇 녹화 (D-411, v1.83)

녹화 주체는 카메라 유닛(`rosy-camera`)의 `pilot_recorder_node` 다. CORE 는 `std_srvs/SetBool` `pilot_recorder/set_active` 로 시작·정지를 **요청**만 하고, 래치된 `pilot_recorder/status`(`rosy.pilot.recording.status/1`, 1 Hz)를 받아 판단한다. 녹화는 증거일 뿐이며 제어 경로는 이 토픽들을 읽지 않는다(D-2). 스키마 정본은 `core_common.protocol.recording` 이다.

| Method | 경로 | 권한 | 요청/응답 |
|---|---|---|---|
| GET | `/api/v1/recordings` | Viewer | `{active, items[RecordingSummary], download_allowed, download_blocker}` — `active` 는 녹화기 상태(낡았으면 `null`), `items` 는 최신순 `{id, started_at, ended_at, duration_s, bytes, topics, status: recording\|complete\|incomplete, manifest_sha256, fetched}`, `download_blocker` 는 `RECORDING_BUSY`·`ROBOT_MOVING`·`null` |
| GET | `/api/v1/recordings/active` | Viewer | `{active, owned, preview_modes}` — `owned` 는 호출 토큰이 시작한 녹화인가. 신선한 recorder 상태와 설치된 typed start 서비스가 있으면 preview_modes는 raw/annotated, legacy는 raw, 미확인은 [] |
| POST | `/api/v1/recordings` | Operator | optional `{preview_mode:raw\|annotated}`; body 생략은 raw. 임의 key·다른 값·잘못된 타입은 400. 201 실제 `RecorderStatus`(대개 `starting`, 아래); preview_mode는 recorder 확인값이다. 거부: 409 `RECORDING_BUSY`, 507 `RECORDING_QUOTA_FULL`·`RECORDING_DISK_FULL`, 503 `RECORDER_UNAVAILABLE` |
| POST | `/api/v1/recordings/active/stop` | Operator | `RecorderStatus`(대개 `stopping`). `starting`·`recording` 에서 받는다. 시작한 토큰·Admin, 또는 소유자가 없는 녹화(CORE 재시작)면 아무 Operator; 그 밖은 403 `FORBIDDEN`. 없으면 409 `RECORDING_NOT_ACTIVE` |
| GET | `/api/v1/recordings/{id}/archive` | Operator | `application/x-tar` 무압축 USTAR(mcap 은 이미 zstd), `Content-Length` 정확, `Cache-Control: no-store`. 멤버는 `<id>/manifest.json` 다음 manifest 가 적은 파일만. 정지 중에만(409 `RECORDING_BUSY`·`ROBOT_MOVING`), 한 번에 한 수신만(진행 중이면 409 `RECORDING_BUSY`), 없는·안전하지 않은 id 404 `RECORDING_NOT_FOUND`. 수신 중에도 정지 조건을 블록마다 다시 보고, 깨지거나 파일이 계획과 달라지면(링크·교체·크기) 본문을 `Content-Length` 보다 짧게 끊는다. 짧은 본문은 실패이며, tar 는 이어 받을 수 없으므로 나중에 처음부터 다시 받는다 |

- 녹화기 상태 `state`: `idle` · `starting` · `recording` · `stopping` · `error`. `starting`·`recording`·`stopping` 은 `id` 를 싣고, 셋 다 진행 중으로 친다(시작·수신 `RECORDING_BUSY`, 목록의 그 항목은 `status: recording`, 소유자·링크·seat 규칙 적용, 정지 가능).
- `starting`: 시작 요청(201)은 대개 `starting` 을 돌려준다. `ros2 bag record` 는 띄운 뒤 첫 파일을 열기까지 몇 초 걸리고(Gazebo 실측 4.0 s), 그동안은 아무것도 기록되지 않는다. 녹화기는 `<세션>/bag/*.mcap` 이 생기면 `recording` 으로 넘긴다 — 파일 크기는 보지 않는다(mcap 은 zstd 청크·캐시를 닫을 때까지 디스크에 쓰지 않아 20 s 세션 내내 0 바이트였다). rosbag2 는 이 파일을 연 직후 구독한다(실측: 파일 연 뒤 0.2 s 에 첫 메시지, 0.4 s 안에 모든 토픽 구독). 그 순간부터 `elapsed_s` 를 세고, session.json 의 `started_at` 도 그 시각으로 바꾸며(처음 요청 시각은 `requested_at`), manifest `duration_s` 와 600 s 상한도 거기서 센다. 15 s 안에 파일이 없으면 녹화기가 스스로 멈추고 `last_stop_reason: writer_start_timeout` 을 남긴다. `starting` 중 정지는 정상 정지다(`duration_s: 0`). session.json `writer_ready` 는 시작 때 `false`, 파일이 생기면 `true` 이고, `false` 인 채 끝난 세션(`starting` 중 종료·충돌 뒤 복구)의 길이는 0 이다. 운전은 `recording` 이 보인 뒤에 시작한다. 카메라 압축 토픽은 `starting` 부터 켠다(`pilot_recorder/active`). `recording.started` 는 시작 요청이 받아들여진 때(대개 `starting`) 나가며, 기록이 실제로 시작된 시각은 아니다.
- 배포: 카메라 유닛(녹화기)과 CORE 는 함께 올린다. `starting` 은 같은 `rosy.pilot.recording.status/1` 스키마에 새로 더한 값이라, 이전 CORE 는 `starting` 상태를 검증에서 버린다 — 준비 중인 몇 초 동안 마지막 `idle` 을 붙들거나 낡았다고(`RECORDER_UNAVAILABLE`) 보고, 그사이 두 번째 시작도 막지 못한다.
- 녹화본 `id` 의 기기 부분(session.json `device`)은 로봇이다: 노드 파라미터 `device`, 없으면 노드 네임스페이스(장비에서는 `ROSY_NAMESPACE` = `rosy_NN`), 둘 다 없을 때만 호스트 이름. 영숫자·`_`·`-` 만, 48자 이하, `_` 로 끝나지 않는다.
- 한 번에 1개, 최대 600 s. 전용 쿼터(기본 4 GiB, 예비 1 GiB) 안에서 시작하며, 디스크 빈 공간이 512 MiB 이하면 시작하지 않는다. 쿼터를 넘기면 녹화기가 `quota`, 빈 공간이 바닥나면 `disk_full` 로 스스로 멈춘다.
- 정지 뒤 녹화기가 manifest(`rosy.pilot.recording.manifest/1`: 파일별 `{path, bytes, sha256}`, 선택 `bag_returncode`·`writer_killed`)를 작업 스레드에서 쓰는 동안 상태는 `stopping` 이고, 그동안 시작·수신은 `RECORDING_BUSY` 다.
- 토픽: `camera/front/compressed`(녹화 중에만 발행), `cmd_vel`, `odom`, `scan`, `line/observation`, `teleop/intent`.
- CORE 가 스스로 멈추는 경우: 시작 토큰이 `/ws/state` 를 한 번이라도 연 뒤 그 연결이 5 s 넘게 없음(`link_lost`), 다른 토큰의 teleop 이 수락됨(`seat_changed`). `/ws/state` 를 열지 않은 REST 전용 소유자는 `link_lost` 로 멈추지 않는다(600 s 상한은 그대로). 둘 다 비차단 정지 요청이고, `recording.stopped` 는 녹화기 상태가 정지를 확인한 뒤에야 낸다(거부되거나 3 s 안에 확인되지 않으면 다음 상태에서 다시 묻는다). 소유자 없는 녹화(CORE 재시작)가 녹화기 쪽에서 끝나도 `recording.stopped`(`by: null`)를 한 번 낸다. 이벤트는 §8 `recording.started`·`recording.stopped`.
- 녹화기 상태는 `boot_id`(녹화기 기동마다 새 값)와 `seq`(상태를 만들 때마다 증가)를 싣는다. CORE 는 같은 `boot_id` 에서 이미 받은 것보다 오래된 상태(예: 시작 전에 나가 시작 뒤에 도착한 `idle`)를 버린다. `seq: 0` 은 순번 없음.
- tar 의 마지막 바이트가 나간 녹화만 CORE 가 `pilot_recorder/fetched`(`{id}`)로 알리고, 녹화기가 `fetched.json` 을 써 쿼터 정리 대상으로 삼는다. 받지 않은 녹화는 지우지 않는다.
- 저장 위치는 `/var/lib/rosy/pilot-recordings`(설정 `recording.pilot_root`): `rosy-camera` 가 쓰고 setgid `rosy-core` 그룹으로 CORE 가 읽기만 한다.

`teleop/intent`(ROS `std_msgs/String` JSON, `rosy.teleop.intent/1`)는 CORE 가 teleop 판정마다 낸다 — 관리자 앞 거부(capability·보정 lease·keep)도 포함. 싱크 실패는 명령을 거부하지 않는다. 수신 중에도 정지 조건을 블록마다 다시 보고, 깨지거나 파일이 계획과 달라지면(링크·교체·크기) 본문을 `Content-Length` 보다 짧게 끊는다. 짧은 본문은 실패이며, tar 는 이어 받을 수 없으므로 나중에 처음부터 다시 받는다.

| 필드 | 형 | 의미 |
|---|---|---|
| `schema` | str | `rosy.teleop.intent/1` |
| `raw_linear` · `raw_angular` | float\|null | 요청 값(유한하지 않으면 null) |
| `linear` · `angular` | float\|null | 수락 시 클립된 값, 거부면 null |
| `source` | str | 명령 원천(`manual`) |
| `mode` | str | 판정 시점 모드 |
| `accepted` | bool | 수락 여부 |
| `code` | str | 거부 코드, 수락이면 `""` |
| `t_mono_ns` | int | CORE monotonic ns |

## 5.11 Pilot 방 목록 — `GET /api/v1/site/rooms` (D-343·D-432·D-452, v1.98)

브라우저는 mDNS를 직접 수행하지 않는다. CORE는 공용 `_rosy._tcp` event cache를 먼저 읽고, 해당 adapter가 없을 때만 제한된 Avahi fallback을 사용한다.
행은 발견 규칙 v0.1의 공개 정보만 싣는다 — 토큰·비밀은 싣지 않는다(D-193).

| Method | 경로 | 권한 | 요청/응답 |
|---|---|---|---|
| GET | `/api/v1/site/rooms` | 공개 발견 읽기(인증 없음) | `{rooms: [{hostname, address, port, kind, url}]}` — `url`은 그 기기의 pilot 진입(`http[s]://<hostname>:<port>/pilot/#join`; hostname은 정규화된 `.local` FQDN이고 `tls=required`는 HTTPS). 발견 adapter/Avahi가 없거나 실패하면 503 `DISCOVERY_UNAVAILABLE`. `Cache-Control: no-store`. |

행은 미승인 발견 힌트이고 선택 후 해당 origin의 기존 인증·승인을 거친다. 자격을 전달하거나 자동 등록하지 않는다. canonical private IPv4 분류·최대 64행·중복/신원 충돌 제외를 유지한다. fallback은 동시 한 번, 성공/실패 5초 cache, stdout 128KiB, subprocess 4초와 유한 종료/회수 상한을 갖는다. 응답 typed 계약은 `core_common.protocol.schemas.SiteRoomsSnapshot`이다.

---

# 6. WebSocket 프로토콜 (로봇)

## 6.1 `/ws/state` — 상태 스트림

서버가 10 Hz(기본, 설정 가능)로 상태 JSON을 push한다.

```json
{
  "robot_id": "rosy_01",
  "online": true,
  "mode": "NAVIGATION",
  "navigation": "NAVIGATING",
  "map_id": "warehouse_a",
  "pose": { "x": 1.82, "y": 3.21, "yaw": 0.73 },
  "velocity": { "linear": 0.12, "angular": 0.0 },
  "battery": { "percent": 81 },
  "safety": { "estop": false },
  "power": {
    "mode": "STANDBY",
    "presence": "none",
    "info_visible": false,
    "sample_rate_hz": 2.0,
    "last_wake_reason": null,
    "idle_seconds": 412.5,
    "lidar_spinning": false,
    "lidar_ready": false
  },
  "line_follow": {
    "mode": "CAMERA_LINE",
    "state": "TRACKING",
    "source": "CAMERA_LINE",
    "error": -0.214,
    "confidence": 0.82,
    "age_s": 0.04,
    "linear": 0.047,
    "angular": 0.171,
    "reason": "tracking"
  },
  "traffic_policy": {
    "mode": "ENFORCED",
    "state": "WAIT_SIGNAL",
    "reason": "signal_red",
    "enforced": true,
    "map_id": "map_260905_update_v2",
    "scene_revision": "road-scene-v1",
    "policy_revision": "traffic-policy-v1",
    "junction_rule": "signal_controlled",
    "evidence_revision": 42,
    "age_s": 0.04,
    "stop_line_visible": true,
    "stop_line_distance_m": 0.08,
    "crosswalk_visible": true,
    "signal_colour": "RED",
    "signal_confidence": 0.93,
    "signal_conflict": false,
    "signal_source_kind": "camera",
    "signal_head_age_s": null,
    "signal_head_frozen": false,
    "linear_scale": 0.0
  },
  "diagnostics_summary": { "rosy_core": "OK", "nav2": "OK" },
  "seq": 10241,
  "timestamp": "2026-08-29T12:00:00.123Z",
  "evidence": {
    "pose": { "received_at": "2026-08-29T12:00:00.023Z", "evidence": "fresh", "stale_after_s": 2.0 },
    "velocity": { "received_at": "2026-08-29T12:00:00.100Z", "evidence": "fresh", "stale_after_s": 0.5 },
    "battery": { "received_at": "2026-08-29T11:59:58.000Z", "evidence": "delayed", "stale_after_s": 5.0 },
    "navigation": { "received_at": "2026-08-29T12:00:00.000Z", "evidence": "fresh", "stale_after_s": 2.0 },
    "safety": { "received_at": "2026-08-29T12:00:00.110Z", "evidence": "fresh", "stale_after_s": 0.2 },
    "docking": { "received_at": null, "evidence": "disconnected", "stale_after_s": 2.0 }
  }
}
```

`GET /api/v1/robot/state` 도 같은 스냅샷이다.

`localization` 은 v1.69 additive 다(D-395). v1.72 부터 CORE 가 로봇 sensing 노드의 `localization/state` 토픽으로 채운다(D-395 P2-1). 그 토픽이 한 번도 오지 않은 로봇(D-395 이전)은 `null` 이다. 토픽이 3 s 끊기면 CORE 는 `state: UNKNOWN`, `reason: state_stale` 로 내린다(닫힌 실패).

```json
"localization": {
  "state": "LOCALIZED",
  "pose_frame": "map",
  "confidence": 0.93,
  "reason": null,
  "needs_human": false,
  "request_id": "rosy_01-7",
  "unmapped_objects": [{ "x": 0.62, "y": -0.08 }],
  "objects_stamp": 1834.5
}
```

- `state`: `UNKNOWN` \| `CANDIDATES` \| `LOCALIZED` \| `SUSPECT`. 로봇이 소유한다. 전원 투입은 항상 `UNKNOWN` 이고 자율 주행은 `LOCALIZED` 에서만 한다.
- `pose_frame`: 같은 스냅샷 `pose` 의 프레임, `map` \| `odom`. CORE 가 map→base TF 를 2 s 넘게 못 읽어 `pose` 에 odom 을 대신 쓰는 동안에는 로봇이 `map` 이라 해도 `odom` 이다(v1.72). CORE 는 `odom` 을 `map` 으로 올리지 않는다. Fleet 교통정리·bays 는 `odom` 이거나 `LOCALIZED` 가 아닌 자세를 쓰지 않는다(D-395 10항).
- `confidence`: 스캔/지도 적합도 0–1. `reason`: SUSPECT 사유(`pickup`, `fit_drop`, `inject_rejected`, `fleet_monitor`), 또는 `CANDIDATES` 에서 결정의 3 s 주입 검사가 도는 동안 `checking`(`core_common.protocol.localization.CHECKING`; Fleet 사다리는 멈추고 CORE 는 미션을 `busy` 로 거부한다, D-395 S1 재실행 R6). `needs_human`: 사다리 시간 초과. `request_id`: 진행 중인 후보 보고의 id.
- `unmapped_objects`(v1.75, 선택, ≤16, 기본 `[]`): `LOCALIZED` 로봇의 LiDAR 가 전체 스캔에서 지도로 설명하지 못한 물체 `{x, y}`(base_link, 앞 x·왼쪽 y, m; 자기 차체 안쪽은 뺀다). `objects_stamp`(v1.74, 선택): 그 스캔의 로봇 시각 s. 시계가 동기되지 않으므로 Fleet 은 스캔을 구별하는 데만 쓰고 신선도는 처음 본 때부터 잰다. `LOCALIZED` 밖에서는 빈 목록이다(후보 물체는 `CandidateReport` 에 실린다). CORE 는 그대로 넘기되 `pose_frame` 이 `odom` 이거나 상태가 끊겨 `state_stale` 이면 둘 다 비운다. Fleet 감시(D-395 9항, 개정 4 5항 후속)가 닻 로봇의 보고 자세로 이 물체를 놓아 다른 `LOCALIZED` 로봇의 거울 잠금을 잡는 데 쓴다.

`safety_policy` 는 v1.71 additive 다(D-400). 공급자가 없거나 공급자가 실패하면 `null` 이다(CORE 가 실패를 로그에 남긴다). 같은 블록이 Fleet 하트비트의 상태 스냅샷에도 실린다. `safety` 는 e-stop 요약, `safety_policy` 는 D-400 정책 모드·그림자 기록이다.

```json
"safety_policy": {
  "mode": "shadow",
  "mode_effective": "shadow",
  "mode_error": "",
  "revision": "abcd1234abcd1234",
  "sources": { "lidar_yaw_offset": "unused while lidar_use_tf (TF = URDF nominal); line_follow uses: line_follow lidar_forward_deg (hand value; no accepted mount)" },
  "shadow": {
    "counts": { "allow": 312, "limit": 4, "stop": 1, "unavailable": 0 },
    "last_stop": { "t": 1843.512, "reason": "pickup", "source": "navigation" },
    "last_unavailable": null,
    "eval_ms": { "p50": 0.4, "p99": 1.1, "n": 317 },
    "dropped_events": 0,
    "suppressed_events": 2,
    "record_errors": 0
  }
}
```

- `mode`: `off` \| `shadow` \| `enforce`. `mode_effective`: 실제로 도는 모드(그림자 워커가 못 뜨면 `off`). `mode_error`: 그림자 워커가 시작하지 못한 이유(예외 종류: 메시지), 없으면 빈 문자열. 설정 오류는 CORE 시작을 막으므로 여기 나타나지 않는다.
- `revision`: 워커 파라미터 해시 16자. `sources`: 키별 값의 출처.
- `shadow`: `{counts, last_stop, last_unavailable, eval_ms{p50,p99,n}, dropped_events, suppressed_events, record_errors}`. `shadow` 가 없으면 `null`. `last_stop`·`last_unavailable` 은 `{t, reason, source}` 또는 `null`, 기록이 없으면 `eval_ms.p50`·`p99` 는 `null`.
- 시각 `t` 는 CORE monotonic 초이며 벽시계가 아니다.

`activity` 는 v1.68 additive 다(D-321 부록). 보정 세션 lease 가 살아 있는
동안만 객체이고, 아니면 `null` 이다.

```json
"activity": {
  "kind": "CALIBRATING",
  "session_id": "3f9c1a0b7d2e4c55",
  "calibration_kind": "drive",
  "label": "주행 보정",
  "owner": { "id": "a1b2c3d4e5f6", "role": "operator", "label": "pilot tablet" },
  "started_at": "2026-10-01T09:00:00+00:00",
  "remaining_s": 24.5
}
```

화면(Pilot·대시보드·LCD 얼굴)은 이 값이 있으면 "보정 중 — <label>" 을 보여야
한다. `owner.id` 가 자기 토큰(`/auth/whoami` 의 `id`)이 아니면 주행 조작을
사유와 함께 끄고, E-Stop 은 켜 둔다. `remaining_s` 는 마지막 heartbeat 로부터
남은 lease 시간이다.

보정 lease 규칙 (D-321 부록, v1.68):

- **소유는 토큰 단위다.** 같은 사람이라도 다른 토큰(다른 기기·재발급)은 owner 가
  아니다. 회수·만료·로그아웃된 토큰의 lease 는 즉시 풀리지 않고 `ttl_s` 가 지나야
  만료된다 — 더 기다릴 수 없으면 Administrator 가 `DELETE` 한다.
- **시작 조건:** 모드가 IDLE 또는 MANUAL 이고 navigation·mapping·도킹·line-follow·
  swarm follow 가 돌고 있지 않을 때만 연다. 아니면 409 `MODE_CONFLICT`.
- **비소유자에게 막히는 쓰기(409 `CALIBRATION_ACTIVE`):** teleop, `/mode`(IDLE 제외),
  line-follow 모드(OFF 제외)·hold, navigation goal·home, `/api/v1/do` 의 같은 동사,
  docking dock·undock, swarm follow, `PUT /safety/limits`(Admin 포함),
  `POST /localization/initialpose`, `/slam/start`·`stop`·`reset`, `POST /power/mode`,
  그리고 `POST /host/release/install`·`/release/rollback`·`/reboot`(Admin 이
  `override_calibration: true` 를 보내면 통과 — CORE 가 재시작되어 보정이 끝난다).
  `/ws/swarm/reference` 는 비소유자 프레임을 조용히 버린다.
- **열려 있는 것:** `POST /safety/stop`(Viewer 포함), `/mode` IDLE, line-follow OFF,
  navigation·swarm·docking cancel, `/do` stop, `/power/wake`, `/slam/save`.
- **배터리 복귀는 lease 를 보지 않는다.** SAF-005 `battery_critical_policy:
  RETURN_HOME` 은 CORE 내부 경로(`nav.home(source="battery_policy")`)로 가며 일부러
  막지 않는다 — 방전 보호가 보정보다 앞선다.
- Pilot 은 자기가 MANUAL 을 잡은 적이 있고 남의 보정으로 잠겨 있지 않을 때만 나가면서
  `/mode` IDLE 을 보낸다.

`line_follow` 는 v1.10 additive 다. `state` 는 `OFF | WAITING | TRACKING |
HOLD | LOST | RECOVERING`(v1.74; D-407 후진, D-468 로컬 차선 복귀 `lane_return_*`, D-476 예상 도로 bridge `lane_bridge` 이동 중에만) 이며 `LOST` 는 모드를 `OFF` 로 바꾼 뒤 다시 선택하기 전까지
해제되지 않는다. 선택되지 않은 소스, 신뢰도 미달, 원본 센서 시각 기준 stale,
형식 오류는 모두 선속도·각속도 0으로 fail-closed 된다. `linear` 는 이 모드의
별도 상한 0.10 m/s를 넘지 않는다(D-143).

`traffic_policy` 는 v1.11 additive 다. `mode` 는 `DISABLED |
MONITOR_ONLY | ENFORCED`, `state` 는 `DISABLED | FOLLOW | APPROACH |
STOP_REQUIRED | WAIT_SIGNAL | PROCEED | HOLD` 다. `ENFORCED`에서는 stale,
신호 충돌, map/scene revision 불일치, 거리 미확정이 모두 0 명령을 만든다.
정지선에서는 신호색과 무관하게 먼저 완전 정지와 dwell을 완료한 뒤, 신뢰도
기준을 통과한 `GREEN`만 `PROCEED`를 허용한다. `MONITOR_ONLY`는 같은 판정을
표시하지만 주행 후보를 변경하지 않는다. `junction_rule`은 v1.54 additive다.
`signal_controlled`(기본)는 위 동작 그대로다. `stop_and_go`는 무신호 교차로
선언이다 — 완전 정지와 dwell을 마친 뒤 신호가 관측되지 않으면
`PROCEED / unsignalized_proceed`로 `proceed_speed_scale` 속도로 진입하고,
신호가 관측되면(약한 오탐 포함) `HOLD / signal_unexpected`로 정지한다. 이 값은
운영자의 씬 선언이지 카메라의 부재 판단이 아니다
(`docs/plans/2026-09-29-traffic-policy-unsignalized-junction-design.md`).
`signal_source_kind`·`signal_head_age_s`·`signal_head_frozen`은 v1.56 additive다
(D-337). 운영자가 파일 설정(`traffic_policy.signal_observer` = `{url, roi_map,
timeout_s}`, `~/.rosy/rosy.yaml` 오버레이 — stage 대상이 아니다)으로 관측 서비스의
읽기 전용 `GET /observed`(측정된 빛)를 묶으면 정지선 판정이 그 증거를 카메라와
함께 쓴다. `fused`는 관측 증거가 유효한 동안만 표기되고, 소스 불일치는
`signal_source_conflict` HOLD, 소등·부정은 `signal_dark` 진입 불허, 침묵(503·동결·
debounce 미확정·stale)은 카메라 단독으로 강등되며 그 전환마다
`nav.traffic_policy_signal_source_stale` 경보가 1회 발행된다. 미설정 사이트는 값이
`camera`·`null`·`false`로 고정되고 동작은 v1.54와 같다.

카메라 preview는 v1.12 additive다. Control은 인식 오버레이가 포함된 bounded JPEG를
최대 2 FPS로 만들고 CORE는 최신 한 장만 보관한다. 대시보드는 Viewer 토큰으로
`status`를 먼저 조회한 다음 sequence가 바뀐 경우에만 `frame`을 가져온다. 프레임이
`preview_stale_after_s`를 넘으면 CORE는 이미지를 제공하지 않고 관제 화면은 `STALE`로
전환한다. raw frame은 `/ws/state`, Fleet, Games 또는 명령 경로에 포함하지 않는다.

`GET /api/v1/vision/front/status` 응답 예:

```json
{
  "available": true,
  "stale": false,
  "source": "GAZEBO",
  "frame_id": "front_camera_link",
  "captured_at": 42.25,
  "age_ms": 80,
  "width": 640,
  "height": 360,
  "overlay": "semantic-road-v1",
  "sequence": 7,
  "quality": null
}
```

CORE-only 런타임(`runtime_mode: core`, D-161)에서 한 번도 값이 오지 않은 채널은 출처가 구성되지 않은 것이므로 `unavailable` 이다 — `disconnected` 는 출처가 있는데 값이 오지 않는 경우에만 쓴다. 첫 표본이 오면 보통 판정으로 돌아간다(v1.18).

`evidence` 는 v1.8 additive 다. 채널별 `{received_at, evidence, stale_after_s}` 이며, `evidence` 는 서버가 판정한 `fresh` | `delayed` | `disconnected` | `unavailable` 이다. 판정에 쓴 임계값(`stale_after_s`)도 같이 실는다. 클라이언트는 임계값을 다시 계산하지 않고 이 문자열을 그대로 표시·게이트한다. 알 수 없는 채널 키는 무시한다(API-002). `PROTOCOL_VERSION`(envelope 1.0)은 바꾸지 않는다.

Camera preview transfer rules (v1.12, D-152):

- v1.102 운전자 MJPEG 스트림(D-368): `GET /api/v1/vision/front/stream` 는 최신 프레임 저장소에서 **새 sequence가 들어올 때만** 파트를 내보낸다(multipart, boundary `frame`). 받을 수 있는 사람은 **현재 운전자 한 명** — 조종 소유권은 좌석 임대가 아니라(D-460) 가장 최근 수락된 teleop의 토큰이다. 운전자가 없거나 다른 토큰이면 409 `CAMERA_STREAM_NOT_DRIVER`, 스트림은 동시에 하나만 열린다(409 `CAMERA_STREAM_BUSY`). 다른 토큰의 teleop가 수락되면 열린 스트림은 끝나고 슬롯이 비며, 클라이언트 끊김도 슬롯을 돌려놓는다. 인증은 `Authorization` 헤더로만 하고 토큰을 URL에 두지 않는다(D-193) — 브라우저 `<img>` 는 헤더를 못 보내므로 클라이언트는 `fetch()` 스트림을 잘라 그린다. 발행 주기 상향(기본 12 fps)은 ROS-SIM/DEVICE 단계의 로봇 측 사항이며 이 경로 계약에 속하지 않는다.

- v1.91 `raw_available`와 `raw_sequence`는 같은 capture stamp·frame_id·크기의 원본이 있는지 표시한다. raw_sequence는 대응 주석 sequence와 같다. `GET /front/frame?sequence=S&overlay=false`는 원본, 생략/true는 주석 JPEG이며 Variant(raw/annotated)·Frame-Id·Captured-At·Sequence 응답 header로 구분한다. 최근 최대 4개 frame 쌍을 보관하고 source image age와 monotonic 수신 TTL을 2초로 제한한다. 한 viewer의 같은 pair는 각 variant를 한 번만 가져올 수 있으며 둘이 한 admission을 공유한다. 반복 variant/400ms 안의 다음 pair는 429, 교체되어 짝을 확인할 수 없으면 409, 없거나 낡은 raw는 404이다. 원본 요청을 주석으로 대체하지 않는다.
- `quality_age_ms`는 source image age + monotonic 수신 나이이며 얼굴 조명 보조 handover도 이 나이에 파일 전달 나이를 더해 만료한다. source clock이 없거나 잘못되거나 image age가 0..2초 밖이면 조도는 null이고 raw pair로 채택하지 않는다. 기존 주석 JPEG 표시 경로는 유지한다.
- 브라우저 video evidence는 optional `preview_mode`(raw/annotated)와 `pair_group_id`(소문자 32 hex)를 함께 제공한다. annotated 저장은 같은 group·started_at·stopped_at·frame_count의 raw가 먼저 저장돼야 한다. 두 파일은 별도로 보존하며 서버가 `annotation_origin=none` 또는 `model_unreviewed`를 붙인다. 모델 주석은 사람이 검토한 라벨이 아니다. legacy 영상의 출처가 없으면 새 provenance 필드는 null이다.

- v1.90 `quality`는 원본 픽셀의 조도 관측 `{valid:false, reason:"low_light"|"overexposed"}` 또는 `{valid:true, reason:"usable"}`이며 물체·차선 판정이나 이동 허가가 아니다. legacy·잘못된 metadata·2초를 넘긴 원본 촬영·수신은 null이다. 저조도·과다 노출에서도 JPEG는 보이며 CAMERA_LINE 관측은 visible=false/confidence=0으로 무효화되어 즉시 정지, 지속 시 기존 LOST 재선택을 요구한다. 저조도 조명 보조는 `low_light`에만 허용하며 `overexposed`에서는 해제한다. LiDAR·IR 안전 기준은 유지한다.

- Both `status` and `frame` responses are `Cache-Control: no-store`.
- A client MUST request
  `GET /api/v1/vision/front/frame?sequence={status.sequence}`. If the latest
  frame advanced between the two calls, CORE returns
  `409 CAMERA_FRAME_ADVANCED`; the client refreshes status instead of pairing
  old metadata with new JPEG bytes.
- Omitting `sequence` fails request validation with `400 VALIDATION_ERROR`.
- CORE returns `429 CAMERA_RATE_LIMITED` when the same authenticated token
  successfully pulls frames less than 400 ms apart. A sequence mismatch is
  checked first and does not consume this allowance.
- `captured_at` is the ROS/source capture clock. `age_ms` is the independent
  local receipt age used for freshness; the dashboard displays both.
- Successful JPEG responses include `X-Rosy-Camera-Sequence`,
  `X-Rosy-Camera-Captured-At`, and `X-Rosy-Camera-Source`.

Operator camera capture (v1.39): `/console`의 카메라 화면은 인증된 preview JPEG만 최대 2 FPS로 기록한다. 스크린샷은 해당 JPEG 그대로, 영상은 브라우저 canvas의 녹화 형식(WebM 또는 MP4)으로 만든다. 조작 기록은 정해진 운전·도킹·정지 API의 작업 이름, 요청 접수/실패, 녹화 시작 후 경과 시간만 포함하며 토큰·명령 본문·IP를 포함하지 않는다. 화면에서 `이 PC`, `로봇 SD`, `PC와 로봇 SD`를 고를 수 있다. PC 저장은 브라우저 다운로드이며 CORE 저장 API를 호출하지 않는다.

로봇 SD 저장의 `POST` 본문은 `application/octet-stream`: little-endian unsigned 32-bit JSON 길이(최대 32,768바이트), UTF-8 JSON, 미디어 바이트 순서다. JSON은 `schema_version:1`, `kind:screenshot|video`, `mime_type`, 저장 또는 시작·종료 UTC 시각을 포함한다. screenshot은 `saved_at`, `sequence`, `source`, video는 `started_at`, `stopped_at`, `frame_count`와 최대 200개의 `{action,result,elapsed_ms}` 항목을 요구한다. JPEG는 1 MiB, 영상은 64 MiB, 전체 저장 미디어는 512 MiB 상한이며 CORE의 HOME 아래 `captures/`에 원자 기록한다(네이티브 `/var/lib/rosy/core/captures`, 컨테이너 `/var/lib/rosy/captures`). 한도를 넘으면 413/507로 실패하고 부분 파일은 삭제한다. 저장 응답은 `{id,kind,file_name,mime_type,bytes,sha256,created_at}`이다. 이 기능은 Control의 고속 원본 영상 캡처나 장치 카메라 활성화를 의미하지 않는다.

## 6.1.1 Vision `DetectionEvidence` (v1.9 additive, D-137)

검출기는 박스를 보고, 움직일지는 정하지 않는다. 한 프레임의 증거:

```json
{ "model_revision": "yolo11n-r1", "observed_at": 1000.0, "seq": 41,
  "input_width": 640, "input_height": 640, "input_fps": 10.0,
  "inference_ms": 12.3,
  "detections": [
    { "label": "person", "x": 0.4, "y": 0.3, "w": 0.2, "h": 0.4,
      "confidence": 0.8, "track_id": 3 }
  ] }
```

- 박스 좌표는 입력 프레임 정규화(0..1)다. `model_revision`은 가중치+입력 규격을
  묶는다(D-47 패턴) — 모르는 revision은 fail-closed.
- 신선도 상한 300 ms(D-136). 빈 `detections` + 전진 `seq`는 "없음"이고,
  `seq` 점프는 "놓침"이다 — 둘을 혼동하지 않는다.
- `inference_ms` 는 생산 측이 report하는 추론 지연(ms)다 — 선택 필드이고
  없어도 패킷은 유효하다 (v1.11 additive).
- 자문 전용이다. 이 증거 하나로 정지·해금을 만들지 않는다(SAF-006, D-137).
- D-423 `object_detector_node` 는 같은 필드를 ROS 토픽 `vision/detections` 에 내고, 검출마다
  거리를 담은 추가 목록 `ranges`(`detections` 와 같은 순서, 항목 `{m, s}` 또는 `null`; `m` 카메라
  앞 미터, `s` `L` LiDAR·`G` 바닥 평면)를 붙인다. CORE 는 이 토픽을 구독하지 않는다(CORE 의 자문
  입력은 `detection_evidence`). `DetectionEvidence` 파서는 `ranges` 를 무시한다.

클라이언트→서버 선택 메시지(WS Teleop, Operator 권한):

```json
{ "type": "teleop", "linear": 0.1, "angular": -0.2 }
```

WS Teleop에도 Watchdog·감사 로그가 동일 적용된다(SAF-002).

## 6.2 `/ws/events` — 이벤트 스트림

구독 필터: `?types=nav.*,safety.estop` (콤마 구분, `*` 와일드카드).

서버 메시지는 EVT-001 이벤트 모델 그대로 전송한다. 연결 끊김 후 재구독 시 `since_seq`로 갭을 보정한다(EVT-003).

---

# 7. Fleet ↔ Robot 프로토콜 (WS + REST)

로봇이 Fleet WS endpoint(`wss://fleet:8081/ws/robots`)에 **outbound 접속**한다(ADR-D-5).

## 7.1 Envelope (PRT-001)

모든 WS 메시지의 공통 포장:

```json
{
  "protocol_version": "1.0",
  "msg_id": "uuid",
  "correlation_id": "uuid|null",
  "type": "hello|heartbeat|event|command|ack|error",
  "ts": "2026-08-29T12:00:00.123Z",
  "payload": { }
}
```

## 7.2 핸드셰이크 (PRT-002)

접속 후 로봇이 첫 메시지로 전송:

```json
{ "type": "hello",
  "payload": { "robot_id": "rosy_01", "pairing_token": "pt_xxx",
               "api_versions": ["v1"], "protocol_version": "1.0" } }
```

추가 선택 필드(additive, 없어도 유효): `device_uid`, `device_name`, `model`, `hardware_serial`.

Fleet 응답: `welcome`(성공, 장기 토큰 발급) / `error(PAIRING_INVALID)`.

## 7.3 Heartbeat (PRT-003)

로봇 → Fleet, 1 Hz:

```json
{ "type": "heartbeat",
  "payload": { "state_snapshot": { "...": "/ws/state 스키마 동일" } } }
```

## 7.4 이벤트 전달

로봇은 내부 이벤트(EVT-001)를 `type: "event"`로 Fleet에 실시간 forward한다. 재접속 시 로봇은 미전송 이벤트를 `since_seq` 기준으로 재전송한다(PRT-005).

## 7.5 명령 및 추적 (PRT-004)

명령은 **REST**(Fleet → 로봇 §5 API)로 전달하고, WS는 추적 보조로 사용한다.

```text
Fleet → Robot (REST):  명령 헤더에 X-Correlation-Id 부여
Robot → Fleet (WS):    { "type": "ack", "correlation_id": "...",
                         "payload": { "status": "ACCEPTED|STARTED|COMPLETED|FAILED",
                                      "error": "..." } }
```

Fleet 추적 타임아웃(기본 10초) 내 ack 없으면 Fleet 기록에 `COMMAND_TIMEOUT`을 남긴다.

> **상태 (v1.15, ADR D-170)**: 위 추적 흐름의 **로봇 측 구현**(ack 송신,
> `correlation_id` 설정·소비, 로봇 ACK의 실행 상태와 Fleet 추적 레코드)는
> 중앙 Fleet 서버 착수와 함께 제공된다(D-297). `TIMEOUT`은 Fleet 기록
> 전용이며 로봇 `AckPayload`에 추가하지 않는다(D-215).
> 이 보류는 PRT `Envelope.correlation_id`와 `AckPayload`의 설정·소비에
> 적용된다. D-316의 Site Fleet Pinky navigation 경로는 별도 REST
> `GoalRequest.correlation_id`와 CORE navigation event data를 사용하며,
> PRT envelope/schema/version은 바꾸지 않는다.

## 7.6 재접속 (로봇 측 의무)

- Exponential backoff: 1s → 2s → 4s → ... 최대 30s
- `fleet.discovery`를 설정한 로봇은 재접속마다 예상 `.local` 호스트의 `_rosy-fleet._tcp` 광고를 조회하고 별도 설치된 사이트 CA로 TLS health를 확인한다. mDNS 광고만으로 토큰을 발급하거나 연결 대상을 바꾸지 않는다. 승인된 `fleet.pairing_token`이 없으면 Agent를 시작하지 않는다.
- 재접속 즉시 `hello` → 마지막 전송 `seq` 이후 이벤트 재전송
- 접속 단절 시 SAF-003 정책 적용 (D-419, v1.86): Agent 가 돌고 있고, 링크가 끊긴 순간 Fleet 주행 목표(`correlation_id` 가 있는 `POST /navigation/goal`)가 진행 중이었으며, 그 목표가 그대로인 채로 `safety.fleet_loss_timeout_s` 동안 계속 끊겨 있으면 한 번 적용한다. 로컬 목표·teleop·swarm follow(SWM-004 가 따로 지킴)·끊긴 뒤 들어온 목표는 대상이 아니다. `STOP` 은 그 목표 취소(e-stop 아님), `HOLD` 는 같은 정지에 재개용 목표 기록(자동 재개 없음), `RETURN_HOME` 은 취소 뒤 `__home__` 귀환(home 이 없거나 `LOCALIZED` 가 아니면 선 채로 `applied: STOP`), `CONTINUE` 는 이벤트만. 재접속은 아무것도 재개하지 않는다. 링크가 살아 있다는 것은 허브 `welcome` 을 받은 뒤이고 마지막 허브 수신이 링크 신선도(1 s 하트비트 주기 + `fleet.heartbeat_reply_timeout_s` + 0.5 s) 이내라는 뜻이다 — 판정 시간과 따로다(설정 여부는 기동 설정으로 정하고, 뒤에 Agent 가 hello 거부·중지로 꺼져도 끊긴 링크로 본다). 하트비트 답이 `fleet.heartbeat_reply_timeout_s`(기본 2 s) 안에 오지 않으면 로봇이 소켓을 끊는다(반쯤 열린 TCP). 하트비트에 대한 `error` 답(예: `TASK_PROJECTION_UNAVAILABLE`)도 답이라 링크를 유지하고, `PAIRING_INVALID`·`SESSION_NOT_PAIRED`·`DUPLICATE_IDENTITY`·`IDENTITY_DRIFT`·`PROTOCOL_UNSUPPORTED` 가 하트비트에 대한 답이면 세션을 즉시 끝낸다(`PAIRING_INVALID` 는 언제나). `event` 에 대한 `error` 는 이벤트 거부로 기록하고 세션을 유지한다. SAF-003 은 허브 건강이 아니라 링크 생존을 판정한다. hello 답 시한은 D-407 의 5 s(링크는 `welcome` 전까지 끊긴 것이라 SAF-003 판정에 영향 없음). `event` 에 대한 `error` 는 D-407 규칙대로 `EVENT_NOT_AUDITABLE` 이면 버리고, 다른 코드면 최대 3 번까지 다시 보낸다. 답을 기다리는 `event` 는 한 번에 8 개까지만 보낸다 — 재접속 뒤 밀린 이벤트가 하트비트 답을 시한 밖으로 밀어내지 않게. 단절은 마지막 허브 수신부터 잰다 — 답 하나를 놓친 기본 설정에서 정책은 마지막 수신 뒤 5 s. 재접속 backoff 는 세션이 하트비트 답 3 개를 받은 뒤에만 1 s 로 돌아간다. 취소가 그 목표를 찾지 못하면 `applied: NONE`·`reason: goal_changed`

## 7.7 프로토콜 버저닝 (PRT-006)

`MAJOR.MINOR`. MINOR는 추가 전용. Fleet이 로봇보다 낮은 버전만 지원하면 Fleet 지원 최고 MINOR로 통신한다.

## 7.8 Leader Pose Stream (Swarm, SWM-003)

Leader 로봇 → Fleet ≥10 Hz, Fleet → Follower 릴레이 ≥5 Hz. envelope `type: "pose"`(v1.1 추가).

```json
{ "protocol_version": "1.0", "msg_id": "...", "type": "pose",
  "ts": "2026-08-29T12:00:00.123Z",
  "payload": { "robot_id": "rosy_01", "pose": { "x": 1.1, "y": 0.5, "yaw": 0.2 }, "seq": 8123,
               "map_id": "site_a" } }
```

Follower의 rosy_core은 스트림 수신 여부를 `stream_timeout_ms`(기본 1000 ms)로 감시하고 단절 시 SWM-004 정책(HOLD)을 적용한다.

`map_id` 는 v1.7 additive 다. 좌표만으로는 받는 쪽이 그것이 자기 맵의 좌표인지 알 수 없고,
다른 맵의 리더를 따라가면 그럴듯해 보이는 엉뚱한 지점으로 간다 — 웨이포인트가 MAP-002 로
막는 것과 같은 사고다. 팔로워는 **양쪽 다 값이 있고 서로 다를 때만** 거부하고, 목표를 거둔 뒤
`swarm.hold`(`reason: map_mismatch`)를 한 번 낸다. 대형은 끝나지 않으므로 리더가 우리 맵으로
돌아오면 새 `follow` 없이 이어진다. 필드가 없는 프레임은 그대로 따라간다 — 이 필드를 모르는
릴레이가 계속 동작해야 하기 때문이다.

로봇은 이 envelope 을 쓰는 소켓 두 개를 직접 제공한다(D-31). Fleet 이 가운데 서지 않아도 군집이 성립하고,
Fleet 이 들어오면 같은 envelope 을 중계하므로 어느 쪽 끝도 바뀌지 않는다.

| Path | Role | 방향 | 요구사항 |
|---|---|---|---|
| `WS /ws/swarm/pose` | Viewer + capability `swarm.lead` | 로봇 → 밖 | SWM-003 리더 pose 스트림. ≥10 Hz 는 하한이며 설정으로 낮출 수 없다 |
| `WS /ws/swarm/reference` | Operator | 밖 → 로봇 | 팔로워의 참조 pose 입구 (SWM-007). 형식이 어긋난 프레임은 버리고 소켓은 유지한다 |

인증은 AUTH-101 첫 메시지 방식이다(Fleet 도 D-370 S7 부터 `?token=` 을 쓰지 않는다).

close code: `4401` 은 토큰이 없거나 틀린 것(`/ws/state` 와 동일), `4403` 은 인증은 됐지만 허용되지 않는 것 — 역할이 모자라거나 capability 가 그 기능을 선언하지 않은 경우(CAP-003)다.

## 7.9 Fleet 보조 위치 확정 모델 (D-395, v1.69 스키마만)

원천은 `core_common.protocol.localization` 이다. v1.69 는 모델만 고정했고, v1.72(D-395 P2-4)에서 전송이 열렸다. Fleet 은 `GET /api/v1/localization/candidates` 로 `CandidateReport` 를 읽고 `POST /api/v1/localization/decision` 으로 `LocalizationDecision` 을, `POST /api/v1/localization/suspect` 로 의심을 보낸다(§5.3, capability `LOCALIZE_ASSIST`, §2). CORE 는 결정을 ROS `localization/decision` 에 `{decision, received_s}`(`received_s` 는 CORE 가 받은 ROS 시각)로 싣고, 로봇의 `localization/result` 는 이벤트 `localization.result` 로 나온다(§8). 토픽 계약은 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §1 이다. Fleet 이 결정을 보낸 뒤 확인할 곳은 다음 스냅샷의 `localization` 과 그 이벤트다.

| 모델 | 방향 | 필드 |
|---|---|---|
| `CandidateReport` | 로봇 → Fleet | `robot_id`, `request_id`(1–64자 `[A-Za-z0-9_.:-]`), `candidates[1..8]` `{x, y, yaw, scan_fit 0–1, paint_score 0–1\|null}`(map 프레임 base_link), `unmapped_objects[≤16]` `{x, y}`(base_link, 앞 x·왼쪽 y), `square_sightings[≤4]` `{bearing_rad, range_m>0\|null, confidence 0–1}`, `pickup`, `stamp`(로봇 시각 s) |
| `LocalizationDecision` | Fleet → 로봇 | `request_id`, `candidate_index`(0–7) **또는** `pose {x, y, yaw}` 중 정확히 하나, `source` `candidate`\|`overhead`\|`homing_ref`\|`human`(`candidate` 는 인덱스와만, 나머지는 `pose` 와만), `cues`(≤6, `square`\|`paint`\|`peers`\|`slot`\|`last_good`\|`overhead`), `evidence`(≤16 키), `ttl_s`(받은 때부터 유효한 초, 0 초과 30 이하, 기본 5) |

로봇은 낡은 `request_id` 와, 받은 뒤 `ttl_s` 가 지난 결정을 무시한다(Fleet·로봇 시계 동기 불필요, D-395 개정 3). 사람이 아닌 결정은 `cues` 에 비대칭 단서(`square`·`paint`·`peers`·`slot`)가 하나 이상 있어야 받는다 — `last_good`·`overhead` 만으로는 거부한다. 받아들인 결정도 주입 뒤 3 s 스캔/지도 일치를 통과해야 `LOCALIZED` 가 되고, 실패하면 `SUSPECT`(`inject_rejected`)다. 대칭 맵에서는 거울상도 같은 적합도라 이 검증이 거울 주입을 거르지 못한다 — 거울은 Fleet 중재와 감시가 막는다. `square_sightings` 는 설계 4.2절 표 이후 개정 1의 `square_seen` 단서를 위해 더한 선택 필드다. `range_m` 이 null 인 목격(방위만)은 선로에 그대로 실리지만 Fleet 은 근거로 세지 않는다(D-395 개정 11).

---

# 8. 이벤트 카탈로그

> 소비자(Core 감사로그·Fleet·AI)가 의존하는 안정적 계약. 추가는 허용, 제거·의미 변경은 폐기 정책(API-003) 적용.

| type | severity | 발신 | payload 예시 |
|---|---|---|---|
| `system.boot` | info | 로봇 | `{version}` |
| `system.shutdown` | warning | 로봇 | `{}` |
| `config.changed` | warning | 로봇 | `{key, id, role, deleted}` — `key`: `robot.identity` \| `auth.tokens` \| `safety.limits` \| `dds.rmw`. `id`·`role` 은 토큰 추가, `id`·`deleted` 는 토큰 삭제·로그아웃, `id` 만은 이름표 변경일 때 실린다. 토큰 원문도, 원문에서 유도된 값도 싣지 않는다 |
| `auth.paired` | warning | 로봇 | `{id, role, source, expires_at}` — 로그인 코드로 토큰이 발급됐다(D-193). 코드도 토큰도 싣지 않는다 |
| `auth.code_burned` | warning | 로봇 | `{code_id, attempts}` — 틀린 시도가 쌓여 로그인 코드를 폐기했다 |
| `auth.enrollment_code_issued` | warning | 로봇 | `{code_id, role, by}` — 관리자(`by` = 토큰 id)가 등록 코드를 받았다. 코드는 싣지 않는다 |
| `auth.credentials_refused` | warning | 로봇 | `{count}` — 장치 모드가 기동 때 개발 토큰·평문 항목을 거부했다 |
| `mode.changed` | info | 로봇 | `{from, to, by}` |
| `calibration.session_started` | info | 로봇 | `{session_id, kind, label, owner, ttl_s}` — `owner` 는 토큰 id (D-321 부록, v1.68) |
| `calibration.session_ended` | info | 로봇 | `{session_id, kind, owner, by, duration_s}` — `by` 는 끝낸 토큰 id(Admin 강제 해제면 owner 와 다름) (v1.68) |
| `calibration.session_expired` | warning | 로봇 | `{session_id, kind, owner, ttl_s}` — `ttl_s` 안에 heartbeat 가 없어 lease 가 풀림. 보정 도구가 죽었거나 링크가 끊겼다는 신호 (v1.68) |
| `nav.started` | info | 로봇 | `{goal, by, correlation_id}` — `goal` 은 `{x, y, yaw}`; Fleet가 dispatch 시도 ID를 보낸 경우 그 값, 아니면 `null` |
| `nav.completed` | info | 로봇 | `{correlation_id}` — 동일 dispatch 시도 ID 또는 `null` |
| `nav.failed` | error | 로봇 | `{error_code, correlation_id}` — 동일 dispatch 시도 ID 또는 `null` |
| `nav.canceled` | info | 로봇 | `{source, correlation_id}` — 로컬 취소 요청을 냈다는 뜻이며 액션 완료나 물리 정지를 증명하지 않는다 |
| `nav.stuck` | error | 로봇 | `{timeout_s}` — NAV-006 무진척 판정 시간(초) |
| `nav.lane_lost` | warning | 로봇 | `{mode, reason, lost_after_s}` (NAV-007 차선 상실 — 유예 `lost_after_s` 초과 시 정지, 자동 재탐색 없음) |
| `nav.line_mode_changed` | info | 로봇 | `{from, to}` — D-143 line-follow 모드 선택 |
| `nav.line_driver_released` | info | 로봇 | `{mode}` — D-344 §8 운전자 확인(`hold_s`)이 끊겨 CORE 가 line-follow 를 스스로 내림 (v1.63) |
| `nav.line_obstacle_hold` | warning | 로봇 | `{mode, clearance_m, held_s}` — D-344 §11 앞 물체 정지(`obstacle_ahead`)가 `line_follow.obstacle_escalate_s` 넘게 이어짐, 정지 한 번에 한 번 (feat/device-prep, v1.64). 몸 기준 정지(D-422)면 `body_gap_m`·`stop_gap_m`·`clearance_source` 도 온다 (v1.84) |
| `nav.line_stuck_opened` | warning | 로봇 | `{stuck_id, cause, front_clearance_m, rear_clearance_m, rear_state, turn_clearance_m, rear_blind_m, last_lane, preview_seq, restuck_of, attempts}` — D-407 §1 막힘 열림: `cause` 는 `obstacle_ahead`(앞물체 정지가 `obstacle_escalate_s` 이상) 또는 `lane_lost`. 여유는 로봇별 self-mask 적용, 앞은 LiDAR 기준 경로 띠, 뒤는 URDF 몸 뒤끝 기준, 회전은 회전 반경 밖; `rear_blind_m` 은 LiDAR `range_min` 때문에 안 보이는 뒤 거리. 같은 막힘에 한 번 (v1.74) |
| `nav.line_stuck_asked` | info | 로봇 | `{stuck_id, cause, console_linked, local_fallback_s, attempts, reason, decisions}` — D-407 §2·§3 관제 판단 요청(FleetAgent 가 중계). `local_fallback_s` 가 null 이면 로컬 복구로 넘어가지 않고 관제 답만 기다린다(`reason`: `opened`·`console_wait`·`local_disabled`·`local_refused`·`local_aborted`·`attempts_exhausted`·`local_candidates_exhausted`). 늦게 연결한 관제는 반복 이벤트가 아니라 로봇 status 의 열린 stuck 으로 찾는다 (v1.74) |
| `nav.line_stuck_answered` | info | 로봇 | `{stuck_id, decision, by, principal_ref, accepted, reason, rear_blind_m, trail_m, trail_yaw_deg, trail_age_s}` — D-407 §2 관제 답. `by` 는 역할, `principal_ref` 는 답한 토큰의 이름 — 설정된 id 가 있으면 그 id, 없으면 `anon-` + CORE 프로세스마다 새로 만드는 키로 낸 HMAC 앞 12자(해시 앞자리를 그대로 내면 후보 토큰으로 확인할 수 있어서다; 이 값은 CORE 한 번 실행 동안만 같다). 비밀이 아니다. v1.80 에서 `token_id` 에서 이름을 바꿈: Fleet 감사 저장소가 자격 증명 이름으로 거부했다. `BACK_AND_RETRY` 거부면 판정한 scan 의 `rear_blind_m`·`trail_m`·`trail_yaw_deg`·`trail_age_s`, 아니면 null. 거부된 답(`stuck_id_mismatch`, 거부 사유)도 남는다 (v1.74) |
| `nav.line_stuck_local_attempt` | warning | 로봇 | `{stuck_id, attempt, trigger, back_m, speed_mps, rear_clearance_m, rear_blind_m, trail_m, trail_age_s}` — D-407 §4 로컬 후진 시작. `rear_blind_m` 은 LiDAR `range_min` 과 몸 뒤끝을 넘는 self-mask 창이 가리는 뒤 깊이, `trail_m` 은 방금 앞으로 지나온 거리(사용자 결정 2026-10-02: 사각 띠는 그 안에서만 들어간다)(`trigger`: `ask_timeout`·`no_console`·`retry`·`console`) (v1.74) |
| `nav.line_stuck_local_result` | info | 로봇 | `{stuck_id, attempt, result, reason, lane_visible, front_clear, rear_clearance_m, rear_blind_m, trail_m, trail_yaw_deg, trail_age_s}` — D-407 §4 결과: `recovered`·`still_stuck`·`refused`(시작 전)·`aborted`(후진 중 뒤 여유·scan stale·관제 WAIT) (v1.74) |
| `nav.line_stuck_closed` | info | 로봇 | `{stuck_id, cause, reason, attempts, held_s}` — D-407 막힘 닫힘(`cleared`·`recovered`·`console_resume`·`console_manual`·`console_abort`·`mode_off`·`mode_changed`·`driver_released`·`estop`) (v1.74) |
| `nav.traffic_policy_staged` | info | 로봇 | `{actor, policy_revision}` — D-151 traffic policy 변경 대기 |
| `nav.traffic_policy_applied` | info | 로봇 | `{actor, policy_revision, mode}` — D-151 대기 정책 적용(정지 상태에서만) |
| `nav.traffic_policy_reset` | info | 로봇 | `{reason}` — D-151 정책 상태 초기화(HOLD/DISABLED 로 복귀) |
| `nav.traffic_policy_signal_source_stale` | warning | 로봇 | `{outcome, silent_for_s}` — D-337 관측 신호 소스 침묵(카메라 단독으로 강등, 전환마다 1회) |
| `sim.traffic_signal_changed` | info | 로봇 | `{actor, colour}` — 시뮬레이션 신호등 제어가 켜진 프로필에서만 |
| `nav.blocked` | warning | 로봇 | **미구현** — CORE 는 Nav2 액션 피드백을 구독하지 않아 막힘을 알 방법이 없다. 진척이 없는 주행은 NAV-006 이 `nav.stuck` 으로 끝낸다 |
| `safety.estop` | critical | 로봇 | `{source}` |
| `safety.estop_released` | warning | 로봇 | `{by}` |
| `safety.watchdog` | warning | 로봇 | `{timeout_ms}` |
| `safety.shadow_verdict` | info | 로봇 | `{verdict, reason, source, t, commanded, output, limited, suppressed}` — D-400 그림자 판정. 판정이 바뀔 때·명령 중(0 아닌 후보) 같은 판정 1 s마다·최대 5/s. `suppressed` 는 그 사이 억제된 판정 변화 수, `commanded` 는 프로필 클립 뒤 값, `t` 는 CORE monotonic 초 (v1.71) |
| `safety.policy_off` | warning | 로봇 | `{source}` — D-400 정책 off 에서 navigation·docking 출력이 처음 0 이 아닐 때, 모드 진입마다 한 번 (v1.71) |
| `safety.fleet_lost` | warning | 로봇 | `{policy, applied, activity, correlation_id, goal, disconnected_s, reason}` — SAF-003(D-419): FleetAgent 링크가 `fleet_loss_timeout_s` 넘게 끊긴 채 Fleet 주행 목표가 진행 중이어서 정책을 적용했다(행동 뒤 발행, 단절마다 한 번). `policy` 는 설정값, `applied` 는 실제로 한 것(`STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`·`NONE`), `activity` 는 `navigation`, `goal` 은 `{x, y, yaw}`, `reason` 은 `null` 또는 `unknown_policy`·`home_unavailable: …`·`action_failed: …`·`goal_changed`(취소 순간 그 목표가 이미 끝났거나 바뀜, `applied: NONE`). 취소는 `nav.canceled {source: fleet_loss}` 로도 보인다 (v1.86) |
| `safety.fleet_restored` | info | 로봇 | `{applied, correlation_id, disconnected_s, held_goal}` — `safety.fleet_lost` 뒤 링크가 돌아왔다. 아무것도 재개하지 않는다. `held_goal` 은 `HOLD` 가 보관한 `{correlation_id, x, y, yaw}` 또는 `null` (v1.86) |
| `battery.low` | warning | 로봇 | `{percent}` |
| `battery.critical` | critical | 로봇 | `{percent, policy}` |
| `battery.deep` | critical | 로봇 | `{percent, voltage, dwell_s}` — D-27 딥 방전. 모터가 서고 셧다운 센티넬이 무장된다 |
| `battery.shutdown_request_failed` | error | 로봇 | `{path, error, armed}` — D-27 셧다운 센티넬을 쓰지 못했다. 딥배터리 보호가 무장되지 않았다는 뜻이므로 조용히 넘어가면 안 된다 |
| `command.rejected` | warning | 로봇 | `{source, reason}` |
| `recording.started` | info | 로봇 | `{id, owner}` — D-411 §5.10 Pilot 로봇 녹화가 시작됐다. `owner` 는 시작한 토큰 id (v1.83) |
| `recording.stopped` | info | 로봇 | `{id, by, reason}` — D-411 녹화 끝. `by` 는 정지한 토큰 id 또는 `null`(CORE 가드·녹화기 쪽 종료). `reason` ∈ `operator`·`link_lost`·`seat_changed`·`max_duration`·`quota`·`disk_full`·`recorder_exit`·`requested`·`shutdown`·`recovered` (v1.83) |
| `waypoint.created/updated/deleted` | info | 로봇 | `{name}` |
| `slam.started` | info | 로봇 | `{by, reset}` — `reset` 은 재시작일 때만 (NAV-005) |
| `slam.stopped` | info | 로봇 | `{by}` |
| `power.mode_changed` | info | 로봇 | `{from, to, reason, sample_rate_hz}` (PWR-001) |
| `power.wake` | info | 로봇 | `{reason}` — `proximity\|contact\|api\|battery` (PWR-004) |
| `presence.detected` | info | 로봇 | `{state, range}` (PWR-002) |
| `presence.cleared` | info | 로봇 | `{range}` |
| `power.lidar_changed` | info | 로봇 | `{spinning, reason, spinup_s}` (PWR-005 STANDBY LiDAR 정지) |
| `map.saved` | info | 로봇 | `{map_id}` |
| `localization.initialpose` | info | 로봇 | `{x, y, yaw, source}` — 운영자가 자세를 놓았다. `source` 는 결정 출처로 이 경로에서는 늘 `human`(v1.72). D-395 로봇에서는 `localization/decision` 으로 가 로봇의 3 s 검증을 거친다. 누가 놓았는지는 envelope 의 `source` 에 있다 |
| `localization.state` | info | 로봇 | `{state, previous, pose_frame, reason, request_id}` — D-395 상태가 바뀌었다(v1.72). `previous` 는 처음이면 `null`. 상태 토픽이 3 s 끊기면 `UNKNOWN`(`reason: state_stale`). `previous: LOCALIZED` 에서 벗어나면 CORE 가 자율 주행을 기존 정지 경로로 멈춘다: swarm follow 취소(`swarm.aborted`, `reason: localization`), 도킹 취소, line-follow OFF, Nav2 취소(`nav.canceled`), NAVIGATION → IDLE. MANUAL(teleop)은 그대로 |
| `localization.candidates` | info | 로봇 | `{request_id, count, pickup}` — 새 `request_id` 의 후보 보고가 왔다(v1.72). 2 s 재보고는 다시 내지 않는다 |
| `localization.result` | info | 로봇 | `{request_id, accepted, reason, state, source, cues}` — 로봇이 결정을 받았거나 거부했다(v1.72). `source`·`cues` 는 CORE 가 그 `request_id` 로 보낸 결정의 것이고, 모르면 `null`·`[]` |
| `localization.mission` | info | 로봇 | `{phase, kind, reason, elapsed_s, travelled_m, turned_rad}` — D-395 P2-7 미션이 시작했거나(`phase: started`, `reason: null`) 끝났다(`phase: done`\|`aborted`, `reason` 은 `POST /localization/mission` 의 끝 사유). 같은 내용이 ROS `localization/mission` 으로 로봇 sensing 노드에 가서 다시 탐색하게 한다 (v1.73) |
| `docking.started` | info | 로봇 | `{dock_id}` (DNC-003) |
| `docking.docked` | info | 로봇 | `{dock_id}` |
| `docking.charging` / `docking.charge_lost` | info | 로봇 | `{dock_id}` — 독립된 두 소스로 확인한 충전 상태 (D-28) |
| `docking.full` | info | 로봇 | `{dock_id, source, voltage_v}` — 만춫 감지, 1회 방출. `source: instrumented` 또는 `voltage_only` (D-350) |
| `docking.undock_started` | info | 로봇 | `{dock_id}` |
| `docking.undocked` | info | 로봇 | `{}` |
| `docking.canceled` | info | 로봇 | `{dock_id}` |
| `docking.retry` | warning | 로봇 | `{reason, attempt}` — 접근 재시도 |
| `docking.reseat` | warning | 로봇 | `{reason, attempt}` — 접점 재착좌 |
| `docking.failed` | error | 로봇 | `{reason, dock_id}` — 종착이며 스스로 재시도하지 않는다 (D-28) |
| `docking.return_started` | warning | 로봇 | `{dock_id, reason}` — SAF-005 저배터리 복귀 |
| `mission.assigned` | info | Fleet | `{mission_id, robot_id}` |
| `mission.started` | info | Fleet | `{mission_id}` |
| `mission.step_completed` | info | Fleet | `{mission_id, step_index}` |
| `mission.completed/failed/canceled` | info/error/info | Fleet | `{mission_id, reason}` |
| `robot.online/offline` | info/warning | Fleet | `{robot_id}` |
| `pairing.requested/approved/revoked` | warning | Fleet | `{robot_id}` |
| `swarm.role_assigned` | info | 로봇 | `{role, formation, target_robot_id, reference_source, by}` |
| `swarm.hold` | warning | 로봇 | `{reason, formation, stream_timeout_ms, reference_map_id, map_id}` — `reason`: `reference stream lost`(+`stream_timeout_ms`) \| `map_mismatch`(+`reference_map_id`, `map_id`) |
| `swarm.aborted` | warning | 로봇 | `{formation, reason, robots, by}` — `reason`: `canceled` \| `estop` \| `docking` \| `stuck` \| `manual` \| `navigation_canceled` \| `localization`(D-395 로봇이 `LOCALIZED` 를 벗어남, v1.72) |
| `swarm.succession` | warning | 로봇 | `{leader, dead, role, by}` — 명단이 공유된 대형에서 리더(`dead`)를 잃은 팔로워가 follow 를 끝내고 낸다. `leader` 는 `next_leader` 규칙이 고른 다음 리더(없으면 `null`), `role` 은 이 로봇의 새 역할, `by`: `followers` |

---

# 9. 데이터 스키마 카탈로그

## 9.1 Capability Descriptor (CAP-001)

```json
{
  "capability_version": 1,
  "navigation": { "goal_navigation": true, "return_home": true,
                  "max_linear_velocity": 0.2, "max_angular_velocity": 0.8 },
  "teleop": true,
  "slam": true,
  "swarm": { "follow": true, "lead": true },
  "docking": { "supported": false },   // true 이면 DNC-004~006 전체가 활성
  "sensors": ["lidar", "imu", "battery", "encoder"],
  "events": ["nav.*", "safety.*"],
  "api_versions": ["v1"],
  "protocol_version": "1.0"
}
```

**`withheld` (v1.18 additive, v1.21 판정 변경, D-32/D-161/D-192)**: 지금 런타임이 지킬 수 없는 하드웨어 플래그
(`teleop`, `navigation.goal_navigation`, `navigation.return_home`, `slam`, `swarm.follow`, `swarm.lead`,
`docking.supported`)를 `false` 로 내리고, 내린 것과 이유를 싣는다. `reason` 은 첫 플래그의 이유(v1.18 호환),
`reasons` 는 플래그마다의 이유다(v1.21 additive).

```json
"withheld": {
  "flags": ["teleop", "navigation.goal_navigation", "slam"],
  "reason": "drive_disabled:no_motion",
  "reasons": {"teleop": "drive_disabled:no_motion",
              "navigation.goal_navigation": "drive_disabled:no_motion",
              "slam": "navigation_absent"}
}
```

판정은 설정 문자열(`runtime.mode`)이 아니라 **살아 있는 증거**로 한다(v1.21). 네이티브 이미지는 `runtime.mode: core`
그대로 운용자가 `rosy-io` 를 손으로 켠다(D-192). 플래그마다 아래 순서로 첫 이유 하나:

| 이유 | 조건 | 대상 플래그 |
|---|---|---|
| `runtime_mode:core` | `runtime.mode: core` 이고 오도메트리(velocity)·배터리 표본이 한 번도 없음 | 전부 |
| `hardware_silent` | 표본이 온 적은 있으나 단조 시계 기준 15 s 안에 없음 | 전부 |
| `drive_disabled:no_motion` | bringup 이 `motor/ready: false` 를 보고(D-192 무동작: torque off, `cmd_vel` 미구독) | `slam` 을 뺀 전부 |
| `drive_lease_expired` | `motor/ready: true` 였으나 lease(`navigation.readiness.stale_after_s`)가 지남 | `slam` 을 뺀 전부 |
| `drive_absent` | `motor/ready` 보고가 없고, readiness 게이트가 motor adapter 를 요구하거나 오도메트리가 살아 있지 않음. `slam`도 오도메트리 없이 배터리만 들어오면 보류 | 이동 플래그 및 오도메트리 없는 `slam` |
| `navigation_absent` | readiness 게이트가 required 이거나 bringup 이 `motor/ready` 를 보고했는데, 백엔드 프로파일의 Nav2/SLAM lifecycle 노드가 모두 active 로 보고하지 않음 | `navigation.goal_navigation`, `navigation.return_home`, `slam` |
| `readiness_hold:<missing>` | 필수 하드웨어 준비 게이트가 HOLD | 이동 플래그 및 `slam` |

`motor/ready` 없이 오도메트리만 오는 시뮬 벤치(gz_multi, CORE-only)는 종전대로 광고를 유지한다. 명령 경로의
CAP-003 게이트는 이 변경으로 바뀌지 않는다. `POST /teleop`, `/navigation/goal`,
`/navigation/home`은 지원 여부를 먼저 확인한 뒤 현재 보류된 기능을 409
`CAPABILITY_WITHHELD`와 동일한 `reason`으로 거절한다. 준비 상태가 판정과 전송 사이에
변하면 기존 503 `HARDWARE_NOT_READY`가 발생할 수 있다.

**`runtime` (v1.21 additive)**: 위 판정의 근거. 대시보드는 하드웨어 존재를 `runtime_mode` 문자열이 아니라 이것으로 읽는다.

```json
"runtime": {
  "mode": "core",
  "hardware": "on",
  "evidence": ["odometry", "battery"],
  "drive": "disabled",
  "navigation": "absent",
  "maps": {"occupancy": false, "global_costmap": false}
}
```

`hardware`: `on`(오도메트리 또는 배터리 표본이 15 s 안) \| `silent`(온 적은 있으나 끊김) \| `off`(온 적 없음).
`drive`: `ready` \| `disabled`(`motor/ready: false`) \| `stale`(lease 만료) \| `unknown`(보고 없음).
`navigation`: `ready` \| `absent` \| `unknown`(판정하지 않음 — 게이트 비필수이고 bringup 보고도 없음).
`maps`: 스냅샷이 있는지. `false` 인 것을 `GET /api/v1/map`·`/map/costmap?scope=global` 로 물으면 404 다 — 클라이언트는
묻지 않는다.

**`lifecycle` (v1.58 additive, D-347)**: 광고된 플래그 각각의 런타임 생애를 **단일 어휘**로 실는다. 원천은 이미
있는 두 값 — 위 `withheld` 판정(모드 마스킹 사유가 우선)과 플래그의 참/거짓 — 이며, 새 판정을 만들지 않는다.
`withheld.flags` 는 항상 `lifecycle` 의 `unavailable` 집합과 정확히 일치한다.

```json
"lifecycle": {
  "teleop": {"state": "unavailable", "reason": "drive_disabled:no_motion",
             "reasons": ["drive_disabled:no_motion"]},
  "slam": {"state": "ready"}
}
```

- `ready`: 지금 아무것도 보류하지 않는다.
- `unavailable`: `reason`·`reasons` 는 `withheld.reasons` 와 같은 값이다.
- `activating`: **예약** — 온디맨드 그래프 기동(D-347 토론 B레인)용 슬롯으로, 아직 이 상태로 진입하는 생산자는
  없다. 클라이언트는 이 값을 "준비 안 됨, 실패 아님"으로 읽는다: 갱신하거나 기다리지, 오류로 승격하지 않는다.

프로파일과 런타임 어느 쪽도 true 로 말하지 않는 플래그(예: `docking.supported`)는 `lifecycle` 에 없다(설계 §7).
inventory 기술자의 `state`(available/constrained/… presentation 어휘)와의 대응은 D-347 본문의 표가 정한다:
`unavailable` ≈ `blocked`, `ready` ≈ `available`·`constrained`·`degraded_fallback`, 대응 없음 ≈ `not_provided`.

**`controls` (v1.87 additive, D-411 B)**: 이 기기가 받는 조작부 서술자 `rosy.controls/1` `{schema, items[]}`. 항목은
`{id, kind, label, ...}`이고 kind 는 `base_velocity`(`max_linear`·`max_angular`·`pivot`·`fine`·`autonomy`),
`joint_jog`(`joints[{name, lower, upper}]`·`max_step_rad` ≤ 0.05·`duration_s` 0.1–1.0·`command: "bounded_goal"`),
`gripper`(`joint`·`closed`·`open`·`unit`·`presets{open, half, close}`·`readback`)다.

- `base_velocity`: `max_linear`·`max_angular` 는 지금의 수동 한도다. **0 은 "구동은 있으나 지금 정지로 제한됨"**
  (`PUT /safety/limits` 가 0 을 받는다)이며 오류가 아니다. `autonomy` 는 기기가 **제공하는** 자율 모드다 — CORE 는
  line-follow 서비스를 가질 때 `["line"]`, 없으면 `[]`. 이것은 지금 차선 추종을 시작할 수 있다는 런타임 증거가 **아니다**
  (차선 관측은 모드를 켠 뒤에만 들어오고, 쉬는 동안 카메라·차선 준비를 보여 주는 신호가 없다). 시작 가능 여부는
  `PUT /line-follow/mode` 응답과 `GET /line-follow` 상태(`WAITING`·`LOST` 등)가 판정한다. `pivot`·`fine` 은 Pinky
  프로필 상수다(런타임 증거 아님).
- `joint_jog`: 요청 한 번은 관절 하나를 `max_step_rad` 이하로 옮긴다. `duration_s` 는 **클라이언트가 각 요청에 보낼 목표
  길이**다. 이전 목표가 끝난 뒤에만 다음 목표를 보낸다(D-390 §2).
- `gripper`: `presets.open` = `open`, `presets.close` = `closed`, `presets.half` 는 둘 사이(끝값 제외)다. 목표는 절대
  위치 하나씩이다. `max_velocity`(선택, rad/s)를 알리는 기기는 `|목표 − readback| / duration_s` 가 그보다 큰 목표를 거절하므로
  클라이언트는 그 속도로 목표 길이를 정한다. `readback` 의 `grasp` 는 상태 readback 의 그리퍼 상태(`open`·`closed`·`holding`·`moving`·`unknown`,
  OMX SIM 은 §5.9 `/state` `gripper`)를 낸다는 뜻이다.

Pinky 는 켜진 adapter manifest `provides` 의 `drive`(manifest 가 없으면 `teleop`)에서 `base_velocity` 하나
(`id: "base"`, 최대값 = `safety.manual_linear`·`manual_angular`)를 낸다. `teleop` 이 보류되면(`withheld`) `items` 는
비어 있다. 빈 `items` 는 "지금 조작부 없음"이지 "구 서버"가 아니다 — 이 필드가 **없는** 구 서버에서만 Pilot 이 기존
Pinky 프로필로 대체한다.

호환: 스키마 정본 `core_common.protocol.controls`(`ControlsDescriptor`)는 **생산자** 스키마다(모르는 필드 거부). `/1`
안에서는 새 kind 와 새 선택 필드를 더할 수 있고, 소비자(Pilot)는 모르는 kind·필드를 무시하고 kind 는 "지원하지 않는
조작부"로 보인다. 필드를 빼거나 뜻을 바꾸면 `rosy.controls/2` 다.

같은 동안 `GET /api/v1/system/inventory` 의 descriptor 는 `available: false`, `state: "blocked"` 이고 `reason` 은
그 플래그의 런타임 이유다. **런타임 이유가 `device_state` 보다 먼저다(v1.21, 이전에는 반대)** — 비상정지를 풀어도
구동이 없는 로봇은 움직이지 않으므로 SAFE_STOP 이 더 오래 가는 이유를 가리면 안 된다. `reasons`(v1.21 additive)는
모든 이유를 기본적인 것부터 싣는다: `["runtime_mode:core", "device_state:SAFE_STOP"]`.

## 9.2 Waypoint (WPT-001)

```json
{ "name": "dock_1", "x": 2.5, "y": 1.8, "yaw": 1.57,
  "map_id": "warehouse_a", "metadata": { "label": "충전독 앞" } }
```

## 9.3 Mission DSL v1 (MSN-001)

```json
{ "mission_id": "patrol_evening",
  "target": { "robots": ["rosy_01"] },
  "idempotency_key": "pe-20260829-01",
  "steps": [
    { "action": "goto", "waypoint": "zone_a" },
    { "action": "home" },
    { "action": "wait", "seconds": 30 },
    { "action": "formation", "formation": "V", "robots": ["rosy_01","rosy_02"], "center": {"x":0,"y":0} }
  ] }
```

v1 action: `goto`(waypoint|x,y,yaw) / `home` / `wait(seconds)` / `formation`. 상태머신은 FLEET SRS MSN-002.

## 9.4 Robot Profile (HWA-001)

```yaml
profile:
  model: Pinky Pro
  drivetrain: differential
  wheel_base: 0.15
  max_linear_velocity: 0.20
  max_angular_velocity: 0.80
  sensors: [ {lidar: rplidar_c1}, {imu: bno055}, {battery: adc} ]
```

## 9.5 Command 추적 레코드 (PRT-004)

```json
{ "correlation_id": "uuid", "robot_id": "rosy_01",
  "action": "goto", "params": { "waypoint": "zone_a" },
  "status": "ACCEPTED|STARTED|COMPLETED|FAILED|TIMEOUT",
  "issued_by": "user:admin|mission:m123|fleet:stop_all",
  "ts_issued": "...", "ts_final": "..." }
```

`TIMEOUT`은 Fleet 측 레코드 전용이며 로봇 ack에는 나타나지 않는다 (D-215).
타임아웃은 로봇의 정지나 실패 증거가 아니다. 늦은 ACK는 동일
`correlation_id`로 조정하고, 타임아웃만으로 물리 명령을 재발행하지 않는다(D-297).

---

# 10. Fleet REST API 카탈로그

Fleet(rosy_fleet)이 제공하는 엔드포인트. Base: `http://<fleet-host>:8081`

> **상태 (v1.97, D-454): 로봇 레지스트리 읽기 두 경로 구현.**
> `fleet console --central`이 기존 사이트 앱에 §10.1의 GET 두 경로를 마운트한다.
> 기본 사이트 프로파일에는 이 경로가 없다. 별도 8081 서비스나 중앙 쓰기·명령·
> 미션 API는 아직 구현하지 않았다. 기존 `:8090`의 `/api/fleet/*`와 SiteHub는
> 유지하며, 로봇↔사이트 프로토콜은 §5~§7을 따른다.

사이트 시드의 추가 경로는 §10.6에 기록한다. 이 API는 로봇 `/api/v1/*`와 다른
listener·자격 증명이다. §10.1의 명시된 읽기 경로 외 중앙 카탈로그의 구현 상태로
간주하지 않는다.

## 10.1 로봇·페어링

D-454 1단계의 구현은 아래 GET 두 경로에 한정한다. 기존 Fleet Viewer 이상의
인증을 사용하며, CLI 활성화에는 기존 `--robot-credential-key-file`과 `--tasks-db`
등록 구성이 필요하다. 나머지 행은 후속 목표 계약이다. 등록·페어링·권한을
읽기 요청이나 발견 광고로 변경하지 않는다.

목록은 `{robots: [...]}`, 상세는 한 행이며 각 행은 `robot_id`, `source`
(`static`·`enrolled`), `online`, `state`, `capabilities`, `address_last_seen`을
반환한다. 등록 로스터가 정본이며 등록되지 않은 상세는 404 `UNKNOWN_ROBOT`이다.
목록은 robot_id 오름차순이고 이 단계에는 pagination이 없다. `online`은 기존
Hub의 연결 상태이고 물리 동작 수락 증거가 아니다. `state`·`capabilities`는 기존
스냅샷에 없으면 null이며 서버가 기능을 추정하지 않는다. 마지막 발견 주소도
등록 신원과 안전하게 대조할 수 없으면 null이다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/robots` | Viewer | REG-002 (상태·Capability 포함) |
| GET | `/api/v1/fleet/robots/{id}` | Viewer | REG-002 |
| PATCH | `/api/v1/fleet/robots/{id}` | Admin | 이름·그룹 변경 (REG-003) |
| DELETE | `/api/v1/fleet/robots/{id}` | Admin | 등록 해제 (REG-001a) |
| POST | `/api/v1/fleet/pairing-tokens` | Admin | 1회용 발급 (SEC-201) |
| DELETE | `/api/v1/fleet/pairing-tokens/{token}` | Admin | 폐기 (SEC-201) |
| GET | `/api/v1/fleet/pending-robots` | Admin | 승인 대기 목록 (SEC-202) |
| POST | `/api/v1/fleet/pending-robots/{id}/approve` | Admin | 승인 (SEC-202) |
| POST | `/api/v1/fleet/robots/{id}/token/revoke` | Admin | 토큰 폐기 (SEC-203) |

## 10.2 명령

현행 Site Fleet 구현의 `POST /api/fleet/estop`은 각 등록 로봇의
`POST /api/v1/safety/stop`에 요청을 보낸다. 응답의 레거시 `stopped` 및 로봇별
`stopped`는 CORE HTTP 응답을 받은 수/여부다. CORE 안전 래치, 속도 0,
물리 E-stop 또는 드라이버 인터록의 확인 결과가 아니다. 응답 실패 대상의 실제
정지 상태는 `UNKNOWN`으로 취급하며 현장 readback을 따로 확인한다(D-298).
이 경로는 래치형 **전체 비상 정지**다: CORE EMERGENCY 래치와 Fleet 발행 래치를
걸고, 다시 움직이려면 로봇별 Admin `safety/release`와 발행 재허가가 필요하다.
래치 없는 **전체 주행 취소**는 `POST /api/fleet/cancel-all`이다(D-421, v1.81,
§10.8): 대기 Fleet 작업 취소, 대형 해제, 로봇마다 `swarm/cancel`·
`navigation/cancel`·`line-follow/mode OFF`. e-stop 래치·발행 래치·수동 조작은
건드리지 않으며 응답은 CORE 응답이지 물리 정지 증거가 아니다. CTR-002 STOP ALL은
이 두 경로로 나뉜다.
아래 `/api/v1/fleet/*`는 목표 계약이며 현행 `/api/fleet/*`와 혼동하지 않는다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/fleet/commands` | Operator | 다중 로봇 명령 `{robot_ids, action, params}` (CTR-001, PRT-004) |
| POST | `/api/v1/fleet/stop-all` | Operator | STOP ALL (CTR-002) |
| GET | `/api/v1/fleet/commands/{correlation_id}` | Viewer | 추적 상태 조회 |

`action`: `goto | home | stop | estop | estop_release | mode | formation`

## 10.3 Mission·Formation

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/fleet/missions` | Operator | 생성·실행 (MSN-001/003) |
| GET | `/api/v1/fleet/missions` | Viewer | 목록 |
| GET | `/api/v1/fleet/missions/{id}` | Viewer | 상세(스텝 상태) |
| POST | `/api/v1/fleet/missions/{id}/cancel` | Operator | 취소 (MSN-002) |
| POST | `/api/v1/fleet/formations` | Operator | `{formation, robots, params}` (FOR-001) |

## 10.4 Waypoint·맵·운영

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/waypoints?map_id=` | Viewer | 전체 로봇 Waypoint 조회 |
| POST | `/api/v1/fleet/waypoints/sync` | Operator | `{robot_ids, waypoints}` 로봇 동기화 (WPT-005) |
| GET | `/api/v1/fleet/maps` | Viewer | map_id·버전 목록 (MAP-003) |
| POST | `/api/v1/fleet/robots/{id}/backup` | Admin | 스냅샷 수집 (OPS-001) |
| POST | `/api/v1/fleet/robots/{id}/restore` | Admin | 복구 프로비저닝 (OPS-002) |

## 10.5 이벤트·감사

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/fleet/events?robot_id=&type=&since=` | Viewer | 통합 이벤트 조회 (OBS-202) |
| GET | `/api/v1/fleet/audit` | Admin | Fleet 감사 로그 |

## 10.6 Site Fleet sighting (D-257 Proposed)

Base: `https://<site-fqdn>:8443`. 이 경로는 지도 위 표시·로봇 pose 대조용이다.
이미지나 자동 정책 입력이 아니며 source 설정이 없는 앱에는 경로를 등록하지 않는다.
`fleet console --sightings-config <site-cameras.yaml> --sightings-db <fleet.sqlite3>`로
source/map/calibration 허용 목록과 SQLite 영속 저장을 설정한다. source token은 YAML이 아닌
별도 secret mount에서 환경 변수로 읽는다. HTTPS/WSS 종단과 내부 upstream TLS는 `deploy/site`
Compose/Caddy 구성이 담당한다. 로컬 합성 카메라의 Docker end-to-end 경로를 확인했지만 현장
인증서·실제 카메라·survey calibration은 별도 수용 gate다.

| Method | Path | Credential | 요구사항 |
|---|---|---|---|
| POST | `/api/fleet/sightings` | source 전용 Bearer token | vision worker가 `SiteSightingPayload`를 제출. 토큰 설정이 허용한 source/robot/map/calibration만 수용 |
| GET | `/api/fleet/sightings` | console Bearer token | 로봇별 최신 sighting, server-derived source, capture/receive age 및 1 s lease stale 상태 |
| GET | `/api/fleet/site-map` | console Bearer token 또는 viewer 이상 | 설정된 `corner_world_m` 사각형을 `map_id`별로 묶어 반환(`frame: map`, m 단위 `polygon_m`·`bounds_m`, source별 `source_id`·`calibration_revision`·`calibration_source`·`corner_marker_ids`(D-484 `field_boundary` 소스는 `null`)·`robot_ids`·`robot_markers`). 토큰은 싣지 않는다. 설정·기하가 없으면 404 `NO_SITE_MAP`. 표시 전용 |

`POST` body `SiteSightingPayload`:

```json
{
  "robot_id": "rosy_01",
  "x": 1.25,
  "y": -0.5,
  "yaw": 0.2,
  "captured_at": 1790000000.25,
  "seq": 42,
  "map_id": "lane-map:sha256:abc",
  "calibration_revision": "ceiling-1-v2",
  "processor_revision": "aruco-map-v1",
  "quality": null,
  "corner_marker_ids": [30, 31, 32, 33]
}
```

`quality`가 `null`이면 측정하지 않은 상태다. 화면 표시에만 사용하며 D-268 정책 증거로 승격하지 않는다.

D-484(v1.109)부터 `corner_marker_ids`는 선택 필드가 되고, 대신 `calibration_source`가
추가된다. 값은 `corner_markers`(기본, 코너 ArUco 마커 측정) 또는 `field_boundary`
(흰 경계 사각형+페인트 정합 orientation 캘리브레이션)다. `field_boundary` sighting은
`corner_marker_ids` 없이 `calibration_source: "field_boundary"`만 싣고, 서버 설정의
`calibration_source`까지 일치해야 한다. 과거 페이로드(마커 id만)는 그대로 유효하다.

```json
{
  "robot_id": "rosy_01",
  "x": 1.25,
  "y": -0.5,
  "yaw": 0.2,
  "captured_at": 1790000000.25,
  "seq": 42,
  "map_id": "lane-map:sha256:abc",
  "calibration_revision": "ceiling-1-v2",
  "processor_revision": "aruco-map-v1",
  "quality": null,
  "corner_marker_ids": null,
  "calibration_source": "field_boundary"
}
```

`captured_at`은 UTC Unix seconds다. 서버가 `source_id`와 `received_at`을 붙인다. client가
`source_id`, image/JPEG/URL 또는 policy 필드를 추가하면 422다. map/calibration/코너 설정
불일치, 1 s 초과 stale/future/out-of-order 입력은 409, 허가되지 않은 robot은 403이다.
source token은 console/robot REST/CORE Agent token과 달라야 하고 이 credential로 명령
경로를 호출할 수 없다. D-268 policy evidence 및 자동 실행은 이 API에 포함되지 않는다.

### 10.6.1 Site Fleet camera preview and rectification (D-318 Accepted)

The phone sends latest-only JPEG frames to Vision over the authenticated
`rosy-overhead/1` WSS. The Fleet browser receives a short-lived source-scoped
lease, then reads one fresh JPEG directly from Vision. Fleet does not relay image
bytes. The optional `rectification` object on lease creation is signed into the
lease, so Vision can verify and bound CPU preview work without a new camera
credential. No browser or Fleet process connects to ROS/DDS.

| Method | Path | Credential | Result |
|---|---|---|---|
| GET | `/api/fleet/vision/sources` | Site console Bearer token, or tokenless through the site Caddy proxy from a private LAN address | Configured preview source IDs |
| POST | `/api/fleet/vision/lease` | Viewer Bearer token, or tokenless through the site Caddy proxy from a private LAN address | 60 s source-scoped lease and direct Vision frame path |
| GET | `/api/vision/sources/{source_id}/frame` | Vision preview lease Bearer token | One latest fresh JPEG; `Cache-Control: no-store`; `X-Frame-Seq`, `X-Frame-Age-Ms`, `X-Frame-Captured-At`, `X-Frame-Width`, `X-Frame-Height`, `X-Frame-Rotation-Deg`, and `X-Frame-Rectified` (`true` manual, `auto` D-484 field calibration, `false` raw) describe that exact frame; `mode: "auto"` requests additionally report `X-Field-Calib` (calibration state) and, while no accepted quad exists, answer the raw JPEG with `X-Frame-State: field-unavailable` |
| GET | `/api/vision/sources/{source_id}/field-proposal` | Vision preview lease Bearer token | D-360 field-corner proposal JSON for operator review (`proposal` null when no full field is visible); own 1/s bucket per lease subject; detection runs at most once per source per second, off the event loop (readers in between get the last result, 429 while the first run is busy); `no-store`, same freshness 404s, 422 on undecodable frame. Display only, never applied to sightings |

The tokenless camera exception applies only to the two Fleet preview endpoints above. Caddy determines the immediate peer's private address and overwrites a private proxy header for those paths; it strips client-supplied copies on all other Fleet paths. Fleet and Vision are not published outside the site backend network. The issued lease is still required at Vision, source scoped, and expires after 60 seconds. Robot state, commands, enrollment, and other Fleet APIs still require their existing credentials.

Lease request body accepts `{ "source_id": "ceiling-north" }` for the original
JPEG or an optional `rectification` object:

```json
{
  "source_id": "ceiling-north",
  "rectification": {
    "fx": 1.2, "fy": 1.2, "cx": 0.5, "cy": 0.5,
    "k1": -0.18, "k2": 0.03, "p1": 0.0, "p2": 0.0, "k3": 0.0,
    "corners": [[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]],
    "output_aspect": 1.0
  }
}
```

Intrinsics (`fx`, `fy`) are normalized focal lengths in `[0.25, 4]`; principal
point (`cx`, `cy`) is normalized to `[0, 1]`. Radial coefficients (`k1`, `k2`,
`k3`) are bounded to `[-1, 1]`, tangential (`p1`, `p2`) to `[-0.5, 0.5]`.
`corners` is four normalized `[x,y]` pairs in clockwise top-left, top-right,
bottom-right, bottom-left order; crossed, degenerate, non-finite, or out-of-frame
polygons are rejected. `output_aspect` is automatic `0` or `[0.25, 4]`; output
dimensions are capped at 1920×1080. The Vision service keeps its raw latest JPEG
for ArUco/sighting processing. OpenCV correction is applied only to the returned
preview copy. Existing source/principal limit of 5 frame reads per second still
applies. Invalid settings return 422; missing or stale images remain unavailable.

D-484(v1.109)부터 `rectification`에 `mode: "manual" | "auto"`가 추가됐다(기본
`manual`, 과거 리스는 그대로 유효). `auto`면 이 문서의 `corners`·왜곡 계수는 무시되고,
Vision worker가 수용한 필드 경계 사각형으로 평면 보정한다(렌즈 왜곡값도 함께 안 쓴다).
수용된 사각형이 없으면 원본 JPEG와 `X-Frame-State: field-unavailable`을 돌려준다.
자동 보정은 미리보기 전용이며 원본 프레임·sighting 경로를 바꾸지 않는다.

Fleet stores operator drafts per source in the current browser only. Until the
camera intrinsics and floor plane have been measured and reviewed, this view is a
visual adjustment and not calibrated site evidence. Rectified pixels do not
change sightings, navigation, mission acceptance, or robot motion.

## 10.6.2 Site Fleet policy-eligible evidence (D-268 Proposed)

작업 **발의 자격** 증거의 제출·보관 계약이다(승격 사다리 1단계). sighting(§10.6)은 표시·대조
자료이고 목표 성공 증거는 Mission 원장의 별개 면이다 — 어느 쪽도 이 경로를 대신하지 않는다.

| Method | Path | Auth | 설명 |
|---|---|---|---|
| POST | `/api/fleet/policy-evidence` | 정책 증거 source Bearer 토큰 | `PolicyEvidencePayload` 제출. 서버가 토큰에서 출처를 결정하고 클라이언트 제시 출처는 신뢰하지 않는다 |
| GET | `/api/fleet/policy-evidence/latest` | Viewer | 최근 증거 기록(최대 50건, `payload` 포함) |

`PolicyEvidencePayload`(`core_common.protocol.policy_evidence`): `evidence_id`(≤160, 식별자
규칙), `asset_kind`(robot·workcell·object), `asset_id`, `task_kind`(v1 닫힌 집합 `navigate`),
`captured_at`, `map_id`·`calibration_revision`·`model_revision`(공백 불가), `observation`
(`kind`만 담는 닫힌 봉투). 클라이언트가 `source`·`source_id`·`token`·`policy`·`satisfied`를
보내면 422다(`satisfied`는 목표 판정 전용 어휘).

제출 검증 순서: 출처(401 `EVIDENCE_SOURCE_UNKNOWN`, 폐기 토큰 포함) → transit
(`captured_at`→수신 0~300 ms) → 출처 허용의 `task_kind`·`asset_kind`·revision 삼종 →
관측 등록부. 수용·거절 모두 SQLite에 기록으로 저장되고 200에
`{evidence_id, source_id, payload, received_at, outcome, reason}`을 반환한다. `reason`은
`EVIDENCE_TRANSIT_LATE`·`EVIDENCE_REVISION_MISMATCH`·`EVIDENCE_TASK_KIND_NOT_REGISTERED`·
`EVIDENCE_ASSET_NOT_PERMITTED`·`EVIDENCE_OBSERVATION_KIND_UNKNOWN` 중 하나다. **v1 관측
등록부는 비어 있어 잘 구성된 제출도 전부 `EVIDENCE_OBSERVATION_KIND_UNKNOWN`으로
거절된다(fail-closed)** — 첫 관측 종류는 실 사용 사례와 함께 등록된다. 같은 `evidence_id`의
같은 내용 재전송은 멱등(동일 기록 반환), 다른 내용은 409 `EVIDENCE_REPLAY`.

**발의 binding.** `source="policy"` 작업 제출은 `evidence`에 정확히 `{"evidence_id": ...}`
참조를 담아야 한다(다른 모양은 400 `INVALID_EVIDENCE_REFERENCE`, 작업 미생성). admission은
저장 기록의 `outcome`·`task_kind`·`asset`·수신 시각 age(사이트 설정 `max_age_s`, 미설정 시
거절)를 대조해 실패 사유를 작업 HOLD 이유로 남긴다: `EVIDENCE_NOT_CONFIGURED`(서비스에
증거 저장이 연결되지 않음)·`EVIDENCE_NOT_FOUND`·`EVIDENCE_ASSET_MISMATCH`·`EVIDENCE_STALE`
또는 제출 거절 사유의 전달. admission을 통과해도 `POLICY_DISPATCH_ENABLED`가 False인 한
`HOLD(POLICY_NOT_ACCEPTED)`에 머문다 — 이 계약은 자동 실행을 열지 않는다.


## 10.6.1 Site Fleet marker-priority tracking (D-457)

지도 표시·대조 전용. source 설정이 있는 Fleet에 등록된다. 기존 sighting 계약은 유지한다.
Vision `vision --track`은 모서리 마커 보정 우선, 없으면 승인 사각형·차선 맞춤 보정으로 투영한다.
로봇 마커가 보이면 그것을 우선하고 없으면 익명 배경 blob으로 폴백한다.
`robot_markers`는 `robot_ids`의 중복 없는 부분집합이며 빈 대응도 허용한다.

| Method | Path | Credential | 내용 |
|---|---|---|---|
| POST | `/api/fleet/detections` | source Bearer | `OverheadDetectionsPayload` 제출. source/map/revision·1 s lease 검사 |
| GET | `/api/fleet/detections/config` | source Bearer | 해당 source의 승인 calibration 또는 null, relearn_seq |
| GET | `/api/fleet/tracking` | viewer 이상 | sources 상태·fps, robots 대조, unknown 위치 |
| POST | `/api/fleet/tracking/relearn` | operator | `{source_id}`의 배경 재학습 번호 증가 |
| GET | `/api/fleet/calibrations` | viewer 이상 | 승인 기록 목록과 `use: display-only` |
| POST | `/api/fleet/robots/{robot_id}/identify` | operator | D-472, `{color:"blue"\|"amber"}`. 해당 등록 로봇의 CORE 식별 요청을 전달한다. 한 번에 한 대, 6 s 중복 요청 409 `IDENTIFY_BUSY`. 응답 `{robot_id, request_id, state:"pending_visual_confirmation"}`는 카메라 신원 확정이 아니다. |
| POST | `/api/fleet/calibrations` | operator | source_id/map_id, map_to_image(9), image(width,height), track_bounds_m, fit_score, lens 또는 null, frame_seq 또는 null을 승인·영속 기록 |
| DELETE | `/api/fleet/calibrations/{source_id}` | operator | 승인 기록 철회·감사 |
| GET | `/api/fleet/start-points` | viewer 이상 | `{start_points, persistent}`. 저장한 무마커 시작 위치·방향, `use: reference-only`; 주행·로봇 위치 증거가 아니다 |
| PUT | `/api/fleet/start-points/{source_id}` | operator | `{map_id, calibration_revision, expected_revision: string 또는 null, x, y, yaw}`. 승인된 paint-fit 지도 내부 좌표(m), yaw(rad, -π~π). 새 기록은 expected_revision null, 수정은 읽은 revision. 응답은 저장 기록 |
| DELETE | `/api/fleet/start-points/{source_id}?expected_revision=...` | operator | 읽은 revision과 일치할 때만 삭제. 보정이 철회돼도 기록 삭제 가능 |

무마커 시작점(v1.103)은 `source_id`, `map_id`, `calibration_revision`, `revision`, `x`, `y`, `yaw`, `saved_by`, `saved_at`(Unix초), `valid`, `use: reference-only`를 반환한다. 승인된 보정이 현재 source/map과 일치하고 기록 revision과 같을 때만 valid=true다. 좌표는 지도 원점을 바꾸지 않으며, 저장은 goal·initialpose·로봇 신원 대응·주행 승인에 쓰지 않는다. 시작점에 마커는 요구하지 않는다. SQLite는 보정 DB와 같은 writable 데이터 디렉터리의 start-points.sqlite3에 저장한다. 보정이 메모리 전용이면 persistent=false이며 서버 재시작 시 사라진다. 미등록 source는 404 UNKNOWN_SOURCE, 보정 미승인은 409 CALIBRATION_REQUIRED, 지도 불일치는 409 MAP_MISMATCH, 보정 변경은 409 CALIBRATION_CHANGED, 동시 편집은 409 START_POINT_CHANGED, 범위 밖은 400 START_POINT_OUT_OF_BOUNDS다. bool/NaN/Infinity·추가 필드는 거절한다.


`OverheadDetectionsPayload`는 source_id/map_id/calibration_revision/processor_revision/captured_at/seq/status,
`detections[{x,y,footprint_m,score,marker_id?}]`(최대 16)를 싣는다. x/y는 map metres,
captured_at은 Vision 수신 시각 기반 Unix seconds다. status는 OK/LEARNING/CALIBRATION_REQUIRED/SCENE_CHANGED.
OK 외에는 검출이 비어 있고 CALIBRATION_REQUIRED에서만 calibration_revision이 null이다.
marker_id는 음이 아닌 strict 정수·프레임 내 유일이며 익명 검출에서는 생략한다. robot_id·영상은 싣지 않는다.
공유 스키마는 `contracts/foundation/core_common/protocol/overhead_detections.py`, 벡터는
`test/fixtures/protocol/overhead-detections.v1.json`이다. envelope protocol_version 1.0은 그대로다.

Fleet은 인증된 source의 marker 대응으로 `MARKER` 이름을 확정하고 없으면 신선한 같은-map pose와 익명 검출을 대조한다.
robots 상태는 MARKER/MATCHED/NO_DETECTION/NO_POSE/CAMERA_UNAVAILABLE이고 camera·pose·offset_m은 없으면 null이다.
마커 관측은 pose 없이도 표시하며 익명 이름은 odom으로 추측하지 않는다. 남은 검출은 unknown이다.
token 오류 401, source 불일치 403, map/revision/future/stale/out-of-order 409, 잘못된 body 422.
보정과 검출은 CORE pose 주입·자동 작업·주행 명령의 입력이 아니다.

## 10.7 Site Fleet CORE Agent event history (D-269 Proposed)

CORE Agent WebSocket의 pairing 및 `EventMessage` 검증을 통과한 이벤트는 Fleet SQLite의
`core_event_audit`에 append-only로 기록한다. `event_id` 재전송은 멱등이며 동일 ID에 다른
내용이 오면 거절한다. 자격 증명 필드, private key 또는 64 KiB 초과 payload는 저장하지 않는다.
SQLite `audit_id`는 재시작 뒤에도 유지되는 페이지 커서다. `--events-db`는 `--sightings-db`와
같은 영속 파일로 설정할 수 있다. CORE Agent pairing을 켠 CLI는 `--events-db`를 요구한다.

| Method | Path | Credential | 요구사항 |
|---|---|---|---|
| GET | `/api/fleet/events?after_id=&limit=&robot_id=` | console Bearer token | 인증된 CORE 이벤트 감사 기록을 audit cursor 순으로 조회. `limit` 1–200, 기본 100 |

조회 응답은 `events`, `next_cursor`, `has_more`를 포함한다. 이벤트 수신/저장은 DDS 접근이나
동작 명령을 수행하지 않는다. SQLite 쓰기 실패 시 Agent 이벤트를 성공 수신으로 응답하지 않는다.

---

# 10.8 Site Fleet task submission, role authorization, and readback (D-276 Accepted)

Fleet `GET /api/fleet/state` robot rows also expose optional `capabilities`: the
authenticated CORE CAP-001 object, or `null` when it cannot be read. Presentation
may reuse this value for up to 5 seconds; an absent field denotes an older Fleet.
This value is not permission to move. Immediately before goal dispatch (including
yielding to a bay), Fleet reads CAP-001 again and requires
`navigation.goal_navigation == true`. Formation planning similarly requires
leader `swarm.lead` and each follower `swarm.follow` before opening relay streams.
Missing/false flags are refused as `NOT_SUPPORTED`; transport errors remain errors.
CORE still performs its own authorization, localization, and safety checks.

When durable task storage is configured, the operator navigation route creates a
persistent task before contacting CORE. The browser sends a fresh
`Idempotency-Key`; repeating the same request with the same authenticated
operator identity returns the original task without issuing another robot
command. Reusing a key for a different request returns `409 IDEMPOTENCY_CONFLICT`.

| Method | Path | Credential | Requirement |
|---|---|---|---|
| GET | `/api/fleet/session` | any configured site-user bearer | Returns only the authenticated `principal_id` and role for the current console session. |
| GET | `/api/fleet/auth/connection` | none | D-473 (v1.108): `{mode: "development"\|"paired"}` with `Cache-Control: no-store`. `development` only when Fleet started with both `ROSY_DEPLOYMENT=development` and `--connection-mode development`; any other combination, or a missing setting, is `paired`. |
| POST | `/api/fleet/auth/development-session` | none (development mode only) | D-473 (v1.108): 201 `{token, principal_id, role: "operator", expires_at}` with `Cache-Control: no-store`. `principal_id` is `development-<8 hex>`; the token is returned once and lives 1 h in Fleet memory only (gone on restart). The caller address (the last `X-Forwarded-For` entry when Fleet runs with `--lan-camera-proxy` behind the site proxy, otherwise the TCP peer) must be loopback, RFC1918, link-local or the Tailscale tailnet `100.64.0.0/10`; `Host` must be a LAN IP literal, `localhost`, a `.local` name or the host name, and a present `Origin` must equal `Host`; otherwise, and always in paired mode, 403 `FORBIDDEN`. More than 6 requests per address per minute is 429 `RATE_LIMITED` with `Retry-After: 60`. At most 8 sessions are live; a ninth evicts the oldest. The session is a named operator: it passes the named-operator gate (missions included), and the issue and every later POST are written to the API audit under that principal; an unavailable audit is 503 `AUDIT_STORAGE_UNAVAILABLE` and no session. Robot credentials (`robots.yaml`, D-361 enrollment) and stop paths are unchanged. |
| POST | `/api/fleet/robots/{robot_id}/goal` | `operator` bearer + `Idempotency-Key` | Validates the configured robot and finite goal, durably accepts the task as `QUEUED`, then lets the dispatcher request a CORE goal. |
| POST | `/api/fleet/robots/{robot_id}/route` | `operator` bearer + `Idempotency-Key` when durable tasks are configured | D-463 (v1.100): body `{edges: [edge_id, ...]}` of 1 to 8 stored lane-graph edge ids; extra fields 422. Each edge must exist and its `to` must equal the next edge `from`, or 400 `ROUTE_UNKNOWN_EDGE` / `ROUTE_DISCONTINUOUS`. Fleet expands the stored polyline and submits only the next point about 0.20 m ahead, yaw equal to the tangent, through the existing goal path. It does not submit the far junction as that goal. The fresh snapshot must be `LOCALIZED` with `pose_frame` `map` and within 0.08 m of the polyline; otherwise 409 `ROUTE_POSE_UNTRUSTED` or `ROUTE_OFF_LANE` and CORE is not called. A snapshot with no localization block is refused. Within 0.05 m of the end the response is 200 `ROUTE_COMPLETE` and no goal. `GoalRequest` stays `{x, y, yaw}`. |
| GET | `/api/fleet/site-map/active` | any configured user bearer | D-488 (v1.111): the active `rosy.site_map/1` (places `{id, name, x, y, yaw?, kind park/charge/stop/junction/turnaround}`, edges `{id, from, to, polyline, direction one_way/two_way, width_m, speed_cap_mps, drive_mode lane/free, robot_kinds?}`, optional `turn_bans {at, from_edge, to_edge}`) with `version`, `sha256`, `activated_by`, `activated_at`. Places are more than 0.05 m apart and every edge is longer than 0.10 m between its places. 404 `SITE_MAP_NOT_ACTIVE` when the site has none. Errors here and on `/trip` are `{"detail": {"code", "detail"}}`. `GET /api/fleet/site-map` (D-257 camera rectangle) is unchanged. |
| GET / PUT | `/api/fleet/site-map/draft` | GET any user; PUT named `operator` | D-488 (v1.111): one editable draft. PUT `{map, expected_revision}` (body at most 2 MiB, else 413 `SITE_MAP_TOO_LARGE`); the map is validated or 422 `SITE_MAP_INVALID` with `detail.errors [{loc, msg}]` (no submitted values). A stale `expected_revision` is 409 `SITE_MAP_DRAFT_CHANGED`. Each save is a recorded site map event. A draft is never used for planning. |
| POST | `/api/fleet/site-map/activate` | named `operator` | D-488 (v1.111): `{expected_revision}` copies the saved draft into a new immutable version that becomes active; audited. 409 `SITE_MAP_NO_DRAFT`, `SITE_MAP_DRAFT_CHANGED`, or `SITE_MAP_ROUTE_ACTIVE` while a lane route (`/route`) was stepped in the last 30 s; 422 `SITE_MAP_UNPLANNABLE` when the planner cannot use the map. The first version may come from `fleet console --site-map-import <lane_graph.yaml>` when the store is empty. `/route` reads the active map's edges and answers 409 `SITE_MAP_NOT_ACTIVE` without one. |
| POST | `/api/fleet/robots/{robot_id}/trip` | named `operator` | D-488/D-490 (v1.111): body `{to: place_id or {x, y, yaw?}, via?: [place_id] (max 8), arrive_yaw?, speed_cap?, execute?: false}`. Plans one layered lane-state A* over the vias and the goal on the active map from the robot's fresh `LOCALIZED` map pose (start snaps within half the lane width) and returns 200 `{plan_id, map_version, segments [{edge_id, forward, s_from, s_to}], places, actions [{place_id, action straight/left/right/uturn/stop, theta_deg}], length_m, eta_s, expires_at}`; a robot already on the goal place gets an empty plan. Nothing is sent to CORE. Refusals are 422 `{code, detail}`: `TRIP_START_OFF_MAP`, `TRIP_HEADING_CONFLICT`, `TRIP_OFF_MAP`, `TRIP_UNKNOWN_PLACE`, `TRIP_NO_ROUTE` (`detail.segment`, `detail.unblock_would_help`), `TRIP_ARRIVE_YAW_UNREACHABLE`, `TRIP_NO_ACTIVE_MAP`, `TRIP_POSE_UNTRUSTED` (also a pose without yaw); 404 `UNKNOWN_ROBOT`; an unexpected planner failure is 500 `TRIP_PLAN_FAILED` in the same body. Every plan and refusal is recorded (last 1000 within 30 days). Costs come from site config `fleet.routing`. |
| POST | `/api/fleet/trips/{plan_id}/start` | named `operator` | D-491 5 (v1.112, was a 501 reservation in v1.111): runs the stored plan through the Fleet trip loop; the trip id is the `plan_id`, audited. Checks in order: 404 `TRIP_PLAN_UNKNOWN`, 409 `TRIP_ALREADY_STARTED`, 422 `TRIP_PLAN_EXPIRED` (more than 30 s after the plan), 422 `TRIP_MAP_CHANGED` (active map version differs), 422 `TRIP_ROBOT_CAPS_UNKNOWN` (no D-491 1 capability fields), 422 `TRIP_MODE_UNSUPPORTED` (`detail.edge_id`; an edge outside the robot's `drive_modes`/kind, a `lane` U-turn `LANE_UTURN`, a `lane` turn over 150° `LANE_TURN_TOO_SHARP`, a `lane` left/right on a robot without `junction_turn: true` `JUNCTION_TURN_UNSUPPORTED` (D-492 3), or a `lane` trip not ending at a place `LANE_END_NOT_A_PLACE`), 409 `TRIP_BUSY` (one open trip per site, `detail.trip_id`), 422 `TRIP_POSE_UNTRUSTED` (D-491 3 map pose not `LOCALIZED`). 200 is the trip view `{trip_id, plan_id, robot_id, started_by, state started/running/arrived/stopped/failed/canceled, reason, detail, map_version, plan {segments, places, actions}, segment_index, current_edge, drive_mode, next_place, next_action, hold, pose {x, y, yaw, state, source, dead_reckon_m, age_s}, caps, created_at, updated_at}`. Every 0.5 s: `lane` segments send the next place's action through robot `POST /api/v1/line-follow/junction` within 0.6 m of it (`straight`; `left`/`right` with `turn_deg` = the map's signed junction angle, D-492; `stop` at the last place), and reads the snapshot's `line_follow.junction`: `aborted` or `unresolved`, or `waiting` for 10 s, ends the trip `stopped` (`reason: junction`, `detail.junction_state`); `free` segments send the D-463 point 0.20 m ahead as a navigation goal. A pose that is not `LOCALIZED` or more than half a lane width off the lane ends the trip `stopped` (`reason: pose`) and nothing more is sent. A robot answering 404 to the junction call ends it `failed` (`TRIP_ROBOT_JUNCTION_UNSUPPORTED`). A Fleet restart turns an open trip into `stopped` (`reason: restart`); it is never resumed. `/trip` with `execute: true` still answers 501 `TRIP_EXECUTION_NOT_AVAILABLE`. |
| POST | `/api/fleet/trips/{trip_id}/cancel` | named `operator` | D-491 5 (v1.112): ends an open trip `canceled` (`detail.canceled_by`) and sends `stop` (lane) or a navigation cancel (free); `detail.stop_sent` false with `detail.error` when the robot did not take it. 404 `TRIP_UNKNOWN`, 409 `TRIP_NOT_RUNNING`. Audited. |
| POST | `/api/fleet/trips/{trip_id}/confirm-replan` | named `operator` | D-491 5 / D-489 9 (v1.112): a blocked remaining edge (or a changed map) replans only at the next place; a changed route sets `hold {reason: replan, plan, map_version, length_m, eta_s}` and the robot is held there (`stop`, or a goal at the place). This call switches the trip to `hold.plan`. 409 `TRIP_NO_REPLAN`, 409 `TRIP_REPLAN_FAILED` (`hold.plan` null, `hold.code` from the planner; cancel instead), 409 `TRIP_MAP_CHANGED` (the map changed after the hold; the trip plans again at the same place), 409 `TRIP_NOT_RUNNING`. Audited. |
| GET | `/api/fleet/trips` · `/api/fleet/trips/{trip_id}` | any configured user bearer | D-491 5 (v1.112): `{running: trip view or null, trips: [recent trip views]}`; one trip view, or 404 `TRIP_UNKNOWN`. While a trip is `started`/`running`, `POST /api/fleet/site-map/activate` answers 409 `SITE_MAP_ROUTE_ACTIVE` (replaces the v1.111 "`/route` stepped in the last 30 s" guard; `/route` itself is unchanged). |
| POST | `/api/fleet/do` (when `do` is `navigate`) | `operator` bearer + `Idempotency-Key` | Uses the same task service; each navigation step gets a deterministic child key from the request key and step position. |
| GET | `/api/fleet/tasks/{task_id}` | any configured user bearer | Returns the durable task projection and append-only status history. |
| POST | `/api/fleet/tasks/{task_id}/cancel` | `operator` bearer | Cancels a task only while it is still queued; it does not cancel a goal already dispatched to CORE. |
| POST | `/api/fleet/cancel-all` | `operator` bearer | D-421 (v1.81): non-latching site-wide driving cancel. In order: queued tasks of every robot become `CANCELED` with reason `FLEET_CANCEL_ALL` and the operator as actor (dispatch latch and generation unchanged); an open formation is stopped; then per robot, concurrently, `POST /api/v1/swarm/cancel`, `POST /api/v1/navigation/cancel`, `PUT /api/v1/line-follow/mode {mode: OFF}`, each attempted even when an earlier one failed. It never calls `safety/stop`/`safety/release`, `/mode`, signals or OMX stop. Each request writes a durable record in the task journal database (`fleet_cancel_all`: id, principal, opened/closed times, robot ids, canceled queued task ids, robots whose navigation cancel was answered; closed records older than 30 days are pruned when a window opens) and tags the in-flight dispatch attempts of those robots by `(task_id, attempt_id)` (`ACCEPTED`, `RUNNING`, mid-dispatch `QUEUED`, and `UNKNOWN` changed since the window opened or not already canceled). Dispatched tasks are not rewritten by Fleet: a correlated CORE `nav.canceled` (evidence that a cancel was issued, not of standstill, D-298) moves a tagged task to `HOLD` with reason `FLEET_CANCEL_ALL`, which releases its robot claim, so in-flight robots become dispatchable once CORE confirms the cancel. The event must match the tagged attempt, its `data.source` (when present) must be `api:*`, and the window must be open, or closed at most 30 s ago with that robot's navigation cancel answered or a fence re-cancel; other later cancels stay `UNKNOWN`. A dispatch started inside the window is tagged before its CORE goal call, and tagging settles an attempt whose `nav.canceled` already arrived during the window. Correlated events and dispatch receipts arriving after `HOLD(FLEET_CANCEL_ALL)` are logged, not applied. If the record cannot be written the fanout continues and the response carries `record_error: "CANCEL_ALL_RECORD_UNAVAILABLE"`; without that event the task stays as it was (`ACCEPTED`/`UNKNOWN`), the robot stays claimed and the task needs reconciliation (no operator reconcile route exists yet). An untagged `nav.canceled` still yields `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`. `tasks.awaiting_core_result` lists per robot the `ACCEPTED`/`RUNNING` tasks plus `UNKNOWN` tasks changed since the window opened. A dispatcher CORE goal call that overlaps the request (including a task submitted and dispatched inside the window) is inspected when it ends: an explicit CORE reject stays `FAILED`/`COMMAND_REJECTED`; a dispatch left in Fleet's own traffic queue with no live CORE goal becomes `CANCELED`/`FLEET_CANCEL_ALL`; otherwise the task is tagged, Fleet sends `navigation/cancel` to the robot and to any robot it sent to a bay for it, and the task becomes `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH` (no retry); a goal call that raised is re-canceled the same way and keeps its existing classification. 200 even on partial failure: `{cancel_all_id, record_error, cancelled, total, evidence: "CORE_REPLY_ONLY", robots[{robot_id, result: cancelled\|failed\|unreachable, steps{swarm, navigation, line_follow: {ok, error?{reachable, sent?, code, message}}}, tasks{awaiting_core_result[]}}], formation{stopped, state, error?}, tasks{canceled[], error}}`; `sent: false` marks a step Fleet's D-361 address gate refused locally (`ADDRESS_UNVERIFIED`; `line-follow/mode` is not a stop path because a path-level gate would also allow turning it on). `cancelled` = all three CORE calls replied 2xx; `unreachable` = no call got a reply; otherwise `failed`. A reply is not physical stop evidence (D-298). Repeating the request is safe. Normal audit gate applies (`503 AUDIT_STORAGE_UNAVAILABLE`); the D-330 audit exception stays with `/api/fleet/estop`. |
| GET | `/api/fleet/line-stuck` | any configured user bearer | D-407 (v1.77): returns the board as of the last shared gather (it does not contact the robots) as `{pending[], answers[], observed_age_s}`; `observed_age_s` is null before the first gather. D-438 (v1.91): one shared gather feeds both `GET /api/fleet/state` and the stuck resolver loop and is reused for up to 1 s, so with the resolver running the board is at most about 1 s old even when no console is open. `pending` has one row per robot whose CORE `line_follow.stuck` is open: the CORE `LineStuckStatus` fields plus `robot_id`, `front_clearance_m`, `rear_clearance_m`, `turn_clearance_m`, `rear_blind_m`, `preview_seq` (from the `nav.line_stuck_opened` FleetAgent event, `null` when not received; `opened_event` says which), `robot_online` (false = last value kept while the robot is unreachable), `observed_age_s`, `fleet_answer` (the last forwarded answer for this stuck id; `ESCALATE` rows are not answers and are skipped) and `resolver` (D-438, see `.../line-stuck/claim`). `answers` is the recent forwarded-answer record `{robot_id, stuck_id, decision, principal_id, accepted, outcome, code, message, audit_id, tier, rule, escalated, at}` (`accepted` null = outcome unknown). The same row appears as `line_stuck` on each robot of `GET /api/fleet/state`. |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/decision` | `operator` bearer | D-407 (v1.77): `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT}`; `stuck_id` 1-64 chars of `[A-Za-z0-9_.:-]` (CORE ids are `stuck-<12 hex>`), extra fields 422. Forwarded unchanged to that robot's `POST /api/v1/line-follow/stuck/decision` with the robot credential; Fleet never refuses on CORE's behalf. 200 `{robot_id, actor_id, answer, result}` (`result` is CORE's body incl. `outcome`). A CORE 409 (`STUCK_ID_MISMATCH`, `STUCK_DECISION_REFUSED` with its reason, `EMERGENCY_ACTIVE`, `CALIBRATION_ACTIVE`) is returned as 409 `{code, message, robot_id, robot_status}` with CORE's code and message verbatim; other robot error statuses are 502 with the same body, unknown robot 404. A transport failure is 502 `{code, message, robot_id, transport}`: `ROBOT_UNREACHABLE` when the connection was never made (not delivered), `STUCK_DECISION_OUTCOME_UNKNOWN` on a timeout or a dropped reply (CORE may have applied the answer; re-read the stuck before answering again). Every forwarded answer is recorded with the site principal in memory and, with durable task storage, in the `fleet_line_stuck_answers` table of the Fleet journal database, keyed by the API audit `request_id` (§10.10). D-438 (v1.91) nullable columns: `tier` (`human` for this route, `rule` for a resolver answer), `rule` (`R1`–`R3`, resolver only), `escalated` (hand-off reason). Every resolver hand-off to a human is its own row with `decision: "ESCALATE"`, `accepted` null, `tier: "human"`, `escalated` = the reason and `principal_id: "fleet-resolver"`. A database created before v1.91 gains the three columns when Fleet opens it (rows written before stay null). |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/claim` | `operator` bearer | D-438 (v1.91): `{stuck_id}` — 사람이 그 막힘을 맡는다. 판단기는 맡은 막힘에 답하지 않고 `human_claimed` 로 올린다. 200 `{robot_id, stuck_id, claimed_by}`, 모르는 로봇 404 `UNKNOWN_ROBOT`. `.../line-stuck/decision` 도 404 확인 뒤 먼저 맡고, CORE 전달이 실패해도 맡음을 유지한다. 로봇 행 `line_stuck.resolver` = `{tier, rule, decision, escalated, at}` 또는 null(escalated 사유: `no_rule`, `rule_budget`, `deadline`, `restuck_after_resume`, `estop`, `calibration`, `no_resolver_token`, `human_claimed`, `core:<CODE>`). 판단기 답은 `principal_id: "fleet-resolver"` 로 기록하고, 전송 실패는 `ROBOT_UNREACHABLE` 이면 `accepted=false`, 아니면 null. 설정: `robots.yaml` 의 `resolver_token`(비어 있지 않은 따옴표 문자열, `token`·`fleet_pairing_token` 과 달라야 함), `fleet console --stuck-resolver`. `robots.yaml` 로봇만 판단기 클라이언트를 가진다(등록 D-361 로봇은 아직 없음) |

Task status is the shared `FleetTaskStatus` enum: `REQUESTED`, `QUEUED`,
`ACCEPTED`, `RUNNING`, `COMPLETED`, `FAILED`, `UNKNOWN`, `HOLD`, `CANCELED`,
or `EXPIRED`. The normal path is `REQUESTED` → `QUEUED` → `ACCEPTED`; a queued
task may instead become `CANCELED` or `EXPIRED`, and dispatch uncertainty is
`UNKNOWN`. `QUEUED` means Fleet durably recorded the request and has not yet
dispatched it. `ACCEPTED` means CORE returned an explicit receipt; it does not
mean the task started or completed. `RUNNING` and `COMPLETED` require separate
CORE status/final-result evidence. `CANCELED` and `EXPIRED` apply only before
dispatch. An ambiguous post-dispatch result is `UNKNOWN` and is never retried
automatically. This Fleet task enum does not change the robot DDS/WSS envelope
`protocol_version`.

The browser treats `QUEUED` as durably accepted by Fleet and shows the task ID,
server-computed `queue_position`, wait reason, blockers when available, and
queued-only cancellation. The position orders queued `READY` and
`WAITING_TRAFFIC` tasks by server priority and FIFO timestamp; it is not an
execution-time estimate and does not override robot availability or traffic
eligibility. Before cancelling, the browser reads the authenticated task
projection again; if the task has
already left `QUEUED`, the operator action uses the robot cancel route. Robot
cancel/stop and site E-Stop remove undispatched queued work before sending the
CORE safety request. An `UNKNOWN` task is shown as requiring manual CORE status
verification; the UI never turns a command receipt into completion.

The site Compose configuration loads an individual `site-users.yaml` registry.
Each row binds a unique `principal_id` and role (`viewer`, `operator`,
`policy-admin`, or `service`) to a SHA-256 digest of one high-entropy bearer token. The raw
token is delivered separately and is never stored in that file. `viewer` may
read Fleet state, evidence, and task history. `operator` may also request,
cancel, and stop work. A `service` principal may create and resolve `cell_job`
proposals only; it cannot admit work. Cell Job admission requires a different
named `operator` principal. `policy-admin` may not issue robot commands; no
policy mutation endpoint exists yet. The separate `/registry` endpoint
continues to use its own server-side credential.

Authenticated `POST /api/fleet/*` requests other than source-authenticated
`POST /api/fleet/sightings` and read-only mDNS observation
`POST /api/fleet/discovery/scan` attempt to append an `INTENT` and a `RESULT` row to the durable
API audit. The rows contain principal, role, method, path, and response code,
not the bearer token or request body. If the intent cannot be persisted, Fleet
normally returns `503 AUDIT_STORAGE_UNAVAILABLE` before calling CORE. The
dedicated `POST /api/fleet/estop` is the D-330 exception: an authenticated
operator's stop fanout continues on audit-storage failure, as specified in
§10.11. `POST /api/fleet/do` (including an `estop` step) retains the normal
audit gate. If the result row
cannot be written after an action, the intent remains pending and the outcome
must be reconciled; it is not safe to infer failure or retry.

The legacy shared `--token` mode is not per-user authorization and does not
satisfy D-276. Site Compose requires `--users-file`; replacing or removing a
digest and restarting Fleet rotates or revokes that user. Policy submissions
require a stored `evidence_id` reference (§10.6.2) and remain `HOLD` — with the
evidence admission reason, or `POLICY_NOT_ACCEPTED` when the admission itself
passes — while D-268 is Proposed and `POLICY_DISPATCH_ENABLED` stays false. A command timeout or unclassified post-dispatch error becomes
`UNKNOWN`; the server does not retry it. For a dispatched Pinky navigation task,
Fleet keeps `task_id` as its ledger identity and sends the current `attempt_id`
as CORE `correlation_id`. CORE echoes that value in correlated `nav.started`,
`nav.completed`, and `nav.failed` event data. Paired CORE events update the
matching robot and current attempt in Fleet's durable task projection; duplicate
event IDs and out-of-order sequences do not regress the projection. Events with
unknown, stale, or mismatched attempt IDs do not change a task. A cancel request
event leaves the task `UNKNOWN` while a correlated final result is pending; if
none is delivered, it remains `UNKNOWN` for reconciliation. None of these task
states is a physical stop readback. HTTP ambiguity remains
`UNKNOWN` and is not automatically retried. The dated P0
[boundary trace](../validation/2026-09-27-platform-p0-task-result-trace.md)
records the pre-change gap and counterexamples.

CORE binds the ID to one Nav2 action generation. An active Fleet-correlated
goal cannot be replaced by an uncorrelated moving goal; after a cancel request,
later goal generations carry no previous attempt ID. Fleet stores each CORE
event before projecting it. If projection temporarily fails, the durable audit
log is retried on subsequent CORE heartbeats and replayed after Fleet restart;
delivery does not depend on CORE retrying a sent event.

On Fleet startup, a persisted `REQUESTED` task is changed to `UNKNOWN` with a
`fleet-recovery` history entry; startup never assumes that it is safe to resend.

## 10.9 Site Fleet LAN discovery

The Ubuntu host Avahi bridge resolves `_rosy._tcp.local` and submits one full
scan every 15 seconds. `DiscoveryScanPayload.devices` contains at most 64
objects with `name`, optional `hostname`, private LAN IPv4 `address`, `port`,
`stage`, `release`, and `network=sta`. The host scanner has one dedicated Bearer
credential, separate from site users, CORE REST, and FleetAgent pairing.

| Method | Path | Authority | Result |
|---|---|---|---|
| POST | `/api/fleet/discovery/scan` | host scanner Bearer only | Replace the short-lived discovery scan; 401 invalid credential, 400 invalid observation |
| GET | `/api/fleet/peers` | site viewer+ | D-452 `PeerCatalogue`: bounded role catalogue, separate discovery/approval/readiness; no credentials or automatic enrollment |
| GET | `/api/fleet/discovery` | site viewer+ | `{scanner_online, scanner_state, scanner_age_s, devices[]}` with status `registration_pending`, `pairing_pending`, `verified_online`, or `conflict` |
| GET | `/api/fleet/discovery/addresses` | site viewer+ | `{scanner_state, all_outside, robots[]}`: per roster robot `{robot_id, origin, pinned, pinned_is_name, status, in_subnet, seen_addresses[], movable}`; status `in_scanned_subnet`, `outside_scanned_subnets`, `seen_at_other_address`, or `unknown`. Explains only: nothing resolves or follows a new address (D-361 3, D-370 5.3); no credentials |

The scan expires after 45 seconds. Empty successful scans remove prior rows;
scanner failure sends nothing and later reads report `scanner_online=false`.
`scanner_state` is `never_seen` (no scan since Fleet started, `scanner_age_s`
null), `online`, or `expired` (the lease ran out; `scanner_age_s` is the age
of the last scan in whole seconds). The console raises an alarm on `expired`
because discovery and move-address stop until the scanner returns.
Advertisement data is not identity evidence. `verified_online` requires an
existing `robots.yaml` endpoint and an online authenticated FleetAgent HELLO
with a device UID and matching device name while the advertised stage is
`CORE_READY`. The endpoint is matched by advertised IP or `.local` hostname and
port. A duplicate advertised name or identity mismatch is a conflict. The
discovery routes never add an endpoint, assign a robot number, expose a token,
or command CORE. Cross-VLAN, blocked multicast, and AP mode use manual endpoint
configuration and the existing outbound FleetAgent path.

### D-452 역할 목록 (v1.94)

정본은 `core_common.protocol.network_peers`의 `PeerObservation`, `PeerSummary`,
`PeerCatalogue`이다. 기존 scanner payload의 `devices[]`는 로봇 등록 관찰로 유지한다.
선택적 `services[]`는 역할별 관찰이며 두 배열의 합계가 최대 64개이다. 생략하면 빈 배열이다.
`services[]`는 non-robot 5역할만 전달한다. 로봇 관찰은 기존 `devices[]`에서 한 번만 세며,
선택적 `transport=http|https`는 검증한 TXT의 TLS 요구를 표현한다(기존 생략 행은 legacy HTTP).
이는 TLS 인증 접속 성공이 아니다. catalogue는 이 기존 로봇 관찰을 역할 row로도 표현한다.
한 번의 성공한 scan이 두 관찰 목록을 교체하며 같은 45초 lease를 사용한다.
클라이언트 앱의 session presence를 scanner가 임의로 제출할 수 없다.

`PeerCatalogue`는 `{peers[], scanner_state, scanner_age_s}`이다. `scanner_state`는
`never_seen|online|expired`, age는 유한한 0 이상 초 또는 null이다. 각 row는
`name`, `role`(`robot|fleet|overhead-camera|dock|signal|model-host|pilot|cam`),
`transport`(`http|https|ssh|session`), nullable `service_type`, `hostname`, `address`, `port`,
nullable `peer_id`, `provenance`(`mdns|approved-directory`),
`freshness`(`fresh|expired|conflict|unavailable`), `approval`(`approved|unapproved`),
`readiness`(`unknown|verified|unreachable`)를 가진다. mDNS network endpoint는
정규화된 `.local` 이름, RFC1918 IPv4, 1..65535 port이다. 승인 directory는 기존 승인된
정규화 DNS 이름과 port를 유지하며 현재 미해결 address는 null로, 확인된 VPN/DNS 주소는
unicast 힌트로 표시할 수 있다. 둘 다 역할별 정본 service type과 transport를 검사한다.
기존 승인된 literal-IP profile은 `hostname=null`과 실제 `address`로 이주 전 상태를
보존하며 DNS 이름을 만들어 넣지 않는다. 정상 선택 화면은 승인 `peer_id`·이름을 사용한다.
이름은 제어 문자 없는 1..96자이다. token·key·개인 경로·임의 TXT를
반환하지 않는다. 앱 presence는 `transport=session`이며 inbound endpoint가 모두 null이다.

광고는 `peer_id`나 승인·검증 상태를 만들지 않는다. 승인 신원은 기존 directory가 제공하며,
`verified`는 fresh인 승인 대상의 endpoint owner가 실제 인증 접속을 확인했을 때만 가능하다.
충돌·만료·오류에서는 verified를 유지하지 않는다. 목록 조회는 viewer에게 허용하지만,
선택 이후 접속·쓰기·SSH 배포는 각 endpoint의 기존 인증과 운영자 권한을 그대로 적용한다.
다른 망의 approved DNS/profile 경로와 실제 연결 수락은 이 LAN 조회의 성공만으로 증명하지 않는다.

관제의 `--approved-peer-directory-file`은 배포 관리자가 준비한 metadata-only JSON 배열을
시작 시 읽는다(예: `deploy/site/approved-peers.json.example`). 최대 64행·1 MiB이며
각 행은 approved-directory/approved, unknown readiness와 unavailable freshness만 허용한다.
중복 JSON 키·신원·역할/hostname 소유 충돌·credential/extra·허위 live 상태는 시작을 거부한다.
이 파일은 토큰을 발급하거나 기존 endpoint를 변경하지 않으며 쓰기 API가 없다. 이후 접속은
해당 장비 owner의 기존 승인 profile과 인증을 따른다. IP/URL 가져오기는 운용자의 정상 선택 단계가 아니다.

MODEL은 `_rosy-model._tcp`, `product=rosy`, `role=model-host`, `proto=ssh/2`,
`tls=none`, `transport=ssh`를 필수로 광고한다. 실제 sshd listener의 SRV port만 제공하며
추론 HTTP API가 아니다. `tls=none`은 SSH 호스트 키 인증을 생략한다는 뜻이 아니다.
기존 승인 논리 이름의 HostKeyAlias·known_hosts·StrictHostKeyChecking이 계속 신원을 검증한다.

CORE `fleet.discovery`의 기존 `expected_hostname`·`ca_file`은 신원 pin으로 유지한다.
다른 망의 승인 경로는 선택적 `allow_dns_fallback: true`와 `approved_directory_url`
(`wss://<approved DNS or IP>:<port>/ws/robots`, userinfo/query/fragment 없음)을 함께
로컬 승인 profile에 명시한다. 기본은 fallback 없음이며 legacy `hub_url`을 대신 쓰지 않는다.
일치하는 광고가 없을 때만 이 대상의 `/healthz`를 기존 CA와 expected_hostname SNI로
검증한 뒤 같은 신원으로 WSS를 연다. 충돌·잘못된 일치 광고·인증서·health role·401/403
실패는 이 경로로 우회하지 않는다. health 요청에는 Agent token을 넣지 않으며 신원 검증
전 HELLO/credential을 전송하지 않는다. 이것은 새로운 등록/credential 생성 규약이 아니다.


## 10.10 Site Fleet intent interpretation and message boundaries (D-293 Accepted, D-316 Accepted)

The site API accepts a domain intent and lets Fleet interpret it. For the current
navigation request, CORE's typed `GoalRequest` contains goal intent and may
carry an optional `correlation_id` supplied internally by Site Fleet for the
current dispatch attempt. The public `/api/fleet/*` intent schema remains
limited to goal intent. The correlation value is
tracing metadata: it does not choose the goal, authorize motion, or claim an
execution result. The authenticated principal supplies the actor identity.
Fleet derives source, priority, task ID, eligibility, and dispatch state from
server configuration and policy. Clients cannot submit `priority_class`, worker
identity, arbitrary source identity, ROS/DDS topics, `cmd_vel`, raw camera
frames, or a claimed execution result. `GoalRequest` is not a general command
envelope.

Goal coordinates must be finite JSON numbers; booleans and non-finite values
are invalid. The direct `/api/fleet/robots/{robot_id}/goal` route rejects
undeclared body fields with HTTP `422`. `/api/fleet/do` rejects unknown intent
fields with HTTP `400` (`UNKNOWN_FIELD`) and invalid navigation numbers with
HTTP `400` (`INVALID_NUMBER`). These requests are rejected before a CORE
navigation call.

The interpreter returns stable `400` error codes: `UNKNOWN_VERB` for an unsupported action, `UNKNOWN_FIELD` for undeclared fields, `MISSING` for required values, `FORBIDDEN` for low-level robot payloads or unsupported peer operations, `INVALID_NUMBER` and `INVALID_FIELD_TYPE` for typed value failures, and `TOO_LONG` when the ordered plan exceeds eight steps.

`POST /api/fleet/do` OpenAPI describes either one intent step or an ordered
`steps` array containing 1 through 8 steps. Each step selects exactly one
supported `do` verb, exposes only that verb's fields, and rejects additional
properties. The schema is generated by `core_common.intent.request_schema()`
from the same verb table used by `interpret()`. Before dispatch, the interpreter
checks field types: non-finite or non-numeric values (including booleans in
numeric fields) return `400 INVALID_NUMBER`; mismatched string, integer, or
string-array fields return `400 INVALID_FIELD_TYPE`. Omit optional fields rather
than sending `null`. More than eight steps returns `400 TOO_LONG` before any CORE
dispatch. Verb-specific required fields and forbidden values remain checked by
the interpreter; OpenAPI does not replace those runtime checks.

The decision path is:

```text
authenticated intent
  -> role and typed-input validation
  -> append-only API audit + durable SQLite task
  -> Fleet-derived eligibility and priority
  -> existing per-robot CORE HTTPS REST contract
  -> explicit CORE receipt or UNKNOWN reconciliation
```

`QUEUED` means Fleet durably recorded the request and has not dispatched it.
`ACCEPTED` means CORE explicitly acknowledged receipt, not that execution began
or finished. `RUNNING`, `COMPLETED`, and `FAILED` require CORE navigation
events correlated to the current dispatch `attempt_id`; Fleet applies them to
the matching durable task history. A `nav.canceled` request event alone yields
`UNKNOWN` while the action result is pending. D-316 covers this Site Fleet
REST/event path; it does not activate D-297's PRT-004 envelope correlation or
ACK protocol. Any ambiguous result after dispatch stays `UNKNOWN` and is not
automatically retried. Fleet SQLite and append-only history remain the source
of truth. Priority is server-derived and never a public request field. Physical
stop evidence remains a separate readback.

Transport and payload ownership remain separate:

| Producer → consumer | Contract | Carries | Does not carry |
|---|---|---|---|
| Browser/operator → Site Fleet | HTTPS `/api/fleet/*`, per-principal Bearer (D-276) | typed task intent, idempotency key | DDS, command priority, raw video |
| Ceiling phone → overhead ingress | `rosy-overhead/1` WSS | latest JPEG frame, source-scoped credential | Fleet task or CORE command |
| Vision → Site Fleet | HTTPS sighting REST, `SiteSightingPayload` (D-257) | derived pose and map/calibration lineage | image bytes, caller-selected source, policy approval |
| CORE Agent → Site Fleet | existing PRT WebSocket `Envelope` | CORE heartbeat/event protocol | Site task queue state |
| Site Fleet → robot CORE | configured CORE HTTPS REST | CORE-supported robot request | direct DDS participation |

The PRT envelope's `protocol_version` remains `1.0`. `SiteSightingPayload` and
`FleetTaskStatus` are typed contracts but do not make their REST fields part of
the robot envelope. DDS remains inside CORE and robot runtime (D-59/D-269).

### 10.11 Fleet dispatch control and explicit rearm (D-330)

The Fleet task dispatcher starts closed on each process start. A site stop also
closes dispatch and advances a durable, monotonically increasing generation.
Claims are admitted only while dispatch is enabled and are stamped with the
current generation. A stop invalidates pre-send claims. A claim persisted as
`DISPATCHING` or `UNKNOWN` remains held until its result and resource state are
reconciled; rearm is refused while any such action claim remains.

| Method | Path | Authority | Result |
|---|---|---|---|
| GET | `/api/fleet/dispatch-control` | site viewer+ | `{authority_epoch, generation, dispatch_enabled, reason, queued_tasks, unresolved_actions, rearm_available}` |
| POST | `/api/fleet/dispatch/rearm` | site operator | explicitly opens dispatch at a new generation and attempts configured local OMX re-arm; stale generation, unresolved action, or any local re-arm failure returns 409 |

The rearm request is `{ "expected_generation": <integer >= 0> }`. The caller
must read the current generation and explicitly submit it. The response is the
new control state. The authority epoch advances at Fleet process startup; the
separate generation advances on startup hold, site stop, and successful rearm.
An old request cannot reopen a newer stop. Operator rearm is audited using the
normal mutation audit rule. If local OMX instances are configured, Fleet
attempts `RearmLocal` on each with the new epoch/generation and exposes their
receipts. Any missing/failed receipt re-trips Fleet dispatch and fans out a
local stop rollback. Empty OMX inventory remains `NOT_CONFIGURED`; this source
change does not enable Mission, policy, or the disabled-by-default OMX Action
runner.

Fleet rechecks the generation immediately before its CORE call. For configured
same-host OMX instances, it also sends `StopLocal` over the per-instance UDS and
includes `omx_local_stop` (`LOCAL_LATCHED`, `UNKNOWN`, or `NOT_CONFIGURED`) in
the stop response. These software latch receipts are not physical E-stop or
driver standstill proof. The existing CORE/mobile stop fanout remains
independent, and physical E-stop/readback remain separate.

The dedicated `POST /api/fleet/estop` requires an authenticated operator but
still sends the stop fanout if the audit store, dispatch-latch write, or queued
task cleanup fails. Fleet logs each failed durable step; the response reports
CORE request outcomes only and is not physical stop proof. Other mutations,
including goal and rearm, remain blocked with `503 AUDIT_STORAGE_UNAVAILABLE`
when their pre-command audit record cannot be written. The compound
`POST /api/fleet/do` continues to use the normal audit gate.

The current single-host dispatcher uses SQLite; there is no RabbitMQ API or
queue service in this release (D-271). If independent workers later require a
broker, its versioned message must identify the task and dispatch attempt, have
an expiry, and cause the consumer to re-read the authoritative task row.
Publisher confirmation/outbox recovery and consumer ACK ownership must be
specified and tested before deployment. A broker ACK is never a CORE receipt or
robot completion. Video frames, DDS streams, secrets, and raw physical command
payloads stay outside the generic work queue.

An API or message contract change updates this reference, the typed schema or
generated OpenAPI surface, implementation, and contract tests together. Add a
new PRT field only when the robot/Fleet protocol itself changes; do not version
the robot envelope for a site-only REST change. D-268 and field acceptance remain
prerequisites for any automatic source; a displayed sighting alone never
authorizes navigation or picking.

## 10.12 Site Fleet to OMX local Device Action contract (D-333, D-336)

This is a same-Linux-host, per-workcell Unix domain socket (UDS) contract. It is
not a robot REST route, Fleet-to-robot PRT message, ROS topic, or remote-host
API. The socket path is `/run/rosy/omx/{instance_id}/control.sock`; service-owned
directories and socket permissions are checked together with `SO_PEERCRED`
against the dedicated Fleet service UID. A bounded, versioned JSON frame has a
maximum encoded size of 64 KiB. Remote Fleet/OMX placement remains HOLD pending
the separate host-placement and device validation decisions in D-281/D-273.

The v1 `GetAction` request contains only `version`, `operation`, and `action_id`.
Its receipt includes `attempt_id`; Fleet compares the full receipt identity and
generation against the persisted grant before accepting that readback.
`DeviceActionLookup` is the identity-pair base for attempt-scoped operations
such as cancellation, not the v1 `GetAction` request shape. A lookup does not
resubmit or create an attempt.

Phased `PICK_PLACE` and `CELL_TRANSFER` receipts use UDS protocol v2 while
retaining the same six operation names. V2 adds at most four ordered `phase_summaries`, each containing
only fixed `phase_id`, `ordinal`, bounded ROS phase `state`, local
`journal_event_id`, and aware `observed_at`. It excludes ROS goal UUIDs, joint
trajectories, camera payloads, and planner scenes. Fleet requires v2 for
`PICK_PLACE` and `CELL_TRANSFER` submission, readback and cancellation, and
fails closed on a missing summary; it never falls back to v1.
V1 remains available to non-phased operations. Stop requests remain v1.
Every response — success or error — carries the version of the request it
answers; only frames rejected before version validation (bad JSON, framing,
an unsupported version) answer version 1.
Repeated phase snapshots are idempotently keyed by Mission/Action/attempt,
ordinal, and local journal event ID. Reuse with changed evidence conflicts;
older snapshots cannot regress the current phase projection.

Required operations are `SubmitAction(FleetActionGrant)`,
`GetAction(action_id)`, `CancelAction(DeviceActionCancelRequest)`,
`StopLocal(LocalStopRequest)`, `GetStopState(LocalStopQuery)`, and
`RearmLocal(LocalStopRearmRequest)`. Every request
and response is bound to the workcell and runtime instance. The submit grant
carries distinct `mission_id`, `step_id`, `action_id`, and `attempt_id`, a
SHA-256 request digest, `PICK_PLACE`, source and destination
`ResolvedTargetEvidence`, capability, configuration and observation revisions,
authority epoch, dispatch generation, and aware issue/expiry times. The two
object evidences must identify distinct objects in the same observation, image
digest, camera, optical frame, calibration, transform revision, and capture
time. Image evidence is not a 3D pose, grasp, reachability decision, or
permission to bypass the local planner.

D-403 adds the separate additive `FleetCellTransferGrant` variant with
`action_kind: CELL_TRANSFER`; it does not alter or widen `FleetActionGrant`.
Its bounded `cell_transfer` body binds `job_id`, recipe/cell SHA-256 revisions,
ordered `step_index`, item/pallet/layer, `frame: robot_base`, and finite `home`,
`pick`, and `place` poses with pick/place approach heights and `carry_z`. The
carry height must cover both approaches. This schema describes one atomic
pick-plus-place unit. It does not enable Fleet dispatch or certify that any
receiver executes the variant; the D-403 simulation gate remains in force.

`DeviceActionState` is the durable local Action journal state: `PREPARED`,
`SUBMITTING`, `ACCEPTED`, `RUNNING`, `CANCEL_REQUESTED`, `UNKNOWN`, `SUCCEEDED`,
`FAILED`, or `HOLD`. A successful transport response or `SUCCEEDED` Action
journal entry is not independent Mission goal evidence and does not prove
object placement. Timeout or unknown acknowledgement is `UNKNOWN`; it never
authorizes an automatic re-submit. Read and cancel are fenced by the Fleet-
issued action/attempt pair.

Stop snapshots expose `OPEN`, `REQUESTED`, `LOCAL_LATCHED`, or `UNKNOWN`, with
request source derived by the trusted server. Caller-supplied stop principal is
forbidden. `OPEN` means the software submission fence has been rearmed for the
reported generation. `LOCAL_LATCHED` is a middleware software fact; it is not a
driver standstill readback, safety-rated E-stop, or physical stop confirmation.
Physical stop and goal evidence remain separately sourced and correlated.
`RearmLocal(LocalStopRearmRequest)` is accepted only from the configured Fleet peer UID. Site Fleet may issue it only after an authenticated named-operator rearm request advances the shared dispatch generation; OMX independently requires the exact current Fleet authority/generation fence, zero unresolved local Actions, and a generation newer than its persisted latch. A Fleet rearm that cannot confirm every configured local instance rolls Fleet dispatch closed again and sends a local stop rollback. A process restart reopens neither Fleet nor OMX dispatch automatically. These checks coordinate software submission; they do not certify a physical E-stop reset or safe-to-move state.

#### OMX owner HOLD 복구 (D-442 U3)

owner recovery adapter를 가진 같은-host OMX 구성은 version 1의 `GetOwnerState`와 `RecoverOwner`를 추가로 제공한다. 기존 `RearmLocal`과 다른 owner HOLD 래치이며 preempt·motion 제출·물리 reset은 이 표면에 없다. Fleet peer UID만 허용한다. 모든 필드는 추가 필드를 거부하며 version·순번·generation은 실제 int(bool 제외)다.

- `GetOwnerState`: `{version:1, operation:"GetOwnerState", workcell_id, instance_id}`. 정확한 장치 identity와 `{state, reason, observed_sequence}`를 읽는다. 순번이 없으면 null이며 어떤 래치도 바꾸지 않는다.
- `RecoverOwner`: `{version:1, operation:"RecoverOwner", workcell_id, instance_id, authority_epoch, dispatch_generation, operator_confirmed:true, observed_sequence, actor_id}`. 확인은 실제 bool true, 순번/epoch/generation은 nonnegative int, actor는 Fleet가 인증한 이름 있는 operator identity다. 이름을 보냈다는 것만으로 사람 확인을 증명하지 않는다.
- local stop OPEN·현재 fence·미해결 Action 없음(PREPARED 포함)·선점 이후 fresh readback·operator 확인을 검사한다. stop→owner→journal 순서로 확인부터 복구까지 직렬화한다. journal commit 실패는 원래 owner HOLD를 같은 잠금 안에서 복원한다. 반환은 `decision`(accepted/state/reason), 정확한 장치·actor·readback identity이며 성공은 ready일 뿐 동작이나 물리 정지 증거가 아니다. 닫힌 fence/오래된 readback은 409, 저장소 실패는 503이다.

Fleet 표면은 `GET /api/fleet/workcells/{workcell_id}/owner`(viewer 읽기), `POST /api/fleet/workcells/{workcell_id}/owner/recover`(configured named operator만)다. POST 본문은 `{operator_confirmed:true, observed_sequence, expected_generation}`(strict bool/int, 추가 필드 금지). Fleet의 기존 durable INTENT/RESULT 감사 경로를 사용하고 저장 실패·닫힌 dispatch·미해결 Action·generation 불일치 시 UDS를 보내지 않는다. workcell은 configured OMX map에서 instance로 해석하며 사용자가 instance를 바꾸지 않는다. POST는 현재 epoch/generation과 인증된 actor를 UDS에 전달한다. ACK의 identity·순번·ready 상태를 검사하고 잃거나 불명한 ACK를 자동 재전송하지 않는다.

현재 이 recovery 표면은 OMX cell simulation composition에 연결된다. 실제 ROS/UDS·물리 장치 수용은 별도 증거이며, 이 API를 추가했다고 hardware owner를 켜지 않는다.


The source now provides a newline-delimited JSON UDS handler and local Action runner. Each connection carries one request frame, capped at 64 KiB, and peer UID is read from Linux `SO_PEERCRED`; the parent socket directory must already be provisioned. `request_digest` is lowercase SHA-256 over UTF-8 canonical JSON of the complete `FleetActionGrant` with `request_digest` omitted (sorted keys, compact separators, Pydantic JSON-mode ISO-8601 timestamps). The runner is disabled by default, journals before driver submission, and never replays an Action already in `SUBMITTING`, `UNKNOWN`, or later. These source modules do not register a service entrypoint, connect a selected ROS/gripper driver, or provide physical stop/goal proof; those remain gated by ROS-SIM, DEVICE, and FIELD.

`DeviceActionReceipt` binds every local readback to the same mission, step, action,
attempt, workcell, instance, request digest, authority epoch, dispatch generation,
journal event ID, and observed time. Site Fleet has one background Mission dispatcher;
it is disabled by default and can be constructed only with the complete Mission API,
shared persistent database, explicit OMX workcell/instance map, and a local Action
transport. Admission and provider proposal handlers never call the device API.
Before first submit, Fleet persists the exact grant and IDs while atomically moving
the Mission from `READY` to `RUNNING`. A process restart reads that stored grant and
calls `GetAction`; it does not regenerate IDs or replay `SubmitAction`. Lost
acknowledgement becomes Fleet `HOLD` with claims retained while one durable
reconciliation is pending. A readback that is missing or remains nonterminal clears
that one reconciliation attempt and leaves the Mission held for operator review.
An Action terminal success advances only to `ACTION_SUCCEEDED`; independent goal
evidence is still required for Mission completion. Goal confirmation is an internal
Fleet service operation and requires an explicitly injected trusted producer
verifier; no producer is registered by default, so completion fails closed. Evidence
must identify the current Action/attempt, a post-action frame with a new observation
ID and digest, the evaluator revision, and a separately identified post-action
gripper `OPEN` readback. The verifier is responsible for producer authentication
and current camera/calibration/evaluator revision checks. Model prose and the input
frame used to propose the task cannot confirm placement. Invalid or stale evidence
records HOLD and does not release Mission claims. No device, physical stop, or
manipulator acceptance follows from enabling this source worker.

## 10.13 Fleet proposal, Mission draft, and operator admission (D-333/D-334)

These Site Fleet routes are separate from `/api/v1/fleet/missions` on robot CORE.
They require the Site Fleet named-user authorization and persistent audit store.
The authenticated principal is server-derived; proposal data cannot supply an
actor or principal. Candidate metadata is limited to 32 KiB, retained for 30
days, and never includes source image bytes, provider credentials, or auth tokens.
Resolved Mission metadata is limited to 64 KiB and rejects the same secret/image fields.

| Method | Path | Role | Meaning |
|---|---|---|---|
| POST | `/api/fleet/proposals` | Operator; `service` for `cell_job` only | Store one immutable, idempotent candidate under `(principal_id, request_key)`; performs no model call or device submission. A cell service cannot submit ER 2 candidates; operators cannot submit Cell Jobs. |
| GET | `/api/fleet/proposals/{proposal_id}` | Viewer | Read the caller-owned candidate and resolution status; a named operator may inspect a Cell Job proposal. |
| POST | `/api/fleet/proposals/{proposal_id}/resolve` | Operator; `service` for `cell_job` only | Recheck current evidence/capability through the injected resolver or recompile a Cell Job through the process compiler port; create a proposal-only Mission draft and ordered steps. |
| GET | `/api/fleet/missions/{mission_id}` | Viewer | Read caller-owned candidate, Mission state, and Fleet Mission event history. |
| POST | `/api/fleet/missions/{mission_id}/admit` | Named Operator | Recheck evidence and revisions, then atomically acquire the shared workcell/object claims at `expected_generation`. |
| GET | `/api/fleet/cell-jobs/{mission_id}` | Viewer | Read the resolved Cell Job, ordered step states, and Fleet journal events; a named operator may inspect another principal's Cell Job. |
| POST | `/api/fleet/cell-jobs/{mission_id}/reconcile` | Named Operator | Read the current step back from the OMX owner now (GetAction), ignoring the readback backoff. 503 when the dispatcher is disabled. |
| POST | `/api/fleet/cell-jobs/{mission_id}/resume` | Named Operator | Body `{expected_generation}`. Re-approve a HOLD Job under the current fence: the first unconfirmed step becomes READY (or ACTION_SUCCEEDED if its last device outcome was a success; it is never resent), claims are re-taken at the new generation. Refused (409) while a claim is DISPATCHING or UNKNOWN, or for a cancelled Job. |
| POST | `/api/fleet/cell-jobs/{mission_id}/cancel` | Named Operator | End the Job: status HOLD with reason `CANCELLED_BY_OPERATOR` (terminal; no CANCELLED status until the D-420 v2 schema) and its claims released in the same transaction. Refused while a claim is DISPATCHING or UNKNOWN. |
| GET | `/api/fleet/resource-claims` | Viewer | `{claims: [{resource_key, resource_kind, resource_id, owner_kind, owner_id, generation, phase, mission_id, job_status, job_reason}]}`; `mission_id`/`job_status`/`job_reason` are set when a Cell Job owns the claim, otherwise null. `phase` is CLAIMED, DISPATCHING, UNKNOWN or HELD (a held Cell Job; the stop latch keeps it, rearm ignores it). |

`POST /api/fleet/proposals` accepts `request_key`, `workcell_id`, `instance_id`,
and either an ER 2 selector candidate or a service-owned `cell_job` candidate.
The Cell Job candidate contains `recipe`, `cell`, `recipe_sha256`,
`cell_sha256`, and submitted compiled `job`; its metadata limit is 64 KiB
(ER 2 remains 32 KiB). Fleet recompiles with the injected process compiler and
rejects a Job or digest mismatch. Recipe/Cell calculations remain outside
Fleet. Its authenticated owner and request scope are
stored by Fleet; duplicate same-content requests return the existing proposal,
while reuse with a changed candidate or workcell/instance returns `409
REQUEST_CONFLICT`. The API does not call ER 2. Candidate records allow only
selector/provenance metadata and reject principal, credential, and image-payload
fields.

ER 2 feedback candidates use the same proposal read/resolve routes. Their
response adds `source_mission_id`, `source_action_id`, `source_attempt_id`,
`source_dispatch_generation`, `source_event_watermark`,
`source_observation_id`, and `supersedes_mission_id`. Fleet writes this row only
after one SQLite `BEGIN IMMEDIATE` transaction rechecks the active dispatch
latch/generation, source Mission/action/attempt, latest event watermark, and a
post-action observation captured no more than 30 seconds before candidate
commit. A later stop/generation change or
source event makes the candidate non-resolvable. Operator resolution creates a
separately identified `PROPOSED` successor Mission with
`supersedes_mission_id`; it never changes the source Mission. The successor
still requires the ordinary admission gate. Image bytes are used for model
reasoning only and are never persisted in proposal metadata.

ER 2 resolution is available only when a trusted current-observation and capability
resolver is explicitly injected into the Site Fleet app. It receives the stored
candidate, requested workcell/instance, and current time; it must verify image
digest, camera/frame, capture time, calibration/transform/config revisions,
freshness, unique target and destination, and capability. Missing resolver,
stale or ambiguous evidence, or changed revisions fail closed. Resolution
stores a target/goal predicate and shared resources in the Fleet Mission journal;
it does not submit a device Action. Cell Job resolution stores canonical
PlanBundle data as ordered `CELL_TRANSFER` rows in the versioned `cell_jobs`
journal; the legacy single-step `PICK_PLACE` table and digest are unchanged.
Admission recompiles and compares the ordered plan, then atomically claims the
workcell and every pallet for the complete Job. Only step zero becomes `READY`;
later steps remain `WAITING` until the prior step receives independent goal
confirmation. The Cell Job journal is not connected to a device dispatcher in
this source slice.

Admission requires a configured named operator credential; the development
fallback principal is refused. The server re-resolves the candidate and compares
the resulting target, goal predicate, revisions, and resource set with the
stored draft before the atomic generation check and claim acquisition. Stale
generation or any existing navigation/direct-action/workcell/object claim
returns `409` with no new claim. General mutation audit failure returns `503`
before proposal or admission mutation. The synchronous admission response reports
`physical_submission: NOT_CONNECTED`: admission itself is only a claim transaction.
For Cell Jobs, the approving operator must have a different principal ID from
the service proposer. Changed compilation, changed generation, or resource
conflict leaves the Job unadmitted and creates no claim. If the separately configured, explicitly enabled background dispatcher is running,
it may later submit one fenced local Action. Neither response proves ROS goal
completion, software stop, driver standstill, object placement, or physical E-stop
state.


## 10.14 Mission progress snapshots and event cursor

These Site Fleet read routes are scoped to the authenticated proposal owner and
require the Viewer role. The robot CORE Mission API is a separate interface.

| Method | Path | Role | Meaning |
|---|---|---|---|
| GET | `/api/fleet/missions/{mission_id}` | Viewer | Return the owner-scoped Mission, progress axes, and up to 50 most recent journal events from one SQLite read snapshot. |
| GET | `/api/fleet/missions/{mission_id}/events?after_event_id={id}&limit={n}` | Viewer | Read a bounded Mission event page in Fleet journal ID order; `limit` defaults to 50 and is restricted to 1..200, with each event detail limited to 16 KiB of JSON. |

`progress` contains `snapshot_event_id`, `snapshot_at`, and five independently
sourced axes: `mission`, `step`, `action`, `goal_evidence`, and `stop`. Each axis
contains `state`, `source`, nullable `last_event_id`, nullable `observed_at`,
nullable `revision`, `freshness` (`CURRENT`, `FRESH`, `STALE`, or `UNKNOWN`), and
nullable `reason`. Action readback without a timestamp is `UNKNOWN`; an Action
success without a matching goal event leaves `goal_evidence` as `PENDING`.
Fresh negative evidence from the registered independent evaluator is shown as
`UNSATISFIED` and holds the Mission with `GOAL_NOT_SATISFIED`; rejected or stale
evidence remains `REJECTED` and cannot be interpreted as a negative result.
`stop.state` is `DISPATCH_ENABLED` or `DISPATCH_BLOCKED` and represents only
Fleet's dispatch-control latch. `physical_state: UNKNOWN` is returned because
this API does not receive an independent physical
stop readback. No percentage is returned because no physical-progress measure
is available.

The Mission response returns at most 50 recent events and includes
`history_truncated`. When true, older events were omitted or removed by a
retention policy; clients use the cursor endpoint to page the retained journal.
The snapshot still computes its Action and goal axes from the latest events for
the current `action_id`/`attempt_id`, even when those events are older than the
recent-history window.

Clients read the snapshot first and continue with
`after_event_id=progress.snapshot_event_id`. Event IDs describe Fleet journal
insertion order, not device timestamps or attempt recency. Clients ignore IDs at
or below their stored cursor and apply Action/goal events to the current view
only when their action/attempt pair matches the active attempt in the latest
snapshot. A late report from an older attempt can have a larger Fleet event ID.
`snapshot_event_id` in an event page is that read's high water mark;
`next_after_event_id` is the last returned event ID, or the supplied cursor when
the page is empty.

Mission event rows are retained for the lifetime of the Mission; v1 has no
automatic pruning. The per-Mission `cursor_floor` starts at zero and advances
only if a future retention process removes older entries. A cursor below that
floor returns `410 MISSION_CURSOR_EXPIRED`; a cursor above the current high water
mark returns `409 MISSION_CURSOR_RESET_REQUIRED`. Both responses include a fresh
snapshot and `snapshot_restart_required: true`. Missing or non-owned Missions
return `404` in both routes. WebSocket/subscription delivery is not part of this
contract.

Fleet can build an internal model context from the same snapshot after matching
the authenticated principal and workcell. It contains only Mission/step/Action/
goal/stop states and bounded reasons; it excludes object selectors, raw
observations, evidence payloads, and credentials. This context is consumed by an
internal ER 2 feedback adapter. It is not a public `get_mission_status` route.
The read-only status result also contains up to four ordered phase summaries
and `active_phase` from the durable Fleet event journal. These fields describe
local progress only and cannot submit, cancel, stop, rearm, or confirm a Mission.

## 10.15 ER 2 Mission feedback tools and outbox (D-357/D-358)

ER 2 feedback tools are provider-internal function declarations; they are not
authenticated Fleet REST routes and do not add a public control surface. The
allowlist contains `get_mission_status` and `propose_replan`. The former reads
the Mission already bound to the trusted turn scope. The latter declaration is
limited to a trigger event watermark and rationale; Fleet obtains the actual
observation ID from its trusted post-action reader rather than asking ER 2 to
guess an ID it has not been shown. Its candidate write
remains unavailable because no trusted fresh post-action observation source is
wired to Fleet. Before any future candidate path is enabled, it must use an
atomic stop/candidate transaction. It does not write an Action, admit a Mission, issue a motor/gripper
command, cancel, stop, or rearm. Fleet validates each tool call and returns a
bounded structured result. Unknown tools and malformed arguments are rejected.

Every turn scope is captured by trusted Fleet code and binds principal,
workcell, Mission, active Action/attempt, Mission dispatch generation, event
watermark, model-policy revision, and outcome policy. The separately built
feedback context adds current stop generation, authority epoch, per-axis
evidence source/freshness, and snapshot/observation timestamps. A replan context is invalid if the current stop generation
does not equal its Mission dispatch generation. Provider arguments cannot select
or widen these identities. A fresh `UNSATISFIED` state remains status-only until
Fleet has a trusted source for a new post-action image and candidate resolution;
`propose_replan` currently returns unavailable when that observation is missing.
The feedback context is capped at 8 KiB; tool arguments
and results at 4 KiB each; one turn allows at most four function calls, eight
replay steps, 64 KiB of replay and response, a 45-second request deadline, and
14 MiB per image. The configured estimated-turn cost ceiling is USD 0.10.
Missing provider project/service-tier, mission-progress, mission-instruction,
workcell, or task-class approval, or an acceptable cost estimate denies egress
before transport. The full Mission instruction is classified separately from
the structured progress fields. The outbox has a hard row cap configured when
`create_app()` is constructed through `mission_model_turn_max_rows` (default
10,000). At capacity, a trigger is dropped for each enqueue attempt,
the global cursor advances, and a durable counter plus error log records the
drop. Raising the configured cap is required to resume future enqueueing;
already dropped triggers are not replayed. A worker also requires a current-principal authorization callback;
absent authorization is denied. Its pre-submit SQLite transaction rechecks the
stop latch/generation, Mission owner/workcell/action/attempt/state, and exact
event watermark. Production policy loading and provider runtime wiring remain
disabled.

Interactions requests use `store=false`. Each tool-result request replays the
original user input, the exact model steps received so far, and the matching
function results. Replay data and opaque provider step material exist only in
turn memory. The SQLite model-turn outbox stores only trusted scope references,
watermarks, policy revision, and lifecycle state. Its state path is
`PENDING -> CLAIMED -> SUBMITTING -> RESPONDED | REJECTED | UNKNOWN`, with an
explicit `SUPPRESSED` state. A pre-transport policy/validation failure may
return a claim to `PENDING`. Once submission begins, a timeout or lost response
becomes `UNKNOWN` and is not automatically resubmitted. Stop-generation
suppression is atomic with provider submission admission; candidate fencing is
not implemented because candidate creation is unavailable. The scheduler polls
durable Mission events and fills the outbox; no provider worker is configured,
so this does not initiate model calls. Production provider configuration
remains disabled. A worker response would currently be marked `RESPONDED`
without storing or exposing model text; no user-visible model feedback channel
is implemented. No provider status or tool result changes Mission, Action, goal,
or physical stop state.

This source implementation enables event-to-outbox scheduling only; it does not
enable provider calls or policy dispatch. Fleet admission remains a separate operator/policy gate;
Action execution remains with the device-local controller; the independent
goal verifier and physical stop owner remain authoritative for their respective
evidence. `POLICY_DISPATCH_ENABLED` remains false.

## 10.16 Fleet goal-evidence producer contract (D-348)

The route is exposed only when Fleet Mission API composition includes a valid
goal-evidence producer registry. It does not enable ER 2 calls, automatic policy
dispatch, Mission Action dispatch, ROS, or a manipulator driver. The registry is
read-only YAML: each producer is scoped to one `workcell_id` and `predicate_id`,
exact object/destination IDs, `camera_observation`, an allowlist of evaluator
revisions, server-enforced `max_age_s`, a missing-evidence `grace_s`, and an
aware `valid_until`. YAML stores only a `token_env` name; the credential is read
from the process environment and never returned in a response.

| Method | Path | Credential | Meaning |
|---|---|---|---|
| POST | `/api/fleet/goal-evidence` | `X-Goal-Evidence-Token` | Submit `{ "mission_id": "?", "evidence": {?} }` from a registered independent producer. |

The evidence object must match the existing `GoalEvidence` contract, including
the producer ID, approved evaluator revision, current Mission Action/attempt,
new post-action observation, and independent gripper `OPEN` readback. A fresh,
registered `satisfied: true` predicate records `GOAL_CONFIRMED`. A fresh,
registered `satisfied: false` result is preserved as
`GOAL_PREDICATE_UNSATISFIED` and holds the Mission as `GOAL_NOT_SATISFIED`;
malformed, stale, untrusted, or mismatched evidence remains
`GOAL_EVIDENCE_REJECTED`. Negative evidence is never completion proof. Producer
credentials are separate from Site Fleet user roles. A
`viewer` can read Mission state, an `operator` can admit a draft, and registry
administration remains a deployment-controlled read-only file change; the
producer token cannot create or admit a Mission.

Accepted evidence is persisted in the same SQLite database as Mission state.
`evidence_id` is idempotent for identical content and conflicts if reused with
different content. The server records `received_at`; caller timestamps do not
set freshness policy. Invalid/rejected raw evidence is not stored. Evidence
received before action terminal readback stays pending and is checked when the
matching terminal success arrives. Evidence submitted after success is checked
immediately. Missing evidence remains pending through the registered grace
period and then moves the Mission to `HOLD` with `GOAL_EVIDENCE_TIMEOUT`;
stale, mismatched, untrusted, or conflicting evidence cannot produce
`GOAL_CONFIRMED` or release claims. HTTP errors include `401
PRODUCER_UNAUTHORIZED`, `404 MISSION_NOT_FOUND`, `409` scope/replay/rejection
codes, and `422 INVALID_GOAL_EVIDENCE_ENVELOPE`.

This route is independent of the software stop API. It never reports physical
stop, gripper, placement, or hardware acceptance unless the trusted producer
supplies the corresponding separately sourced evidence. SOURCE/LOCAL tests use
fake credentials and clocks; device and field acceptance remain separate gates.

## 10.17 Cell goal-evidence producer contract (D-413)

Exposed only when the existing Fleet app is composed with `cell_goal_registry`,
a persistent Cell Job compiler/API and `deployment_profile="simulation"`
(`sim_model_pose` is simulation-only evidence, D-403 §5); any other profile
refuses at startup. There is one Cell journal and one site dispatch worker
(`StepJobDispatcher`, C4b).

| Method | Path | Credential | Body |
|---|---|---|---|
| POST | `/api/fleet/cell-goal-evidence` | `X-Goal-Evidence-Token` | `CellGoalEvidenceSubmission`: `{ "mission_id": "...", "evidence": {...} }` |

The shared strict contract is `core_common.protocol.cell_goal_evidence`, exposed
through `core_common.protocol.schemas.CellGoalEvidenceSubmission`. All fields
are required; additional fields, Boolean step indices, nonfinite numbers and
whitespace/control characters in identifiers are rejected. The evidence includes:

| Fields | Meaning |
|---|---|
| `producer_id`, `evidence_id`, `evidence_source`, `evaluator_revision` | Registered producer, immutable evidence identity, literal `sim_model_pose`, pinned evaluator revision. |
| `job_id`, `step_id`, `step_index`, `action_id`, `attempt_id`, `request_digest`, `recipe_sha256`, `cell_sha256` | Exact persisted canonical CELL_TRANSFER grant and ordered step. Digests are lowercase 64-character SHA-256 values. |
| `model_id` | Attempt model identity: `cell_` followed by the saved Action ID. The independent evaluator must bind that model to the physical item and pinned recipe/cell. |
| `observation_id`, `observation_digest`, `evidence_revision`, `observed_at`, `model_pose_base` | Final independent model observation, provenance and robot-base pose. |
| `initial_observation_id`, `initial_observation_digest`, `initial_observed_at`, `initial_model_pose_base` | Initial independent observation after grant issuance and before terminal success. |
| `gripper_state`, `gripper_evidence_id`, `gripper_evidence_revision`, `gripper_observed_at` | Separately sourced post-terminal gripper `OPEN` readback. |

There is no `satisfied` field (C4b merge, 2026-10-03): a producer reports
observations only. Fleet judges `model_pose_base` against the `item_at_pose`
predicate stored in the step at resolution (target, xy/z/yaw/tilt tolerances and
their basis) and confirms the step only when it is met, after the step's durable
device `SUCCEEDED` for the same attempt. A submission carrying `satisfied` is
rejected (422).

Both poses require finite `x_m`, `y_m`, `z_m`, `roll_rad`, `pitch_rad`, `yaw_rad`.
Observation timestamps are nonnegative epoch seconds. The read-only YAML registry
pins producer/workcell/instance/recipe/cell/evaluator identities, `max_age_s`
(positive, at most 60 seconds), timezone-aware `valid_until`, and environment-only
`token_env`. Producer credentials must differ from user, robot, discovery,
Vision, pairing, policy and legacy goal producer credentials. They cannot propose,
admit, rearm or dispatch a Job.

The service matches evidence to the saved grant, checks registry scope/expiry and
freshness using server receipt time, and requires final model and gripper samples
after the local terminal success. Evidence received before terminal readback stays
`PENDING_ACTION_TERMINAL`; the composed dispatcher revalidates it after recording
the exact successful receipt. Rejected pending evidence retains the successful
Action record and claims. Placement geometry belongs to the pinned independent
evaluator, rather than Fleet journal arithmetic.

Already available invalid/preterminal evidence is rejected before persistence.
Accepted evidence IDs are immutable and replay identical content idempotently.
Completion rechecks the exact latest terminal event ID inside its SQLite
transaction. A concurrent newer terminal cannot complete a step using older
samples. Intermediate completion returns `READY` or `HOLD` depending on the live
site fence; only every ordered goal confirmed releases claims and returns
`GOAL_CONFIRMED`. Goal confirmation never rearms dispatch. Errors include `401
PRODUCER_UNAUTHORIZED`, `404 MISSION_NOT_FOUND`, `409` scope/conflict/invalid-evidence
codes, and `422` strict envelope validation errors. Responses never include tokens.

This contract and host tests establish SOURCE/LOCAL composition. Independent
Gazebo placement evaluation, the actual OMX owner/provider and ROS-SIM, device
and field acceptance require their own evidence.

## Fleet Cell 작업 화면 (D-450, v1.90)

`/console/cell`은 기존 Fleet Console 프로세스·인증·포트의 작업 화면이다. 신규 실행 writer나 원장을 만들지 않는다. 운영자 입력 문서는 초안으로 저장할 수 있으며, 저장 성공이 실행 가능한 문서임을 뜻하지 않는다. `compile`은 설치된 정본 process compiler로 검증하고 계산한다.

| 경로 | 권한 | 요청 · 응답 |
|---|---|---|
| `GET /api/fleet/cell-app/documents` | 기존 viewer | `{documents:[{kind,id,digest,updated_at}]}` |
| `GET /api/fleet/cell-app/documents/{kind}/{identifier}` | 기존 viewer | `{kind,id,digest,document,updated_at}` |
| `POST /api/fleet/cell-app/documents/{kind}/{identifier}` | named operator | `CellAppDocumentSaveRequest`: `{document,expected_digest:null 또는 sha256}` → 저장 문서. 생성은 null, 수정은 현재 digest가 필요 |
| `POST /api/fleet/cell-app/compile` | named operator | `CellAppCompileRequest`: `{recipe_id,recipe_digest,cell_id,cell_digest}` → `{candidate,process_artifact_digest,summary:{transfer_count,pallet_markers}}`. 실행·제안·승인 부작용 없음 |
| `POST /api/fleet/cell-app/proposals` | named operator | `CellAppProposalRequest`: compile 참조 + `{request_key,workcell_id,instance_id}` → 기존 proposal resolve 응답. 구성된 service principal이 제안·resolve하며 admit하지 않음 |

`kind`는 `recipe|cell`, 문서 ID는 `[A-Za-z0-9][A-Za-z0-9_-]{0,63}`, digest는 소문자 sha256다. 문서는 finite JSON object, canonical JSON UTF-8 64 KiB 이하. 동일 DB의 문서 revision은 트랜잭션에서 비교한다. `request_key`는 160자 이하, `workcell_id`/`instance_id`는 96자 이하이며 공백 trim·제어문자 없는 기존 proposal 식별자 규칙을 따른다. 미리보기 candidate는 기존 `{kind:"cell_job",recipe,cell,recipe_sha256,cell_sha256,job}` 계약 그대로다. 저장 revision digest와 process의 recipe/cell hash는 각각 해당 canonical 표현의 해시다.

제안 composition은 `--cell-app-service-id`로 지정한 실제 site-users `role=service` ID를 검증한다. 미구성이면 제안은 503; 존재하지 않거나 operator/viewer ID이면 서버 구성을 거절한다. 서비스 자격은 브라우저에 전달하지 않는다. HTTP를 시작한 named operator의 API audit와 proposal 원장의 service author를 함께 유지한다. 같은 request key 재시도는 기존 ProposalStore idempotency/충돌 규칙을 사용한다. UI는 실패 시 자동 재제안·승인·재실행하지 않는다.

오류: `CELL_APP_UNCONFIGURED`(503), `CELL_APP_DOCUMENT_NOT_FOUND`(404), `CELL_APP_DOCUMENT_CHANGED`(409), `CELL_APP_DOCUMENT_INVALID`(422), `CELL_APP_COMPILE_INVALID`(422; `message`, `problems`). 문서 저장·compile·proposal POST는 기존 Fleet API audit를 받는다. 기존 proposal/admission 오류도 그대로 전달한다.

작업 화면의 승인·진행·복구는 기존 `/api/fleet/missions/{id}/admit`, `/api/fleet/cell-jobs/{id}`, `/reconcile`, `/resume`, `/cancel`을 사용한다. 승인/재승인은 현재 dispatch generation과 named operator가 필요하다. UNKNOWN의 자동 재시도는 없다. cancel은 기존 `HOLD/CANCELLED_BY_OPERATOR` 계약을 유지한다. 서비스 제안 성공·실행 성공·독립 목표 확인은 별개다.

## Cell 수동 슬립시트 대기 (D-450)

`rosy_cell.recipe/2`는 palletize의 작업자 간지 삽입을 명시한다. `slip_sheet`는
`{handling:"operator",thickness:<positive metres>}`이며 로봇 공급 station을 받지 않는다.
recipe/1의 자동 sheet·문서 해시·Job 직렬화는 유지한다. 수동 depalletize는 아직 거절한다.
PROCESS가 간지 두께를 다음 층 높이에 포함하고 non-motion `operator_sheet` Job 단계와
hash-bound checkpoint를 만든다. 실행 PlanBundle에는 box transfer만 들어간다.

`GET /api/fleet/cell-jobs/{mission_id}`는 수동 Job에만 `job.operator_checkpoints`를 추가한다.
각 행은 공유 `CellOperatorCheckpoint` 스키마이며 다음 필드를 가진다.

| 필드 | 의미 |
|---|---|
| `checkpoint_id` | recipe/cell digests와 아래 canonical instruction을 결합한 SHA-256 |
| `kind` | `operator_sheet` |
| `before_transfer_ordinal` | 다음 box transfer의 1-based 순번 |
| `pallet_id`, `layer_index` | 팔레트 ID와 0-based 층 번호 |
| `sheet_pose_base` | 작성된 간지 top-face 배치 지시 `{x_m,y_m,z_m,yaw_rad}`. 실측 pose가 아님 |
| `thickness_m` | 양수 두께(m) |
| `status` | `WAITING` 또는 `WAITING_ACCESS` |
| `updated_at` | timezone을 포함한 원장 변경 시각 |

`checkpoint_id = SHA256(UTF8(canonicalJSON({recipe_sha256,cell_sha256,checkpoint:descriptor_without_id})))`.
canonical JSON은 sorted keys·compact separators·`ensure_ascii=False`·`allow_nan=False`이며
descriptor는 위 필드 중 `checkpoint_id`, `status`, `updated_at`을 제외한 여섯 지시 필드다.

이전 box의 독립 목표 확인과 marker 원장 반영 후 다음 transfer를 READY로 만들기 전에
같은 SQLite transaction에서 checkpoint와 Job/다음 step을 HOLD하고 CLAIMED 자원을 HELD로 보존한다.
첫 층 간지도 admission에서 막는다. 재시작·start·일반 resume는 이 대기를 우회하지 못하며
완료 box를 다시 하달하지 않는다. 수동 checkpoint가 없는 기존 Job의 응답 필드는 유지한다.

현재 대기 이유는 `OPERATOR_SHEET_ACCESS_UNAVAILABLE`이며 일반 resume는 409다.
작업자 삽입 확인 API와 owner-exclusive 접근 허가 계약은 아직 제공하지 않는다.
owner ready, StopLocal ACK, caller 확인 boolean 또는 simulation pose만으로 다음 층을 열지 않는다.
이 readback은 작업자의 안전 접근이나 간지 삽입 완료 증거가 아니다.

### D-456 CORE 수신 승인과 기억한 연결 (v1.101)

이 규약은 LAN 최초 승인과 이미 승인된 키의 재접속을 구분한다. 모든 경로는 실제
HTTPS listener를 요구하며 CORE는 `proxy_headers=False`를 유지한다. 광고는 후보를
보여줄 뿐 인증서를 신뢰시키거나 권한을 발급하지 않는다. HTTP-only 로봇의 최초
신뢰·TLS provisioning과 Native Pilot 결합은 이 CORE 후보의 완료 범위가 아니다.

Prefix: `/api/v1/auth/peer-pairing`.

| Method / path | 입력·권한 | 결과 |
|---|---|---|
| GET `/identity` | 검증할 HTTPS origin | receiver_id, receiver_public_key(SPKI DER base64), receiver_key_sha256, optional tls_hostname/tls_ca_pem/tls_ca_sha256 |
| POST `/requests` | LAN, fields+P256 signature | request_id, request_secret, display_code, revision=0, state=pending, paired=false, expires_at |
| GET `/pending` | 현재 named administrator | 대기 요청(D-483부터 최대 3개); 비밀값 없음 |
| GET `/requests/{id}` | `X-Request-Secret` | state/revision, 승인됐다면 relationship_id/generation/persistent/authorization_expires_at/authorization_available |
| DELETE `/requests/{id}` | 같은 요청 비밀 | pending만 cancelled로 전환 |
| POST `/requests/{id}/decision` | 현재 named administrator; action=approve/reject, revision, persist_requested | 승인 거래 결과; **paired=false**, credential 발급과 구분 |
| POST `/requests/{id}/confirm` | 인증 없음, `X-Request-Secret`; 본문 `{approval_code}`(6자, `23456789ABCDEFGHJKMNPQRSTUVWXYZ`) | D-483 (v1.110): 수신 LCD 승인 코드로 같은 요청을 승인. 200 StateSnapshot(approved, persistent=false, 168 h); 틀림 400 `detail.remaining_attempts`(5회째 rejected); 요청 역할 > operator 403; 출처별 30회/분 공유 또는 전체 틀린 코드 20회/10분 초과 429; 변경·만료·비밀 불일치 409 |
| POST `/relationships/{id}/challenge` | 이미 승인된 관계 ID | fields와 receiver_signature; 최대 60초, 한 번만 사용 |
| POST `/relationships/{id}/session` | 해당 client key의 fields+signature | 기존 digest token의 id/token/role/expires_at; 최대 1시간 |
| DELETE `/relationships/{id}` | 현재 named administrator | revoked와 증가한 generation; 자식 세션 거부 |

Request fields: receiver_id, receiver_key_sha256, client_id, label(1–64자),
client_public_key(SPKI DER base64), role(viewer/operator), nonce(64자 hex).
관계 ID는 request ID와 같은 32자 base64url이다. 비밀 request_secret은 43자
base64url이며 서버는 hash만 보관한다. 4자리 영숫자는 양쪽 화면의 요청 비교용이고,
승인·로그인 자격이 아니다. 상태 polling 간격은 최소 2초다.

D-483 화면 승인 코드(v1.110): CORE는 요청마다 6자 승인 코드를 만들고 상수 시간
hash 비교만 한다. 원문은 응답·상태·`pending`·로그에 없고, 살아 있는 대기 요청을
가장 최근 것부터 최대 3개 `/run/rosy-peer-display/approval.json`(`rosy-core:rosy-display`
2750, 파일 0640, `{"requests": [{display_code, approval_code, expires_at}]}`)으로
rosy-face에 넘긴다. LCD는 요청마다 "표시 번호  승인 코드" 한 줄을 보인다. 대기 요청이
없으면(승인·거절·취소·만료·정리) 파일을 지우고, CORE 시작 때 남은 파일도 지운다.
살아 있는 대기 요청은 LCD 목록과 같은 3개까지(끝난 요청은 세지 않음), 출처별 동시 대기는
2개다. 요청 취소도 출처별 30회/분 한도에 센다. 모든 출처를 합친 틀린 승인 코드가 10분에
20회에 이르면 그 창이 지날 때까지 `confirm`은 맞는 코드에도 429(콘솔 승인 안내)를 돌려준다.
콘솔 `decision`은 영향이 없다. 상태 보관 행은 600초 전에는 승인되지 않은
끝난 요청만 먼저 비운다. 화면 코드 행의 `approved_at`이 60초 넘게 미래이면 사용 시점에 거부한다. `confirm`으로
생긴 관계는 `approved_by`·`issuer_id`·`issuer_source`가 `screen-code`, `issuer_digest`가
수신 키 지문, `persistent=false`, `approved_at`부터 최대 168시간이며 발급자 token 없이
관계 자체의 만료·폐기·수신 키만 확인한다. 토큰 id `screen-code`는 예약어다. 콘솔
`decision`과 경합하면 하나만 승인한다. 관계 128개 상한에 닿으면 만료·폐기되었고 살아
있는 세션이 없는 관계를 지우고 `relationship_pruned` 감사 행을 남긴다.

Challenge fields: relationship_id, challenge_id, nonce, receiver_id,
receiver_key_sha256, client_id, client_key_sha256, role, generation, expires_at.
처음 승인한 generation은 0이며 client는 기억한 승인과 정확히 비교한다. 폐기한
관계 ID는 재승인하지 않는다. 새 동의는 새 request/relationship ID를 쓴다.

서명 transcript는 `{"version":"rosy.peer-proof/1","context":...,"fields":...}`의
key를 정렬한 compact ASCII JSON이다. Python `ensure_ascii=True`, lowercase Unicode
escape와 UTF16 surrogate pair, `/` 비escape, `allow_nan=False`가 기준이다. Context는
request / receiver-challenge / session-request로 분리한다. P256 ECDSA SHA256,
DER signature의 canonical base64를 사용한다. 서버 challenge의 공개 키·키 지문은
광고에서 새로 받아 신뢰하지 않고 기존 HTTPS 또는 승인된 화면/QR trust anchor에
대한 값과 비교한다.

`persistent=true`는 수신 소유자가 `persist_requested=true`로 명시 승인하고 실제 현재
issuer record가 nonlegacy·nondevelopment digest·card/manual source의 만료 없는
administrator일 때만 허용한다. issuer ID/digest/source/named principal/scope를
보존하고 매 갱신과 HTTP·live socket 인증에 재확인한다. 임시 pair-* issuer는 기억
요청이 있어도 `persistent=false` 및 issuer보다 길지 않은 만료(최대 168시간)를
반환한다. 관계 기록은 세션 만료·오프라인만으로 지우지 않는다. issuer 폐기·키 변경·
관계 폐기·만료는 자식 세션과 새 발급을 거부한다.

동일 요청 승인 결과가 저장된 뒤 응답을 잃어도 같은 관계를 읽어 복구한다. 재시도는
권한 기간을 늘리거나 관계를 중복 생성하지 않는다. nonce 소비·token digest·관계·
감사는 CORE의 기존 config overlay 한 번의 atomic commit에 포함한다. 최대 관계
128개, pending 3개/300초(D-483, 상태 보관 600초), source 128개·신청 30회/분(잘못된
증명도 crypto 실행 전에 포함), challenge 64개/60초, 관계당 활성 세션 8개, audit
256개를 넘기지 않는다. 용량이 가득 차면 기존 관계를 암묵적으로 삭제하지 않는다.

API 오류: 실제 HTTPS 또는 최초 LAN 조건 불충족 403, 기존 인증 없음 401,
권한 부족 403, 409(변경·만료·한도·증명 거부), 잘못된 typed 입력 422,
4096 bytes 초과 413, 저장 identity 초기화 불가 503. 응답은 no-store다.
이 로그인 발급은 Pilot seat·teleop 수락·calibration lease·모드·정지 해제를
발급하지 않는다(D-460/D-411). 실제 조작은 기존 CORE 게이트를 그대로 통과한다.

암호화 의존은 signed release의 `runtime-python` 보조 경로에 hashlocked ARM binary
wheels로 실어 CORE entry만 읽는다. D-189 base `python-runtime.sha256`과 이미지
global Python 요구사항은 변경하지 않는다. 기기에서 apt/pip download를 실행하지
않으며 새 CLI·user-site·`.pth` hook을 실행하지 않는다. native ARM build의 실제
import/sign/verify와 정상 signed candidate/device 수락은 별도 검증이다.


`authorization_available`은 현재 issuer와 관계가 유효할 때만 true다. 과거의 승인
결정은 revoked/expired 관계에서도 보관하지만 usable approval로 해석하지 않는다.
새 세션 token에는 `peer_binding={relationship_id,generation}`을 함께 저장한다.
관계 저장소·관계·session_ids 누락/손상이나 generation 불일치는 HTTP와 live socket
모두 거부한다. 기존 peer_binding 없는 D-193 token 의미는 바꾸지 않는다.

선택적 `network.tls.ca_file`은 TLS provisioning 소유의 절대 경로이며 cert_file과
key_file을 대체하지 않는다. 설정된 public CA 하나(최대 8192 bytes)가 현재 TLS
leaf/fullchain(최대 32768 bytes)을 실제 OS hostname.local에 대해 검증해야 한다.
CA BasicConstraints/keyCertSign/현재 validity 및 chain/SAN을 검증하고 실패하면
listener/first-contact를 닫는다. 성공할 때만 identity의 세 optional field를 함께
공개한다. 지문은 CA DER SHA256 lowercase hex이며 CA private key는 공개하지 않는다.
ca_file이 없으면 세 field는 null이며 기존 신뢰 검증을 대체하지 않는다.

수신 기기의 인증된 관리자 화면에 독립적으로 읽은 CA 지문과 hostname을 표시한다.
D-341 첫 접촉은 anonymous identity/request/status와 물리 화면의 지문 비교,
실제 관측 leaf의 CA binding/SAN 검증까지만 허용한다. 해당 신뢰가 확립되기 전
challenge/session이나 bearer 전송을 허용하지 않는다. mDNS·4자리 번호로 CA를
신뢰하지 않는다. 이 CORE slice의 public QR renderer는 아직 구현하지 않았다.

anonymous identity/challenge/session 호출은 crypto 전에 source별 합계 30회/분,
source map 최대 128개로 admission하며 한도는 429다. 최초 신청의 별도 30회/분
한도도 잘못된 증명을 포함한다. overlay 거래는 config.yaml.lock의 동일 UID
소유 0600 sidecar로 process/thread fence하고 unrelated token/config를 보존한다.
기존 lower-layer card/manual token은 실제 merged config provenance로 확인하지만,
peer 관계 저장소는 overlay 소유이며 삭제된 관계를 process memory에서 복원하지 않는다.

운영 수용은 별도다: HTTP-only Pinky의 TLS provisioning, 실제 native ARM crypto
build/import, signed delivery, Native Pilot coupled client, 실제 두 화면 승인과 재접속,
Fleet/Cam의 지속 관계 확장은 이 source/local 결과로 완료했다고 주장하지 않는다.


# 11. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.112 | 2026-10-07 | Additive (D-491 5, D-492 3): Fleet trip loop `POST /api/fleet/trips/{plan_id}/start` (opens the v1.111 501 reservation), `POST /api/fleet/trips/{trip_id}/cancel`, `POST /api/fleet/trips/{trip_id}/confirm-replan`, `GET /api/fleet/trips`, `GET /api/fleet/trips/{trip_id}`; map activation now waits for a running trip instead of a recent `/route` step. Uses robot `POST /api/v1/line-follow/junction` (D-491 4) and the D-491 1/3 capability and map pose inputs. Robot API and envelope 1.0 unchanged |
| v1.111 | 2026-10-07 | Additive (D-488/D-490 M1): Fleet site map `GET /api/fleet/site-map/active`, `GET/PUT /api/fleet/site-map/draft`, `POST /api/fleet/site-map/activate`; `POST /api/fleet/robots/{robot_id}/trip` returns a lane-state A* plan only; `POST /api/fleet/trips/{plan_id}/start` is 501 until M2. `/route` reads the active site map instead of a repo lane graph. v1.109 (D-484) and v1.110 (D-483) landed first on main. Robot API and envelope 1.0 unchanged |
| v1.110 | 2026-10-06 | Additive (D-483): D-456 요청의 수신 LCD 승인 코드 경로 POST `/api/v1/auth/peer-pairing/requests/{id}/confirm`(`X-Request-Secret`, `{approval_code}`). 화면 코드 관계는 168 h·persistent=false·발급자 token 없음(`screen-code`). 콘솔 `decision` 유지, envelope 1.0 유지 |
| v1.109 | 2026-10-06 | Additive (D-484): 천장 카메라 측정 캘리브레이션에 필드 경계 자동 캘리브레이션 추가. `SiteSightingPayload.corner_marker_ids` 선택화·`calibration_source` 추가, 미리보기 리스 `rectification.mode: "auto"`와 `X-Frame-Rectified: auto`·`X-Field-Calib`·`X-Frame-State: field-unavailable`, site-map source에 `calibration_source`. 로봇 마커·전선·정책 증거 의미 불변 |
| v1.108 | 2026-10-06 | Additive (D-473): Fleet `GET /api/fleet/auth/connection` and `POST /api/fleet/auth/development-session`. Development connection mode (both `ROSY_DEPLOYMENT=development` and `--connection-mode development`) gives same-LAN (or tailnet) console browsers a 1 h in-memory named operator session; paired mode unchanged. Robot API and envelope 1.0 unchanged |
| v1.107 | 2026-10-06 | Fix (버전 번호 변경 없음) (fix/sensors-nonfinite-json): `GET /api/v1/sensors`·`/sensors/{type}` 가 LiDAR `ranges` 의 inf/NaN 때문에 500 이던 것을 비유한 값 `null` 로 직렬화. 필드 추가·이름 변경 없음 |
| v1.107 | 2026-10-06 | Additive (D-472): CORE 후면 LED 단기 식별 요청과 Fleet 단일 로봇 전달 경로. Rosy Cam 프레임 표시만 연결하며 자동 신원·주행 권한은 열지 않음 |
| v1.106 | 2026-10-05 | Additive (D-468): CAMERA_LINE 관측에 원본 시각과 같은 optional containment 경계 증거, geometry/ground source/uncertainty를 추가. 명령·자동 복구 활성화·envelope 1.0은 변경 없음 |
| v1.102 | 2026-10-05 | Additive (D-368, feat/d368-driver-mjpeg-stream): 운전자 전용 MJPEG 스트림 `GET /api/v1/vision/front/stream`(operator, `multipart/x-mixed-replace; boundary=frame`, `?overlay=`). 조종 소유권은 수락 teleop 토큰(D-460 — 임대 없음). 운전자 아님 409 `CAMERA_STREAM_NOT_DRIVER`, 이미 열림 409 `CAMERA_STREAM_BUSY`, 새 수락 teleop가 열린 스트림을 끝낸다. 관전자·관제는 기존 0.4 s 폴링 유지. envelope 1.0 유지. v1.100(D-463)·v1.101(D-456)을 main이 먼저 써 v1.102로 재번호 |
| v1.105 | 2026-10-05 | Additive: Fleet 상태 로봇 행의 선택 capabilities(CAP-001 원문 또는 null), 표시 캐시 5초. 목표·양보 및 대형 전송 전에 지원 기능 재확인. CORE 계약·최종 안전 판정·envelope 1.0 유지 |
| v1.104 | 2026-10-05 | Additive: D-456 Fleet/Cam LAN 수신 승인 프로파일과 typed field handoff. CORE 운영자 로그인과 Fleet 영상 자격을 분리하고 envelope 1.0 유지 |
| v1.103 | 2026-10-05 | Additive: 사용자 승인 무마커 시작점. Fleet `/api/fleet/start-points` GET·PUT·DELETE, 승인 보정 revision에 묶인 지도 x/y/yaw 참조 저장과 동시 편집 거절. 로봇 API·envelope·주행 권한 변경 없음 |
| v1.101 | 2026-10-05 | D-456: LAN 수신 승인·P256 관계·명시적 연결 기억·issuer-bound 단기 세션·선택적 CA first-contact. D-460 조작 게이트 유지; 실기 수용 별도 |
| v1.100 | 2026-10-05 | Additive (D-463): POST `/api/fleet/robots/{robot_id}/route` expands stored lane-graph edge ids into that polyline and submits only the next point about 0.20 m ahead through the existing goal path. The far junction is not one goal. A pose that is not LOCALIZED in the map frame, or is more than 0.08 m off the polyline, does not call CORE. GoalRequest stays {x, y, yaw}. envelope 1.0 unchanged |
| v1.99 | 2026-10-04 | D-457: 마커 우선·무마커 폴백 표시 추적, source-token 검출, operator 보정·재학습. 기존 sighting·envelope 1.0·주행 경계 유지 |
| v1.98 | 2026-10-04 | Additive (D-343·D-432·D-452): 공개 LAN 로봇 발견 목록의 typed 64행 계약, FQDN/TLS 링크, 공용 cache와 제한된 singleflight fallback. 인증·승인·제어 부여 없음; 기존 v1.97 중앙 GET 정본과 envelope 1.0 유지 |
| v1.97 | 2026-10-04 | Additive (D-454): 기존 등록 로스터를 읽는 opt-in 중앙 Fleet GET 목록·상세의 구현 상태와 응답을 명시. 기존 Viewer 인증·등록 정본·envelope 1.0 유지; 중앙 쓰기·명령·미션은 미구현 |
| v1.96 | 2026-10-04 | Additive integration (D-452, D-450, D-453): 역할 발견·승인 directory, Cell 수동 간지 readback, CORE 단일 구간 YIELD 계약을 함께 보존. 기존 인증·HOLD·보정 lease·E-Stop 및 envelope 1.0 유지 |
| v1.95 | 2026-10-04 | Additive (D-453, feat/meet-algorithms): CORE `POST /api/v1/line-follow/stuck/decision` 에 `YIELD` 와 선택 필드 `yield_m`·`yield_turn_rad`. 한 답은 한 구간이고 outcome 에 `yield` 가 있다. 필드가 없거나 다른 결정에 붙으면 400. 보정 lease·E-Stop 은 `RESUME`·`BACK_AND_RETRY` 와 같다. `stuck_resolver` 의 `MANUAL` 은 403. 운용자 Fleet `POST /api/fleet/robots/{robot_id}/line-stuck/decision` 의 다섯 단어와 추가 필드 422 는 그대로다. 판단기가 로봇에 `YIELD` 를 직접 보낸다. envelope `protocol_version` 1.0 유지 |
| v1.94 | 2026-10-04 | Additive (D-450): recipe/2 작업자 간지 지시와 Cell Job의 optional read-only `operator_checkpoints`, 공유 `CellOperatorCheckpoint` 스키마. durable HOLD·재시작/재개 우회 차단; owner 접근·삽입 확인 API는 미제공. envelope 1.0 유지 |
| v1.94 | 2026-10-04 | Additive (D-452): 별도 authenticated peers 역할 목록, 선택적 bounded scanner services, 실제 모델 SSH profile. 발견·승인·ready 분리, envelope 1.0 및 기존 등록/인증 유지 |
| v1.93 | 2026-10-04 | Additive (D-450): Fleet Console `/console/cell` 작업 화면의 revision 문서 저장·정본 compile·명시 service proposal API 및 `CellApp*Request` 스키마 추가. 기존 named operator admission/복구·원장을 재사용. envelope version 1.0 유지 |
| v1.92 | 2026-10-04 | Additive: Viewer GET /api/v1/power/health; battery age/freshness, timestamped charging evidence, software sleep blockers and wake constraints. Read-only; envelope protocol_version 1.0 unchanged. |
| v1.91 | 2026-10-04 | Additive (D-438 1단계, docs/d438-fleet-stuck-resolver): CORE 역할 `stuck_resolver`(순위 viewer)와 capability `STUCK_DECIDE`; `POST /api/v1/line-follow/stuck/decision` 은 `STUCK_DECIDE` 를 요구(operator·administrator 도 가짐), `stuck_resolver` 의 `MANUAL` 은 403. Site Fleet `POST /api/fleet/robots/{robot_id}/line-stuck/claim`(operator), 로봇 행 `line_stuck.resolver`, `robots.yaml` `resolver_token`, `fleet console --stuck-resolver`. `fleet_line_stuck_answers` 에 null 가능 열 `tier`·`rule`·`escalated`(옛 DB 는 열 때 추가), 판단기가 사람에게 올릴 때마다 `ESCALATE` 행. `GET /api/fleet/state` 와 판단기는 1 s 안에서 한 번의 gather 를 같이 쓴다. 로봇 이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.90 | 2026-10-03 | Additive (D-432): LAN 장비 목록 접속, auth/connection·auth/development-session, 선택적 CORE TLS·발견 전송과 SSH 공개 키 등록. 기존 코드 규약·envelope 1.0 유지. |
| v1.89 | 2026-10-03 | Additive (D-418, feat/d418-ssh-access): 로봇 SSH 접속 §5.8 — Admin 전용 `GET /host/ssh/host-keys`, `GET\|POST /host/ssh/keys`, `DELETE /host/ssh/keys/{label}`, `GET\|POST\|DELETE /host/ssh/password` 신설. 오류 코드 `SSH_INVALID`(422)·`SSH_LABEL_EXISTS`·`SSH_KEY_EXISTS`·`SSH_KEYS_FULL`(409)·`SSH_KEY_NOT_FOUND`(404)·`SSH_ACCESS_UNAVAILABLE`(503). 스키마 `Ssh*`(`schemas.py`). 기존 경로·필드 변화 없음. 브랜치에서 v1.84 로 적었으나 main 이 v1.84(D-422)–v1.88(D-423)을 먼저 써서 v1.89 로 재번호 |
| v1.91 | 2026-10-04 | Additive: Pilot 녹화 preview_mode raw/annotated와 live typed start capability, 실제 옵션 readback. 같은 capture의 원본/주석 JPEG pair를 bounded cache·공유 admission으로 제공하고 브라우저 파생 영상은 먼저 저장된 원본과 provenance를 보존한다. source image age로 저조도 보조 만료를 보완한다. envelope protocol_version 1.0 유지. |
| v1.90 | 2026-10-04 | Additive: `GET/PUT /line-follow/perception` 신설. Viewer 설정·signed model integrity 조회, Administrator `paint_source`만 선택. `LanePerceptionRequest/Status` 스키마, Host Agent 정지 재검사·기하 보존·원자 적용/실패 복구와 CORE IDLE motion reservation. live source 미확인은 null로 구분한다. 운전 모드·물체 검출·envelope protocol_version 1.0은 유지. |
| v1.88 | 2026-10-03 | Additive (D-423, feat/d423-object-range-detection): `GET /api/v1/vision/models`(viewer, 읽기 전용) — 로봇 학습 모델 상태를 작업별로(`lane_seg` shadow, `object_det` active). §6.1.1 에 ROS `vision/detections`(DetectionEvidence 필드 + 추가 `ranges`)를 적음 — CORE 는 구독하지 않음. 카메라 관측 영역의 `s`(`L`/`G`)·`ground_source` 는 control 내부 증거(`camera/observation`)라 이 계약 밖. 쓰기 API·이벤트·FleetAgent 변경 없음. v1.82 는 main 의 D-403/D-413 행 |
| v1.87 | 2026-10-03 | Additive (D-411 B+C, feat/d411bc-pilot-controls-gripper; A 는 v1.83 에서 먼저 들어감): B: capabilities `controls`(`rosy.controls/1`, §9.1), OMX SIM `GET /sim/omx/target` `controls`; Pilot 이 `controls` 로 주행·팔 조작부를 조립(필드 없음 = 구 서버 대체, 빈 `items` = 조작부 없음, 팔 조이스틱은 순차 제한 목표·떼면 새 목표만 멈춤). C: OMX SIM `POST /sim/omx/gripper`(`OmxSimGripperGoal`, 절대 위치·0.2–2.0 s), `/state` `gripper` readback(`open`·`closed`·`holding`·`moving`·`unknown`), `/target` `controls` 의 `gripper` 항목(그리퍼는 `joint_jog` 에서 빠짐, 선택 `max_velocity`(`GripperControl.max_velocity`), 409 `gripper_velocity_limit`), SIM 허용 범위 = 셀 프로필 ∩ URDF·알리는 범위는 0.02 rad 안쪽·목표 길이 상한 2.0 s, 쥔 채 팔 조그는 멈춘 위치 + preload, 시연 기록 `action.gripper` 열과 LeRobot 특성(선택, 이전 에피소드 유효). 기존 필드 변화 없음 |
| v1.86 | 2026-10-03 | Additive (D-419, feat/d419-saf003-fleet-loss): SAF-003 이 처음으로 동작한다. 이벤트 `safety.fleet_lost`(warning)·`safety.fleet_restored`(info), `GET /safety/state` 선택 필드 `fleet_link`, 설정 `safety.fleet_loss_timeout_s`(기본 5.0, 4–60 s)·`fleet.heartbeat_reply_timeout_s`(기본 2.0, 0.5–10 s), 판정 시간 ≥ 1 + 답 시한 + 1 (어기면 기동 실패). §7.6 판정 규칙. `PUT /safety/limits` 의 받는 값은 그대로(`RETURN_HOME` 포함), `RETURN_HOME` 이면 응답 선택 필드 `warning`. 기동 때 저장된 모르는 정책은 `STOP` 으로 읽는다. envelope `protocol_version` 1.0 유지 |
| v1.85 | 2026-10-03 | Additive (D-413): opt-in independent Cell goal-evidence ingress, shared strict submission schema, isolated producer credentials and terminal callback reconciliation with atomic latest-terminal fencing. No physical dispatch or ROS-SIM promotion. |
| v1.84 | 2026-10-03 | Additive (D-422, feat/body-referenced-obstacle-stop): `GET /api/v1/line-follow` 상태에 선택 필드 `body_gap_m`·`stop_gap_m`·`clearance_source`(`lidar`·`memory`·`ultrasonic`), `nav.line_obstacle_hold` 데이터에 같은 세 필드(몸 기준 정지일 때만). 몸 기준 정지에서 `clearance_m` 은 LiDAR 원점 거리가 아니라 몸 간격이다(path + 로봇 패키지 몸 기하에서만; sector 와 몸 기하 없는 path 는 그대로). 설정 `line_follow.body_front_x_m`·`body_ultrasonic_x_m`(URDF, 로봇 패키지), `obstacle_body_margin_m`(0.02)·`obstacle_latency_s`(0.15)·`obstacle_decel_mps2`(0.5)·`obstacle_resume_hysteresis_m`(0.03)·`obstacle_ultrasonic_half_angle_deg`(15)·`obstacle_ultrasonic_stale_s`(0.3). `obstacle_stop_m`·`obstacle_resume_m` 은 기본 yaml 에서 빠지고(비면 0.20 / 0.28 또는 유도) LiDAR 원점 기준 덮어쓰기로 남는다 — 옛 overlay 는 그대로 읽힌다. 덮어쓰기는 앞으로 가는 판정에만 쓰고 제자리 회전(회전 반경 원 밖 `obstacle_body_margin_m`)에는 쓰지 않는다. 움직이는 판정의 `stop_gap_m` 은 초음파와 상관없이 LiDAR `range_min` 사각 하한 이상이고, `range_min` 아래로 사라진 반환은 기억해 `body_gap_m` 에 계속 든다(`clearance_source: memory`; 기억은 바퀴로 나간 명령으로 적분하고 차선 추종 출력이 아니면 지운다). 기존 필드 이름·형식 변화 없음 |
| v1.83 | 2026-10-03 | Additive (D-411 A, feat/d411-pilot-recording-controls): §5.10 Pilot 로봇 녹화 (`GET/POST /api/v1/recordings`, `GET /recordings/active`, `POST /recordings/active/stop`, `GET /recordings/{id}/archive`), ERR-102 `RECORDING_BUSY`·`RECORDING_NOT_ACTIVE`·`ROBOT_MOVING`·`RECORDING_NOT_FOUND`·`RECORDING_QUOTA_FULL`·`RECORDING_DISK_FULL`·`RECORDER_UNAVAILABLE`, §8 `recording.started`·`recording.stopped`, ROS 증거 토픽 `teleop/intent`, 녹화기 상태 `boot_id`·`seq`, 설정 `recording.pilot_root`. 기존 필드 변화 없음 |
| v1.82 | 2026-10-03 | Clarify (D-403 / D-413): Fleet uses existing UDS v2 for phased CELL_TRANSFER submission, readback and cancellation; missing phase summaries fail closed. OMX already accepts the additive grant in v2. Simulation dispatch gates and independent goal requirements remain unchanged. |
| v1.81 | 2026-10-02 | Additive (D-421, feat/d421-fleet-cancel-all): Site Fleet 새 경로 `POST /api/fleet/cancel-all`(operator, §10.8) — 래치 없는 전체 주행 취소(대기 작업 `CANCELED`/`FLEET_CANCEL_ALL`, 대형 해제, 로봇마다 `swarm/cancel`·`navigation/cancel`·`line-follow/mode OFF`, 로봇별 `cancelled`/`failed`/`unreachable`, `evidence: CORE_REPLY_ONLY`). 발행 겹침 작업은 `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH`. 창마다 취소 기록(`cancel_all_id`)을 남기고, 표시된 진행 중 작업의 CORE `nav.canceled` 는 `HOLD`/`FLEET_CANCEL_ALL` 로 로봇 점유를 푼다(사건이 없으면 그대로). §10.2 에 `/api/fleet/estop` 이 래치형 전체 비상 정지임을 명시(의미 불변). FLEET SRS CTR-002 개정. 로봇 계약(`/api/v1/*`)·이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.80 | 2026-10-02 | Corrective + Additive (D-407 관제 재실행, fix/d407-console-link-and-event-fields): **Corrective** `nav.line_stuck_answered` 의 `token_id` → `principal_ref`(비밀 아닌 이름: 설정 id, 없으면 프로세스 키 HMAC `anon-…`) — Fleet 사건 저장소가 `token` 이 든 키를 자격 증명으로 보고 `EVENT_NOT_AUDITABLE` 로 거부해 이 사건이 Fleet 감사에 남지 않았다. **Additive** `nav.line_stuck_opened` `rear_state`(`clear`·`blocked`·`unknown` — `rear_clearance_m` null 이 "띠가 비었다"와 "모른다"를 함께 뜻하던 것을 가름), 거부된 `BACK_AND_RETRY` 답에 `rear_blind_m`·`trail_m`·`trail_yaw_deg`·`trail_age_s`. FleetAgent 는 hub 의 모든 답을 한 수신 루프로 읽는다(사건 답이 쌓여 연결이 끊기던 결함; envelope 형식 변화 없음, `protocol_version` 1.0). 설정 `line_follow.recovery_console_grace_s`(3 s) |
| v1.79 | 2026-10-02 | Additive (D-407, fix/d407-trail-age-and-recording-marker): `nav.line_stuck_local_attempt`·`nav.line_stuck_local_result` 에 `trail_age_s`(지나온 길의 마지막 전진 명령 뒤 경과, 단조 초). 사각 띠 후진은 그 값이 `line_follow.recovery_trail_max_age_s`(30 s) 이하일 때만 — 넘으면 `rear_blind`. 기존 필드 변화 없음 |
| v1.78 | 2026-10-02 | Additive (D-403 / D-413 Task 4): define separate `FleetCellTransferGrant` and bounded `CELL_TRANSFER` body for one recipe/cell-bound pick/place pair. Existing `PICK_PLACE` schema, payload and digest remain unchanged; Fleet dispatch stays gated on simulation evidence. |
| v1.79 | 2026-10-02 | Additive (D-403 / D-413 Task 4): scope a `service` principal to Cell Job proposals/resolution, require a distinct named operator for admission, expose ordered Cell Job status, and persist ordered `CELL_TRANSFER` steps. Existing `PICK_PLACE` records remain unchanged; device dispatch and independent goal evidence remain gated. |
| v1.77 | 2026-10-02 | Additive (D-407 Fleet 쪽, feat/d407-console-stuck-decisions): Site Fleet 새 경로 `GET /api/fleet/line-stuck`(viewer+)·`POST /api/fleet/robots/{robot_id}/line-stuck/decision`(operator), `GET /api/fleet/state` 로봇 행에 선택 필드 `line_stuck`(§10.8). Fleet 은 CORE 거부를 그대로 409 로 옮긴다. 로봇 계약(`/api/v1/*`)·이벤트·FleetAgent 프로토콜 변경 없음 |
| v1.76 | 2026-10-02 | Additive (D-407 Gazebo 후속, fix/d407-sim-findings): `nav.line_stuck_opened` 에 `restuck_of`·`attempts` — `recovered` 로 닫힌 뒤 `line_follow.recovery_restuck_s`(20 s) 안이거나 순 전진 `recovery_restuck_m`(0.30 m) 전에 다시 막히면 같은 막힘으로 시도 수를 이어 센다(다 쓰면 곧바로 관제 답만 기다림). `nav.line_stuck_local_result` 에 판정한 scan 의 `rear_clearance_m`·`rear_blind_m`·`trail_m`·`trail_yaw_deg`. `nav.line_stuck_closed` 사유 `estop`. 뒤 띠 폭은 URDF 몸 반폭(`body_half_width_m`) + `recovery_rear_lateral_margin_m`(0.02). 기존 필드 변화 없음 |
| v1.75 | 2026-10-02 | Additive (D-395 개정 4 5항 후속, S1 R1, feat/d395-localized-objects): 상태 스냅샷·하트비트 `localization` 에 선택 필드 `unmapped_objects[≤16]` `{x, y}`(base_link)·`objects_stamp`(로봇 시각 s). `LOCALIZED` 로봇이 전체 스캔의 지도 밖 물체를 상태(2 Hz)마다 싣고, 밖에서는 빈 목록이다. CORE 는 그대로 넘기고 `pose_frame: odom`·`state_stale` 에서 비운다. Fleet 감시가 닻 로봇의 관찰로 다른 `LOCALIZED` 로봇의 거울 잠금을 잡는다. 기존 필드 변화 없음 |
| v1.74 | 2026-10-02 | Additive (D-407, feat/d407-stuck-recovery-core): `POST /api/v1/line-follow/stuck/decision`, line-follow 상태 `stuck`(`LineStuckStatus`: `stuck_id, cause, phase, held_s, attempts, max_attempts, local_enabled, ask_remaining_s, last_answer, decisions`, 막힘 없으면 null)·`state` 값 `RECOVERING`·사유 `stuck_back_off`·`stuck_<phase>`, 에러 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`, 이벤트 `nav.line_stuck_opened/asked/answered/local_attempt/local_result/closed`, 설정 `line_follow.recovery_*`(로컬 복구 기본 꺼짐; `recovery_trail_s`·`recovery_trail_yaw_deg` 는 사각 띠 후진 조건)·`body_lidar_x_m`·`body_rear_x_m`·`body_rotation_radius_m`(URDF, 로봇 패키지). Fleet 콘솔·FleetAgent 답 중계는 다음 단계. 기존 필드 변화 없음 |
| v1.73 | 2026-10-02 | Additive (D-395 P2-7, feat/d395-p2-7-missions): 새 경로 `POST /localization/mission`(`LOCALIZE_ASSIST`)·`GET /localization/mission`(Viewer) — `LOCALIZED` 가 아닌 로봇에서 CORE 가 확인 기동·귀환 미션(`rotate_in_place`, `nudge_forward`, `lane_to_stopline`; `to_square` 는 409 `unsupported`)을 자기 장애물 정지·e-stop·거리·시간 한도 아래 아주 느리게 실행한다; 거부 409 코드 `localized`·`busy`·`estop`·`path_not_clear`·`calibration_lease`·`unsupported`; 이벤트 `localization.mission`. **행동 변화:** `lane_to_stopline` 미션은 이 미션에 한해 line-follow 를 `LOCALIZED` 관문 없이 켠다(공개 `PUT /line-follow/mode` 의 관문은 그대로); 미션 중에는 Nav2 `nav_cmd_vel` 을 버린다; 미션이 도는 동안 모드는 NAVIGATION 이고 MANUAL·IDLE 로 바꾸면 미션이 `cancelled` 로 끝난다 |
| v1.72 | 2026-10-01 | Additive (D-395 2단계 lane B, feat/d395-p2-core-api): 스냅샷 `localization` 을 CORE 가 실제로 채움(`localization/state`, `pose_frame` 은 CORE 가 odom 을 대신 쓰는 동안 `odom`, 3 s 무응답이면 `UNKNOWN`/`state_stale`); 새 경로 `GET /localization/candidates`, `POST /localization/decision`, `POST /localization/suspect`(§5.3, §7.9); 토큰 capability `NAVIGATE`·`LOCALIZE_ASSIST`(§2 AUTH-102, 역할에서 정해짐, Fleet operator 토큰이 가짐); 새 에러 `NOT_LOCALIZED`·`STALE_REQUEST`·`NO_CANDIDATES`, D-395 경로의 lease 거부는 423; 이벤트 `localization.state`·`localization.candidates`·`localization.result` 추가, `localization.initialpose` 에 `source` 추가(§8). **행동 변화:** D-395 로봇(`localization` 이 null 아님)에서 `navigation/goal`·`home`·`line-follow/mode`(OFF 제외)는 `LOCALIZED` 가 아니면 409, 레거시 `localization/initialpose` 는 `/initialpose` 대신 `source: human` 결정으로 가며 응답 모양은 같다; `LOCALIZED` 진입이나 결정 수락 시 진행 중 Nav2 목표를 취소한다; `LOCALIZED` 를 벗어나면(3 s 무응답 포함) swarm follow·도킹·line-follow·Nav2 를 멈추고 NAVIGATION 을 IDLE 로 내린다(MANUAL 은 그대로); `docking/dock`·`swarm/follow` 도 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED`; `LOCALIZED` 라도 `pose_frame: odom` 이면 409; 저배터리 자동 도킹은 `LOCALIZED` 까지 대기, SAF-005 `RETURN_HOME` 은 `LOCALIZED` 가 아니면 e-stop. D-395 이전 로봇은 전부 예전 그대로 |
| v1.71 | 2026-10-01 | Additive: state `safety_policy`(상태 스냅샷·Fleet 하트비트에 실림), events `safety.shadow_verdict`·`safety.policy_off` (D-400). 기존 필드 변화 없음 |
| v1.70 | 2026-10-01 | Additive (D-390 부록): OMX SIM camera 상태/JPEG, 시연 기록 시작·종료·manifest, typed 기록 상태와 task outcome. 로컬 LeRobot v3 변환; 실물 권한 변화 없음 |
| v1.69 | 2026-10-01 | Additive (D-395 1단계, feat/d395-phase1): 상태 스냅샷(`/robot/state`·`/ws/state`)·하트비트 `localization` `{state, pose_frame, confidence, reason, needs_human, request_id}`(D-395 이전 로봇은 null); §7.9 `CandidateReport`·`LocalizationDecision`(`cues`, 수신 기준 `ttl_s`) 모델(스키마만, 전송 경로 없음). 기존 필드 변화 없음 |
| v1.68 | 2026-10-01 | Additive (D-321 부록, feat/calibration-session-mode): 보정 세션 lease `GET/POST /api/v1/calibration/session`, `POST …/{id}/heartbeat`, `DELETE …/{id}`; 상태 스냅샷(`/robot/state`·`/ws/state`) `activity` (보정 중이면 `{kind: CALIBRATING, session_id, calibration_kind, label, owner, started_at, remaining_s}`, 아니면 null); 에러 `CALIBRATION_ACTIVE`(다른 토큰의 teleop·`/mode`(IDLE 제외)·line-follow 모드(OFF 제외)·hold·navigation goal/home·docking dock/undock·swarm follow 409); 이벤트 `calibration.session_started/ended/expired`. E-Stop 은 막지 않는다. 기존 필드 변화 없음 |
| v1.67 | 2026-10-01 | Additive (D-390): 격리된 OMX-AI Gazebo Pilot 전용 `/api/v1/sim/omx/*` 목표·상태·조종권 계약. 실물과 Fleet 경계는 불변. 카메라·녹화는 미구현으로 명시. |
| v1.64 | 2026-09-30 | Additive (D-344 §11·§13): 이벤트 `nav.line_obstacle_hold`(앞 물체 정지가 `line_follow.obstacle_escalate_s` 넘게 이어지면 한 번), line-follow 정지 사유 `limit_level_too_low`(수동 한도가 L1 미만이면 차선 자동 HOLD)·`angular_limit_zero`(수동 각속도 한도를 읽을 수 없음), 설정 `obstacle_mode`(`sector` 기본·`path`)·`obstacle_release_s`·`obstacle_escalate_s`·`lane_auto_min_manual_angular`·`max_angular_follows_manual`. 와이어 형식 변화 없음 |
| v1.66 | 2026-10-01 | Clarify (D-382 부합): a local Action UDS response — success or error — carries the version of the request it answers; only frames rejected before version validation answer version 1. Fixes v2 stale-fence 403 and `GetAction` 404 being read as version-unsupported by the Fleet client. |
| v1.65 | 2026-10-01 | Additive (OMX Task 6): version the same-host phased `PICK_PLACE` receipt as UDS v2 with bounded durable phase snapshots; project current phase state into Fleet progress and the existing read-only ER 2 status result. V1 remains compatible for non-phased operations; no new command, public route, or Mission-completion shortcut. |
| v1.63 | 2026-09-30 | Additive + Corrective (D-344): `PUT /line-follow/mode` 가 선택 필드 `hold_s` 를 받고 `POST /line-follow/hold`·이벤트 `nav.line_driver_released`·에러 `LINE_FOLLOW_NOT_HELD` 를 둔다 — 운전자가 누르고 있는 동안만 가는 보조 자율. **Corrective**: line-follow 요구 능력을 `navigation.goal_navigation` 에서 `mobility.move` 로 — Nav2 가 없는 실물 `motor` 런타임에서 차선 추종이 늘 거절되던 것을 고친다(증거 검사는 그대로). `hold_s` 없는 기존 호출은 동작이 같다. envelope `protocol_version` 1.0 유지 |
| v1.62 | 2026-09-30 | Additive (D-358): Vision frame replies expose width, height, and source rotation for the exact no-store JPEG. A trusted Fleet post-action reader uses the existing source-scoped lease, capture timestamp/sequence/freshness headers, and immutable workcell-to-camera mapping; the app consumes provider turns only when a shared-database worker is explicitly injected. Default CLI remains provider-disabled. |
| v1.56 | 2026-09-29 | Additive (D-337): traffic policy status gains `signal_source_kind`/`signal_head_age_s`/`signal_head_frozen`; the optional file-only `traffic_policy.signal_observer` binding fuses the observer service's measured light with camera evidence (mismatch `signal_source_conflict` HOLD, dark/indeterminate `signal_dark`, silence falls back camera-only) and emits `nav.traffic_policy_signal_source_stale` once per lapse |
| v1.57 | 2026-09-29 | Additive (D-333): add owner-scoped Mission progress axes, a 50-event recent-history window with truncation signal, and bounded snapshot-first event cursor pages. Fleet event IDs are journal order; dispatch latch is distinct from physical stop (UNKNOWN); no percentage or provider status tool is introduced. |
| v1.61 | 2026-09-30 | Additive (D-358): expose Fleet ER 2 successor-candidate source Mission/action/attempt/generation/event/observation correlation and `supersedes_mission_id`; stop/source-event drift makes the candidate non-resolvable, and resolution creates a distinct linked Mission draft. This does not enable a provider worker, trusted Vision reader, policy dispatch, or ROS. |
| v1.60 | 2026-09-30 | Additive (D-360/D-357/D-358): Vision field-corner proposals for operator review; bounded ER 2 feedback tools, trusted turn scope, stateless `store=false` replay, transcript-free SQLite outbox with durable-cursor event scheduling, hard capacity bound and explicit ambiguous `UNKNOWN` behavior. No public tool route, ER 2 provider worker/model calls, policy dispatch, or ROS enablement. |
| v1.59 | 2026-09-30 | Additive (D-348): opt-in registered goal-evidence producer route, environment-only source tokens, SQLite evidence-ID idempotency, evaluator/freshness scope, terminal-action verification and grace-timeout HOLD. No model/action dispatch or ROS enablement. |
| v1.58 | 2026-09-29 | Additive (D-347): `GET /api/v1/system/capabilities` gains the per-flag `lifecycle` block — one vocabulary (`ready`/`unavailable`+reasons, `activating` reserved with no producer yet) derived from the existing `withheld` judgment; `withheld.flags` always equals the `unavailable` set. Presentation states on inventory descriptors are unchanged; the mapping lives in D-347. |
| v1.55 | 2026-09-29 | Additive (D-333): require an injected trusted producer verifier and a new post-action observation for Mission goal confirmation. Evidence is correlated to the Action/attempt and carries frame digest, evaluator revision, and a separate `OPEN` gripper readback; absent verifier, stale/mismatched evidence leaves claims held. |
| v1.54 | 2026-09-29 | Additive (D-18): include the operator-declared `junction_rule` in traffic policy status so an unsignalized stop-and-go junction is distinct from signal-detection failure. |
| v1.53 | 2026-09-29 | Additive (D-333/D-336): connect the explicit opt-in Fleet Mission dispatcher to the same-host OMX UDS Action API. Persist stable grants before one SubmitAction; reconcile restart/lost ACK through GetAction without replay; bind receipts to digest and both fences. Dispatcher stays disabled by default; Action success remains separate from goal evidence and physical acceptance. |
| v1.52 | 2026-09-29 | Additive (D-336): define the local software-stop OPEN projection and explicit newer-generation rearm; a persisted stop latch, stale Fleet fence, or process restart blocks the final driver submission boundary. This remains separate from driver standstill and physical E-stop proof. |
| v1.51 | 2026-09-29 | Clarify (D-336): define one-frame newline JSON UDS encoding, SO_PEERCRED UID derivation, 64 KiB bound, and FleetActionGrant canonical digest; source adds a disabled-by-default local Action runner with durable attempt IDs and no unknown replay. No service entrypoint or physical capability is enabled. |
| v1.50 | 2026-09-29 | Additive (D-333/D-334): separate Site Fleet candidate storage, observation/capability resolution, Mission draft readback, and named-operator generation-checked admission routes. Proposal creation does not invoke ER 2; admission only acquires Fleet claims and remains disconnected from Device Action/ROS. |
| v1.46 | 2026-09-29 | Additive (D-330): Fleet dispatch-control readback and explicit generation-checked operator rearm; startup/stop hold, unresolved-action rearm refusal, and device-side generation fencing remains unimplemented. |
| v1.47 | 2026-09-29 | Clarify (D-330): dedicated operator E-stop fanout proceeds on audit/latch/queue-storage failure with server logging; ordinary mutations remain audit fail-closed; request replies do not prove physical stop. |
| v1.49 | 2026-09-29 | Additive (D-333/D-336): typed Site Fleet-to-OMX local Device Action and software-stop contracts, same-host UDS boundary, attempt/generation fences, and explicit separation from Mission goal evidence and physical stop proof. No REST path, PRT envelope change, listener, runner, or device capability is implied. |
| v1.48 | 2026-09-29 | Additive (D-268 승격 사다리 1단계): Site Fleet 정책 적격 증거 계약 — source-token 제출·readback, `PolicyEvidencePayload`, `evidence_id` 멱등(다른 내용 409 `EVIDENCE_REPLAY`), transit 0~300 ms, v1 빈 관측 등록부로 잘 구성된 제출도 전부 거절(fail-closed), policy 작업 제출은 `evidence_id` 참조 필수(400 `INVALID_EVIDENCE_REFERENCE`)이며 admission 사유와 함께 HOLD. `POLICY_DISPATCH_ENABLED` False 유지 — 자동 실행 불변 |
| v1.44 | 2026-09-28 | Additive (D-316): correlate Pinky Site Fleet navigation attempts through optional CORE REST metadata and CORE navigation events; project matching results into durable task status. PRT-004/Envelope ACK and physical stop readback remain separate. |
| v1.45 | 2026-09-28 | Additive (D-318): bounded rectification settings in signed Site Fleet Vision preview leases; Vision applies OpenCV lens and plane correction only to the returned latest-frame preview copy. Raw sighting input and robot command paths are unchanged. |
| v1.43 | 2026-09-28 | Additive (D-313): CORE binds IR fallback to fresh IR-line evidence and its configured calibration digest; Fleet operator selection forwards through CORE. Refuse Nav2 goal/home while line-follow owns motion. Robot DDS/WSS envelope remains 1.0. |
| v1.41 | 2026-09-27 | Corrective(P0, D-297): document the observed navigation task/CORE event correlation gap and replace stale D-177 activation references. No path, schema, runtime, or robot PRT envelope change. |
| v1.40 | 2026-09-26 | Additive (D-293): typed Site Fleet intent/OpenAPI grammar, server-derived priority and identity, durable task/audit semantics, and purpose-specific message boundaries. No robot PRT envelope change. |
| v1.39 | 2026-09-26 | Additive: Operator camera preview screenshot/video evidence upload, list, download and bounded `VisionEvidenceRecord`/`VisionEvidenceList`. Browser PC storage stays local. Robot DDS/WSS envelope version remains 1.0. |
| v1.38 | 2026-09-26 | Robot FleetAgent location: paired robots may resolve a pinned site over mDNS with CA/TLS verification; no envelope change. |
| v1.37 | 2026-09-26 | Additive: site-only mDNS scan/readback and `DiscoveryScanPayload`; no robot envelope change. |
| v1.36 | 2026-09-26 | Additive(D-283): `UiPanelDescriptor.action_group` optional field exposes console operation groups. Only role-, capability-, and inventory-visible panels are included; unsupported action groups are absent. |
| v1.35 | 2026-09-26 | Additive(D-276): authenticated Fleet session identity endpoint for the console role cue. Robot DDS/WSS envelope version remains 1.0. |
| v1.34 | 2026-09-26 | Clarify(D-276 Accepted): individual site-user token digests, viewer/operator/policy-admin API roles, operator task actor identity, and pre-dispatch append-only mutation audit. Robot DDS/WSS envelope version remains 1.0. |
| v1.32 | 2026-09-26 | Additive(D-271): Fleet task `QUEUED` lifecycle, status/receipt semantics, shared `FleetTaskStatus`, and queued-only cancel contract. Robot DDS/WSS envelope version remains 1.0. |
| v1.33 | 2026-09-26 | Additive(D-271): Fleet console queued-task feedback/readback/cancel and cancel/stop/E-Stop queue coordination. |
| v1.31 | 2026-09-26 | Additive(D-269 Proposed): operator navigation `Idempotency-Key`, durable task status/history, authenticated `/api/fleet/tasks/{task_id}` readback. Policy work remains `HOLD`; D-177 command ACK and per-user identity are not implemented. |
| v1.30 | 2026-09-26 | Additive(D-269 Proposed): paired CORE Agent 이벤트를 credential-free bounded SQLite audit history에 저장, 중복 `event_id` 멱등 처리, 인증된 cursor 기반 `/api/fleet/events` 조회. 이는 자동 작업 승인이나 D-177 command ACK 구현을 뜻하지 않음 |
| v1.29 | 2026-09-26 | Clarify(D-257/D-269 Proposed): Fleet CLI source config와 SQLite latest/history storage, HTTPS API path 및 site Docker TLS boundaries. Synthetic Docker WSS→vision→Fleet readback은 LOCAL evidence만 제공; D-268/자동 실행 상태 불변 |
| v1.28 | 2026-09-26 | Additive(D-257 Proposed): Site Fleet sighting `quality`는 미측정 시 `null` 허용. 표시 전용이며 D-268 정책 증거로 사용하지 않음. envelope `protocol_version` 1.0 유지 |
| v1.26 | 2026-09-26 | Additive(D-257 Proposed): Site Fleet 전용 source-token `POST /api/fleet/sightings`, operator `GET` readback 및 `SiteSightingPayload` shared schema. 파생 pose만 전달하며 source identity는 서버가 token에서 결정. 1 s 표시 lease, D-268 자동 정책 경로는 계속 별도/HOLD |
| v1.25 | 2026-09-26 | Additive(D-260 5): `GET /host/status-summary`(Viewer) 신설 — 로봇 상태 하나·이유·장치 요약·배터리·온도·할 일. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.24 | 2026-09-26 | Additive(D-263/D-265): 역할별 기반 화면 `GET /api/v1/ui/surfaces/{surface}` 및 `UiSurfaceManifest` REST 응답 스키마. 메뉴 노출은 패널 수와 독립이며 직접 요청은 역할에 따라 401/403/404. Fleet envelope `protocol_version` 1.0 유지 |
| v1.27 | 2026-09-26 | Additive: `GET /api/v1/docking/types` 는 Viewer가 설정된 도크 검출기 유형을 조회한다. `/types`의 POST 권한은 계속 Admin이며 도크 유형 구성 응답만 추가한다. |
| v1.23 | 2026-09-26 | Additive(D-247 6): `POST /host/hardware/test`·`POST /host/hardware/confirm`(Admin) 신설, `HW_TEST_COOLDOWN`(429)·`HW_TEST_UNAVAILABLE`(503)·`HW_CONFIRM_UNAVAILABLE`(503)·`HW_CONFIRM_NO_TEST`(409), `GET /host/hardware`의 `test` 필드와 `source:"human"` 행 덮기 추가. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.22 | 2026-09-25 | Additive(D-247): `GET /host/hardware`(Viewer)·`POST /host/hardware/refresh`(Admin) 신설, 에러 코드 `HW_PROBE_UNAVAILABLE`(503) 신설, `GET /host/commissioning` 에 `motion_reason` 필드 추가. 기존 필드 불변 — envelope `protocol_version` 1.0 유지 |
| v1.21 | 2026-09-25 | Additive: 이벤트 `swarm.succession`(warning) `{leader, dead, role, by}` 문서화 — 공유 명단 대형에서 죽은 리더를 교체할 때 이미 발행되고 있었으나 §8 에 없었다. 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.21 | 2026-09-24 | Corrective + Additive, 실기(rosy-pinky-e4us, release 2026.09.24-010, CORE-only 이미지 + 무동작 `rosy-io`) 근거. **Corrective**: CAP-001 `withheld` 판정이 설정 문자열 대신 살아 있는 증거를 쓴다 — 무동작 모드(`motor/ready: false`)에서 `teleop`·이동 플래그를 광고하던 것(D-32 위반)을 `drive_disabled:no_motion` 으로 내린다. 새 이유 `hardware_silent`·`drive_lease_expired`·`drive_absent`·`navigation_absent`. inventory descriptor 의 `reason` 은 런타임 이유가 `device_state` 보다 먼저다(≠v1.18). **Additive**: `withheld.reasons`(플래그별), `capabilities.runtime`(`hardware`·`evidence`·`drive`·`navigation`·`maps`), descriptor `reasons`. envelope `protocol_version` 1.0 유지 |
| v1.20 | 2026-09-24 | Additive + Corrective. **Additive**: 에러 코드 `LINE_FOLLOW_ACTIVE`(409)·`NO_ODOMETRY`(409) 신설. `POST /docking/dock` 는 라인 추종 중 409 `LINE_FOLLOW_ACTIVE`, DOCKING 모드를 쥘 수 없으면 409 `MODE_CONFLICT`; `POST /docking/undock` 는 여기에 오도메트리 부재 시 409 `NO_ODOMETRY`. `PUT /line-follow/mode` 는 도킹/언도킹 중 409 `DOCKING_ACTIVE`. `POST /docking/types` 에 주차형 도크 선택 필드(`tag_id`·`tag_size_m`·`staging`·`approach`·`settle`·`tag_offset_m`·`acquire_creep_m`·`backoff_m`·`undock_turn_rad`) — 생략하면 기존 동작. **Corrective**(코드를 고친 것): 내비게이션의 `DOCKING_ACTIVE` 거부가 HTTP 매핑이 없어 400 으로 나가던 것을 문서대로 409 로(409≠400). 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.19 | 2026-09-24 | Additive(D-193): `auth/pair`·`auth/whoami`·`auth/logout`·`auth/enrollment-codes`, `PATCH system/tokens/{id}`. 토큰 목록에 `expires_at`·`source`·`current`·`last_used_at`, 생성 응답에 `expires_at`·`source`. 이벤트 `auth.paired`·`auth.code_burned`·`auth.enrollment_code_issued`·`auth.credentials_refused`. `whoami` 가 신원의 정본이고 `system/info.caller_role`(v1.18)은 호환용으로 남는다. WebSocket 첫 메시지 인증(`?token=` 은 한 릴리스 동안 유지). S3: `auth/pair` 의 코드를 폐기시킨 401 에 `error.detail.burned`, 대시보드는 첫 메시지 인증만 쓴다. **동작 변경**: 만료된 토큰은 401, 마지막 관리자 규칙은 만료 없는 administrator 만 센다, 장치 기본값에 토큰이 없다(개발 토큰은 `ROSY_DEV_AUTH=1` 일 때만, 장치 모드는 거부) |
| v1.18 | 2026-09-24 | US-010, 실기(rosy-pinky-e4us, CORE-only) 근거. **Corrective**: `battery.percent` 는 값이 없을 때 `null`(≠`0.0`) — 0.0 은 지어낸 치명 경보였다(D-82 Law 0). 형은 `number \| null` 이고 `voltage` 와 같은 규약이다. CORE-only 에서 값이 한 번도 오지 않은 evidence 채널은 `unavailable`(≠`disconnected`). `system/info` 의 `robot_name` 은 이름이 기본값뿐이면 프로비저닝 신원에서 온다(≠`Rosy 01`). **Additive**: `system/info.caller_role`, CAP-001 `withheld` 와 CORE-only 동안 하드웨어 플래그 `false`·descriptor `blocked`(`runtime_mode:core`) (D-32). envelope `protocol_version` 1.0 유지 |
| v1.17 | 2026-09-23 | Additive: `logs/audit` 의 `log` 에 `dir_sync_failures`·`last_dir_sync_error`, `/metrics` 에 `rosy_audit_dir_sync_failures_total`(counter). 정리의 바꿔 끼우기 뒤 디렉터리 fsync 실패를 정리 실패(`prune_failures`)에서 떼어 센다 — 파일은 이미 정리됐다 |
| v1.16 | 2026-09-22 | 상태 표기·계약 명확화: §10 Fleet REST 카탈로그에 **미구현** 표기(시드는 :8090 `/api/fleet/*`), §1 `Deprecation`/`Sunset` 헤더 구현 시점 명시, §2 AUTH-103 CORS 미제공 제약, §4 enum 대소문자 표. 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.15 | 2026-09-22 | 상태 표기 정정: §7.5 PRT-004 로봇 측 구현(correlation_id 소비·AckPayload 확장)을 중앙 Fleet 서버 착수 조건부로 명시 (ADR D-170). 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.14 | 2026-09-22 | Additive: `logs/audit` 응답에 `log` (기록 상태 — `writable`·`write_failures`·`write_failures_total`·`prune_failures`·`prune_skipped`·`serialize_failures`·`last_write_error`·`last_prune_error`·`last_skip_reason`·`last_serialize_error`), `/metrics` 에 `rosy_audit_write_failures_consecutive`(gauge)·`rosy_audit_write_failures_total`·`rosy_audit_prune_failures_total`·`rosy_audit_prune_skipped_total`·`rosy_audit_serialize_failures_total`(counter). 감사 기록 실패는 EventBus 가 삼켜 어디에도 남지 않았다. 조회는 이제 파일을 재작성하지 않고 메모리에서 걸러 답한다 — 보존 약속(30 일)은 그대로고, 이벤트 목록의 모양도 그대로다 |
| v1.13 | 2026-09-22 | Corrective + Additive. **Corrective**: 이벤트 카탈로그(§8)가 실제 발행과 갈라져 있던 것을 맞춤. payload 키명 — `nav.stuck` 은 `timeout_s`(≠`timeout_ms`), `mode.changed` 는 `by`(≠`source`), `nav.started` 는 `{goal, by}`(≠`{goal\|waypoint}`), `nav.completed`·`system.shutdown` 은 payload 없음(≠기존 표기), `nav.lane_lost` 는 `{mode, reason, lost_after_s}`(≠`{lost_ms}`), `slam.*`·`presence.*` 는 이벤트별로 다름. 심각도 — 문서를 고친 것: `nav.lane_lost` 는 warning(≠error). 코드를 고친 것: `config.changed`·`swarm.aborted` 는 문서대로 warning 을 실제로 싣는다(≠기본값 info). 문서를 그대로 읽은 소비자는 이 목록만큼 이미 깨져 있었다. **Additive**: 구현돼 있지만 적혀 있지 않던 `docking.*` 11 종, `battery.deep`(D-27), `battery.shutdown_request_failed`, `localization.initialpose`, `nav.line_mode_changed`(D-143), `nav.traffic_policy_staged/applied/reset`(D-151), `sim.traffic_signal_changed` 신규 문서화, `config.changed` key 에 `dds.rmw`. `safety.watchdog` 은 v1.0 부터 약속만 있었고 이제 실제로 발행된다(SAF-002). `nav.blocked` 는 미구현 표시. 카탈로그와 발행 지점의 일치는 `src/runtime/gateway/test/test_event_catalogue.py` 가 고정한다 |
| v1.12 | 2026-09-21 | Additive: 인증된 front camera preview status/JPEG API. latest-only bounded frame, source/overlay/sequence 메타데이터, stale 시 404, raw image의 상태 WebSocket·Fleet·명령 경로 제외 |
| v1.11 | 2026-09-21 | Additive: semantic road `traffic_policy` 상태와 §6.1.1 vision `DetectionEvidence.inference_ms`(선택). map/scene/policy revision과 camera evidence를 결합한 fail-closed traffic policy, 추론 지연 메타, `core_common.protocol.detections`와 control 생산 스냅샷 동기 계약을 추가. envelope `protocol_version`은 1.0 유지 |
| v1.10 | 2026-09-21 | Additive: D-143 `line-follow` 조회·모드 선택 API와 상태 스냅샷 `line_follow`. IR/카메라 소스는 상호 배타적이며 stale·저신뢰·형식 오류는 0 명령, 3초 손실은 재선택 전까지 `LOST` latch |
| v1.9 | 2026-09-20 | Additive: §6.1.1 vision `DetectionEvidence` — 박스 정규화 좌표, `model_revision` 바인딩(D-47), 신선도 300 ms(D-136), 빈 detections/seq 점프 구분, 자문 전용(SAF-006, D-137). envelope `protocol_version` 은 1.0 유지 |
| v1.8 | 2026-09-17 | Additive: §6.1 스냅샷에 채널별 `evidence` — 서버가 `fresh`/`delayed`/`disconnected`/`unavailable` 과 그 판정의 `stale_after_s` 를 계산해 싣는다. 타임스탬프만 주고 클라이언트가 임계값을 하드코딩하는 경로는 계약이 아니다(D-18, D-72 S3). `GET /api/v1/robot/state` 와 `/ws/state` 가 동일 필드다. envelope `protocol_version` 은 1.0 유지(PRT-006 additive / MINOR 는 문서 쪽) |
| v1.7 | 2026-09-06 | Additive: §7.8 pose payload 에 `map_id` — 다른 맵의 참조 pose 는 목표가 되지 않고 `swarm.hold(map_mismatch)` 를 낸다(MAP-002 를 추종으로 확장). `swarm/state` 에 `max_speed`·`map_mismatch`, `safety/state` 에 `limits.session_linear` 추가. `max_speed` 는 이제 검증만이 아니라 실제 상한으로 적용된다. 그리고 정정: `slam/reset` 은 리셋하지 않았는데도 200 을 돌려주고 있었다. 런타임 미지원은 501 `CAPABILITY_NOT_SUPPORTED`, 세션 없음은 400 `VALIDATION_ERROR` 로 답한다 — CAP-003 준수 시정이며 의미 변경이 아니다(200 쪽이 위반이었다). D-32 |
| v1.6 | 2026-09-06 | Additive: DIAG-001 `diagnostics` 조회 구현. 군집 추종 구현 — `swarm/follow·cancel·state` 가 실제로 서빙되고, `/ws/swarm/pose`(SWM-003)·`/ws/swarm/reference`(SWM-007) 소켓 신설(§7.8, D-31). `swarm/state` 에 `holding`·`target_robot_id`·`source`·`stream_age_s` 추가 |
| v1.5 | 2026-09-06 | Additive: 현장 설정 — `PUT system/info`, `system/tokens/*`, `system/runtime`, `host/*` 릴레이 카탈로그(§5.7) 신설. `safety/limits` 에 `fleet_loss_policy`·배터리 임계값 추가(SAF-004/005). 미구현 상태였던 `diagnostics/*`·`ros/*`·`swarm/*` 행에 표시. 토큰은 해시 저장이며 목록은 불투명 `id` 로 식별한다(D-30) |
| v1.4 | 2026-09-01 | Additive: 절전/근접 웨이크 — `power/*` REST, 스냅샷 `power` 필드, 이벤트 `power.*`·`presence.*`, 센서 `ultrasonic` (PWR-001~004, D-24) |
| v1.3 | 2026-08-29 | Additive: 이벤트 `slam.started`/`slam.stopped` (NAV-005 세션 API 구현에 수반) |
| v1.2 | 2026-08-29 | Additive: `swarm/follow`에 `source` 필드(fleet 기본, peer 예약 — D-21 분산 진화 훅), SWM-007 |
| v1.1 | 2026-08-29 | Additive: swarm 인터페이스 — `swarm/follow·cancel·state` REST, envelope `pose` 스트림(§7.8), 이벤트 `swarm.*`, capability `swarm` 필드 (D-20) |
| v1.0 | 2026-08-29 | 최초 작성. PKY-CORE-SRS-001 v0.1의 API 산재 정의를 통합·확장 (버전·폐기 정책, 에러코드, 이벤트 카탈로그, Fleet↔Robot 프로토콜, 데이터 스키마, Fleet API 신설) |


### D-432 구현 보충 — 발견과 승인 (2026-10-03)

CORE `network.tls = {cert_file, key_file}`는 읽을 수 있는 절대 경로의 인증서·키를 시작 전에 검증하며 실패하면 HTTP로 대체하지 않는다. `network.connection_mode` 기본값은 `paired`; `development`는 `link_policy_file`의 사이트·장치·예상 `.local` 호스트·UTC 만료와 TLS를 모두 요구한다. Fleet 로스터의 `tls_ca_file`, `discovery: true`, `link_policy_file`은 인증된 HTTPS/WSS에서만 주소 갱신을 허용한다. 공개 HTTP 로스터는 기존 등록 주소를 유지한다. 개발 모드는 운전 모드가 아니다.

현재 로봇 로그인·등록은 기존 8자 코드, Cam 승인은 기존 6자리 숫자 코드다. 4자 숫자·영문 통합은 D-432의 추후 적용 사항이며 이번 API 계약에 활성화하지 않는다. 기존 TLS leaf·양쪽 nonce 결합, 지문 확인, 권한별 자격 및 감사 규칙을 유지한다.

`POST /api/v1/host/ssh/pair` (administrator, HTTPS 전용): `SshPairRequest {public_key, confirmed:false}`. `public_key`는 옵션 없는 Ed25519 공개키이며 최대 512자다. `confirmed:true`에서만 Host Agent `ssh.register_key`로 릴레이한다. 기존 host 릴레이 응답 `{available, ok, code, detail, recovery, data}`를 사용한다. 성공 data는 `{account:"rosy", port:22, public_key_fingerprint, host_public_key, host_key_fingerprint, already_registered}`이며 개인키·암호는 반환하지 않는다. TLS 없는 요청은 403, 권한 부족은 기존 admin 검사, Host Agent 부재·거부는 `available/ok`로 구분한다. 원시 화면 코드·API 토큰은 응답 로그에 남기지 않는다.


### v1.90 — D-432 장비 목록 자동 접속 추가 결정 (2026-10-03)

Pilot은 같은 LAN에서 발견한 장비 목록으로 시작한다. 설정 파일 가져오기·주소 입력은 필수 단계가 아니다.
앞 D-432 절의 개발 연결 정책 파일·TLS 필수 조건은 다음 명시적 로컬 개발 경로에 한해 개정한다.

| Method/path | Admission | Response |
|---|---|---|
| `GET /api/v1/auth/connection` | LAN peer, 인증 불필요, `no-store` | 200 `{mode: paired|development, robot_id: string, transport: http|https}` (`ConnectionInfo`) |
| `POST /api/v1/auth/development-session` | 아래 개발 조건, LAN peer, 허용 Host와 같은 Origin 또는 Origin 없음 | 201 `{id, token, role: operator, label, source: pair-development, expires_at}` |

개발 자동 접속은 장비의 `network.connection_mode=development`와 `ROSY_DEPLOYMENT=development`가
동시에 지정된 경우만 허용한다. 기본 `paired`, `device`·생산·미지정 배포는 403이다. 기존 LAN HTTP API는
개발 예외로 사용할 수 있다. TLS 광고는 HTTPS 필수이며 인증서 오류 시 HTTP로 재시도하지 않는다.
개발 세션은 1시간, 살아 있는 세션 최대 8개, IP별 분당 5회·전체 분당 30회 제한이다. 만료 세션은 다음 발급 시
정리하고 모드·배포가 바뀌면 기존 개발 자격도 즉시 거부한다. token 원문은 응답에서만 전달하며 저장은 digest다.
`POST /api/v1/auth/logout`으로 자기 개발 세션을 회수할 수 있다. 관리자 코드 발급·SSH 등록 권한은 주지 않는다.
외부 Host·Origin은 거부한다. HTTP 자격을 DHCP의 새 주소로 자동 전달하지 않고 연결을 닫아 다시 입장한다.
기존 `POST /api/v1/auth/pair`는 8자리 코드로 일반 모드에 연결한다. 새 접속 API가 없는 기존 로봇도 이 경로로 연결한다.
envelope `protocol_version`은 1.0이다. 발견은 신뢰·안전 승인·액추에이터 허용의 증거가 아니다.


## D-456 Fleet/Cam LAN 수신 승인 프로파일

API Reference v1.104의 additive minor 변경이며 envelope 1.0은 유지한다. CORE 운영자 로그인과 Fleet 영상 자격은 서로 다른 권한이다.
`core_common.protocol.camera_peer`가 새 typed wire의 원천이며 기존 v1은 유지한다.

| 항목 | 계약 |
|---|---|
| profile | `rosy.camera-peer/1` |
| audience | `fleet-camera-ingest` |
| device_kind | `overhead-camera` |
| source_role | `camera` |
| 발급 자격 role | 기존 `overhead-camera` |
| TLS endpoint | 선택한 수신 장비의 기존 사이트 HTTPS origin; frame ingress와 동일 |
| 발견 TXT | 기존 `pair=rosy-pair/1`에 선택적 `peer=rosy.camera-peer/1` 추가 |

새 TXT는 capability hint이며 신원·준비 상태·승인 증거가 아니다. 새 signed site의
resolved Compose가 camera profile과 pairing CA/TLS/named-users/SQLite/sync 설정을
포함하고 기존 pairing이 활성일 때만 public env와 overhead advertiser가 추가한다.
권한·네트워크 daemon·수동 IP 설정은 추가하지 않는다. 실제 HTTPS identity/proof가
실패하면 자격을 전달하지 않는다. 광고로 CA, source 또는 endpoint를 바꾸지 않는다.

`/api/fleet/pairing/v2`는 HTTPS 전용이다. 초기 anonymous identity는 locally configured
site CA가 실제 configured leaf/chain/hostname을 검증한 public anchor만 제공한다.
client는 기존 D341 limited first-contact 및 물리 수신 지문 비교 후 operational proof로
넘어간다. QR/4문자에 bearer를 담지 않는다; 4문자는 요청 비교용이다.

| 경로 | 권한·결과 |
|---|---|
| GET `/identity` | anonymous, IdentitySnapshot, 공개 receiver P256 key와 CA |
| POST `/requests` | anonymous, SignedRequest -> CreatedRequest, 메모리 대기만 생성 |
| GET `/pending` | 실제 현재 named configured operator, PendingRequest 목록 |
| GET `/relationships` | 같은 operator, RelationshipSnapshot 목록; 비밀/digest 미노출 |
| GET `/requests/{id}` | request_secret Bearer, StateSnapshot |
| POST `/requests/{id}/cancel` | request_secret Bearer, 아직 pending인 요청만 취소 |
| POST `/requests/{id}/decision` | named operator; action/revision/source_id/persist_requested |
| POST `/challenge` | remembered relationship_id/generation; signed 60초 ChallengeSnapshot |
| POST `/session` | SignedSession; 원래 key/source/profile/generation에만 영상 자격 발급 |
| POST `/relationships/{id}/revoke` | current named operator, 관계 세대 폐기와 자식 자격 회수 |

모든 응답은 no-store. 승인 결과는 `credential_issued=false`이고 실제 session 발급과
구별한다. 관계의 `authorization_available=false`는 기록 삭제가 아니라 갱신 불가다.
relationship_id=request_id로 승인 직후 응답 유실/재시작 상태를 복구한다. request secret은
digest로만 SQLite에 보관하고 승인 전 요청은 restart 때 잊는다.

단기 자격은 기존 최대 180일과 사이트가 정한 더 짧은 credential lifetime을 넘지 않는다.
`persist_requested=true`와 실제 `site-users.yaml` strict loader의 configured static
named operator (principal_id+role+token digest)를 함께 확인한 경우만 관계 만료를 두지
않는다. direct-config의 extra expiry/unknown metadata를 버려 영구 issuer로 만드는
변환은 거부한다. 이 slice에는 임시 named-site-user issuer를 새로 만드는 기능이 없다.
remember=false 관계는 자격 lifetime으로 제한하고 기록은 남긴다.

issuer principal/digest/role/provenance는 갱신 및 sync 때 현재 loaded site config와
다시 비교한다. named user 변경은 기존 loader/restart 경계를 따른다. remembered
source는 오프라인/자격 만료 뒤에도 다른 key에 재할당하지 않으며 명시적 revoke가 필요하다.
SQLite 트랜잭션은 nonce 소비와 자격 digest/관계 marker/감사를 한 번에 commit한다.
재접속은 이전 active 자식을 대체하고 관계별 최근 자격 이력 4개만 남긴다.
missing/malformed marker, missing relationship, generation/issuer/source 불일치는
new camera credential을 legacy credential로 취급하지 않는다.

기존 Vision sync body와 source/lease/capability는 바꾸지 않는다. 정상 sync는 2초 주기이고
실패 때 last-good 목록은 기존 600초 한도를 유지하므로 즉시 offline revoke를 주장하지 않는다.
CORE route/좌석/주행/정지 해제나 카메라 시작 권한은 발급하지 않는다.

한도: pending 16개/300초+closed 300초, request 및 proof 각각 site-wide 30회/분,
status 600회/분 및 valid request별 2초, poll cache 144개, relationship 128개,
challenge 64개/60초, request body 4096bytes, transcript 4096bytes. 한도는 기존 상태를
밀어내지 않고 거부한다. receiver 웹 polling은 2.5초 singleflight이며 hidden/offscreen/
locked/lifetime 종료 시 멈춘다.

현재 source/host 후보이며 실제 Native Cam 연결, 배포/재부팅/lease 수용은 별도다.

## Typed field handoff for API v1.104

Every v2 expires_at and authorization_expires_at is an ISO-8601 UTC string,
for example 2026-10-05T00:05:00Z. Unchanged v1 Vision credential sync uses numeric
Unix seconds for expires_at; do not substitute the numeric field in v2 examples.
No live token belongs in a public example. State retains credential_issued=false
even after approval; SessionSnapshot alone contains the newly issued credential.
persistent=true plus authorization_expires_at=null describes only the explicit
remembered static-owner relationship, not child credential expiration.
SessionSnapshot role is exactly overhead-camera. Signed profile source_role=camera,
device_kind=overhead-camera, audience=fleet-camera-ingest and profile=rosy.camera-peer/1
remain mandatory. ChallengeFields/SessionSnapshot source_id is immutable. Initial
generation is 0; revocation increments it. Four-character display code is unique
among current bounded requests and is not a secret. Request status/cancel require
the exact request-secret Bearer header.

SessionSnapshot credential_id는 `^cam-peer-[A-Za-z0-9_-]{24}$` 전용 namespace다.
P-256 public key는 canonical padded Base64 DER SPKI이며 키 digest는 DER의 SHA256이다.
서명은 DER ECDSA SHA256이고 canonical padded Base64를 사용한다. 서명 입력은
`{version: rosy.peer-proof/1, context, fields}`의 키 정렬·공백 없는 ensure_ascii JSON이다.
context는 request, receiver-challenge, session-request로 분리한다. 공개 golden vector는
`test/fixtures/protocol/camera-peer.v1.json`이며 Native Cam resource와 바이트가 같아야 한다.
