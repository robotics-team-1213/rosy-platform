# ROSY API & Protocol Reference
## 공유 인터페이스 계약서

**Document ID:** ROSY-API-REF-001
**Version:** v1.194
**Status:** Approved
**대상 독자:** rosy_core 개발자, rosy_fleet 개발자, 외부 SDK·AI·연동 시스템

> **거버넌스:** 본 문서는 로봇(rosy_core)과 Fleet(rosy_fleet)이 **공유하는 유일한 인터페이스 계약**이다.
> 본 문서의 변경은 양측 합의 + 문서 버전 업을 통해서만 가능하며(일방 변경 금지), 구현은 본 문서에 명시된 스키마를 임의로 확장하지 않는다.
> 구현 시 본 문서를 OpenAPI(YAML)로 기계 판독 가능하게 유지하는 것을 원칙으로 한다(계약 테스트의 원천).

**관련 문서:** ROSY-CORE-SRS-001 / ROSY-FLEET-SRS-001 / ROSY-ADR-001 / ROSY-PLN-001

---

# 1. 버저닝 및 폐기 정책

### D-531 경로 문맥 발행 (v1.166, 기본 꺼짐)

`line_follow.route_context_enabled: true`인 CORE는 `line/route_context`에
`std_msgs/String` JSON을 RELIABLE, KEEP_LAST 1, VOLATILE로 발행한다.
활성 문맥은 5 Hz로 갱신하며 지시 변경 시 바로 발행한다. 지시 완료·만료,
모드 변경, odom 소실·epoch 변경, E-Stop 시 `{ "v": 1, "seq": null }`로 비운다.
활성 메시지는 `{v: 1, seq, place_id, map_id, kind, stamp_s, valid_until_s}`와
선택 필드 `ahead_m: [lo, hi]`, `bend_phase`, `lane_turn_deg`, `curvature_1pm`을 갖는다.
`kind`는 `junction|bend|ring`; 시각은 ROS clock 기준이고 유효 기간은 최대 1초다.
`bend_phase`는 `kind: bend`일 때만 `bending|reacquiring`으로 나타낸다.
이 단계에서는 이미 굽이에 들어왔으므로 CORE는 접근 거리 `ahead_m` 대신 이 필드를 보낸다.
`exit_segment`가 지시에 있어도 실제 호 주행이 시작되기 전에는 `junction`이다.
`ahead_m`의 각 값은 −0.5~2.0 m, `|lane_turn_deg|`는 360° 이하,
ring의 `|curvature_1pm|`는 0.5~5.0 1/m이다. 경로 문맥은 인식 보조 증거이며
주행 명령이 아니다. CORE만 최종 `cmd_vel`을 발행한다.

켜진 경우 `GET /api/v1/line-follow`와 상태 스냅숏의 `line_follow`에는
`route_context`(현재 발행 중인 문맥 또는 null)와 `route_context_published_at_s`
(마지막 발행 ROS 시각 또는 null)가 추가된다. `rosy.controls/1`의
`base_velocity.route_context: true`는 설정이 켜졌음을 뜻하며 주행 가능성이나
현장 수용을 뜻하지 않는다. 인식의 `line/observation`과 `line/keep_debug`가
선택 필드 `route_context_seq`를 실으면 CORE는 현재 발행 문맥의 `seq`와
다른 프레임을 거절한다. 필드가 없거나 null이면 기존 인식 경로와 같다.
거절한 카메라 프레임은 `invalid_observation`으로 무효화해 즉시 HOLD하고,
그 프레임의 교차로 감지도 받지 않는다.

기본값은 false이며 이때 토픽과 능력 필드는 없다. 인식 소비자와 경계 판정은
별도 단계로 검증한다(D-531 P2/P3).

### D-468 추가 차선 경계 증거 (v1.106)

내부 `line/observation`의 CAMERA_LINE 증거는 optional `containment`를 포함할 수 있다.
원본 영상 `stamp`와 1us 이내로 일치하는 `stamp`, `geometry_id`,
`ground_source`(NOMINAL/CALIBRATED/GAZEBO), optional `uncertainty_m`와
`boundaries`(0~2개)를 보낸다. 각 경계는 `side`(left/right), `slope`,
`intercept_m`, 실제 관측 구간 `observed_x_min_m`/`observed_x_max_m`를 갖는다.
좌표는 base footprint 기준 x 전방/y 좌측, 직선 y=slope*x+intercept_m이다.
경계는 칠한 선의 중심이 아니라 차로 쪽(안쪽) 가장자리, 곧 달릴 수 있는 끝이다(생산자가
칠 폭의 절반 `lane_paint_half_width_m`만큼 안쪽으로 옮긴다).
CALIBRATED는 실제 승인된 calibration이 있을 때만 사용한다. unknown uncertainty는
null이며 임의의 안전 여유로 대체하지 않는다. 누락/단일 경계로 전체 차체 containment를
증명할 수 없고 관측 구간 밖으로 무제한 외삽하지 않는다. 명령 필드는 없다.
기존 관측 메시지와 공개 mode/route는 보존한다. 이 계약의 추가는 자동 복구 활성화나
장치/현장 수용을 뜻하지 않는다.

D-491(v1.115): `containment`는 optional `crosswalk`(`near_m`, `far_m`)를 더 가질 수 있다. D-573 6 개정(v1.194): optional `crosswalk_uncertainty_m`(m, 0–1) — 횡단보도 가까운·먼 끝의 앞뒤 최악 한도(영상 시각 몸 좌표). 검출기가 돈 모든 프레임에 둔다(찾았든 못 찾았든). 없으면 검출기가 돌지 않은 것이고 CORE 횡단보도 보고는 `unknown` 이다.
같은 영상 시각에 카메라가 본 차로와 나란한 줄무늬 횡단보도의 가까운 끝과 먼 끝이며,
base footprint 기준 전방 거리(m, 0~1, near < far)다. CORE는 지면 표시와 상관없이
`uncertainty_m`이 있고 0.015 m 이하일 때만(D-468과 같다) 이 구간을 영상 시각의 odom 자세에 고정해 IR 차선 감시의
휴식 구간으로 쓴다(D-491 개정 2026-10-07). 불확실도 없음·odom 끊김이면 구간이 없고 감시는 그대로다.
명령 필드는 없다.

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
  예외(D-548): root 가 만든 `/etc/rosy/dev-mode` 가 있으면 그 로봇만 세 공용 개발 토큰을 받고 기동 때 `auth.development_mode` 를 낸다. 파일을 지우면 즉시 401 이다. 이때도 공용 개발 토큰은 `/api/v1/host/ssh*`·`/api/v1/auth/enrollment-codes` 전부와 `/api/v1/host/*`·`/api/v1/system/tokens*`·`/api/v1/system/dds*` 쓰기에 403 `FORBIDDEN` 이다.
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
| `NO_REQUEST` | 404 | `GET /localization/request` — 로봇이 연 위치 요청이 없거나 `ttl_s` 가 지남 (v1.163) | 로봇 |
| `localized` · `busy` · `estop` · `path_not_clear` · `calibration_lease` · `unsupported` | 409 | `POST /localization/mission` 거부(D-395 P2-7, v1.73, 계약 §2 의 소문자 코드): 로봇이 이미 `LOCALIZED`; 미션·MANUAL·NAVIGATION·도킹·line-follow·swarm·Nav2 목표가 바퀴를 쥐고 있거나 로봇의 3 s 주입 검사가 도는 중(`reason: checking`); e-stop; 신선한 LiDAR 가 없거나 정면 부채꼴(±20°)이 0.25 m 보다 가까움(`nudge_forward`·`lane_to_stopline`); 다른 토큰의 보정 lease; 아직 없는 종류(`to_square`, 후속) | 로봇 |
| `CALIBRATION_ACTIVE` | 409 | 다른 토큰이 보정 세션 lease 를 쥐고 있어 구동 쓰기를 거부함: `teleop`, `/mode`(IDLE 제외), `line-follow/mode`(OFF 제외)·`hold`, `navigation/goal`·`home`, `docking/dock`·`undock`, `swarm/follow`. 멈추기만 하는 것(`safety/stop`, `/mode` IDLE, line-follow OFF, 각종 cancel)은 막지 않는다. `detail: {session}` 은 `GET /calibration/session` 의 세션과 같다. `POST /calibration/session` 이 이미 세션이 있을 때도 같은 코드 (D-321 부록, v1.68). D-395 경로 `POST /localization/decision`·`suspect` 에서는 같은 코드를 **423** 으로 낸다(v1.72, 계약 `docs/plans/2026-10-01-d395-phase2-interfaces.md` §2) | 로봇 |
| `TRIP_LEASED` | 409 | D-541 (v1.157): Fleet trip lease 가 살아 있어 **주인 아닌 토큰**의 구동·모드 쓰기를 거부함. `require_calibration_owner` 를 지나는 모든 쓰기다: `teleop`, `/mode`(IDLE 제외), `line-follow/mode`(OFF 제외)·`hold`·`junction`·`authority`, 막힘 결정 중 움직이는 답(RESUME·BACK_AND_RETRY·MANUAL·YIELD; `stuck_resolver` 토큰도 주인이 아니다), `navigation/goal`·`home`, `localization/initialpose`, `slam/start`·`stop`·`reset`, `docking/dock`·`undock`, `swarm/follow`, `PUT /safety/limits`, `POST /power/mode`, host install·rollback·reboot(`override_calibration` 없이), `/api/v1/do` 의 같은 동사, `POST /localization/mission`. D-395 경로 `POST /localization/decision`·`suspect` 에서는 `CALIBRATION_ACTIVE` 와 같이 **423** 으로 낸다. `POST /calibration/session` 은 lease 가 있으면 토큰과 관계없이 이 코드다. `PUT /trip-lease` 는 다른 `lease_id`(같은 토큰이어도)나 다른 토큰일 때 이 코드다. `detail: {lease_id, trip_id, holder, operator_name, since, expires_in_s}`. 멈춤(`safety/stop`, `/mode` IDLE, `navigation/cancel`, line-follow OFF, `swarm/cancel`, docking cancel, 막힘 WAIT·ABORT)은 막지 않는다 | 로봇 |
| `GOAL_LEASE_NOT_ACTIVE` | 409 | D-550 10 (v1.160): `POST /navigation/goal/lease` 의 `correlation_id` 가 활성 임대 목표가 아님(취소·도착·실패·만료·교체, 또는 임대 없이 연 목표). 갱신은 목표를 되살리지 않는다 | 로봇 |
| `FLEET_GOAL_ACTIVE` | 409 | D-555 (v1.163): `PUT`/`DELETE /api/v1/fleet/link` 를 Fleet 목표(`nav.fleet_goal()`)가 진행 중일 때 부름. relink 가 링크를 끊어 SAF-003 을 무장시키지 않도록 목표가 끝난 뒤 다시 한다 | 로봇 |
| `FLEET_LINK_CONFIG_INVALID` | 409 | D-555 (v1.163): 기동 때 잘못된 `fleet.heartbeat_reply_timeout_s` 또는 SAF-003 시간을 기본값으로 대신한 CORE 에 `PUT /api/v1/fleet/link`. 설정을 고치고 CORE 를 다시 띄운다 | 로봇 |
| `MANUAL_MODE` | 409 | D-541 2 (v1.157): `PUT /trip-lease` 를 MANUAL 모드 로봇에 엶(`manual_active` 와 관계없이). 먼저 IDLE 로 둔다 | 로봇 |
| `LINE_FOLLOW_NOT_HELD` | 409 | `POST /line-follow/hold` 인데 운전자 확인(`hold_s`) 세션이 없음 (v1.63) | 로봇 |
| `LINE_FOLLOW_NOT_ACTIVE` | 409 | `POST /line-follow/junction`·`POST /line-follow/authority`(v1.143) 인데 line-follow 가 꺼져 있음 (D-494, v1.114) | 로봇 |
| `JUNCTION_ALREADY_DONE` | 409 | `POST /line-follow/junction` 인데 같은 `place_id`·`action` 지시가 이미 실행됨(재획득 완료·직진 통과·회전 뒤 중단). 다른 `place_id` 지시로만 풀림(모드 변경으로는 풀리지 않음) (D-495, v1.114) | 로봇 |
| `JUNCTION_CAMERA_ONLY` | 409 | `POST /line-follow/junction` 인데 line-follow 가 `IR_LINE` — 교차로 감지는 CAMERA_LINE keep 에만 있음 (D-495, v1.114) | 로봇 |
| `AUTHORITY_ODOM_STALE` | 409 | `POST /line-follow/authority` 인데 받는 순간 신선한 odom(0.3 s)이 없어 주행 거리를 잴 수 없음. 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `AUTHORITY_POSE_STALE` | 409 | `POST /line-follow/authority` 의 `pose_stamp` 가 CORE odom 기록(이 line-follow 세션의 같은 odom 궤적, 최대 200개 표본)보다 오래됨. 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `AUTHORITY_POSE_FUTURE` | 409 | `POST /line-follow/authority` 의 `pose_stamp` 가 CORE 의 가장 새 odom 표본보다 0.05 s 넘게 앞섬(시계 불일치). 쥐고 있던 통행권도 버리고 선다 (D-517 4, v1.143) | 로봇 |
| `JUNCTION_ODOM_STALE` | 409 | `POST /line-follow/junction` 에 기대 창(`expect_in_m`·`expect_tol_m`)이 있는데 받는 순간 신선한 odom(0.3 s)이 없어 기대 점을 둘 수 없음 (D-507, v1.127) | 로봇 |
| `LANE_ARC_UNAVAILABLE` | 409 | `POST /line-follow/junction` 에 `exit_segment` 가 있는데 능력 `lane_arc` 가 거짓(`line_follow.arc_enabled` 꺼짐, 현장 바닥 선언 `site_floor_map_id` 없음, 또는 `ir_guard_speed_scale` 0) (D-520, v1.145, v1.154) | 로봇 |
| `JUNCTION_ARC_RUNNING` | 409 | `POST /line-follow/junction` 의 `action: bend` 인데 D-520 호(`line_follow.arc.state: running`)가 달리는 중 — 호가 그 차로를 달리므로 굽이 지시를 받지 않는다. Fleet 은 호가 도는 동안 굽이를 보내지 않는다 (D-520, v1.145) | 로봇 |
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
| D-535 연결 이유 코드 (`ROBOT_UNREACHABLE` · `TLS_REQUIRED` · `TLS_NAME_MISMATCH` · `CA_UNKNOWN` · `CORE_NOT_READY` · `API_VERSION_TOO_OLD` · `PAIRING_UNAVAILABLE` · `PAIRING_REQUIRED` · `IDENTITY_CHANGED` · `LAN_REQUIRED` · `APPROVAL_PENDING` · `APPROVAL_CODE_WRONG` · `CONSOLE_APPROVAL_REQUIRED` · `APPROVAL_TIMEOUT` · `APPROVAL_CANCELLED` · `APPROVAL_EXPIRED` · `APPROVAL_DENIED` · `APPROVAL_REVOKED` · `RATE_LIMITED` · `SESSION_TAKEN` · `UNEXPECTED_RESPONSE`) | 경로의 기존 상태 그대로 | 연결·승인·세션이 안 된 이유. `/api/v1/auth/peer-pairing/*`·`/api/v1/auth/connection` 거절의 `error.code`이고, `error.message`(운영자 문장)와 `error.detail.action`(할 일)·`detail.retry`(`auto`\|`person`)를 싣는다. 기존 `detail` 필드는 본문 맨 위에 그대로 있다. 로봇에 닿지 못한 실패(이름·TCP·TLS)와 옛 로봇의 답은 클라이언트가 같은 코드로 분류한다. 기계 원천 `test/fixtures/protocol/connect-reasons.v1.json` = `core_common.protocol.connect_reason` (D-535, v1.155) | 로봇/클라이언트 |
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
| GET | `/api/v1/system/info` | Viewer | IDN-003. `caller_role`(v1.18 additive) — 이 요청 토큰의 역할(`viewer`\|`operator`\|`administrator`). 대시보드는 이것으로 관리 패널을 가르고, 권한 밖 경로를 찔러 보지 않는다. `robot_name` 은 오버레이에 이름이 없고 기본값(`Rosy 01`)뿐이면 프로비저닝 신원(`ROSY_DEVICE_NAME`, 없으면 `Rosy NN` ← `ROSY_ROBOT_NUMBER`)에서 온다. `device_uid`(v1.150 additive)는 프로비저닝 UID이며 없으면 null. `serial_number`는 설정값이 없고 UID가 있을 때 Pi `/proc/cpuinfo`의 Serial을 읽으며, 못 읽으면 null이다. 두 값은 등록 일관성 확인용이며 물리 차체 위치 증거가 아니다 |
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
| GET | `/api/v1/sensors/{lidar\|imu\|ultrasonic\|battery\|encoder\|motor}` | Viewer | §12. 표본이 없으면 404 `NOT_FOUND`. 예외로 `battery` 는 404 를 내지 않는다(D-502, v1.120): 200 `{voltage, received_at, source, evidence, sample_age_s, stale_after_s}`. `evidence` 는 `missing`\|`fresh`\|`stale`(`GET /power/health` 의 `battery` 와 같은 판정, 5 s), 표본이 없으면 `voltage`·`received_at`·`source` 는 `null`. 배터리 모니터가 없는 런타임은 `evidence: missing`, `stale_after_s: null`. 제품 그래프의 표본은 `battery/voltage` 에서 오며 `source: "battery/voltage"` 다(D-192 4). 벤치의 `batt_state` 표본은 기존 필드 `percentage`·`power_supply_status`·`location` 을 더 싣는다. 두 토픽이 함께 돌면 마지막으로 온 표본이 이기므로 이 세 필드는 나타났다 사라진다 — 소비자는 있을 때만 읽는다 |
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
| POST | `/api/v1/navigation/goal/lease` | Operator | D-550 10 (v1.160, Safety-Review). Fleet 목표 임대 갱신 `{correlation_id (1–128자), ttl_s (0 < s ≤ 5, 유한)}` → `{renewed: true, correlation_id, ttl_s}`. `POST /navigation/goal` 선택 필드 `lease_ttl_s`(0 < s ≤ 5, 유한, `correlation_id` 필요; 어기면 모드 전이 전에 400 `VALIDATION_ERROR`)로 연 임대를 늘린다. 활성이 아니거나(취소·도착·실패·만료·교체된) 임대 없이 연 `correlation_id`는 409 `GOAL_LEASE_NOT_ACTIVE`이고 목표를 되살리지 않는다. 만료하면 5 Hz 전원 타이머가 SAF-003 STOP과 같은 취소 경로로 목표를 취소한다(`nav.canceled` source `goal_lease`). 만료는 `fleet_loss_policy`와 관계없이 STOP이다: 임대가 먼저 끝나면 SAF-003은 지킬 목표가 없어 `safety.fleet_lost`를 내지 않는다(D-550 10). `ttl_s`는 CORE 단조 시계. 능력 `controls` `base_velocity.goal_lease: true`(목표 주행이 있을 때)일 때만 Fleet이 쓴다. `lease_ttl_s`가 없는 목표는 지금과 같다 |
| POST | `/api/v1/navigation/cancel` | Operator | NAV-002 |
| POST | `/api/v1/navigation/home` | Operator | NAV-003. 기능 보류 시 409 `CAPABILITY_WITHHELD`. D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| GET | `/api/v1/navigation/state` | Viewer | NAV-004. `mapping_active: bool`은 CORE가 수락한 맵핑 세션 상태다. SLAM Toolbox의 실제 실행·지도 갱신 성공을 증명하지 않는다. |
| GET | `/api/v1/navigation/path` | Viewer | MAP-003. `{poses}`; 경로 메시지를 받은 뒤에는 `map_id`(그때 로봇 지도 ID 또는 null), `frame_id`(`nav_msgs/Path.header.frame_id` 또는 null), `age_s`(CORE 수신 뒤 경과 초, 서버 monotonic 시계)를 함께 반환한다. 최초 수신 전은 `{poses: []}`. 이 응답은 마지막 수신 계획이며 현재 목표와의 동일성은 증명하지 않는다. |
| GET | `/api/v1/line-follow/perception` | Viewer | 저장된 `paint_source`(threshold / denoise / learned), `camera_lane_mode`, 서명·해시 확인 `model_ready`와 `model_revision`. 별도 `applied_paint_source`는 실제 최신 keeper 프레임의 threshold / denoise / learned / denoise_fallback 또는 null; `applied_source_age_s`는 monotonic 수신 나이(2초 이내), `applied_model_revision`은 실제 사용한 learned mask의 producer revision(없으면 null). stale·malformed·설정 불일치·재시작 전 증거는 null. 운전 모드와 독립이며 물체 검출이나 주행 허가가 아니다. |
| PUT | `/api/v1/line-follow/perception` | Administrator | `{paint_source: threshold\|denoise\|learned}`만 허용. IDLE·line-follow OFF·보정 비활성, Host Agent가 fresh 정지 및 active mission 부재를 재확인. 기존 기하 보존, learned는 고정 signed model pointer 검증, camera만 재시작·실패 복구. `applied: true`는 설정/서비스 적용이며 live 추론이나 실제 주행 성공이 아니다. |
| GET | `/api/v1/line-follow` | Viewer | D-143 — 선택 모드, 상태, 증거 신뢰도·나이, 최종 선속도·각속도와 사유. `clearance_m`(정면 LiDAR 최소 거리, 없으면 null)과 정지 사유 `obstacle_ahead`·`obstacle_sensor_stale`·`driver_released` (D-344, v1.63). IR 이탈 감시(`line_follow.ir_guard_enabled`)가 켜지면 추종 사유 `lane_edge_left`·`lane_edge_right`(경계 반대로 비킴)와 정지 사유 `lane_departure`·`lane_guard_stale` (D-344 §12, v1.63). 감시가 알려진 횡단보도 구간(D-491)에서 쉬면 추종 사유 `ir_guard_crosswalk` (v1.115). 공칭 지면(`ground: NOMINAL`) 카메라 증거는 `hold_s` 세션이 없으면 `nominal_ground_requires_driver` 로 멈춘다 (D-364 §3, v1.63). 정지 사유 `limit_level_too_low`(수동 한도 L1 미만)·`angular_limit_zero`(각속도 한도를 읽을 수 없음) (D-344 §13, feat/device-prep, v1.64). 몸 기준 정지(D-422, v1.84: `obstacle_mode: path` + 로봇 패키지 URDF 몸 기하)에서는 `body_gap_m`(의도한 차선 호를 따라 몸 윤곽이 닿기까지의 거리, 없으면 null)·`stop_gap_m`(그 속도의 정지 간격)·`clearance_source`(`lidar`·`memory`(LiDAR `range_min` 아래로 사라져 기억한 반환)·`ultrasonic`·`odometry_lost`(바퀴 값 적분 실패 — 다음 스캔까지 정지), 아무것도 없으면 null)가 오고 `clearance_m` 은 `body_gap_m` 과 같은 몸 간격이다. 그 밖에는 세 필드 모두 null. 선택 필드 `lane_return_containment`(D-507 7, v1.133, 개정 v1.134): D-468(`recovery_local_enabled`)이 추종 중일 때 `contained`(차로 안이 증명됨) 또는 `unknown`(증명 못 함 — D-468은 멈추지도 움직이지도 않고 추종은 `recovery_local_enabled: false` 와 같다), 그 밖에는 null. D-468 이탈(`lane_return_*`)은 양의 증거가 있을 때만 열린다: (1) 신선한 `ready` 차로에서 몸이 경계를 넘음(`margin + uncertainty_m < 0`), (2) 추종 중 자세 불연속(odom 점프) 또는 연속성 epoch 변경, (3) 증명된 차로 안이지만 체크포인트 차로가 아님. 차로가 보이지 않은 채 D-476 bridge 가 끝나면 D-468은 역추적하지 않고 손실 경로(LOST)로 간다. D-517 4 (v1.143): CORE 가 통행권을 강제하는 동안에만 `authority {state: FREE\|HOLDING\|EXPIRED\|NONE, authority_id, leg_id, remaining_m, expires_in_s, reason}` 가 붙는다(`POST /line-follow/authority`). 강제하지 않으면 이 키가 없고 응답은 이전과 같다. 이 응답에만 있고 상태 스냅숏 `line_follow` 에는 없다 D-573 6 (v1.179, 개정 v1.194): `crosswalk` 는 게이트 설정과 무관하게 늘 있다. 게이트(`line_follow.crosswalk_gate_enabled`, 기본 false)가 무장한 구역 안이면 `{state: armed|approaching|looking|waiting|crossing, zone_id, source: camera, reason: person_present|look_unknown|sensor_stale|zone_lost|null, waiting_s, look_progress}`. 그 밖에는 (v1.194) `{state: inside}`(이 odom epoch의 D-491 카메라 구역이 몸 또는 D-407 후진 범위의 반지름 `hypot(max(body_front_x_m, recovery_back_m − body_rear_x_m), body_half_width_m)` 안), `{state: ahead}`(같은 길에서 구역이 아직 앞), `{state: unknown, reason: pose_stale|perception_stale|not_watched|camera_crosswalk_unadmittable|zone_unplaced}`(CORE가 알 수 없음: 최근 카메라 프레임의 `containment.crosswalk_uncertainty_m` 이 없거나 `line_follow.crosswalk_max_uncertainty_m` 초과면 `camera_crosswalk_unadmittable`, odom 자세 0.3 s 초과, 그 모드의 카메라 관측이 `stale_after_s` 초과·모드 OFF, 이 epoch에 경계와 한도 안 불확실도를 가진 카메라 프레임이 없었거나, 끊김 없는 그런 프레임 구간 안에서 몸 뒤끝 + `recovery_back_m` 이 카메라가 본 가장 가까운 땅까지 아직 오지 못했거나, 마지막 그런 프레임 뒤 그 프레임의 가장 가까운 땅보다 멀리 움직임·URDF 몸 모름, 구역을 odom에 아직 놓지 못했거나 한 epoch에 64개 초과), 아니면 null(몸과 후진 범위가 카메라가 본 땅 위이고 어느 구역에도 닿지 않음). `inside`·`ahead`·`unknown` 의 `zone_id`·`waiting_s`·`look_progress` 는 null, `source` 는 `camera`. 키가 없으면 이전 CORE 다. Fleet D-577 R3 는 null 에서만 열리고, `unknown`·키 없음은 R5 `crosswalk_unknown`, 그 밖은 R5 `crosswalk`. Fleet은 현장 지도 `crosswalks[]` 를 기준으로도 본다: 신뢰 지도 자세가 다각형에서 0.29 m 안이면 R5 `crosswalk`, 지도에 횡단보도가 있는데 신뢰 지도 자세가 없거나 출처 없는 `UNKNOWN` 이면 R5 `crosswalk_unknown`. 게이트가 세우면 `state: HOLD`, `reason` `crosswalk_looking`·`crosswalk_person_present`·`crosswalk_look_unknown`·`crosswalk_sensor_stale`·`crosswalk_zone_lost`. |
| PUT | `/api/v1/line-follow/mode` | Operator | D-143 — `{mode: OFF\|IR_LINE\|CAMERA_LINE, hold_s?}`. 소스는 상호 배타적이며 변경 즉시 이전 증거와 명령을 폐기. 도킹/언도킹 중에는 409 `DOCKING_ACTIVE` (v1.18). 요구 능력은 구동(`mobility.move`)이다 — Nav2 가 없는 `motor` 런타임에서도 켜진다(D-344 §7, v1.63). `hold_s`(0 < s ≤ 2)를 주면 운전자 확인 세션이다: `POST /line-follow/hold` 가 그 안에 계속 와야 하고, 끊기면 CORE 가 스스로 OFF(`reason: driver_released`)로 내리고 바퀴 명령을 지운다(D-344 §8, v1.63). OFF 가 아닌 모드는 D-395 로봇이 `LOCALIZED` 가 아니면 409 `NOT_LOCALIZED` (v1.72) |
| POST | `/api/v1/line-follow/hold` | Operator | D-344 §8 — 운전자가 "진행"을 누르고 있다. 활성 `hold_s` 세션의 만료를 `hold_s` 만큼 미룬다. 세션이 없으면 409 `LINE_FOLLOW_NOT_HELD` (v1.63) |
| POST | `/api/v1/line-follow/junction` | Operator | D-494 4항 (v1.114) — 다음 교차로 하나에 대한 지시 `{action: straight\|left\|right\|stop, place_id, stop_after_m?, expires_s, turn_deg?, advance_m?}`. `expires_s` 0 < s ≤ 30, `stop_after_m` 0 ≤ m ≤ 2 이고 `stop` 에만 쓴다(아니면 400 `VALIDATION_ERROR`). 지시는 하나만 보관하고 새 지시가 바꾼다. 응답 `{accepted, junction_seq, state}`. 회전 동작 중에 온 새 지시는 그 동작을 `aborted` 로 멈추고 자신은 받지 않는다(`accepted: false`). 모드를 바꾸지 않는다. line-follow 가 OFF 면 409 `LINE_FOLLOW_NOT_ACTIVE`, `IR_LINE` 이면 409 `JUNCTION_CAMERA_ONLY`(IR 에는 교차로 감지가 없다, D-495 검토 M4). "seat" 는 D-460 의 기존 어휘라 다른 구동 경로처럼 수동 조종 해제(409 `MODE_CONFLICT`)와 보정 lease(409 `CALIBRATION_ACTIVE`)를 지킨다. 회전 동작 중 같은 지시(`place_id`·`action`·`turn_deg`·`advance_m`)의 재전송은 지금 seq·상태를 돌려주는 무동작이다. 이미 실행된 지시의 반복은 409 `JUNCTION_ALREADY_DONE` 이다. 한 교차로 정지 안의 모든 회전은 그 교차로를 처음 본 순간의 진입 yaw + `turn_deg` 를 겨눈다(중단 뒤 재전송이 방향을 더하지 않는다). CORE 는 자기 차선 명령을 그대로 두거나 0 으로 만들 뿐이다. 오늘 인식은 분기 후보를 주지 않으므로(D-494 구현 부록 2026-10-07) `turn_deg` 없는 `left`·`right` 는 받자마자 `unresolved` 이고 HOLD `junction_unresolved` 다. D-495: `turn_deg`(부호 있는 각도, `left` 는 +, `right` 는 −, 0 < \|θ\| ≤ 150)와 `advance_m`(0–0.30, 기본 0.10, `turn_deg` 와만)가 있으면 `armed` 이고, 교차로가 감지되면 CORE 매니저가 정지 확인(odom \|v\| < 0.01 m/s·\|ω\| < 0.05 rad/s 0.2 s, 사유 `junction_stopping`) → 제자리 회전(`turning`, odom yaw 닫힌 고리, 각속도 ≤ 수동 한도, `\|오차\| ≤ max(5°, ω·junction_turn_lead_s)` 에서 멈춘 뒤 ±5° 안 0.3 s 머무름과 odom 정지 확인, 한도 \|θ\|/ω_min + 2 s) → 직진(`advancing`, `advance_m`, 속도 ≤ trip 최고 속도의 절반, 한도 `advance_m`/속도 + 2 s) → 차선 다시 잡기(`reacquiring`, 0.20 m 또는 5 s 안에 연속 `junction_reacquire_frames`(기본 3)장의 신뢰도 기준 이상 visible 프레임, containment 방향이 있으면 돌린 방향 ±30° 안, 못 잡으면 `unresolved`)를 한다. 회전·전진 중 상태는 `RECOVERING` 에 사유 `junction_stopping`·`junction_turning`·`junction_advancing` 이다. odom 낡음·점프, 모드 변경·E-Stop, 보정 lease, D-422 근접 정지, 동작 확인 실패·미바인딩, D-498 현장 근거로 시작한 회전에서 그 근거를 잃음(`turn_basis_lost`, v1.118), 정지 확인 실패, 교차로 전에 시작된 차선 손실(`lane_lost_before_junction`), 시간 초과, 다른 새 지시는 즉시 0 명령과 `aborted`(HOLD `junction_aborted`, `junction.reason` 에 이유)다. `aborted` 는 다음 지시나 모드 변경까지 이어진다. `straight` 는 `armed` 이고 D-476 bridge 방향 힌트를 채운다. `stop` 은 측정한 odom 으로 `stop_after_m` 뒤 또는 교차로 감지 중 먼저 오는 쪽에서 HOLD `junction_stop` 이며(odom 이 없으면 바로) 다음 지시나 모드 변경까지 이어진다. 교차로 감지는 keep 모드 keeper 의 교차로 HOLD 사유(`line/keep_debug` `reason`: `junction_transverse`·`junction_fork`, `lane_corner_turning` 이 켜졌을 때만 — D-495부터 로봇 기본값 켜짐)뿐이다. 감지됐는데 지시가 없거나 `armed` 지시가 만료됐으면 HOLD `junction_waiting` 이고 다음 지시까지 잠근다. 상태는 `GET /line-follow` 와 스냅숏 `line_follow.junction {pending_action, place_id, state: idle\|armed\|executing\|waiting\|unresolved\|turning\|advancing\|reacquiring\|aborted, seq, turn_deg, reason}`. D-507 2–4항 (v1.127, `junction_pivot` 능력이 참인 로봇에만 보낸다): 선택 필드 `map_id`(`^[A-Za-z0-9_.-]{1,64}$`, 지시를 계산한 지도. 기대 창 누락 시 감지를 거절하는 표지이며, 현장 바닥 선언(D-507 9항)과 운동 허가 시 대조한다), `expect_in_m`(0 < m ≤ 2, 보낼 때 로봇 자세에서 장소까지 차로를 따른 거리), `expect_tol_m`(0 < m ≤ 0.30, 장소 위치 오차), `pivot_past_line_m`(−0.30 ≤ m ≤ 0.30, v1.135부터 부호 있음: 감지된 가로선에서 회전 축(장소 점)까지, 장소가 선 너머면 양수, 선 앞이면 음수(회전교차로 입구·T자에서 keeper가 재는 먼 쪽 경계), `straight` 또는 `turn_deg` 가 있는 `left`·`right`. `straight` 에서는 기대 창에만 쓰고 접근하지 않는다). `expect_in_m` 과 `expect_tol_m` 은 함께 보낸다. 범위·짝이 틀리면 400 `VALIDATION_ERROR` 다. 기대 창 필드가 있는데 지시를 받는 순간 신선한 odom(0.3 s)이 없으면 409 `JUNCTION_ODOM_STALE` 이다. map_id도 기대 창도 없는 옛 지시는 오늘 동작 그대로다. map_id가 있는데 기대 창이 빠진 straight·회전 지시는 가로선 감지 시 HOLD junction_unexpected이고 지시는 armed로 남는다(D-507 3항 보충, 2026-10-08); Fleet은 trip을 중단한다. 모서리 정지(v1.148, lap SIM A): 기대 창이 있는 지도 지시가 `armed` 이고 감지가 없을 때, `line/keep_debug` `strategy` 가 `corner_left`·`corner_right`(최근 2 s 안 한 프레임)이고 기대 가로선이 0.45 m + `expect_tol_m` 안이면 keeper 의 모서리 회전 대신 HOLD `junction_corner_hold` 다(지시는 `armed`, 창을 측정할 수 없으면 HOLD). 2 s 동안 모서리 프레임이 없으면 풀린다. 이 정지 중에 지시가 만료되면 풀지 않고 새 지시나 모드 변경까지 HOLD `junction_corner_hold` 로 남는다(fail closed). Fleet 은 자기 지시에서 이 사유를 보면 trip 을 바로 끝낸다. 모서리 방향 범위(v1.152, lap SIM 2): 지시와 어긋나는 모서리만 정지한다. `left`·`right` 는 반대쪽 모서리(`left` 에 `corner_right`, `right` 에 `corner_left`)만, `straight` 는 선택 필드 `lane_turn_deg`(지도 차로가 로봇에서 장소까지 도는 부호 있는 방향 변화, 도, 왼쪽 +, −360 ≤ θ ≤ 360, `straight` 이고 기대 창이 있을 때만, 아니면 400 `VALIDATION_ERROR`)가 그 모서리 쪽으로 20° 이상이 아닐 때만 정지한다(왼쪽으로 도는 회전교차로 둘레의 `corner_left` 는 차로다). `lane_turn_deg` 가 없으면 모든 모서리에서 정지한다(옛 Fleet, 이 필드를 모르는 옛 CORE 는 무시하고 v1.148 그대로). Fleet 은 기대 창을 보내는 `straight` 에 늘 싣는다. stop은 이 창을 쓰지 않는다. 기대 창(v1.139부터 주행 거리, 2026-10-08 사용자 결정): 기대 값은 차로를 따른 거리 `expect_in_m − pivot_past_line_m`(`junction_fork` 감지면 `expect_in_m`, 필드가 없으면 0을 뺀다)이다. 받은 순간의 odom 전진 거리 누적값(매 걸음을 앞 자세의 yaw 에 투영한 부호 있는 합)을 기록하고, 감지마다 측정값 = 받은 뒤 감지 때 odom 자세까지 전진 거리 + `line/keep_debug` `junction_ahead_m` 이다. 받은 뒤 전진 거리가 봉우리에서 0.01 m 넘게 내려가면(후진) 창 밖이다. `straight`·회전 지시는 \|측정 − 기대\| ≤ `expect_tol_m` 일 때만 쓰인다. 곧은 접근에서는 v1.139 이전의 곧게 내다본 점 비교와 같은 값이고, 굽은 접근(회전교차로)에서도 쓸 수 있다. 창 밖이거나 측정할 수 없으면(`junction_ahead_m` 없음, odom 끊김·epoch·frame 변경) HOLD `junction_unexpected`, 상태 `unexpected` 이고 지시는 `armed` 로 남는다(감지가 사라지거나 창 안의 감지가 오면 `unexpected` 가 풀린다). `stop` 지시는 창을 쓰지 않는다. 회전 축 접근: 회전 지시에 `pivot_past_line_m` 이 있고 가장 최근 감지가 `junction_ahead_m` 을 실었으면, 정지 확인 뒤 `approaching`(사유 `junction_approaching`)으로 그 감지(같은 odom 궤적에 고정, 나이 무관)의 가로선 점에서 진입 yaw 방향으로 `pivot_past_line_m`(`junction_fork` 면 0) 더 간 점까지 진입 yaw 를 붙잡고 직진한다. 그 점이 로봇 자리이거나 뒤면 접근 거리 0으로 그 자리에서 회전하고 뒤로 가지 않는다. 속도는 `advancing` 과 같고, 한도는 거리/속도 + 2 s, 중단 규칙·운동 근거·D-422 검사도 `advancing` 과 같다. 도착 뒤 정지 확인을 다시 하고 회전한다(목표는 그대로 진입 yaw + `turn_deg`). IR 가드가 켜진 현장 근거에서 접근과 `straight` 통과 중의 IR `centre` 는 측정 가로선 띠 안에서만 허용한다: 띠는 감지 자세 + `junction_ahead_m` 에 odom 으로 고정하고 진입 방향으로 [선 − 테이프 폭/2 − e, 선 + 테이프 폭/2 + e](선은 측정한 테이프 중심, 테이프 폭 0.025 m, v1.135), 옆으로는 ±(반폭 + e)다. 반폭은 지시의 `pivot_past_line_m` 이 양수일 때 그 값, 아니면(없거나 0 이하) D-491 통로 반폭 0.10 m 다. e = `crosswalk_range_error_fraction`·`junction_ahead_m` + `crosswalk_odom_error_fraction`·min(감지 뒤 odom 이동, `junction_ahead_m` + 테이프 폭)이며, IR 줄은 자세 + `ir_row_x_m` 이다. IR 줄이 먼 끝을 지나거나 감지 뒤 이동이 `junction_ahead_m` + 테이프 폭/2 + e 를 넘으면 띠는 끝나고, 모드 변경·정지·다음 지시에서도 끝난다. 띠 밖의 `centre` 는 지금처럼 중단(`turn_basis_lost`, 통과 중이면 `lane_departure`)이고, odom 궤적이 바뀌면 띠가 사라진다. 회전 중에는 띠를 쓰지 않는다. `junction.pivot_basis` 는 접근했으면 `map`, 멈춘 자리에서 돌면 `stop_point`, 회전 전에는 null 이다. 상태 목록에 `approaching`·`unexpected` 를 더한다. D-507 보충 (v1.142, `lane_bend` 능력이 참인 로봇에만 보낸다): `action: bend` 는 지도의 굽이 장소 하나를 odom 호로 지나는 지시다. 필수 `turn_deg`(부호 있는 회전, 왼쪽 +, 0 < \|θ\| ≤ 90), `map_id`, `bend_in_m`(0 < m ≤ 2, 보낼 때 로봇 자세에서 호 시작점까지 차로를 따른 거리), `bend_tol_m`(0 < m ≤ 0.30, 그 거리의 오차), `bend_radius_m`(0 < m ≤ 0.5, 중심선 호 반지름); `expect_in_m`·`expect_tol_m`·`pivot_past_line_m`·`advance_m`·`stop_after_m` 는 함께 둘 수 없고, 세 `bend_*` 필드는 다른 action 에 둘 수 없다(400 `VALIDATION_ERROR`). 받는 순간 신선한 odom 이 없으면 409 `JUNCTION_ODOM_STALE`. 상태: `armed`(카메라 추종 그대로, 받은 뒤 odom 이동 거리를 센다. 같은 `place_id`·`turn_deg` 의 재전송은 만료만 늘리고 잰 거리를 지킨다. D-476 bridge 힌트는 모름 그대로, 이동 거리는 진행 방향 부호 투영이라 뒤로 간 거리는 뺀다) → 호 시작점 `bend_tol_m` + 0.25 m 앞부터 카메라가 곧은 확신 추종(`TRACKING`/`tracking`, \|error\| ≤ `bridge_arm_max_error`)을 멈춘 첫 틱(카메라 자신의 HOLD·손실·큰 오차·교차로 감지. 장애물·IR·한도·LOST HOLD는 그대로 HOLD이고 지시는 `armed`, 닻이 없으면 호 시작점까지 지금의 HOLD)이나 호 시작점 `bend_tol_m` 앞에서 `bending`(사유 `junction_bending`: 마지막 곧은 확신 틱의 odom 자세에서 그 방향 직선, 반지름 `bend_radius_m` 호, 나가는 직선을 `bridge_lookahead_m` pure pursuit 로, 속도 ≤ trip 최고 속도의 절반, 각속도 상한을 넘으면 같은 호로 감속) → 호 끝에서 `reacquiring`(사유 `junction_reacquiring`, 나가는 직선을 계속 좇으며 D-495 재획득 또는 나가는 방향 ±30° 안의 교차로 감지로 끝) → `idle`. 그 앞 구간 밖의 교차로 감지는 HOLD `junction_unexpected`(지시는 `armed`). 이유 있는 0 명령 `aborted`: `no_anchor`(곧은 확신 틱이 없거나 0.25 m 넘게 뒤), `lane_lost_before_bend`, `odom`, `distance`(실측 odom × `bridge_distance_scale` 이 남은 호 경로 + `bridge_lookahead_m` 초과), `timeout`(직선/속도 + 호/호 속도 + 2 s), `stuck`(D-407), `bend_basis_lost`(운동 근거 상실), `motion_unconfirmed`(D-507 6 운동 허가 종류 `bend` 거절: 현장 근거는 IR `clear` 만), `off_path`(경로에서 옆으로 0.06 m 초과 또는 추적점이 뒤), 기존 중단 규칙(모드·보정·stuck·사유). 그 twist 의 D-422 몸 sweep 이 재출발 간격 이하이거나 스캔이 `clearance_stale_s` 보다 낡은 틱은 0 명령 HOLD `junction_bend_blocked` 이고 통과는 이어진다(시간 상한 안). 재획득을 0.20 m·5 s 안에 못 하면 `unresolved`(HOLD). 뒤로 가지 않는다. 상태 목록에 `bending` 을 더한다 D-520 1–2항 (v1.145, `lane_arc` 능력이 참인 로봇에만 보낸다): 선택 객체 `exit_segment {curvature_1pm, length_m, outer_line_offset_m, end_place_id}` — 이 장소의 회전(또는 앞 호 끝의 `straight`) 뒤 들어갈 차로가 반지름 1/\|κ\| 의 원호이고 `end_place_id` 까지 `length_m` 이라는 뜻이다. `curvature_1pm` 은 부호 있는 1/m(왼쪽·반시계 +, 0.5 ≤ \|κ\| ≤ 5), `length_m` 0 < m ≤ 1.0, `outer_line_offset_m` 0.05–0.20(차로 중심선에서 곡선 바깥 칠한 선 중심까지, 지도의 선 간격에서 옴), `end_place_id` 1–128자. `map_id` 가 없거나, `stop` 이거나, `turn_deg` 없는 `left`·`right` 에 오면 지시 전체가 400 `VALIDATION_ERROR` 다. CORE 의 `line_follow.arc_enabled` 가 꺼져 있으면 409 `LANE_ARC_UNAVAILABLE` 이다. `exit_segment` 가 있으면 `advance_m` 은 무시한다(기본 0.10 도 쓰지 않는다). 들어감: (a) `exit_segment` 가 있는 `left`·`right` 가 `turning` 을 마쳤고 `pivot_basis` 가 `map` 또는 `segment_end` 면 그 지시는 `advancing`·`reacquiring` 없이 그 자리에서 끝나고(상태 `idle`, 같은 `place_id`·`action` 반복은 `JUNCTION_ALREADY_DONE`) 새 호 기록이 열린다. (b) 앞 호 끝에서 `end_place_id` 의 `straight` 가 `exit_segment` 를 실었으면 그 지시도 끝나고 다음 호가 곧바로 열린다. `pivot_basis: stop_point` 면 호를 열지 않고 전진 없이(0 m) 재획득한다. 호 주행: v = min(`cruise_speed`, `max_linear`, 수동 선속도 한도), ω = `arc_curvature_gain`·v·κ + v·c (v1.154, D-520 개정 2026-10-09: c 는 호를 열 때 odom 에 놓은 지도 원(회전 뒤면 회전 목표 yaw 를 접선으로 하고 지금 자리를 지나는 원, 같은 세대의 이어지는 `straight` 면 앞 호의 원)으로의 반지름·방향 보정, \|c\| ≤ 1.5 1/m, IR 보정 중 0; 보정 밖에서 원과의 odom 거리가 0.075 m 를 넘으면 HOLD `lane_arc_edge`; 첫 IR `left`·`right` 판정은 원을 그 쪽 칠한 선 기준으로 옮긴다), \|ω\| 가 live 각속도 한도를 넘으면 같은 곡률로 v 를 줄인다. 상태 `RECOVERING`, 사유 `lane_arc`(IR 보정 중 `lane_arc_correcting`). 길이는 매 걸음을 앞 자세 yaw 에 투영한 odom 의 부호 있는 합이고 `length_m` 에 닿으면 끝난다. 시간 한도 `length_m`/v + 2 s(IR 보정이 열리면 그 보정 한도만큼 늘어남). 호 주행 중에는 keeper 사유(`no_boundary`·`flipping`·교차로·`line_not_visible`·`low_confidence`·영상 품질)로 서지 않고 손실 시계가 돌지 않으며(끝나면 새로 시작), D-476 bridge·D-468 이탈 판정·D-407 막힘·keeper 교차로 감지를 쓰지 않는다. 호 중의 지시 칸은 비어 있고, 그 사이에 온 지시는 모두 `armed` 로 받아 호를 끊지 않는다. 끝에서: `end_place_id` 의 `armed`(만료 전) 지시가 있으면 그 지시의 회전 축은 이 끝 자리다(`pivot_basis: segment_end`, 기대 창·접근 없음) — `left`·`right` 는 정지 확인 뒤 회전(나가는 차로가 또 호면 (a)), `straight` 는 `exit_segment` 가 있으면 (b), 없으면 오늘의 `straight` 처럼 `executing` 으로 지나간다, `stop` 은 HOLD `junction_stop`, `turn_deg` 없는 `left`·`right` 는 `unresolved`. 지시가 없으면 오늘의 추종으로 돌아가고 이벤트 `nav.lane_arc_end_unarmed` 를 낸다. 다른 장소의 `armed` 지시는 `aborted`(`reason: arc_mismatch`, HOLD 아님)가 되고 지시 없는 끝과 같다. 장소와 무관하게 `armed` `stop` 은 HOLD `junction_stop` 이다. 호가 도는 동안 `action: bend` 는 409 `JUNCTION_ARC_RUNNING` 이고, 호 끝의 `armed` `bend` 는 다른 장소 지시처럼 `aborted`·`arc_mismatch` 다. 운동 허가는 매 틱 `motion_admitted(kind arc)`(IR `clear` 만)와 그 틱 호 twist 의 D-422 몸 sweep 이다. 후진은 없다. IR 한 번 보정(호 하나에 한 번): 호 시작 뒤 odom 0.03 m 안에서는 `left`·`right` 를 허가하고 보정을 열지 않는다(`centre` 는 멈춤); 유예 뒤 처음 판정이 유예 중 본 쪽과 같으면 `lane_arc_edge` 로 선다. 그 밖에 처음 `left`·`right` 가 보정을 연다: 속도 v·`ir_guard_speed_scale`, `away` 는 선 반대쪽으로 ω = g·v_c·κ ∓ v_c·`bridge_arm_max_curvature`(선이 왼쪽이면 음) 로 odom 0.12 m 간 뒤 확신 있는 `clear`(신선·교정된 IR 이 `visible: false`)여야 하고, `level` 은 반대 편향으로 odom yaw 가 호 기준 ψ₀ + κ·s 에 닿으면 끝난다(상한 0.18 m). 허가는 `away` 에서 그 쪽 또는 `clear`, `level`·보정 뒤에는 `clear` 만이다. 멈춤(HOLD, 호 기록 `stopped`, 다시 열지 않음, 다음 모드 변경까지): `lane_arc_edge`(`centre`, 보정 중 반대쪽 판정, `away` 끝이 확신 있는 `clear` 아님, `level` 중 판정 재등장, `level` 상한, 보정 뒤 두 번째 판정, 보정 중 구간 끝, 보정 한도 (0.12 + 0.18)/v_c + 2 s 초과), `obstacle_ahead`(D-422 sweep 미달), `lane_arc_pose_lost`(odom 이 `stale_after_s` 보다 낡음·끊김·epoch/frame 변경), `lane_arc_motion_unconfirmed`(스캔이 `clearance_stale_s` 보다 낡음, IR `stale`, 운동 허가 거절), `lane_arc_timeout`, `lane_arc_blind`(보정 없이 간 거리가 `arc_blind_max_m` 초과; step 1 은 호 전체), `lane_arc_entry`(step 2 예약), 그리고 오늘의 `angular_limit_zero`·`limit_level_too_low`·`linear_limit_zero`·`calibration_active`, 모드 변경·E-stop·운전자 hold. 상태는 `line_follow.arc {arc_seq, from_place_id, end_place_id, curvature_1pm, length_m, travelled_m, state: running\|ended\|stopped, reason, ir_correction: {side, phase: away\|level\|done, away_m, level_m, used}}`(이 프로세스의 마지막 호, 없으면 null). `reason` 은 끝이면 `segment_end`, 지시 없는 끝(다른 장소 지시 포함)이면 `lane_arc_end_unarmed`(Fleet 이 이 값으로 판정한다), 멈춤이면 그 사유다. D-491: 호를 열 자리에서 알려진 횡단보도 구역(CORE 가 영상으로 odom 에 고정한 구역)이 호 앞 `crosswalk_zone_max_m` 안에 걸치면 CORE 는 `exit_segment` 를 버리고 오늘처럼 동작한다(회전 뒤 `advance_m` 0.10 전진·재획득, 이어지는 `straight` 는 오늘의 통과). 그 지시의 `junction.reason` 은 `arc_crosswalk` 다. Fleet 은 `from_place_id` 가 보낸 장소와 같고 `arc_seq` 가 새로우면 그 지시를 `carried` 로 본다. `junction.pivot_basis` 값에 `segment_end` 를 더한다 |
| POST | `/api/v1/line-follow/authority` | Operator | D-517 4항 (M2, v1.143) — Fleet 이동 통행권 `{authority_id (1–128자), leg_id (1–128자), pose_stamp (> 0), until_m (0–10), ttl_s (0 < s ≤ 2)}`. 범위 밖·누락은 400 `VALIDATION_ERROR`. seat 는 `/junction` 과 같다(수동 조종 해제 409 `MODE_CONFLICT`, 보정 lease 409 `CALIBRATION_ACTIVE`). `until_m` 은 그 자세의 로봇 **앞 끝**(base + 몸 `front_x_m`)에서 통행권 끝까지의 거리다. CORE 는 base odom 주행 거리를 빼므로 앞 끝이 통행권 안에 남는다. `pose_stamp` 는 Fleet 이 계산에 쓴 자세의 CORE odom 시각으로, 스냅숏 `odom_pose.stamp` 와 같은 CORE 벽시계(UTC epoch 초)다. CORE 는 odom 표본마다 같은 벽시계 시각과 누적 경로 길이를 기록하고, `pose_stamp` 이전(같거나 이전)의 가장 새 표본부터 지금까지 odom 경로 길이(부호 없음: 후진도 남은 거리를 줄인다)를 `until_m` 에서 빼서 남은 거리를 낸다. 남은 거리가 D-422/D-424 몸체 정지 거리 d_stop(v)(`derived_stop_gap_m`, v = `max_linear`, line follow 가 낼 수 있는 가장 빠른 속도(D-468 복귀 포함, `cruise_speed` ≤ `max_linear`)) 이하가 되면 선다(`HOLDING`, 사유 `authority_end`). 다시 가려면 남은 거리가 d_stop(v) + `obstacle_resume_hysteresis_m` 보다 커야 한다. `ttl_s` 는 CORE line-follow 시계(`hold_s` 와 같은 시계)로 재고, 그 안에 새 통행권이 없으면 선다(`EXPIRED`, `authority_expired`). 통행권은 줄지 않는다: 같은 `leg_id` 이고 같은 odom 궤적이며 아직 만료되지 않은 통행권보다 끝이 0.02 m 넘게 짧으면 무시하고(응답 `accepted: false`, `reason: shrink`, 로그) 만료도 늦추지 않는다. 0.02 m 안에서 짧으면 쥔 끝을 그대로 두고 만료만 늦춘다(Fleet 지도 자세 잡음). 다른 `leg_id`, 만료 뒤, 또는 odom 궤적이 바뀐 뒤에는 새 통행권이 그대로 대신한다. 응답 `{accepted, reason, authority}`(`authority` 는 아래 상태). 거절: line-follow OFF 409 `LINE_FOLLOW_NOT_ACTIVE`, 409 `AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE` — 이 셋은 쥐고 있던 통행권도 버려서 로봇이 선다. 통행권 강제는 설정 `line_follow.authority_required: true` 이거나, 이 line-follow 세션에서 통행권 요청을 한 번이라도 받은 뒤(trip 구간이 선언함)에만 켜지고, 모드 변경·E-Stop 이 끝낸다. 꺼져 있으면 동작은 오늘과 같다. 켜져 있으면 유효한 통행권 없이는 선다(`NONE`, `authority_none`). odom 이 0.3 s 넘게 끊기거나 궤적이 바뀌면 선다(`HOLDING`, `authority_odom_stale`). 통행권 판정은 그 틱의 결정을 0 으로 만들 수만 있다: D-422 몸체 정지, D-491 IR 가드, E-Stop 은 먼저 결정을 0 으로 만들므로 언제나 앞선다. 통행권 때문에 0 이 된 틱의 상태는 HOLD 와 위 사유다 |
| POST | `/api/v1/line-follow/advice` | Operator | D-551 (v1.156, 표시만). D-525 신호 참고 `{advice_id (1–128자), leg_id (1–128자), seq (≥ 0), fleet_epoch (1–64자), pose_stamp (> 0, CORE가 준 odom 시각을 그대로 되돌림), ttl_s (0 < s ≤ 2), map_version?, route_rev?, signal: {signal_id, approach, stop_m (음수면 정지선 안), lamp: green\|yellow\|red, left_s?, green_in_s?, exact, may_enter} \| null}`. 응답 `{accepted, reason}`. 허가가 아니다: 차선 판정·통행권·교차로 판정이 읽지 않고 움직임을 만들지 않는다(차선 매니저 밖 저장소, import 검사 시험). 수동 조종 해제·보정 lease 를 요구하지 않고 line-follow 가 꺼져 있어도 받는다. 저장소는 하나이고, 만료 전·같은 `leg_id`·같은 `fleet_epoch` 항목보다 `(pose_stamp, seq)`가 같거나 오래되면 `accepted: false`, `reason: stale` 이다. 만료(CORE 단조 시계 `ttl_s`), 다른 구간, 다른 `fleet_epoch` 뒤에는 새 것을 받는다. `signal: null` 은 표시를 지운다. 틀린 본문은 400 `VALIDATION_ERROR`. 노출은 `GET /line-follow` 선택 키 `advice`(만료 전·신호가 있을 때만), 로봇 상태 스냅숏에는 넣지 않는다. 능력 `controls` `line_follow_advice`. 모르는 신호는 Fleet 이 `signal: null` 로 보낸다. odom 기록 대조(자세 409)와 속도 상한은 D-551 다음 단계(Safety-Review) |
| POST | `/api/v1/line-follow/stuck/decision` | `STUCK_DECIDE` (operator·administrator·`stuck_resolver`, D-438 v1.91) | D-407 §2 / D-453 — `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT\|YIELD}`. `YIELD` 는 선택 필드 `yield_m`·`yield_turn_rad` 가 둘 다 있어야 하고, 다른 결정에 그 필드가 있으면 400 `VALIDATION_ERROR`. 한 답은 한 구간이다. CORE 는 회전을 확인한 뒤 그 거리만 앞으로 기어 가고, 끝나면 `YIELDED` 로 서며 차선 추종을 재개하지 않는다. 다음 `YIELD` 가 다음 구간이다. 열린 막힘(`GET /line-follow` 의 `stuck`)에 대한 관제 답. `WAIT` 그대로 HOLD·로컬 복구 안 함; `RESUME` 앞물체 정지를 한 번 풀어 `obstacle_stop_m` 까지 접근 허용·LOST 해제 후 차선 추종 재개; `BACK_AND_RETRY` 짧은 후진과 재판단을 즉시(로컬 복구가 켜져 있어야 함); `MANUAL` 차선 추종 OFF + MANUAL(D-342 한도); `ABORT` 차선 추종 OFF + IDLE. 응답은 line-follow 상태 + `outcome`(`hold\|back\|resume\|manual\|idle\|yield`). `RESUME`·`BACK_AND_RETRY`·`MANUAL`·`YIELD` 는 보정 lease 를, `RESUME`·`BACK_AND_RETRY`·`YIELD` 는 E-Stop 을 지킨다. `MANUAL`·`ABORT` 의 모드 전이는 `POST /mode` 와 같다(`MANUAL` 은 navigation·swarm 취소, `mode.changed`). 409 `STUCK_ID_MISMATCH`·`STUCK_DECISION_REFUSED`·`CALIBRATION_ACTIVE`·`EMERGENCY_ACTIVE`. 운용자 Fleet 경로의 다섯 단어와 추가 필드 422 는 그대로다 (v1.74, YIELD 는 v1.95) D-573 4 (v1.179): `cause: crosswalk_blocked` 에는 `WAIT`·`MANUAL`·`ABORT` 만 받는다. `RESUME`·`BACK_AND_RETRY`·`YIELD` 는 409 `STUCK_DECISION_REFUSED`(`crosswalk_gate`). |
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
| GET | `/api/v1/localization/request` | `LOCALIZE_ASSIST` | D-546 5 (v1.163, 제안) — lane_return 이 위치 증거가 없어 못 갈 때(`pose_stale` 이 1 s 이상, 또는 `fleet_required`) CORE 가 여는 "내 위치를 알려 달라" 요청 하나. `{request_id, robot_id, reason: pose_stale\|fleet_required, created_at(CORE 벽시계 초), age_s, ttl_s(기본 30), evidence {phase, odom_pose {x, y, yaw, frame, stamp_ns, age_s}\|null, lane {visible, confidence, error, quality_reason, stamp}\|null}}`. 같은 사유면 `request_id`·`created_at` 이 유지되고 증거만 갱신된다. 요청이 없거나 `ttl_s` 가 지났으면 404 `NO_REQUEST`(다음 틱에 새 `request_id` 로 다시 열린다). 답은 기존 `POST /localization/decision` 이다(`request_id` 를 그대로 싣고 `source: overhead\|candidate`, `ttl_s`). 로봇의 3 s 스캔 확인이 통과해 `localization.result` `accepted` 가 오고 그 `request_id` 가 열린 요청의 것이며 Fleet 이 보낸 결정일 때만 요청이 닫히고(사람의 initialpose·homing 결과는 닫지 않는다) `fleet` 단계의 lane_return 이 D-407 RESUME 으로 차선 확인을 다시 연다. 요청 중 로봇은 HOLD 로 기다린다 |
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
| GET | `/api/v1/map` | Viewer | MAP-003 (응답의 `map_id`는 해당 점유 지도 스냅숏을 수신할 때 묶인 ID. 이후 로봇 상태의 `map_id`가 바뀌어도 이전 격자에 새 ID를 붙이지 않음) |
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
| POST | `/api/v1/swarm/follow` | Operator | SWM-002 `{target_robot_id, distance, lateral, max_speed, stream_timeout_ms, source, members, mode}`. `mode: offset(기본)\|trail` (D-559, v1.170): `trail` 은 리더가 실제로 지나간 자취를 `distance`(자취 위 경로 거리) 뒤에서 CORE 가 직접 조향해 따라간다 — Nav2 목표를 내지 않고, 그 동안 Nav2 twist 는 버린다. `trail` 에서 `lateral` ≠ 0 은 400 `VALIDATION_ERROR`. 응답의 `mode` 가 `trail` 이 아니면 그 로봇은 trail 을 모른다(옛 CORE 는 필드를 버리고 offset 으로 따라간다). 첫 리더 표본이 1.5 m 넘게 떨어져 있으면 follow 를 끝내고 `swarm.aborted`(`reason: trail_join_too_far`)를 낸다. `source: fleet(기본)\|peer(예약, D-21 — 요청하면 501)`. `members` 는 대형 명단을 `robots.yaml` 순서로 — 비어 있으면 리더 승계를 하지 않고, 있으면 리더 상실 시 `swarm.succession` 을 낸 뒤 follow 를 끝낸다. `max_speed` 는 SAF-004 상한을 넘으면 400 이고, 추종 구간 동안 실제 상한으로 적용된다 — Nav2 가 무엇을 내보내든 `cmd_vel` 은 이 값으로 클리핑된다(D-31). 적용 중인 값은 `GET /safety/state` 의 `limits.session_linear` 에 보인다. 미지원 로봇은 501 `CAPABILITY_NOT_SUPPORTED` (SWM-005/CAP-003), 도킹/언도킹 중에는 409 `DOCKING_ACTIVE`, 맵핑 세션 중에는 409 `MAPPING_ACTIVE`, E-Stop 중에는 409 `EMERGENCY_ACTIVE`. 추종 중 `POST /navigation/cancel` 이나 MANUAL 전환은 대형을 끝내고 `swarm.aborted` 를 낸다 |
| POST | `/api/v1/swarm/cancel` | Operator | SWM-002 |
| GET | `/api/v1/swarm/state` | Viewer | SWM-006 — `{role, formation, active, holding, target_robot_id, source, max_speed, map_mismatch, mode, trail, stream_age_s}`. `mode`·`trail` 은 D-559 (v1.170): `trail` 은 trail 모드에서 자취가 생긴 뒤 `{leader_s, progress, hold_reason, anchor}`(`anchor` 는 D-581 v1.176: Fleet 천장 기준 odom 자취면 `fleet`, 아니면 null)(경로 거리 m; `hold_reason` 은 아래 `swarm.hold` 의 trail 사유, `stream_lost`, `map_mismatch`, `waiting_for_leader` 또는 null), 아니면 null. `map_mismatch` 는 거부 중인 리더의 `map_id` 다. 상태 스냅샷의 `swarm` 필드는 그중 `role`·`formation`·`active` 다 |
| GET | `/api/v1/calibration/session` | Viewer | D-321 부록 (v1.68) — `{session: Session\|null}`. `Session` = `{id, kind, label, owner: {id, role, label}, started_at, ttl_s, elapsed_s, remaining_s}`. `owner.id` 는 `GET /auth/whoami` 의 `id` 와 같은 불투명 토큰 id |
| POST | `/api/v1/calibration/session` | Operator | `{kind, label?, ttl_s?}` → 201 `{session}`. 모드가 IDLE·MANUAL 이 아니거나 navigation·도킹·line-follow·swarm 이 돌고 있으면 409 `MODE_CONFLICT`. `kind` 는 `^[a-z][a-z0-9_]{0,31}$`(알려진 값 `drive`·`camera`·`imu`·`ir`·`lidar`·`odometry`), `label` ≤ 80자(비면 `kind`), `ttl_s` 5–300(기본 30). 호출 토큰이 owner 가 된다. 세션은 로봇당 하나 — 이미 있으면(같은 토큰이어도) 409 `CALIBRATION_ACTIVE` + `detail.session` |
| POST | `/api/v1/calibration/session/{id}/heartbeat` | Operator | owner 만. `ttl_s` 를 다시 채운 `{session}`. 다른 토큰 403 `FORBIDDEN`, 없거나 만료된 id 404 `NOT_FOUND`. `ttl_s` 안에 heartbeat 가 없으면 세션은 만료되고 `calibration.session_expired` 가 한 번 발행된다 |
| DELETE | `/api/v1/calibration/session/{id}` | Operator | owner 또는 Admin(걸린 lease 강제 해제). 끝난 `{session}`. 그 밖의 토큰 403, 없는 id 404 |
| PUT | `/api/v1/trip-lease` | Operator | D-541 1–2 (v1.157) — `{lease_id (^[A-Za-z0-9_.:-]{1,64}$), trip_id (1–128자), holder (Fleet 사이트, 1–64자), operator_name (trip 을 시작한 이름 있는 운영자, 1–64자), ttl_s (1–10, 기본 5)}` → 200 `{trip_lease, renewed}`. `trip_lease` = `{lease_id, trip_id, holder, operator_name, since, expires_in_s}`. lease 가 없으면 열고(호출 토큰이 주인), 같은 토큰·같은 `lease_id` 면 만료를 `ttl_s` 로 다시 채운다(renew, `renewed: true`). 다른 `lease_id`(같은 토큰이어도) 또는 다른 토큰 409 `TRIP_LEASED`. 열 때만 거절: 보정 세션이 있음 409 `CALIBRATION_ACTIVE`(보정과 trip lease 는 서로 배타. **같은 토큰의 보정 세션도 막는다** — D-541 2항의 "다른 토큰"보다 엄격한 fail-closed 선택), E-stop 409 `EMERGENCY_ACTIVE`, MANUAL 모드 409 `MANUAL_MODE`, DOCKING 모드 409 `MODE_CONFLICT`(도킹이 바퀴를 쥐고 있다). 이미 끝난 `lease_id` 로 부르면(넘겨받기·만료·주인 아닌 멈춤·release 뒤의 renew) 다시 열지 않고 404 `NOT_FOUND` + `detail.ended {lease_id, reason, by}` 다(D-541 7: 잃은 lease 는 되살리지 않는다; CORE 는 끝난 id 를 최근 1024개 기억한다). 새 `lease_id` 는 보통대로 연다. 값 밖 400 `VALIDATION_ERROR`. 상태는 메모리에만 있다(CORE 재시작이면 lease 없음). `ttl_s` 안에 renew 가 없으면 CORE 5 Hz 타이머가 lease 를 끝내고(`expired`) line-follow 를 끄고 내비게이션을 취소해 IDLE 로 둔다. 만료를 타이머가 처리하기 전까지(≤ 0.2 s) 지난 lease 도 주인 아닌 쓰기를 막는다 |
| DELETE | `/api/v1/trip-lease/{lease_id}` | Operator | D-541 1 (v1.157) — 주인 토큰의 정상 끝(`released`). 로봇을 멈추지 않는다(Fleet 이 먼저 `stop`/취소를 보낸다). 200 `{trip_lease_ended}`. 다른 토큰 403 `FORBIDDEN`. 없거나 끝난 lease 404 `NOT_FOUND`, 바로 앞에 끝난 그 lease 면 `detail.ended {lease_id, reason, by}` — Fleet renew 가 404 를 받았을 때 끝 이유를 읽는 자리다 |
| POST | `/api/v1/trip-lease/takeover` | Operator | D-541 4 (v1.157) — `{lease_id, reason? (≤ 200자)}`. 주인 아닌 토큰의 명시적 넘겨받기: 같은 처리 안에서 lease 를 끝내고(`taken_over`, `by` = 넘겨받은 토큰의 라벨, 없으면 역할) line-follow 를 끄고 내비게이션을 취소해 IDLE 로 둔다. 200 `{trip_lease_ended, mode}`. MANUAL 은 그다음 `POST /mode` 로 따로 요청한다. 주인이 부르면 400(주인은 `DELETE`), 다른·끝난 `lease_id` 404(`detail.ended` 는 DELETE 와 같다), Viewer 403 |
| GET | `/api/v1/fleet/link` | Viewer | D-555 (v1.163) — `{configured, provisioned, expected_hostname, hub_url, enabled, connected, fleet_goal_active, arm_state, arm_deadline_s}`. `arm_state`: `armed`(WELCOME 받음, 또는 relink 없음) \| `pending`(relink 뒤 첫 WELCOME 대기, `arm_deadline_s` 남은 초) \| `grace_expired`(35 s 안에 WELCOME 없음 — SAF-003 이 끊긴 링크로 센다). 허브 페어링 토큰은 어떤 응답에도 싣지 않는다 |
| PUT | `/api/v1/fleet/link` | Admin 또는 사이트 등록 토큰 | D-555 3 (v1.163) — CORE 자신의 TLS 리스너(`https` + `network.tls`)로 온 요청만; 아니면 403 `TLS_REQUIRED`. Fleet 목표(`navigation/goal` + `correlation_id`)가 진행 중이면 409 `FLEET_GOAL_ACTIVE`. 기동 때 잘못된 Fleet·SAF-003 설정을 기본값으로 대신했으면 409 `FLEET_LINK_CONFIG_INVALID`. 새 링크는 허브의 첫 WELCOME 또는 relink 뒤 35 s(`FLEET_LINK_ARM_GRACE_S`) 중 먼저 오는 때부터 SAF-003 `fleet_link.configured` 다. 호출자는 관리자, 또는 화면 코드(`pair-physical`·`pair-admin`)로 받은 운영자 토큰 중 라벨이 `site:` 로 시작하는 것(Fleet 등록 토큰. 라벨은 인증이 아니다). 공용 개발 토큰과 그 밖은 403 `FORBIDDEN`. `{pairing_token (32–256자, [A-Za-z0-9_-]), expected_hostname (<name>.local), ca_pem (PEM 인증서, ≤ 16 KiB)}` → 비밀 덮어쓰기 `~/.rosy/fleet-link.yaml`(`ROSY_FLEET_LINK`, 0600)과 CA `fleet-link-ca.pem` 을 쓰고 FleetAgent 만 다시 시작한다(발견 프로필, D-452). 이 파일의 `fleet` 링크 키가 모든 층 위에 온다. 200 은 GET 과 같다. 틀린 본문 400 `VALIDATION_ERROR`(입력을 되돌리지 않도록 필드 detail 없음). 사건 `fleet.link_provisioned`. 능력: `GET /system/capabilities` 최상위 `fleet_link_provisioning: true` |
| DELETE | `/api/v1/fleet/link` | PUT 과 같음 | D-555 6 (v1.163) — Fleet 목표 중이면 409 `FLEET_GOAL_ACTIVE`. 비밀 파일과 CA 를 지우고 아래 층(덮어쓰기 파일을 뺀 `load_config`)의 링크(있으면)로 FleetAgent 를 다시 시작한다. 200 `{…GET, removed}`. 사건 `fleet.link_cleared` |
| POST | `/api/v1/safety/stop` | Viewer↑ | SAF-001 (누구나). 보정 세션 중에도 막지 않는다 |
| POST | `/api/v1/safety/release` | Admin | SAF-001. 어떤 경로의 래치든(API, control 정책, SAF-005 `battery_policy`·`battery_deep`) E-Stop 은 모드 EMERGENCY 와 함께 걸리므로 이 경로로 풀린다. EMERGENCY 가 아니면 409 `MODE_CONFLICT`. 배터리 래치는 전압이 회복되어도 스스로 풀리지 않는다. 해제는 배터리 정책을 끄지 않으며 Deep 이 이어지면 다음 표본에서 다시 래치한다. 어떤 출처의 E-Stop 이든 배터리 자동 복귀(도크 복귀·`RETURN_HOME`)를 배터리 단계가 OK 로 돌아올 때까지(복귀 히스테리시스 포함) 끄고, 해제는 래치 중 무장된 복귀를 지우며, 그 사이 Critical 통과는 다시 래치한다 — 해제 뒤 로봇은 새 명령 없이 움직이지 않는다(D-502, v1.120) |
| GET | `/api/v1/safety/state` | Viewer | SAF-001. `battery` 는 정책 `{warning_percent, critical_percent, deep_percent, critical_policy}` 와 지금의 근거 `{evidence, sample_age_s, level, percent}`(D-502, v1.120 additive) — `evidence` 는 `missing`\|`fresh`\|`stale`, `level` 은 `ok`\|`warning`\|`critical`\|`deep`, 표본이 없으면 `sample_age_s`·`percent` 는 `null`. `source: battery_policy`\|`battery_deep` 래치를 풀기 전에 관리자는 `evidence: fresh` 와 `level` 을 본다. `fleet_loss_policy` 와 선택 필드 `fleet_link` (SAF-003, D-419, v1.86) `{configured, connected, lost, timeout_s, applied, correlation_id, disconnected_s, held_goal}` — `configured` 는 FleetAgent 가 돌고 있는가(승인된 `pairing_token` + 주소), `lost` 는 이번 단절에서 정책을 적용했는가, `applied` 는 실제로 한 것(`STOP`·`HOLD`·`RETURN_HOME`·`CONTINUE`·`NONE`), `held_goal` 은 `HOLD` 가 보관한 `{correlation_id, x, y, yaw}`(재접속 이벤트 뒤 비움). 서비스가 없으면 `null` |
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
| POST | `/api/v1/host/lamp/identify` | Operator | D-472 (v1.129), `{color?:"blue"\|"amber"}`. v1.185(D-596): 쿼리 `?quiet=true`면 같은 점멸을 호출음(두 번 삑) 없이 한다(rosy-hw-test·rosy-face 동작 `identify_<색>_quiet`, 다음 로봇 payload부터). `color`를 빼면 이 로봇의 설정 색 (CORE 설정 `lamp_identify.color`, 없으면 D-472 4항 기본 `rosy_26` blue·`rosy_60` amber(주황)); 둘 다 없으면 409 `IDENTIFY_COLOR_UNSET`. CORE는 식별 요청만 기록하고(`requested_at` ms) 후면 램프는 `rosy-face`만 구동한다: 1 s 켬→1 s 끔→1 s 켬, 3.5 s에 강제 종료. 요청부터 끝까지 6 s 이내: `rosy-hw-test`는 1.5 s, `rosy-face`는 1 s보다 오래된 식별 요청을 버린다. 정상 패턴(ready·manual·navigating·docking·illumination) 위에서만 켠다 — 움직이는 로봇 포함(addendum 5항). E-Stop·EMERGENCY·고장·주의·booting·blocked 또는 CORE 인계가 없으면 즉시 `failed`로 거절하고, 점멸 중 그렇게 되면 끊고 상태 패턴으로 돌아간다. 바퀴·모드·E-Stop·localization은 바꾸지 않는다. 200 `{accepted:true, request_id, color, state:"pending_visual_confirmation"}`는 영상상 식별 성공을 뜻하지 않는다. 결과는 `GET /host/hardware`의 `test`. 기존 `HW_TEST_COOLDOWN`/`HW_TEST_UNAVAILABLE` 거절을 공유한다. |
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
- 토픽: `camera/front/compressed`(녹화 중에만 발행), `cmd_vel`, `odom`, `scan`, `line/observation`, `teleop/intent`, `line/keep_debug`, `ir_sensor/range`(`std_msgs/UInt16MultiArray`, 로봇 기준 좌·중·우 원시 ADC 0–4095). 초음파 `us_sensor/range` 는 넣지 않는다.
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

`odom_pose` 는 v1.112 additive 다(D-494 2). `{x, y, yaw, stamp}` 는 로봇 odom 프레임의 자세와 CORE 가 그 odom 메시지를 받은 시각(ROS 헤더 시각이 아님)이다. 유한하지 않은 표본은 버리고 이전 값을 둔다. `stamp` 는 UTC epoch 초(실수)로, sighting 의 `captured_at` 과 같은 형식이다(로봇 단조 시각이 아니다). `pose` 가 map 프레임이어도 같이 싣는다. odom 이 한 번도 오지 않은 로봇과 D-494 이전 로봇은 `null` 이다. odom 이 끊겨도 마지막 값이 남으므로 소비자는 `stamp` 로 신선도를 판단한다. 같은 값이 Fleet 하트비트(1 Hz)의 상태 스냅샷에도 실린다.

```json
"odom_pose": { "x": 1.204, "y": -0.311, "yaw": 1.57, "stamp": 1791374400.123 }
```

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

`trip_lease` 와 `trip_lease_ended` 는 v1.157 선택 필드다(D-541 1). **없으면 키가 없다**
(`null` 이 아니다). `trip_lease` `{lease_id, trip_id, holder, operator_name, since,
expires_in_s}` 는 Fleet trip lease 가 살아 있는 동안만 있다. `trip_lease_ended
{lease_id, reason, by}` 는 lease 가 끝난 뒤 10 s 동안(다음 lease 가 열리면 없어진다)
있어 1 Hz heartbeat 와 `/ws/state` 가 모두 한 번은 본다. `reason` 은 `mode_left`(IDLE·
MANUAL·도킹으로 감, D-407 ABORT, 주인 아닌 토큰의 `navigation/cancel`·line-follow OFF)·
`estop`·`taken_over`·`expired`·`released` 다. 주인의 NAVIGATION ↔ line-follow 전환(trip 의
`lane` ↔ `free`)은 lease 를 끝내지 않는다: lease 주인의 `navigation/goal` 은 line-follow 가
켜져 있어도 받아 line-follow 를 끄고 목표로 간다(주인이 아니면 그대로 409
`LINE_FOLLOW_ACTIVE`).

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
               "map_id": "site_a", "frame": "map" } }
```

Follower의 rosy_core은 스트림 수신 여부를 `stream_timeout_ms`(기본 1000 ms)로 감시하고 단절 시 SWM-004 정책(HOLD)을 적용한다.

`frame` 은 v1.170 additive 다(D-559): `map` 또는 `odom`. 리더의 map TF 가 2 s 넘게 끊기면 보고 pose 는
odom 으로 떨어지는데, 그 좌표는 맵의 장소가 아니다. trail 팔로워는 `odom` 표본을 자취에 넣지 않고 멈춘다
(`hold_reason: reference_frame_not_map`). 아직 pose 가 없는 CORE 는 `null` 을 보낸다. trail 은 `map` 표본만 쓴다 — 필드가 없는 옛 리더도 trail 에서는 멈춘다(offset 은 확인하지 않는다).

`anchor`·`for_robot_id`·`anchor_age_s`·`anchor_hold` 는 v1.176 additive 다(D-581). TRAIL 대형에서 리더가 `frame: odom` 을 보내면
(로봇에 map pose 가 없는 모터 모드 현장) Fleet 은 그 프레임을 팔로워마다 **그 팔로워의 odom 좌표로** 다시 써서 보낸다:
`frame: odom`, `anchor: "fleet"`, `for_robot_id: <받는 팔로워>`, `map_id`(천장 카메라 사이트 맵), `anchor_age_s`(리더·팔로워
천장 기준 중 오래된 쪽, s — 진단용이며 CORE 는 읽지 않는다). 변환은 D-494 3 Fleet map pose 의 천장 기준(map ← odom)이다. 천장 기준이
없거나 5 s 넘게 낡았거나, DEGRADED 가 2 s 를 넘었거나(또는 T 를 만든 기준이 바뀌었거나), 추적기 odom 이 재시작했거나, 기준이 로봇
위치에서 0.20 m·15° 넘게 튀었거나, 리더 스트림 odom 이 추적기 odom 과 맞지 않으면(`leader_odom_mismatch`) 그 팔로워에게는 쓸 수 있는
표본 대신 **정지 표본** `anchor_hold: "<robot>:<이유>"`(좌표는 리더 odom 그대로, 자취에 들어가지 않는다)을 리더 프레임마다 보낸다 —
침묵은 리더 상실(D-20 승계)로 읽히기 때문이다. 리더 프레임이 끊기면 Fleet 도 아무것도 보내지 않는다. `map` 프레임은 지금처럼 바이트 그대로 중계한다. trail 팔로워는 `anchor: fleet` 이고
`for_robot_id` 가 자기 id 이고 `frame: odom` 이고 follow `source` 가 `fleet` 인 표본만 자취에 넣고, 그때 자기 위치는 상태
스냅샷의 `odom_pose` 다(`own_pose_not_map` 판정 없음, CORE 가 받은 지 단조 시계로 0.5 s 넘으면 `own_pose_stale`). 조건이 맞지 않는 `anchor` 표본은
`reference_anchor_invalid` 로 선다. `anchor_hold` 표본은 `anchor_withheld` 로 세우되 스트림은 살아 있다(승계 없음). 정지 표본마다
D-559 건너뜀 한도의 시계가 다시 시작되므로, 긴 정지 사이 리더가 0.3 m 넘게 갔으면 다음 표본은 `trail_lost` 다. `anchor`·`for_robot_id`
는 길 찾기 검사이지 인증이 아니다 — operator 토큰이면 이 소켓에 넣을 수 있다(map 프레임 trail 과 같다). 한 자취는 처음 쌓인 종류(map 또는 fleet)만 받는다 — 다른 종류 표본은
`reference_frame_changed` 로 서고 follow 를 다시 걸 때까지 유지된다. `anchor` 표본의 `map_id` 는 로봇 자신의 `map_id` 와
비교하지 않는다(아래 `map_mismatch` 는 `anchor` 없는 표본에만 적용).

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
| `auth.development_mode` | warning | 로봇 | `{marker}` — 장치 모드인데 개발 모드 표식이 있어 공용 개발 토큰을 받는다(D-548) |
| `fleet.link_provisioned` | warning | 로봇 | `{by, expected_hostname}` — D-555 (v1.163). `by` = 호출 토큰 id. 토큰은 싣지 않는다 |
| `fleet.link_cleared` | warning | 로봇 | `{by, removed}` — D-555 (v1.163) |
| `mode.changed` | info | 로봇 | `{from, to, by}` |
| `trip_lease.opened` | info | 로봇 | `{lease_id, trip_id, holder, operator_name, ttl_s}` — D-541 (v1.157) |
| `trip_lease.renewed` | info | 로봇 | `{lease_id, trip_id, ttl_s}` — renew 는 0.5 s 마다 오므로 lease 하나에 30 s 에 한 번만 낸다 (v1.157) |
| `trip_lease.ended` | info, warning | 로봇 | `{lease_id, trip_id, holder, operator_name, reason, by, note}` — `reason` `released` 는 info, 그 밖(`mode_left`·`estop`·`taken_over`·`expired`)은 warning. `note` 는 넘겨받기 `reason`(없으면 빈 문자열) (v1.157) |
| `trip_lease.shared_token` | warning | 로봇 | `{lease_id, trip_id, holder, use, origin}` — lease 주인 토큰이 Fleet 밖에서 쓰인 흔적: `use: teleop`(trip 은 teleop 하지 않는다, `origin` 빈 문자열) 또는 `use: ws_state`(lease 를 연 주소와 다른 `origin` 의 `/ws/state`). lease·쓰임·출발지마다 한 번 (v1.157) |
| `calibration.session_started` | info | 로봇 | `{session_id, kind, label, owner, ttl_s}` — `owner` 는 토큰 id (D-321 부록, v1.68) |
| `calibration.session_ended` | info | 로봇 | `{session_id, kind, owner, by, duration_s}` — `by` 는 끝낸 토큰 id(Admin 강제 해제면 owner 와 다름) (v1.68) |
| `calibration.session_expired` | warning | 로봇 | `{session_id, kind, owner, ttl_s}` — `ttl_s` 안에 heartbeat 가 없어 lease 가 풀림. 보정 도구가 죽었거나 링크가 끊겼다는 신호 (v1.68) |
| `nav.started` | info | 로봇 | `{goal, by, correlation_id}` — `goal` 은 `{x, y, yaw}`; Fleet가 dispatch 시도 ID를 보낸 경우 그 값, 아니면 `null` |
| `nav.completed` | info | 로봇 | `{correlation_id}` — 동일 dispatch 시도 ID 또는 `null` |
| `nav.failed` | error | 로봇 | `{error_code, correlation_id}` — 동일 dispatch 시도 ID 또는 `null` |
| `nav.canceled` | info | 로봇 | `{source, correlation_id}` — 로컬 취소 요청을 냈다는 뜻이며 액션 완료나 물리 정지를 증명하지 않는다 |
| `nav.stuck` | error | 로봇 | `{timeout_s}` — NAV-006 무진척 판정 시간(초) |
| `nav.lane_lost` | warning | 로봇 | `{mode, reason, lost_after_s}` (NAV-007 차선 상실 — 유예 `lost_after_s` 초과 시 정지, 자동 재탐색 없음. CAMERA_LINE은 D-407 개정 2026-10-10에 따라 차선이 다시 보이면 같은 모드로 이어 감, `nav.lane_reacquired`) |
| `nav.lane_reacquired` | info | 로봇 | `{mode, frames, since_s}` — D-407 개정 2026-10-10: CAMERA_LINE `LOST`(`camera_reselection_required`)가 `line_follow.lost_resume_frames`(3)개 연속 신선·확신 프레임이 `lost_resume_s`(1.0 s) 넘게 이어지고 앞 물체 정지가 없으며 IR 감시가 비어 있을 때 풀려 같은 모드로 이어 감(재선택 없음). `lost_auto_resume: false`면 옛 잠금 (v1.181) |
| `nav.line_mode_changed` | info | 로봇 | `{from, to}` — D-143 line-follow 모드 선택 |
| `nav.line_driver_released` | info | 로봇 | `{mode}` — D-344 §8 운전자 확인(`hold_s`)이 끊겨 CORE 가 line-follow 를 스스로 내림 (v1.63) |
| `nav.line_obstacle_hold` | warning | 로봇 | `{mode, clearance_m, held_s}` — D-344 §11 앞 물체 정지(`obstacle_ahead`)가 `line_follow.obstacle_escalate_s` 넘게 이어짐, 정지 한 번에 한 번 (feat/device-prep, v1.64). 몸 기준 정지(D-422)면 `body_gap_m`·`stop_gap_m`·`clearance_source` 도 온다 (v1.84) |
| `nav.lane_arc_end_unarmed` | warning | 로봇 | `{end_place_id, arc_seq, travelled_m}` — D-520 2 호(`line_follow.arc`)가 odom 길이로 끝났는데 `end_place_id` 의 `armed` 지시가 없거나(만료 포함) 다른 장소의 지시였음(그 지시는 `aborted`·`arc_mismatch`). CORE 는 오늘의 차선 추종으로 돌아간다 (v1.145) |
| `nav.line_stuck_opened` | warning | 로봇 | `{stuck_id, cause, front_clearance_m, rear_clearance_m, rear_state, turn_clearance_m, rear_blind_m, last_lane, preview_seq, restuck_of, attempts}` — D-407 §1 막힘 열림: `cause` 는 `obstacle_ahead`(앞물체 정지가 `obstacle_escalate_s` 이상) 또는 `lane_lost`. 여유는 로봇별 self-mask 적용, 앞은 LiDAR 기준 경로 띠, 뒤는 URDF 몸 뒤끝 기준, 회전은 회전 반경 밖; `rear_blind_m` 은 LiDAR `range_min` 때문에 안 보이는 뒤 거리. 같은 막힘에 한 번 (v1.74) D-573 4 (v1.179): `cause` `crosswalk_blocked` 는 횡단보도 게이트가 `crosswalk_report_s`(기본 10 s) 동안 "비었다"를 증명하지 못했거나 무장한 횡단보도 앞에서 앞물체 정지가 길어진 때다. 이때만 `detail`(`person_present`·`look_unknown`·`sensor_stale`·`zone_lost`)이 붙고, 로컬 후진 없이 관제 답만 기다린다(`nav.line_stuck_asked` `reason: crosswalk_gate`, `decisions` `[WAIT, MANUAL, ABORT]`; status `stuck.detail`·`stuck.decisions` 도 같다). 게이트가 스스로 비었음을 확인하면 `cleared` 로 닫힌다. 2026-10-10 (v1.187): `cause` `no_motion` 은 활성 차선 모드에서 line-follow 결정이 `line_follow.stuck_report_s`(기본 5 s, 0 = 끔) 동안 0 이고 다른 원인이 없을 때다(사유 무관: `lane_departure`, `angular_limit_zero`, `obstacle_sensor_stale`, `nominal_ground_requires_driver` 등). `detail` 은 그 HOLD 사유다. 로컬 후진 대체 없이 곧바로 관제 답만 기다린다(`nav.line_stuck_asked` `reason: no_motion`, `ask_remaining_s` null). 다섯 답은 다른 원인과 같고 CORE 가 다시 검사한다. 명령이 다시 0 이 아니면 `cleared` 로 닫힌다. D-520 arc·D-468 로컬 복귀가 틱을 가진 동안과 저조도·과노출 HOLD 는 세지 않는다. |
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
| `localization.request` | info | 로봇 | `{request_id, reason}` — lane_return 이 위치 요청을 열었다(v1.163). 같은 사유의 갱신은 다시 내지 않는다 |
| `localization.request_cleared` | info | 로봇 | `{request_id, why}` — 요청이 닫혔다(v1.163). `why`: `answered`(수락된 결정), `lane_return_resumed`, `line_follow_reset`. `ttl_s` 만료는 이벤트 없이 사라진다 |
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
| `swarm.role_assigned` | info | 로봇 | `{role, formation, target_robot_id, mode, reference_source, by}` — `mode` 는 D-559 (`offset`\|`trail`) |
| `swarm.hold` | warning | 로봇 | `{reason, formation, stream_timeout_ms, reference_map_id, map_id}` — `reason`: `reference stream lost`(+`stream_timeout_ms`) \| `map_mismatch`(+`reference_map_id`, `map_id`) \| D-559 trail (v1.170): `trail_lost`(자취에서 0.30 m 넘게 벗어났거나 리더가 표본 사이에 0.3 m + SAF-004 `max_linear` × 경과 시간(최대 1.5 m)보다 멀리 건너뜀, follow 를 다시 걸 때까지 유지) \| `reference_frame_not_map` \| `own_pose_not_map` \| `own_pose_stale`(자기 pose 가 0.5 s 넘게 갱신되지 않음 — map 자취는 map pose, D-581 Fleet 기준 자취는 `odom_pose`) \| `obstacle`(D-422 몸체 정지, 멈춘 판정의 재개 거리를 넘어야 다시 간다) \| `obstacle_sensor_stale` \| D-581 (v1.176): `reference_anchor_invalid`(`anchor` 표본이 이 로봇 몫이 아니거나 `frame: odom` 이 아님) \| `reference_frame_changed`(map 자취에 Fleet 기준 표본, 또는 그 반대 — follow 를 다시 걸 때까지 유지) \| `anchor_withheld`(Fleet 이 `anchor_hold` 정지 표본을 보냄, 스트림 유지) |
| `swarm.aborted` | warning | 로봇 | `{formation, reason, robots, by}` — `reason`: `canceled` \| `estop` \| `docking` \| `stuck` \| `manual` \| `navigation_canceled` \| `localization`(D-395 로봇이 `LOCALIZED` 를 벗어남, v1.72) \| `trail_join_too_far`(D-559, v1.170) |
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
- `base_velocity` trip 필드(v1.112 additive, D-494 1, 선택): `robot_kind` 는 로봇 패키지 이름(`robot.model`, 없으면
  CORE 기본 로봇 패키지; 예 `pinky_pro`)이다. `drive_modes` 는 Fleet trip 에 쓸 수 있는 주행 방식 목록이다 — CORE 가
  line-follow 서비스를 가지면 `lane`, 같은 응답의 `navigation.goal_navigation` 이 참이면 `free`(보류 뒤 값)다. 둘 다 없으면
  `[]` 이다. `trip_max_linear`(m/s, ≥0)는 로봇이 trip 에 허용하는 최고 속도로, `safety` 의 `max_linear`·`fleet_linear` 와
  line-follow 가 있을 때 그 `max_linear` 중 가장 작은 값이다. `junction_turn`(bool, D-495)은 CORE line-follow 가 교차로의
  제한된 회전 동작을 지원할 때 `true` 다(지원하지 않으면 `false`, 없으면 지원하지 않는 것으로 읽는다). 지원은 읽을 때마다 다시 판단한다: keep 모드 교차로 감지 증거와 회전의 운동 근거가 함께 있어야 한다. 운동 근거는 D-400 enforce 바닥 증명이거나, D-498/D-507 6 현장 근거(`line_follow.site_floor_map_id` 선언 + `ir_guard_enabled` 의 신선한 IR 가드 판정(이탈 아님) + `obstacle_mode: path`·URDF 몸 + 신선한 스캔의 D-422 몸체 정지)다 (v1.118, v1.126). `site_floor_map_id`(문자열, D-507 9, v1.126)는 로봇의 현장 바닥 선언, 곧 걸어서 확인한 지도의 `SiteMap.map_id`다. 선언이 없으면(설정 null) 필드가 없다. Fleet 은 이 값이 활성 지도의 `map_id`와 다른 로봇의 `lane` trip 을 열지 않는다. `junction_pivot`(bool, D-507 2항, v1.127)은 CORE 가 `POST /line-follow/junction` 의 `map_id`·`expect_in_m`·`expect_tol_m`·`pivot_past_line_m` 를 받고, 최근 2 s 안에 받은 `line/keep_debug` 프레임이 표지 `junction_ahead_v`(정수 ≥ 1, 인식이 모든 프레임에 싣는다)를 실었을 때만 참이다(`junction_turn` 의 `corner_turning` 과 같은 창). 표지가 끊기면 다시 거짓이다. 없거나 거짓이면 Fleet 은 그 필드를 보내지 않는다. `lane_bend`(bool, D-507 보충, v1.142)는 CORE 가 `POST /line-follow/junction` 의 `action: bend` 와 `bend_in_m`·`bend_tol_m`·`bend_radius_m` 를 받을 때 참이다(D-400 증명이 살아 있으면 그 증명이 구성됐을 때, 아니면 `site_floor_map_id`·`ir_guard_enabled`·`obstacle_mode: path`·URDF 몸이 모두 있을 때). 없거나 거짓이면 Fleet 은 굽이 지시를 보내지 않는다. `line_follow_authority`(bool, D-517 4, v1.143)는 CORE line-follow 가 `POST /line-follow/authority` 를 받아 강제할 때 `true`(line-follow 가 없으면 `false`)다. 없거나 거짓인 로봇에 Fleet 은 통행권을 보내지 않고 M1 교차로 보류만 쓴다. `line_follow_authority_required`(bool, D-517 4, v1.143)는 설정 `line_follow.authority_required` 가 참이라 CORE 가 첫 통행권 전에도(E-Stop·CORE 재시작 뒤 포함) 통행권 없이는 서는 때 `true`(line-follow 가 없으면 `false`)다. `fleet.traffic.authority: true` 인 Fleet 은 `line_follow_authority` 가 참인데 이 값이 참이 아닌 로봇의 `lane` trip 을 열지 않는다(422 `TRIP_AUTHORITY_NOT_REQUIRED`). `lane_arc`(bool, D-520 1항, v1.145)는 CORE 가 `POST /line-follow/junction` 의 `exit_segment` 를 받을 때 참이다. v1.154(D-520 개정 2026-10-09)부터 `line_follow.arc_enabled` 는 기본 켬이고, 능력은 그 설정과 현장 바닥 선언 `site_floor_map_id`, `ir_guard_speed_scale` > 0 이 함께 있을 때만 참이다(선언 없는 켬은 시작 거부가 아니라 능력 거짓). 없거나 거짓이면 Fleet 은 `exit_segment` 를 빼고 오늘처럼 보낸다. `trip_lease`(bool, D-541 1, v1.157)는 CORE 가 `PUT/DELETE /api/v1/trip-lease`·`POST /trip-lease/takeover` 를 받고 lease 동안 주인 아닌 움직임을 거절할 때 `true` 다. 없는 로봇은 이전 이미지다. D-494 세 필드 `robot_kind`·`drive_modes`·`trip_max_linear`가 **없는** 로봇은 D-494 이전 이미지다(`junction_turn`도 없다). `robot.model`이 로봇 패키지 이름(`[a-z][a-z0-9_]*`, 64자 이하)이 아니면 CORE는 `robot_kind`만 뺀다. Fleet 은 모르는 `drive_modes` 값을 무시한다. Fleet 은 그
  로봇의 계획 미리보기를 지금처럼 허용하고, trip 실행은 열지 않는다(`TRIP_ROBOT_CAPS_UNKNOWN`, D-494 5).
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
| POST | `/api/fleet/place-markers` | source 전용 Bearer token | D-564 (v1.168): vision worker가 `PlaceMarkerPayload {map_id, calibration_revision, captured_at, seq, markers[1..16]{marker_id 0–49, x, y, yaw}}`(`core_common.protocol.place_markers`)를 제출. source는 token에서 정하고 본문의 `source_id`는 422. 그 source의 `place_markers`에 없는 id 403 `PLACE_MARKER_FORBIDDEN`, `MAP_MISMATCH`·`CALIBRATION_MISMATCH`·`SIGHTING_FUTURE`·`SIGHTING_STALE`(2 s)·`SIGHTING_OUT_OF_ORDER`(source·marker별) 409. (source, marker_id)마다 최신 하나를 메모리에만 둔다. 표시·가르치기 입력만이고 지도 자세·trip·교통정리는 읽지 않는다 |
| GET | `/api/fleet/place-markers` | console Bearer token | D-564: `{markers[{marker_id, x, y, yaw, source_id, map_id, calibration_revision, captured_at, seq, received_at, age_ms, stale}], ts, lease_s: 2.0}` |
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

D-587(v1.177)부터 `calibration_source`에 `approved_record`가 더해진다. Vision 추적 단계가
그 source의 승인 추적 보정(D-457, `GET /api/fleet/detections/config`의 `calibration`)으로
투영한 로봇 마커(`robot_markers`에 있는 것만)의 sighting이다. `corner_marker_ids`는 `null`,
`calibration_revision`은 그 승인 기록의 revision이다. Fleet은 그 revision이 지금 그 source의
승인 기록(같은 `map_id`)일 때만 받고, 다르거나 기록이 없으면 409 `CALIBRATION_MISMATCH`다.
이 경로는 서버 설정의 `calibration_source`와 고정 `calibration_revision`을 보지 않는다.
`x, y, yaw`는 마커 아래의 로봇 자세다(마커 높이 시차 보정, URDF 부착 위치, 로봇별
`marker_yaw_offset_deg`). D-494 지도 자세의 앵커가 된다.

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
| GET | `/api/vision/sources/{source_id}/frame` | Vision preview lease Bearer token | One latest fresh JPEG; `Cache-Control: no-store`; `X-Frame-Seq`, `X-Frame-Age-Ms`, `X-Frame-Captured-At`, `X-Frame-Width`, `X-Frame-Height`, `X-Frame-Rotation-Deg`, and `X-Frame-Rectified` (`true` manual, `auto` D-484 field calibration, `map` D-560 map plane, `false` raw) describe that exact frame; `mode: "map"` requests add `X-Frame-Plane` and `X-Frame-Calibration` or answer 409 `X-Frame-State: plane-unavailable` (never the raw JPEG); `mode: "auto"` requests additionally report `X-Field-Calib` (calibration state) and, while no accepted quad exists, answer the raw JPEG with `X-Frame-State: field-unavailable` |
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

D-560(v1.167)부터 `rectification`에 `{"mode": "map"}`이 추가됐다. `map`은 다른 필드를
받지 않는다(있으면 lease 생성 422). Vision은 추적이 Fleet `/api/fleet/detections/config`에서
이미 읽는 승인 보정 기록(D-457 `map_to_image`, `image`, `track_bounds_m`, `lens`,
`calibration_revision`)으로 최신 원본을 지도 평면에 편다. 그 기록은 추적 worker가 넘기므로
그 source에 추적(`rosy-vision` `--track`)이 켜져 있어야 평면이 나온다. 꺼져 있으면 늘 409다.

- 영역: `track_bounds_m`에 여유 `0.15 m`를 더한 직사각형. 지도 `+x`가 오른쪽, `+y`가 위.
- 축척: `400 px/m`. 긴 변이 1920 px를 넘으면 그 안으로 줄인다(소수 넷째 자리에서 내림).
- 화면 밖이었던 부분은 어두운 고정색(BGR 24,24,24)이다. JPEG 품질 88.
- 응답 헤더: `X-Frame-Rectified: map`, `X-Frame-Plane: <min_x>,<min_y>,<max_x>,<max_y>,<px_per_m>`
  (미터, 여유 포함, 소수 넷째 자리; `px_per_m`은 줄인 뒤 값), `X-Frame-Calibration: <calibration_revision>`.
  픽셀 수를 반올림한 뒤 `max_x = min_x + 폭 / px_per_m`, `min_y = max_y − 높이 / px_per_m`로 다시 정하므로
  이 사각형은 영상 크기 / `px_per_m`와 같다.
  `X-Frame-Width`·`X-Frame-Height`는 평면 영상 크기이고 `X-Frame-Rotation-Deg`는 `0`이다.
  `X-Frame-Seq`·`X-Frame-Age-Ms`·`X-Frame-Captured-At`·`X-Source-Lens`는 원본 프레임 그대로다.
- 픽셀↔지도: 캔버스 좌표(픽셀 모서리 기준) `(u, v)`는 `x = min_x + u / px_per_m`,
  `y = max_y − v / px_per_m`이다.
- 못 펼 때: 승인 기록이 없거나 source·map·렌즈(`X-Source-Lens`와 같은 비교)·영상 비율(1 % 초과)이
  기록과 다르면 `409`, `X-Frame-State: plane-unavailable`, 본문 `map plane unavailable`. 원본으로
  대신하지 않는다. 오래된 프레임은 다른 모드와 같은 404다.
- 펴기는 이벤트 루프 밖에서 프레임·revision마다 한 번 하고, 같은 프레임의 다른 읽기는 그 결과를 쓴다.
  평면 영상은 표시·좌표 확인용 사본이며 원본 프레임·추적·sighting을 바꾸지 않는다(D-560 7).

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
`robot_ids: enrolled`(D-580, v1.175)이면 대상은 Fleet의 살아 있는 명단이고, `robot_markers`는 예외만 적는다(명단에 없는 로봇은 무시). 나머지 로봇의 마커는 로봇 번호(`rosy_NN`의 NN, 40–49)이며 모서리·장소 마커·예외 값과 겹치면 배정하지 않는다.

| Method | Path | Credential | 내용 |
|---|---|---|---|
| POST | `/api/fleet/detections` | source Bearer | `OverheadDetectionsPayload` 제출. source/map/revision·1 s lease 검사. v1.186(D-600): 선택 `unknown_floor` `[{x, y, radius_m}]`(최대 16, `OK`일 때만, 비면 생략) — 배경이 아직 못 본 바닥 v1.189(D-589): 선택 필드 `tuning` `{state, score, ev, locked}`(없으면 JSON에서 빠짐, 추가 키 거부). 이 Fleet 이전 판은 `tuning`이 실린 payload를 422로 거부한다. Vision은 그 422를 받으면 같은 payload를 `tuning` 없이 한 번 다시 보내고, 그 프로세스에서는 다시 싣지 않는다 |
| GET | `/api/fleet/detections/config` | source Bearer | 해당 source의 승인 calibration 또는 null, relearn_seq. v1.130(D-472): `identity_challenge` `{request_id, color, not_before, not_after}`(Fleet 벽시계, 창 ≤ 6 s) 또는 null — 이 source가 보는 로봇에 열린 LED 확인 요청. v1.175(D-580): `robot_markers` `{robot_id: marker_id}` — 이 source의 현재 로봇 마커(`robot_ids: enrolled` source는 살아 있는 명단, 마커 = YAML 예외 또는 로봇 번호 40–49). Vision은 이 값을 YAML보다 먼저 쓴다. v1.185(D-596): `identity_challenges` — 이 source의 열린 LED 확인 요청 전부(색마다 하나, 최대 2, 같은 모양). `identity_challenge`는 그중 가장 오래된 것(이전 Vision 호환). Vision은 열린 창이 끝날 때까지 배경 학습·장면 변경 재학습·유령 치유를 멈춘다. v1.186(D-600): `occupied` `[{robot_id\|null, x, y, radius_m, basis:"marker"\|"sighting"\|"operator_pin"\|"map_pose"\|"own_pose"\|"blob"}]` — Vision 배경 학습이 배우지 않을 로봇 자리(지도 m). 로봇마다 마커 > D-494 지도 자세(반경 + odom 다리, 최대 0.3 m) > LOCALIZED 자기 자세, 그리고 배정 없는 마커와 마지막 OK 프레임(60 s 이내)의 익명 blob |
| POST | `/api/fleet/detections/identity` | source Bearer | D-472 (v1.130). 한 `identity_challenge`에 대한 Vision 판정: `{source_id, map_id, request_id, processor_revision, state:"matched"\|"ambiguous", reason?:"none"\|"multiple"\|"frames_missing"\|"stale"\|"calibration_changed", x?, y?, captured_at?, calibration_revision?, evidence}`. 숫자만, 영상 바이트 없음(D-136). 다른 키 422. `matched`는 창 안 `captured_at`, source의 현재 map·보정 revision, 최신 탐지에서 0.25 m 안의 이어지는 익명 blob이 있고 0.30 m 안에 다른 blob이 없을 때만 확인 트랙이 된다. 열린 요청이 아니면 409 `IDENTIFY_NOT_PENDING`, 묻지 않은 source 409 `IDENTIFY_SOURCE_MISMATCH`. 응답 `{robot_id, state:"CONFIRMED"\|"UNKNOWN", reason?}` |
| GET | `/api/fleet/tracking` | viewer 이상 | sources 상태·fps, robots 대조, unknown 위치. v1.186(D-600): source 행 `unknown_floor` `[{x, y, radius_m}]`(신선한 페이로드, 아니면 `[]`) v1.189(D-589): `sources[].tuning` `{state, score, ev, locked}` 또는 null — Vision이 마지막으로 보낸 그 카메라의 인식 맞춤 상태(lease 안에서만). `state` `off`(폰 스위치 꺼짐)·`waiting`·`tuning`(맞추는 동안 그 source의 검출은 `LEARNING`)·`locked`·`paused`(폰 열)·`unsupported`(연결 15 s 동안 `camera_state`가 없는 옛 앱), `score` 0–1 인식 점수(표시용 측정값, 맞춤 판단에 쓰지 않음) 또는 null(미측정), `ev` 적용된 노출 보정(실제 EV, 소수) 또는 null, `locked` AE 잠금. 사이트 `auto_tune: false`인 source는 `tuning`을 보내지 않아 null. 표시 전용 |
| GET | `/api/fleet/tracking/identity` | viewer 이상 | D-472 (v1.130), 읽기 전용. v1.185(D-596): `pendings[]`(열린 요청 전부, 각 `trigger`), `pending`은 가장 오래된 것, `last.trigger`, `config.auto_min_interval_s`. `{ts, use:"observation-only", pending:{robot_id, request_id, color, sources, not_before, not_after}\|null, robots:[{robot_id, state:"CONFIRMED"\|"UNKNOWN", reason, x, y, yaw:null, age_s, source_id, map_id, calibration_revision, confirmed_at, use, last}], config:{window_s, identity_ttl_s, overlap_m, auto_request}}`. 확인 트랙은 트랙 손실(`track_lost_s` 1 s)·0.30 m 겹침·map/보정 revision 변경·`identity_ttl_s` 경과 중 하나로 UNKNOWN이 된다(addendum 4). D-511 차로 준수 입력과 콘솔 표시 전용이며 `map-pose` 중재·trip·initialpose·경로·명령에 쓰지 않는다(addendum 3) |
| POST | `/api/fleet/tracking/relearn` | operator | `{source_id}`의 배경 재학습 번호 증가. v1.186(D-600): 응답 `{source_id, relearn_seq, occupied, unlocated:[robot_id]}` — 로봇은 그대로 두고, `occupied` 자리는 배우지 않으며, `unlocated` 로봇은 배경이 될 수 있다 |
| GET | `/api/fleet/calibrations` | viewer 이상 | 승인 기록 목록과 `use: display-only` |
| POST | `/api/fleet/robots/{robot_id}/identify` | named `operator` (D-540 9, v1.161) | D-472, v1.130; v1.185(D-596). 본문 생략 또는 `{color?:"blue"\|"amber"}`(생략 = 파랑, 파랑이 그 로봇을 보는 source에서 쓰이는 중이면 주황. 주황은 주의(caution) 램프와 같은 점멸이라 자동 요청은 파랑만 쓴다). 자동 요청은 CORE에 `?quiet=true`(호출음 없음, 이전 payload는 이 값을 무시하고 소리를 낸다), 마커가 계속 안 보이는 로봇은 30 s → 2 min → 5 min 간격. Vision의 `matched`는 그 로봇의 예상 자리 안이어야 하고(v1.191: Fleet 지도 자세, 반경 `auto_near_m` + 앵커 뒤 odom 1 m마다 0.15 m·최대 1.0 m; 지도 자세가 없으면 마지막 천장 마커 자리·`auto_near_m`; 아니면 UNKNOWN `far_from_robot`; v1.193부터 파랑 점멸 판정은 예상 자리 밖에서도 받는다, 주황과 정색 표시는 아님), 예상 자리를 모르는 주황 요청은 UNKNOWN `no_prediction`. 신원 미확인 등록 로봇에 서 있든 움직이든(로봇을 움직이지 않는다) CORE `POST /host/lamp/identify`를 전달하고 그 로봇을 보는 Vision source에 6 s 창을 연다. 동시에 source마다 색 하나씩(최대 2대): 같은 로봇이 이미 확인 중이거나 요청한 색이 쓰이는 중이거나 두 색 모두 쓰이는 중이면 창+2 s 동안 409 `IDENTIFY_BUSY`, 확인된 로봇 409 `IDENTIFY_ALREADY_CONFIRMED`, 로봇 거절(또는 쓰이는 색으로 답함) 502 `IDENTIFY_NOT_ACCEPTED`. 로봇이 주의 표시 중(차선 HOLD, 도킹 실패)이면 409 `IDENTIFY_ROBOT_CAUTION`(v1.191, 자동 요청은 묻지 않는다). `IDENTIFY_NOT_MOVING`은 없어졌다. 응답 `{robot_id, request_id, color, not_after, sources, state:"pending_visual_confirmation", trigger:"operator"}`는 카메라 신원 확정이 아니다. 사이트 YAML `identity.auto_request`(기본 true, v1.185)면 Fleet이 스스로 요청한다: 마커를 본 로봇의 마커가 `auto_marker_missing_s`(3 s) 넘게 안 보이고 마지막 마커 자리(없으면 로봇 지도 자세) `auto_near_m`(0.5 m) 안에 익명 blob이 있을 때(`marker_missing`), 겹침으로 풀린 확인 트랙 근처 blob이 다시 혼자일 때(`split`), 로봇 자세가 odom 원점으로 뛴 뒤 익명 blob이 있을 때(`odom_reset`). 로봇마다 `auto_min_interval_s`(30 s)에 한 번, 상태가 신선하고 `safety.estop`이 정확히 false일 때만 |
| POST | `/api/fleet/calibrations` | operator | source_id/map_id, map_to_image(9), image(width,height), track_bounds_m, fit_score, lens 또는 null, frame_seq 또는 null을 승인·영속 기록 |
| DELETE | `/api/fleet/calibrations/{source_id}` | operator | 승인 기록 철회·감사 |
| GET | `/api/fleet/start-points` | viewer 이상 | `{start_points, persistent}`. 저장한 무마커 시작 위치·방향, `use: reference-only`; 주행·로봇 위치 증거가 아니다 |
| PUT | `/api/fleet/start-points/{source_id}` | named `operator` (D-540 9, v1.161) | `{map_id, calibration_revision, expected_revision: string 또는 null, x, y, yaw}`. 승인된 paint-fit 지도 내부 좌표(m), yaw(rad, -π~π). 새 기록은 expected_revision null, 수정은 읽은 revision. 응답은 저장 기록 |
| DELETE | `/api/fleet/start-points/{source_id}?expected_revision=...` | named `operator` (D-540 9, v1.161) | 읽은 revision과 일치할 때만 삭제. 보정이 철회돼도 기록 삭제 가능 |

무마커 시작점(v1.103)은 `source_id`, `map_id`, `calibration_revision`, `revision`, `x`, `y`, `yaw`, `saved_by`, `saved_at`(Unix초), `valid`, `use: reference-only`를 반환한다. 승인된 보정이 현재 source/map과 일치하고 기록 revision과 같을 때만 valid=true다. 좌표는 지도 원점을 바꾸지 않으며, 저장은 goal·initialpose·로봇 신원 대응·주행 승인에 쓰지 않는다. 시작점에 마커는 요구하지 않는다. SQLite는 보정 DB와 같은 writable 데이터 디렉터리의 start-points.sqlite3에 저장한다. 보정이 메모리 전용이면 persistent=false이며 서버 재시작 시 사라진다. 미등록 source는 404 UNKNOWN_SOURCE, 보정 미승인은 409 CALIBRATION_REQUIRED, 지도 불일치는 409 MAP_MISMATCH, 보정 변경은 409 CALIBRATION_CHANGED, 동시 편집은 409 START_POINT_CHANGED, 범위 밖은 400 START_POINT_OUT_OF_BOUNDS다. bool/NaN/Infinity·추가 필드는 거절한다.

| Method | Path | 권한 | 내용 |
|---|---|---|---|
| GET | `/api/fleet/tethers` | viewer 이상 | `{watch_age_s, tethers: [{robot_id, anchor_xy: [x, y], radius_m, set_by, watch}]}`. `watch_age_s`: 감시 루프 마지막 틱 나이(null: 틱 없음; 2 s 넘으면 루프가 멈춘 것). `watch`(v1.153, D-526)는 아직 틱이 없으면 null, 아니면 `{state: watching\|tripped, trip: null\|tether_radius\|tether_turn\|tether_pose_stale, distance_m, turn_deg, pose_age_s, stop_sent, stop_error, stop_failures, tick_age_s}` |
| POST | `/api/fleet/robots/{robot_id}/tether` | named operator | `{anchor_xy: [x, y], radius_m}`. 같은 본문을 다시 보내도 결과가 같다. 응답은 저장 행. 보낼 때마다 그 로봇의 감시를 새로 시작한다(트립 해제, 회전 0) |
| DELETE | `/api/fleet/robots/{robot_id}/tether` | named operator | 테더를 지운다. `{robot_id, cleared}`, 없던 테더도 200 |

테더(v1.140, D-512 개정 1의 표시·설정 쪽)는 로봇별 map 프레임 원(anchor_xy 각 −1000~1000 m, 0 < radius_m ≤ 50)이다. Fleet 지도는 원과 기준점을 그리고, 로봇 map pose가 원 밖이면 주의 색, 감시가 정지를 내렸으면 위험 색으로 바꾼다. D-526(v1.156): Fleet tether 감시가 0.5 s마다 테더가 있는 로봇의 지도 자세(`GET /api/fleet/state`와 같은 상태 pose, `localization.pose_frame`이 `odom`이면 자세 없음)를 읽는다. 기준점 거리 > `radius_m` + 0.15 m(`tether_radius`), 선언 뒤 펼친 누적 yaw의 절댓값 > 405°(`tether_turn`), 신선한 지도 자세 없음 2 s 초과(`tether_pose_stale`) 가운데 하나면 그 로봇에 기존 CORE E-Stop(`POST /api/v1/safety/stop`, 전체 정지와 같은 로봇 클라이언트)을 보내고 열린 trip을 `tether_trip`으로 끝낸다. 트립은 다시 POST하거나 DELETE할 때까지 래치되고 정지는 CORE가 답할 때까지 틱마다 다시 보낸다. 되돌아가기는 하지 않는다(운영자 몫). CORE E-Stop 해제는 기존 관리자 경로 그대로다. 메모리에만 두어 Fleet 재시작 때 사라지고, 로스터에서 빠진 로봇의 테더는 목록에서 지운다. 미등록 로봇은 404 UNKNOWN_ROBOT, bool·Infinity·범위 밖·추가 필드는 422다. JSON이 아닌 NaN도 저장 전에 거절된다(현재 앱 공통 검증 응답이 NaN을 담지 못해 500). 지도 궤적(지나온 길)은 브라우저가 기존 `GET /api/fleet/state` pose로 모으며(최근 120 s, 600점, 1 cm 이상 이동 시, `localization.pose_frame`이 `odom`인 자세는 넣지 않는다) 새 필드가 없다.


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
unknown 행은 `{source_id,x,y,footprint_m,score,marker_id}`이다. 익명 검출은 `marker_id: null`, 배정 로봇이 없는 마커 검출(D-575, Vision은 D-562 로봇 범위 40–49만 보냄)은 그 id를 싣고 발자국 안의 익명 검출 하나를 흡수한다.
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
| POST | `/api/fleet/ai/heartbeat` | site-users `ai_observer` only | D-577 4 (v1.183): the AI PC situation service's status every 2 s, body `{service_version, model_profiles[] (≤8), owner_mode: available\|shared\|owner_busy, gpu_used_mib?, mem_used_mib?, input_lag_s?}` (extra fields 422); answers the status below. Not written to `fleet_api_audit` (the facts table is its record). |
| POST | `/api/fleet/ai/facts` | site-users `ai_observer` only | D-577 3·4 (v1.183), shadow only: `{facts: [ {kind, robot_ids[1..16], value, confidence 0–1, evidence {…}, source, observed_at (epoch s), ttl_s} ]}`, at most 32 facts. `kind` is one of D-577 3 (`wait_cycle_confirmed`, `wait_cycle_stale_input`, `waiting_but_moving`, `livelock`, `stalled`, `unknown_occupancy_long`, `lane_obs_vs_range`, `lane_conf_collapse`, `shadow_active_drift`, `pose_vs_paint`, `pose_sources_disagree`, `obstacle_identity`, v1.188: `rear_blocked`, `path_blocked_by_robot`, `incident_context`); `source` is `analyzer:<name>@<version>` (`ttl_s` ≤ 5) or `vlm:<profile_id>` (`ttl_s` ≤ 8). 422 `AI_FACT_INVALID` for a command word (`WAIT`, `RESUME`, `BACK_AND_RETRY`, `YIELD`, `ABORT`, `MANUAL`, `STOP`, `GO`, any case) as a key or value anywhere in `value`/`evidence`, a ttl over its bound, `observed_at` more than 1 s in the future, an unknown kind or field; 413 `AI_FACTS_TOO_LARGE` over 64 KiB; 429 `AI_FACTS_RATE` over 2 posts in one second. 200 `{accepted, ignored, ai}`: with no heartbeat for 6 s (`ai: absent`) or `owner_mode: owner_busy` every fact is ignored. Accepted facts go to memory (256 newest) and `fleet_ai_facts` (`--tasks-db`, written off the event loop) with `stage: shadow`; nothing reads them as a rule input. D-577 개정 2026-10-10 (v1.188): a `rear_blocked` or `path_blocked_by_robot` fact whose first robot id is in site config `fleet.stuck_resolver.ai_facts_acting` (robot id list, default empty) is stored `stage: acting`, and while it is live the Fleet stuck resolver turns any back-off it would send that robot (R2/R3/R6 `BACK_AND_RETRY`) into R5 `WAIT` plus a human row `<cause>_hold:ai:<kind>`; it never adds another answer. |
| POST | `/api/fleet/ai/proposals` | site-users `ai_observer` only | D-577 개정 2026-10-10 (v1.188, 사용자 결정 "AI PC 제안 → Fleet 검증 후 실행"): `{robot_id, stuck_id, decision: WAIT\|BACK_AND_RETRY\|YIELD\|ABORT\|RESUME\|MANUAL, reason ([a-z0-9_:.-], ≤64), confidence 0–1, evidence {…}, source, observed_at, ttl_s ≤ 8}` (extra fields or another word 422; `observed_at` over 1 s ahead 422 `AI_PROPOSAL_INVALID`). 200 `{state: queued\|absent\|owner_busy\|robot_not_acting}`: kept (newest per robot, memory) only for a robot in site config `fleet.stuck_resolver.ai_facts_acting` while the service is present. The stuck resolver waits up to 5 s from first seeing a stuck of such a robot for a proposal, judges it once (`stuck_id`, ttl, word allowed for the cause: `lane_lost`/`no_motion` WAIT·BACK_AND_RETRY·ABORT, `obstacle_ahead` also RESUME, none for `crosswalk_blocked`; trip robots WAIT only; YIELD and MANUAL never forwarded; BACK_AND_RETRY under the R2/R3/R6 preconditions and not `rear_state: blocked`) and forwards it to CORE as the decision (`tier: ai`, a WAIT also raises the human row `ai_wait:<reason>`), else the rules R1–R6 answer. Verdicts and CORE outcomes go to `fleet_ai_proposals` (`--tasks-db`) and `GET /api/fleet/ai` `proposals[]` (64 newest). |
| GET | `/api/fleet/ai` | any configured user bearer | D-577 5 (v1.183): `{status {state: present\|absent, owner_mode, age_s, service_version, …heartbeat fields}, facts[]}` — live facts (within `ttl_s`, none while absent). Each `line_stuck` row (state and `/api/fleet/line-stuck`) carries `ai {state, owner_mode}` and that robot's live `ai_facts[]`; the console shows them as the AI chip ("AI 판단 있음/없음") and fact lines. Role `ai_observer` (site-users, token only, no console login) reads every GET like a viewer and is refused with 403 `AI_OBSERVER_FACTS_ONLY` on every other write route, whatever that route's own guard (stops, stuck answers, trips, goals included). |

조회 응답은 `events`, `next_cursor`, `has_more`를 포함한다. 이벤트 수신/저장은 DDS 접근이나
동작 명령을 수행하지 않는다. SQLite 쓰기 실패 시 Agent 이벤트를 성공 수신으로 응답하지 않는다.

---

# 10.8 Site Fleet task submission, role authorization, and readback (D-276 Accepted)

Fleet `GET /api/fleet/state` (D-493) rows also carry `state_age_s`: seconds from when
that robot's state was observed (hub heartbeat time, or the REST read) to the moment
the response was built, so shared-gather cache age is included; `null` for an offline
row, absent on an older Fleet. The top level carries `gathered_at` (server UTC epoch
seconds, display only; clients must not subtract it from their own clock). The console
exception queue adds its receive-time age to `state_age_s` and warns above 5 s.
Fleet `GET /api/fleet/state` robot rows also expose optional `capabilities`: the
authenticated CORE CAP-001 object, or `null` when it cannot be read. Presentation
may reuse this value for up to 5 seconds; an absent field denotes an older Fleet.
This value is not permission to move. Immediately before goal dispatch (including
yielding to a bay), Fleet reads CAP-001 again and requires
`navigation.goal_navigation == true`. Formation planning similarly requires
leader `swarm.lead` and each follower `swarm.follow` before opening relay streams.
Missing/false flags are refused as `NOT_SUPPORTED`; transport errors remain errors.
CORE still performs its own authorization, localization, and safety checks.

Fleet `GET /api/fleet/state` robot rows also expose optional `link` (D-499):
`up`, `unreachable`, `moved`, `tls-refused`, or `protocol`. Absent on a robot
API error other than HTTP 401. `up` is a successful gather and carries no
console tag. The field is display-only. CORE paths, envelope 1.0, and the
dispatch loop's online/state/goal read are unchanged. An older Fleet omits the field.
D-535 (v1.155) adds optional `link_reason {code, message, action, retry}` to a row whose
gather failed: the D-535 reason (transport failure classified by the Fleet, or the robot's
`error.code`/HTTP status). Message and action come from Fleet's own table, never the robot's text.

Fleet `GET /api/fleet/state` robot rows also carry optional D-509 display fields
`power_health` and `power_health_age_s`. `power_health` is the existing shared
`core_common.protocol.power_health.PowerHealthResponse` (the authenticated
Viewer `GET /api/v1/power/health` readback), or `null` if the robot is offline,
the robot answers an error, or the body violates that schema. Fleet refreshes it
about once a second off the request path; a refresh that gets no answer (timeout,
refused) keeps the last good body, which is shown up to five seconds old and is `null`
after that. `power_health_age_s` is the nonnegative
Fleet monotonic-clock age in seconds, or `null` whenever `power_health` is null.
The browser adds its own elapsed time after receiving the Fleet response and
checks CORE `battery.sample_age_s` against `stale_after_s` before showing a
current percentage, and separately checks `charging_evidence_age_s` against
the CORE five-second confirmation window before showing confirmed charging.
`battery_status.charging` is a
policy latch, not current charging evidence. These fields are display-only:
Fleet never uses them for motion admission, E-Stop release, or power policy.
The response type is already a shared schema; no CORE endpoint or envelope
field changes.

When durable task storage is configured, the operator navigation route creates a
persistent task before contacting CORE. The browser sends a fresh
`Idempotency-Key`; repeating the same request with the same authenticated
operator identity returns the original task without issuing another robot
command. Reusing a key for a different request returns `409 IDEMPOTENCY_CONFLICT`.

| Method | Path | Credential | Requirement |
|---|---|---|---|
| GET | `/api/fleet/session` | any configured site-user bearer | Returns only the authenticated `principal_id` and role for the current console session. |
| GET | `/api/fleet/auth/connection` | none | D-473 (v1.108): `{mode: "development"\|"paired"}` with `Cache-Control: no-store`. `development` only when Fleet started with both `ROSY_DEPLOYMENT=development` and `--connection-mode development`; any other combination, or a missing setting, is `paired`. D-519 (v1.137): also `password_login: bool`, true when site-users holds at least one login account; the console then offers 아이디·비밀번호 and folds the token field. |
| POST | `/api/fleet/auth/development-session` | none (development mode only) | D-473 (v1.108): 201 `{token, principal_id, role: "operator", expires_at}` with `Cache-Control: no-store`. `principal_id` is `development-<8 hex>`; the token is returned once and lives 1 h in Fleet memory only (gone on restart). The caller address (the last `X-Forwarded-For` entry when Fleet runs with `--lan-camera-proxy` behind the site proxy, otherwise the TCP peer) must be loopback, RFC1918, link-local or the Tailscale tailnet `100.64.0.0/10`; `Host` must be a LAN IP literal, `localhost`, a `.local` name or the host name, and a present `Origin` must equal `Host`; otherwise, and always in paired mode, 403 `FORBIDDEN`. More than 6 requests per address per minute is 429 `RATE_LIMITED` with `Retry-After: 60`. At most 8 sessions are live; a ninth evicts the oldest. The session is a named operator: it passes the named-operator gate (missions included), and the issue and every later POST are written to the API audit under that principal; an unavailable audit is 503 `AUDIT_STORAGE_UNAVAILABLE` and no session. Robot credentials (`robots.yaml`, D-361 enrollment) and stop paths are unchanged. |
| POST | `/api/fleet/auth/login` | none (site-users login accounts only) | D-519 (v1.137): body `{login, password, remember?: bool}`. 204 with `Cache-Control: no-store` and `Set-Cookie: rosy_fleet_session=<random>; HttpOnly; Secure; SameSite=Strict; Path=/`, plus `Max-Age=2592000` (30 d) only when `remember` is true. Accounts are `site-users.yaml` entries with `login` (`^[a-z0-9._-]{1,32}$`, unique) and `password_scrypt` (`scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`, made by `python -m fleet.server.site_users hash-password`); `service` cannot have a login. A wrong password and an unknown login give the same 401 `LOGIN_FAILED`. More than 5 failures per address or 10 per login in a minute is 429 `RATE_LIMITED` with `Retry-After: 60`. A present `Origin` must equal `Host`, else 403 `CSRF_REJECTED`; a malformed body is 422 `INVALID_REQUEST`. Success is audited under the principal, failure as `login:<name>` (role `viewer`); 429 is audited the same way at most once per address per minute. A login that does not match the pattern is the same 401 (after the dummy scrypt) and is audited as `login:?`. At most two password checks run at once; one that cannot start within 5 s is 429 `RATE_LIMITED`. Without any login account in site-users this route and logout are 404. The session lives in the `--tasks-db` (SHA-256 of the cookie only) and survives a Fleet restart: idle limit 12 h (sliding), 30 d with `remember`, never more than 30 d after login; account changes take effect when Fleet restarts with the edited site-users file (as for tokens), and then every session whose login's principal, role or password changed, or whose entry was removed, ends at once. A session read that cannot reach the DB is 503 `SESSION_STORAGE_UNAVAILABLE`; a cookie validated in the last 60 s needs no DB, and `POST /api/fleet/estop` also accepts an older cached cookie while the DB is unavailable. |
| POST | `/api/fleet/auth/logout` | session cookie | D-519 (v1.137): 204; deletes the cookie's session and expires the cookie. With a cookie, `Origin` must equal `Host`, else 403 `CSRF_REJECTED`. |
| GET | `/api/fleet/auth/session` | site-user bearer, development session or session cookie | D-519 (v1.137): `{principal_id, role, via: "cookie"\|"bearer"\|"development", expires_at}` with `Cache-Control: no-store`; `expires_at` is the cookie session's UTC ISO end, `null` for bearer and development. 401 without a credential. **Cookie rule (all `/api/fleet/*` routes):** an `Authorization: Bearer` header is checked exactly as before and wins; only without it is `rosy_fleet_session` read. A cookie-authenticated request other than `GET`/`HEAD` needs an `Origin` whose authority equals `Host`, else 403 `CSRF_REJECTED`. The cookie principal is a named operator for `require_named_operator`. Machine clients keep their Bearer tokens. |
| POST | `/api/fleet/robots/{robot_id}/goal` | named `operator` (D-540 9, v1.161) + `Idempotency-Key` | Validates the configured robot and finite goal, durably accepts the task as `QUEUED`, then lets the dispatcher request a CORE goal. |
| POST | `/api/fleet/robots/{robot_id}/route` | named `operator` (D-540 9, v1.161) + `Idempotency-Key` when durable tasks are configured | D-463 (v1.100): body `{edges: [edge_id, ...]}` of 1 to 8 stored lane-graph edge ids; extra fields 422. Each edge must exist and its `to` must equal the next edge `from`, or 400 `ROUTE_UNKNOWN_EDGE` / `ROUTE_DISCONTINUOUS`. Fleet expands the stored polyline and submits only the next point about 0.20 m ahead, yaw equal to the tangent, through the existing goal path. It does not submit the far junction as that goal. The fresh snapshot must be `LOCALIZED` with `pose_frame` `map` and within 0.08 m of the polyline; otherwise 409 `ROUTE_POSE_UNTRUSTED` or `ROUTE_OFF_LANE` and CORE is not called. A snapshot with no localization block is refused. Within 0.05 m of the end the response is 200 `ROUTE_COMPLETE` and no goal. `GoalRequest` stays `{x, y, yaw}`. |
| GET | `/api/fleet/site-map/active` | any configured user bearer | D-488 (v1.111): the active `rosy.site_map/1` (places `{id, name, x, y, yaw?, kind park/charge/stop/junction/turnaround/start/bend, exit_yaw?, radius_m?}; D-513 (v1.124): a `start` place needs `yaw`, else 422 `SITE_MAP_INVALID`; D-507 addendum (v1.142): a `bend` place is the vertex of two lane centre lines with `yaw` (entering heading as its edge is drawn), `exit_yaw` and `radius_m` (0, 0.5], the arc the robot drives inside the lane, all required and a turn of 15–90°; other kinds may not carry `exit_yaw`/`radius_m`; bends do not split edges``, edges `{id, from, to, polyline, direction one_way/two_way, width_m, speed_cap_mps, drive_mode lane/free, robot_kinds?}`, optional `turn_bans {at, from_edge, to_edge}`, optional `view_turn_deg` 0/90/180/270 (D-513 7, v1.130: clockwise screen turn of the plain +y-up map view that every Fleet map and camera view follows; display only, default 0), optional `crosswalks` (D-573 1, v1.174) `[{id, polygon [[x, y]] (3–32 points, map frame), approach [[[x, y]]] (0–4 waiting bands, 3–32 points each), lanes [edge_id], revision}]` at most 50: the polygon is the import lane graph's `crosswalks[].polygon` as is (ids `cw1`.. in file order, `revision` `lane_graph:<sha256[:12]>` of that file), `lanes` is recomputed from the edges the polygon touches on every validation (a submitted value is replaced), waiting bands are drawn in the site map editor. 422 `SITE_MAP_INVALID` when crosswalk ids repeat, a polygon or band is not finite, under 1 cm² or over 3 m across, a crosswalk touches no edge, a band does not reach one of its lanes (within half the lane width) or a band point is off the D-507 9 site floor (farther than half the width + 0.30 m from every edge). Absent when empty; map data only, nothing is sent to a robot) with `version`, `sha256`, `activated_by`, `activated_at`. Places are more than 0.05 m apart and every edge is longer than 0.10 m between its places. 404 `SITE_MAP_NOT_ACTIVE` when the site has none. Errors here and on `/trip` are `{"detail": {"code", "detail"}}`. `GET /api/fleet/site-map` (D-257 camera rectangle) is unchanged. |
| GET | `/api/fleet/site-map/lane-graph-crosswalks` | any configured user bearer | D-573 1 (v1.174): `{source, crosswalks [{id, polygon, approach: [], lanes: [], revision}]}` read from the configured `--site-map-import` lane graph, for the site map editor to merge into the draft (polygons replaced by id, drawn bands kept); the draft is then saved by a named operator like any edit. 404 `SITE_MAP_NO_LANE_GRAPH` without a configured import, 422 `SITE_MAP_NO_LANE_GRAPH` when the file cannot be read. Writes nothing. |
| GET / PUT | `/api/fleet/site-map/draft` | GET any user; PUT named `operator` | D-488 (v1.111): one editable draft. PUT `{map, expected_revision}` (body at most 2 MiB, else 413 `SITE_MAP_TOO_LARGE`); the map is validated or 422 `SITE_MAP_INVALID` with `detail.errors [{loc, msg}]` (no submitted values). A stale `expected_revision` is 409 `SITE_MAP_DRAFT_CHANGED`. Each save is a recorded site map event. A draft is never used for planning. |
| POST | `/api/fleet/site-map/activate` | named `operator` | D-488 (v1.111): `{expected_revision}` copies the saved draft into a new immutable version that becomes active; audited. 409 `SITE_MAP_NO_DRAFT`, `SITE_MAP_DRAFT_CHANGED`, or `SITE_MAP_ROUTE_ACTIVE` while a lane route (`/route`) was stepped in the last 30 s; 422 `SITE_MAP_UNPLANNABLE` when the planner cannot use the map; 422 `SITE_MAP_START_INVALID` (D-513, v1.124) when a `start` place is not a trip start pose (within half a lane width of a lane whose direction there agrees with its `yaw` within the planner heading tolerance), `detail.message` names the place and `TRIP_START_OFF_MAP` or `TRIP_HEADING_CONFLICT`. The first version may come from `fleet console --site-map-import <lane_graph.yaml>` when the store is empty. `/route` reads the active map's edges and answers 409 `SITE_MAP_NOT_ACTIVE` without one. |
| POST | `/api/fleet/robots/{robot_id}/trip` | named `operator` | D-488/D-490 (v1.111): body `{to: place_id or {x, y, yaw?}, via?: [place_id] (max 8), arrive_yaw?, speed_cap?, execute?: false}`. Plans one layered lane-state A* over the vias and the goal on the active map from the robot's fresh `LOCALIZED` map pose (start snaps within half the lane width) and returns 200 `{plan_id, map_version, segments [{edge_id, forward, s_from, s_to}], places, actions [{place_id, action straight/left/right/uturn/stop, theta_deg}], length_m, eta_s, expires_at}`; a robot already on the goal place gets an empty plan. Nothing is sent to CORE. Refusals are 422 `{code, detail}`: `TRIP_START_OFF_MAP`, `TRIP_HEADING_CONFLICT`, `TRIP_OFF_MAP`, `TRIP_UNKNOWN_PLACE`, `TRIP_NO_ROUTE` (`detail.segment`, `detail.unblock_would_help`), `TRIP_ARRIVE_YAW_UNREACHABLE`, `TRIP_NO_ACTIVE_MAP`, `TRIP_POSE_UNTRUSTED` (also a pose without yaw); 404 `UNKNOWN_ROBOT`; an unexpected planner failure is 500 `TRIP_PLAN_FAILED` in the same body. Every plan and refusal is recorded (last 1000 within 30 days). Costs come from site config `fleet.routing`. D-494 (v1.112): when the robot's capabilities carry the `base_velocity` trip fields, the plan uses only edges of its `drive_modes` and its `robot_kind`, at most `trip_max_linear` (0 m/s allows no edge, so `TRIP_NO_ROUTE`); `junction_turn` is read for trip execution (D-495), not for planning; a robot without them is planned as before (every drive mode, kind-restricted edges left out). D-517 2 (v1.141): a place that is no lane's end (a D-513 `start` place part-way along a lane) is planned as a coordinate goal at its `x, y` with its `yaw` as arrive yaw (D-489 6 snapping, `TRIP_OFF_MAP` when no lane is within twice its width); as a `via` it cuts the plan into legs that carry on along the same lane. `repeat: true` (needs `to` as a place id and at least one `via`, otherwise 422 validation) records a lap trip: see `/trips/{plan_id}/start`. D-517 9 M3 (v1.146): `convoy: {leader: robot_id (1–96)}` (only with `repeat`, otherwise 422 validation) asks to follow that robot in a lane convoy; refused 422 before planning when `leader` is the robot itself `TRIP_CONVOY_SELF`, has no open `repeat` trip `TRIP_CONVOY_LEADER_NOT_RUNNING`, follows another robot `TRIP_CONVOY_LEADER_IS_FOLLOWER` (`detail.follows`), or its `{to, via}` place set differs `TRIP_CONVOY_OTHER_LOOP` (`detail.leader` on each). D-601 (v1.192): a plan with a `lane` edge first reads the robot's `GET /api/v1/vision/front/status` once (site config `fleet.trip.lane_camera_check`, default true; false where no preview exists, e.g. Gazebo SIM); `available` not true, or no answer, is 422 `TRIP_LANE_CAMERA_UNAVAILABLE` (`detail {stale, age_ms}` or `{error}`, recorded). The 200 body carries `start_check` `{code, edge_id, heading_err_deg, tol_deg, off_lane_m}` (`{code: null}` for a `free` first edge): the start's alignment check (below) on the planning pose, `code` null when it would pass. The planner's 422 `TRIP_HEADING_CONFLICT` carries `detail.heading_err_deg` (the smallest heading difference to a lane within half its width) and `TRIP_START_OFF_MAP` `detail.off_lane_m`. |
| POST | `/api/fleet/trips/{plan_id}/start` | named `operator` | D-494 5 (v1.116, was a 501 reservation in v1.111–v1.114): runs the stored plan through the Fleet trip loop; the trip id is the `plan_id`, audited. Checks in order: 404 `TRIP_PLAN_UNKNOWN`, 409 `TRIP_ALREADY_STARTED`, 422 `TRIP_PLAN_EXPIRED` (more than 30 s after the plan), 422 `TRIP_MAP_CHANGED` (active map version differs; checked again just before the trip opens), 422 `TRIP_ROBOT_CAPS_UNKNOWN` (no D-494 1 capability fields), 422 `TRIP_MODE_UNSUPPORTED` (`detail.edge_id`; an edge outside the robot's `drive_modes`/kind, any `lane` edge on a robot without `junction_turn: true` `JUNCTION_TURN_UNSUPPORTED` (D-495 3: without keep-mode evidence CORE neither stops at a junction nor turns), a `lane` U-turn `LANE_UTURN`, a `lane` turn over 150° `LANE_TURN_TOO_SHARP`, or a `lane` trip not ending at a place `LANE_END_NOT_A_PLACE`), 422 `TRIP_SITE_FLOOR_MISMATCH` (D-507 9, v1.126: a plan with a `lane` edge on a robot whose `base_velocity` capability `site_floor_map_id` is a string other than the active map's `map_id`, `detail {site_floor_map_id, map_id}`; an absent or null key is not checked), 422 `TRIP_AUTHORITY_NOT_REQUIRED` (D-517 4, v1.143: with site config `fleet.traffic.authority: true`, a plan with a `lane` edge on a robot whose capability `line_follow_authority` is true but `line_follow_authority_required` is not, so after an E-stop or CORE restart it could move before Fleet's first authority; a robot without `line_follow_authority` keeps the M1 hold-back as before), 422 `TRIP_AUTHORITY_SITE_OFF` (D-517 4, v1.150: with site config `fleet.traffic.authority` off, a plan with a `lane` edge on a robot whose capability `line_follow_authority_required` is true: Fleet sends no authority, so CORE would stand at `authority_none` and the trip would end on `stall`), 409 `TRIP_BUSY` (D-517 1, v1.141: this robot already has an open trip, `detail.trip_id`; other robots run their own trips at the same time), 409 `TRIP_ROBOT_BUSY` (the robot already moves for the console: `detail.reason` `goal` (running), `queued`, `yielding` or `formation`), 422 `TRIP_LINE_FOLLOW_NOT_ACTIVE` (a plan with a `lane` edge while the robot's `GET /api/v1/line-follow` `mode` is not `CAMERA_LINE`, `detail.mode`; CORE takes junction instructions only on `CAMERA_LINE`), 422 `TRIP_POSE_UNTRUSTED` (D-494 3 map pose not `LOCALIZED`, or its sighting anchor older than 2 s or unknown; D-593 7, v1.180: an `operator_pin` anchor up to the map pose's 10 s limit also starts while `dead_reckon_m` ≤ `fleet.trip.pin_start_still_m` (0.02) and `bridge_turn_deg` ≤ `pin_start_still_deg` (2°)), 422 `TRIP_LOOP_FULL` (D-517 3, v1.141, `repeat` plans only: one more repeat trip on the same set of edges would break N·h ≤ S − 1, `detail {robots, capacity, held_per_robot}`, h = 3). D-517 3 (2026-10-09 signal SIM, v1.172), with site zones (`fleet.traffic.zones`) no trip stops inside a zone (within a body length + u of a zone lane): a destination or a `repeat` lap's last place reached over a zone lane moves on along the route to the nearest place the robot can hold outside every zone (2026-10-09 user decision "다음 지점까지 가서 섬"; the old destination becomes the last `via`, a coordinate one is dropped), and the trip view's `stop_moved` is `{from, to}` (`from` null for a coordinate) or null; a `stop` at a place next to a zone (a hold, the last place) sends `stop_after_m` shortened so the robot stands outside the zone, and lane arrival counts from that point; no replan hold is set at a place reached over a zone lane. 422 `TRIP_STOP_IN_ZONE` (`detail {place, repeat}`) only when the route has no such place. D-517 9 M3 (v1.146), plans with `convoy`, after the capability checks and before the loop check: 422 `TRIP_CONVOY_SELF`, `TRIP_CONVOY_LEADER_NOT_RUNNING`, `TRIP_CONVOY_LEADER_IS_FOLLOWER`, `TRIP_CONVOY_OTHER_LOOP` (the lap edge sets differ), `TRIP_CONVOY_NOT_BEHIND` (the plan reaches the leader's located lane position only through an edge outside the leader's lap, such as a roundabout shortcut, or starts ahead of it on the same lane), `TRIP_CONVOY_NO_AUTHORITY` (the follower would not get CORE authority: site `fleet.traffic.authority` off or no `line_follow_authority`; the gap is kept only by authority), and `TRIP_CONVOY_LOOP_FULL` in place of `TRIP_LOOP_FULL` (same detail; the leader and every follower count, 1 + N). The trip view carries `convoy` `{leader}` or null. D-517 2 (v1.141): a `repeat` plan may end part-way along a lane but needs a place in it; within `arm_distance_m` of the lap's last place Fleet runs the start checks above again (no named operator) and plans the next lap from the lap end with the same `via`/`to`. The same route as the last lap is appended and the robot drives through (`lap` + 1); a failed check or another route sets `hold {reason: lap, plan (null with code/detail on a failed check), map_version, length_m, eta_s}` and the robot stops at that place; `confirm-replan` takes it. 200 is the trip view `{trip_id, plan_id, robot_id, started_by, state started/running/arrived/stopped/failed/canceled, reason, detail, map_version, plan {segments, places, actions}, segment_index, current_edge, drive_mode, next_place, next_action, hold, pose {x, y, yaw, state, source, dead_reckon_m, age_s, anchor_age_s}, caps, created_at, updated_at, repeat, lap, stop_moved}` (`lap` null unless `repeat`). Every 0.5 s every trip robot steps at once, each in its own task (D-517 7, v1.141: a robot whose last step is still running skips that period, so a slow robot never delays another), and the trip robot's state/odom is read once over REST (past the 1 Hz hub cache) and, on a `lane` segment, its `line_follow.junction` before anything is sent; each robot call gives up after 1.5 s. `lane`: within 0.6 m of the segment's end place the action there goes through robot `POST /api/v1/line-follow/junction` (`straight`; `left`/`right` with `turn_deg` = the map's signed junction angle, D-495; `stop` at the last place, where the trip leaves the lane and at a replan hold, with `stop_after_m` = the distance left to the place clamped to [0, 2] because CORE measures it in odom from receipt). D-507 2 (v1.126): only to a robot whose `base_velocity` capability reports `junction_pivot: true`, each instruction also carries `map_id` (the active map), for `straight`/`left`/`right` `pivot_past_line_m` (v1.135: the signed distance from the first painted line past the place, searched along the lane heading at the place since v1.139, to the place; with no line within 0.30 m the outgoing lane `width_m / 2`, at most 0.30, and no window) and the window pair: `expect_in_m` = the distance along the lane polyline from the robot's snapped position to the place (v1.139, 2026-10-08 user decision: CORE compares it with its odom path length, so a bend or the 260919 ring gets a window too; before v1.139 Fleet sent the straight-ahead distance and no pair past a 15° bend), sent only within (0, 2], and `expect_tol_m` = 0.05 per metre of odom travel (dead-reckoned since the last sighting plus `expect_in_m`) + `trip_max_linear` × (pose age + measured pose-read-to-send time + 0.2 s allowance) + 0.05 m `ENDPOINT_TOL_M`, at least site config `fleet.trip.expect_tol_min_m` (default 0.12), plus the robot's distance beside the lane centre line × the lane's total heading change (rad) from the robot to the place (beside the centre line a curve is that much longer or shorter), and at most 0.30 (0.30 when the pose age or dead-reckoned distance is unknown). D-520 1–2 (Fleet side; the API version is the D-520 CORE entry's): only to a robot whose `base_velocity` capability also reports `lane_arc: true`, and only with `map_id`, a `straight`/`left`/`right` whose outgoing lane is a whole `lane` arc to its place, at most 1.0 m, at least 6 polyline points all within site config `fleet.trip.arc_fit_tol_m` (default 0.005 m; the 260919 ring fits within 0.0001 m) of one circle with 0.5 ≤ |κ| ≤ 5.0 1/m, also carries `exit_segment {curvature_1pm` (signed, left +)`, length_m, outer_line_offset_m` (site config `fleet.trip.arc_outer_line_offset_m`, default 0.095: the site map carries no paint)`, end_place_id}`; such a `left`/`right` sends the plain tangent `turn_deg` (no 6° over-turn) and no `advance_m`. An instruction also counts as carried out once the robot's `line_follow.arc.from_place_id` is its place with an `arc_seq` newer than at its send (the turn before an arc and the chained `straight`, which CORE marks done without `executing`); the end place's instruction goes out while the arc runs (the arc is no manoeuvre). A `line_follow.arc` opened after the trip's first instruction with `state: stopped` ends the trip `stopped` (`reason: lane_arc`, `detail.arc_reason`, `arc_place`, `arc_end_place`); one with `reason: lane_arc_end_unarmed` sets `detail.arc_end_unarmed {end_place_id, travelled_m}` and the trip goes on; an instruction CORE drops at an arc end (`aborted`, `junction_reason: arc_mismatch`) ends the trip like any abort (`reason: junction`). A plan whose map version is no longer active sends none of them (`detail.junction_fields_dropped: map_version`). A robot answer 409 `JUNCTION_ODOM_STALE` is not a trip failure: nothing counts as sent, `detail.junction_retry` shows the code and the next tick sends again (the `waiting` rules still bound it). The keeper detects a junction 0.45 m ahead (`JUNCTION_AHEAD_M`), so `arm_distance_m` (0.6) should be at least 0.45 + `pivot_past_line_m` + `expect_tol_m`; SIM checks it. D-507 addendum (v1.142): only to a robot reporting `lane_bend: true`, a `bend` place whose two tangent points lie on the current lane segment (within 0.05 m, entering heading within 15° of the lane) and that the robot has not passed comes before the segment's place: within 0.6 m (`arm_distance_m`) of its arc start Fleet sends `action: bend`, `place_id` = the bend place, `turn_deg` = its signed turn in the direction of travel, `map_id`, `bend_in_m` = the lane distance to the arc start, `bend_tol_m` = the `expect_tol_m` rule without the travelled-distance and curve-offset terms (odom drift over the dead-reckoned distance only), `bend_radius_m`; refreshed at half its expiry while CORE shows it `armed`; the place's own instruction waits until CORE has carried the bend out (`bending`/`reacquiring` seen under our seq, then `idle` or a newer seq; `JUNCTION_ALREADY_DONE` counts) or the robot passed the arc start without one. A plan on another map version sends no bend. Each `repeat` lap (D-517 2) sends its bends again. Nothing is sent while CORE is `executing` or `turning`/`advancing`/`reacquiring`/`bending` (a new instruction would abort the manoeuvre); a `stop` is sent once; `straight`/a turn is refreshed at half its 15 s expiry only while CORE still shows it `armed` with the same seq and place, or sent again when CORE is `idle`/`waiting` before the place. An instruction CORE has shown under our seq as `executing` or `turning`/`advancing`/`reacquiring` is carried out and never sent again; a robot answer 409 `JUNCTION_ALREADY_DONE` also counts as carried out. Lane arrival needs our accepted `stop` for the last place and the robot within 0.15 m, or CORE holding that `stop` (our seq `executing`) within 0.3 m. The next segment is current once CORE reports the instruction done (`idle` or a newer seq) within 0.3 m of the place, or once the pose is more than 0.02 m along the next lane and closer to it. `free`: the D-463 point 0.20 m ahead goes as a navigation goal. Ends: CORE `aborted`/`unresolved` for one of the trip's instructions, or `waiting` for 10 s, is `stopped` (`reason: junction`, `detail.junction_state`, `junction_reason`); D-507 3 (v1.126): on a `lane` segment CORE `unexpected`, or `waiting` with the next place farther than 0.6 m (`arm_distance_m`), is `stopped` at once (`reason: junction_unexpected`, `detail.junction_state`, `junction_reason`, `line_reason` = the robot's `line_follow.reason`; the trip `pose` is the map pose where it stopped); lap SIM A (v1.148): CORE `line_follow.reason` `junction_corner_hold` on our instruction (`junction.seq` ≥ the trip's first seq) is `stopped` at once (`reason: junction_corner_hold`, `detail.line_reason`), not after `stall_s`; D-507 2 (v1.139, 2026-10-08 user decision): a `left`/`right` that would go without the window pair (`expect_in_m`/`expect_tol_m`): a robot without `junction_pivot: true`, a plan whose map version is no longer active, no painted line within 0.30 m past the place, or the place outside (0, 2] m, is never sent and the trip is `stopped` at once (`reason: junction_no_window`, `detail.junction_place`, `junction_action`, `junction_fields` = the fields it would have carried or null), because a turn without a window could be taken at any sighting (a misread bend included); `straight` and `stop` are unchanged; a pose that is not `LOCALIZED` or more than half a lane width off the lane is `stopped` (`reason: pose`, with the provider's `sightings_filtered_map_id` and `odom_refused` in `detail`); less than 0.05 m of progress for `fleet.trip.stall_s` (default 20 s), outside a junction manoeuvre and a replan hold, is `stopped` (`reason: stall`); D-517 (v1.141): standing because the Fleet block table refuses the robot its next block is not a stall, and no `straight`/`left`/`right` goes to CORE while a block at or before that place is refused (CORE waits at the junction; the `waiting` timeout does not run); a goal the console did not send (queued behind traffic, yielding, untrusted) is `failed` (`TRIP_GOAL_REFUSED`, `detail.goal_reason`) and the robot's console queue is cleared, as at every free trip end; a robot error is `failed` (its code, or `TRIP_ROBOT_JUNCTION_UNSUPPORTED` for a 404 junction call, or `TRIP_ROBOT_UNREACHABLE`); a loop fault is `failed` (`TRIP_LOOP_ERROR`). Every end stops the robot at once (lane: junction `stop` and `PUT /api/v1/line-follow/mode {mode: OFF}`; free: navigation cancel; a free robot that lost its pose is left to its deadman) and records `detail.stop_sent` (and `detail.error`). A Fleet restart turns an open trip into `stopped` (`reason: restart`), stops that robot (retried every 10 s, at most 30 times, outside the loop tick, until it takes, the robot leaves the roster or a new trip takes the robot) and never resumes it. While a trip runs, Fleet refuses other motion for that robot with 409 `TRIP_ROBOT_BUSY`: `POST /api/fleet/robots/{robot_id}/goal` and `/route`, the durable task dispatcher (the robot is not available), `POST /api/fleet/formation/start`, `formation/reform`, `formation/resume`, `POST /api/fleet/robots/{robot_id}/line-stuck/decision` with `RESUME`, `BACK_AND_RETRY` or `YIELD`, and `POST /api/fleet/robots/{robot_id}/line-follow` with `IR_LINE`; the Fleet stuck resolver does not answer a trip robot. Stops are never refused, reach the robot first and then end the trip `canceled`: `POST /api/fleet/robots/{robot_id}/cancel`, `/api/fleet/cancel-all` and intent cancel (`reason: operator_cancel`), `POST /api/fleet/estop` (`operator_estop`), `line-follow` `OFF` (`operator_line_follow_off`), line-stuck `ABORT`/`MANUAL` (`operator_stuck_abort`/`operator_stuck_manual`; `WAIT` is forwarded and the trip goes on). Console traffic never asks a trip robot to yield and never hands it another robot's mission. `/trip` with `execute: true` still answers 501 `TRIP_EXECUTION_NOT_AVAILABLE`. D-541 7 (v1.162, Fleet side; default off): with site config `fleet.trip_lease_required: true`, after the pose check Fleet opens a CORE trip lease with the robot's REST token (`PUT /api/v1/trip-lease` `{lease_id` = a new uuid per trip, never reused`, trip_id, holder` = the Fleet site name`, operator_name` = the named operator`, ttl_s` = site config `fleet.trip_lease_ttl_s`, default 5, 1–10`}`); 422 `TRIP_LEASE_UNSUPPORTED` (the robot's `base_velocity` capability has no `trip_lease: true`), CORE's open refusals as 409 `TRIP_ROBOT_LEASED` (`TRIP_LEASED`), `TRIP_ROBOT_MANUAL` (`MANUAL_MODE`), `CALIBRATION_ACTIVE`, or `TRIP_LEASE_REFUSED` (any other, `detail.code`), 422 `TRIP_ROBOT_UNREACHABLE`; a later start refusal releases the lease. The trip view carries `lease` `{lease_id, state: held|lost|released, renewed_at, reason?}` or null. Every period Fleet renews it (same body) apart from the step; a renew answered 404 (CORE ended it: `detail.ended.reason` `taken_over`, `expired`, `mode_left`, `estop`), 409 or another 4xx, `renewed: false` (CORE restarted; that new lease is released at once, `core_restarted`), or no confirmed renew for `ttl_s` since the last confirmed one was sent (`renew_timeout`) ends the trip `stopped` (`reason: lease_lost`, `detail.lease_reason`, `lease_by` = CORE's `by`); a free robot gets a navigation cancel, a lane robot nothing; the lease is never opened again in that trip. Fleet's own stops inside a trip (a replan or lap hold, D-517 traffic, a free/lane switch) keep it. Every other trip end sends `DELETE /api/v1/trip-lease/{lease_id}` after its stop (404 if CORE already ended it). With the setting true the console token may not equal a robot REST token (startup error): the lease owner is that token and must be Fleet's own (D-541 1). D-601 (v1.192): for a plan whose first edge is `lane`, `TRIP_LINE_FOLLOW_NOT_ACTIVE` is now only `IR_LINE` or an unknown mode (a plan starting on a `free` edge still needs `CAMERA_LINE`): a robot with `mode` `OFF` starts, and after every check above, the trip lease and the trip opening, Fleet sends robot `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}` (the trip loop only; `POST /api/fleet/robots/{robot_id}/line-follow` still takes `IR_LINE`/`OFF`) and the view has `detail.line_follow_started: true`; a robot already on `CAMERA_LINE` gets nothing. A refusal or no answer ends the trip `failed` (`reason: TRIP_LINE_FOLLOW_START_FAILED`, `detail {error, status}`), stops the robot as every end, and the start answers 409 `TRIP_LINE_FOLLOW_START_FAILED` (after no answer at all, Fleet stops it once more after `port_timeout_s`); a cancel or E-stop that closes the trip meanwhile stops it again after the answer. Every trip end still sends `OFF`, also when the robot was on `CAMERA_LINE` before. After the pose check, a plan whose first edge is `lane` is refused 422 `TRIP_START_OFF_LANE` (the pose more than half the lane width from that lane) or `TRIP_START_HEADING_MISMATCH` (yaw unknown or more than site config `fleet.trip.start_heading_tol_deg`, default 20, at most 90, from the lane direction at the pose's projection), `detail {code, edge_id, heading_err_deg, tol_deg, off_lane_m}`; a `repeat` lap's next-lap check does not use it. |
| POST | `/api/fleet/trips/{trip_id}/cancel` | `operator` bearer (a stop; named until v1.160) | D-494 5 (v1.116): ends an open trip `canceled` (`detail.canceled_by`) and stops the robot now, without waiting for a loop tick in flight (a send that lands after it is stopped again): lane sends junction `stop` and then `PUT /api/v1/line-follow/mode {mode: OFF}` (robot `POST /line-follow/hold` extends a hold-to-run session and is not a stop), free sends a navigation cancel; `detail.stop_sent` false with `detail.error` when the robot did not take it. 404 `TRIP_UNKNOWN`, 409 `TRIP_NOT_RUNNING`. Audited. |
| POST | `/api/fleet/trips/{trip_id}/confirm-replan` | named `operator` | D-494 5 / D-489 9 (v1.116): a blocked remaining edge (or a changed map) replans only at the next place; a changed route sets `hold {reason: replan, plan, map_version, length_m, eta_s}` and the robot is held there (`stop`, or a goal at the place). This call switches the trip to `hold.plan`. 409 `TRIP_NO_REPLAN`, 409 `TRIP_REPLAN_FAILED` (`hold.plan` null, `hold.code` from the planner; cancel instead), 409 `TRIP_MAP_CHANGED` (the map changed after the hold; the trip plans again at the same place), 409 `TRIP_NOT_RUNNING`. Audited. |
| GET | `/api/fleet/trips` · `/api/fleet/trips/{trip_id}` | any configured user bearer | D-494 5 (v1.116): `{running: trip view or null, trips: [recent trip views]}` (D-517 1, v1.141: `running` is the most recently started open trip and `open` lists every open trip); one trip view, or 404 `TRIP_UNKNOWN`. While a trip is `started`/`running`, `POST /api/fleet/site-map/activate` answers 409 `SITE_MAP_ROUTE_ACTIVE` (replaces the v1.111 "`/route` stepped in the last 30 s" guard; `/route` itself is unchanged). |
| GET | `/api/fleet/traffic` | any configured user bearer | D-517 3 (M1, v1.141): read-only Fleet fixed-block table of the last trip period; nothing of it is sent to a robot (CORE authority is M2). `{map_version, block_length_m {edge_id: m}, units [{id, capacity, zone, two_way, state FREE/GRANTED/OCCUPIED/UNKNOWN, holders [robot_id], waiting [robot_id]}], robots [{robot_id, authority_end_m, front_d_m, convoy, waiting_for [robot_id], lap, trip_state}], loop_capacity [{edges, capacity, robots}], wait_cycle [robot_id] or null, unplaced [robot_id]}`. Blocks are cut per active map version with ℓ ≥ L + max(d_stop(v) + 2u, 0.45) (Pinky body, `RobotBody` stop gap + hysteresis, u = `expect_tol_min_m` + 0.05 × dead-reckoned m, at most with 1.5 m); zones from site config `fleet.traffic.zones {zone_id: {edges, capacity}}` (default none), a two-way lane outside a zone is one direction-locked zone. `authority_end_m` and the units are route metres from the start of each trip's first lane. A robot whose pose is not `LOCALIZED` keeps its last occupancy as `UNKNOWN`. A robot whose trip ended, or whose trip is on another map version, keeps its grants and last body as `UNKNOWN` until a fresh `LOCALIZED` map pose shows it clear of them (D-517 6); a map activation re-places every robot from its last `LOCALIZED` pose. While `unplaced` names a trip robot never localized, no trip gets a junction instruction. `loop_capacity` lists each loop: the edge set of one lap of an open `repeat` trip (its cycle via…, to, not the approach); `TRIP_LOOP_FULL` counts trips by that set and S by that lap's blocks. Empty lists before the first period or without an active map. D-517 4 (M2, v1.143): with site config `fleet.traffic.authority: true` (YAML boolean, default false) each trip whose robot advertises `line_follow_authority` gets `POST /api/v1/line-follow/authority` once per trip period after the table: `until_m` = its `authority_end_m` − its route position at the map pose the table used (clamped to [0, 10]), `pose_stamp` = that pose's `odom_stamp`, `ttl_s` 2, `leg_id` `{trip_id}:{route revision}`, never a smaller end on the same leg than already sent (plan metres, so dropped laps do not count as a shrink). At most one send per robot in flight, no retry inside a period; when sends stop the robot stops on expiry. A trip view carries `traffic_authority: core` (sent) or `hold_back` (M1 junction hold-back only) and `caps.line_follow_authority`; a trip robot standing at its authority end (CORE answered `HOLDING`) is not a stall. D-517 9 M3 (v1.146): `front_d_m` is the robot front the table used (route metres, null without a `LOCALIZED` pose); `convoy` is null except on a follower: `{leader, follows, gap_m}`. Each period a follower follows the nearest `LOCALIZED` member of its convoy (the leader or another follower of it, while the leader's trip is open) whose front, mapped onto the follower's route over the same arcs under that member's body, lies past the follower front − body − both u; `gap_m` is that member's rear minus the follower front. Its `authority_end_m` is then min(its fixed-block end, that rear − (d_stop(v) + 2u_follower + u_member)) with d_stop(v) the `RobotBody` stop gap + hysteresis at its `trip_max_linear`, and it may be granted a unit held by that member only (never another robot's) where the span reaches past that end; such a grant ends its fixed-block authority while it no longer follows that member and the member still holds the unit. Without a member to follow (unknown pose, not on the same arcs, leader trip ended: the convoy dissolves and the follower keeps lapping on fixed blocks) it is on fixed blocks. A follower never gets an end smaller than one it had: the row has `authority_end_m` null, nothing is sent and CORE stops on expiry, with `waiting_for` naming the member (not a stall). D-517 5 M4 (v1.149): `resolver` lists the robots Fleet's resolver took over this period as `[{robot_id, trigger, decision, cycle?, blocked_edges?, since?}]` (empty when none). `trigger: wait_cycle` (the robot is in `wait_cycle`): one member whose refused unit lies past its next place (not on its current segment, not on its last segment) gets `decision: replan` with `blocked_edges` (that unit's edges); the trip loop plans it again from just before its next place with those edges closed (D-489 9 `replan_hold`), so a changed route stands at that place as `hold.reason: replan` for a named operator to confirm and no route is `plan: null`; Fleet never switches a route by itself. The other members are `wait`. No member able to leave first, a replan already given on the same route (trip id and route revision), or an UNKNOWN member makes every member `human`. `trigger: unknown`, `decision: human`, `since` (Fleet epoch s): the robot has held an `UNKNOWN` unit for more than 30 s. |
| GET | `/api/fleet/robots/{robot_id}/path` | any configured user bearer | D-594 (v1.184): read-only recorded path `{robot_id, now, retention_s, use: "display-only", truncated, points: [{t, x, y, state, source, seg, map_id, trip_id, formation_id}]}`, oldest first. Query `since`·`until` (UTC epoch s, ≥ 0), or `last_s` (0 < s ≤ 86400, back from Fleet's `now`; not with `since`), optional `trip_id`; default the whole 24 h retention. At most 5,000 points: when more match, the newest 5,000 and `truncated: true`. Fleet writes one point per robot per second only in map coordinates: `state` LOCALIZED + `source` `robot` (the robot reports LOCALIZED in the map frame, D-395), else the D-494 3 map pose LOCALIZED/DEGRADED + `sighting`/`bridged`, else CAMERA_ONLY + `tracking` (D-457 marker, or a match to a verified map pose; display-only). A `localization: null` pose and odom are never recorded. A point is kept after 2 cm of travel, a change of state/source/map/trip/formation, or 30 s; a new `seg` starts after a tick without a point. Kept 24 h and at most 86,400 points per robot in the site DB (`--tasks-db`, table `fleet_robot_path`; in memory without one). 404 `UNKNOWN_ROBOT` off the roster; 422 `BAD_PATH_RANGE` for `since` with `last_s` or `until` < `since`. Traffic, routes, trips and stops do not read it |
| GET | `/api/fleet/robots/{robot_id}/map-pose` | any configured user bearer | D-494 3 (v1.113): read-only trip map pose `{robot_id, x, y, yaw, state LOCALIZED/DEGRADED/UNKNOWN, source sighting/bridged, dead_reckon_m, age_s, anchor_age_s, map_id, odom_refused, odom_refused_reason, sightings_filtered_map_id}`. Fleet anchors on each accepted `/api/fleet/sightings` row (lease 1 s, source token bound to the robot, `quality` ≥ `min_quality` when present, `map_id` equal to the active site map's when one is active, otherwise counted in `sightings_filtered_map_id`) paired with the robot's `odom_pose` (its `stamp` is UTC epoch seconds, like `captured_at`) at `captured_at`: sightings wait in order (up to 32, at most 3 s) for an odom sample at or after their capture, then are interpolated between two samples at most 1.2 s apart, else paired with the nearest sample within 0.25 s, and bridges with the odom delta since. `DEGRADED` after more than `max_dead_reckon_m` (1.5 m) or `max_bridge_turn_deg` (270°) of odom, an anchor in another map frame than the active one, an anchor older than `max_anchor_age_s` (10 s), or a sighting more than `max_jump_m` (0.15 m) / `max_jump_deg` (20°) off the bridged prediction (re-anchored; 2 consistent sightings recover, a first anchor needs the same 2). `UNKNOWN` (x/y/yaw null) before any anchor, with odom older than 3 s, and after an odom gap over 3 s or a step faster than `max_speed_mps` (1 m/s) or a turn faster than `max_turn_rate_dps` (360°/s) (an odom reset) until the next sighting. Odom stamped more than `max_odom_future_s` (0.5 s) ahead is refused and counted in `odom_refused`. Robot and site clocks must agree within 0.1 s. Limits come from site config `fleet.map_pose`. The read refreshes the robot state (hub snapshot when fresh, else REST; skipped while odom is under 0.2 s old); an unreachable robot answers its last odom. 404 `UNKNOWN_ROBOT`. Only trip execution uses this pose: `/route`, traffic and D-395 are unchanged. `odom_stamp` (v1.143, D-517 4): the `stamp` of the newest odom sample in a `LOCALIZED`/`DEGRADED` pose (null when `UNKNOWN`), the CORE authority's `pose_stamp`. `anchor_source` (v1.180, D-593): `sighting` \| `operator_pin` \| null; `source` is also `operator_pin` while no odom arrived since a pin. `bridge_turn_deg` (v1.180): summed odom heading change since the anchor. |
| POST | `/api/fleet/robots/{robot_id}/map-pin` | named operator (D-540 9) | D-593 (v1.180): body `{x, y, yaw}` (map frame, m, rad; finite, |x|,|y| ≤ 1000, |yaw| ≤ 2π). Fleet reads the robot state, then anchors the map pose on this pose at the newest odom sample (must be within `max_odom_age_s`, 3 s): `LOCALIZED` at once, `anchor_source: operator_pin`, bridged by odom under the same limits as a sighting anchor (1.5 m, 270°, 10 s). A later sighting is checked against it like any anchor (0.15 m / 20° → `DEGRADED`); sightings captured before the pin are dropped. Answer: the map-pose body. Errors: 404 `UNKNOWN_ROBOT`, 409 `MAP_PIN_TRIP_ACTIVE` (that robot is on a trip), 409 `MAP_PIN_ODOM_STALE`, 409 `MAP_PIN_POSE_INVALID`, 422 body. Site map event `map_pin` (principal, pose, map_id, the pose before). A pin is never a D-546 overhead decision to a robot. Trip start (D-593 7): a pin older than `start_anchor_age_s` (2 s) still starts while the robot has not moved since it (≤ 0.02 m, ≤ 2°). |
| GET | `/api/fleet/robots/{robot_id}/lane-compliance` | any configured user bearer | D-511 M0 (v1.128): read-only lane compliance `{robot_id, level OK/WARN/ACT/UNKNOWN, pose_state, edge_id, arc_id, offset_m, margin_m, width_m, body_half_width_m, warn_count, act_count, moving, map_version, at}`. A 2 Hz Fleet monitor projects the D-494 3 map pose onto the arcs of the active site map; an arc counts only when the foot point lies strictly inside it (not clamped to either end), within `max_lateral_m` of its centreline (default: that arc's `width_m`) and with its tangent within `heading_gate_deg` (45°) of the robot heading, and the nearest such arc is used (so a two-way edge or a junction takes the lane being driven): `offset_m` is signed against the arc tangent (left +), `margin_m = width_m/2 − (|offset_m| + body_half_width_m)` with the Pinky Pro URDF half width (`core_common.robot_body`). `WARN` after `persist_n` consecutive samples with `margin_m < warn_margin_m`, `ACT` after `persist_n` with `margin_m < 0`; `UNKNOWN` (edge/offset/margin null) when the pose is not `LOCALIZED`, no site map is active, or no arc passes those tests — a robot parked in a bay or yard off the graph, past a dead-end arc, crossing a lane, or backing along a one-way lane — and it restarts both counts; UNKNOWN is never a departure. Robots whose odom moved more than `moving_min_m` (0.01 m) or `moving_min_deg` (2°) within `fleet.map_pose.max_odom_age_s` get a REST state read per tick, cut at 0.5 s (`moving: true`); others are judged from their heartbeat odom. The console exception queue raises WARN/ACT only for `moving` robots and says the body is over the edge whenever `margin_m < 0`. Thresholds come from site config `fleet.lane_compliance` (`warn_margin_m` 0.02, `persist_n` 3, `act_timeout_s` 3.0, `max_lateral_m` null, `heading_gate_deg` 45, `moving_min_m` 0.01, `moving_min_deg` 2; provisional until measured). The same object is the `lane_compliance` field of each `GET /api/fleet/state` robot row (`null` before the first tick). Before the first tick the route answers `{level: UNKNOWN, pose_state: null, at: null}`. 404 `UNKNOWN_ROBOT`. Observe only: nothing is sent to the robot, and trip, `/route` and meet thresholds are unchanged (D-511 M1). v1.132 (D-472 addendum 3): when the map pose is not `LOCALIZED`, the robot's LED-confirmed track (`GET /api/fleet/tracking/identity`) is judged instead if it is `CONFIRMED`, its `age_s` lies within [−0.05 s, `fleet.map_pose.sighting_lease_s`] like a map pose sighting (`age_s` of `GET /api/fleet/tracking/identity` is not clamped at 0) and its `map_id` is the active site map; additive fields `pose_source` (`map_pose` \| `led_track`, the input judged) and `heading_source` (`pose` \| `track_motion` \| `none`): the blob has no yaw, so while the robot's odom says moving and the track moved more than `fleet.lane_compliance.track_heading_min_m` (0.05 m, provisional, above camera blob noise) the direction of that move is the heading, kept while the track stays fresh (a skipped camera frame repeats the position); before the first such heading (`none`) the nearest arc is taken without the heading gate, so on a two-way edge the offset sign may belong to the opposite arc and at a junction the nearest arc can be the crossing lane. A change of `pose_source` restarts `warn_count`/`act_count`. `pose_state` stays the map pose state. The track never feeds the map pose, trips, initialpose or commands. |
| GET / POST | `/api/fleet/teach` · `/api/fleet/teach/start` · `/stop` · `/confirm` · `/place` | GET any configured user bearer; POST named `operator` | D-494 6 (v1.119): teach a lane by driving it. Teach never sends anything to a robot (the driver moves it with Pilot). `POST /start {robot_id}` opens the one recording of the site (409 `TEACH_BUSY` with `detail.teach_id` and `detail.robot_id` of the recording, also when another start wins while the pose is read; 404 `UNKNOWN_ROBOT`; 422 `TEACH_POSE_UNTRUSTED` with `detail.state` when the robot's D-494 3 map pose is not `LOCALIZED`). Every 0.5 s Fleet reads the robot state over REST (`refresh(force_rest)`) and keeps the map pose only when it is `LOCALIZED` with `dead_reckon_m` ≤ 0.5 m (`DEGRADED` is never kept), at least 0.1 m from the last kept point (at most 20000 points). A recording that keeps no new point for 10 min, or reaches 20000 points, stops itself through the same stop path (site map event principal `system:teach_idle`, `detail.reason` `idle`/`full`; operator stops are `operator`) and then waits for confirm like any stopped recording. `POST /stop` (409 `TEACH_NOT_RECORDING`) ends it and returns `{teach_id, robot_id, points, kept, polyline, from_candidates, to_candidates, expires_at}`: the line simplified by Ramer–Douglas–Peucker (0.02 m, distance to the chord segment) and, per end, the existing places within 0.15 m nearest first `[{place_id, name, distance_m}]` (empty: suggest a new address). A line of fewer than 2 points or not longer than 0.10 m is 422 `TEACH_TOO_SHORT` and dropped. Stop never writes the map. `POST /confirm {teach_id, from, to, direction one_way/two_way, drive_mode lane/free, speed_cap_mps, width_m? (default 0.185), expected_revision?}` where `from`/`to` is a place id or `{name, kind?}` for a new address at that end appends one edge (ids `teach_eN`, new places `teach_pN`, line ends pinned onto the places, dropping leading/trailing interior points within 0.15 m of them) to the draft (or a copy of the active map, or an empty map) and saves it like `PUT /site-map/draft`: same `expected_revision` rule (409 `SITE_MAP_DRAFT_CHANGED`), 422 `SITE_MAP_INVALID` `detail.errors [{loc, msg}]`, 413 `SITE_MAP_TOO_LARGE` over 2 MiB. 422 `TEACH_UNKNOWN_PLACE`, `TEACH_PLACE_TOO_FAR` (a chosen place more than 0.15 m from that end, `detail.end`); 404 `TEACH_UNKNOWN` (confirmed already, or stopped more than 10 min ago: a stopped recording that is not confirmed is discarded 10 min after its stop). A refused confirm keeps the recording. 200 `{edge_id, draft}`. `POST /place {robot_id, name, kind?, expected_revision?}` adds an address at the robot's `LOCALIZED` map pose (with its yaw) to the draft the same way (422 `TEACH_POSE_UNTRUSTED`); 200 `{place_id, draft}`. `GET /api/fleet/teach` is `{recording: {teach_id, robot_id, started_by, started_at, points [[x, y]] (mm-rounded), last_kept_at, stopped_at: null, result: null} or null, pending: [stop results, newest first]}`. Recordings live in memory only (a restart drops them). Start, stop, confirm and place are site map events (`teach_started`, `teach_stopped`, `teach_confirmed`, `teach_place`) beside the HTTP audit; activation stays `POST /site-map/activate`. Errors are `{"detail": {"code", "detail"}}`, except request body validation (FastAPI's default 422). |
| POST | `/api/fleet/teach/place-from-marker` | named `operator` | D-564 (v1.168): `{marker_id, name?, kind?, place_id?, expected_revision?}`. 그 마커의 가장 새로운 신선한 관측(2 s 이내, source 설정과 같은 map·calibration revision)으로 `place_id`가 없으면 새 초안 장소(`name` 필수, 없으면 422 `PLACE_NAME_REQUIRED`, `kind` 기본 junction, yaw 포함)를, 있으면 그 장소의 x·y·yaw(와 준 이름·종류)를 바꾼다. 409 `PLACE_MARKER_STALE`(관측 없음·만료), 409 `PLACE_MARKER_MAP_MISMATCH`(활성 사이트 지도 또는 초안(활성·초안이 없으면 빈 지도 `site`)의 `map_id`와 다름), 404 `PLACE_UNKNOWN`, 422 `PLACE_MARKER_BEND`, 503 `PLACE_MARKERS_DISABLED`(장소 마커 source 없음), 초안 저장 오류는 `/place`와 같다. 응답 `{place_id, draft}`, 이벤트 `teach_place {marker_id, source_id, place_id, updated, revision}`. 로봇에 아무것도 보내지 않고 활성 지도는 바꾸지 않는다 |
| POST | `/api/fleet/do` (when `do` is `navigate`) | named `operator` (D-540 9, v1.161) (any verb other than `estop`, `cancel`, `stop`, `formation_stop`, `follow_cancel`) + `Idempotency-Key` | Uses the same task service; each navigation step gets a deterministic child key from the request key and step position. |
| GET | `/api/fleet/tasks/{task_id}` | any configured user bearer | Returns the durable task projection and append-only status history. |
| POST | `/api/fleet/tasks/{task_id}/cancel` | `operator` bearer | Cancels a task only while it is still queued; it does not cancel a goal already dispatched to CORE. |
| POST | `/api/fleet/cancel-all` | `operator` bearer | D-421 (v1.81): non-latching site-wide driving cancel. In order: queued tasks of every robot become `CANCELED` with reason `FLEET_CANCEL_ALL` and the operator as actor (dispatch latch and generation unchanged); an open formation is stopped; then per robot, concurrently, `POST /api/v1/swarm/cancel`, `POST /api/v1/navigation/cancel`, `PUT /api/v1/line-follow/mode {mode: OFF}`, each attempted even when an earlier one failed. It never calls `safety/stop`/`safety/release`, `/mode`, signals or OMX stop. Each request writes a durable record in the task journal database (`fleet_cancel_all`: id, principal, opened/closed times, robot ids, canceled queued task ids, robots whose navigation cancel was answered; closed records older than 30 days are pruned when a window opens) and tags the in-flight dispatch attempts of those robots by `(task_id, attempt_id)` (`ACCEPTED`, `RUNNING`, mid-dispatch `QUEUED`, and `UNKNOWN` changed since the window opened or not already canceled). Dispatched tasks are not rewritten by Fleet: a correlated CORE `nav.canceled` (evidence that a cancel was issued, not of standstill, D-298) moves a tagged task to `HOLD` with reason `FLEET_CANCEL_ALL`, which releases its robot claim, so in-flight robots become dispatchable once CORE confirms the cancel. The event must match the tagged attempt, its `data.source` (when present) must be `api:*`, and the window must be open, or closed at most 30 s ago with that robot's navigation cancel answered or a fence re-cancel; other later cancels stay `UNKNOWN`. A dispatch started inside the window is tagged before its CORE goal call, and tagging settles an attempt whose `nav.canceled` already arrived during the window. Correlated events and dispatch receipts arriving after `HOLD(FLEET_CANCEL_ALL)` are logged, not applied. If the record cannot be written the fanout continues and the response carries `record_error: "CANCEL_ALL_RECORD_UNAVAILABLE"`; without that event the task stays as it was (`ACCEPTED`/`UNKNOWN`), the robot stays claimed and the task needs reconciliation (no operator reconcile route exists yet). An untagged `nav.canceled` still yields `UNKNOWN`/`CORE_CANCEL_RESULT_PENDING`. `tasks.awaiting_core_result` lists per robot the `ACCEPTED`/`RUNNING` tasks plus `UNKNOWN` tasks changed since the window opened. A dispatcher CORE goal call that overlaps the request (including a task submitted and dispatched inside the window) is inspected when it ends: an explicit CORE reject stays `FAILED`/`COMMAND_REJECTED`; a dispatch left in Fleet's own traffic queue with no live CORE goal becomes `CANCELED`/`FLEET_CANCEL_ALL`; otherwise the task is tagged, Fleet sends `navigation/cancel` to the robot and to any robot it sent to a bay for it, and the task becomes `UNKNOWN`/`FLEET_CANCEL_ALL_DURING_DISPATCH` (no retry); a goal call that raised is re-canceled the same way and keeps its existing classification. 200 even on partial failure: `{cancel_all_id, record_error, cancelled, total, evidence: "CORE_REPLY_ONLY", robots[{robot_id, result: cancelled\|failed\|unreachable, steps{swarm, navigation, line_follow: {ok, error?{reachable, sent?, code, message}}}, tasks{awaiting_core_result[]}}], formation{stopped, state, error?}, tasks{canceled[], error}}`; `sent: false` marks a step Fleet's D-361 address gate refused locally (`ADDRESS_UNVERIFIED`; `line-follow/mode` is not a stop path because a path-level gate would also allow turning it on). `cancelled` = all three CORE calls replied 2xx; `unreachable` = no call got a reply; otherwise `failed`. A reply is not physical stop evidence (D-298). Repeating the request is safe. Normal audit gate applies (`503 AUDIT_STORAGE_UNAVAILABLE`); the D-330 audit exception stays with `/api/fleet/estop`. |
| GET | `/api/fleet/line-stuck` | any configured user bearer | D-407 (v1.77): returns the board as of the last shared gather (it does not contact the robots) as `{pending[], answers[], observed_age_s}`; `observed_age_s` is null before the first gather. D-438 (v1.91): one shared gather feeds both `GET /api/fleet/state` and the stuck resolver loop and is reused for up to 1 s, so with the resolver running the board is at most about 1 s old even when no console is open. `pending` has one row per robot whose CORE `line_follow.stuck` is open: the CORE `LineStuckStatus` fields plus `robot_id`, `front_clearance_m`, `rear_clearance_m`, `turn_clearance_m`, `rear_blind_m`, `preview_seq` (from the `nav.line_stuck_opened` FleetAgent event, `null` when not received; `opened_event` says which), `robot_online` (false = last value kept while the robot is unreachable), `observed_age_s`, `fleet_answer` (the last forwarded answer for this stuck id; `ESCALATE` rows are not answers and are skipped) and `resolver` (D-438, see `.../line-stuck/claim`). `answers` is the recent forwarded-answer record `{robot_id, stuck_id, decision, principal_id, accepted, outcome, code, message, audit_id, tier, rule, escalated, at}` (`accepted` null = outcome unknown). The same row appears as `line_stuck` on each robot of `GET /api/fleet/state`. D-517 5 M4 (v1.149): the resolver also answers a robot on an open Fleet trip, with the stopping `WAIT` only (rule `R1`, a peer in the front band); any other rule (back-off, yield, resume) escalates that stuck to a human (`escalated: no_rule`), as D-494 14 refuses moving decisions on a trip. |
| GET | `/api/fleet/robots/{robot_id}/line-stuck/evidence?stuck_id=` | any configured user bearer | D-577 8 (v1.182): the open stuck's one evidence picture, `{robot_id, stuck_id, sequence, source, media_type: image/jpeg, age_s, jpeg_base64}`; `age_s` is the frame's age (CORE `age_ms` at the read plus the time since). The first read asks the robot (`GET /api/v1/vision/front/status`, then `/front/frame?sequence=` with Fleet's robot credential, 3 s limit); Fleet keeps that one frame in memory only while the stuck is open (never disk, bus or event; dropped when the stuck closes or is replaced) and later reads serve it without asking the robot again. 404 `STUCK_NOT_OPEN` (no open stuck with that id on the board, or it closed during the read), 404 `STUCK_PREVIEW_UNAVAILABLE` (`message` = the robot's code, e.g. `CAMERA_FRAME_UNAVAILABLE`; a failure is not kept, the next read asks again). The picture is display evidence only; nothing reads it as a rule input. One still per stuck, not a relay: D-136 T1 (no video or preview relay routes in Fleet) stays. |
| GET | `/api/fleet/line-stuck/episodes` | any configured user bearer | D-407 (v1.121): durable stuck episodes, newest first, `?limit=` 1-1000 (default 100), as `{episodes[]}`; empty when Fleet runs without `--tasks-db`. One row per `(robot_id, stuck_id)` from the same board transitions (no extra robot calls): `source` (`fleet_poll`, so times are poll resolution, about 1 s, and a stuck shorter than one poll can be missed), `cause`, `phase_at_open`, `local_enabled_at_open`, `trip_busy_at_open` (null before the trip runner is wired), `peer_ahead_at_open` (the D-438 R1 band test; null = no own pose), `opened_at`, `closed_at` (UTC ISO), `held_s_max`, `attempts_max` (CORE `held_s` is the duration of record), `close_reason` `cleared`\|`replaced`\|`left_roster`\|`fleet_restart` (an episode still open at start-up; the same `stuck_id` seen again reopens the row and keeps the first `opened_at`), `resolved_by` from the last non-`ESCALATE` answer (`human`\|`rule` when accepted, `<tier>_unconfirmed` when the outcome is unknown, null when only refused or unanswered), `resolved_principal`, `last_answer_tier`, `escalation_code` (the last `ESCALATE` row's `escalated`), and `pose_x`, `pose_y`, `pose_yaw`, `pose_state`, `pose_age_s` (Fleet map pose at open, null without the map pose service). An unreachable robot's episode stays open. |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/decision` | `operator` bearer for `WAIT`·`ABORT`; named `operator` (D-540 9, v1.161) for `RESUME`·`BACK_AND_RETRY`·`MANUAL` | D-407 (v1.77): `{stuck_id, decision: WAIT\|RESUME\|BACK_AND_RETRY\|MANUAL\|ABORT}`; permission by value (D-540 9, v1.161): WAIT and ABORT stay open to any `operator` like the CORE route; RESUME, BACK_AND_RETRY, MANUAL and YIELD need a named operator (403 `OPERATOR_IDENTITY_REQUIRED`), and on a robot under a D-541 trip lease CORE answers the moving values from a non-owner token with 409 `TRIP_LEASED`; `stuck_id` 1-64 chars of `[A-Za-z0-9_.:-]` (CORE ids are `stuck-<12 hex>`), extra fields 422. Forwarded unchanged to that robot's `POST /api/v1/line-follow/stuck/decision` with the robot credential; Fleet never refuses on CORE's behalf. 200 `{robot_id, actor_id, answer, result}` (`result` is CORE's body incl. `outcome`). A CORE 409 (`STUCK_ID_MISMATCH`, `STUCK_DECISION_REFUSED` with its reason, `EMERGENCY_ACTIVE`, `CALIBRATION_ACTIVE`) is returned as 409 `{code, message, robot_id, robot_status}` with CORE's code and message verbatim; other robot error statuses are 502 with the same body, unknown robot 404. A transport failure is 502 `{code, message, robot_id, transport}`: `ROBOT_UNREACHABLE` when the connection was never made (not delivered), `STUCK_DECISION_OUTCOME_UNKNOWN` on a timeout or a dropped reply (CORE may have applied the answer; re-read the stuck before answering again). Every forwarded answer is recorded with the site principal in memory and, with durable task storage, in the `fleet_line_stuck_answers` table of the Fleet journal database, keyed by the API audit `request_id` (§10.10). D-438 (v1.91) nullable columns: `tier` (`human` for this route, `rule` for a resolver answer), `rule` (`R1`–`R3`, resolver only), `escalated` (hand-off reason). Every resolver hand-off to a human is its own row with `decision: "ESCALATE"`, `accepted` null, `tier: "human"`, `escalated` = the reason and `principal_id: "fleet-resolver"`. A database created before v1.91 gains the three columns when Fleet opens it (rows written before stay null). |
| POST | `/api/fleet/robots/{robot_id}/line-stuck/claim` | `operator` bearer (D-540 9: open, the console claims before an `ABORT` confirm) | D-438 (v1.91): `{stuck_id}` — 사람이 그 막힘을 맡는다. 판단기는 맡은 막힘에 답하지 않고 `human_claimed` 로 올린다. 200 `{robot_id, stuck_id, claimed_by}`, 모르는 로봇 404 `UNKNOWN_ROBOT`. `.../line-stuck/decision` 도 404 확인 뒤 먼저 맡고, CORE 전달이 실패해도 맡음을 유지한다. 로봇 행 `line_stuck.resolver` = `{tier, rule, decision, escalated, at, age_s}` 또는 null(escalated 사유: `no_rule`, `rule_budget`, `deadline`, `restuck_after_resume`, `estop`, `calibration`, `no_resolver_token`, `human_claimed`, `core:<CODE>`, D-577 `lane_lost_hold:<peer_behind|peer_unknown|attempts|local_disabled|crosswalk|crosswalk_unknown|pose|refused|rule_budget>`, v1.187 같은 이유의 `no_motion_hold:<…>`). 2026-10-10 (v1.187): CORE `no_motion` 막힘은 `lane_lost` 와 같은 조건으로 R6 `BACK_AND_RETRY`(조건이 모두 참) 또는 R5 `WAIT` + 사람(`no_motion_hold:<이유>`)이고 `RESUME`·`YIELD` 는 나가지 않는다. 뒤 띠는 `localization` 을 보고하는 신뢰 지도 자세로만 잰다: 동료가 온라인인데 자신이나 동료가 LEGACY(odom)이면 `peer_unknown`(D-577 남은 항목 1). 현장 설정 `fleet.stuck_resolver.enrolled_robots`(로봇 id 목록, `--site-config`)에 적은 등록(D-361) 로봇은 판단기가 Fleet 의 등록 CORE 자격(operator, `STUCK_DECIDE` 포함)으로 답한다. 기본은 빈 목록이다. D-577 1 (v1.173): `lane_lost` 막힘에 R3 `BACK_AND_RETRY`는 로컬 복구 켜짐·시도 남음·규칙 예산 남음·R3 거절 없음·CORE 상태의 `line_follow.crosswalk`가 `null`(키가 없으면 지금의 모든 CORE처럼 보고 안 함 → `crosswalk_unknown`, 객체면 `crosswalk`; D-573 구현은 구역 밖에서 `null`을 낸다)·Fleet 지도 자세가 `LOCALIZED`이고 `age_s` ≤ 2 s이거나 그 로봇의 목격 출처가 한 번도 없어 `UNKNOWN`(출처가 있었는데 `UNKNOWN`이면 `pose`)·뒤 띠(R1 띠의 반대쪽, D-395 신뢰 지도 자세로만 잼)에 동료 없음일 때만이다. 다른 로봇이 온라인인데 자신이나 그 로봇의 신뢰 자세가 없으면 `peer_unknown`. 아니면 R5가 `WAIT`을 보내고 같은 주기에 `lane_lost_hold:<이유>`로 사람에게 올린다(`tier: human`, `rule: R5`, `decision: WAIT`; CORE가 `WAIT`을 거절해도 올리고, 전송 실패면 `WAIT`을 한 번 다시 보낸 뒤 올린다). R5는 막힘마다 한 번이고 규칙 예산을 쓰지 않는다. `lane_lost`에 `RESUME`·`YIELD`는 어떤 경로로도 나가지 않는다. `age_s`는 그 메모 뒤 초이고, 콘솔은 30 s 넘게 답이 없는 올림 행을 큐 맨 위로 올린다(콘솔만, 로봇은 계속 HOLD). 판단기 답은 `principal_id: "fleet-resolver"` 로 기록하고, 전송 실패는 `ROBOT_UNREACHABLE` 이면 `accepted=false`, 아니면 null. 설정: `robots.yaml` 의 `resolver_token`(비어 있지 않은 따옴표 문자열, `token`·`fleet_pairing_token` 과 달라야 함). D-577 2 (v1.173): `fleet console` 은 판단기를 기본으로 돌리고 `--no-stuck-resolver` 로 끈다(`--stuck-resolver` 는 호환용, 효과 없음). 시작할 때 판단기가 답할 로봇(`resolver_token` 있음)을 stderr 에 적는다. 자격(`resolver_token`)이 없는 로봇의 막힘은 지금처럼 `no_resolver_token` 으로 사람에게 간다. `robots.yaml` 로봇만 판단기 클라이언트를 가진다(등록 D-361 로봇은 아직 없음) |
| POST | `/api/fleet/robots/{robot_id}/line-follow` | `operator` bearer for `{mode: "OFF"}`; named `operator` (D-540 9, v1.161) for `IR_LINE` | Forwards the bounded line-follow selection to CORE `PUT /api/v1/line-follow/mode`. OFF stops, so it stays open |
| POST | `/api/fleet/formation/start` · `/reform` · `/resume` | named `operator` (D-540 9, v1.161) | D-20 formation. `formation: TRAIL` (D-559, v1.170) = COLUMN slots, every follower armed with `mode: trail` and `distance` = slot × spacing behind the leader on its path; a follower whose follow reply lacks `mode: trail` is disarmed and the start fails `ARMING_FAILED` (`TRAIL_NOT_SUPPORTED`). D-581 (v1.176): while the leader streams `frame: odom`, Fleet re-expresses each frame in each follower's odom from the ceiling-camera map pose (§7.8 `anchor`); while an anchor is missing the follower gets `anchor_hold` samples, not silence; formation status carries `anchor: {followers: {robot_id: "<robot>:no_map_pose|anchor_stale|map_pose_degraded|anchor_jump|map_id_differs|leader_odom_mismatch" or null while sending usable samples}, robots: {robot_id: {anchor_age_s, residual_m, residual_deg, jumped}}, jumps}` (null when no map pose service), and `stream_evidence[robot_id].anchor_hold` repeats a follower's reason (frames flow, the follower stands). `/api/fleet/formation/stop` stays `operator` bearer (a stop) |
| POST | `/api/fleet/signals/{signal_id}/command` | `operator` bearer for `mode` `all_red`·`flash_red`; named `operator` (D-540 9, v1.161) otherwise | D-443 physical signal. `manual` without any configured credential still answers 401 `UNAUTHORIZED` first |

v1.136: 진행 중인 lane trip의 `detail.bend_candidate`는 읽기 전용 지도 굽이 **후보**다. 현재 활성 지도 버전이 trip과 같고, 자세가 `LOCALIZED`이며 나이 ≤0.30 s, dead reckoning ≤0.05 m, 현재 edge 중심선에서 ≤0.04 m, 투영 진행 거리 차 ≤0.05 m, 접선과 yaw 차 ≤15°일 때만 기록한다. 값은 `{map_id, map_version, arc_id, bend_in_m, heading_change_deg, map_offset_m}`이며 0.40 m 앞까지의 edge polyline에서 접선 변화 ≥15°와 전체 변화 ≤80°를 찾는다. 다음 tick에서 근거가 사라지거나 trip이 끝나면 삭제한다. CORE로 보내는 지시나 운동 허가가 아니며 페인트·벽·분기의 같은 경계 확인을 뜻하지 않는다.

**D-608 Fleet 사건 보고서 (additive).** `GET /api/fleet/incidents?limit=1..100`(viewer+, 기본 20)은 `{reports:[...],traffic_reports:[...]}` 최신순이다. 각 `rosy.incident.v1` 행은 `id: "line_stuck:<robot_id>:<stuck_id>"`, `stuck_id`, `classification: "line_stuck"`, `robot_ids`, `opened_at`, `closed_at`, `evidence`(`core`, `fleet`, `rosy_cam`, `ai_facts`, `front_image`), `actions`, `reviews`를 가진다. `rosy_cam`은 같은 DB의 사건 시작 ±5 s 수락 관측 1건 또는 null, `ai_facts`는 같은 로봇·시간대의 최대 3건이며 둘 다 원인 확정 근거가 아니다. `front_image.status: "requestable_while_open" | "not_retained"`는 D-577의 메모리 한정 사진이 닫힌 뒤 남지 않았다는 뜻이다. `POST /api/fleet/incidents/{robot_id}/{stuck_id}/review`(이름 있는 operator)는 `{root_cause, note}`를 받는다. `root_cause`는 `line_marking|obstacle|robot_fault|localization|traffic_wait|unknown`, `note`는 최대 1000자다. 검토는 append-only이며 성공 `{reviewed:true}`, 사건 없음 404 `INCIDENT_NOT_FOUND`, 잘못된 본문 422다. 사건·검토는 움직임 권한이나 모델 승격 권한을 주지 않는다.

같은 응답의 `traffic_reports[]`는 별도 D-577 AI 상황 사실(`wait_cycle_confirmed`, `wait_cycle_stale_input`, `waiting_but_moving`, `livelock`, `stalled`, `unknown_occupancy_long`) 최신순이다. `id: "ai_fact:<fact_row>"`, `classification`은 사실 종류, `evidence.ai_fact`는 원래의 값·출처·stage·시각, `evidence.core`·`fleet`·`rosy_cam`은 직접 연결된 표본이 없으면 null이다. `POST /api/fleet/incidents/facts/{fact_row}/review`는 같은 본문·권한·응답·오류 계약이고, 검토는 `fleet_ai_fact_reviews`에 누적한다. AI `wait_cycle_confirmed`의 `value.fleet_agrees: false`는 Fleet의 순환과 다른 AI 단독 판단이다. 이 보고서가 Fleet 통행권이나 CORE 명령을 변경하지 않는다.

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
| POST | `/api/fleet/enrollment/robots` | named operator | D-361 화면 코드 등록 `{code, discovery_name}` 또는 `{code, address}`. D-565 (v1.169): HTTPS(`tls=required`) 대상에 등록 행이 없으면 아직 등록되지 않은 승인 binding(`rosy.enrolled-tls/1`) 중 `hostname`·`port`가 같은 하나로만 TLS(그 CA·호스트 이름, 코드 전 identity `receiver_id`)로 짝짓고, `system/info` `robot_id`가 binding과 같을 때만 저장한다. 409 `tls_binding_required`(맞는 binding 없음), 409 `tls_binding_required`는 승인 binding이 가진 이름·주소를 HTTP로 등록하려 할 때도 요청 전에 낸다. 409 `tls_binding_mismatch`(코드 전 identity `receiver_id`가 binding과 다름, 코드는 나가지 않음), 409 `code_consumed` reason `tls_binding_mismatch`(코드 뒤 `system/info` `robot_id`가 binding과 다름) 또는 reason `tls_binding_required`(binding이 가진 ID·이름이 HTTP로 답함), 둘 다 토큰 로그아웃, 502 `unreachable`(binding 이름을 찾지 못함). HTTP로 내려가지 않는다 |
| POST | `/api/fleet/robots/{robot_id}/hub-link` | named operator | D-555 (v1.163): issue (or rotate) the enrolled robot's hub credential, store only its SHA-256, deliver it once with `PUT /api/v1/fleet/link` over the TLS-bound enrollment. 409 `tls_binding_required` (plain-HTTP enrollment), `hub_link_unavailable` (no `--hub-link-hostname`/`--hub-link-ca`, `--events-db` or console token), `robot_unsupported` (no `fleet_link_provisioning`), `not_active`; 502 `unreachable`, `robot_refused` (digest rolled back). 409 `fleet_goal_active` when a Fleet goal runs (this console's goal table or the robot's `fleet_goal_active`, or CORE's `FLEET_GOAL_ACTIVE`). Rotation drops the hub session made with the old credential. Returns the enrollment row |
| DELETE | `/api/fleet/robots/{robot_id}/hub-link` | named operator | D-555 (v1.163): 409 `fleet_goal_active` as above unless `?force=true` (named operator, confirmed in the console): then the digest and hub session are cleared during the goal too and the robot's SAF-003 STOP/HOLD applies (audit `forced_…`). Otherwise the digest is cleared and the hub session dropped first, then one robot `DELETE /api/v1/fleet/link` attempt behind the TLS fence (a changed or missing binding gives `robot_cleared: false`). `{…row, robot_cleared, was_linked}`. Enrollment rows add `hub_linked`, `hub_host`, `hub_online`, `hub_state` (`online` \| `checking` within 35 s of delivery or Fleet start \| `failed`), `hub_linkable` (never the digest) |

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
| POST | `/api/fleet/dispatch/rearm` | named site operator (D-540 9, v1.161: reopening dispatch starts queued tasks) | explicitly opens dispatch at a new generation and attempts configured local OMX re-arm; stale generation, unresolved action, or any local re-arm failure returns 409 |

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

D-535 이유 코드(v1.155, additive): 위 거절은 상태와 기존 `detail`을 그대로 두고 ERR-101
`error {code, message, detail{action, retry, …}}`을 더한다. HTTP로 온 요청 403 `TLS_REQUIRED`,
수신 초기화 불가 503 `PAIRING_UNAVAILABLE`, LAN 밖 최초 요청 403 `LAN_REQUIRED`, 없는 관계
409 `PAIRING_REQUIRED`, 철회·발급자 회수 409 `APPROVAL_REVOKED`, 다른 수신 키·옛 수신 키 요청
`IDENTITY_CHANGED`, 관계 만료 409 `APPROVAL_EXPIRED`, 사라진 요청(없는 id·틀린 비밀 구분 없음)
409 `APPROVAL_TIMEOUT`, 끝난 요청의 확인·취소·결정은 상태대로(`APPROVAL_TIMEOUT`·`APPROVAL_DENIED`·
`APPROVAL_CANCELLED`; 이미 승인된 요청은 기본값 `PAIRING_REQUIRED`, 요청자는 상태를 읽는다),
틀린 화면 코드 400 `APPROVAL_CODE_WRONG`(`detail.remaining_attempts` 유지, 다섯째 `APPROVAL_DENIED`),
역할 초과 403·틀린 코드 전체 한도 429 `CONSOLE_APPROVAL_REQUIRED`, 모든 한도 `RATE_LIMITED` +
`Retry-After`(상태 읽기 간격 2 s, 나머지 60 s; 예전에 409였던 한도는 409 그대로).
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

anonymous identity 호출은 D-533에 따라 source별 300회/분으로 따로 센다.
challenge/session 증명 호출은 기존 source별 합계 30회/분을 유지한다. 두 예산 모두
crypto 전에 적용하고 source map 최대 128개로 admission하며 한도는 429다. 최초 신청의 별도 30회/분
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
| v1.194 | 2026-10-10 | 동작 변경 (D-573 6 개정·D-577 남은 항목 2·3, feat/crosswalk-null-outside-zone, Safety-Review 대상): CORE 는 `line_follow.crosswalk` 를 게이트 설정과 무관하게 늘 보고한다(게이트 기본값은 여전히 꺼짐). 값은 게이트 객체, 새 `{state: inside}`·`{state: ahead}`, 새 `{state: unknown, reason: pose_stale\|perception_stale\|not_watched\|zone_unplaced}`, 또는 null(구역 밖이 증명됨). 게이트를 켠 로봇도 이제 증명하지 못하면 null 대신 `unknown` 이다. Fleet 판단기는 `unknown` 을 R5 `crosswalk_unknown` 으로 막고, 현장 지도 횡단보도 0.29 m 안(신뢰 지도 자세)이면 R5 `crosswalk`, 지도에 횡단보도가 있는데 신뢰 지도 자세가 없으면 R5 `crosswalk_unknown` 이며, R5 를 보낸 막힘의 재전송은 같은 R5 로만 하며(R3·AI 답으로 바뀌지 않음), Fleet 정지로 끊긴 R5 도 사람 행을 올린다. 계약(같은 버전): `LaneContainmentEvidence` 선택 필드 `crosswalk_uncertainty_m`(m, 0–1, 영상 시각 몸 좌표에서 횡단보도 가까운·먼 끝의 앞뒤 최악 한도, 검출기가 돈 모든 프레임에 있음, 없음 = 돌지 않음). CORE 설정 `line_follow.crosswalk_max_uncertainty_m`(0.058). 필드가 없거나 한도를 넘으면 `unknown` 사유 `camera_crosswalk_unadmittable`; 구역 앞뒤 여유는 그 필드(차선 `uncertainty_m`은 옆만). 인식은 이 버전의 CORE가 로봇에 들어간 뒤 플래그로 낸다(기본 꺼짐). envelope 1.0 변경 없음 |
| v1.193 | 2026-10-10 | 동작 변경 (D-596 개정 2026-10-10 사용자 결정 (a)(b), feat/led-confirm-anywhere-pin-prefill): `matched` 판정이 파랑 점멸(`evidence.mode`가 `steady` 아님)이면 예상 자리 밖이어도 `far_from_robot` 없이 이름을 붙인다(source마다 파랑 요청은 하나). 주황과 정색 표시는 예상 자리 안에서만. 콘솔 "위치 찍기"는 지도 자세가 `LOCALIZED`가 아니고 `GET /api/fleet/tracking/identity`에 `CONFIRMED` 트랙이 있으면 그 자리를 핀 위치로 쓴다(방향은 운영자). 새 필드 없음 |
| v1.192 | 2026-10-10 | Behavioural + Additive (D-601, feat/trip-start-enables-camera-line): Fleet `POST /api/fleet/trips/{plan_id}/start`이 `lane` 계획에서 로봇 line-follow `OFF`를 거절하지 않고, 모든 시작 검사·trip lease·trip 열림 뒤 마지막으로 로봇 `PUT /api/v1/line-follow/mode {mode: CAMERA_LINE}`을 보낸다(trip 루프만; 운영자 `line-follow` 경로는 그대로 `IR_LINE`·`OFF`). 실패는 trip `failed`(`TRIP_LINE_FOLLOW_START_FAILED`) + 멈춤, 응답 409. 끝에서는 지금처럼 언제나 `OFF`. 새 시작 거절 422 `TRIP_START_HEADING_MISMATCH`(첫 차로 방향과 `fleet.trip.start_heading_tol_deg` 20° 넘게 다름)·`TRIP_START_OFF_LANE`(차로 반폭 밖), `detail {code, edge_id, heading_err_deg, tol_deg, off_lane_m}`. `/trip`: `lane` 계획은 로봇 `GET /api/v1/vision/front/status` `available`이 아니면 422 `TRIP_LANE_CAMERA_UNAVAILABLE`, 응답에 `start_check`(같은 검사), `TRIP_HEADING_CONFLICT` `detail.heading_err_deg`·`TRIP_START_OFF_MAP` `detail.off_lane_m`. 로봇 API 변경 없음. |
| v1.191 | 2026-10-10 | 동작 변경 + Additive (D-596 개정 2026-10-10·D-494 6항 개정, fix/marker-loss-auto-relocalize): `POST /api/fleet/robots/{id}/identify` 409 `IDENTIFY_ROBOT_CAUTION`(로봇이 주의 표시 중: 차선 HOLD 또는 도킹 실패, rosy-face가 점멸을 거절함). 자동 요청과 `matched` 확인의 예상 자리는 Fleet 지도 자세(반경 `auto_near_m` + odom 1 m마다 0.15 m, 최대 1.0 m), 없으면 마지막 마커 자리. 점수 0.1 미만 blob은 자동 규칙에서 세지 않음, 주의 중인 로봇은 자동으로 묻지 않음. Vision 판정 `processor_revision` `led-identity/3`(고리 2.6 r, S≥60, V≥120). `GET /api/fleet/robots/{id}/map-pose`: 서 있는 로봇은 sighting 사이가 10 s보다 길어도 일치 2회로 `LOCALIZED` |
| v1.190 | 2026-10-10 | Additive (D-511 개정 1, feat/fleet-lane-return): Fleet `GET /api/fleet/robots/{robot_id}/lane-compliance`와 `/api/fleet/state` 행 `lane_compliance`에 `return` `{state: ON_LANE|ON_LINE|OFF_LANE|OFF_MAP|WRONG_WAY, since, raw, edge_id, offset_m, side, bearing_deg, lane_heading_deg, turn_deg, entry, crosswalk, crosswalk_ahead}`(첫 판정 전 null). 설정 `fleet.lane_compliance` 새 키 `line_half_width_m`·`off_map_pad_m`·`off_map_unseen_s`·`return_persist_s`·`wrong_way_min_m`·`entry_ahead_m`·`crosswalk_ahead_m`·`return_cue`(기본 true). 켜져 있으면 Fleet이 로봇에 `POST /api/v1/line-follow/lane-cue`를 2 Hz로 보낸다(그 경로가 없는 CORE는 404, 60 s 뒤 다시). 콘솔 예외 한 줄 |
| v1.189 | 2026-10-10 | Additive (D-589 S1, feat/rosy-cam-recognition-tuning): `OverheadDetectionsPayload` 선택 필드 `tuning` `{state off/waiting/tuning/locked/paused/unsupported, score 0–1 또는 null, ev 실제 EV 또는 null, locked}`, `GET /api/fleet/tracking` `sources[].tuning`(lease 안, 아니면 null). `rosy-overhead/1` hello 뒤 텍스트 메시지 두 가지(공유 벡터 `overhead-ingest.v1.json` `messages.camera_example`·`camera_state_example`): 하향 `camera {seq, ev(보정 지수), ae_lock, awb_lock, max_exposure_us, antibanding}`, 상향 `camera_state {seq, applied{…, mode vision/local/disabled/thermal_hold}, supported{ev_min, ev_max, ev_step, …}, exposure_us, iso, thermal}`. `site-cameras.yaml` source 키 `auto_tune`(기본 true; Fleet은 읽고 무시). 표시 전용, 로봇 명령·envelope 1.0 변화 없음 |
| v1.188 | 2026-10-10 | Additive (D-577 개정 2026-10-10 AI PC 판단, feat/ai-pc-judge): 새 `POST /api/fleet/ai/proposals`(`ai_observer`; 사용자 결정 "AI PC 제안 → Fleet 검증 후 실행": Fleet이 봉투를 검증해 CORE에 결정으로 보내거나 규칙으로 되돌아감, `fleet_ai_proposals` 감사, `GET /api/fleet/ai` `proposals[]`). AI 사실 종류 `rear_blocked`·`path_blocked_by_robot`(분석기 `analyzer:stuck_scene@1`). 현장 설정 `fleet.stuck_resolver.ai_facts_acting`(로봇 id 목록, 기본 빈 목록)의 로봇에서 이 두 종류는 `stage: acting`이 되고, 살아 있는 동안 판단기의 후진 답(R2·R3·R6)을 R5 `WAIT` + 사람(`<cause>_hold:ai:<kind>`)으로 바꾼다. 다른 답은 만들지 않는다. 로봇 API 변경 없음. |
| v1.187 | 2026-10-10 | Behavioural + Additive (D-407·D-577 개정 2026-10-10, feat/stuck-5s-fleet-ai): CORE 설정 `line_follow.stuck_report_s`(기본 5.0, 0 = 끔, [0, 60]). 활성 차선 모드에서 결정이 그 시간 동안 0 이고 다른 막힘 원인이 없으면 막힘 `cause: no_motion`·`detail` = HOLD 사유를 열고 로컬 후진 없이 관제 답만 기다린다(`nav.line_stuck_asked` `reason: no_motion`). Fleet 판단기: `no_motion` 에 R6 `BACK_AND_RETRY`(R3 조건) 또는 R5 `WAIT` + 사람(`no_motion_hold:<이유>`); R3/R6 뒤 띠는 LEGACY odom 자세를 받지 않는다(`peer_unknown`); 현장 설정 `fleet.stuck_resolver.enrolled_robots`. 콘솔 원인 표시 `no_motion`. envelope 1.0 변경 없음 |
| v1.186 | 2026-10-10 | Additive (D-600, feat/background-relearn-with-robots): `GET /api/fleet/detections/config` `occupied`, `OverheadDetectionsPayload.unknown_floor`(선택, `OK`만), `GET /api/fleet/tracking` source `unknown_floor`, `POST /api/fleet/tracking/relearn` 응답 `occupied`·`unlocated`. Robot API와 envelope 1.0 변경 없음 |
| v1.185 | 2026-10-10 | 동작 변경 + Additive (D-596, feat/led-identity-active): `POST /api/fleet/robots/{id}/identify` 서 있는 로봇도 요청(`IDENTIFY_NOT_MOVING` 제거), source마다 색 하나씩 동시 요청(두 번째 로봇은 남은 색), 응답 `trigger`. detections config `identity_challenges`, `GET /api/fleet/tracking/identity` `pendings`·`last.trigger`·`config.auto_min_interval_s`. 사이트 `identity.auto_request` 기본 true와 자동 요청 규칙(`auto_marker_missing_s`·`auto_near_m`·`auto_min_interval_s`). CORE `POST /host/lamp/identify` 쿼리 `quiet`(자동 요청은 소리 없음, 다음 로봇 payload부터)와 Fleet 기본 색 파랑(자동은 파랑만, 마커가 계속 안 보이면 30 s→2 min→5 min), `matched`는 요청 로봇의 예상 자리 0.5 m 안(`far_from_robot`·`no_prediction`). Vision 판정 `processor_revision` `led-identity/2`(끔 0.8–2.2 s, 프레임 간격 1.1 s까지, 익명 blob 하나일 때 정색 표시 `evidence.mode:"steady"`). 확인 트랙은 여전히 D-511 입력·표시 전용 |
| v1.184 | 2026-10-10 | Additive (D-594, feat/fleet-robot-path-history): Fleet `GET /api/fleet/robots/{robot_id}/path`, the robot path Fleet records each second in map coordinates only (robot LOCALIZED map report, else D-494 3 map pose LOCALIZED/DEGRADED, else ceiling-camera CAMERA_ONLY), kept 24 h in the site DB. The console map trail draws this record (range 2 min / 10 min / this trip, per robot, solid/dashed/dotted by state) instead of building it from polled poses; a `localization: null` pose (may be odom) is no longer drawn. Robot API and envelope 1.0 unchanged |
| v1.183 | 2026-10-10 | Additive (D-577 3·4·5·8, feat/d577-ai-pc-situation-skeleton, shadow only): site-users 새 역할 `ai_observer`(토큰만, 콘솔 로그인 없음) — 모든 GET은 viewer처럼 읽고, 쓰기는 `POST /api/fleet/ai/facts`·`POST /api/fleet/ai/heartbeat`만 통과한다. 그 밖의 모든 쓰기 경로(비상정지·정지·막힘 답·trip·목표 포함)는 그 경로 자신의 guard와 무관하게 403 `AI_OBSERVER_FACTS_ONLY`. 새 `GET /api/fleet/ai`(viewer+). 막힘 행(`line_stuck`)에 `ai {state, owner_mode}`·`ai_facts[]`. 사실은 `fleet_ai_facts`(`--tasks-db`)와 메모리에만 두고 `stage: shadow`로 규칙 입력이 되지 않는다. AI PC 서비스 `operations/situation`(`rosy-situation`). 로봇 API 변경 없음. |
| v1.182 | 2026-10-10 | Additive (D-577 8, uiux/d577-queue-evidence-notify): Site Fleet 새 경로 `GET /api/fleet/robots/{robot_id}/line-stuck/evidence?stuck_id=`(viewer+) — 열린 막힘 하나에 로봇 앞 카메라 그림 한 장(`{robot_id, stuck_id, sequence, source, media_type, age_s, jpeg_base64}`). Fleet은 첫 읽기에 로봇 `GET /api/v1/vision/front/status`·`/front/frame?sequence=`로 받고 막힘이 열린 동안 메모리에만 둔다(디스크·버스·사건 없음, 막힘이 닫히면 버림). 404 `STUCK_NOT_OPEN`·`STUCK_PREVIEW_UNAVAILABLE`(실패는 남기지 않아 다음 읽기가 다시 묻는다). 콘솔 예외 큐의 막힘 행이 답 아래에 그림·프레임 번호·촬영 나이를 보이고, 행이 생기면 소리·브라우저 알림 한 번, 30 s 무응답이면 한 번 더 한다(로봇은 HOLD). 로봇 API 변경 없음. |
| v1.181 | 2026-10-10 | Behavioural + Additive (D-407 개정 2026-10-10, fix/keep-auto-resume): CORE CAMERA_LINE `LOST`는 차선이 다시 보이면 같은 모드로 자동으로 이어 간다. 설정 `line_follow.lost_auto_resume`(기본 true)·`lost_resume_frames`(3, = D-495 `junction_reacquire_frames`)·`lost_resume_s`(1.0, = D-407 `recovery_settle_s`); 조건은 연속 신선·확신 프레임, 앞 물체 정지 없음, IR 감시 비어 있음(또는 꺼짐). 사건 `nav.lane_reacquired` `{mode, frames, since_s}`. 상태·사유 문자열은 그대로이고 IR_LINE의 재선택 잠금도 그대로 |
| v1.180 | 2026-10-10 | Additive (D-593, feat/operator-map-pin-anchor): Fleet `POST /api/fleet/robots/{robot_id}/map-pin` (named operator), map-pose `anchor_source` (`sighting` \| `operator_pin`), `bridge_turn_deg` and `source` value `operator_pin`; trip start accepts a still operator pin up to 10 s old (`fleet.trip.pin_start_still_m` 0.02, `pin_start_still_deg` 2). Robot API and envelope 1.0 unchanged |
| v1.179 | 2026-10-10 | Additive (D-573 2·3·4·6, feat/crosswalk-core-gate, Safety-Review 대상, 기본 꺼짐): CORE line-follow 횡단보도 게이트. 설정 `line_follow.crosswalk_gate_enabled`(기본 false, URDF 몸 필요)·`crosswalk_look_s`(1.0)·`crosswalk_look_min_scans`(8)·`crosswalk_report_s`(10)·`crosswalk_cross_speed`(0.04)·`crosswalk_approach_default_m`(0, 보기 영역은 카메라가 본 차로 안쪽 경계 사이). 출처는 D-491 카메라 구역(Fleet 힌트는 나중). `GET /line-follow`·상태 `line_follow.crosswalk`(꺼짐이면 키 없음, 구역 밖 null), 막힘 원인 `crosswalk_blocked`와 `stuck.detail`, 그 원인의 움직이는 답 거부(`crosswalk_gate`). 꺼져 있으면 동작·응답 변경 없음. envelope 1.0 변경 없음 |
| v1.178 | 2026-10-10 | 동작 변경 + Additive (D-525 rev 6, feat/signal-occupancy-default): 가상 신호의 새 기본 모드이자 Fleet 재시작 상태는 `occupancy`(점유 기반)다(이전 `all_red`). 이 모드에서 신호는 D-517 구역 허가에 단계 관문을 더하지 않고(모든 입구 허용, 수용 1이 한 대만 들임) 등은 살아 있는 구역 상태에서 나온다: 비어 있음 모두 `green`, 허가만 쥠 그 입구 `green`·나머지 `yellow`(화면 주황), 점유·모름 모두 `red`. `POST /api/fleet/traffic/signals/{id}` 동사 `occupancy` 추가. `GET /api/fleet/traffic` `signals[]` `occupancy {state free\|reserved\|occupied\|unknown, holder, approach}`, `mode: occupancy`이면 `aspect`는 요약이고 `left_s`·입구 `left_s` null, `green_in_s`는 초록 0 아니면 null. `signal_ahead`(로봇 행과 `GET /api/fleet/traffic/signals/ahead/{robot_id}`)에 `mode`·`occupancy`. 설정 오류 신호의 입구 `lamp`는 늘 `red`. 등은 표시·참고이고 허가는 D-517만 준다. Robot API, D-551 advice `lamp` 값(green/yellow/red), CORE 명령과 envelope 1.0 그대로 |
| v1.177 | 2026-10-10 | Additive (D-587, feat/ceiling-marker-sightings): `SiteSightingPayload.calibration_source` 값 `approved_record`(승인 추적 보정으로 투영한 이름 있는 천장 로봇 마커, `corner_marker_ids: null`, revision = 그 source의 지금 승인 기록, 아니면 409 `CALIBRATION_MISMATCH`). `site-cameras.yaml` source 선택 키 `marker_yaw_offset_deg: {robot_id: deg}`(스티커 윗변 방향 − 로봇 앞, 반시계 +, 유한, 절댓값 360 이하; 그 source의 로봇만, `robot_ids: enrolled`이면 아무 로봇). 옛 Vision·Fleet은 이 키를 모른다며 시작을 거절하므로 릴리스 뒤에 설치한다 |
| v1.176 | 2026-10-10 | Additive (D-581, feat/trail-fleet-anchored-frame): §7.8 `anchor: fleet`·`for_robot_id`·`anchor_age_s`·`anchor_hold`(기준이 없을 때 침묵 대신 정지 표본, `swarm.hold` `anchor_withheld`, `stream_evidence[*].anchor_hold`) — TRAIL 대형에서 리더가 `frame: odom` 이면 Fleet 이 천장 카메라 기준(D-494 3)으로 팔로워마다 그 팔로워 odom 좌표의 표본을 만들어 보낸다(D-31 개정, `map` 프레임은 바이트 그대로). trail 팔로워는 자기 id 표본만 받아 자기 `odom_pose` 로 달린다. `swarm.hold` 사유 `reference_anchor_invalid`·`reference_frame_changed`, `swarm/state` `trail.anchor`, Fleet formation 상태 `anchor`. 안전 경로(D-422·SAF-004·D-400·스트림 단절) 변화 없음 |
| v1.175 | 2026-10-09 | Additive (D-580, feat/fleet-managed-site-roster): `GET /api/fleet/detections/config` `robot_markers`. `site-cameras.yaml` source `robot_ids: enrolled`(Fleet 명단을 따른다; `GET /api/fleet/site-map` 등의 `robot_ids`·`robot_markers`는 등록·해제 때 바뀐다). `POST /api/fleet/enrollment/robots`: 등록되었다 해제된 TLS binding은 다른 `robot_id`를 받는다(새 오류 코드 없음, 다른 binding의 ID면 `code_consumed` reason `robot_id_conflict`); 감사 동작 `tls_renumber`. `autoupdate.conf` `/api/fleet/state` 검사 `required_ids: "enrolled"` |
| v1.174 | 2026-10-09 | Additive (D-573 1, feat/crosswalk-fleet-map-zones): `rosy.site_map/1` 선택 필드 `crosswalks[] {id, polygon, approach[], lanes[], revision}`(lane_graph 다각형, 차로는 유도, 대기 띠는 편집기에서 그림; 차로에 닿지 않거나 D-507 9 바닥 밖이면 `SITE_MAP_INVALID`), `GET /api/fleet/site-map/lane-graph-crosswalks`(`SITE_MAP_NO_LANE_GRAPH`). 지도 자료와 표시만, CORE·교통·통행권 변경 없음 |
| v1.173 | 2026-10-09 | 동작 변경 (D-577 (a), feat/d577-resolver-default-lane-lost, Safety-Review 대상): `fleet console` 의 막힘 판단기 기본 켜짐(`--no-stuck-resolver` 로 끔, `--stuck-resolver` 는 호환용). `lane_lost` R3 `BACK_AND_RETRY` 조건 좁힘(로컬 복구·시도·예산·거절 없음·CORE가 `line_follow.crosswalk: null` 보고·Fleet 지도 자세 신선 또는 목격 출처 없음·신뢰 자세로 잰 뒤 띠 비어 있음; 모르면 닫힘)과 새 R5(`WAIT` + 사람, escalated `lane_lost_hold:<이유>`). 로봇 행 `line_stuck.resolver.age_s` 추가. 자격 없는 로봇과 trip 로봇(D-517 M4) 동작은 그대로. Robot API·envelope 1.0 변경 없음 |
| v1.172 | 2026-10-09 | 동작 변경 (D-517 3 개정, fix/trip-lap-hold-outside-zone, AI PC 신호 SIM): 현장 구역이 있으면 trip이 구역 안에 서지 않는다. 구역 차로로 들어오는 목적지나 반복 운행 바퀴의 마지막 장소는 경로를 따라 구역 밖에 설 수 있는 가장 가까운 장소로 옮긴다(사용자 결정 "다음 지점까지 가서 섬"). trip 보기 선택 필드 `stop_moved {from, to}`(옮기지 않았으면 null), 구역 옆 장소의 `stop`은 `stop_after_m`을 줄여 구역 밖에서 선다. 그런 장소가 경로에 없을 때만 `POST /api/fleet/trips/{plan_id}/start` 422 `TRIP_STOP_IN_ZONE`(`detail {place, repeat}`). 출발 차로를 고를 때 막힌 차로를 뺀다. Robot API·CORE 명령·envelope 1.0 그대로 |
| v1.171 | 2026-10-09 | Additive (D-575, fix/ceiling-marker-missed-and-unassigned): `GET /api/fleet/tracking` `unknown[].marker_id`(익명은 null, 배정 로봇 없는 마커는 그 id). Vision은 `robot_markers`에 없는 D-562 로봇 범위 마커(40–49)도 검출 payload에 싣는다(스키마 변화 없음). 표시 전용, 로봇 명령·envelope 1.0 변화 없음 |
| v1.170 | 2026-10-09 | Additive (D-559, feat/swarm-trail-follow): `POST /api/v1/swarm/follow` 선택 필드 `mode: offset\|trail`(기본 offset, 이전과 같다), `GET /api/v1/swarm/state` 의 `mode`·`trail`, §7.8 `payload.frame: map\|odom`, `swarm.hold` trail 사유, `swarm.aborted` `trail_join_too_far`, Fleet `formation: TRAIL`. trail 은 CORE 가 NAVIGATION 슬롯을 직접 조향한다(SAF-004 클리핑·D-400·D-422 몸체 정지를 지난다). envelope 1.0 유지 |
| v1.169 | 2026-10-09 | 동작 변경 (D-565, fix/fleet-tls-renumber-enroll, 보안 검토 대상): `POST /api/fleet/enrollment/robots`가 등록 행이 없는 HTTPS 로봇을 아직 등록되지 않은 승인 binding으로 등록한다(CA·호스트 이름·`robot_id` 셋이 맞아야 함). 새 오류 409 `tls_binding_mismatch`. Fleet 기동은 등록되지 않은 binding을 거절하지 않고 경고한다(다른 등록 행의 호스트 이름이면 계속 거절). v1.167·v1.168은 다른 브랜치(D-560·D-564)가 선점 |
| v1.168 | 2026-10-09 | Additive (D-564, feat/ceiling-place-markers): 바닥 장소 마커 `POST`/`GET /api/fleet/place-markers`(source token, 2 s), `POST /api/fleet/teach/place-from-marker`(이름 있는 운영자, 초안 장소 추가·이동), 공유 스키마 `PlaceMarkerPayload`, 사이트 카메라 설정 `place_markers`. 표시·가르치기만, 로봇 명령 없음. v1.166은 다른 브랜치(feat/route-context-bend-phase)가 쓴다 |
| v1.167 | 2026-10-09 | Additive (D-560 S1, feat/rosy-cam-map-plane): Vision 미리보기 lease `rectification`에 `{"mode": "map"}`(다른 필드 없음). Vision이 추적용 승인 보정 기록으로 원본을 지도 평면(track_bounds_m + 0.15 m, 400 px/m, 긴 변 ≤ 1920 px)에 펴서 `X-Frame-Rectified: map`·`X-Frame-Plane`·`X-Frame-Calibration`과 함께 돌려주고, 기록이 없거나 source·map·렌즈·비율이 다르면 409 `X-Frame-State: plane-unavailable`(원본 대체 없음). `manual`·`auto`와 원본 프레임·추적 불변. 스키마·envelope 1.0 변경 없음 |
| v1.166 | 2026-10-09 | Additive (D-531 굽이 단계 보완, 기본 꺼짐): `line/route_context`의 선택 필드 `bend_phase: bending|reacquiring`. CORE 굽이 진행·재획득 단계의 B9 기대 굽이 창을 표시한다. Fleet 경로 지시와 CORE의 최종 주행 권한은 그대로이며 실물 재생·SIM·DEVICE 수용은 별도 |
| v1.165 | 2026-10-09 | Additive (D-531 P1, 기본 꺼짐): CORE `line/route_context` 경로 증거, `line_follow.route_context`·`route_context_published_at_s` 상태, `base_velocity.route_context` 능력, 인식 `route_context_seq` 역검증. 기존 주행 판단 불변; P2/P3와 SIM·DEVICE 별도 검증 |
| v1.164 | 2026-10-09 | Additive (D-546 5–7 첫 조각, feat/d546-pose-request, Safety-Review 대상): `GET /api/v1/localization/request`, 오류 `NO_REQUEST`, 이벤트 `localization.request`·`localization.request_cleared`. lane_return(D-468)이 `pose_stale`(1 s 이상) 또는 `fleet_required` 에서 CORE 의 위치 요청을 열고 닫는다. 기존 필드·경로는 그대로이며 옛 Fleet 은 요청을 읽지 않을 뿐이다. 장치 기본값(`localization` 꺼짐)은 그대로다. |
| v1.163 | 2026-10-09 | Additive (D-555, feat/enrolled-hub-pairing, 보안 검토·Safety-Review 대상): `GET`/`PUT`/`DELETE /api/v1/fleet/link`(TLS 리스너, 관리자 또는 사이트 등록 토큰), 능력 최상위 `fleet_link_provisioning`, 사건 `fleet.link_provisioned`·`fleet.link_cleared`, 오류 `FLEET_GOAL_ACTIVE`·`FLEET_LINK_CONFIG_INVALID`(409), `GET` `arm_state`·`arm_deadline_s`, Fleet 강제 해제 `?force=true`. SAF-003 `configured` 는 지금 설정을 읽는다(실행 중 페어링·해제를 따른다). Fleet `POST`/`DELETE /api/fleet/robots/{robot_id}/hub-link`, 허브는 등록 로봇 HELLO 를 digest 로 확인. 스키마 변경 없음 — envelope 1.0 유지 |
| v1.162 | 2026-10-09 | Additive (D-541 7 Fleet side, feat/fleet-trip-lease-holder, Safety-Review 대상): 사이트 설정 `fleet.trip_lease_required`(기본 false)·`fleet.trip_lease_ttl_s`(기본 5, 1–10). 참이면 `POST /api/fleet/trips/{plan_id}/start` 가 CORE trip lease 를 열고(trip 마다 새 uuid `lease_id`), 주기마다 renew, 끝에서 정지 뒤 DELETE. 새 시작 거절 422 `TRIP_LEASE_UNSUPPORTED`, 409 `TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`CALIBRATION_ACTIVE`·`TRIP_LEASE_REFUSED`. 새 끝 `stopped`/`lease_lost`(`detail.lease_reason` `taken_over`·`expired`·`mode_left`·`estop`·`leased`·`core_restarted`·`renew_timeout`, `lease_by`), 다시 열지 않음. trip 보기 `lease`. 거짓이면 이전과 같다. Wi-Fi 끊김이 `ttl_s` 를 넘으면 trip 이 끝난다(현장별 10 s까지) |
| v1.161 | 2026-10-09 | 권한 변경 (D-540 9, fix/fleet-named-operator-motion-routes, Safety-Review 대상): 로봇을 움직이는 Fleet 경로는 이름 있는 운영자만. 공유 콘솔 토큰과 자격 없는 루프백(`site-console`)은 403 `OPERATOR_IDENTITY_REQUIRED`(자격 없음·틀림은 그대로 401). 대상: `POST /api/fleet/robots/{robot_id}/goal`, `/line-follow`(`OFF` 제외), `/route`, `/identify`, `/line-stuck/decision`(`RESUME`·`BACK_AND_RETRY`·`MANUAL`), `POST /api/fleet/dispatch/rearm`(발행 재개가 대기 작업을 움직인다), `POST /api/fleet/formation/{start,reform,resume}`, `POST /api/fleet/signals/{signal_id}/command`(`all_red`·`flash_red` 제외), `PUT`·`DELETE /api/fleet/start-points/{source_id}`, `POST /api/fleet/do`(`estop`·`cancel`·`stop`·`formation_stop`·`follow_cancel` 만인 요청 제외). 멈춤은 어느 운영자에게나 열림: `/api/fleet/estop`, `/cancel-all`, `/robots/{robot_id}/cancel`, `/tasks/{task_id}/cancel`, `/formation/stop`, 막힘 `WAIT`·`ABORT`와 `/line-stuck/claim`(콘솔이 `ABORT` 확인 전에 맡는다), 그리고 `POST /api/fleet/trips/{trip_id}/cancel`(v1.116–v1.160 은 이름 있는 운영자였다). 이미 이름이 필요했던 `POST /api/fleet/cell-jobs/{mission_id}/cancel`(HOLD 작업만 끝내고 점유를 푼다, 움직임을 세우지 않음)과 `POST /api/fleet/teach/stop`(녹화만 끝낸다, 로봇에 명령 없음)은 멈춤이 아니라 그대로 둔다. 이름 있는 운영자 = `site-users.yaml` 자격·D-519 로그인 쿠키·D-473 개발 세션. 현장 이행은 D-540 9 운영 메모(배포 전 `site-users.yaml` 로그인 줄). 스키마·envelope 1.0 변경 없음 |
| v1.160 | 2026-10-09 | Additive (D-550 10 목표 임대, feat/navigation-goal-lease, Safety-Review 대상): `POST /api/v1/navigation/goal` 선택 필드 `lease_ttl_s`(0 < s ≤ 5, `correlation_id` 필요), `POST /api/v1/navigation/goal/lease` 구현, 오류 `GOAL_LEASE_NOT_ACTIVE`(409), 능력 `controls` `base_velocity.goal_lease`. 임대 만료는 `nav.canceled` source `goal_lease`(사건 모양 변화 없음). `lease_ttl_s`가 없는 목표는 v1.159 와 같다. Fleet 쪽: 설정 `fleet.goal_lease_ttl_s`(기본 0 = 끔), `POST /api/fleet/goal-lease/presence`(이름 있는 운영자). envelope 1.0 변화 없음 |
| v1.159 | 2026-10-09 | Additive + 동작 변경 (D-548, feat/device-dev-profile): 이벤트 `auth.development_mode` `{marker}`. 장치 모드 CORE 는 `/etc/rosy/dev-mode` 가 있을 때만 공용 개발 토큰 `rosy-dev-*` 를 받는다(없으면 D-193 7 그대로). 그 토큰은 장치에서 `/host/ssh*`·`/auth/enrollment-codes` 전부와 `/host/*`·`/system/tokens*`·`/system/dds*` 쓰기에 403 `FORBIDDEN`. Fleet `--mission-api` 는 `--users-file` 대신 개발 연결 모드로도 시작. 스키마 변경 없음 — envelope 1.0 유지 |
| v1.158 | 2026-10-09 | Additive (D-526 1단계, feat/fleet-tether-watch, Safety-Review 대상): Fleet tether 감시. `GET /api/fleet/tethers` 행에 `watch {state, trip, distance_m, turn_deg, pose_age_s, stop_sent, stop_error}`(첫 틱 전 null); 반경+0.15 m·누적 회전 405°·지도 자세 2 s 없음이면 기존 로봇 E-Stop을 보내고 그 로봇의 trip을 `tether_trip`으로 끝낸다. 테더 POST가 감시를 다시 시작한다. 신뢰하는 지도 자세(LOCALIZED·map)만 지도 자세이고 `localization`이 없으면 2 s 안에 정지한다. 목록에 `watch_age_s`, `watch`에 `stop_failures`·`tick_age_s`, E-Stop 10회 실패는 관제 `alarms`의 `TETHER_STOP_FAILED`. 로봇 API·envelope 1.0 변경 없음 |
| v1.157 | 2026-10-09 | Additive + 동작 변경 (D-541 CORE 부분, feat/core-trip-lease, Safety-Review 대상): `PUT /api/v1/trip-lease`, `DELETE /api/v1/trip-lease/{lease_id}`, `POST /api/v1/trip-lease/takeover`; 상태 선택 필드 `trip_lease`·`trip_lease_ended`(없으면 키 없음); 능력 `base_velocity.trip_lease`; 오류 `TRIP_LEASED`·`MANUAL_MODE`; 이벤트 `trip_lease.opened|renewed|ended|shared_token`. 동작 변경은 lease 가 살아 있을 때만: 주인 아닌 `/mode`·`/teleop`·구동 쓰기 409 `TRIP_LEASED`, `POST /calibration/session` 409 `TRIP_LEASED`, `/ws/swarm/reference` 주인 아닌 프레임 버림, 주인 아닌 `navigation/cancel`·line-follow OFF 는 lease 를 끝내고 IDLE, 주인의 `navigation/goal` 은 line-follow 가 켜져 있어도 받음, 만료·넘겨받기는 IDLE, 끝난 `lease_id` 의 PUT 은 404(다시 열지 않음), `localization/mission` 409·`decision`·`suspect` 423 `TRIP_LEASED`, DOCKING 에서 열기 409 `MODE_CONFLICT`. lease 가 없으면 동작은 v1.156 과 같다. Fleet 쪽 코드(`TRIP_ROBOT_LEASED`·`TRIP_ROBOT_MANUAL`·`TRIP_LEASE_UNSUPPORTED`)는 Fleet 구현(D-541 7, feat/fleet-trip-lease-holder)과 함께 싣는다. envelope 1.0 변화 없음 |
| v1.156 | 2026-10-09 | Additive (D-551, feat/core-line-advice): `POST /api/v1/line-follow/advice` 구현(표시만, 허가 아님), `GET /line-follow` 선택 키 `advice`, 능력 `controls` `line_follow_advice`. 공유 schema `core_common.protocol.line_advice` |
| v1.155 | 2026-10-09 | Additive (D-535, feat/connect-failure-reasons): 연결 이유 코드 21개(ERR-102 행, 기계 원천 `connect-reasons.v1.json`). `/api/v1/auth/peer-pairing/*` 거절에 기존 상태·`detail`을 두고 `error {code, message, detail.action, detail.retry}`를 더함, 한도 거절에 `Retry-After`. `GET /api/v1/auth/connection`에 `connect_contract`·`api`·`core_ready`·`stage`·`release`·`tls_hostname`·`pairing`, 출발지별 30회/분 429, LAN 밖 403 코드 `LAN_REQUIRED`(이전 `FORBIDDEN`). Fleet `GET /api/fleet/state` 로봇 행 선택 필드 `link_reason {code, message, action, retry}`. envelope 1.0 변화 없음 |
| v1.154 | 2026-10-09 | 동작 변경 (D-520 개정 2026-10-09, fix/d520-arc-entry-tangent·feat/d520-arc-radial-tracking·docs/d520-default-on-ring, Safety-Review 대상): `line_follow.arc_enabled` 기본 켬, 능력 `lane_arc` 는 그 설정·`site_floor_map_id` 선언·`ir_guard_speed_scale` > 0 이 함께 있을 때만 참(선언 없는 켬은 시작 거부가 아님); 409 `LANE_ARC_UNAVAILABLE` 은 그 능력이 거짓일 때; 호 명령에 odom 지도 원으로의 반지름·방향 보정(\|c\| ≤ 1.5 1/m), 원과 0.075 m 넘게 떨어지면 HOLD `lane_arc_edge`, 첫 IR 판정이 원을 옮김. 스키마 필드 변경 없음. Fleet 은 `exit_segment` 가 있는 회전에도 `turn_target` 회전각을 보낸다 |
| v1.153 | 2026-10-09 | Additive (D-524 Proposed, feat/host-control, Safety-Review 대상): `GET /api/fleet/hosts`(운영자, 행에 `stoppable_units`)와 `POST /api/fleet/hosts/{host}/control`(이름 있는 운영자). 409 `REBOOT_ALREADY_SCHEDULED`·`NO_HOST_CONTROL_REBOOT`, 503 `HOST_HELPER_UNAVAILABLE`, 502 `HOST_HELPER_FAILED`. 사이트 유닛은 재시작만. envelope 1.0 변경 없음 |
| v1.152 | 2026-10-08 | Additive (lap SIM 2, fix/junction-corner-hold-scope, Safety-Review 대상): `POST /line-follow/junction` 선택 필드 `lane_turn_deg`(`straight` + 기대 창, −360…360); `junction_corner_hold` 는 지시와 어긋나는 모서리에서만(`left`/`right` 의 반대쪽, `straight` 는 `lane_turn_deg` 가 그쪽 20° 미만이거나 없을 때). Fleet 이 `straight` 에 지도 차로 방향 변화를 싣는다. envelope 1.0 그대로 |
| v1.151 | 2026-10-08 | Additive (D-517 M5 발견 1, fix/d517-trip-authority-mismatch, Safety-Review 대상): `POST /api/fleet/trips/{plan_id}/start` 422 `TRIP_AUTHORITY_SITE_OFF` — 사이트 `fleet.traffic.authority` 가 꺼져 있는데 로봇 능력 `line_follow_authority_required` 가 참이면 `lane` trip 을 열지 않는다(통행권이 나가지 않아 CORE 가 서 있고 trip 이 20 s 뒤 `stall` 로 끝나던 것). CORE 동작 변경 없음. envelope 1.0 변경 없음 |
| v1.150 | 2026-10-08 | Additive (D-361 S4 identity readback): robot `GET /api/v1/system/info` includes provisioned `device_uid` (or null); on a provisioned Pi with no configured serial, `serial_number` reads the CPU serial (or remains null). Fleet enrollment can store both on a new pairing; existing rows are unchanged. Envelope 1.0 and motion authority unchanged |
| v1.149 | 2026-10-08 | Additive (D-517 5 M4, feat/d517-m4-fleet-resolver, Safety-Review 대상): `GET /api/fleet/traffic` `resolver [{robot_id, trigger wait_cycle\|unknown, decision replan\|wait\|human, cycle, blocked_edges, since}]`; a wait cycle replans one member around the unit it waits for as an operator-confirmed `hold.reason: replan`; the D-438 stuck resolver answers trip robots with `WAIT` only. Robot API, CORE commands and envelope 1.0 unchanged |
| v1.148 | 2026-10-08 | Additive (lap SIM A, fix/junction-corner-hold, Safety-Review 대상): CORE HOLD 사유 `junction_corner_hold`(기대 창이 있는 지도 지시가 `armed` 이고 `line/keep_debug` `strategy` 가 기대 가로선 0.45 m + `expect_tol_m` 안에서 `corner_left`·`corner_right`, 2 s 래치; 그 정지 중 만료되면 새 지시나 모드 변경까지 HOLD). Fleet trip `stopped` `junction_corner_hold`(자기 지시에서 바로). envelope 1.0 그대로 |
| v1.147 | 2026-10-08 | Additive (uiux/robot-navigation-stage): `GET /api/v1/navigation/state`에 `mapping_active`를 추가해 CORE 맵핑 세션 수락 상태를 읽는다. 실제 SLAM Toolbox 실행 증거는 아니다. 같은 브랜치의 `/navigation/path` 수신 `map_id`·`frame_id`·`age_s`도 명시한다. 주행 권한과 envelope 1.0은 그대로다. |
| v1.146 | 2026-10-08 | Additive (D-517 9 M3, feat/d517-m3-lane-convoy, Safety-Review 대상): Fleet `POST /api/fleet/robots/{robot_id}/trip` `convoy {leader}` (with `repeat`), start refusals `TRIP_CONVOY_SELF`, `_LEADER_NOT_RUNNING`, `_LEADER_IS_FOLLOWER`, `_OTHER_LOOP`, `_NOT_BEHIND`, `_NO_AUTHORITY`, `_LOOP_FULL`, trip view `convoy`, `GET /api/fleet/traffic` robot `front_d_m` and `convoy {leader, follows, gap_m}`; a follower's authority end follows the member ahead (moving block). Robot API, CORE commands and envelope 1.0 unchanged |
| v1.145 | 2026-10-08 | Additive (D-520 단계 1 CORE, feat/d520-core-arc-feedforward): `POST /api/v1/line-follow/junction` 선택 객체 `exit_segment {curvature_1pm, length_m, outer_line_offset_m, end_place_id}`(`map_id` 필수, 400 `VALIDATION_ERROR`), 409 `LANE_ARC_UNAVAILABLE`, 능력 `base_velocity.lane_arc`, `line_follow.arc` 상태와 `junction.pivot_basis` 값 `segment_end`, 정지 사유 `lane_arc_edge`·`lane_arc_pose_lost`·`lane_arc_motion_unconfirmed`·`lane_arc_timeout`·`lane_arc_blind`(·`lane_arc_entry` 예약), 상태 사유 `lane_arc`·`lane_arc_correcting`, 이벤트 `nav.lane_arc_end_unarmed`, 지시 `aborted` 사유 `arc_mismatch`, 호 기록 `reason` `lane_arc_end_unarmed`, 횡단보도 구역 위 호 거절(`junction.reason` `arc_crosswalk`), 호가 도는 동안의 `bend` 409 `JUNCTION_ARC_RUNNING`(호 끝에 `armed` `bend` 가 있으면 `aborted`·`arc_mismatch` 로 지시 없는 끝과 같다). 설정 `line_follow.arc_enabled`(기본 false)·`arc_curvature_gain`·`arc_blind_max_m`. 카메라 호 맞춤(단계 2) 없음. v1.142–v1.144 는 다른 브랜치(feat/d507-bend-odom-pass, feat/d517-m2-authority, feat/d517-m3-lane-convoy 워크트리)가 쓰고 있어 건너뜀 |
| v1.143 | 2026-10-08 | Additive (D-517 4 M2, feat/d517-m2-authority, Safety-Review 대상): CORE `POST /api/v1/line-follow/authority` 와 에러 `AUTHORITY_ODOM_STALE`·`AUTHORITY_POSE_STALE`·`AUTHORITY_POSE_FUTURE`, 강제 중에만 붙는 `GET /line-follow` `authority`, 설정 `line_follow.authority_required`(기본 false), `base_velocity` 능력 `line_follow_authority`·`line_follow_authority_required`, 공유 schema `core_common.protocol.line_authority`. Fleet: 사이트 설정 `fleet.traffic.authority`(기본 false)와 능력이 있을 때만 trip 주기마다 통행권 전송, trip 보기 `traffic_authority`·`caps.line_follow_authority`, map-pose `odom_stamp`, `until_m` 은 표의 앞 끝 `d` 기준, trip 시작 거절 422 `TRIP_AUTHORITY_NOT_REQUIRED`. 둘 다 꺼져 있으면 동작 변경 없음. envelope 1.0 변경 없음 |
| v1.142 | 2026-10-08 | Additive (D-507 보충, feat/d507-bend-odom-pass): `POST /api/v1/line-follow/junction` `action: bend`(`turn_deg`, `map_id`, `bend_in_m`, `bend_tol_m`, `bend_radius_m`), `junction.state` `bending`, 사유 `junction_bending`, 중단 이유 `no_anchor`·`lane_lost_before_bend`·`distance`·`bend_basis_lost`·`off_path`, `rosy.controls/1` `base_velocity.lane_bend`; site map place kind `bend`(`exit_yaw`, `radius_m`); Fleet trip 루프의 굽이 지시. 굽이 장소가 없는 지도와 `lane_bend` 가 없는 로봇은 그대로다. envelope 1.0 변화 없음 |
| v1.141 | 2026-10-08 | Additive (D-517 M1a, feat/d517-m1-fleet): one Fleet trip per robot (`TRIP_BUSY` per robot, `GET /api/fleet/trips` `open`), `POST /trip` `repeat` laps with per-lap start checks and `hold.reason: lap`, D-513 start places part-way along a lane as goals and vias, `TRIP_LOOP_FULL`, read-only `GET /api/fleet/traffic` block table; a junction instruction into a refused block is held back and that wait is not a stall. No authority is sent; Robot API, CORE commands and envelope 1.0 unchanged |
| v1.140 | 2026-10-08 | Additive (D-512 개정 1 표시 쪽, feat/fleet-map-trail): Fleet `GET /api/fleet/tethers`, named operator `POST`·`DELETE /api/fleet/robots/{robot_id}/tether`. 지도 궤적은 기존 상태 pose(map 프레임만)를 브라우저가 모은다. 로봇 API·envelope 1.0·주행 권한 변경 없음 |
| v1.139 | 2026-10-08 | Behaviour (D-507 2 개정, 2026-10-08 사용자 결정, fix/d507-travelled-distance-window): Fleet trip 루프는 기대 창(`expect_in_m`·`expect_tol_m`) 없는 `left`·`right` 를 보내지 않고 trip 을 `stopped` `junction_no_window` 로 끝낸다(`detail.junction_place`·`junction_action`·`junction_fields`). `straight`·`stop` 은 그대로. 같은 결정 (1): `POST /api/v1/line-follow/junction` 의 기대 창은 주행 거리로 비교한다. `expect_in_m` 은 차로를 따른 거리이고 CORE 는 받은 뒤 odom 경로 길이 + `junction_ahead_m` 을 `expect_in_m − pivot_past_line_m` 과 비교한다(곧은 접근에서는 예전 값과 같다). Fleet 은 15° 굽이 규칙을 없애고 `expect_in_m` = 차로 polyline 거리, 선 찾기는 장소의 차로 방향, `expect_tol_m` 의 odom 오차 항에 갈 거리를 더하고 광선 옆 거리 항을 뺀다. 필드 이름·범위는 그대로. envelope 1.0 변경 없음 |
| v1.137 | 2026-10-08 | Additive (D-519): Fleet `POST /api/fleet/auth/login`, `POST /api/fleet/auth/logout`, `GET /api/fleet/auth/session`; `GET /api/fleet/auth/connection` adds `password_login`. Console people log in with site-users `login` + `password_scrypt` and get an HttpOnly `SameSite=Strict` `Secure` session cookie (12 h idle, 30 d with remember, 30 d absolute, voided on account change); Bearer still wins, cookie-authenticated unsafe methods need `Origin` = `Host` (403 `CSRF_REJECTED`). Robot API·envelope 1.0 변경 없음 |
| v1.136 | 2026-10-08 | Additive (feat/lane-bend-cue): Fleet lane trip `detail.bend_candidate` 읽기 전용 지도 굽이 후보. 활성 지도 버전·신선한 정렬 자세 조건에서만 표시하고 근거 상실·trip 종료 시 삭제한다. 로봇 API·CORE 명령·envelope 1.0 변화 없음. |
| v1.135 | 2026-10-08 | D-507 2·4 개정(fix/d507-map-cross-line-pivot, SIM 발견 1–2): `POST /api/v1/line-follow/junction` `pivot_past_line_m` 범위 [0, 0.30] → [−0.30, 0.30]. 음수는 측정 가로선이 장소 점 너머(먼 쪽 경계)라는 뜻이다. 접근 목표가 로봇 자리이거나 뒤면 접근 0, 후진 없음. 직진 띠 반폭은 양수 pivot 일 때만 그 값. 가로선 띠는 측정 선(테이프 중심) ± 테이프 폭/2 ± e. Fleet은 지도 `lane` 차로의 합집합 경계에서 장소 너머 첫 칠한 선을 찾아 부호 있는 거리를 보내고, 0.30 m 안에 선이 없으면 나가는 차로 폭/2 와 창 없음. 창을 보내지 않는 장소에는 음수 pivot 을 보내지 않는다(CORE `stop_point`). v1.131·v1.132는 다른 브랜치 몫 |
| v1.134 | 2026-10-08 | Behaviour (D-507 7 개정 2026-10-08, feat/d507-item7-departure-evidence): v1.133 위에서 — D-468 이탈은 (1) 신선한 `ready` 차로에서 `margin + uncertainty_m < 0` 외에 (2) 추종 중 자세 불연속(odom 점프)·연속성 epoch 변경, (3) 증명된 차로 안이지만 체크포인트 차로가 아님에서도 열린다(사용자 결정, D-507 7 개정). `lane_return_containment: unknown` 틱은 D-468이 결정을 내지 않아 D-407 막힘(`stuck`)이 `recovery_local_enabled: false` 와 같은 시각에 열리고, 그동안 필드는 `unknown` 이다. 점프 뒤 새로 잡은 체크포인트가 기준이 되어 같은 차로를 (3)으로 읽지 않는다. 필드 이름·형식 변화 없음 |
| v1.133 | 2026-10-07 | Additive + behaviour (D-507 7, feat/d468-departure-on-evidence): `GET /api/v1/line-follow` 선택 필드 `lane_return_containment`(`contained`\|`unknown`\|null). D-468은 이탈의 양의 증거(신선한 `ready` 차로에서 `margin + uncertainty_m < 0`)가 있을 때만 `lane_return_*` 로 선다. 근거가 없거나 낡거나 불확실도가 미상·초과이거나 몸 기하가 없으면 추종은 `recovery_local_enabled: false` 와 같다(손실 시계 → LOST). 체크포인트 규칙은 그대로다. 기존 필드 이름·형식 변화 없음 |
| v1.132 | 2026-10-08 | Additive (D-472 addendum 3 / D-511, feat/d511-led-track-input): Fleet lane compliance (`GET /api/fleet/robots/{robot_id}/lane-compliance`, `lane_compliance` of `/api/fleet/state` rows) judges a fresh LED-confirmed track when the map pose is not `LOCALIZED`; new fields `pose_source`, `heading_source`. Observe only: Robot API, envelope 1.0, map pose, trips unchanged. v1.131 is held by feat/fleet-console-password-login (D-519); D-507 7 is v1.134 |
| v1.130 | 2026-10-08 | D-513 7: `rosy.site_map/1` optional `view_turn_deg` (0/90/180/270, omitted when 0), the one clockwise screen turn of the plain +y-up map view that Fleet map and camera views follow. Display only. Robot API·envelope 1.0 변경 없음 |
| v1.130 | 2026-10-08 | Additive (D-472 addendum, feat/d472-led-identity): Fleet LED 신원 — `identity_challenge`(detections config), Vision 판정 `POST /api/fleet/detections/identity`, 읽기 전용 `GET /api/fleet/tracking/identity`, `/robots/{id}/identify` 색 생략·움직이는 로봇 한정. 확인 트랙은 D-511 입력·표시 전용, 지도 자세 중재·trip·initialpose·명령에 쓰지 않음 |
| v1.129 | 2026-10-08 | Additive (D-472 addendum, feat/d472-led-identity): CORE `POST /host/lamp/identify`의 `color` 생략 시 로봇 설정 색, 움직이는 로봇에서도 정상 패턴 위 점멸, 안전 표시 중 즉시 거절, 요청~종료 6 s 상한. 신원 확정·주행 권한은 열지 않음. v1.124~v1.128은 다른 브랜치(D-511 M0 v1.128) 몫 |
| v1.129 | 2026-10-08 | Additive (D-507 2/3/9 Fleet side, feat/d507-fleet-trip-expect): trip start refuses 422 `TRIP_SITE_FLOOR_MISMATCH` when the robot's `site_floor_map_id` capability names another map than the active one; to robots with `junction_pivot: true` the trip loop adds `map_id`, `expect_in_m`, `expect_tol_m`, `pivot_past_line_m` to `POST /api/v1/line-follow/junction`; CORE `unexpected`, or `waiting` beyond `arm_distance_m`, ends the trip at once as `stopped` `junction_unexpected`. Robot API fields are CORE's D-507 2 change; envelope 1.0 unchanged |
| v1.128 | 2026-10-08 | Additive (D-511 M0, feat/d511-lane-compliance-m0): Fleet `GET /api/fleet/robots/{robot_id}/lane-compliance` and the `lane_compliance` field of `GET /api/fleet/state` robot rows — signed lateral offset, body margin and `OK`/`WARN`/`ACT`/`UNKNOWN` (UNKNOWN off the graph, past arc ends, across lanes) from the D-494 3 map pose, site config `fleet.lane_compliance`. The console exception queue shows WARN/ACT. Observe only: Robot API, envelope 1.0, trip/`/route`/meet thresholds unchanged. v1.124–v1.127 are held by open peer branches |
| v1.127 | 2026-10-08 | Additive (D-507 2–5항 CORE, feat/d507-junction-approach): `POST /api/v1/line-follow/junction` 선택 필드 `map_id`·`expect_in_m`·`expect_tol_m`·`pivot_past_line_m`, 409 `JUNCTION_ODOM_STALE`, `junction.state` `approaching`·`unexpected`, HOLD `junction_unexpected`, `junction.pivot_basis`(`map`\|`stop_point`), `rosy.controls/1` `base_velocity.junction_pivot`(최근 2 s 안 `line/keep_debug` 표지 `junction_ahead_v` ≥ 1 일 때만 참), `straight` 의 `pivot_past_line_m`(창 전용), 접근·직진 통과 중 측정 가로선 띠 안의 IR `centre` 허용. CORE 는 `line/keep_debug` 의 `junction_ahead_m` 을 읽는다. 필드가 없는 옛 Fleet 요청은 동작이 그대로다 |
| v1.126 | 2026-10-08 | Breaking config + Additive (D-507 6·9, feat/d507-motion-admitted-site-floor): 설정 `line_follow.site_floor_map_id`(문자열 또는 null, 기본 null; `^[A-Za-z0-9_.-]{1,64}$`, `site` 아님, `ir_guard_enabled`·`obstacle_mode: path`·URDF 몸 필요)가 `bridge_site_no_dropoffs`·`junction_turn_site_accepted`를 대신한다. 옛 키가 어느 설정 겹에 있어도 CORE 는 새 키 이름을 담은 오류로 시작을 거부한다(별칭 없음). `rosy.controls/1` `base_velocity` 선택 필드 `site_floor_map_id`. D-468 복귀·역추적, D-476 bridge, D-495 회전이 한 운동 허가(enforce 또는 현장 근거)를 쓰고, 현장 근거의 후진은 D-468 역추적만(한도 그대로). 중단 사유 그대로. envelope 1.0 유지 |
| v1.125 | 2026-10-08 | Additive (D-509): Fleet `GET /api/fleet/state` 선택 로봇 행 필드 `power_health`(기존 공유 `PowerHealthResponse` 또는 null), `power_health_age_s`(초 또는 null). Fleet Operator 토큰으로 CORE Viewer `GET /api/v1/power/health` 읽기, 최대 5초 표시 캐시. 오프라인·실패·스키마 오류·낡음은 확인 불가. CORE 경로·envelope 1.0·안전/명령 판정 불변 |
| v1.124 | 2026-10-08 | D-513: site map place kind `start` (demo start slot with required `yaw`); activation refuses a start place a trip could not start from (`SITE_MAP_START_INVALID`). Teach `POST /place` accepts `kind: start`; a new place in `/teach/confirm` does not (it has no robot yaw). Robot API·envelope 1.0 변경 없음 |
| v1.123 | 2026-10-07 | Additive (D-499): Fleet `GET /api/fleet/state` 로봇 행 선택 필드 `link`(`up`·`unreachable`·`moved`·`tls-refused`·`protocol`). 401이 아닌 로봇 API 오류에는 필드가 없다. 표시 전용. CORE 경로·envelope 1.0·발행 루프의 online/state/goal 판정은 그대로다 |
| v1.122 | 2026-10-07 | Additive (D-493, fix/d493-attention-stale-state): `GET /api/fleet/state` 로봇 행에 `state_age_s`(상태가 관찰된 뒤 지난 초. hub 나이와 SharedGather 캐시 나이 포함, 오프라인이면 `null`)와 최상위 `gathered_at`(마지막 실제 수집의 서버 UTC epoch 초, 표시용)을 더함. 콘솔 예외 큐는 `state_age_s` + 받은 뒤 지난 시간이 5초를 넘으면 "상태 오래됨" warn 을 붙인다. 기존 필드는 그대로다. |
| v1.121 | 2026-10-07 | Additive (D-407 Fleet 쪽, feat/d407-stuck-episode-log): Site Fleet 새 경로 `GET /api/fleet/line-stuck/episodes`(viewer+) — 막힘 에피소드 기록(`fleet_line_stuck_episodes`, `--tasks-db` 파일). 보드 전이에서만 쓰고 로봇 요청은 늘지 않는다. Robot API·envelope 1.0 변경 없음 |
| v1.120 | 2026-10-07 | Corrective + Additive (D-502, fix/core-battery-health): SAF-005 배터리 래치(`battery_policy`·`battery_deep`)도 모드 EMERGENCY 로 들어가 Admin `POST /safety/release` 로 풀린다(전에는 409 `not in EMERGENCY` 로 풀 수 없었다). `GET /sensors/battery` 는 404 대신 `evidence`·`sample_age_s`·`stale_after_s` 를 싣고, 표본은 제품 토픽 `battery/voltage` 에서 온다. `GET /safety/state` `battery` 에 `evidence`·`sample_age_s`·`level`·`percent`. Fleet envelope `protocol_version` 1.0 유지 |
| v1.119 | 2026-10-07 | Additive (D-494 6, feat/d494-fleet-teach-drive): Fleet 주행 가르치기 `GET /api/fleet/teach`, `POST /api/fleet/teach/start`, `/stop`, `/confirm`, `/place`. 기록은 D-494 3 map pose만 읽고 로봇에 아무것도 보내지 않는다. 확정과 주소 만들기는 초안 PUT과 같은 규칙으로 초안에만 쓴다. Robot API·envelope 1.0 변경 없음 |
| v1.118 | 2026-10-07 | Additive (D-498, feat/d498-junction-turn-site-basis): 교차로 회전의 운동 근거에 현장 근거를 더함 — 설정 `line_follow.junction_turn_site_accepted`(기본 false, `ir_guard_enabled` 없이 true 면 CORE 시작 거부), `junction_turn` 능력은 enforce 증명 또는 현장 근거가 있을 때만 참(읽을 때마다 재판단), 중단 사유 `turn_basis_lost`. envelope 1.0 유지 |
| v1.117 | 2026-10-07 | Corrective/semantic (D-468): containment boundaries are the drivable inner edge of the paint (previously paint centre). 생산자가 칠 폭 절반(`lane_paint_half_width_m`, 260919 STL 공칭 12.5 mm)만큼 안쪽으로 옮기고 그 값을 `geometry_id`에 넣는다. 필드 모양·envelope 1.0 변경 없음 |
| v1.116 | 2026-10-07 | Additive (D-494 5, D-495 3): Fleet trip loop `POST /api/fleet/trips/{plan_id}/start` (opens the v1.111 501 reservation), `POST /api/fleet/trips/{trip_id}/cancel`, `POST /api/fleet/trips/{trip_id}/confirm-replan`, `GET /api/fleet/trips`, `GET /api/fleet/trips/{trip_id}`; map activation now waits for a running trip instead of a recent `/route` step. While a trip runs, `/goal`, `/route`, task dispatch, `formation/start|reform|resume`, moving line-stuck decisions and line-follow modes other than `OFF` for that robot answer 409 `TRIP_ROBOT_BUSY`; every operator stop (cancel, cancel-all, E-stop, `OFF`, stuck `ABORT`/`MANUAL`) reaches the robot and cancels the trip. Uses robot `POST /api/v1/line-follow/junction` (D-494 4) and the D-494 1/3 capability and map pose inputs. Robot API and envelope 1.0 unchanged |
| v1.115 | 2026-10-07 | Additive (D-491): 내부 `line/observation` CAMERA_LINE `containment`에 optional `crosswalk`(`near_m`, `far_m`). `GET /api/v1/line-follow` 추종 사유 `ir_guard_crosswalk`(IR 감시가 알려진 횡단보도 구간에서 쉼). 기본 동작 불변: IR 감시 기본 꺼짐, 로봇 패키지 `ir_row_x_m` 없으면 쉬지 않음 |
| v1.114 | 2026-10-07 | Additive (D-494 4항, D-495, feat/d491-core-junction-action): CORE `POST /api/v1/line-follow/junction`(operator, 보정 lease)·에러 `LINE_FOLLOW_NOT_ACTIVE`·`JUNCTION_CAMERA_ONLY`·`JUNCTION_ALREADY_DONE`(409)·line-follow 상태와 스냅숏의 `junction`(`LineJunctionStatus`: `pending_action, place_id, state, seq`)·정지 사유 `junction_waiting`·`junction_unresolved`·`junction_stop`. 좌·우는 분기 인식 없이 D-495 제한 회전(`turn_deg`·`advance_m`, 상태 `turning`·`advancing`·`reacquiring`·`aborted`, `junction.turn_deg`·`junction.reason`, 사유 `junction_turning`·`junction_advancing`·`junction_reacquiring`·`junction_aborted`)으로만 간다. envelope 1.0 유지 |
| v1.113 | 2026-10-07 | Additive (D-494 3): Fleet `GET /api/fleet/robots/{robot_id}/map-pose`, the trip-only map pose from Rosy Cam sightings and robot `odom_pose`; site config `fleet.map_pose`. `/route`, traffic and D-395 unchanged. Robot API and envelope 1.0 unchanged |
| v1.112 | 2026-10-07 | Additive (D-494 1·2): `rosy.controls/1` `base_velocity` 선택 필드 `robot_kind`·`drive_modes`·`trip_max_linear`와 D-495 `junction_turn`; 상태 스냅샷 선택 필드 `odom_pose {x, y, yaw, stamp}`(UTC epoch 초); Fleet `/trip` 계획이 능력 필드가 있을 때 그 주행 방식·종류·속도를 따른다. 옛 로봇·소비자는 그대로 동작한다. envelope 1.0 유지 |
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
| `GET /api/v1/auth/connection` | LAN peer, 인증 불필요, `no-store`; D-535부터 출발지별 30회/분(넘으면 429 `RATE_LIMITED` + `Retry-After`), LAN 밖 403 `LAN_REQUIRED` | 200 `{mode: paired|development, robot_id: string, transport: http|https}` (`ConnectionInfo`). D-535 (v1.155) 추가: `connect_contract`(정수, 1), `api`(`v1`), `core_ready`(부팅 단계가 `CORE_READY`; 표시 파일이 없으면 CORE가 답하므로 true), `stage`, `release`(없으면 null), `tls_hostname`(TLS일 때 `<host>.local`, 아니면 null), `pairing`(`open`\|`console_only`(LCD가 화면 코드를 보일 수 없음 — 관제 승인)\|`full`(대기 요청 3개)\|`unavailable`(HTTP이거나 수신 초기화 불가)). mDNS TXT가 이미 광고하는 값과 개수·가능 여부뿐이며 신뢰 앵커가 아니다 |
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

## Service Control (D-524 Proposed)

`GET /api/fleet/hosts`는 운영자가, `POST /api/fleet/hosts/{host}/control`은 이름 있는 운영자
(site-users 자격, 로그인 세션, 개발 세션)만 호출한다. 이름 없는 `site-console`은 403
`OPERATOR_IDENTITY_REQUIRED`이고, site-users와 로그인이 둘 다 없으면 Fleet은 도우미를 만들지 않는다.
`host`는 `site`, `ai`, `model`이다. GET 행은 `{host, actions, units, stoppable_units, reboot_delay_min}`이다.
POST 본문은 `{action, unit, operator_confirmed:true}`이고 추가 필드는 거절한다. `action`은 `reboot`,
`cancel-reboot`, `restart-unit`, `stop-unit`만이다. `pkill`, 시그널, 셸, 프로세스 이름은 400
`UNKNOWN_ACTION`이다. `unit`은 그 호스트의 허용 목록에 있고 그 동작이 허용될 때만 받는다(사이트 유닛은
`restart-unit`만, 아니면 400 `UNIT_NOT_ALLOWED`). 재부팅은 `shutdown -r +10`이다. 이미 예약된 재부팅이
있으면 409 `REBOOT_ALREADY_SCHEDULED`이다. `cancel-reboot`는 이 도우미가 예약한 재부팅만 `shutdown -c`로
취소하고, 아니면 409 `NO_HOST_CONTROL_REBOOT`이다. 그 호스트의 연결 설정이 없으면 503
`HOST_HELPER_UNAVAILABLE`, SSH나 도우미가 실패하면 502 `HOST_HELPER_FAILED`이다. 성공은 200
`{host, action, unit, requested_by, code:"ACCEPTED", output}`이다. 이 API는 로봇을 재부팅하지 않는다.
