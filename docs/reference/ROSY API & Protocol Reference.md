# ROSY API & Protocol Reference
## 공유 인터페이스 계약서

**Document ID:** ROSY-API-REF-001
**Version:** v1.19
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
| `MAP_MISMATCH` | 409 | Goal의 map_id 불일치 (MAP-002) | 로봇 |
| `MAPPING_ACTIVE` | 409 | 매핑 세션 중 명령 거부 (NAV-005) | 로봇 |
| `DOCKING_ACTIVE` | 409 | 도킹/언도킹이 주행을 쥐고 있다 (DNC-003, §8.1 DOCKING > NAVIGATION) | 로봇 |
| `ROBOT_OFFLINE` | 503 | 대상 로봇 미접속 | Fleet |
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
| GET | `/api/v1/system/capabilities` | Viewer | CAP-001. 지킬 수 있는 것만 광고한다(D-32) — §9.1 `withheld` |
| GET | `/api/v1/system/runtime` | Viewer | ROS-102 — 호스트 OS/CPU/RAM/디스크/온도 + 읽기 전용 ROS 그래프 스냅샷 |
| GET | `/api/v1/system/tokens` | Admin | SEC-101 — `{id, role, label, created_at, legacy, expires_at, source, current, last_used_at}`. `current` 는 호출자 자신의 토큰, `last_used_at` 은 CORE 가 켜진 뒤 마지막 인증 시각(메모리, 없으면 null). 만료된 토큰은 빠진다. 토큰에서 유도된 값은 싣지 않는다 |
| POST | `/api/v1/system/tokens` | Admin | SEC-101 (payload: `{role, label?, token?}`) — `token` 을 비우면 서버가 생성해 응답에 **단 한 번** 싣는다. 직접 정하면 16자 이상. 응답은 `Cache-Control: no-store`. 만료가 있는 호출자(페어링 세션)는 403 — 만료 없는 토큰을 만들 수 없다(D-193 보안 리뷰) |
| DELETE | `/api/v1/system/tokens/{id}` | Admin | SEC-101 — 호출자 자신의 토큰(400)과 만료 없는 마지막 administrator(409) 는 거부. 만료가 있는 administrator 는 세지 않는다(D-193). 만료가 있는 호출자가 만료 없는 administrator 를 지우려 하면 403 |
| PATCH | `/api/v1/system/tokens/{id}` | Admin | SEC-101 (payload: `{label}`, 64자 이하) — 이름표만 바꾼다. 응답은 목록 항목 한 개. 없거나 만료된 id 는 404 (v1.19) |
| POST | `/api/v1/auth/pair` | 없음 | D-193 (payload: `{code, label?}`, 본문 1 KiB 이하, 넘으면 413) — 로그인 코드 `ABCD-EFGH`(하이픈·대소문자 무시) → `201 {id, token, role, label, source, expires_at}`, `Cache-Control: no-store`. 원문 토큰은 이때 한 번만 싣는다. 출발지는 RFC 1918·루프백만(그 밖 403), IP 마다 60 s 5회·전체 60 s 30회(넘으면 429 + `Retry-After`). 형식이 아닌 코드는 400, 틀리거나 만료·사용된 코드와 발급된 코드가 없는 경우는 모두 같은 401 이다. 한 코드에 틀린 시도가 5회 쌓이면 코드를 폐기하고, 그 5번째 요청의 401 만 `error.detail = {"burned": true}` 를 싣는다(대시보드가 새 코드를 받으라고 안내한다) 토큰 수명은 `auth.pairing.token_lifetime_hours`(기본 operator·viewer 168 h, administrator 24 h) — 만료 없는 토큰은 나오지 않는다 |
| GET | `/api/v1/auth/whoami` | Viewer | D-193 — `{id, role, label, source, created_at, expires_at}`. 대시보드가 역할을 추측하지 않고 묻는다 |
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
| POST | `/api/v1/navigation/goal` | Operator | NAV-001 (payload: `{x,y,yaw}` 또는 `{waypoint}`) |
| POST | `/api/v1/navigation/cancel` | Operator | NAV-002 |
| POST | `/api/v1/navigation/home` | Operator | NAV-003 |
| GET | `/api/v1/navigation/state` | Viewer | NAV-004 |
| GET | `/api/v1/navigation/path` | Viewer | MAP-003 |
| GET | `/api/v1/line-follow` | Viewer | D-143 — 선택 모드, 상태, 증거 신뢰도·나이, 최종 선속도·각속도와 사유 |
| PUT | `/api/v1/line-follow/mode` | Operator | D-143 — `{mode: OFF\|IR_LINE\|CAMERA_LINE}`. 소스는 상호 배타적이며 변경 즉시 이전 증거와 명령을 폐기 |
| GET | `/api/v1/traffic` | Viewer | D-151 — 교통 인식 증거, 정책 판정, active/staged 설정과 simulation signal capability readback |
| POST | `/api/v1/traffic/policy/stage` | Operator | D-151 — 정책 모드·revision·거리·dwell·신뢰도 기준을 검증해 검토본으로 저장. 활성 정책은 바꾸지 않음 |
| POST | `/api/v1/traffic/policy/apply` | Operator | D-151 — IDLE/EMERGENCY이고 line-follow가 꺼져 있으며, fresh 0 속도 또는 E-stop으로 정지가 증명된 경우에만 staged 정책을 원자 적용 |
| PUT | `/api/v1/traffic/simulation/signal` | Operator | D-151 — 명시적 simulation capability에서만 `{colour: RED\|YELLOW\|GREEN}` 허용. 실제 장치에서는 501 |
| GET | `/api/v1/vision/front/status` | Viewer | 최신 front camera preview의 available/stale, source, frame, 크기, overlay, sequence 메타데이터. 원본 영상은 상태 WebSocket에 싣지 않음 |
| GET | `/api/v1/vision/front/frame` | Viewer | D-152 fresh 최신 JPEG 한 장. `Cache-Control: no-store`, `Content-Encoding: identity`; 없거나 stale이면 404 `CAMERA_FRAME_UNAVAILABLE` |
| POST | `/api/v1/localization/initialpose` | Operator | AMCL 초기화 |
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
| POST | `/api/v1/teleop` | Operator | §11 |
| POST | `/api/v1/mode` | Operator | `{mode: MANUAL\|NAVIGATION\|IDLE}` |
| POST | `/api/v1/swarm/follow` | Operator | SWM-002 `{target_robot_id, distance, lateral, max_speed, stream_timeout_ms, source}`. `source: fleet(기본)\|peer(예약, D-21 — 요청하면 501)`. `max_speed` 는 SAF-004 상한을 넘으면 400 이고, 추종 구간 동안 실제 상한으로 적용된다 — Nav2 가 무엇을 내보내든 `cmd_vel` 은 이 값으로 클리핑된다(D-31). 적용 중인 값은 `GET /safety/state` 의 `limits.session_linear` 에 보인다. 미지원 로봇은 501 `CAPABILITY_NOT_SUPPORTED` (SWM-005/CAP-003), 도킹/언도킹 중에는 409 `DOCKING_ACTIVE`, 맵핑 세션 중에는 409 `MAPPING_ACTIVE`, E-Stop 중에는 409 `EMERGENCY_ACTIVE`. 추종 중 `POST /navigation/cancel` 이나 MANUAL 전환은 대형을 끝내고 `swarm.aborted` 를 낸다 |
| POST | `/api/v1/swarm/cancel` | Operator | SWM-002 |
| GET | `/api/v1/swarm/state` | Viewer | SWM-006 — `{role, formation, active, holding, target_robot_id, source, max_speed, map_mismatch, stream_age_s}`. `map_mismatch` 는 거부 중인 리더의 `map_id` 다. 상태 스냅샷의 `swarm` 필드는 그중 `role`·`formation`·`active` 다 |
| POST | `/api/v1/safety/stop` | Viewer↑ | SAF-001 (누구나) |
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
| POST | `/api/v1/docking/dock` | Operator | DNC-003 (미지원 시 501). body: `{"dock": "dock_1"}` — 도크가 1개면 생략 가능 |
| POST | `/api/v1/docking/undock` | Operator | DNC-003 |
| POST | `/api/v1/docking/cancel` | Operator | DNC-003 |
| GET | `/api/v1/docking/status` | Viewer | DNC-003 — **capability 무관 항상 200**, `supported` 포함 |
| GET | `/api/v1/docking/docks` | Viewer | DNC-005 |
| POST | `/api/v1/docking/types` | Admin | DNC-005 도크 기종 등록 |
| POST | `/api/v1/docking/docks` | Admin | DNC-005 도크 개체 등록 |
| DELETE | `/api/v1/docking/docks/{id}` | Admin | DNC-005 |
| POST | `/api/v1/docking/docks/{id}/teach` | Operator | DNC-005 teach-by-docking |

## 5.7 Host (Host Agent 릴레이)

CORE 는 이 경로들을 처리하지 않고 unix 소켓으로 Host Agent 에 넘긴다(`docs/reference/rosy-host-agent-contract.md`). 에이전트가 없으면 503 과 사유를 돌려준다.
파괴적 명령은 `{confirmed: true}` 와 `idempotency_key` 를 받는다.

| Method | Path | Role | 요구사항 |
|---|---|---|---|
| GET | `/api/v1/host/network` | Viewer | NET-001 — 현재 모드와 도달성. SSID 는 싣되 PSK 는 절대 싣지 않는다 |
| POST | `/api/v1/host/network/apply` | Admin | NET-001 (payload: `{profile_id, confirmed, idempotency_key?}`) — 등록된 NetworkManager 프로파일로 전환. PSK 는 호스트에 남고 CORE 에 들어오지 않는다 |
| GET | `/api/v1/host/release` | Viewer | OPS — current/previous/staged 와 마지막 실패 사유 |
| POST | `/api/v1/host/release/install` | Admin | OPS — 서명 검증된 릴리스 설치 |
| POST | `/api/v1/host/release/rollback` | Admin | OPS — previous 로 복귀 |
| POST | `/api/v1/host/release/clear-hold` | Admin | OPS — RECOVERY HOLD 해제 |
| GET | `/api/v1/host/commissioning` | Viewer | HWA-001 — runtime mode 와 hardware 재승인 사유 |

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
    "evidence_revision": 42,
    "age_s": 0.04,
    "stop_line_visible": true,
    "stop_line_distance_m": 0.08,
    "crosswalk_visible": true,
    "signal_colour": "RED",
    "signal_confidence": 0.93,
    "signal_conflict": false,
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

`line_follow` 는 v1.10 additive 다. `state` 는 `OFF | WAITING | TRACKING |
HOLD | LOST` 이며 `LOST` 는 모드를 `OFF` 로 바꾼 뒤 다시 선택하기 전까지
해제되지 않는다. 선택되지 않은 소스, 신뢰도 미달, 원본 센서 시각 기준 stale,
형식 오류는 모두 선속도·각속도 0으로 fail-closed 된다. `linear` 는 이 모드의
별도 상한 0.10 m/s를 넘지 않는다(D-143).

`traffic_policy` 는 v1.11 additive 다. `mode` 는 `DISABLED |
MONITOR_ONLY | ENFORCED`, `state` 는 `DISABLED | FOLLOW | APPROACH |
STOP_REQUIRED | WAIT_SIGNAL | PROCEED | HOLD` 다. `ENFORCED`에서는 stale,
신호 충돌, map/scene revision 불일치, 거리 미확정이 모두 0 명령을 만든다.
정지선에서는 신호색과 무관하게 먼저 완전 정지와 dwell을 완료한 뒤, 신뢰도
기준을 통과한 `GREEN`만 `PROCEED`를 허용한다. `MONITOR_ONLY`는 같은 판정을
표시하지만 주행 후보를 변경하지 않는다.

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

Fleet 타임아웃(기본 10초) 내 ack 없으면 `COMMAND_TIMEOUT`.

> **상태 (v1.15, ADR D-170)**: 위 추적 흐름의 **로봇 측 구현**(ack 송신,
> `correlation_id` 설정·소비, `AckPayload`의 `TIMEOUT`·`issued_by`·
> `ts_issued/ts_final` 필드)은 중앙 Fleet 서버 착수와 함께 제공된다.
> 그 전까지 `correlation_id`는 계약 전용 필드이며, 명령 추적은 REST
> 요청/응답과 이벤트 `seq`로 대체된다. 로봇 스키마 변경은 없다.

## 7.6 재접속 (로봇 측 의무)

- Exponential backoff: 1s → 2s → 4s → ... 최대 30s
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
| `WS /ws/swarm/pose?token=` | Viewer + capability `swarm.lead` | 로봇 → 밖 | SWM-003 리더 pose 스트림. ≥10 Hz 는 하한이며 설정으로 낮출 수 없다 |
| `WS /ws/swarm/reference?token=` | Operator | 밖 → 로봇 | 팔로워의 참조 pose 입구 (SWM-007). 형식이 어긋난 프레임은 버리고 소켓은 유지한다 |

close code: `4401` 은 토큰이 없거나 틀린 것(`/ws/state` 와 동일), `4403` 은 인증은 됐지만 허용되지 않는 것 — 역할이 모자라거나 capability 가 그 기능을 선언하지 않은 경우(CAP-003)다.

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
| `nav.started` | info | 로봇 | `{goal, by}` — `goal` 은 `{x, y, yaw}` |
| `nav.completed` | info | 로봇 | `{}` — 어떤 목표였는지는 싣지 않는다. `nav.started` 와 짝지으려면 소비자가 순서로 이어야 한다 |
| `nav.failed` | error | 로봇 | `{error_code}` |
| `nav.canceled` | info | 로봇 | `{source}` |
| `nav.stuck` | error | 로봇 | `{timeout_s}` — NAV-006 무진척 판정 시간(초) |
| `nav.lane_lost` | warning | 로봇 | `{mode, reason, lost_after_s}` (NAV-007 차선 상실 — 유예 `lost_after_s` 초과 시 정지, 자동 재탐색 없음) |
| `nav.line_mode_changed` | info | 로봇 | `{from, to}` — D-143 line-follow 모드 선택 |
| `nav.traffic_policy_staged` | info | 로봇 | `{actor, policy_revision}` — D-151 traffic policy 변경 대기 |
| `nav.traffic_policy_applied` | info | 로봇 | `{actor, policy_revision, mode}` — D-151 대기 정책 적용(정지 상태에서만) |
| `nav.traffic_policy_reset` | info | 로봇 | `{reason}` — D-151 정책 상태 초기화(HOLD/DISABLED 로 복귀) |
| `sim.traffic_signal_changed` | info | 로봇 | `{actor, colour}` — 시뮬레이션 신호등 제어가 켜진 프로필에서만 |
| `nav.blocked` | warning | 로봇 | **미구현** — CORE 는 Nav2 액션 피드백을 구독하지 않아 막힘을 알 방법이 없다. 진척이 없는 주행은 NAV-006 이 `nav.stuck` 으로 끝낸다 |
| `safety.estop` | critical | 로봇 | `{source}` |
| `safety.estop_released` | warning | 로봇 | `{by}` |
| `safety.watchdog` | warning | 로봇 | `{timeout_ms}` |
| `battery.low` | warning | 로봇 | `{percent}` |
| `battery.critical` | critical | 로봇 | `{percent, policy}` |
| `battery.deep` | critical | 로봇 | `{percent, voltage, dwell_s}` — D-27 딥 방전. 모터가 서고 셧다운 센티넬이 무장된다 |
| `battery.shutdown_request_failed` | error | 로봇 | `{path, error, armed}` — D-27 셧다운 센티넬을 쓰지 못했다. 딥배터리 보호가 무장되지 않았다는 뜻이므로 조용히 넘어가면 안 된다 |
| `command.rejected` | warning | 로봇 | `{source, reason}` |
| `waypoint.created/updated/deleted` | info | 로봇 | `{name}` |
| `slam.started` | info | 로봇 | `{by, reset}` — `reset` 은 재시작일 때만 (NAV-005) |
| `slam.stopped` | info | 로봇 | `{by}` |
| `power.mode_changed` | info | 로봇 | `{from, to, reason, sample_rate_hz}` (PWR-001) |
| `power.wake` | info | 로봇 | `{reason}` — `proximity\|contact\|api\|battery` (PWR-004) |
| `presence.detected` | info | 로봇 | `{state, range}` (PWR-002) |
| `presence.cleared` | info | 로봇 | `{range}` |
| `power.lidar_changed` | info | 로봇 | `{spinning, reason, spinup_s}` (PWR-005 STANDBY LiDAR 정지) |
| `map.saved` | info | 로봇 | `{map_id}` |
| `localization.initialpose` | info | 로봇 | `{x, y, yaw}` — 운영자가 AMCL 자세를 놓았다. 누가 놓았는지는 envelope 의 `source` 에 있다 |
| `docking.started` | info | 로봇 | `{dock_id}` (DNC-003) |
| `docking.docked` | info | 로봇 | `{dock_id}` |
| `docking.charging` / `docking.charge_lost` | info | 로봇 | `{dock_id}` — 독립된 두 소스로 확인한 충전 상태 (D-28) |
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
| `swarm.aborted` | warning | 로봇 | `{formation, reason, robots, by}` — `reason`: `canceled` \| `estop` \| `docking` \| `stuck` \| `manual` \| `navigation_canceled` |

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

**`withheld` (v1.18 additive, D-32/D-161)**: CORE-only 런타임에서 오도메트리(pose·velocity)가 한 번도 오지
않았으면 하드웨어가 필요한 플래그(`teleop`, `navigation.goal_navigation`, `navigation.return_home`, `slam`,
`swarm.follow`, `swarm.lead`, `docking.supported`)를 `false` 로 내리고, 내린 것과 이유를 싣는다.

```json
"withheld": { "flags": ["teleop", "navigation.goal_navigation", "slam"], "reason": "runtime_mode:core" }
```

같은 동안 `GET /api/v1/system/inventory` 의 descriptor 는 `available: false`, `state: "blocked"`,
`reason: "runtime_mode:core"` 다(`device_state` 차단이 있으면 그 이유가 먼저다). 첫 오도메트리 표본(시뮬 벤치 포함)이
오면 둘 다 프로파일 선언으로 돌아간다. 명령 경로의 CAP-003 게이트는 이 변경으로 바뀌지 않는다.

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

---

# 10. Fleet REST API 카탈로그

Fleet(rosy_fleet)이 제공하는 엔드포인트. Base: `http://<fleet-host>:8081`

> **상태 (v1.16): 미구현.** 이 카탈로그 전체(포트 8081, 페어링 토큰 발급, 명령
> 추적, 미션)는 중앙 Fleet 서버가 착수할 때 구현된다. 현재 존재하는 것은 사이트
> 시드(`fleet console`)로, **`:8090`의 `/api/fleet/*`**(경로도 다르다 — 사이트
> 것과 로봇 계약을 섞지 않으려는 의도)와 SiteHub gather/scatter 뿐이다. 로봇↔
> 시드 콘솔 사이의 실제 프로토콜은 §5~§7 을 따른다.

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

---

# 11. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.19 | 2026-09-24 | Additive(D-193): `auth/pair`·`auth/whoami`·`auth/logout`·`auth/enrollment-codes`, `PATCH system/tokens/{id}`. 토큰 목록에 `expires_at`·`source`·`current`·`last_used_at`, 생성 응답에 `expires_at`·`source`. 이벤트 `auth.paired`·`auth.code_burned`·`auth.enrollment_code_issued`·`auth.credentials_refused`. `whoami` 가 신원의 정본이고 `system/info.caller_role`(v1.18)은 호환용으로 남는다. WebSocket 첫 메시지 인증(`?token=` 은 한 릴리스 동안 유지). S3: `auth/pair` 의 코드를 폐기시킨 401 에 `error.detail.burned`, 대시보드는 첫 메시지 인증만 쓴다. **동작 변경**: 만료된 토큰은 401, 마지막 관리자 규칙은 만료 없는 administrator 만 센다, 장치 기본값에 토큰이 없다(개발 토큰은 `ROSY_DEV_AUTH=1` 일 때만, 장치 모드는 거부) |
| v1.18 | 2026-09-24 | US-010, 실기(rosy-pinky-e4us, CORE-only) 근거. **Corrective**: `battery.percent` 는 값이 없을 때 `null`(≠`0.0`) — 0.0 은 지어낸 치명 경보였다(D-82 Law 0). 형은 `number \| null` 이고 `voltage` 와 같은 규약이다. CORE-only 에서 값이 한 번도 오지 않은 evidence 채널은 `unavailable`(≠`disconnected`). `system/info` 의 `robot_name` 은 이름이 기본값뿐이면 프로비저닝 신원에서 온다(≠`Rosy 01`). **Additive**: `system/info.caller_role`, CAP-001 `withheld` 와 CORE-only 동안 하드웨어 플래그 `false`·descriptor `blocked`(`runtime_mode:core`) (D-32). envelope `protocol_version` 1.0 유지 |
| v1.17 | 2026-09-23 | Additive: `logs/audit` 의 `log` 에 `dir_sync_failures`·`last_dir_sync_error`, `/metrics` 에 `rosy_audit_dir_sync_failures_total`(counter). 정리의 바꿔 끼우기 뒤 디렉터리 fsync 실패를 정리 실패(`prune_failures`)에서 떼어 센다 — 파일은 이미 정리됐다 |
| v1.16 | 2026-09-22 | 상태 표기·계약 명확화: §10 Fleet REST 카탈로그에 **미구현** 표기(시드는 :8090 `/api/fleet/*`), §1 `Deprecation`/`Sunset` 헤더 구현 시점 명시, §2 AUTH-103 CORS 미제공 제약, §4 enum 대소문자 표. 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.15 | 2026-09-22 | 상태 표기 정정: §7.5 PRT-004 로봇 측 구현(correlation_id 소비·AckPayload 확장)을 중앙 Fleet 서버 착수 조건부로 명시 (ADR D-170). 스키마 변경 없음 — envelope `protocol_version` 1.0 유지 |
| v1.14 | 2026-09-22 | Additive: `logs/audit` 응답에 `log` (기록 상태 — `writable`·`write_failures`·`write_failures_total`·`prune_failures`·`prune_skipped`·`serialize_failures`·`last_write_error`·`last_prune_error`·`last_skip_reason`·`last_serialize_error`), `/metrics` 에 `rosy_audit_write_failures_consecutive`(gauge)·`rosy_audit_write_failures_total`·`rosy_audit_prune_failures_total`·`rosy_audit_prune_skipped_total`·`rosy_audit_serialize_failures_total`(counter). 감사 기록 실패는 EventBus 가 삼켜 어디에도 남지 않았다. 조회는 이제 파일을 재작성하지 않고 메모리에서 걸러 답한다 — 보존 약속(30 일)은 그대로고, 이벤트 목록의 모양도 그대로다 |
| v1.13 | 2026-09-22 | Corrective + Additive. **Corrective**: 이벤트 카탈로그(§8)가 실제 발행과 갈라져 있던 것을 맞춤. payload 키명 — `nav.stuck` 은 `timeout_s`(≠`timeout_ms`), `mode.changed` 는 `by`(≠`source`), `nav.started` 는 `{goal, by}`(≠`{goal\|waypoint}`), `nav.completed`·`system.shutdown` 은 payload 없음(≠기존 표기), `nav.lane_lost` 는 `{mode, reason, lost_after_s}`(≠`{lost_ms}`), `slam.*`·`presence.*` 는 이벤트별로 다름. 심각도 — 문서를 고친 것: `nav.lane_lost` 는 warning(≠error). 코드를 고친 것: `config.changed`·`swarm.aborted` 는 문서대로 warning 을 실제로 싣는다(≠기본값 info). 문서를 그대로 읽은 소비자는 이 목록만큼 이미 깨져 있었다. **Additive**: 구현돼 있지만 적혀 있지 않던 `docking.*` 11 종, `battery.deep`(D-27), `battery.shutdown_request_failed`, `localization.initialpose`, `nav.line_mode_changed`(D-143), `nav.traffic_policy_staged/applied/reset`(D-151), `sim.traffic_signal_changed` 신규 문서화, `config.changed` key 에 `dds.rmw`. `safety.watchdog` 은 v1.0 부터 약속만 있었고 이제 실제로 발행된다(SAF-002). `nav.blocked` 는 미구현 표시. 카탈로그와 발행 지점의 일치는 `src/core/core/test/test_event_catalogue.py` 가 고정한다 |
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
