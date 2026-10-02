# ROSY API & Protocol Reference
## 공유 인터페이스 계약서

**Document ID:** ROSY-API-REF-001
**Version:** v1.83
**Status:** Approved
**대상 독자:** rosy_core 개발자, rosy_fleet 개발자, 외부 SDK·AI·연동 시스템

> **거버넌스:** 본 문서는 로봇(rosy_core)과 Fleet(rosy_fleet)이 **공유하는 유일한 인터페이스 계약**이다.
> 본 문서의 변경은 양측 합의 + 문서 버전 업을 통해서만 가능하며(일방 변경 금지), 구현은 본 문서에 명시된 스키마를 임의로 확장하지 않는다.
> 구현 시 본 문서를 OpenAPI(YAML)로 기계 판독 가능하게 유지하는 것을 원칙으로 한다(계약 테스트의 원천).

**관련 문서:** ROSY-CORE-SRS-001 / ROSY-FLEET-SRS-001 / ROSY-ADR-001 / ROSY-PLN-001

---

# 1. 버저닝 및 폐기 정책

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
| `STUCK_DECISION_REFUSED` | 409 | 막힘 답을 지금 실행할 수 없음 — `RESUME`: 경로 띠 안 물체가 `obstacle_stop_m` 안이거나 scan 이 `clearance_stale_s` 보다 오래되었거나 LiDAR 정지를 쓰는데 scan 이 없음; `BACK_AND_RETRY`: 로컬 복구 꺼짐·시도 소진·뒤 여유 부족·LiDAR 사각·몸 기하 미설정·scan stale. 메시지에 사유 (D-407, v1.74) | 로봇 |
| `LINE_FOLLOW_ACTIVE` | 409 | 라인 추종이 켜져 있어 도킹/언도킹을 시작하지 않음 — `line-follow/mode` 를 `OFF` 로 먼저 (v1.18) | 로봇 |
| `IR_FALLBACK_NOT_READY` | 409 | 카메라 고장 상태, IR 라인 증거 최신성, 보정 revision, 또는 센서 안전 정책을 만족하지 못함 | 로봇 |
| `NO_ODOMETRY` | 409 | 오도메트리가 없어 언도킹 후진 거리를 잴 수 없음 (v1.18) | 로봇 |
| `RECORDING_BUSY` | 409 | Pilot 로봇 녹화가 진행 중이거나 manifest 해시를 끝내는 중(`stopping`) — 동시 녹화는 1개, 그동안 시작·수신 불가 (D-411, v1.83) | 로봇 |
| `RECORDING_NOT_ACTIVE` | 409 | 정지할 녹화가 없음 (`POST /recordings/active/stop`, D-411, v1.83) | 로봇 |
| `ROBOT_MOVING` | 409 | 녹화 수신은 정지 중에만: 살아 있는 MANUAL 입력 없음·NAVIGATION/DOCKING 아님·line-follow OFF·신선한 0 속도(또는 E-Stop). MANUAL 모드 자체는 막지 않는다 (D-411, D-136 §6, v1.83) | 로봇 |
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
| GET | `/api/v1/system/capabilities` | Viewer | CAP-001. 지킬 수 있는 것만 광고한다(D-32) — §9.1 `withheld`, `runtime`(v1.21) |
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
| POST | `/api/v1/power/wake` | Operator | PWR-004 (원격 웨이크 — 정보 화면 표시) |
| POST | `/api/v1/power/mode` | Operator | PWR-001 (payload: `{mode: ACTIVE\|IDLE\|STANDBY}`) |

## 5.3 Navigation·SLAM

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| POST | `/api/v1/navigation/goal` | Operator | NAV-001 (`{x,y,yaw}` 또는 `{waypoint}`; 선택적 `correlation_id`는 Fleet dispatch 시도 ID와 실행 이벤트를 잇는 추적 메타데이터). 기능 보류 시 모드 전이 전에 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/navigation/cancel` | Operator | NAV-002 |
| POST | `/api/v1/navigation/home` | Operator | NAV-003. 기능 보류 시 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| GET | `/api/v1/navigation/state` | Viewer | NAV-004 |
| GET | `/api/v1/navigation/path` | Viewer | MAP-003 |
| GET | `/api/v1/line-follow` | Viewer | D-143 — 선택 모드, 상태, 증거 신뢰도·나이, 최종 선속도·각속도와 사유. `clearance_m`(정면 LiDAR 최소 거리, 없으면 null)과 정지 사유 `obstacle_ahead`·`obstacle_sensor_stale`·`driver_released` (D-344, v1.63). IR 이탈 감시(`line_follow.ir_guard_enabled`)가 켜지면 추종 사유 `lane_edge_left`·`lane_edge_right`(경계 반대로 비킴)와 정지 사유 `lane_departure`·`lane_guard_stale` (D-344 §12, v1.63). 공칭 지면(`ground: NOMINAL`) 카메라 증거는 `hold_s` 세션이 없으면 `nominal_ground_requires_driver` 로 멈춘다 (D-364 §3, v1.63). 정지 사유 `limit_level_too_low`(수동 한도 L1 미만)·`angular_limit_zero`(각속도 한도를 읽을 수 없음) (D-344 §13, feat/device-prep, v1.64) |
| PUT | `/api/v1/line-follow/mode` | Operator | D-143 — `{mode: OFF\|IR_LINE\|CAMERA_LINE, hold_s?}`. 소스는 상호 배타적이며 변경 즉시 이전 증거와 명령을 폐기. 도킹/언도킹 중에는 409 `DOCKING_ACTIVE` (v1.18). 요구 능력은 구동(`mobility.move`)이다 — Nav2 가 없는 `motor` 런타임에서도 켜진다(D-344 §7, v1.63). `hold_s`(0 < s ≤ 2)를 주면 운전자 확인 세션이다: `POST /line-follow/hold` 가 그 안에 계속 와야 하고, 끊기면 CORE 가 스스로 OFF(`reason: driver_released`)로 내리고 바퀴 명령을 지운다(D-344 §8, v1.63). OFF 가 아닌 모드는 D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/line-follow/hold` | Operator | D-344 §8 — 운전자가 "진행"을 누르고 있다. 활성 `hold_s` 세션의 만료를 `hold_s` 만큼 미룬다. 세션이 없으면 409 `LINE_FOLLOW_NOT_HELD` (v1.63) |
| POST | `/api/v1/line-follow/stuck/decision` | Operator | D-407 §2 — `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT}`. 열린 막힘(`GET /line-follow` 의 `stuck`)에 대한 관제 답. `WAIT` 그대로 HOLD·로컬 복구 안 함; `RESUME` 앞물체 정지를 한 번 풀어 `obstacle_stop_m` 까지 접근 허용·LOST 해제 후 차선 추종 재개; `BACK_AND_RETRY` 짧은 후진과 재판단을 즉시(로컬 복구가 켜져 있어야 함); `MANUAL` 차선 추종 OFF + MANUAL(D-342 한도); `ABORT` 차선 추종 OFF + IDLE. 응답은 line-follow 상태 + `outcome`(`hold\|back\|resume\|manual\|idle`). `RESUME`·`BACK_AND_RETRY`·`MANUAL` 은 보정 lease 를, `RESUME`·`BACK_AND_RETRY` 는 E-Stop 을 지킨다. `MANUAL`·`ABORT` 의 모드 전이는 `POST /mode` 와 같다(`MANUAL` 은 navigation·swarm 취소, `mode.changed`). 409 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`·`CALIBRATION_ACTIVE`·`EMERGENCY_ACTIVE` (v1.74) |
| GET | `/api/v1/traffic` | Viewer | D-151 — 교통 인식 증거, 정책 판정, active/staged 설정과 simulation signal capability readback |
| POST | `/api/v1/traffic/policy/stage` | Operator | D-151 — 정책 모드·revision·거리·dwell·신뢰도 기준을 검증해 검토본으로 저장. 활성 정책은 바꾸지 않음 |
| POST | `/api/v1/traffic/policy/apply` | Operator | D-151 — IDLE/EMERGENCY이고 line-follow가 꺼져 있으며, fresh 0 속도 또는 E-stop으로 정지가 증명된 경우에만 staged 정책을 원자 적용 |
| PUT | `/api/v1/traffic/simulation/signal` | Operator | D-151 — 명시적 simulation capability에서만 `{colour: RED\|YELLOW\|GREEN}` 허용. 실제 장치에서는 501 |
| GET | `/api/v1/vision/front/status` | Viewer | 최신 front camera preview의 available/stale, source, frame, 크기, overlay, sequence 메타데이터. 원본 영상은 상태 WebSocket에 싣지 않음 |
| GET | `/api/v1/vision/front/frame` | Viewer | D-152 fresh 최신 JPEG 한 장. `Cache-Control: no-store`, `Content-Encoding: identity`; 없거나 stale이면 404 `CAMERA_FRAME_UNAVAILABLE` |
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
| GET | `/api/v1/safety/state` | Viewer | SAF-001 |
| PUT | `/api/v1/safety/limits` | Admin | SAF-004 — `{manual_linear?, manual_angular?}` 는 프로필 최대값으로 clamp. SAF-005 배터리 임계값 `{battery_warning_percent?, battery_critical_percent?, battery_deep_percent?, battery_critical_policy?}` 과 `{fleet_loss_policy?}` 도 같은 경로로 받는다. 임계값은 `0 < deep < critical < warning <= 100` 을 만족해야 한다 |

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
| POST | `/api/v1/host/hardware/confirm` | Admin | D-247 6 (v1.23, payload: `{device: "buzzer"\|"lamp", observed: bool}`, 엄격한 bool) — 사람의 답을 `{observed, by(토큰 id), label, at}`로 CORE 상태 디렉터리 `~/.rosy/hw-confirmations.json`(0600, 원자적 교체)에 기록한다. `rosy-hw-test`의 마지막 결과가 같은 장치·`state:"done"`·5분 안에 끝난 것이어야 하며, 아니면 409 `HW_CONFIRM_NO_TEST`. 기록에는 그 시험의 `request_id`가 함께 남는다(파일에만, 응답·카드에는 싣지 않음). 장치마다 마지막 답 하나. 200 `{recorded:true, device, observed, by, label, at}`. 쓰지 못하면 503 `HW_CONFIRM_UNAVAILABLE` |

---

## 5.9 OMX-AI Gazebo Pilot 전용 API (D-390, v1.70)

오류는 ERR-101의 `{error:{code,message,detail}}` 형식이다. 스키마 오류는 400 `VALIDATION_ERROR`, 인증 없음은 401 `UNAUTHORIZED`, 조종권·상태 충돌은 409 `MODE_CONFLICT`로 돌려준다.

이 경계는 격리된 개발용 Gazebo 컨테이너에서만 제공한다. CORE/Fleet 토큰, 실물 OMX profile, Fleet Action UDS 권한과 분리된다. `/pilot` 정적 화면과 아래 API는 같은 origin이다. 브라우저 명령은 단일 `ArmCommandOwner`를 거쳐 `/arm_controller/follow_joint_trajectory`로 간다.

| Method | 경로 | 요청/응답 |
|---|---|---|
| GET | `/api/v1/sim/omx/target` | 공개 `{kind:"omx_sim",simulation:true,instance_id,joints,gripper,camera,recording}`; Pinky CORE에서는 404 |
| POST | `/api/v1/sim/omx/pair` | 로컬 콘솔의 10분 유효 일회용 `{code}` → `{token}`; 성공 201, 재사용 403 |
| GET | `/api/v1/sim/omx/whoami` | Bearer → `{role:"operator"}` |
| POST/PUT/DELETE | `/api/v1/sim/omx/seat[/{seat_id}]` | 단일 조종권 취득·1초 간격 갱신·반납. lease 10초; 만료/반납 시 진행 목표 취소 요청. 취소 ACK는 정지 증거가 아니다 |
| GET | `/api/v1/sim/omx/state` | `{instance_id,ready,owner_state,owner_reason,action_server_ready,state_sequence,joint_age_ms,positions,active_goal}`. 신선한 관절 상태와 action server가 없으면 `ready:false` |
| POST | `/api/v1/sim/omx/goals` | `OmxSimJog` → `OmxSimGoal`, 202. 같은 `request_id`·동일 payload는 멱등; 다른 payload는 409 |
| GET | `/api/v1/sim/omx/goals/{command_id}` | 비동기 goal readback. 미등록 404 |
| POST | `/api/v1/sim/omx/goals/{command_id}/cancel?seat_id=...` | 취소 요청. `CANCEL_REQUESTED`는 정지 완료가 아니다 |

`OmxSimJog` 필수 필드: `instance_id`, `seat_id`, `request_id`, `joint`, `delta_rad`(0이 아니며 절댓값 ≤0.05 rad), `duration_s`(0.1~1.0), `state_sequence`, `expires_at_ms`. 명령은 현재 관절 상태에서 해당 관절만 상대 이동하며 모든 관절의 현재 값을 함께 보낸다. 최근 5초 안에 Pilot API가 제공하지 않은 sequence, 6초보다 먼 만료 시각, 이미 만료된 요청, 범위 초과, 진행 중 goal, HOLD는 거부한다. ROS는 새 sequence를 계속 발행하므로 제출 시점에는 가장 최근의 신선한 관절 상태를 사용한다. `OmxSimGoal.state`는 `LOCAL_ACCEPTED`, `ROS_ACCEPTED`, `RUNNING`, `SUCCEEDED`, `REJECTED`, `CANCEL_REQUESTED`, `CANCELED`, `UNKNOWN_HOLD` 중 하나다. `LOCAL_ACCEPTED`는 ROS 수락이 아니고, action의 `SUCCEEDED`는 물리적 정지나 목표 도달의 독립 증거가 아니다. schema 정본은 `core_common.protocol.omx_sim`이다.

v1.70 추가 경로(모두 Bearer 인증):

| Method | 경로 (`/api/v1/sim/omx` 아래) | 요청/응답 |
|---|---|---|
| GET | `/camera` | `{available,fresh,capture_time_ns,sim_time_ns,age_ms,camera_identity,width,height}` |
| GET | `/camera/frame` | 신선한 RGB 프레임의 JPEG, `Cache-Control:no-store`; 결측/오래됨 409 |
| GET | `/recordings` | `OmxSimRecording`: `{status,episode_id,task,task_outcome,frame_count,issues}` |
| POST | `/recordings` | 소유 조종권 `{seat_id,task}` → 기록 상태, 201; 신선한 영상/관절/명령 소유자 필요 |
| POST | `/recordings/{episode_id}/stop` | 소유 조종권 `{seat_id,outcome:success\|failure\|unspecified}` → 기록 상태 |
| GET | `/recordings/{episode_id}/manifest` | 원본 manifest; 미등록/잘못된 UUID 404; 서버 파일 경로 없음 |

기록은 10 simulation FPS 영상과 그 시각 이전 50 ms 이내의 관절 상태, ROS 수락 UUID가 있는 절대 목표(rad)를 묶는다. 영상 신선도 2초와 현재 관절 스트림 신선도 0.5초는 별도다. 지연 영상은 과거 상태와 pair하며 미래 상태를 사용하지 않는다. 프레임 누락/시계 역행/취소/HOLD/조종권 반납·만료/서버 종료/미선택 결과는 `incomplete`이며 export를 거부한다. `success`는 운용자가 지정한 과제 결과이며 Action 성공과 구분한다. 기록은 최대 3000프레임, 저장 위치는 서버 설정으로만 지정한다. LeRobot 0.4.4 오프라인 변환은 `omx_sim_ros`/rad를 유지하고, 영상 시간축은 index/fps, 실제 Gazebo 시각은 int64 source 필드와 원본 해시로 보존한다. 업로드·학습·정책 실행 API는 없다. 실물 OMX 명령을 이 경로로 보내거나 `omx.disabled.yaml`을 켜서는 안 된다.

## 5.10 Pilot 로봇 녹화 (D-411, v1.83)

녹화 주체는 카메라 유닛(`rosy-camera`)의 `pilot_recorder_node` 다. CORE 는 `std_srvs/SetBool` `pilot_recorder/set_active` 로 시작·정지를 **요청**만 하고, 래치된 `pilot_recorder/status`(`rosy.pilot.recording.status/1`, 1 Hz)를 받아 판단한다. 녹화는 증거일 뿐이며 제어 경로는 이 토픽들을 읽지 않는다(D-2). 스키마 정본은 `core_common.protocol.recording` 이다.

| Method | 경로 | 권한 | 요청/응답 |
|---|---|---|---|
| GET | `/api/v1/recordings` | Viewer | `{active, items[RecordingSummary], download_allowed, download_blocker}` — `active` 는 녹화기 상태(낡았으면 `null`), `items` 는 최신순 `{id, started_at, ended_at, duration_s, bytes, topics, status: recording\|complete\|incomplete, manifest_sha256, fetched}`, `download_blocker` 는 `RECORDING_BUSY`·`ROBOT_MOVING`·`null` |
| GET | `/api/v1/recordings/active` | Viewer | `{active, owned}` — `owned` 는 호출 토큰이 시작한 녹화인가 |
| POST | `/api/v1/recordings` | Operator | 201 `RecorderStatus`(대개 `starting`, 아래). 거부: 409 `RECORDING_BUSY`, 507 `RECORDING_QUOTA_FULL`·`RECORDING_DISK_FULL`, 503 `RECORDER_UNAVAILABLE` |
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

`teleop/intent`(ROS `std_msgs/String` JSON, `rosy.teleop.intent/1`)는 CORE 가 teleop 판정마다 낸다 — 관리자 앞 거부(capability·보정 lease·keep)도 포함. 싱크 실패는 명령을 거부하지 않는다.

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
HOLD | LOST | RECOVERING`(v1.74, D-407 후진 중에만) 이며 `LOST` 는 모드를 `OFF` 로 바꾼 뒤 다시 선택하기 전까지
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
  "sequence": 7
}
```

CORE-only 런타임(`runtime_mode: core`, D-161)에서 한 번도 값이 오지 않은 채널은 출처가 구성되지 않은 것이므로 `unavailable` 이다 — `disconnected` 는 출처가 있는데 값이 오지 않는 경우에만 쓴다. 첫 표본이 오면 보통 판정으로 돌아간다(v1.18).

`evidence` 는 v1.8 additive 다. 채널별 `{received_at, evidence, stale_after_s}` 이며, `evidence` 는 서버가 판정한 `fresh` | `delayed` | `disconnected` | `unavailable` 이다. 판정에 쓴 임계값(`stale_after_s`)도 같이 실는다. 클라이언트는 임계값을 다시 계산하지 않고 이 문자열을 그대로 표시·게이트한다. 알 수 없는 채널 키는 무시한다(API-002). `PROTOCOL_VERSION`(envelope 1.0)은 바꾸지 않는다.

Camera preview transfer rules (v1.12, D-152):

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
- 접속 단절 시 SAF-003 정책 적용

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
| `nav.line_obstacle_hold` | warning | 로봇 | `{mode, clearance_m, held_s}` — D-344 §11 앞 물체 정지(`obstacle_ahead`)가 `line_follow.obstacle_escalate_s` 넘게 이어짐, 정지 한 번에 한 번 (feat/device-prep, v1.64) |
| `nav.line_stuck_opened` | warning | 로봇 | `{stuck_id, cause, front_clearance_m, rear_clearance_m, rear_state, turn_clearance_m, rear_blind_m, last_lane, preview_seq, restuck_of, attempts}` — D-407 §1 막힘 열림: `cause` 는 `obstacle_ahead`(앞물체 정지가 `obstacle_escalate_s` 이상) 또는 `lane_lost`. 여유는 로봇별 self-mask 적용, 앞은 LiDAR 기준 경로 띠, 뒤는 URDF 몸 뒤끝 기준, 회전은 회전 반경 밖; `rear_blind_m` 은 LiDAR `range_min` 때문에 안 보이는 뒤 거리. 같은 막힘에 한 번 (v1.74) |
| `nav.line_stuck_asked` | info | 로봇 | `{stuck_id, cause, console_linked, local_fallback_s, attempts, reason, decisions}` — D-407 §2·§3 관제 판단 요청(FleetAgent 가 중계). `local_fallback_s` 가 null 이면 로컬 복구로 넘어가지 않고 관제 답만 기다린다(`reason`: `opened`·`console_wait`·`local_disabled`·`local_refused`·`local_aborted`·`attempts_exhausted`) (v1.74) |
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

> **상태 (v1.16): 미구현.** 이 카탈로그 전체(포트 8081, 페어링 토큰 발급, 명령
> 추적, 미션)는 중앙 Fleet 서버가 착수할 때 구현된다. 현재 존재하는 것은 사이트
> 시드(`fleet console`)로, **`:8090`의 `/api/fleet/*`**(경로도 다르다 — 사이트
> 것과 로봇 계약을 섞지 않으려는 의도)와 SiteHub gather/scatter 뿐이다. 로봇↔
> 시드 콘솔 사이의 실제 프로토콜은 §5~§7 을 따른다.

사이트 시드의 추가 경로는 §10.6에 기록한다. 이 API는 로봇 `/api/v1/*`와 다른
listener·자격 증명이며 중앙 Fleet catalog의 구현 상태로 간주하지 않는다.

## 10.1 로봇·페어링

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
| GET | `/api/fleet/site-map` | console Bearer token 또는 viewer 이상 | 설정된 `corner_world_m` 사각형을 `map_id`별로 묶어 반환(`frame: map`, m 단위 `polygon_m`·`bounds_m`, source별 `source_id`·`calibration_revision`·`corner_marker_ids`·`robot_ids`·`robot_markers`). 토큰은 싣지 않는다. 설정·기하가 없으면 404 `NO_SITE_MAP`. 표시 전용 |

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
| GET | `/api/fleet/vision/sources` | Site console Bearer token | Configured preview source IDs |
| POST | `/api/fleet/vision/lease` | Viewer Bearer token | 60 s source-scoped lease and direct Vision frame path |
| GET | `/api/vision/sources/{source_id}/frame` | Vision preview lease Bearer token | One latest fresh JPEG; `Cache-Control: no-store`; `X-Frame-Seq`, `X-Frame-Age-Ms`, `X-Frame-Captured-At`, `X-Frame-Width`, `X-Frame-Height`, `X-Frame-Rotation-Deg`, and `X-Frame-Rectified` describe that exact frame |
| GET | `/api/vision/sources/{source_id}/field-proposal` | Vision preview lease Bearer token | D-360 field-corner proposal JSON for operator review (`proposal` null when no full field is visible); own 1/s bucket per lease subject; detection runs at most once per source per second, off the event loop (readers in between get the last result, 429 while the first run is busy); `no-store`, same freshness 404s, 422 on undecodable frame. Display only, never applied to sightings |

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

When durable task storage is configured, the operator navigation route creates a
persistent task before contacting CORE. The browser sends a fresh
`Idempotency-Key`; repeating the same request with the same authenticated
operator identity returns the original task without issuing another robot
command. Reusing a key for a different request returns `409 IDEMPOTENCY_CONFLICT`.

| Method | Path | Credential | Requirement |
|---|---|---|---|
| GET | `/api/fleet/session` | any configured site-user bearer | Returns only the authenticated `principal_id` and role for the current console session. |
| POST | `/api/fleet/robots/{robot_id}/goal` | `operator` bearer + `Idempotency-Key` | Validates the configured robot and finite goal, durably accepts the task as `QUEUED`, then lets the dispatcher request a CORE goal. |
| POST | `/api/fleet/do` (when `do` is `navigate`) | `operator` bearer + `Idempotency-Key` | Uses the same task service; each navigation step gets a deterministic child key from the request key and step position. |
| GET | `/api/fleet/tasks/{task_id}` | any configured user bearer | Returns the durable task projection and append-only status history. |
| POST | `/api/fleet/tasks/{task_id}/cancel` | `operator` bearer | Cancels a task only while it is still queued; it does not cancel a goal already dispatched to CORE. |
| POST | `/api/fleet/cancel-all` | `operator` bearer | D-421 (v1.81): non-latching site-wide driving cancel. In order: queued tasks of every robot become `CANCELED` with reason `FLEET_CANCEL_ALL` and the operator as actor (dispatch latch and generation unchanged); an open formation is stopped; then per robot, concurrently, `POST /api/v1/swarm/cancel`, `POST /api/v1/navigation/cancel`, `PUT /api/v1/line-follow/mode {mode: OFF}`, each attempted even when an earlier one failed. It never calls `safety/stop`/`safety/release`, `/mode`, signals or OMX stop. Each request writes a durable record in the task journal database (`fleet_cancel_all`: id, principal, opened/closed times, robot ids, canceled queued task ids, robots whose navigation cancel was answered; closed records older than 30 days are pruned when a window opens) and tags the in-flight dispatch attempts of those robots by `(task_id, attempt_id)` (`ACCEPTED`, `RUNNING`, mid-dispatch `QUEUED`, and `UNKNOWN` changed since the window opened or not already canceled). Dispatched tasks are not rewritten by Fleet: a correlated CORE `nav.canceled` (evidence that a cancel was issued, not of standstill, D-298) moves a tagged task to `HOLD` with reason `FLEET_CANCEL_ALL`, which releases its robot claim, so in-flight robots become dispatchable once CORE confirms the cancel. The event must match the tagged attempt, its `data.source` (when present) must be `api:*`, and the window must be open, or closed at most 30 s ago with that robot's navigation cancel answered or a fence re-cancel; other later cancels stay `UNKNOWN`. A dispatch started inside the window is tagged before its CORE goal call, and tagging settles an attempt whose `nav.canceled` already arrived during the window. Correlated events and dispatch receipts arriving after `HOLD(FLEET_CANCEL_ALL)` are logged, not applied. If the record cannot be written the fanout continues and the response carries `record_error: "CANCEL_ALL_RECORD_UNAVAILABLE"`; without that event the task stays as it was (`ACCEPTED`/`UNKNOWN`), the robot stays claimed and the task needs reconciliation (no operator reconcile route exists yet). An untagged `nav.canceled` still yields `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`. `tasks.awaiting_core_result` lists per robot the `ACCEPTED`/`RUNNING` tasks plus `UNKNOWN` tasks changed since the window opened. A dispatcher CORE goal call that overlaps the request (including a task submitted and dispatched inside the window) is inspected when it ends: an explicit CORE reject stays `FAILED`/`COMMAND_REJECTED`; a dispatch left in Fleet's own traffic queue with no live CORE goal becomes `CANCELED`/`FLEET_CANCEL_ALL`; otherwise the task is tagged, Fleet sends `navigation/cancel` to the robot and to any robot it sent to a bay for it, and the task becomes `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH` (no retry); a goal call that raised is re-canceled the same way and keeps its existing classification. 200 even on partial failure: `{cancel_all_id, record_error, cancelled, total, evidence: "CORE_REPLY_ONLY", robots[{robot_id, result: cancelled\|failed\|unreachable, steps{swarm, navigation, line_follow: {ok, error?{reachable, sent?, code, message}}}, tasks{awaiting_core_result[]}}], formation{stopped, state, error?}, tasks{canceled[], error}}`; `sent: false` marks a step Fleet's D-361 address gate refused locally (`ADDRESS_UNVERIFIED`; `line-follow/mode` is not a stop path because a path-level gate would also allow turning it on). `cancelled` = all three CORE calls replied 2xx; `unreachable` = no call got a reply; otherwise `failed`. A reply is not physical stop evidence (D-298). Repeating the request is safe. Normal audit gate applies (`503 AUDIT_STORAGE_UNAVAILABLE`); the D-330 audit exception stays with `/api/fleet/estop`. |
| GET | `/api/fleet/line-stuck` | any configured user bearer | D-407 (v1.77): returns the board as of the last `GET /api/fleet/state` gather (it does not contact the robots) as `{pending[], answers[], observed_age_s}`; `observed_age_s` is null before the first gather. `pending` has one row per robot whose CORE `line_follow.stuck` is open: the CORE `LineStuckStatus` fields plus `robot_id`, `front_clearance_m`, `rear_clearance_m`, `turn_clearance_m`, `rear_blind_m`, `preview_seq` (from the `nav.line_stuck_opened` FleetAgent event, `null` when not received; `opened_event` says which), `robot_online` (false = last value kept while the robot is unreachable), `observed_age_s` and `fleet_answer` (the last forwarded answer for this stuck id). `answers` is the recent forwarded-answer record `{robot_id, stuck_id, decision, principal_id, accepted, outcome, code, message, audit_id, at}` (`accepted` null = outcome unknown). The same row appears as `line_stuck` on each robot of `GET /api/fleet/state`. |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/decision` | `operator` bearer | D-407 (v1.77): `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT}`; `stuck_id` 1-64 chars of `[A-Za-z0-9_.:-]` (CORE ids are `stuck-<12 hex>`), extra fields 422. Forwarded unchanged to that robot's `POST /api/v1/line-follow/stuck/decision` with the robot credential; Fleet never refuses on CORE's behalf. 200 `{robot_id, actor_id, answer, result}` (`result` is CORE's body incl. `outcome`). A CORE 409 (`STUCK_ID_MISMATCH`, `STUCK_DECISION_REFUSED` with its reason, `EMERGENCY_ACTIVE`, `CALIBRATION_ACTIVE`) is returned as 409 `{code, message, robot_id, robot_status}` with CORE's code and message verbatim; other robot error statuses are 502 with the same body, unknown robot 404. A transport failure is 502 `{code, message, robot_id, transport}`: `ROBOT_UNREACHABLE` when the connection was never made (not delivered), `STUCK_DECISION_OUTCOME_UNKNOWN` on a timeout or a dropped reply (CORE may have applied the answer; re-read the stuck before answering again). Every forwarded answer is recorded with the site principal in memory and, with durable task storage, in the `fleet_line_stuck_answers` table of the Fleet journal database, keyed by the API audit `request_id` (§10.10). |

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

# 11. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
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
