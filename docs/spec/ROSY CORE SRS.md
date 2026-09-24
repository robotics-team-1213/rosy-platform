# ROSY CORE Robot Middleware
## 소프트웨어 개발 요구사양서 (로봇 책임)

**Document ID:** ROSY-CORE-SRS-001
**Version:** v1.0
**Target Platform:** Ubuntu 24.04 / ROS 2 Jazzy (첫 구현 하드웨어: Pinky Pro)
**Project Type:** Robot Middleware / Web Control
**Status:** Approved

**승계:** 본 문서는 `PKY-CORE-SRS-001 v0.1`의 로봇(엣지) 책임 분을 승계·확장한다.
플랫폼명을 PINKY → **ROSY**로 전환하고(ADR-D-15, D-16), 하드웨어명 Pinky Pro는 로봇 모델명으로 유지한다.

**관련 문서:**

| 문서 | ID | 역할 |
|---|---|---|
| ROSY FLEET SRS | ROSY-FLEET-SRS-001 | 중앙 서버(Fleet) 책임 |
| ROSY API & Protocol Reference | ROSY-API-REF-001 | 로봇·플릿·외부가 공유하는 유일한 인터페이스 계약 |
| ROSY ADR Log | ROSY-ADR-001 | 의사결정 기록 |
| ROSY Implementation Plan | ROSY-PLN-001 | 실행 계획·추적성 |

---

# 1. 개요

## 1.1 시스템 위치

ROSY CORE는 로봇 내부에서 동작하는 핵심 Middleware 계층이다. 로봇 하드웨어(ROS 2)와 외부 애플리케이션(Web 브라우저·REST·WebSocket·SDK·Fleet·AI) 사이를 잇는 유일한 관문이며, 로봇 1대가 **중앙 서버 없이 독립적으로 안전하게 동작**하는 것을 보장하는 책임을 진다.

## 1.2 본 문서의 책임 범위

본 문서는 다음을 정의한다.

- 로봇 1대가 독립적으로 수행해야 하는 모든 기능 요구사항
- 로봇이 Fleet 및 외부 시스템에 대해 지켜야 하는 계약의 **로봇 측 구현 의무**
- 로봇 단위 인수 시험(AT)

Fleet 서버의 요구사항은 본 문서에 포함하지 않는다(→ ROSY-FLEET-SRS-001).

## 1.3 핵심 개발 원칙

### ROS와 외부 인터페이스 분리

외부 애플리케이션은 ROS Node, Topic, Service 구조를 알 필요가 없어야 한다. 외부는 ROSY API만 사용한다.

```text
/api/v1/robot/state
/api/v1/navigation/goal
/api/v1/navigation/cancel
/api/v1/teleop
```

ROSY CORE가 해당 요청을 내부 ROS 2 Topic, Action, Service로 변환한다.

### Local-First Architecture

중앙 Fleet Server가 존재하지 않아도 로봇은 독립적으로 다음 기능을 수행할 수 있어야 한다.

- 부팅 / 센서 사용 / 모터 제어 / Navigation / 장애물 회피
- Web API / 로컬 Web UI
- Emergency Stop / 상태 확인

Fleet Server의 장애가 로봇 자체의 기본 운용 불능으로 연결되어서는 안 된다.

### 중앙 서버는 모터를 직접 제어하지 않는다

Fleet Server가 일반 이동을 위해 지속적으로 `/cmd_vel`을 전송하지 않는다. 정상적인 자율 이동은 Goal → ROSY CORE → Nav2 → Local Planner → 장애물 회피 → cmd_vel → Motor 경로를 따른다. 수동 Teleoperation은 별도로 지원한다.

본 원칙의 준수 주체는 로봇(ROSY CORE)이다. 로봇은 Fleet을 포함한 어떤 외부 시스템도 cmd_vel의 직접 원천이 되게 해서는 안 된다.

---

# 2. 시스템 구성

전체 플랫폼은 3개 계층으로 구성된다. 본 문서는 Layer 1과 Layer 2의 로봇 측 요구사항을 다룬다.

## 2.1 Layer 1 — Robot Hardware Layer

로봇 하드웨어와 기존 ROS 2 스택. 첫 구현 하드웨어는 **Pinky Pro**이며, 이 계층은 HWA(§5) 어댑터를 통해 교체 가능하다.

주요 구성(첫 구현 기준):

- Motor Driver / Odometry / LiDAR / IMU / ADC·Battery / LED / Emotion
- URDF / TF / SLAM / Nav2

## 2.2 Layer 2 — ROSY CORE (rosy_core)

본 프로젝트의 핵심 Middleware 계층.

```text
rosy_core
│
├── Robot Identity
├── Capability
├── State Manager
├── Command Manager
├── Navigation Manager
├── Waypoint Manager
├── Safety Manager
├── Event Bus
├── ROS Bridge
├── API Server
├── WebSocket Server
└── Diagnostics
```

## 2.3 Layer 3 — Application Layer

ROSY CORE 위에서 동작하는 상위 애플리케이션. 로봇 API만 사용한다.

- Rosy Web(로봇 로컬 UI, §17) / Rosy Fleet / Rosy Swarm
- Mobile Application / Python SDK / ROS Application
- AI Agent / VLA / ERP·WMS Integration

---

# 3. Robot Identity 요구사항

### IDN-001 Robot ID

각 로봇은 영구적인 고유 `robot_id`를 가져야 한다.

```yaml
robot_id: rosy_01
robot_name: Rosy 01
```

### IDN-002 Hostname

권장 hostname 형식:

```text
rosy-01
rosy-02
rosy-03
```

로컬 네트워크에서 mDNS로 접근 가능해야 한다.

```text
http://rosy-01.local
```

## 3.1 네트워크 접속 (운용 모드 2종)

로봇은 두 가지 운용 네트워크 모드를 지원한다(→ ADR D-26). 기본값은 `SITE_STA`이며 릴레이는 장비별로 명시적으로 켠다.

- **`SITE_STA` (기본)** — 로봇이 사업장 WiFi(공유기)에 STA로 참여한다. 작업자 단말·Site Fleet·다른 로봇이 같은 WLAN에 있고 로봇은 AP를 열지 않는다. 다수 로봇 사이트의 정상 운용 모드다.
- **`RELAY_AP_STA` (장비별 옵트인)** — 로봇이 상위 WiFi에 STA로 연결된 상태에서 **동시에 자체 AP를 제공해 무선을 릴레이**한다. 사용자 기기는 로봇 AP에 접속하여 로봇에 직접 접근한다. 상위 공유기가 없거나 신뢰할 수 없는 현장, 시운전 상황을 위한 모드다.

두 모드 모두 동일한 첫 부팅 설정 AP로 프로비저닝된다. 설정 AP는 프로비저닝 전용 임시 모드이며 릴레이 AP와 수명주기가 다르다(→ NET-005).

### NET-001 운용 네트워크 모드

로봇은 `SITE_STA`와 `RELAY_AP_STA`를 모두 지원해야 하며, 어느 모드로 기동할지는 장비별 설정으로 결정한다. 설정이 없으면 `SITE_STA`로 기동한다.

`RELAY_AP_STA`에서는 상위 WiFi 연결(STA)을 유지하면서 동시에 자체 AP를 제공한다. NetworkManager AP 모드 + shared 기반으로 프로비저닝한다. 단일 라디오 제약(AP는 상위와 동일 채널)과 다수 로봇 동시 운용 시의 간섭을 접속 가이드에 명시한다. 이 제약은 릴레이를 켠 장비에만 적용된다.

현재 모드는 API와 대시보드에서 조회할 수 있어야 한다.

### NET-002 단일 진입점

두 모드 모두에서 표준 진입점(`http://rosy-01.local:8080`)으로 접근 가능해야 한다. mDNS 미지원 클라이언트를 위한 폴백 주소는 모드에 따라 다르다.

- `SITE_STA`: 공유기가 할당한 `wlan0` IPv4
- `RELAY_AP_STA`: AP 게이트웨이 IP(예: `http://10.42.0.1:8080`)

두 폴백 주소 모두 접속 가이드에 문서화한다.

### NET-003 업링크 단절 시 로컬 유지

상위 WiFi 또는 인터넷이 끊겨도 로컬 접속·정보 조회·제어(Teleop·Navigation·E-Stop)가 유지되어야 한다. Local-First 원칙(§1.3)의 네트워크 표현이다. 성립 범위가 모드마다 다르다.

- `RELAY_AP_STA`: 로봇 AP 서브넷 안에서 유지된다. 상위 업링크와 무관하다.
- `SITE_STA`: 사업장 WLAN 안에서 유지된다. 인터넷 단절과는 무관하지만, 공유기의 client isolation이 켜져 있으면 같은 WLAN의 단말에서도 로봇에 닿지 못할 수 있다.

두 모드는 실패 양상이 다르므로 인수 시험에서 별도 항목으로 기록한다. 인터넷 도달 성공과 WLAN peer 도달 성공은 서로 다른 판정으로 다룬다.

### NET-004 Fleet 업링크 경유

Fleet 접속(로봇 아웃바운드 WS)은 상위 WiFi 업링크를 경유한다. 릴레이 NAT 하에서도, 사업장 WLAN의 공유기 NAT 하에서도 로봇이 접속을 개시하므로(ADR-D-5) 인바운드 포트 개방이 필요 없어야 한다.

### NET-005 프로비저닝 AP와 운용 AP의 분리

첫 부팅 설정 AP는 프로비저닝 전용 임시 모드이며 운용 모드가 아니다. 프로비저닝이 끝나면 설정 AP와 setup endpoint를 비활성화해야 한다. `RELAY_AP_STA`로 운용하는 장비의 릴레이 AP는 설정 AP와 별개의 프로파일이며, 설정 AP의 자격정보를 재사용해서는 안 된다.

### IDN-003 Robot Information

다음 정보를 API에서 조회할 수 있어야 한다. 상세 응답 스키마는 API Ref를 따른다.

- Robot ID / Robot Name / Hostname / IP Address
- Hardware Model / Hardware Version / Serial Number
- Software Version / ROS Version / Firmware Version
- Capability 목록(→ CAP-001)
- Current Map ID(→ MAP-001) / Uptime

```text
GET /api/v1/system/info
```

---

# 4. Capability 요구사항

### CAP-001 Capability Descriptor

각 로봇은 자신이 지원하는 기능을 표준화된 JSON 형식으로 선언해야 한다. 선언 내용은 정적 설정 파일 기반이며 API로 조회할 수 있어야 한다.

```text
GET /api/v1/system/capabilities
```

선언 항목(초기 버전):

```json
{
  "capability_version": 1,
  "navigation": {
    "goal_navigation": true,
    "return_home": true,
    "max_linear_velocity": 0.20,
    "max_angular_velocity": 0.80
  },
  "teleop": true,
  "slam": true,
  "docking": { "supported": false },
  "sensors": ["lidar", "imu", "battery", "encoder"],
  "events": ["nav.*", "safety.*", "mission.assigned", "system.*"],
  "api_versions": ["v1"],
  "protocol_version": "1.0"
}
```

정확한 스키마 정의는 API Ref를 따른다.

### CAP-002 Capability 버저닝

Capability 스키마는 **추가 전용(Additive)**으로만 진화한다. 새 필드 추가는 기존 소비자 호환성을 깨지 않아야 하며, 소비자는 알 수 없는 필드를 무시해야 한다. 필드 제거·의미 변경은 `capability_version`을 올려야 한다.

### CAP-003 Capability 협상

외부 시스템(Fleet·AI·SDK)은 로봇에 명령을 내리기 전에 Capability를 확인할 수 있어야 한다. 로봇은 자신이 지원하지 않는 명령을 수신한 경우 일반 실패가 아닌 **명확한 에러 코드(`CAPABILITY_NOT_SUPPORTED`)**로 응답해야 한다.

---

# 5. Hardware Abstraction 요구사항 (HWA)

> 목적: ROSY를 Pinky 전용이 아닌 범용 로봇 플랫폼으로 유지하기 위해, 하드웨어 종속성을 격리한다.

### HWA-001 Robot Profile

각 로봇은 하드웨어 명세를 Robot Profile 파일로 정의해야 한다.

```yaml
profile:
  model: Pinky Pro
  drivetrain: differential
  wheel_base: 0.15        # 예시 값, 실제 값은 하드웨어 검증 후 확정
  max_linear_velocity: 0.20
  max_angular_velocity: 0.80
  sensors:
    - lidar: rplidar_c1
    - imu: bno055
    - battery: adc
```

ROSY CORE의 Safety(§9), Navigation(§10) 설정은 로봇 코드에 하드코딩하지 않고 Profile에서 주입받아야 한다.

### HWA-002 Driver Adapter Interface

ROS Bridge(§18)는 로봇별 드라이버(모터·센서·IMU 등)와의 결합을 **어댑터 인터페이스** 뒤로 격리해야 한다. 첫 구현 어댑터는 Pinky Pro(`rosy_bringup` 등)이며, 신규 로봇 추가는 새 어댑터 구현만으로 가능해야 한다(코어 코드 수정 불필요).

### HWA-003 Capability 연동

Robot Profile은 CAP-001 Capability Descriptor 생성의 원천 데이터여야 한다. Profile 변경 없이 Capability가 변경되어서는 안 된다.

---

# 6. Multi-Robot ROS 요구사항

각 로봇의 ROS namespace를 독립적으로 구성할 수 있어야 한다.

```text
/rosy_01/cmd_vel
/rosy_01/odom
/rosy_01/scan
/rosy_01/joint_states

/rosy_02/cmd_vel
/rosy_02/odom
/rosy_02/scan
/rosy_02/joint_states
```

ROS Topic에서 불필요한 절대경로 사용을 제거해야 한다.

## 6.1 TF 분리

로봇별 TF 충돌이 발생해서는 안 된다. 개념적 식별 구조:

```text
rosy_01/odom
 └── rosy_01/base_footprint
      └── rosy_01/base_link

rosy_02/odom
 └── rosy_02/base_footprint
      └── rosy_02/base_link
```

구현은 namespace + frame_prefix 조합을 사용한다(ADR-D-4).

## 6.2 DDS 격리

동일 네트워크 내 로봇 간 ROS DDS 트래픽이 상호 간섭을 일으키지 않아야 한다. 로봇별 고유 `ROS_DOMAIN_ID`와 localhost-only DDS 프로파일을 적용한다(ADR-D-6, 신원 유도는 D-33이 대체). 도메인과 namespace는 모두 로봇 번호 하나에서 유도하며(`40 + N` / `rosy_%02d`), 템플릿·설치 스크립트·compose 어디에도 기본값을 두지 않는다. 로봇 간 통신은 DDS를 사용하지 않고 Fleet을 경유한다.

---

# 7. State Manager 요구사항

### CORE-001 State Manager

다음 상태를 통합 관리한다.

- Online/Offline / Current Mode / Pose / Velocity / Battery
- Navigation State / Motor State / Sensor State / Network State
- Error State / Emergency State

**처리 요구사항:**

- 10 Hz(최소 5 Hz)로 불변 스냅샷을 생성해야 한다.
- REST·WebSocket·내부 중재 로직이 동일 스냅샷을 참조해야 한다.
- 스냅샷에는 `robot_id`, `mode`, `pose{x,y,yaw}`, `velocity{linear,angular}`, `battery{percent,voltage}`, `navigation`(§10 상태), `safety`(§9 상태), `map_id`(MAP-001), `diagnostics_summary`, `errors[]`, `timestamp`가 포함되어야 한다.

상태 push는 WebSocket `/ws/state`로 제공한다(주기·스키마는 API Ref).

---

# 8. Command Manager 요구사항

### CORE-002 Command Manager

모든 이동 명령은 Command Manager를 거쳐야 한다.

입력 소스:

```text
Web / REST API / WebSocket / ROS / Fleet / AI / Local Controller / Plugin(향후)
```

서로 다른 시스템이 동시에 상충하는 명령을 발생시키는 것을 방지해야 한다.

### CMD-001 Command Source 등록 인터페이스

명령 소스는 **등록 기반(Registry)으로 확장** 가능해야 한다. 새 명령 모듈(예: Docking, Patrol, Follow)은 코어 수정 없이 설정 기반으로 소스를 등록할 수 있어야 한다.

```yaml
command_sources:
  - name: manual        # teleop
    priority: 3
  - name: docking
    priority: 4         # 예약됨 (DNC-002)
    enabled: false      # 어댑터 구현 전까지 비활성
  - name: navigation
    priority: 5
  - name: fleet
    priority: 6
```

등록되지 않은 소스의 명령은 거부하고 감사 로그에 기록한다.

## 8.1 Command Arbitration

제어 우선순위:

```text
1. EMERGENCY STOP
2. SAFETY STOP
3. MANUAL CONTROL
4. DOCKING
5. NAVIGATION
6. FLEET COMMAND
7. IDLE
```

- Emergency Stop 활성 시 다른 모든 이동 명령은 무시되어야 한다.
- Manual Control 활성 상태에서 Nav2 이동 명령이 동시에 Motor에 전달되어서는 안 된다.
- Command Manager는 **유일한 `cmd_vel` 퍼블리셔**여야 한다(ADR-D-2). Nav2 출력은 `nav_cmd_vel`로 리매핑해 멀렉싱한다.

모든 수락/거부 명령은 감사 로그에 기록한다(§24).

---

# 9. Safety Manager 요구사항

### SAF-001 Emergency Stop

다음 인터페이스에서 Emergency Stop이 가능해야 한다: Web / REST API / Fleet Server / ROS.

```text
POST /api/v1/safety/stop
```

Emergency Stop은 zero-twist 유지 상태로 진입하며, 해제(`POST /api/v1/safety/release`)는 Administrator 권한으로 제한한다.

### SAF-002 Communication Watchdog

Teleoperation 도중 일정 시간 새로운 명령이 수신되지 않으면 자동 정지한다.

- 기본 Timeout: `500 ms`(설정 가능)
- 만료 시 zero-twist 발행 + `safety.watchdog` 이벤트 발생(§14)

### SAF-003 Fleet Connection Loss

Fleet Server 연결이 끊겨도 ROSY CORE 자체는 동작해야 한다. Fleet 명령 수행 중 연결 장애 시 사전 정의된 Safety Policy를 수행한다.

```text
STOP | HOLD | RETURN_HOME | CONTINUE_CURRENT_NAVIGATION
```

기본값은 `STOP`이다(설정 가능).

### SAF-004 Speed Limit

다음 속도를 설정할 수 있어야 한다.

- Maximum Linear / Angular Velocity (Profile 기반, HWA-001)
- Manual Velocity Limit / Fleet Velocity Limit

Command Manager는 모든 cmd_vel에 상한 클리핑을 적용한다.

### SAF-005 Low-Battery Safety Policy

배터리 임계값 기반 정책을 지원해야 한다.

| 단계 | 기본 임계값 | 동작 |
|---|---|---|
| Warning | 20% | `battery.low` 경고 이벤트 발행, 상태 표시 |
| Critical | 10% | 설정 정책 실행: `RETURN_HOME` 또는 `STOP` + `battery.critical` 이벤트 |
| Deep | 5% | 모터 정지 → 유예 후 호스트 정상 종료 + `battery.deep` 이벤트 (D-27) |

임계값과 정책은 설정으로 변경 가능해야 하며, Critical 정책 실행은 감사 로그에 기록된다.

**잔량은 추정치다.** 전류 센서가 없어 쿨롱 카운팅이 불가능하며, 잔량은 전압을
저역통과 필터에 통과시킨 뒤 팩별 OCV 곡선(`battery_curve`)으로 환산한 값이다.
주행 중에는 전압 새그로 실제보다 낮게 읽힌다. 표시 계층은 이를 정확한 연료계가
아니라 추정치로 제시해야 한다.

단계 전이는 연속 표본 수(`battery_enter_samples`/`battery_exit_samples`)와
복귀 마진(`battery_hysteresis_percent`)을 요구하며, 한 번에 한 단계씩만 이동한다.
모터 기동 시의 전압 새그 한 발이 정책을 오발화시켜서는 안 된다.

**Deep 단계 (D-27).** `battery_deep_dwell_s` 동안 유지되어야 무장되며, 무장 시
CORE는 `${ROSY_DATA_PATH}/battery-shutdown-request.json`에 요청을 기록한다. CORE는
호스트 권한이 없으므로 이 파일은 명령이 아니라 관찰이며, 판단과 실행은 호스트의
`rosy-lowbatt-shutdown` 유닛이 신선도를 자체 검증한 뒤 수행한다. 회복 시 파일이
삭제되므로 유예 중 충전을 시작하면 셧다운은 철회된다.

**저배터리 표시.** 경보 표시는 근접 정보창과 무관하게 동작해야 한다. Warning은
상시 주황, Critical은 빨강 1 Hz 점멸, Deep은 빨강 2 Hz 점멸이며, 절전 모드
(`STANDBY` 포함)에서도 유지된다 — 아무도 앞에 없는 상태가 이 표시가 필요한
바로 그 상황이다.

### SAF-006 사람 회피 (Vision Advisory)

사람은 LiDAR/IR metric 정지의 **확대 사유**이며, vision 단독 정지 사유가 아니다.

- YOLO `person` 분류는 advisory evidence로만 소비한다. 사람이 있으면 정책은
  metric 정지 거리 여유를 넓히고(감속 개시점을 앞당김) 최고 속도를 낮춘다.
- YOLO가 사람을 못 봐도 LiDAR/IR 정지는 그대로 동작한다. 거짓음성이 안전을
  깎지 않는 방향으로만 결합한다 (D-137).
- 사람 감속 후 재가속은 자동이다(사람 소멸 후 정상 속도 복귀). e-stop과는
  다른 경로이며, 해금 조건(SAF-001)을 공유하지 않는다.

---

# 10. Navigation 요구사항

### NAV-001 Goal Navigation

외부에서 목표 좌표 또는 **Waypoint 이름**을 전달할 수 있어야 한다.

```text
POST /api/v1/navigation/goal
```

```json
{ "x": 2.5, "y": 1.8, "yaw": 1.57 }
```

```json
{ "waypoint": "dock_1" }
```

ROSY CORE는 요청을 Nav2 `NavigateToPose` Action으로 변환한다. Goal의 `map_id`가 현재 로봇의 `map_id`와 불일치하면 거부한다(MAP-002).

### NAV-002 Cancel

```text
POST /api/v1/navigation/cancel
```

### NAV-003 Return Home

```text
POST /api/v1/navigation/home
```

Home 위치는 설정 파일 또는 Web UI에서 지정할 수 있어야 한다. Home은 특수 Waypoint로 취급한다(WPT-004).

### NAV-004 Navigation State

상태를 최소 다음과 같이 제공한다.

```text
IDLE | PLANNING | NAVIGATING | ARRIVED | CANCELED | FAILED | BLOCKED
```

### NAV-005 Mapping Session

SLAM 맵 생성을 세션 기반 API로 제어할 수 있어야 한다.

```text
POST /api/v1/slam/start     # 매핑 세션 시작
POST /api/v1/slam/stop      # 세션 종료
POST /api/v1/slam/save      # 맵 저장 (map_id 부여)
POST /api/v1/slam/reset     # 현재 세션 초기화
```

매핑 세션 중 Navigation Goal은 거부한다(상충 방지).

### NAV-006 Stuck Detection

Navigation 중 다음 조건이 지속되면 자동으로 Goal을 취소하고 이벤트를 발행해야 한다.

- Nav2 recovery 동작 소진
- 설정 시간(기본 30초) 이상 pose 진척 없음

```text
이벤트: nav.stuck
```

자동 재시도는 하지 않는다(재시도 판단은 상위 시스템 또는 운용자 책임).

### NAV-007 차선 추종 (고전 CV)

바닥 차선 추종은 YOLO가 아니라 고전 CV 영역이다. 카메라 전처리 worker 위에
라인 횡오차 evidence를 얹고, 주행은 다음 규칙을 따른다.

- 차선 evidence는 조향 보정 입력일 뿐 최종 명령이 아니다. 출력은 Command
  Manager가 소유한다 (D-2).
- 차선 상실이 설정 시간(기본 3초)을 넘기면 정지 + `nav.lane_lost` 이벤트 발행.
  자동 재탐색 주행은 하지 않는다(재개는 운용자 또는 상위 목표 책임).
- 차선 추종 중 최고 속도는 0.10 m/s로 고정한다(SAF-004 상한과 별도의 모드 캡).

## 10.1 Swarm 지원 (로봇측 군집 모드)

> 원칙(D-12 유지): 미션 오케스트레이션은 Fleet. 단 **폐루프 추종은 로봇이 직접 수행**한다(D-20).
> Fleet-완전-중앙 방식의 지연(왕복 목표 갱신)과 Fleet 단일실패점을 제거하기 위한 하이브리드.

### SWM-001 Swarm 명령 경로

Swarm 추종은 별도 cmd_vel 소스가 아니라 **Navigation Manager의 이동 목표 스트림**(moving goal)으로 투입된다(Nav2 장애물 회피 그대로 활용). 모드는 `NAVIGATION`을 유지하고 상태로 군집 역할을 노출한다(SWM-006). v2에서 로컬 추종 컨트롤러(pure-pursuit) 소스로 대체 가능하도록 CMD-001 소스 등록 인터페이스를 예약한다.

### SWM-002 Follow 프리미티브

다음 원자 명령을 지원한다.

```text
POST /api/v1/swarm/follow    # {target_robot_id, distance, lateral, max_speed, stream_timeout_ms, source}
POST /api/v1/swarm/cancel
GET  /api/v1/swarm/state
```

- v1 구현: 목표 갱신 ≤2 Hz moving-goal Nav2 (속도 ≤0.2 m/s 군집 운용에 충분)
- 종료 조건: cancel / 스트림 단결(`stream_timeout_ms`, 기본 1000 ms) → HOLD
- SAF-004 속도 상한·NAV-006 stuck 감지가 그대로 적용된다

### SWM-007 참조 소스 추상화 (분산 진화 훅, D-21)

Follow 소비자는 참조 pose 스트림의 **소스를 묻지 않아야** 한다. `source` 파라미터(`fleet`(기본) | `peer`(예약))로 소스를 지정하며, `peer` 소스(로봇 간 P2P 유니캐스트)는 D-21 재검토 트리거 발생 시 구현한다. 소스 교체가 추종 로직·나머지 계약에 영향을 주어서는 안 된다.

### SWM-003 Leader 역할

Leader로 지정된 로봇은 자신의 pose를 **≥10 Hz 전용 스트림**으로 Fleet에 발행한다(heartbeat 1 Hz와 별도, API Ref §7.8).

### SWM-004 군집 단절 정책

Swarm 활성 중 Fleet/스트림 단절 시 기본 정책은 **HOLD**(자리 유지)이다 — SAF-003 기본값(STOP)과 별도의 군집 전용 설정. 형상 붕괴 방지와 로컬 생존을 모두 고려한 값이며, 정책은 설정 가능하다.

### SWM-005 Capability 선언

```json
"swarm": { "follow": true, "lead": true }
```

Robot Profile(HWA) 기반으로 선언하며, 미지원 로봇은 `CAPABILITY_NOT_SUPPORTED`로 응답한다(CAP-003).

### SWM-006 상태·이벤트 노출

상태 스냅샷에 `swarm` 필드를 추가한다(additive): `{role: leader|follower|none, formation, active}`. 이벤트: `swarm.role_assigned` / `swarm.hold` / `swarm.aborted`.

---

# 11. Manual Teleoperation

Web/API에서 수동 이동을 지원한다.

```text
POST /api/v1/teleop
```

```json
{ "linear": 0.1, "angular": -0.2 }
```

- Teleoperation에는 반드시 Watchdog을 적용한다(SAF-002).
- MANUAL 모드 진입/해제는 `POST /api/v1/mode`로 제어한다.
- MANUAL 모드 중 Nav2 출력은 차단한다(§8.1).

---

# 12. Sensor API

다음 센서 정보를 조회할 수 있어야 한다.

```text
GET /api/v1/sensors
GET /api/v1/robot/pose
GET /api/v1/robot/battery
GET /api/v1/robot/velocity
```

세부 Endpoint: LiDAR / IMU / Battery / Encoder / Motor / Temperature / Device Diagnostics. 응답 스키마는 API Ref를 따른다.

---

# 13. Waypoint 요구사항

### WPT-001 Named Location

로봇은 이름 있는 위치(Named Location)를 저장·관리해야 한다.

```json
{
  "name": "dock_1",
  "x": 2.5,
  "y": 1.8,
  "yaw": 1.57,
  "map_id": "warehouse_a",
  "metadata": { "label": "충전독 앞" }
}
```

### WPT-002 Waypoint CRUD

다음 API를 제공해야 한다.

```text
GET    /api/v1/waypoints
POST   /api/v1/waypoints
PUT    /api/v1/waypoints/{name}
DELETE /api/v1/waypoints/{name}
```

이름 충돌 시 생성을 거부한다. Waypoint는 로봇 로컬 저장소에 영속화한다(ADR-D-9).

### WPT-003 Navigation 연동

NAV-001 Goal에서 waypoint 이름을 직접 사용할 수 있어야 한다.

### WPT-004 Home 일반화

Home(NAV-003)은 예약된 이름의 Waypoint로 구현한다(`__home__`). 기존 Home 설정 호환성을 유지한다.

### WPT-005 Fleet 동기화

Fleet이 로봇의 Waypoint 목록을 조회하고, Fleet에서 생성한 Waypoint를 로봇에 내려보낼 수 있어야 한다. 로봇 간 직접 공유는 하지 않고 Fleet을 경유한다. 동기화 프로토콜은 API Ref를 따른다.

---

# 14. Event 요구사항

### EVT-001 Event Model

상태 스냅숏과 구분되는 **단발성 이벤트**를 표준 스키마로 발행해야 한다. 이벤트는 감사 로그(§24)와 동일한 모델을 공유한다.

```json
{
  "seq": 142,
  "event_id": "8f14e45f-..",
  "ts": "2026-08-29T12:00:00.123Z",
  "robot_id": "rosy_01",
  "type": "nav.completed",
  "severity": "info",
  "source": "navigation_manager",
  "data": { "waypoint": "dock_1" }
}
```

### EVT-002 Event Stream

WebSocket 스트림을 제공한다.

```text
/ws/events?types=safety.*,nav.*
```

타입 와일드카드 필터를 지원한다. 이벤트 카탈로그(전체 유형 목록)는 API Ref에서 관리한다.

### EVT-003 순서 보장 및 갭 필

각 이벤트는 로봇별 단조 증가 `seq`를 가져야 한다. 재접속 클라이언트는 `GET /api/v1/events?since_seq=N`으로 놓친 이벤트를 회수할 수 있어야 한다.

### EVT-004 Event 보존

로봇은 최근 이벤트를 링 버퍼(기본 1,000개, 설정 가능)로 보존하며, 감사 로그로는 기본 30일치를 로컬 파일로 보존한다.

### EVT-005 Event Bus

모든 내부 매니저(Safety·Navigation·Command·System)는 내부 Event Bus를 통해 이벤트를 발행한다(ADR-D-8). 이벤트 소비자(WS 브로드캐스트·감사 로그 기록·Fleet Agent 전달)는 동일 버스에 연결한다.

---

# 15. Map 요구사항

### MAP-001 Map ID

로봇은 현재 로드된 맵의 식별자(`map_id`: 맵 파일명 + 콘텐츠 체크섬, ADR-D-13)를 상태에 보고해야 한다.

### MAP-002 Goal 검증

`map_id`가 불일치하는 Navigation Goal은 거부하고 에러를 반환한다(`MAP_MISMATCH`).

### MAP-003 Map 조회 및 배포

- `GET /api/v1/map` — 현재 OccupancyGrid(메타+데이터) 제공
- `GET /api/v1/navigation/path` — 현재 계획 경로
- `GET /api/v1/map/costmap?scope=global|local` — 코스트맵 스냅샷

맵 배포(Fleet → 로봇)는 수동 복사를 기본으로 하되, API로 맵 업로드가 가능한 구조를 유지한다.

### MAP-004 Web 지도 표시

Web UI에서 현재 맵, 로봇 위치/방향, 경로, 코스트맵을 표시할 수 있어야 한다. 브라우저에서 지도 클릭으로 Goal을 지정할 수 있어야 한다(좌표 변환은 클라이언트가 API Ref 규격에 따라 수행).

---

# 16. Robot API 요구사항 (요약)

### API-101 API 제공

로봇은 REST(`/api/v1/*`)와 WebSocket(`/ws/state`, `/ws/events`)을 단일 포트(기본 8080)로 제공해야 한다.

- 모든 Endpoint의 요청/응답 스키마, 권한, 에러 코드는 **API Ref가 유일한 원천**이다. 본 문서는 요구사항만 기술한다.
- 에러 응답은 표준 형식(`{error: {code, message, detail}}`)을 따른다.
- API 버저닝과 폐기 정책(API Ref §1)을 준수한다.

### API-102 WebSocket 우선

실시간 상태 전송은 REST Polling보다 WebSocket을 우선 사용한다. 기본 상태 갱신 주기는 최소 5 Hz, 권장 10 Hz.

---

# 17. Web UI 요구사항 (로봇 로컬)

로봇 자체에 접속하면 브라우저에서 관리 화면을 사용할 수 있어야 한다. Frontend는 로봇 API만 사용하며, 빌드 산출물을 rosy_core가 정적 서빙한다(ADR-D-7).

초기 Dashboard 구성:

```text
┌────────────────────────────────────┐
│ ROSY 01                   ONLINE ● │
├────────────────────────────────────┤
│ Battery        81%                 │
│ Mode           NAVIGATION          │
│ ROS            OK                  │
│ Nav2           ACTIVE              │
│ LiDAR          OK                  │
│                                   │
│ Position                          │
│ X  1.82   Y  3.21   θ  42°        │
├────────────────────────────────────┤
│ MAP                               │
│              ● Rosy               │
├────────────────────────────────────┤
│ [Joystick] [Home] [Cancel]         │
│         [ EMERGENCY STOP ]         │
└────────────────────────────────────┘
```

### WEB-001 모바일 대응

Web UI는 모바일 브라우저에서 반응형으로 동작해야 하며, Joystick은 터치 입력을 지원해야 한다.

### WEB-002 메뉴

최소 다음 메뉴를 지원한다.

Dashboard / Control / Navigation / Map / Sensors / Devices / Diagnostics / Network / ROS / System / Settings / **Events** / **Waypoints**

---

# 18. ROS Bridge

### ROS-101 Bridge 책임

ROSY CORE는 ROS 2와 외부 Interface 간 Gateway 역할을 수행한다. 로봇 내부 ROS 구현은 변경 가능하지만 외부 API 호환성은 유지한다.

```text
External API /api/v1/navigation/goal
        ↓
Rosy Navigation Manager
        ↓
ROS 2 NavigateToPose
```

모든 ROS I/O(구독·퍼블리시·액션·TF)는 ROS Bridge 모듈에 집중하고, 다른 모듈은 ROS를 직접 다루지 않는다. 드라이버 접근은 HWA-002 어댑터를 경유한다.

### ROS-102 Advanced ROS Interface (개발/디버그)

```text
GET /api/v1/ros/nodes
GET /api/v1/ros/topics
GET /api/v1/ros/services
```

Raw ROS Publish 기능은 기본 비활성화하며 관리자 설정으로만 제한 활성화한다.

---

# 19. Docking (D-28)

### DNC-001 Capability 플래그

Docking 지원 여부는 Capability(`docking.supported`)로 선언한다. 미선언 하드웨어의 기본값은 `false`이며, 그때 §DNC-003의 스텁 계약이 그대로 적용된다.

### DNC-002 모드 통합

Docking 시행 중 모드는 `DOCKING`(우선순위 4, §8.1)으로 전환된다. **도킹 액션은 스테이징 주행(Nav2)까지 스스로 소유하며**, 명령 수락부터 도킹 완료 또는 실패까지 `DOCKING` 모드를 유지한다. 모드 전이표가 `NAVIGATION → DOCKING`을 허용하지 않기 때문이며, 이 구조 덕분에 도킹 중 Fleet 주행 명령이 끼어들지 못한다(4 > 5).

### DNC-003 스텁 계약

Docking 미지원 로봇은 Docking **명령**(`POST /api/v1/docking/dock|undock|cancel`)에 `501 CAPABILITY_NOT_SUPPORTED`로 응답해야 한다. **상태 조회(`GET /api/v1/docking/status`)는 예외로 항상 200을 반환**하며 `supported: false`를 함께 싣는다 — 읽기를 막으면 운영 화면이 "이 로봇은 도크가 없다"조차 표시할 수 없다.

### DNC-004 상태

| 상태 | 의미 |
|---|---|
| `UNDOCKED` | 기본. 도크에 있지 않고 가는 중도 아니다 |
| `DOCKING` | 시퀀스 진행 중 (스테이징·획득·접근·착좌) |
| `DOCKED` | 접점은 물렸으나 충전은 미확인 |
| `CHARGING` | 충전이 확인됨 (DNC-006) |
| `UNDOCKING` | 오도메트리만으로 후진 중 |
| `DOCK_FAILED` | 재시도 소진. 명령 전까지 종착이며 **스스로 재시도하지 않는다** |

**맵은 스테이징까지만 쓴다.** 로컬라이제이션 오차(±10 cm)가 접점 공차(±5 mm)보다 두 자릿수 크므로, 획득 이후의 모든 단계는 관측된 도크 상대 포즈에 폐루프를 건다. 언도킹은 반대로 센서를 보지 않고 오도메트리만으로 직진 후진한다 — 도크에 물린 상태에서는 어떤 거리 센서도 벽을 볼 뿐이다.

### DNC-005 Dock Database

도크는 Waypoint가 아니다. 기종(`dock_types`)과 개체(`docks`)를 분리해 저장하며, 개체는 맵 좌표 포즈·`map_id`·에이전트 주소를 갖는다. 스테이징 포즈는 저장하지 않고 오프셋으로 매번 계산한다(가르친 포즈가 낡은 스테이징을 남기지 않게).

도크 포즈는 **teach-by-docking**으로 기록한다 — 로봇을 도크에 밀어넣은 뒤 그 순간의 맵 포즈를 `POST /api/v1/docking/docks/{id}/teach`로 저장한다. 다른 `map_id`의 도크 요청은 MAP-002에 따라 거부한다.

### DNC-006 충전 확인과 자동 복귀

**충전은 독립된 두 소스로 확인한다** — 도크 에이전트가 보고한 전류 **그리고** 필터를 통과한 팩 전압이 하락하지 않을 것. 로봇에는 충전 신호가 없고(§SAF-005), 이 판정이 D-27 셧다운 억제의 입력이므로, 단일 소스로는 네트워크상의 장치 하나가 안전 경로를 무력화할 수 있다.

**확인된 충전은 SAF-005의 `deep` 셧다운을 억제한다**(D-27 Amendment). 억제 대상은 셧다운이며 단계 판정과 경보 표시는 유지된다.

자동 복귀는 **Warning(20%)** 에서 발동한다. Critical(10%)은 2S 팩의 급락 구간이라 그 지점에서 출발하면 도크 도달을 보장할 수 없고, 전류 센서가 없어 경로 길이 기반 에너지 예산을 산출할 수단도 없다. 수동 조작 세션(우선순위 3)이 있으면 복귀는 보류되었다가 세션 종료 후 실행되며, 20% 위로 회복하면 취소된다. 도크가 없는 로봇에서는 SAF-005의 기존 `RETURN_HOME`/`STOP` 폴백이 그대로 남는다.

### DNC-007 도크 태그 검출 (고전 CV)

획득 이후 접근 단계의 도크 상대 포즈는 카메라 태그 검출이 공급한다. 태그는
YOLO 대상이 아니다 — ArUco 고전 검출(`cv2.aruco`, 사전 `DICT_4X4_50`, 한 변
100 mm)로 충분하며, 트리에 이미 실적이 있다(`games/host/overhead.py`).
YOLO 첫 투입 과제는 사람 회피(SAF-006)로 미룬다 (D-137).

- 태그 사전·크기는 도크 기종 항목(`dock_types`, DNC-005)에 기록한다. 크기가
  없으면 상대 포즈를 풀지 않고 fail-closed.
- 출력은 박스가 아니라 도크 상대 포즈다. 태그 검출 → solvePnP 상대 포즈 변환까지가
  vision 책임이며, 이후 접근 제어는 도킹 SM이 소유한다.
- 태그 상실이 설정 시간(기본 2초)을 넘기면 `DOCK_FAILED`로 종착한다.
  스스로 재시도하지 않는다 (DNC-004).
- 태그 evidence는 D-47 패턴의 generation 바인딩을 따른다. 카메라 보정·태그
  제원이 바뀌면 revision이 바뀌고, 모르는 revision은 fail-closed (D-137).

---

# 20. Diagnostics 요구사항

### DIAG-001 헬스 수집

다음 상태를 Web/API에서 확인할 수 있어야 한다.

ROSY CORE / ROS 2 / Nav2 / Motor / LiDAR / IMU / Battery / Network / CPU / Memory / Disk / Temperature

### DIAG-002 표준화

Health State는 다음으로 표준화한다.

```text
OK | WARNING | ERROR | UNKNOWN
```

1 Hz 갱신을 기본으로 하며, ROS `/diagnostics`와 자체 수집(CPU/MEM/Disk/온도/네트워크)을 통합한다.

### OBS-101 메트릭 노출

로봇은 Prometheus 텍스트 형식의 메트릭을 노출해야 한다.

```text
GET /metrics
```

최소 지표: 상태 갱신 주기, cmd_vel 지연, WS 클라이언트 수, API 지연 히스토그램, 배터리. 수집·집계는 Fleet 책임이다(→ ROSY-FLEET-SRS-001).

---

# 21. 서비스 자동 실행

### SRV-001 systemd

로봇 부팅 시 ROSY CORE가 자동 실행되어야 한다.

```text
rosy-core.service
```

서비스 비정상 종료 시 자동 재시작해야 한다.

---

# 22. Configuration

### CFG-001 설정 분리

환경별 설정을 Source Code에서 분리한다. 설정은 Pydantic로 검증한다.

```yaml
robot:
  id: rosy_01
  name: Rosy 01

network:
  api_port: 8080

safety:
  teleop_timeout_ms: 500
  battery_warning_percent: 20
  battery_critical_percent: 10
  battery_critical_policy: RETURN_HOME

navigation:
  max_linear_velocity: 0.20
  max_angular_velocity: 0.80
```

### CFG-002 Fleet 정책 설정

Fleet 접속 주소, 토큰, 단절 정책(SAF-003)을 설정할 수 있어야 한다.

---

# 23. 보안 요구사항 (로봇 측)

### SEC-101 인증 및 권한

최소 3개 권한 Level을 지원한다.

| Role | 권한 |
|---|---|
| Viewer | 상태·맵·센서 조회 |
| Operator | Navigation, Teleoperation, Stop |
| Administrator | 시스템/ROS/네트워크/Robot ID/Software Update 설정 |

인증은 정적 API 토큰(`Authorization: Bearer`, WS는 쿼리 토큰)을 기본으로 하며, 상세는 API Ref를 따른다.

### SEC-102 전송 보안

HTTPS/WSS는 리버스 프록시(caddy) 옵션으로 지원하고, 초기 폐쇄형 LAN에서는 HTTP 허용을 배포 정책으로 설정할 수 있다. 로봇 API는 CORS 헤더를 제공하지 않는다(AUTH-103). 브라우저 직접 접속이 필요하면 호출자 출신의 리버스 프록시가 CORS를 처리한다.

### SEC-103 Fleet 간 인증

Fleet 접속용 토큰은 사용자 토큰과 분리하며, 페어링·폐기 절차는 Fleet SRS의 온보딩 요구사항을 따른다.

---

# 24. 로그 및 감사 기능

### LOG-001 감사 이벤트

최소 다음 이벤트를 기록한다.

- Robot Start/Stop / User Login / Navigation Command / Manual Control
- Emergency Stop / Safety Event / Fleet Command / Error
- Configuration Change / Software Update / Waypoint 변경 / Mode 변경

### LOG-002 로그 필드

```text
Timestamp / Robot ID / Source / Command·Event / Result / Error Code
```

감사 로그는 EVT-001 이벤트 모델과 동일 스키마를 사용하며, 기본 30일 로컬 보존 후 아카이브한다.

---

# 25. 비기능 요구사항 (로봇 측)

### Performance

일반적인 동일 LAN/Wi-Fi 환경 기준:

| 항목 | 목표 |
|---|---|
| Robot State Update | 최소 5 Hz, 권장 10 Hz |
| Teleop Watchdog | 기본 500 ms 이하 |
| API 내부 처리 지연 | 정상 상태 p95 100 ms 이하 목표 |
| 이벤트 발행 지연 | 발생 후 200 ms 이내 전파 목표 |

### Availability

- Fleet Server 장애가 로봇 ROSY CORE 장애로 전파되지 않는다.
- Web UI 장애가 Navigation·Safety 기능을 중단시키지 않는다.

### 시간 동기화

로봇은 chrony(NTP)로 시간 동기화를 권장하며, 타임스탬프는 UTC(ISO 8601)로 기록한다. Fleet 로그 상관 분석의 전제가 된다.

### 확장성 제약

로봇 보드(RPi급)에서 10 Hz 상태 갱신이 부담될 경우 5 Hz 폴백을 설정으로 지원한다.

---

# 26. 로봇 인수 시험 (AT)

로봇 1대 기준 다음 시험을 통과해야 한다.

| ID | 시험 |
|---|---|
| AT-01 | 부팅 후 rosy-core.service 자동 실행 |
| AT-02 | Web Browser에서 Dashboard 접근 |
| AT-03 | Robot ID 및 상태 조회 |
| AT-04 | Battery 상태 실시간 확인 |
| AT-05 | Joystick Manual Control |
| AT-06 | Teleop 통신 중단 시 Watchdog 자동 정지 |
| AT-07 | Navigation Goal 전송 |
| AT-08 | Nav2 Goal Cancel |
| AT-09 | 지도에서 현재 위치 표시 |
| AT-10 | 지도 선택 위치로 이동 |
| AT-11 | Web Emergency Stop 동작 |
| AT-12 | API Emergency Stop 동작 |
| AT-13 | Web UI 종료 후에도 ROSY CORE·Safety 유지 |
| AT-14 | Waypoint 등록 후 **이름으로** 주행 (WPT-003) |
| AT-15 | `/ws/events`에서 `nav.completed` 이벤트 수신 (EVT-002) |
| AT-16 | Capability 조회 및 미지원 명령 `CAPABILITY_NOT_SUPPORTED` 응답 (CAP-003) |

---

# 27. 주요 산출물 (로봇 측)

1. rosy_core Source Code (및 rosy_* 하드웨어 패키지 리네임 분)
2. rosy_web Source Code (로봇 로컬 UI)
3. ROS Launch / Config / Robot Profile
4. rosy-core.service systemd 유닛
5. Installation Script
6. AT 시험 결과서

---

# 28. 변경 이력

| 버전 | 일자 | 내용 |
|---|---|---|
| v1.0 | 2026-08-29 | PKY-CORE-SRS-001 v0.1의 로봇 책임 분을 승계. Rosy 전환, CAP/HWA/WPT/EVT/SAF-005/NAV-005·006/DNC/WEB/CMD-001/MAP/OBS-101 신설, Fleet 분 제외(→ ROSY-FLEET-SRS-001) |
| v1.1 | 2026-09-20 | 제품 목적 등록: SAF-006 사람 회피, NAV-007 차선 추종(고전 CV), DNC-007 도크 태그 검출(ArUco 고전 CV — YOLO 첫 투입은 SAF-006으로). YOLO 서열은 D-137을 따른다 |
