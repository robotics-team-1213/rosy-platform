# ROSY Implementation Plan
> Status: Historical upstream baseline. The current Rosy OS source-of-truth is under src/, and current absorption/Device execution is tracked in docs/plans/2026-09-12-rosy-os-system-architecture-roadmap.md and docs/plans/2026-09-13-rosy-os-device-validation-implementation-plan.md. Do not use this file as the current deployment procedure.
## 구현 계획서

**Document ID:** ROSY-PLN-001
**Version:** v2.0
**기준 문서:** ROSY-CORE-SRS-001 / ROSY-FLEET-SRS-001 / ROSY-API-REF-001 / ROSY-ADR-001
**기준 코드베이스:** `reference/src/pinky_pro-main.zip` (upstream pinky_pro — 기준 버전 고정, D-16)
**Target:** Pinky Pro / Ubuntu 24.04 / ROS 2 Jazzy
**개발 규모 가정:** 1~2인 개발, 실물 로봇 1~2대 + Gazebo 시뮬레이션 병행

> **승계:** `PKY-CORE-PLN-001 v1.0`을 재편성·확장한다. 의사결정 D-1~D-7은 유지되며 D-8~D-17이 추가되었다. 문서 간 참조는 섹션 번호가 아닌 **요구사항 ID** 기반(D-17).

---

# 1. 문서의 목적

본 문서는 요구사양서(CORE/FLEET SRS)와 계약(API Ref)을 **실행 가능한 작업 단위(WBS)로 분해한 실행 계획서**이다.

- 요구사항 ID → 태스크(Pn-xx) → 시험(AT/FAT/MAT) 3단 추적 (§11 매트릭스)
- 단계별 완료 기준(Definition of Done)과 검증 방법 정의
- 문서 거버넌스 정의 (§12)

---

# 2. 현재 코드베이스 분석 (As-Is)

> 업스트림 `pinky_pro` 분석 결과. 패키지명은 P0-1에서 전면 리네임된다(D-16). As-Is 표기는 upstream 원명을 사용한다.

## 2.1 기존 패키지 현황

| 패키지(upstream) | 리네임 후 | 용도 | 비고 |
|---|---|---|---|
| `pinky_bringup` | `rosy_bringup` | 모터/오도메트리(`bringup.py`), 배터리 | Python, 토픽 상대경로 |
| `pinky_description` | `rosy_description` | URDF, robot_state_publisher | namespace/frame_prefix 이미 지원 |
| `pinky_navigation` | `rosy_navigation` | Nav2/SLAM 설정·런치, 기존 Flask 서버 | 절대경로 토픽 일부 |
| `pinky_gz_sim` | `rosy_gz_sim` | Gazebo 시뮬레이션 | 멀티로봇 검증 활용 |
| `pinky_sensor_adc` | `rosy_sensor_adc` | ADC/배터리 | C++ |
| `pinky_imu_bno055` | `rosy_imu_bno055` | IMU 드라이버 | C++ |
| `pinky_led`/`pinky_emotion`/`pinky_lamp_control` | `rosy_led` 등 | LED/감정 표현 | UI 확장 시 연동 |
| `pinky_interfaces` | `rosy_interfaces` | srv 정의 | rosy_core 인터페이스 확장 |

## 2.2 멀티로봇 관련 발견 사항 (Phase 0 근거)

| # | 위치 | 문제 | 조치 |
|---|---|---|---|
| A-1 | `nav2_params.yaml` (obstacle_layer scan) | `topic: /scan` 절대경로 2곳 | 상대경로 `scan`으로 변경 |
| A-2 | `bringup.py` 모듈 상수 | `ODOM_FRAME_ID = "odom"` 하드코딩 | 파라미터화(frame_prefix) |
| A-3 | `bringup_robot.launch`(XML) | namespace 인자 없음 | **Python launch로 전환 + namespace/frame_prefix 플러밍** (검증 완료) |
| A-4 | LiDAR 런치 include | `frame_id: rplidar_link` 고정 | prefix 적용 |
| A-5 | `gz_bringup_launch.xml` | namespace + `/tf→tf` 리매핑 이미 구현 | **참조 패턴으로 활용** |
| A-6 | 전체 | DDS 도메인 분리 정책 없음 | 로봇별 `ROS_DOMAIN_ID` + localhost-only 프로파일 (D-6, 신원 유도는 D-33) |

## 2.3 기존 Flask 웹서버 (`nav2_web_server.py`, 560줄)

구현된 기능: `GET /api/state`(TF pose·map·**path·costmap** 스냅샷), `POST /api/goal`, `POST /api/initialpose`, `GET /api/nav/status`, `POST /api/nav/stop`, `POST /api/slam/reset`, `POST /api/slam/save_map`.

**부족한 것:** WebSocket, Teleop, Safety/E-Stop, Identity, 인증, 진단, Command Arbitration, Waypoint, Event.

**정책(D-3): Flask 완전 대체.** 위 기능 + 부족분 전부를 rosy_core FastAPI로 재구현. 병행 운용·레거시 경로 호환 없음. path·costmap 스냅샷은 신규 계약에 포함(API Ref §5.3).

---

# 3. 범위 및 우선순위

| 단계 | 내용 | 본 문서 대우 |
|---|---|---|
| Phase 0 | 리네임 + 멀티로봇 리팩토링 | 상세 |
| Phase 1 | rosy_core (미들웨어) | 상세 |
| Phase 2 | rosy_web (로봇 로컬 UI) | 상세 |
| Phase 3 | 2대 멀티로봇 검증 | 상세 |
| Phase 4 | rosy_fleet (중앙 관리) | 상세 |
| Phase 5 | Formation/Swarm | 상세 |
| Phase 6 | Traffic/Docking/AI/OTA | 계약 수준 WBS |

---

# 4. 목표 아키텍처 (To-Be)

## 4.1 프로세스 구조 (D-1)

```text
rosy-core.service (단일 프로세스, systemd 관리)
│
├── Main Thread        rclpy 노드 "rosy_core" (MultiThreadedExecutor)
│                      ├─ ROS Bridge (ROS 구독/퍼블리시/액션 집중, HWA 어댑터 경유)
│                      ├─ Command Manager (cmd_vel 멀렉서 + 우선순위 중재)
│                      ├─ Safety Manager (watchdog/배터리 정책)
│                      └─ State Manager (10 Hz 스냅샷)
│
└── Worker Thread      uvicorn + FastAPI
                       ├─ REST /api/v1/* (계약: API Ref §5)
                       ├─ WebSocket /ws/state, /ws/events
                       └─ rosy_web 정적 파일 서빙 (단일 포트 8080)

[Event Bus D-8]  Managers ──publish──▶ EventBus ──▶ WS 브로드캐스트 / 감사로그 / Fleet Agent
```

## 4.2 cmd_vel 제어 경로 (D-2)

```text
Nav2 (velocity_smoother) ──remap──▶ nav_cmd_vel ─┐
Teleop (API/WS) ──────────────────────────────┤  Command Manager (우선순위 중재, CMD-001 레지스트리)
Fleet Command ────────────────────────────────┤  + Safety Manager (게이트)
                                                  ▼
                                     최종 cmd_vel (유일 퍼블리셔, 50 Hz)
                                                  ▼
                                             Motor Driver (HWA 어댑터)
```

## 4.3 모드 상태머신 (CORE-001)

```text
IDLE ⇄ MANUAL ⇄ NAVIGATION
  │        │         │
  └──▶ EMERGENCY ◀───┘  (어디서든 진입, release는 Admin)
EMERGENCY: 모든 이동 명령 무시, zero-twist 유지
(DOCKING 슬롯은 DNC-002 예약)
```

우선순위: `EMERGENCY(1) > SAFETY(2) > MANUAL(3) > DOCKING(4) > NAVIGATION(5) > FLEET(6) > IDLE(7)`

## 4.4 통신 구조 (D-5, D-6)

- 로봇 내부: ROS 2 (rclpy)
- 로봇 외부(로컬 UI/SDK): REST + WebSocket (8080 단일)
- Fleet↔로봇: 로봇 outbound WS(상태 1 Hz heartbeat + 이벤트) / Fleet→로봇 REST 명령(correlation_id)
- 로봇 간 DDS: 차단

## 4.5 기술 스택 (확정)

| 계층 | 기술 |
|---|---|
| Robot/ROS | ROS 2 Jazzy, rclpy, Nav2, slam_toolbox |
| Middleware | Python 3.12, FastAPI, uvicorn, Pydantic v2 |
| Frontend | 손으로 쓴 정적 ES module + CSS, FastAPI 직접 서빙 (D-75 — 이 표의 `React 18 + TypeScript + Vite (D-7)`는 Superseded) |
| Fleet Server | FastAPI + **SQLAlchemy + Alembic** + SQLite(초기)→PostgreSQL, Docker |
| 배포 | systemd(`rosy-core.service`), `ros2 launch` |

---

# 5. 저장소 및 패키지 구조 (전면 리네임, D-16)

> 실제 리포지토리 루트에는 문서(`docs/`)·CI(`.github/`)가 있고, ROS 패키지는 colcon 관례에 따라 `src/` 아래에 둔다. 아래 트리는 `src/` 내부를 나타낸다(2026-08-29 기준 실제 구성 반영).

```text
src/  (colcon workspace 패키지 루트)
│
├── rosy_bringup/             [리네임+수정] namespace/frame_prefix
├── rosy_navigation/          [리네임+수정] 절대경로 제거, 멀티로봇 파라미터
├── rosy_description/         [리네임] (이미 namespace 지원)
├── rosy_gz_sim/              [리네임+확장] 멀티 인스턴스 런치
├── rosy_sensor_adc/ rosy_imu_bno055/ rosy_led/ rosy_emotion/ rosy_lamp_control/
├── rosy_interfaces/          [리네임+확장]
│
├── rosy_core/                [신규] 핵심 미들웨어
│   ├── rosy_core/
│   │   ├── main.py               # 진입점
│   │   ├── config.py             # YAML 로드/검증 (Pydantic)
│   │   ├── identity.py           # IDN-001~003
│   │   ├── capability.py         # CAP-001~003 (D-11)
│   │   ├── profile.py            # HWA-001 Robot Profile 로더
│   │   ├── state/manager.py      # CORE-001, 10 Hz 스냅샷
│   │   ├── command/manager.py    # cmd_vel 멀렉서 + 모드
│   │   ├── command/arbitration.py# 우선순위 테이블 + 소스 레지스트리 (CMD-001)
│   │   ├── safety/manager.py     # E-Stop/속도제한/저배터리 (SAF-001~005)
│   │   ├── safety/watchdog.py    # teleop timeout
│   │   ├── navigation/manager.py # NAV-001~006
│   │   ├── waypoints/manager.py  # WPT-001~005 (D-9)
│   │   ├── events/bus.py         # Event Bus + seq + 링버퍼 (D-8, EVT)
│   │   ├── bridge/ros_bridge.py  # ROS I/O 집중 (HWA-002 어댑터)
│   │   ├── fleet_agent/agent.py  # outbound WS 클라이언트, backoff, 갭필 (D-5)
│   │   ├── diagnostics/collector.py
│   │   ├── protocol/schemas.py   # envelope/이벤트 스키마 조기 고정 (D-10)
│   │   └── api/                  # app.py, auth.py, audit.py, v1/ 라우터
│   ├── config/rosy_default.yaml
│   ├── config/profile.pinky_pro.yaml   # HWA-001 첫 프로파일
│   ├── config/capabilities.yaml
│   ├── launch/rosy_core.launch.py
│   └── test/
│
├── rosy_web/                 [신규] React 프론트엔드
│   ├── src/api/  src/pages/  src/components/
│   └── dist/  →  rosy_core가 정적 서빙
│
└── rosy_fleet/               [신규, Phase 4]
    ├── fleet/
    │   ├── main.py
    │   ├── registry.py            # REG-001~003
    │   ├── connection.py          # WS 세션/heartbeat (PRT-003)
    │   ├── pairing.py             # SEC-201~203
    │   ├── commands.py            # correlation 추적 (PRT-004)
    │   ├── mission.py             # MSN-001~005 (D-12)
    │   ├── formation/             # FOR (Phase 5)
    │   ├── traffic/               # TRF-002 인터페이스 (Phase 6)
    │   ├── ops/backup.py          # OPS-001~002
    │   └── observability/metrics.py # OBS-201
    ├── api/
    └── migrations/                # Alembic (DAT-001)
```

기존 Flask 서버는 완전 대체(D-3) — P1에서 동등성 달성 시 런치 제거, M2 후 코드 삭제.

---

# 6. rosy_core 상세 설계

## 6.1 State Manager (CORE-001)

입력: `odom`, `battery`, `scan`, IMU, `navigate_to_pose` 피드백, TF(map→base), Nav2 lifecycle, 프로세스/네트워크 메트릭.
10 Hz 불변 스냅샷(dict) 생성, REST/WS/내부 중재가 동일 참조. 필드는 CORE SRS CORE-001 + API Ref §6.1.

## 6.2 Command Manager (CORE-002, CMD-001)

- 명령 정규화 `{source, priority, type, payload, timestamp}` 투입
- 소스 레지스트리(설정 기반 등록, 미등록 소스 거부+감사로그)
- 모드 가드(MANUAL+NAV 소스 → `MODE_CONFLICT` 거부)
- 최종 cmd_vel 50 Hz publish(입력 없으면 zero-twist)
- 수락/거부 전량 감사 로그

## 6.3 Safety Manager (SAF-001~005)

| 기능 | 구현 |
|---|---|
| E-Stop | 플래그 + zero-twist 유지, release는 Admin |
| Teleop Watchdog | 마지막 teleop 시각 추적, 500 ms 경과 시 zero-twist + `safety.watchdog` |
| Fleet 단절 | heartbeat 모니터, STOP/HOLD/RETURN_HOME/CONTINUE (기본 STOP) |
| 속도 제한 | Profile(HWA) 기반 상한 + manual/fleet 한계 클리핑 |
| 저배터리 | 20% 경고 이벤트 / 10% 정책(기본 RETURN_HOME) + 이벤트·감사로그 |

## 6.4 Navigation Manager (NAV-001~006)

- Goal: `{x,y,yaw}` 또는 `{waypoint}` → `NavigateToPose`. map_id 불일치 시 `MAP_MISMATCH` 거부
- 상태 매핑 → NAV 상태 7종, 이벤트(`nav.*`) 발행
- Mapping 세션(NAV-005): slam start/stop/save/reset, 세션 중 Goal 거부
- Stuck(NAV-006): recovery 소진/30초 무진척 → 취소 + `nav.stuck`
- 기존 Flask `send_goal`/`cancel_goal` 로직 이식

## 6.5 Waypoint Manager (WPT, D-9)

- 저장소: `~/.rosy/waypoints.json` (원천), CRUD API, 이름 충돌 `WAYPOINT_EXISTS`
- `__home__` 예약 이름 = NAV-003 Home
- Fleet 동기화 엔드포인트(WPT-005)

## 6.6 Capability + Profile (CAP, HWA, D-11)

- `config/profile.pinky_pro.yaml` → Profile 로더 → `capabilities.yaml` 검증 → `GET /system/capabilities`
- 미지원 명령 → `501 CAPABILITY_NOT_SUPPORTED`

## 6.7 Event Bus (EVT, D-8)

- `EventBus.publish(event)` — 모든 매니저가 EVT-001 스키마로 발행
- 단조 `seq` 카운터(버스 소유), 링 버퍼 1,000개
- 소비자: WS 브로드캐스트(`/ws/events`, 타입 필터), 감사 로그 writer, Fleet Agent forward
- `GET /api/v1/events?since_seq=` 갭 필

## 6.8 Fleet Agent (PRT, D-5, D-10)

- 로봇 측 outbound WS 클라이언트: hello 핸드셰이크 → heartbeat 1 Hz(상태 스냅샷) → 이벤트 forward
- 재접속 exponential backoff 1→30s, 재접속 후 `since_seq` 재전송
- 단절 시 SAF-003 정책 트리거

## 6.9 Diagnostics + Metrics (DIAG, OBS-101)

ROS `/diagnostics` + 자체 수집(CPU/MEM/Disk/온도/네트워크) → 컴포넌트별 `OK|WARNING|ERROR|UNKNOWN`, 1 Hz. `/metrics` Prometheus 노출.

---

# 7. WBS (단계별 실행 계획)

규모 표기: S≤1일, M=2~4일, L≥1주. 각 태스크는 `[요구사항 ID]`로 추적.

## Phase 0 — 리네임 + 멀티로봇 리팩토링 (M0)

| ID | 태스크 | 산출물 / 완료 기준 | 규모 |
|---|---|---|---|
| P0-1 | **리포 구성 + 전면 리네임(D-16)**: ① 포크(`reference/src` → `rosy/`) ② 패키지 디렉터리·`setup.py`·`package.xml`·CMakeLists ③ import 경로 ④ launch include·정적 경로 ⑤ config 파일 경로 ⑥ README ⑦ CI(colcon build + lint) — 리네임 체크리스트 기반 일괄 수행 후 빌드·런치 회귀 | `colcon build` 통과, 전 패키지 rosy_* 명명 일관 | L |
| P0-2 | `nav2_params.yaml` 절대경로 제거 (A-1) | namespace 런치에서 costmap 정상 | S |
| P0-3 | `bringup.py` 프레임 파라미터화 (A-2) | `ns=rosy_01`에서 `/rosy_01/odom`, `rosy_01/odom` TF 정상 | M |
| P0-4 | `bringup_robot.launch.xml` namespace 플러밍 (A-3) + LiDAR frame prefix (A-4) | 실물 1대 namespace 동작 | M |
| P0-5 | DDS 격리: `ROS_DOMAIN_ID` 할당 스크립트 + CycloneDDS localhost 프로파일 (A-6, D-6) | 2대 동일 LAN 상호 간섭 없음 — **이 수용 기준은 아무도 릴리스 2대를 한 LAN에 올리지 않는 한 통과한다.** 판별 형태는 P0-5b 를 쓴다 | S |
| P0-5b | 배포 절반 마감: 신원을 로봇 번호에서 유도하고 세 계층 모두에서 기본값 제거 (D-33) | 같은 릴리스에서 설치한 2대가 서로 다른 도메인·namespace 로 뜬다 | S |
| P0-6 | `rosy_gz_sim` 멀티 인스턴스 런치 (`gz_multi.launch.py`, 인자: 로봇 수/namespace) | 시뮬 2대 독립 주행 | M |
| P0-7 | Flask→FastAPI 동등성 체크리스트 (기존 7 엔드포인트 × API Ref §5 매핑표, path/costmap 포함, 수용 기준 포함) | 체크리스트 문서 | S |

**M0 완료 기준:** 시뮬 2대(`rosy_01`, `rosy_02`) 독립 SLAM/Nav2 주행, 토픽·TF 충돌 없음 → MAT-02, MAT-03 조기 검증.

## Phase 1 — rosy_core (M1) ★핵심

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P1-1 | 스캘폴딩 + 설정 시스템(config.py, rosy_default.yaml, CFG) | `ros2 launch rosy_core ...` 기동 | M |
| P1-2 | Robot Identity (IDN-001~003) | `GET /system/info` 응답 | S |
| P1-3 | ROS Bridge: odom/battery/scan/IMU/TF/Nav2 액션 집중 래핑 (ROS-101, HWA-002) | 단위 테스트 + 시뮬 연동 | L |
| P1-4 | State Manager 10 Hz (CORE-001) | `GET /robot/state` | M |
| P1-5 | Command Manager: cmd_vel 멀렉서 + 중재 + 소스 레지스트리 (CORE-002, CMD-001, D-2) | MANUAL 중 Nav2 차단 테스트 통과 | L |
| P1-6 | Safety Manager: E-Stop·watchdog·속도·Fleet 단절 정책 (SAF-001~004) | AT-06, AT-12 시나리오 통과 | M |
| P1-7 | Navigation Manager + Return Home (NAV-001~004) | AT-07, AT-08 통과 | M |
| P1-8 | Teleop API (§11) + watchdog 연동 | AT-05 통과 | S |
| P1-9 | REST API 전체 (API Ref §5) + 인증·권한 (SEC-101) + 감사 로그 (LOG) | OpenAPI 문서 자동 생성 | M |
| P1-10 | WebSocket `/ws/state` 10 Hz (API-102) | WS 클라이언트로 5 Hz↑ 확인 | M |
| P1-11 | Diagnostics (DIAG) + `/metrics` (OBS-101) | `/diagnostics`, `/metrics` 헬스 표준화 | M |
| P1-12 | systemd `rosy-core.service` + 설치 스크립트 (SRV-001) | AT-01 통과 | S |
| P1-13 | **Flask 완전 대체 완료** (D-3): 동등성 체크리스트(P0-7) 전 항목 통과, 런치 교체 | 기존 워크플로(맵빌딩·주행)를 rosy_core API만으로 수행 | M |
| P1-14 | 통합 테스트: AT-01, 03, 04, 06~08, 12 | 테스트 리포트 | M |
| P1-15 | Capability + Robot Profile (CAP, HWA, D-11) | AT-16 (미지원 명령 501) | S |
| P1-16 | Waypoint Manager + CRUD API (WPT-001~004, D-9) | AT-14 | M |
| P1-17 | Event Bus + `/ws/events` + `/api/v1/events` (EVT-001~005, D-8) | AT-15 | M |
| P1-18 | map_id 노출 + Goal 검증 (MAP-001, MAP-002, D-13) | 불일치 Goal `MAP_MISMATCH` 거부 | S |
| P1-19 | **프로토콜 스키마 패키지 고정** (D-10): envelope/이벤트 스키마(PRT-001, API Ref §7·8)를 `rosy_core/protocol/`에 구현·버전화 | 스키마 단위 테스트 통과 | S |
| P1-20 | 저배터리 정책 + Stuck 감지 (SAF-005, NAV-006) | 임계값 주입 시나리오 통과 | M |
| P1-21 | 네트워크 프로비저닝: `SITE_STA`(기본)와 `RELAY_AP_STA`(장비별 옵트인) NetworkManager 프로파일 스크립트 + 접속 가이드(모드별 폴백 주소) (NET-001~005, D-19→D-26) | 두 모드 각각에서 다른 단말이 대시보드에 접근하는지 확인 | S |

**M1 완료 기준:** ROS CLI 없이 API만으로 기본 기능 제어. **AT 16건 중 API 계열 12건 통과**(브라우저 4건: AT-02, 05, 09, 11은 M2).

## Phase 2 — rosy_web (M2)

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P2-1 | React+TS+Vite 스캘폴딩, API/WS 클라이언트, 빌드 → rosy_core 서빙 | `http://rosy-01.local` 접속 (AT-02) | M |
| P2-2 | Dashboard (WEB): 배터리/모드/위치/헬스 실시간 | AT-03, AT-04 | M |
| P2-3 | Map 뷰: OccupancyGrid + 로봇 위치/방향 + 경로·코스트맵 오버레이 (MAP-003, MAP-004) | AT-09 | L |
| P2-4 | 맵 클릭 → Goal (좌표변환) | AT-10 | M |
| P2-5 | Joystick(가상/게임패드/터치) + MANUAL 연동 (WEB-001) | AT-05 | M |
| P2-6 | E-Stop 버튼 + 해제 + Safety 패널 | AT-11 | S |
| P2-7 | Sensors/Diagnostics/Settings/ROS/**Events/Waypoints** 페이지 (WEB-002 메뉴 전체) | 메뉴 13개 동작 | L |
| P2-8 | Login·롤 기반 UI 제어 | Viewer 제어 요소 비활성 | M |

**M2 완료 기준:** 브라우저(데스크톱+모바일)만으로 주요 기능 운용. AT 16건 전부 통과(실물 기준).

## Phase 3 — 멀티로봇 검증 (M3)

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P3-1 | 실물 2대 namespace/identity/DDS 설정 적용 | MAT-01 | M |
| P3-2 | 로봇별 API 격리 검증 | MAT-04 | M |
| P3-3 | 동시 상태 모니터링 + 동시 상이 Goal | MAT-05, MAT-06 | M |
| P3-4 | Core 독립성 검증 (Fleet 부재) | MAT-08 | S |
| P3-5 | 회귀 벤치마크 시나리오 스크립트: 표준 3종(단일 목적지 주행 / 2대 동시 내비 / Leader-Follow) + `/metrics` 수집·결과 기록 (§8.4) | 시나리오 3종 스크립트화, 결과표 리포지토리화 | M |

시뮬(`gz_multi`) 사전 검증 후 실물. **M3 완료 = MAT-01~06, 08 통과.**

## Phase 4 — rosy_fleet (M4)

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P4-1 | Fleet 스캘폴딩(FastAPI+SQLAlchemy+Alembic, Docker) + Registry/Discovery (REG, DAT-001/002) | mDNS/스캔/수동 등록 | M |
| P4-2 | 로봇 측 Fleet Agent 완성(P1-19 스키마 기반): hello/heartbeat/이벤트 forward/backoff/갭필 (PRT 전체, D-10) | 3회 미응답 → Offline (MON-001) | M |
| P4-3 | Fleet Dashboard: 목록/멀티 맵/그룹 (DASH, CTR-001) | MAT-05 | L |
| P4-4 | 명령 전파 + correlation 추적 + STOP ALL (CTR-001~003, PRT-004) | MAT-07, FAT-03 | M |
| P4-5 | Mission Manager: MSN DSL 실행기 + 멱등 + 이벤트 기반 진행 (MSN-001~004, D-12) | 미션 2개 이상 시나리오 통과 | M |
| P4-6 | **프로토콜 적합성 테스트 스위트** (PRT conformance): envelope 스키마·ack 상태전이·backoff 타이밍·갭필 자동 검증 | CI 통과, FAT-02 | M |
| P4-7 | Waypoint Fleet 동기화 (WPT-005) | FAT-05 | S |
| P4-8 | 온보딩/페어링: 1회용 토큰·승인 대기·폐기 (SEC-201~203) | FAT-01 | M |
| P4-9 | 백업·복구 프로비저닝 (OPS-001~002) | 설정 복원 시나리오 통과 | M |
| P4-10 | 메트릭 수집·집계 + 이벤트 보존 (OBS-201~202) | 집계 대시보드 동작 | M |
| P4-11 | 시뮬 가상 로봇 등록 `sim:true` (SIM-001) | 실물+시뮬 혼합 목록 | S |

**M4 완료 기준:** 3~10대(시뮬+실물 혼합) 통합 관리, **FAT-01~05 + MAT-07 통과**, 핵심 성공 기준(CORE SRS §1.3 원칙 + Fleet SRS §1.2) 충족.

## Phase 5 — Formation/Swarm (M5)

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P5-1 | Formation 생성기: LINE/COLUMN/GRID/V/CIRCLE/FOLLOW 좌표 산출 + 파라미터 (FOR-001) | 6종 좌표 단위 테스트 | M |
| P5-2 | Slot Assignment: 거리 기반 그리디 + 알고리즘 인터페이스(교체 가능) (FOR-002) | 재배정 시 교차 경로 최소 검증 | M |
| P5-3 | Leader-Follower v1 (하이브리드, D-20/D-21): 로봇측 follow 프리미티브(SWM-002, moving-goal ≤2 Hz, `source: fleet`) + Leader pose 스트림(SWM-003) + Fleet 릴레이(≥5 Hz) + 단절 HOLD(SWM-004) | FAT-06: 추종 주행 + Fleet WS 단절 주입 시 전원 HOLD | L |
| P5-4 | Formation 안전: 로봇별 nav 상태 감시 → 중단+HOLD (FOR-004) | 1대 BLOCKED 주입 시 전체 HOLD | S |
| P5-5 | Fleet UI Formation 컨트롤 (DASH) | 3대 시뮬 대형 전환 데모 | M |

**M5 완료 기준:** 시뮬 3대 LINE/V/CIRCLE 전환 + 슬롯 재배정 동작.

## Phase 6 — 플랫폼 확장 (계약 수준)

| ID | 태스크 | 완료 기준 | 규모 |
|---|---|---|---|
| P6-1 | Docking 스텁: `docking.supported=false` 응답 + 하드웨어 인터페이스 계약 문서화 (DNC) | 501 응답 + 계약서 | S |
| P6-2 | Traffic Manager 모듈 인터페이스: 예약 테이블 구조 + MAPF/CBS 교체 지점 설계 (TRF-002) | 인터페이스 설계서 | M |
| P6-3 | OTA: 버전 보고·업데이트 상태머신·롤백 정책 계약화 | 계약 문서화 | M |
| P6-4 | AI 도구 스키마: 최소 도구 세트(로봇 목록/미션 생성/상태 조회/정지) OpenAPI 파생 (AIV-001~002) | 도구 스키마 + 데모 | M |
| P6-5 | 예약 미션 스케줄러 (MSN-005) | cron 시나리오 | M |
| P6-6 | 분산 군집(SWARM-DIRECT) 연구 확장: `source: peer` P2P 유니캐스트 참조 소스 — **D-21 재검토 트리거(≥20대/지연>200ms/Fleet-리스 요구/직접 링크 확보) 충족 시에만 착수** (SWM-007) | 트리거 충족 시 별도 ADR | M |

---

# 8. 테스트 계획

## 8.1 계층별 전략

| 계층 | 방법 |
|---|---|
| 단위 | pytest — 중재 로직, watchdog, 상태머신, Formation 좌표, 좌표변환, 스키마 |
| 계약 | **schemathesis(OpenAPI)** — API Ref 대비 구현 검증, 호환성 회귀 (API-004) |
| 적합성 | **PRT conformance 스위트** (P4-6) — 프로토콜 상태전이·타이밍 |
| 통합 | 시뮬(`rosy_gz_sim`) + rosy_core/rosy_fleet 기동, API 시나리오 |
| 시스템 | 실물 AT/FAT/MAT 체크리스트 |
| 회귀 | Phase 1 종료 후 API 시나리오 + 계약 테스트 자동화 유지 |

## 8.2 인수 시험 매핑

| 시험 | 검증 단계 | 태스크 |
|---|---|---|
| AT-01, 12 | M1 | P1-12, P1-6 |
| AT-02~11, 13 | M2 | P2-1~8 |
| AT-14~16 | M1 | P1-16, P1-17, P1-15 |
| MAT-02, 03 | **M0 선행**(시뮬) → M3 실물 | P0-2~P0-6 |
| MAT-01, 04~06, 08 | M3 | P3-1~P3-4 |
| MAT-07 | M4 | P4-4 |
| FAT-01~05 | M4 | P4-6~P4-8, P4-2 |
| FAT-06 | M5 | P5-3 |

## 8.3 성능 목표 검증 (CORE SRS §25)

- State push 10 Hz / WS 지연 측정 스크립트
- Teleop watchdog ≤500 ms (타임아웃 강제 주입)
- API 처리 지연 p95 ≤100 ms (부하 스크립트)
- 이벤트 전파 ≤200 ms (EVT 발행→WS 수신)
- Swarm: pose 스트림 릴레이 ≥5 Hz·스트림 단절→HOLD ≤1 s (FAT-06, P4-6 적합성 포함)

## 8.4 지속적 개선 루프 (Continuous Improvement)

방법론 자체를 계속 다듬기 위한 구조. 각 마일스톤 종료 시 아래를 실행한다.

1. **회귀 자동화 게이트** — 계약·적합성·API 시나리오 테스트(§8.1) 전량 통과가 다음 Phase 착수 조건
2. **시뮬 벤치마크 축적** — 표준 시나리오 3종(P3-5)의 `/metrics` 결과(주기·지연·성공률)를 리포지토리에 버전 기록 → 마일스톤 간 비교로 성능 회귀 조기 발견
3. **문서·의사결정 리뷰** — ADR Status 점검(Superseded 갱신), 추적 매트릭스(§11) 결행 확인, API Ref ↔ OpenAPI 불일치 점검(API-004)
4. **확장 플레이북 (신규 기능 5단계)** — ① ADR 초안(왜/대안/결과) → ② API Ref 계약 추가(양측 합의·버전 노트) → ③ 플래그/CMD 소스 등록 뒤 구현 + 계약 테스트 → ④ 벤치마크 시나리오에 추가 → ⑤ 변경 이력·추적 매트릭스 갱신. *(D-20 swarm 추가가 본 플레이북의 첫 적용 사례)*

---

# 9. 리스크 및 대응

| 리스크 | 영향 | 대응 |
|---|---|---|
| WiFi DDS 디스커버리 폭주 | 멀티로봇 불안정 | P0-5 도메인 격리 선행, 시뮬 사전 검증 |
| rclpy+uvicorn 스레드 경합 | 상태 불일치/지연 | 불변 스냅샷+짧은 락, 지연 모니터링(P1-11) |
| 실물 2대 확보 지연 | M3 지연 | `rosy_gz_sim` 멀티 인스턴스 대체 검증 후 실물 최종 |
| Flask 기능 이식 누락 | 기능 회귀 | P0-7 체크리스트 + 계약 테스트 회귀 |
| 로봇 보드(RPi급) 리소스 부족 | 10 Hz 미달 | 상태 주기 설정화(5 Hz 폴백), 프로파일링 |
| Nav2 namespace/TF 호환성 | 멀티로봇 파손 | gz_bringup 패턴(A-5) 재사용, M0 조기 검증 |
| **프로토콜 조기 고정 실패** | Phase 4 재작업 | D-10으로 P1-19에서 스키마 선행 고정 + 추가 전용 버저닝(PRT-006) |
| **이벤트 유실·순서 뒤섞임** | Fleet/판동 오판 | seq 단조 증가 + since_seq 갭필 + 적합성 테스트(P4-6) |
| **Mission DSL 과설계** | 일정 지연 | v1은 순차 실행만(D-12), 병렬·조건은 v2 |
| **리네임 재작업 누락** | 빌드·런치 파손 | P0-1 체크리스트 + 빌드·런치 회귀 기준 완료 |

---

# 10. 마일스톤 (1~2인 기준 예상)

| 마일스톤 | 내용 | 예상 기간 | 근거 |
|---|---|---|---|
| M0 | 리네임 + 멀티로봇 리팩토링 | 3~4주 | Phase 0 합계 ~25일 (리네임 L 포함) |
| M1 | rosy_core 완료 (API만으로 제어) | 6~8주 | Phase 1 합계 ~60일 (P1-15~20 추가 반영) |
| M2 | rosy_web 완료 (브라우저 운용) | 3~5주 | Phase 2 합계 ~30일 |
| M3 | 실물 2대 검증 (MAT) | 2주 | Phase 3 합계 ~12일 |
| M4 | Fleet MVP (FAT 포함) | 5~7주 | Phase 4 합계 ~45일 (온보딩·백업·적합성 추가) |
| M5 | Formation | 4주+ | Phase 5 |

---

# 11. 추적 매트릭스 (요구사항 ↔ 태스크 ↔ 시험)

| 요구사항 그룹 | 문서 | 태스크 | 시험 |
|---|---|---|---|
| IDN | CORE | P1-2 | AT-03 |
| CAP / HWA | CORE | P0-1, P1-15 | AT-16, FAT-04 |
| CORE-001 (State) | CORE | P1-4 | AT-03 |
| CORE-002 / CMD-001 | CORE | P1-5 | 단위(중재) |
| SAF-001~004 | CORE | P1-6, P1-8 | AT-05, 06, 11, 12 |
| SAF-005 / NAV-006 | CORE | P1-20 | 시나리오 |
| NAV-001~004 | CORE | P1-7 | AT-07, 08 |
| NAV-005 (SLAM 세션) | CORE | P1-13 | 동등성 체크 |
| WPT-001~005 | CORE/FLEET | P1-16, P4-7 | AT-14, FAT-05 |
| EVT-001~005 | CORE | P1-17 | AT-15 |
| MAP-001~004 | CORE | P1-18, P2-3/4 | AT-09, 10 |
| API-101/102 | CORE | P1-9, P1-10 | 계약 테스트 |
| WEB-001/002 | CORE | P2-1~8 | AT-02~05, 09~11, 13 |
| ROS-101/102 | CORE | P1-3, P1-9 | 단위 |
| DNC-001~003 | CORE | P6-1 | AT-16 |
| DIAG / OBS-101 | CORE | P1-11 | `/diagnostics` |
| SRV-001 | CORE | P1-12 | AT-01 |
| CFG-001/002 | CORE | P1-1 | 설정 로드 |
| SEC-101~103 | CORE | P1-9 | 권한 테스트 |
| NET-001~005 | CORE | P1-21 | AT-02 (SITE_STA peer 접속 / RELAY_AP_STA 경유, 각각) |
| SWM-001~006 | CORE/FLEET | P5-3, P1-19(스키마) | FAT-06 |
| LOG-001/002 | CORE | P1-9, P1-17 | 감사 검증 |
| PRT-001~006 | API Ref | P1-19, P4-2, P4-6 | FAT-02, 03 |
| REG / MON | FLEET | P4-1, P4-2 | MAT-05 |
| DASH / CTR | FLEET | P4-3, P4-4 | MAT-06, 07 |
| SEC-201~204 | FLEET | P4-8 | FAT-01 |
| MSN-001~005 | FLEET | P4-5, P6-5 | 미션 시나리오 |
| FOR-001~004 | FLEET | P5-1~5 | M5 데모 |
| TRF-001~002 | FLEET | P6-2 | — |
| OPS-001~002 | FLEET | P4-9 | 복원 시나리오 |
| OBS-201~202 | FLEET | P4-10 | 집계 확인 |
| SIM-001 | FLEET | P4-11 | 혼합 목록 |
| AIV-001~002 | FLEET | P6-4 | 도구 데모 |
| DAT / NFR | FLEET | P4-1 | MAT-08 |

---

# 12. 문서 거버넌스

| 문서 | ID | 역할 | 변경 권한 |
|---|---|---|---|
| ROSY CORE SRS | ROSY-CORE-SRS-001 | 로봇이 해야 할 것 | 로봇 담당 |
| ROSY FLEET SRS | ROSY-FLEET-SRS-001 | 플릿이 해야 할 것 | 플릿 담당 |
| ROSY API & Protocol Reference | ROSY-API-REF-001 | 양측+외부 공유 계약 | **양측 합의 + 버전 업 전용** |
| ROSY ADR Log | ROSY-ADR-001 | 의사결정 기록 | 결정 시점 기록, 수정 금지(Superseded만) |
| ROSY Implementation Plan | ROSY-PLN-001 | 실행·추적성 | 전체 |

규칙: ① 문서 간 참조는 요구사항 ID 기반 ② 구현은 계약을 임의 확장하지 않는다 ③ API Ref와 OpenAPI 불일치 시 API Ref 우선(API-004).

---

# 13. 다음 액션 (즉시 착수분)

> 진행 상황 (2026-08-29):
> - **완료:** P0 전 태스크(파일 작업) / P1-1, P1-19
> - **P1 1차 스프린트 완료 (2026-08-29):** P1-2(Identity), P1-4(State 10Hz), P1-5(Command 멀렉서·중재·모드머신·소스 레지스트리), P1-6(Safety: E-Stop·워치독·속도 클리핑·배터리 정책), P1-8(Teleop), P1-9(REST 핵심 + 3롤 인증 + ERR-101 표준), P1-10(WS /ws/state·/ws/events), P1-12(systemd 유닛 작성 — 실기기 설치 잔여), P1-15(Capability+Profile), P1-16(Waypoint), P1-17(Event Bus), P1-18(map_id+Goal 검증), P1-20(저배터리·stuck 로직)
> - **검증 증거:** pytest 30/30 통과(중재·워치독·안전·웨이포인트·이벤트·네비·API 7영역) + 실기동 스모크: 노드 기동 → MANUAL 진입 → teleop 스트림 cmd_vel 반영(linear 0.05/angular 0.1) → 스트림 정지 0.7s 후 워치독 자동 zero(SAF-002 실증) / E-Stop 사이클·Waypoint CRUD·이벤트 로그·WS seq 증가 확인
> - **잔여 (P1 2차):** P1-3 잔여(scan·IMU 구독, TF map 좌표 실환경 검증), P1-7 Nav2 액션 실환경 검증(로직은 단위테스트 검증 완료), P1-11(Diagnostics+/metrics), P1-13(SLAM 세션 API + 동등성 체크리스트 실행 → Flask 제거), P1-14(통합테스트 리포트), 실기기 systemd 설치(AT-01)
>
> 검증 기록 (2026-08-29, 로컬 ROS 2 Jazzy):
> - **colcon build 11/11 패키지 통과** (C++ 3종 포함, stderr는 gz upstream deprecation 경고만)
> - **launch smoke test 통과**: `bringup_robot.launch.py`(namespace 그래프 로드), `rosy_core.launch.py`, `gz_multi` OpaqueFunction 로직(액션 수·브리지 YAML prefix·clock 단일화·nav 모드 include — 단위 실행으로 검증)
> - 런타임 수정: bringup XML→Python 전환(XML `$(eval)` 프론트엔드 한계), `gz_multi` import 오류(`PythonLaunchDescriptionSource`)·namespace 규약 버그(`rosy01`→`rosy_01`) 수정
> - 개발환경 참고: 이 머신에 `sllidar_ros2`(LiDAR 드라이버) 미설치 — 스텁으로 include 그래프만 검증, 실기기/시뮬 환경에서 전체 구동 확인 필요

1. **P0 런타임 검증** (ROS 2 Jazzy 환경): `bringup_robot.launch.xml namespace:=rosy_01` 실물 1대, `gz_multi.launch.py robots:=2 mode:=nav` 시뮬 — MAT-02/03 조기 검증
2. **P1-2~P1-14** rosy_core 본구현 착수 (Identity → ROS Bridge → State → Command → Safety → Navigation 순)

---

# 14. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v2.0 | 2026-08-29 | PKY-CORE-PLN-001 v1.0을 재편성. Rosy 전환(전면 리네임 P0-1 상세화), 요구사항 ID 기반 추적로 전환, P1-15~20/P4-6~11/P5 상세/P6 계약 WBS 신설, 계약·적합성 테스트 추가, 문서 거버넌스 신설 |
| v1.0 | 2026-08-29 | PKY-CORE-PLN-001 최초 (승계 이력) |
