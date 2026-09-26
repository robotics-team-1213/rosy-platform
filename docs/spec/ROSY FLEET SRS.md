# ROSY FLEET Fleet Control Platform
## 소프트웨어 개발 요구사양서 (중앙 서버 책임)

**Document ID:** ROSY-FLEET-SRS-001
**Version:** v1.0
**Target Platform:** Linux Server / Docker
**Project Type:** Multi-Robot Fleet Manager
**Status:** Approved

**승계:** 본 문서는 `PKY-CORE-SRS-001 v0.1`의 Fleet 확장 분(§24~34, §36, §42)을 승계·확장한다. 플랫폼명을 PINKY → **ROSY**로 전환한다(ADR-D-15, D-16).

**관련 문서:** ROSY-CORE-SRS-001 (로봇 책임) / ROSY-API-REF-001 (공유 계약) / ROSY-ADR-001 / ROSY-PLN-001

---

# 1. 개요 및 책임 범위

## 1.1 시스템 위치

ROSY FLEET은 여러 로봇(각각 ROSY CORE 탑재)을 하나의 시스템에서 검색·모니터링·명령·오케스트레이션하는 중앙 서버이다.

```text
                      ROSY FLEET
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
         ▼                 ▼                 ▼
      Rosy 01           Rosy 02           Rosy 03
      (rosy_core)       (rosy_core)       (rosy_core)
```

## 1.2 책임 경계 원칙

Fleet은 다음 원칙을 준수한다.

1. **계약만 사용** — 로봇 내부 ROS Node·Topic·Service를 직접 알거나 접근하지 않는다. ROSY API Ref에 정의된 인터페이스만 사용한다.
2. **모터 직접 제어 금지 (HITL 예외)** — 일반 이동을 위해 로봇에 `/cmd_vel` 스트림을 전송하지 않는다. Goal 기반 명령만 내린다. 단, 로봇이 스스로 해결할 수 없는 장애 상황(`Requiring_Assistance` 상태)으로 판단하여 사람의 개입(HITL)을 요청한 경우에 한정하여, 관제사가 수동으로 원격 조종(Teleop)을 할 수 있도록 예외적인 제어 중계를 허용한다.
3. **로봇 독립성 보존** — Fleet 장애가 개별 로봇의 기본 운용 불능으로 전파되어서는 안 된다. Fleet은 "부재 시에도 로봇이 동작"하는 것을 깨는 어떤 설계도 해서는 안 된다.
4. **로봇 간 통신 경유** — 로봇 간 직접 통신(ROS DDS 포함)을 요구하지 않는다. 필요한 모든 조정은 Fleet이 수행한다.

## 1.3 통신 구조 (확정: ADR-D-5, D-6)

```text
Rosy 01 ─ REST / WebSocket ─┐
Rosy 02 ─ REST / WebSocket ─┤
Rosy 03 ─ REST / WebSocket ─┼── Fleet Server
Rosy 04 ─ REST / WebSocket ─┤
Rosy 05 ─ REST / WebSocket ─┘
```

- **상태·이벤트 수집:** 로봇이 Fleet WebSocket에 **outbound 접속**하여 상태(heartbeat)와 이벤트를 push한다. 인바운드 방화벽·mDNS 문제를 회피한다.
- **명령 전달:** Fleet이 로봇 REST API로 명령한다.
- 로봇 내부에서만 ROS 2를 사용하며, 로봇 간 DDS 트래픽은 차단한다(로봇 측 DDS 격리 정책, CORE SRS §6.2).

---

# 2. Fleet ↔ Robot 프로토콜 준수 (PRT)

프로토콜 메시지 스키마·envelope 상세는 API Ref가 유일한 원천이다. 본 절은 Fleet의 **동작 요구사항**을 정의한다.

### PRT-001 Envelope 준수

Fleet은 모든 로봇 통신을 표준 envelope(`protocol_version`, `msg_id`, `type`, `ts`, `payload`)으로 송수신해야 하며, 인식할 수 없는 `protocol_version`은 거부하고 명확한 에러를 반환해야 한다.

### PRT-002 인증 핸드셰이크

로봇의 WS 접속 첫 메시지는 핸드셰이크(`robot_id` + 페어링 토큰)여야 한다. 인증 실패 세션은 즉시 종료하며 감사 로그에 기록한다.

### PRT-003 Heartbeat 수신

Fleet은 로봇 heartbeat(1 Hz, 상태 스냅샷 포함)를 수신하고 로봇 레지스트리를 갱신해야 한다.

### PRT-004 명령 추적 (Ack 모델)

Fleet이 로봇에 내린 모든 명령에는 `correlation_id`를 부여해야 한다. Fleet은 최소 3단계 추적 상태(`ACCEPTED` → `STARTED` → `COMPLETED|FAILED`)를 로봇 응답·이벤트와 연계해 관리해야 하며, 타임아웃(기본 10초) 내 응답 없으면 `TIMEOUT`으로 표시한다.

### PRT-005 재접속 및 갭 필

로봇 재접속 시 Fleet은 `since_seq` 기반 이벤트 재전송 요청에 응해 로봇 이벤트 누락 없이 수신할 수 있어야 한다. Fleet 자체 장애 복구 후에도 세션을 재수립해야 한다.

### PRT-006 하위호환

`protocol_version` minor 증가는 추가 전용으로 호환 유지한다. Major 변경 로봇은 접속을 허용하되 기능 제한 명시(Fleet이 지원하는 최고 버전으로 강등 통신)해야 한다.

---

# 3. Robot Registry & Discovery

### REG-001 Robot 등록

Fleet은 네트워크에 연결된 로봇을 검색·등록할 수 있어야 한다. 등록 경로: ① mDNS/네트워크 스캔, ② 수동 등록(IP/hostname), ③ 로봇 outbound 접속 시 자동 등록(페어링 승인 후).

### REG-002 Robot 정보 관리

레지스트리는 로봇별로 최소 다음을 유지해야 한다.

- Robot ID / Robot Name / IP / Hostname
- Hardware Model / Version(소프트웨어·ROS·펌웨어)
- Capability(CAP-001 스키마) / map_id
- Battery / Pose / Status / Mode
- Last Heartbeat / 접속 이력

### REG-001a 등록 해제·차단

관리자는 로봇을 등록 해제하거나 차단할 수 있어야 하며, 해당 조작은 감사 로그에 남는다.

### REG-003 그룹 관리

로봇을 그룹으로 지정·변경할 수 있어야 한다(예: `warehouse_a`, `patrol_team`).

---

# 4. Heartbeat 감시

### MON-001 Offline 판정

연속 3회(기본, 설정 가능) heartbeat 미수신 시 해당 로봇을 `OFFLINE` 또는 `COMM_ERROR` 상태로 표시해야 한다.

### MON-002 상태 알림 및 큐(Queue) 분류

로봇 상태 전이(ONLINE↔OFFLINE, 배터리 임계, E-Stop 발생 등) 및 **모듈 단위의 상태 변화**는 Fleet UI에 즉시 반영하고 이벤트로 기록해야 한다. Fleet은 수신된 상태를 기반으로 다음 두 가지 큐(Queue)를 관리한다.
- **경고 큐 (Degraded Fallback):** `capabilities_degraded` 상태 보고 시. 임무는 계속되나 로컬 센서 대체 등으로 성능 저하가 발생했음을 조용히 알림.
- **최우선 개입 큐 (Requiring Assistance):** `hitl_requested: true` 수신 시. 미션 진행이 불가능하여 사람의 개입이 필요한 상태로, 화면 최상단 및 중앙 맵에 시각/청각 알람과 함께 팝업 노출.

---

# 5. Fleet Dashboard

### DASH-001 다중 로봇 뷰

중앙 화면에서 여러 로봇을 동시에 표시한다.

```text
┌─────────────────────────────────────────────┐
│               ROSY FLEET                    │
├──────────────────┬──────────────────────────┤
│ ROBOTS           │ MAP                      │
│ ● Rosy 01   81%  │       ②                 │
│ ● Rosy 02   73%  │                          │
│ ● Rosy 03   92%  │  ①            ③         │
│ ○ Rosy 04  OFF   │                          │
├──────────────────┼──────────────────────────┤
│ Group            │ Command                  │
│ ☑ R01  ☑ R02     │ [MOVE] [HOME]            │
│ ☑ R03            │ [FORMATION] [STOP ALL]   │
└──────────────────┴──────────────────────────┘
```

각 로봇은 고유 색상으로 식별한다(로봇별 색 배정 정책).

### DASH-002 다중 로봇 맵

동일 `map_id`를 가진 로봇들을 하나의 맵 위에 표시해야 한다. 서로 다른 `map_id`의 로봇은 맵을 분리 표시한다.

---

# 6. Fleet 기본 기능

### CTR-001 기능 목록

다음 기능을 지원한다.

- Robot 등록 / 검색 / 상태 모니터링
- 개별 Robot 선택 / 다중 Robot 선택 / Group 지정
- Individual Move / Group Move / Return Home
- Waypoint 목록 조회·관리(로봇 동기화 포함)
- Stop Selected / **STOP ALL**

### CTR-002 STOP ALL

STOP ALL 수행 시 선택된 전체 로봇에 **즉시** Stop(안전 정지) 명령을 전달해야 한다. 명령 전달 결과(성공/실패/타임아웃)를 로봇별로 표시한다. STOP ALL은 Navigation 취소이며, 필요 시 로봇별 E-Stop은 별도 명령으로 구분한다.

### CTR-003 명령 결과 집계

다중 로봇 명령은 부분 실패를 허용하며, 로봇별 결과를 집계 표시해야 한다(PRT-004 추적 상태 사용).

---

# 7. 온보딩 및 페어링 (보안)

### SEC-201 Pairing Token

신규 로봇의 Fleet 등록은 **페어링 토큰 기반**이어야 한다. 관리자가 Fleet에서 1회용 페어링 토큰을 발급하고, 로봇 설정에 입력된 토큰으로 첫 접속 인증을 수행한다.

- 페어링 토큰은 1회용 + 만료 시간(기본 24시간)을 갖는다.
- 페어링 성공 시 로봇별 장기 토큰을 발급한다.

### SEC-202 무단 등록 차단

유효한 페어링 토큰 없이 접속한 로봇은 `PENDING` 상태로 대기 목록에 표시하고, 관리자 승인 전까지 어떤 명령도 수행하지 않는다.

### SEC-203 토큰 폐기·재발급

관리자는 로봇 토큰을 폐기·재발급할 수 있어야 하며, 폐기 즉시 해당 로봇 세션을 종료한다. 모든 페어링·폐기 조작은 감사 로그에 기록한다.

### SEC-204 Fleet 접근 통제

Fleet Web/API는 로봇과 동일한 3롤(Viewer/Operator/Administrator) 모델을 사용한다. HTTPS는 기본 권장, LAN 폐쇄 시 배포 정책으로 HTTP 허용.

---

# 8. Mission Manager

### MSN-001 Mission DSL v1

미션은 JSON 순차 스텝으로 정의한다.

```json
{
  "mission_id": "patrol_evening",
  "target": { "robots": ["rosy_01", "rosy_02"] },
  "idempotency_key": "pe-20260829-01",
  "steps": [
    { "action": "goto", "waypoint": "zone_a" },
    { "action": "wait", "seconds": 30 },
    { "action": "home" }
  ]
}
```

v1은 순차 실행만 지원한다(병렬·조건 분기는 v2 이후). 스키마 원천은 API Ref.

### MSN-002 Mission 상태머신

```text
PENDING → RUNNING → COMPLETED
              │  │
              │  └── FAILED
              └──── CANCELED
```

스텝별 진행 상태를 로봇 단위로 추적·표시해야 한다.

### MSN-003 멱등성

동일 `idempotency_key` 재제출 시 미션을 새로 생성하지 않고 기존 미션을 반환해야 한다.

### MSN-004 이벤트 기반 진행 및 동적 재배정(Re-routing)

미션 진행 판단은 로봇 이벤트(`nav.completed`, `nav.failed`, `nav.stuck` 등) 기반으로 수행하며, 로봇 상태 폴링에 의존하지 않는다. 만약 임무를 수행 중인 로봇의 특정 모듈이 `degraded_fallback` 상태로 전환되어 원래 배정된 미션(예: 정밀 픽업)을 온전히 수행하기 어렵다고 판단될 경우, Mission Manager는 해당 로봇의 미션을 취소하고 정상 작동하는 대체 로봇에게 미션을 동적으로 재배정할 수 있어야 한다.

### MSN-005 예약 미션 (Outline)

정기 미션(예: 매일 18시 순찰) 스케줄러를 지원한다. 초기 MVP 범위 외이며, 미션 저장 구조는 스케줄러 추가를 방해하지 않아야 한다.

---

# 9. Formation / Swarm

### FOR-001 Formation 유형

다음 Formation을 지원한다.

```text
LINE | COLUMN | GRID | V | CIRCLE | FOLLOW
```

Formation Parameter: Center Position / Orientation / Robot Spacing / Robot Selection / Leader Robot.

`FOLLOW`는 단일 추종자 전용이다 (2대 이상은 `COLUMN` 사용) — `fleet/formation/geometry.py`가 강제한다.

### FOR-002 Formation Slot Assignment

대형 변경 시 로봇 위치와 목표 Slot 간 비용을 계산해 효율적으로 배정한다. 초기 구현은 거리 기반 배정이며, 배정 알고리즘은 인터페이스 뒤로 격리해 Hungarian Algorithm 등으로 교체 가능해야 한다.

### FOR-003 Leader-Follower

특정 로봇을 Leader로 지정하고 다른 로봇이 추종한다.

- Parameter: Leader ID / Follow Distance / Lateral Distance / Speed Limit / Formation Type
- **하이브리드 구조(D-20):** Fleet은 Leader pose 스트림(SWM-003, ≥10 Hz 수신)을 Follower들에게 WS로 릴레이(≥5 Hz)하고, Follower에는 `swarm/follow` 명령을 1회 전달한다. **폐루프 추종 계산은 로봇 탑재(SWM-002)** — Fleet은 목표를 반복 계산·전송하지 않는다.
- 로봇 간 직접 통신은 발생하지 않는다.

### FOR-004 Formation 안전 및 동적 속도 조절

Formation 실행 중 로봇별 Navigation 상태를 감시하고, 로봇 1대라도 `BLOCKED`/`FAILED`/`nav.stuck` 발생 시 설정 정책(기본: 형성 중단 + 전체 HOLD)을 수행해야 한다. 
만약 편대 중 일부 로봇이 모듈 고장 등으로 `degraded_fallback` 상태가 되어 구동 속도가 저하된 경우, Fleet은 대형 유지를 위해 **전체 편대의 이동 속도(Speed Limit)를 느려진 로봇의 최대 가용 속도에 맞추어 하향 동기화**해야 한다. Fleet 단절 시 각 로봇은 SWM-004(로컬 HOLD)로 자보하고, Fleet은 재접속 후 형성 상태를 재평가한다.

---

# 10. Traffic Manager (확장 예약)

### TRF-001 초기 정책

초기 버전은 각 로봇 Nav2의 Local Obstacle Avoidance를 활용한다(중앙 교통 제어 없음).

### TRF-002 확장 아키텍처

Fleet 규모 증가 시 다음 기능을 추가할 수 있도록 Module 인터페이스를 예약한다.

```text
Path Conflict Detection / Goal Reservation / Priority Control
Intersection Reservation / Multi-Agent Path Finding (MAPF/CBS)
```

MAPF/CBS 고급 구현은 초기 MVP 필수 범위에서 제외한다. Mission Manager·Formation Manager는 Traffic Manager 유무와 무관하게 동작해야 한다.

---

# 11. 운영 지원 (Ops)

### OPS-001 로봇 설정 백업

Fleet은 로봇의 설정·Robot Profile·Waypoint·맵(`map_id` 포함) 스냅샷을 수집·보관해야 한다. 수집은 로봇 승인 하에 주기/수동 트리거로 수행한다.

### OPS-002 복구 프로비저닝

하드웨어 교체 등으로 신규 로봇을 투입할 때, 기존 `robot_id`의 백업 스냅샷으로 설정·Waypoint·맵을 복원할 수 있어야 한다. 복원 후 페어링(SEC-201)을 재수행한다.

---

# 12. 관측성 (Observability)

### OBS-201 메트릭 수집·집계

Fleet은 로봇별 `/metrics`(OBS-101)를 주기 수집해 집계 대시보드를 제공해야 한다. 최소 지표: 상태 갱신 주기, 명령 지연, heartbeat RTT, 배터리 추이, WS 세션 안정성.

### OBS-202 이벤트 보존

Fleet은 수신한 로봇 이벤트·감사 로그를 DB에 보존한다(기본 1년, 설정 가능). 보존 데이터는 시계열 조회 API로 검색할 수 있어야 한다.

---

# 13. 시뮬레이션 통합

### SIM-001 가상 로봇 등록

Gazebo 시뮬레이션 인스턴스(rosy_gz_sim + rosy_core)를 실물과 동일한 계약으로 Fleet에 가상 로봇으로 등록할 수 있어야 한다. 가상 로봇은 `sim: true` 식별 속성을 가지며, 실물과 혼합 운용·FAT 전 수동 검증에 사용한다.

---

# 14. AI / VLA 확장

### AIV-001 계층 구조

AI Agent·VLA는 Fleet API를 사용해서만 명령한다. AI가 직접 로봇 모터 Topic을 제어하지 않는 것을 기본 원칙으로 한다.

```text
LLM / VLA
    ↓ (도구 호출: Fleet API)
Mission Planner          ← MSN-001 DSL 생성
    ↓
Fleet API (Mission·Formation·Robot)
    ↓
Rosy API (로봇별 원자 명령)
    ↓
Nav2
```

예: *"3대의 Rosy를 A구역으로 이동시킨 후 삼각 대형으로 정렬"* → Mission Planner가 Waypoint 조회 + `goto` 스텝 + Formation 명령으로 변환한다.

### AIV-002 도구 스키마

AI 도구 호출(Function Calling)용 스키마는 Fleet API OpenAPI에서 파생하며, 별도 최소 도구 세트(로봇 목록/미션 생성/상태 조회/정지)를 v1로 정의한다.

---

# 15. 데이터 및 확장성

### DAT-001 저장소

Fleet DB는 SQLite(초기) → PostgreSQL(확장) 전환을 전제로 ORM(SQLAlchemy) + 마이그레이션(Alembic) 체계를 사용한다. 필요 시 Redis(세션·실시간 집계)를 추가할 수 있다.

### DAT-002 데이터 모델

최소 엔티티: Robot / Group / PairingToken / Command(추적 상태 포함) / Mission(+Step 상태) / Waypoint / MapSnapshot / Event / AuditLog / User·Role.

### NFR-001 확장성

```text
Phase 1  1 Robot → Phase 2  2 Robots → Phase 3  3~5 Robots → Phase 4  10 Robots
```

Architecture는 장기적으로 **50 Robots 수준까지 확장 가능하도록 로봇별 상태와 통신 연결을 독립 관리**해야 한다. 50대 동시 성능을 초기 인수 요구로 하지는 않는다.

### NFR-002 가용성

- Fleet Server 장애가 개별 로봇 ROSY CORE 장애로 전파되지 않는다(검증: MAT-08).
- Fleet 이중화는 초기 범위 밖이나, 단일 인스턴스 재시작 시 로봇 재접속·상태 복구가 자동화되어야 한다.

### NFR-003 시간

Fleet 서버는 chrony로 시간 동기화한다(로봇 이벤트 상관 분석 전제).

---

# 16. Fleet 인수 시험 (FAT / MAT)

2대 이상의 실제 로봇 또는 시뮬레이션 환경에서 다음을 검증한다.

### MAT (Multi-Robot Acceptance)

| ID | 시험 | 책임 문서 |
|---|---|---|
| MAT-01 | 각 Robot ID가 독립적으로 표시된다 | 본 문서 + CORE |
| MAT-02 | ROS Topic 충돌 없음 | CORE §6 (로봇 측 구현) |
| MAT-03 | TF 충돌 없음 | CORE §6.1 |
| MAT-04 | Robot 01 명령이 Robot 02에서 수행되지 않는다 | 본 문서 + CORE |
| MAT-05 | 두 로봇 상태를 동시에 Web/Fleet UI에서 확인 | 본 문서 |
| MAT-06 | 두 로봇에 서로 다른 Goal 동시 전달 | 본 문서 |
| MAT-07 | STOP ALL 시 선택 전체 로봇에 즉시 Stop 전달 | 본 문서 (CTR-002) |
| MAT-08 | Fleet Server 종료 후 각 로봇 ROSY CORE 독립 동작 | 본 문서 + CORE |

### FAT (Fleet Acceptance)

| ID | 시험 |
|---|---|
| FAT-01 | 페어링 토큰 발급 → 로봇 핸드셰이크 → 자동 등록 (SEC-201) |
| FAT-02 | 로봇 WS 재접속 후 `since_seq` 이벤트 갭 필 (PRT-005) |
| FAT-03 | 명령 `correlation_id` 추적 상태 전이 표시 (PRT-004) |
| FAT-04 | Capability 미지원 명령 전달 시 로봇 `CAPABILITY_NOT_SUPPORTED` 응답 처리·UI 표시 (CAP-003) |
| FAT-05 | Fleet에서 생성한 Waypoint가 로봇에 동기화되어 Goal로 사용 가능 (WPT-005) |
| FAT-06 | Leader-Follower 실검: 리더 주행 중 팔로워가 로컬 폐루프로 추종(SWM-002) + Fleet WS 단절 주입 시 전원 HOLD(SWM-004) |

---

# 17. 주요 산출물 (Fleet 측)

1. rosy_fleet Source Code (FastAPI + Docker)
2. Fleet API Specification (API Ref와 동기화된 OpenAPI)
3. Fleet Dashboard
4. DB 스키마·마이그레이션
5. FAT/MAT 시험 결과서

---

# 18. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.0 | 2026-08-29 | PKY-CORE-SRS-001 v0.1의 Fleet 분 승계. Rosy 전환, PRT/SEC(페어링)/MSN/FOR-004/OPS/OBS/SIM/AIV/DAT 신설, 로봇 측 요구사항은 CORE SRS로 이관 |
