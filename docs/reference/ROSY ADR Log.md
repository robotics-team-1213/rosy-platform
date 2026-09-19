# ROSY ADR Log
## Architecture Decision Records

**Document ID:** ROSY-ADR-001
**Version:** v1.0

> ADR은 "왜 그렇게 결정했는가"를 보존하는 기록이다. 결정 변경 시 기존 ADR을 수정하지 않고 Status를 `Superseded`로 변경하고 신규 ADR로 대체한다.
>
> 형식: **Status / Context / Decision / Consequences**

| ID | 제목 | Status |
|---|---|---|
| D-1 | 단일 프로세스 (rclpy + uvicorn 스레드) | Accepted |
| D-2 | 자체 cmd_vel 멀렉서 (Nav2 출력 remap) | Accepted |
| D-3 | Flask 완전 대체 — FastAPI 전면 이관 | Accepted |
| D-4 | Namespace + frame_prefix 조합 | Accepted |
| D-5 | Fleet↔로봇: 로봇 outbound WS + Fleet REST 명령 | Accepted |
| D-6 | 로봇 간 DDS 차단 (도메인 격리) | Superseded by D-33 |
| D-7 | React+TS+Vite, 빌드 산출물 정적 서빙 | Superseded by D-75 |
| D-8 | 프로세스 내 이벤트 버스 | Accepted |
| D-9 | Waypoint 로컬 저장소 (JSON) | Accepted |
| D-10 | Fleet 프로토콜 envelope을 Phase 1에 조기 고정 | Accepted |
| D-11 | Capability 정적 YAML → API 노출 | Accepted |
| D-12 | Mission은 Fleet 전용, 로봇은 원자 액션 제공 | Accepted |
| D-13 | map_id = 맵 파일명 + 콘텐츠 체크섬 | Accepted |
| D-14 | 하드웨어 프로파일 계층 (벤더 중립 구조) | Accepted |
| D-15 | 플랫폼명 Rosy 확정 | Accepted |
| D-16 | 전면 리네임 (upstream 자동 병합 포기) | Accepted |
| D-17 | 문서 3+2 구조 및 계약 중심 거버넌스 | Accepted |
| D-18 | 프로토콜 스키마 재사용 — rosy_core 단일 소스 유지 | Accepted |
| D-19 | 접속 토폴로지: 로봇 WiFi 릴레이(AP+STA) 지원 | Superseded by D-26 |
| D-20 | Swarm 하이브리드: 오케스트레이션 Fleet / 폐루프 추종 로봇 탑재 | Accepted (D-12 확장) |
| D-21 | 군집 제어: 계층형 마스터-슬레이브 확정 + 분산 진화 훅 | Accepted (D-20 보강) |
| D-22 | Raspberry Pi OS 런타임: Core/I/O 컨테이너 분리 + 드라이버 deadman | Accepted |
| D-23 | Rosy OS 화면: FastAPI 내장 대시보드 + 읽기 전용 호스트 텔레메트리 | Accepted |
| D-24 | 절전: 센서 듀티 사이클링 + 초음파 웨이크 트리거 | Accepted |
| D-25 | 절전 계층은 STANDBY에서 끝난다 — Pi 5 하이버네이트 미채택 | Accepted |
| D-26 | 접속 토폴로지 재정리: SITE_STA 기본 + 릴레이(AP+STA) 장비별 옵트인 | Accepted (D-19 대체) |
| D-27 | 저배터리 셧다운은 D-25가 미채택한 halt의 유일한 예외 | Accepted |
| D-28 | 도킹: 액션이 Nav2 구간을 소유하고, 로봇이 도크를 폴링하며, 충전은 두 소스로 확인한다 | Accepted |
| D-30 | 현장 설정은 로컬 오버레이에만 쓰고, 토큰은 해시로만 남긴다 | Accepted |
| D-31 | 군집 참조 스트림은 로봇의 소켓이다 — Fleet 은 선택적 중계자 | Accepted |
| D-32 | 광고한 능력을 못 지키면 200 이 아니라 코드로 실패한다 | Accepted |
| D-33 | 로봇 신원은 하나의 로봇 번호에서 나온다 | Accepted (D-6 대체) |
| D-34 | 발행 주기는 그것을 읽는 쪽에 맞춘다 | Accepted |
| D-36 | Signed runtime delivery and writable generation data | Accepted; Pi acceptance pending |
| D-37 | Rosy Control을 Rosy OS 내부 기능으로 흡수 | Accepted |
| D-38 | 흡수된 모든 이동 명령의 최종 중재와 정지는 CORE가 소유 | Accepted |
| D-39 | OS 운용·진단·유지보수와 완료 증거를 통합 | Accepted |
| D-40 | Nav2 기본 유지와 단일 주행 backend 소유권 | Accepted |
| D-41 | 카메라와 OpenCV worker 실행 위치 | Proposed |
| D-42 | 후보 명령과 안전 판단의 내부 전달 계약 | Proposed |
| D-43 | 보정 schema와 릴리스 generation 저장 매핑 | Proposed |
| D-44 | ControlBackend 채택과 OMX 작업 액션 경계 | Proposed |
| D-45 | 저장소 문서와 자산의 단일 기준 경로 | Accepted |
| D-46 | Device 설치 후 readback 증거 계약 | Accepted |
| D-47 | CORE sensor adapter calibration binding | Accepted |
| D-48 | Optional camera preprocessing worker telemetry | Accepted |
| D-49 | Gazebo motion provenance hashes use the absorbed package root | Accepted |
| D-50 | Active rosy_control guides use Rosy OS Device procedures | Accepted |
| D-51 | Independent safety and measured Device acceptance contract | Proposed |
| D-52 | ARM64 camera placement and shadow handoff gates | Proposed |
| D-53 | Device signature/readback trust evidence | Accepted; Pi acceptance pending |
| D-54 | Nav2 profile limits and field maps fail closed | Accepted |
| D-55 | Mobile manipulation is a robot-local mission capability | Accepted |
| D-56 | Odometry and IMU fusion is a measured optional profile | Accepted |
| D-57 | ROS-native first; board and vendor differences stay in adapters | Accepted |
| D-58 | Hardware motion requires an authoritative readiness gate | Accepted |
| D-59 | 사이트 패브릭은 역할별 계약 버스다 | Accepted |
| D-60 | 추종은 navigation이 아니라 swarm 패키지다 | Accepted |
| D-61 | 모듈 상태는 progress·logs·생성 index로 기록하고 계약 시험으로 지킨다 | Accepted |
| D-62 | CORE는 필수이고 나머지 런타임은 선택 슬라이스다 | Accepted |
| D-63 | 모듈형 미들웨어 목표 — CORE는 얇고 슬라이스는 선택이다 | Accepted |
| D-64 | CORE 생산 코드의 rosy_control import는 센서 어댑터뿐이다 | Accepted |
| D-65 | 개념 객체는 CORE와 D-62 슬라이스에 매핑한다 | Accepted |
| D-66 | CORE 이미지에 rosy_control과 OpenCV가 없다 | Accepted |
| D-67 | RobotMode가 운용 계약이고 DeviceState는 inventory 파생이다 | Accepted |
| D-68 | CAP-001과 개념 descriptor는 문서를 나눈다 | Accepted |
| D-69 | 어댑터는 트리 안 YAML 매니페스트다 | Accepted |
| D-70 | 워크플로 엔진은 로봇이 아니라 Fleet이다 | Accepted |
| D-71 | concept 05·09–12·15 apt는 v1 미들웨어가 아니다 | Accepted |
| D-72 | 표면은 법을 공유하고 문법은 나눈다 | Accepted |
| D-73 | 모듈마다 자기 코드를 도는 기능 시험 표면이 있다 | Accepted |
| D-74 | 작업 명령은 CORE를 거쳐 내부 ROS로 가고 조회는 CORE에 남는다 | Accepted |
| D-75 | 로봇 로컬 화면은 손으로 쓴 정적 자산이다 — D-7 React 대체 | Accepted |
| D-76 | 501 본문의 capability는 CAP-001이고 concept_id는 부가다 | Accepted |
| D-77 | 운용자 콘솔은 CORE `/dashboard` 하나다 | Accepted |
| D-78 | ARTIFACT 빌더는 네이티브 ARM64 Pi다 | Accepted |
| D-79 | 게이트 GO는 현재 트리 재실행만 인정한다 | Accepted |
| D-80 | G4 GO는 Device 표면이다 | Accepted |
| D-81 | Fleet 콘솔 v1 gather는 CORE REST 폴링이다 | Accepted |
| D-82 | 팔레트는 OKLCH에서 생성하고 수치 게이트로 지킨다 | Accepted |
| D-83 | ROS-SIM 최소 재실행 묶음 | Accepted |
| D-84 | hardware 장치 패키지는 hardware 프로필 전까지 CORE/io에 없다 | Accepted |
| D-85 | 도크 펌웨어 ARTIFACT는 ESP32 툴체인 증거다 | Accepted |
| D-86 | POSIX identity 시험은 POSIX 호스트에서만 deploy를 찍는다 | Accepted |
| D-87 | ROS-SIM은 그 트리의 colcon install이 있을 때만 시작한다 | Accepted |
| D-88 | Fleet 소켓은 사이트 PC 산출물이며 D-83 뒤에 연다 | Accepted |
| D-89 | D-35 대형 후보는 D-83 Task 14 재실행 전에는 열지 않는다 | Accepted |
| D-90 | 축구는 게임 호스트이지 CORE 모드가 아니다 | Accepted |
| D-91 | Device 비교 ADR은 호스트 pytest로 Accepted 하지 않는다 | Accepted |
| D-92 | L2 컴포넌트는 파일이 아니라 어휘 표로 공유한다 | Accepted |
| D-93 | 마주 오는 두 대는 폭으로 풀리지 않는다 — 교행은 Fleet이 중재한다 | Accepted |
| D-94 | rosy_games 천장 OpenCV는 노트북 호스트이며 D-41을 닫지 않는다 | Accepted |
| D-95 | 합성 천장 프레임은 DEVICE가 아니다 — 기본 observer는 hold | Accepted |
| D-96 | 현장 축구 1v1은 다섯 계단이고 충돌 속도는 기기 안전 다음 | Accepted |
| D-97 | 온보드 축구 시야는 FIELD 반복 뒤 CMD-001 후보다 | Accepted |
| D-98 | Isaac 축구 env는 FIELD 반복 전 폴더를 만들지 않는다 | Accepted |
| D-99 | 학습된 축구 정책은 Policy 플러그인이며 cmd_vel을 내지 않는다 | Accepted |
| D-100 | 골대는 천장에서 ArUco+영역으로 보이고, 득점은 필드 m 폴리곤이다 | Accepted |
| D-101 | 축구 호스트 화면은 노트북 게임 표면이며 CORE `/dashboard`가 아니다 | Accepted |
| D-102 | 노트북 매치 루프는 `--ticks`가 없으면 20 Hz로 Ctrl+C까지다 | Accepted |
| D-103 | match.yaml 한계는 게이트 계약이고 유실 HOLD는 즉시다 | Accepted |
| D-104 | 호스트 arm은 MANUAL 다음에 PUT safety/limits를 건다 | Accepted |
| D-105 | 호스트 정지는 스페이스와 보드 /stop이며 양쪽 safety/stop이다 | Accepted |
| D-106 | Fleet 매치 시작은 나중에 Fleet→games 한 방향이며 지금은 버튼을 만들지 않는다 | Accepted |
| D-107 | D-96 계단 1 호스트는 관측만이며 기본은 모터를 무장하지 않는다 | Accepted |
| D-108 | `--drive`는 계단 2+ 스위치이며 FIELD GO가 아니다 | Accepted |
| D-109 | 계단 4 전 카탈로그는 soccer/heuristic/hold/overhead만이다 | Accepted |
| D-110 | 첫 접촉 limits.linear는 0.10을 넘지 않는다 | Accepted |
| D-111 | `--stair 1–5`는 호스트 프리셋이며 FIELD GO가 아니다 | Accepted |
| D-112 | 계단 1 가시성은 호스트 보고이며 FIELD GO가 아니다 | Accepted |
| D-113 | D-96 남은 실행은 현장 실측이며 LOCAL 호스트 트랙은 닫힌다 | Accepted |
| D-114 | gz_multi 시뮬은 도메인 하나·네임스페이스·ros_gz_bridge다 | Accepted |
| D-115 | gz_multi는 스폰 좌표를 map initialpose로 심는다 | Accepted |
| D-116 | 관제 양보는 출발 로봇과 겹친 pose를 길로 보지 않는다 | Accepted |
| D-117 | RMW는 CycloneDDS만 쓴다 | Accepted |
| D-118 | 생 Image는 Fleet·보드·gz_multi 브리지에 타지 않는다 | Accepted |
| D-119 | 스캔·이미지·IMU는 sensor-data QoS다 | Accepted |
| D-120 | 시뮬 디스커버리는 LOCALHOST 범위이며 ROS_LOCALHOST_ONLY를 쓰지 않는다 | Accepted |
| D-121 | Cyclone 적용은 CORE 기동 전이고 웹은 보고만 한다 | Accepted |
| D-122 | 잘못된 RMW는 다음 CORE 기동에서 Cyclone으로 고친다. OS reboot가 아니다 | Accepted |
| D-123 | 웹은 Cyclone을 오버레이에 저장한 뒤 Host Agent 재부팅을 요청한다 | Accepted |
| D-124 | 대시보드는 AP on/off와 Wi-Fi 연결을 Host Agent로 확인하고 적용한다 | Accepted |
| D-125 | Core 패키지를 논리적 도메인 라이브러리로 분할 (Option A) | Accepted |
| D-126 | 완전 모듈 분리 — CORE는 슬라이스 코드를 import하지 않는다 | Accepted |

---

## D-1 단일 프로세스 (rclpy + uvicorn 스레드)

**Status:** Accepted (2026-08)

**Context:** rosy_core는 ROS 2 노드와 Web API 서버를 모두 구동해야 한다. 별도 프로세스 + ROS 통신 구조도 가능했다.

**Decision:** 단일 프로세스로 Main Thread는 rclpy(MultiThreadedExecutor), Worker Thread는 uvicorn+FastAPI로 구동한다. 스레드 간 데이터는 State Manager의 불변 스냅샷 + 짧은 락으로 보호한다.

**Consequences:** 배포·상태 공유가 단순하다. 기존 Flask 서버도 동일 구조로 검증됨. 대신 장애 격리는 약하므로 systemd 재시작(D-1 보완)과 지연 모니터링에 의존한다.

---

## D-2 자체 cmd_vel 멀렉서

**Status:** Accepted (2026-08)

**Context:** 다중 명령 소스(Web·Fleet·Nav2·향후 Docking)와 E-Stop·모드 중재가 요구된다. `twist_mux` 패키지 사용도 검토했다.

**Decision:** Nav2 velocity_smoother 출력을 `nav_cmd_vel`로 리매핑하고, Command Manager가 **유일한 `cmd_vel` 퍼블리셔**가 되는 자체 멀렉서를 구현한다. E-Stop 상태머신·API·감사 로그와 결합.

**Consequences:** CORE SRS §8.1 요건(우선순위·차단·클리핑)을 완전 구현한다. twist_mux 대비 자체 유지보수 부담이 생긴다.

---

## D-3 Flask 완전 대체

**Status:** Accepted (2026-08)

**Context:** 기존 `pinky_navigation/scripts/nav2_web_server.py`(Flask, 560줄)가 존재한다. 병행 운용·레거시 경로 호환도 선택지였다.

**Decision:** 기존 기능 7종을 포함해 전부를 rosy_core FastAPI(`/api/v1/*`)로 재구현한다. 병행 운용·레거시 경로 호환은 하지 않는다. 기능 동등성 체크리스트 충족 시점에 Flask 런치 제거, Web 완성 후 코드 삭제.

**Consequences:** 이중 유지보수 제거, 단일 스택. 누락 방지를 위해 동등성 체크리스트(Impl Plan P0-7)로 관리한다. path/costmap 스냅샷 등 기존 기능이 계약(API Ref §5)에 명시되었다.

---

## D-4 Namespace + frame_prefix 조합

**Status:** Accepted (2026-08)

**Context:** 멀티로봇에서 ROS 토픽·TF 충돌을 방지해야 한다. 기존 `gz_bringup_launch.xml`이 namespace + `/tf→tf` 리매핑 패턴을 이미 검증했다.

**Decision:** namespace + frame_prefix 조합을 표준으로 한다(예: `/rosy_01/cmd_vel`, TF `rosy_01/odom`).

**Consequences:** 검증된 패턴 재사용으로 리스크 최소. 절대경로 토픽(`/scan` 등)은 제거 대상(Impl Plan P0-2).

---

## D-5 로봇 outbound WS + Fleet REST 명령

**Status:** Accepted (2026-08)

**Context:** Fleet이 로봇에 접속하면 인바운드 방화벽·mDNS·보안 정책 문제가 발생한다.

**Decision:** 로봇이 Fleet WS에 outbound 접속해 상태·이벤트를 push하고, 명령은 Fleet→로봇 REST로 전달한다.

**Consequences:** 네트워크·보안 단순화. 로봇은 Fleet 주소·토큰 설정만 필요하다. 명령 추적은 correlation_id + ack 모델(API Ref §7.5)로 보완한다.

---

## D-6 로봇 간 DDS 차단

**Status:** Superseded by D-33 (2026-09-06)

**Context:** 동일 WiFi에서 다수 로봇의 DDS 디스커버리 트래픽은 불안정의 주 원인이 된다(SRS §33).

**Decision:** 로봇별 고유 `ROS_DOMAIN_ID` + CycloneDDS localhost-only 프로파일로 로봇 간 DDS를 차단한다. 로봇 간 데이터는 Fleet 경유만.

**Consequences:** WiFi 안정성 확보. 시뮬레이션은 예외 프로파일로 처리 필요(Impl Plan P0-5).

---

## D-7 React + TS + Vite 정적 서빙

**Status:** Superseded by D-75 (2026-09-17)

**Context:** 로봇 로컬 Web UI가 필요하다. 로봇 보드(RPi급) 리소스가 제한적이다.

**Decision:** React 18 + TypeScript + Vite로 개발하고, 빌드 산출물(dist)을 rosy_core가 정적 서빙한다(단일 포트 8080).

**Consequences:** 로봇에 Node 런타임 불필요, 부하 최소화. CI에서 프론트엔드 빌드 파이프라인 필요.

---

## D-8 프로세스 내 이벤트 버스

**Status:** Accepted (2026-08)

**Context:** Safety·Navigation·Command·System 이벤트를 감사 로그·WS 브로드캐스트·Fleet Agent가 공통 소비해야 한다.

**Decision:** rosy_core 내부에 경량 pub-sub 이벤트 버스를 두고, 모든 매니저가 EVT-001 표준 이벤트를 발행한다. 소비자(WS/audit/Fleet Agent)가 버스에 연결한다. 단조 증가 `seq` 부여는 버스 책임.

**Consequences:** 이벤트 소비자 추가가 코어 수정 없이 가능(확장성). 프로세스 외 전달은 WS/Fleet 프로토콜이 담당.

---

## D-9 Waypoint 로컬 저장소 (JSON)

**Status:** Accepted (2026-08)

**Context:** Waypoint는 로봇 독립 동작(Local-First)에 필요하므로 Fleet 의존 없이 보존되어야 한다.

**Decision:** 로봇 로컬 파일(JSON, `~/.rosy/waypoints.json`)을 원천 저장소로 한다. Fleet은 동기화 API로 읽기/내려보기만 한다(WPT-005).

**Consequences:** Fleet 장애에도 주행 가능. 로봇 다중화 시 Fleet이 조정(마지막 쓰기 승자 방지는 Fleet 동기화 순서로 관리).

---

## D-10 Fleet 프로토콜 envelope 조기 고정

**Status:** Accepted (2026-08)

**Context:** Fleet 구축은 Phase 4이지만, 프로토콜(envelope·heartbeat·ack·이벤트)을 늦게 정하면 Phase 4에서 로봇 측 재작업이 발생한다.

**Decision:** 프로토콜 envelope v1과 이벤트 모델을 Phase 1에서 스키마로 고정(공유 패키지/스키마 정의)하고, 로봇은 Phase 1부터 이 스키마로 이벤트·상태를 발행한다.

**Consequences:** Phase 4 착수 시 계약만 구현하면 됨. 초기 스키마 설계 오류 위험은 추가 전용 버저닝(PRT-006)으로 완화.

---

## D-11 Capability 정적 YAML → API 노출

**Status:** Accepted (2026-08)

**Context:** 이기종 로봇·AI 사전 검증을 위해 기능 선언이 필요하다. 동적 협상은 초기에 과하다.

**Decision:** Capability는 로봇의 정적 설정(YAML)에서 생성되어 `GET /system/capabilities`로 노출된다. Robot Profile(HWA)이 원천 데이터다(HWA-003).

**Consequences:** 구현 단순·예측 가능. 동적 capability(런타임 장착 등)는 capability_version 상향으로 확장.

---

## D-12 Mission은 Fleet 전용

**Status:** Accepted (2026-08)

**Context:** 미션 상태머신을 로봇에 두면 Fleet 장애 시에도 미션이 돌지만, 로봇별 중복 구현·디버깅 복잡도가 커진다.

**Decision:** Mission DSL 실행기는 Fleet에만 둔다. 로봇은 원자 액션(goto/home/stop/estop)과 이벤트를 제공한다. Local-First는 "기본 조작" 수준에만 적용한다.

**Consequences:** 로봇 단순화, 미션 로직 단일 위치. Fleet 장애 시 진행 중 미션은 중단되나 로봇 안전은 SAF-003이 보장.

---

## D-13 map_id = 맵 파일명 + 체크섬

**Status:** Accepted (2026-08)

**Context:** Fleet 맵 뷰와 Goal 검증(MAP-002)에 맵 동일성 판단 기준이 필요하다.

**Decision:** `map_id`를 `"{파일명}:{내용 체크섬 8자리}"` 형식으로 정의한다.

**Consequences:** 무결성 검증 내장, 중복 맵 자동 구분. 체크섬 변경(재저장) 시 새 map_id가 되는 점은 운용상 주의(버전 관리 정책은 Fleet Maps 화면에서 관리).

---

## D-14 하드웨어 프로파일 계층

**Status:** Accepted (2026-08)

**Context:** ROSY를 Pinky 전용이 아닌 범용 로봇 플랫폼으로 발전시킨다.

**Decision:** 하드웨어 종속(구동계·센서·속도 한계)을 Robot Profile(HWA-001)과 Driver Adapter(HWA-002) 뒤로 격리한다. Pinky Pro가 첫 어댑터 구현이다.

**Consequences:** 신규 로봇 지원 시 코어 수정 불필요(어댑터+Profile 추가). 첫 구현은 Pinky Pro 단일 어댑터이므로 인터페이스 추상화 과설계를 주의한다(2번째 로봇 도입 시점에 인터페이스 확정 다듬기).

---

## D-15 플랫폼명 Rosy 확정

**Status:** Accepted (2026-08)

**Context:** pinky_pro 포크를 기반으로 한 자체 플랫폼 명명이 필요했다. 후보: Brain, Corvus, Rook, Skein, Rosy 등. 색 언어유희 계열을 희망.

**Decision:** **Rosy**(ROS + Pinky 계보 언어유희, "장밋빛 전망")로 확정. 패키지 `rosy_core`/`rosy_web`/`rosy_fleet`, robot_id `rosy_NN`, hostname `rosy-NN`, 서비스 `rosy-core.service`. 하드웨어 모델명 "Pinky Pro"는 유지.

**Consequences:** 브랜드 일관성. 검색 시 일반 단어 혼입 가능성은 `rosy_core` 등 복합어 사용으로 완화.

---

## D-16 전면 리네임 (upstream 자동 병합 포기)

**Status:** Accepted (2026-08)

**Context:** 포크한 하드웨어 패키지(pinky_bringup 등)의 리네임 여부. 유지 시 upstream 병합 용이, 리네임 시 브랜드 일관성.

**Decision:** **전면 리네임**한다(rosy_bringup, rosy_navigation 등 전 패키지). upstream 개선사항은 자동 병합 대신 **수동 백포트**로 수용한다. 리네임은 P0-1에서 일괄 수행(패키지명·import·launch·config 경로·CI·systemd).

**Consequences:** 브랜드 일관성 최대, 리네임 비용은 초기(P0)에 1회 발생. upstream major 갱신 추적 노력 증가 — 참조 zip(reference/src)을 기준 버전으로 고정.

---

## D-17 문서 3+2 구조 및 계약 중심 거버넌스

**Status:** Accepted (2026-08)

**Context:** 단일 SRS가 로봇·플릿·계약을 모두 담아 책임이 모호해지고, Phase 4+ 확장 시 유지가 어려워졌다.

**Decision:** 문서를 5개로 분리한다 — ① CORE SRS(로봇 책임) ② FLEET SRS(플릿 책임) ③ API & Protocol Reference(공유 계약, 양측 합의 시에만 변경) ④ ADR Log(의사결정) ⑤ Implementation Plan(실행·추적). 문서 간 참조는 섹션 번호가 아닌 **요구사항 ID** 기반.

**Consequences:** 책임 경계 명확, 양측 독립 개발 가능(계약 문서만 공유). 원본 PKY 문서 2종은 재배치 후 삭제(이력은 각 문서 변경 이력에 승계).

---

## D-18 프로토콜 스키마 재사용 — rosy_core 단일 소스 유지

**Status:** Accepted (2026-08-29)

**Context:** P1-19에서 `rosy_core/protocol/schemas.py`(envelope·이벤트·ack)를 고정했다. Phase 4의 rosy_fleet도 동일 스키마가 필요하다. 독립 공유 패키지(예: rosy_protocol) 분리도 선택지였다.

**Decision:** 별도 패키지 분리는 보류하고, rosy_fleet이 `rosy_core`(ament_python 의존)를 import하여 재사용한다. 스키마 변경 시나리오는 양측이 같은 리포 내에서 동시 컴파일되므로 계약 파열이 구조적으로 차단된다.

**Consequences:** 초기 복잡도 최소화, 중복 제거. 단 rosy_fleet Docker 이미지에 rosy_core가 포함되는 부피와, 로봇 패키지 의존이 fleet 서버에 끼치는 영향은 P4 패키징 시 재검토(3번째 소비자 등장 시 분리 재고).

---

## D-19 접속 토폴로지: 로봇 WiFi 릴레이(AP+STA) 지원

**Status:** Superseded by D-26 (2026-09-02)

**Context:** 현장 네트워크 구성이 "로봇이 상위 WiFi에 연결된 채 AP처럼 동작해 무선을 릴레이"하는 방식으로 확인됨. 사용자 기기는 로봇 AP를 통해 로봇에 직접 접속한다.

**Decision:** 해당 토폴로지를 표준 배포 시나리오로 수용한다(NET-001~004). NetworkManager AP+shared 프로비저닝, 진입점은 mDNS(`rosy-01.local:8080`) + 게이트웨이 IP 폴백, 업링크 단절 시 AP 서브넷 내 제어 유지, Fleet은 로봇 아웃바운드 접속(D-5)으로 NAT 무관 동작.

**Consequences:** 단일 라디오의 AP+STA 동시 운용 제약(동일 채널)과 릴레이 대역폭 공유로 텔레옵 지연 변동 가능 — SAF-002 워치독과 속도 상한(SAF-004)이 완충. 상위 공유기 교체/채널 변경 시 로봇 AP 채널도 따라가므로 접속 가이드에 유의사항 기재.

---

## D-20 Swarm 하이브리드: 오케스트레이션 Fleet / 폐루프 추종 로봇 탑재

**Status:** Accepted (2026-08-29) — D-12 확장(미션 오케스트레이션 Fleet 전용 원칙은 유지)

**Context:** 기존 Formation 설계는 Leader pose를 Fleet이 받아 Follower별 목표를 계산·전송(약 2 Hz)하는 완전-중앙 방식이었다. 왕복 지연으로 추종이 울퉁불퉁해지고, Fleet 단절 시 형상이 즉시 붕괴된다. 로봇 자체가 군집 모드를 지원하면 좋은지 검토 요청이 있었다.

**Decision:** 하이브리드로 간다. Fleet은 지정·릴레이·중단 판단만(Leader pose 스트림 ≥10 Hz 수신 → Follower WS 릴레이 ≥5 Hz, `swarm/follow` 명령 1회). **폐루프 추종 계산은 로봇 탑재**(SWM-001~006): rosy_core이 pose 스트림을 소비해 moving-goal Nav2(≤2 Hz 갱신)로 추종하고, 스트림/Fleet 단절 시 로컬 HOLD(SWM-004). v2 대안(로컬 pure-pursuit cmd_vel 소스)은 CMD-001 등록 인터페이스로 예약.

**Consequences:** 추종 품질 향상(로컬 10 Hz 스트림 소비), Fleet 단절에도 형상·안전 로컬 유지, Fleet 부하 최소화. 로봇 코드에 follow 상태머신·스트림 타임아웃이 추가됨(복잡도 증가). Fleet은 릴레이 지연(≥5 Hz 보장) 품질에 영향을 주므로 적합성 테스트(P4-6)에 포함.

---

## D-21 군집 제어: 계층형 마스터-슬레이브 확정 + 분산 진화 훅

**Status:** Accepted (2026-08-29) — D-20 보강

**Context:** 군집을 마스터-슬레이브로 할지 분산(P2P)으로 할지 검토했다. 분산의 이점: Fleet 단절에도 형상 유지. 분산의 비용: 리더 선출·합의·분산 안전 중재(검증 난이드 급증), 로봇 간 신규 통신 채널. 결정적 사실: WiFi 릴레이 토폴로지(NET-001)에서 로봇 간 통신도 상위 공유기 경유로 동일 무선 매체를 공유하므로 P2P의 지연 이점이 대부분 상쇄된다.

**Decision:**
1. **계층형 마스터-슬레이브로 확정** — Fleet = 형성 오케스트레이션 마스터(지정·슬롯 배정·중단 판단), Leader 로봇 = 형성 기준(참조 스트림 발행), Follower = 슬레이브(로컬 폐루프 추종, SWM-002).
2. **분산 진화 훅**: 로봇측 follow 소비자는 참조 pose 스트림의 **소스를 묻지 않는다**(`source: fleet|peer`, 기본 `fleet`). 향후 P2P 유니캐스트 소스가 추가돼도 로봇 추종 로직·계약은 불변.
3. **재검토 트리거** (하나라도 충족 시 분산 재고): ≥20대 동시 군집 / Fleet 링크 지연 >200 ms 지속 / Fleet-리스 완전 자율 군집 요구 / 로봇 간 직접 링크(상위 공유기 미경유) 확보.

**Consequences:** 초기 구현 단순·안전 책임 명확·기존 계약 유지. 분산 전환은 소스 어댑터 추가 + ADR 스퍼세드로 가능하도록 인터페이스만 예약(과설계 방지 — 구현은 트리거 발생 시).

---

## D-22 Raspberry Pi OS 런타임: Core/I/O 컨테이너 분리 + 드라이버 deadman

**Status:** Accepted (2026-08-31)

**Context:** 제품의 1차 장치는 Raspberry Pi 5 8GB와 Raspberry Pi OS Lite
64-bit다. ROS 2 Jazzy의 기존 네이티브 배포안은 Ubuntu 24.04를 전제로
하고 있으며, 현재 `rosy_core`는 장치를 직접 열지 않고 `rosy_bringup` 등
Driver Adapter를 통해 명령한다. 단일 컨테이너는 FastAPI와 모든 장치
권한을 결합하고, 한 노드의 장애가 전체 런타임 재시작으로 확대된다.

**Decision:** Ubuntu Noble 기반 ROS 2 Jazzy 사용자 공간을 OCI 이미지로
제공한다. 런타임은 장치 권한이 없는 `rosy-core`와 Pinky Pro 장치
어댑터를 실행하는 `rosy-io`로 나눈다. 두 서비스는 동일한 host network,
`ROS_DOMAIN_ID`, localhost CycloneDDS 정책으로 통신한다. `rosy-io`에는
열거된 장치만 전달하며 `privileged` 모드는 금지한다. 모터 어댑터는 마지막
정상 `cmd_vel` 이후 설정된 시간(기본 500 ms)이 지나면 독립적으로 zero RPM을
명령한다.

**Consequences:** Raspberry Pi OS 호스트에 ROS 2를 별도로 포팅하지 않고
Jazzy 사용자 공간을 고정할 수 있으며, 외부 API와 장치 권한이 분리된다.
반면 host networking, 장치 UID/GID, 이미지 빌드·승격, 두 서비스의 장애
복구를 운영해야 한다. 소프트웨어 deadman은 안전 인증 수단이 아니며,
고위험 용도에는 하드웨어 E-stop 또는 독립 컨트롤러가 추가로 필요하다.

---

## D-23 Rosy OS 화면: FastAPI 내장 대시보드 + 읽기 전용 호스트 텔레메트리

**Status:** Accepted (2026-09-01)

**Context:** Raspberry Pi OS에서 `rosy_core`를 운영하려면 로봇 상태뿐 아니라
CPU, 메모리, 저장소, 온도와 런타임 오류를 현장에서 확인할 화면이 필요하다.
별도 React/Node 서비스는 첫 Pi 5 런타임의 프로세스·배포·장애 표면을 늘린다.
반대로 core 컨테이너에 Docker socket, host root 또는 systemd 제어 권한을
주면 D-22의 Core/I/O 최소권한 분리를 훼손한다.

**Decision:** FastAPI가 `/dashboard`와 로컬 HTML/CSS/JavaScript 자산을 직접
제공한다. 로봇 상태와 제어는 기존 인증된 REST/WebSocket 계약을 재사용한다.
호스트 상태는 `/proc` 핵심 파일, `/sys/class/thermal`과 그 심볼릭 링크 대상인
`/sys/devices/virtual/thermal`, `/etc/os-release`,
`/etc/hostname`만 개별 read-only mount하여 수집한다. 임의 셸 실행, host root,
Docker socket, systemd 제어 및 OS 설정 변경은 대시보드 범위에서 제외한다.

**Consequences:** 별도 프론트엔드 런타임 없이 오프라인 현장 화면을 제공하고
기존 API 역할·감사 경계를 유지한다. host 파일이 없거나 플랫폼이 다르면 일부
값은 `unavailable`로 표시된다. 향후 네트워크·업데이트·재부팅을 제어하려면
별도 최소권한 host agent와 명시적인 명령 계약을 새 ADR로 설계해야 한다.
모드 변경은 UI 확인과 중복 요청 잠금을 거치며 서버가 capability를 재검사한다.
내비게이션 속도 표본은 500 ms 뒤 만료되어 stale 명령 재생을 막는다.

---

## D-24 절전: 센서를 끄지 않고 듀티 사이클링하며 초음파를 웨이크 트리거로 쓴다

**Status:** Accepted (2026-09-01)

**Context:** 세워둔 Rosy의 상시 소비원은 둘이다. `rosy_sensor_adc`는 I2C ADC
5채널을 20 Hz로 폴링하는데 채널당 6 ms 왕복이라 한 사이클이 약 30 ms이고,
`rosy_emotion`은 240x320 RGB565 프레임을 10 Hz로 SPI에 밀면서 백라이트를
100% PWM으로 유지한다. 그러나 어느 쪽도 그냥 끌 수 없다. 초음파 채널은 사람이
다가온 것을 알아채야 하는 웨이크 트리거이고, 배터리 채널은 SAF-005 정책에
계속 값을 공급해야 한다. 별도의 저전력 웨이크 IC나 터치 센서는 현재 하드웨어에
없다.

**Decision:** 종료가 아니라 듀티 사이클링을 택한다. `rosy_core`의
`PowerManager`가 ACTIVE/IDLE/STANDBY를 결정해 `power/mode`로 발행하고,
하드웨어 노드는 그 모드를 자기 장치 동작으로만 번역한다. ADC는 20/5/2 Hz로
주기를 바꾸고 STANDBY에서는 초음파·배터리 채널만 읽는다. LCD는 IDLE에서
디밍, STANDBY에서 백라이트 소등과 슬립 진입, SPI 전송 중단을 한다.
웨이크 센서는 초음파 하나이며, 양방향 디바운스와 히스테리시스로 판정하고
`contact_m` 이내는 접촉으로 간주한다. 절전은 표시·샘플링 정책일 뿐 모터
권한이 없다 — 명령·비 IDLE 모드·배터리 경보는 즉시 ACTIVE로 되돌린다.

**Consequences:** STANDBY에서 I2C 왕복이 사이클당 5회에서 2회로, 폴링이
20 Hz에서 2 Hz로 줄고 백라이트가 꺼진다. 2 Hz에서도 접근한 손은 500 ms 안에
검출되어 체감 지연이 없다. 대신 STANDBY 동안 IR 채널이 발행되지 않으므로 이
토픽에 의존하는 소비자는 ACTIVE를 전제해야 하고, 웨이크 판정이 초음파 시야에
묶여 사각지대가 남는다. ADC 노드는 유효한 `power/mode`를 받기 전까지 기동
주기를 유지하므로 `rosy_core` 장애가 센서를 느리게 만들지는 못한다.
IR·IMU 기반 보조 웨이크가 필요하면 별도 ADR로 다룬다.

---

## D-25 절전 계층은 STANDBY에서 끝난다 — Pi 5 하이버네이트는 채택하지 않는다

**Status:** Accepted (2026-09-01)

**Context:** D-24의 듀티 사이클링 아래로 한 단계 더 내려갈 수 있는지 조사했다.
Raspberry Pi 5는 2026년 중반 기준 suspend-to-RAM(`mem`)도 하이버네이트(`disk`)도
지원하지 않는다. BCM2712에 상시 도메인 하드웨어는 있으나 Broadcom SDRAM PHY
self-refresh 시퀀스가 공개되지 않아 펌웨어 경로가 막혀 있다. 실제로 존재하는
유일한 딥 상태는 `POWER_OFF_ON_HALT=1` + `halt`로 PMIC를 STANDBY에 넣는 약 3 mA
상태이며, Pi 5에서는 `WAKE_ON_GPIO`가 의미를 잃어 전원 버튼과 RTC 알람만이 웨이크
소스다. 즉 Pi 5의 전력 상태는 상시 약 2.7 W 아니면 사실상 꺼짐이고 중간 단계가
없다. 한편 세워둔 로봇의 소비는 DYNAMIXEL 홀딩 토크, 상시 회전하는 RPLIDAR C1
모터, LCD 백라이트, SoC 순이라 SoC는 목록의 맨 위가 아니다.

**Decision:** 절전 계층을 ACTIVE/IDLE/STANDBY에서 끝내고 딥 halt를 그 아래
단계로 채택하지 않는다. 네 가지가 D-24의 계약과 충돌하기 때문이다. (1) 웨이크
센서가 함께 죽는다 — halt된 Pi는 초음파를 샘플링하지 못하므로 D-24의 유일한
웨이크 트리거가 사라지고 RTC 예약과 물리 버튼만 남는다. (2) 복귀가 resume이
아니라 부팅이라 Docker/ROS 2 그래프 재기동까지 수십 초가 걸려 500 ms 목표와
자릿수가 다르다. (3) E-Stop, 50 Hz `cmd_vel`, teleop 워치독, SAF-005가 모두
멈춰 "절전은 모터 권한이 없다"는 경계를 깬다. (4) DDS 디스커버리·오도메트리·
SLAM 세션·진행 중 목표가 소실된다. 대신 실효 절감을 LiDAR 모터로 돌린다
(PWR-005): `sllidar_ros2`의 `stop_motor`/`start_motor`를 STANDBY에 연결하되
`power.lidar.standby_stop`은 기본 `false`로 출하해 벤치 승인 뒤 켠다. 모터 토크
오프는 절감이 가장 크지만 전력 정책이 액추에이터 상태를 지시하게 되어 경계를
넘으므로 별도 ADR로 유보한다.

**Consequences:** 세워둔 로봇에서 Pi의 2.7 W는 회수 대상이 아니며, 남은 절감은
주변장치에서만 나온다. LiDAR 정지는 코드 경로가 완성·단위 검증되었지만 기본
비활성이라 실측 이득은 벤치 승인 전까지 0이고, 스캔 단절이 실행 중 Nav2
라이프사이클에 주는 영향은 실기 관찰 항목으로 남는다. 정지 상태에서 재기동
후 스캔을 신뢰하기까지의 창은 `lidar_ready`로 노출되며 `spinup_s: 2.0`은
아직 추정값이다. 근접 웨이크를 유지한 채 호스트를 재우려면 초음파를 쥐고
전원 버튼/`GLOBAL_EN`을 구동하는 상시 MCU가 필요해 보드 변경 사안이 된다.
Jetson·x86처럼 서스펜드가 제대로 되는 컨트롤러로 확장할 때는 `PowerManager`를
정책 소유자로 두고 `PlatformPowerBackend`가 자기 능력을 선언하는 형태로 가며,
그 시점에 별도 ADR로 다룬다. 조사 근거와 출처는
`docs/plans/2026-09-01-deep-power-states-design.md`에 있다.

**Amendment (2026-09-02):** 이 결정은 `halt`를 *절전 계층의 한 단계*로
채택하지 않는다는 뜻이며, 모든 `halt`를 금지하는 것이 아니다. D-27이 배터리
안전 정책에서 오는 단 하나의 예외를 인터록과 함께 기록한다. 위 (1)~(4)의
반론은 그대로 유효하지만 전부 "깨어날 것을 전제한 절전"에 대한 것이고,
D-27의 셧다운은 깨어남을 전제하지 않는다 — 사람이 충전기를 꽂는 것이
복귀 절차다. 두 결정은 함께 읽어야 한다.

---

## D-26 접속 토폴로지 재정리: SITE_STA 기본 + 릴레이(AP+STA) 장비별 옵트인

**Status:** Accepted (2026-09-02) — D-19 대체

**Context:** D-19은 "로봇이 상위 WiFi에 STA로 붙은 채 동시에 자체 AP로 무선을
릴레이하고 사용자 기기는 로봇 AP로 접속한다"를 **표준** 배포 시나리오로 못박았다.
ROSY OS v1 이미지·릴리스 설계를 진행하면서 이 전제가 두 방향에서 압박을 받았다.

한편으로 릴레이는 실제 현장 요구다. 상위 공유기가 없거나 신뢰할 수 없는 장소,
작업자가 로봇에 직접 붙어야 하는 시운전 상황에서 릴레이는 대체재가 없다. 이
요구는 사라지지 않았다.

다른 한편으로 릴레이를 **모든 장비의 기본**으로 두면 비용이 붙는다. Pi 5의 단일
라디오에서 AP와 STA는 같은 채널을 공유하므로 상위 공유기가 채널을 바꾸면 로봇 AP도
따라 움직인다. 로봇을 여러 대 같은 사업장에 놓으면 각 로봇이 자기 AP를 열어 2.4/5 GHz
대역에 서로 간섭하고, 릴레이 NAT가 로봇마다 별도 서브넷을 만들어 Fleet과 작업자
단말의 주소 체계를 복잡하게 만든다. 게다가 상시 AP는 첫 부팅 프로비저닝용 임시 AP와
수명주기가 달라, 하나의 무선 인터페이스에 두 종류의 AP 정책이 겹친다.

즉 릴레이는 **필요하지만 기본값으로는 비싸다**. D-19의 오류는 릴레이를 지원한
것이 아니라 그것을 유일한 표준으로 규정한 것이다.

**Decision:** 접속 토폴로지를 두 모드로 나누고 기본값을 바꾼다.

- `SITE_STA` — **기본값.** 로봇이 사업장 WLAN에 STA로 참여한다. 작업자 단말, Site
  Fleet, 다른 로봇이 같은 WLAN에 있고 로봇은 AP를 열지 않는다. 다수 로봇 사이트의
  정상 운용 모드다.
- `RELAY_AP_STA` — **장비별 옵트인.** D-19이 규정한 AP+STA 릴레이를 그대로 유지한다.
  NetworkManager AP + shared 로 프로비저닝하고, 사용자 기기는 로봇 AP를 통해 로봇에
  직접 접근하며 상위 WiFi가 있으면 릴레이한다. 설정으로 명시적으로 켤 때만 동작한다.

두 모드는 **동일한 첫 부팅 설정 AP**로 프로비저닝된다. 설정 AP는 프로비저닝 전용
임시 모드이며 릴레이 AP와 별개다. 운용 모드 선택은 프로비저닝 단계에서 이루어지고
장비별 설정에 기록된다.

릴레이는 v1 범위 안이다. 후속 Capability로 미루지 않는다.

**Consequences:** D-19의 릴레이 구현 요구는 살아남고 NET-001~004도 폐기되지 않는다.
다만 NET-001은 "릴레이가 가능해야 한다"에서 "두 모드를 지원하되 기본은 SITE_STA"로
바뀌고, NET-002/003/004는 두 모드 각각에서 성립하도록 읽혀야 한다. 특히 NET-003의
"업링크 단절 시 로컬 유지"는 릴레이 모드에서는 로봇 AP 서브넷 안에서, STA 모드에서는
사업장 WLAN 안에서 성립하며 후자는 공유기의 client isolation 설정에 의존한다 — 이
둘은 서로 다른 실패 양상을 가지므로 인수 시험에서 별도 항목으로 기록한다.

네트워크 상태머신은 모드 하나가 아니라 둘을 표현해야 하고, 대시보드의 네트워크 카드도
현재 모드를 세 값(`PROVISIONING_AP` / `SITE_STA` / `RELAY_AP_STA`) 이상으로 구분해
보여야 한다. 릴레이의 채널·간섭 제약은 사라진 것이 아니라 옵트인한 장비에 국한된다.
그 제약은 접속 가이드에 남긴다.

설계 근거는 `docs/plans/2026-09-01-rosy-os-v1-image-release-design.md`에 있다.

---

## D-27 저배터리 셧다운은 D-25가 미채택한 halt의 유일한 예외

**Status:** Accepted (2026-09-02)

**Context:** SAF-005는 크리티컬에서 `RETURN_HOME` 또는 `STOP`까지만 정의한다.
그 아래로 계속 방전되면 결국 팩 보호 회로가 컷오프하는데, 이는 셀을 지키는
동작이지 호스트를 지키는 동작이 아니다. Raspberry Pi 입장에서는 루트
파일시스템이 마운트되고 Docker가 쓰고 있는 상태에서의 예고 없는 전원 제거이며,
반복되면 SD 카드 손상으로 이어진다. 즉 여기서 보호 대상은 셀이 아니라
파일시스템이다. 한편 D-25는 Pi 5의 `halt`를 "채택하지 않는다"고 기록했고,
문서 자체가 그런 상태는 "같은 idle 타이머에서 도달 가능해서는 안 된다"고 썼다.
배터리 안전 경로는 idle 타이머가 아니지만, D-25의 문구를 해석으로 우회해서
기계를 끄는 코드를 넣을 수는 없다.

**Decision:** 배터리 정책에서 출발하는 셧다운 하나를 D-25의 예외로 채택하고,
다음 인터록을 함께 고정한다. (1) 배터리 정책에서만 도달 가능하다 — 어떤 dwell
타이머, 어떤 무활동 경로에서도 도달할 수 없다. (2) SAF-005 아래 신설된 `deep`
단계를 `battery_deep_dwell_s` 동안 유지해야 무장된다. 표본 수가 아니라 초 단위
조건이므로 어떤 필터 튜닝으로도 순간값이 셧다운을 일으킬 수 없다. (3) 회복하면
취소된다 — 무장이 풀리면 센티넬이 삭제되고, 유예 중 충전을 시작하면 별도 신호
없이 셧다운이 철회된다. (4) 모터를 먼저 세운 뒤에만 진입한다. 실행 경로는 Host
Agent가 아니라 일방향 센티넬이다: CORE가 `/var/lib/rosy`에 관찰을 기록하고
호스트의 `rosy-lowbatt-shutdown.path`/`.service`가 신선도를 스스로 판정해
실행한다. Host Agent의 모든 명령은 `administrator` + 확인 필수인데 배터리 정책은
확인해 줄 사람이 없어, 그 경로를 쓰면 무인·무확인 실행 예외를 뚫어야 하고 이는
D-22가 세운 경계 자체를 약화시킨다.

**Amendment (2026-09-02, D-28):** 인터록이 하나 늘었다. **확인된 충전은
셧다운을 억제한다.** 4%에 도크에 도착한 로봇은 수 분간 `deep` 을 유지하므로,
억제가 없으면 충전기 위에서 halt 하고 D-25 대로 다시 깨어나지 못한다.
충전에 성공하고 벽돌이 되는 것은 그냥 방전되는 것보다 나쁘다. "확인된"은
도크의 주장이 아니라 도크가 보고한 전류 **그리고** 떨어지지 않는 팩 전압을
뜻한다 — LAN 의 장치 하나가 말만으로 안전 경로를 끄지 못하게 하기 위해서다.

**Consequences:** 로봇이 스스로 꺼질 수 있게 되었고, 이는 되돌리려면 사람이
가야 하는 동작이다. 그래서 오발화 비용이 크고, 그 대가로 dwell·히스테리시스·
호스트측 재확인이라는 삼중 조건이 붙는다. `.service`에 `[Install]` 절이 없어
path 유닛만이 이를 기동할 수 있다 — `/var/lib/rosy`가 영속이므로 불결한 종료가
남긴 센티넬이 다음 부팅을 끄는 것을 이 구조가 막는다. 호스트는 센티넬의
`grace_seconds`를 상한으로 클램프하므로 컨테이너 쪽 값이 무한정 대기를 만들 수
없다. 반대 방향의 한계도 분명하다. 전류 센싱이 없어 잔량은 추정치이고, 주행
중에는 전압 새그로 실제보다 낮게 읽힌다 — `deep` 임계를 5%로 낮게 잡고 dwell을
건 이유가 이것이다. 그리고 이 셧다운은 "충전하러 갈 곳"을 전제하지 않는다.
도킹스테이션이 생기면 `deep` 진입 전에 도크 복귀를 시도하는 단계가 그 위에
들어가야 하며, 그때 이 결정을 다시 읽어야 한다. 설계 근거는
`docs/plans/2026-09-02-battery-integrity-low-battery-alert-design.md`에 있다.

---

## D-28 도킹: 액션이 Nav2 구간을 소유하고, 로봇이 도크를 폴링하며, 충전은 두 소스로 확인한다

**Status:** Accepted (2026-09-02)

**Context:** 도킹은 첫 SRS 이래 스텁이었다 — `docking.supported=false`, 두
엔드포인트에 501, 우선순위 슬롯 4 예약, `RobotMode.DOCKING` 은 enum 에만 존재.
실물 도크를 설계하면서 코드가 이미 정해둔 세 가지가 설계를 제약했다. (1)
`RETURN_HOME` 은 예약 waypoint `__home__` 을 찾는데 그것을 만드는 코드가
리포에 없어, 기본 크리티컬 정책이 실제로는 STOP 으로 동작해 왔다. (2) 모드
전이표가 `NAVIGATION → DOCKING` 을 막아 "스테이징 주행 후 도킹 전환"이 표현
불가능하다. (3) `Waypoint` 는 포즈만 담아 기종·스테이징 오프셋·에이전트 주소를
가진 도크를 표현할 수 없다. 여기에 하드웨어 제약이 겹친다: `batt_state` 의
`current`·`percentage` 는 NaN 이고 `power_supply_status` 는 `UNKNOWN`
하드코딩이라, 로봇에는 "충전 중"을 알 신호가 하나도 없다.

**Decision:** 넷을 함께 정한다. **(1) 도킹 액션이 Nav2 구간을 소유한다.**
전이표에 간선을 더하는 대신 명령 수락부터 도킹 완료·실패까지 `DOCKING` 모드를
쥔다. 표를 건드리지 않고, `DOCKING`(4) > `NAVIGATION`(5) 이므로 도크에 반쯤
들어간 로봇을 Fleet 주행 명령이 밀어내지 못하는 성질을 공짜로 얻는다. Nav2 의
`opennav_docking` 도 같은 구조다. **(2) 도크를 계측하고 로봇이 폴링한다.**
도크는 어느 로봇이 오는지 모르고 로봇은 자기가 갈 도크를 안다. 도크가 밀어넣는
구조는 로봇 API 에 인증 없는 인바운드를 열고, Fleet 경유는 Fleet 이 죽으면
충전을 막는다. 도크에 MCU 를 두는 근거는 전류 보고가 아니라 **바닥의 상시 통전
접점이 위험하다**는 것이다 — 부하를 감지한 뒤에만 통전한다. **(3) 충전은 독립된
두 소스로 확인한다** — 도크가 보고한 전류 그리고 떨어지지 않는 팩 전압. 이
판정이 D-27 셧다운 억제의 입력이라, 단일 소스면 LAN 의 장치 하나가 안전 경로를
끌 수 있다. **(4) 복귀는 20%(경고)에서 발동한다.** 10% 는 2S 팩의 절벽 구간이라
거기서 출발하면 도크까지 못 갈 수 있고, 전류 센싱이 없어 에너지 예산을 계산할
수단도 없다. 계산된 틀린 값보다 정직한 고정 임계가 낫다.

**Consequences:** 감지 방식(LiDAR 반사판 / IR 비콘 / 카메라 태그)은 **정하지
않았다.** 카메라가 실기 드라이버를 갖느냐에 달렸고 그것은 별도 스펙이라,
`DockDetector` 플러그인 경계 뒤로 유보했다. 경계 위의 코드는 스캔·이미지·IR 을
일절 보지 않고 상대 포즈만 소비하므로, 결정이 나면 플러그인만 교체된다. 구현은
로봇당 도크 1개를 목표로 하되 스키마와 API 는 풀 형태(기종/개체 분리)로 고정해
두었다 — 예약·점유 중재는 Fleet 사안이라 실물 2대 없이 설계하지 않는다.
`DOCK_FAILED` 는 종착이며 스스로 재시도하지 않는다: 무인으로 반복 실패하는
로봇은 물리적 문제를 갖고 있고 자동 루프는 그것을 숨기면서 지키려던 팩을 마저
비운다. 코스트맵 충돌 면제는 접근 구간 전용이며 모든 퇴출 경로가 같은 해제를
지난다. 그리고 `DockState` 는 계약의 `DOCK/UNDOCK/...` 을 다듬어 "도크에 있지
않다"(`UNDOCKED`)와 행위/결과 구분을 추가했다 — enum 값 추가이므로 PRT-006
MINOR 상향이다. 설계 근거는
`docs/plans/2026-09-02-docking-station-design.md` 에 있다.

## D-30 현장 설정은 로컬 오버레이에만 쓰고, 토큰은 해시로만 남긴다

**Status:** Accepted (2026-09-06)

**Context:** 커미셔닝 설정(로봇 id·이름, API 토큰, SAF-004 속도 한계, SAF-005
배터리 임계, fleet 손실 정책)을 바꾸려면 지금까지 SSH 로 들어가 YAML 을 고쳐야
했다. 대시보드에서 바꾸게 하려면 두 가지를 먼저 정해야 한다. **어디에 쓰는가** —
설정 병합 순서는 `rosy_default.yaml` → `~/.rosy/rosy.yaml` → `ROSY_CONFIG` 이고,
패키지 기본값에 쓰면 다음 이미지에서 사라지는 데다 운영자 값이 릴리스 산출물에
섞인다. **토큰을 어떻게 다루는가** — SEC-101 은 정적 토큰 3롤을 규정하지만
저장 형태를 말하지 않았고, 실제 구현은 평문이었다. 평문 토큰을 쓰는 API 를
열면 노출면이 SSH 가능자에서 관리자 세션 전체로 넓어진다.

**Decision:** **(1) 쓰기는 오버레이에만 한다.** `patch_local_config` 가
`ROSY_CONFIG` 가 가리키는 파일(없으면 `~/.rosy/rosy.yaml`)에 deep-merge 하고,
패키지 기본 경로가 대상이면 거부한다. 임시 파일에 쓴 뒤 `os.replace` 로 바꿔,
쓰다 죽어도 반쯤 파싱되는 설정이 남지 않는다. **(2) 토큰은 sha256 다이제스트로만
보관한다.** 인증은 제시된 토큰을 해시해 `hmac.compare_digest` 로 비교한다.
**(3) 토큰을 가리키는 이름은 원문에서 유도하지 않은 불투명 `id` 다.** 처음에는
`sha256(token)[:12]` 를 fingerprint 로 썼는데, 그 값 자체가 약한 토큰을 확인해
보는 오라클이라 해시 저장의 이득을 지운다. 마스킹된 `hint`(앞 3자 + 뒤 2자)도
같은 이유로 없앴다. 대신 운영자가 붙이는 `label` 로 구분한다. **(4) 기본은 서버
생성이다.** `token` 없이 POST 하면 `secrets.token_urlsafe(32)` 를 만들어 응답에
한 번만 싣는다. 직접 정하는 경우는 16자 이상을 요구한다. **(5) 평문 항목은
계속 인증되지만 다음 쓰기에서 해시로 옮겨간다** — 패키지 기본값의 dev 토큰이
그렇고, 목록에 `legacy: true` 로 표시된다.

**Consequences:** 토큰 원문은 생성 응답 한 곳에서만 나간다. 다시 볼 수 없으므로
분실은 재발급이며, 이는 의도된 성질이다. Host Agent 로 넘기던 `user_id` 는
`auth.token[:8]` — 토큰 앞 8자 — 이었고 호스트 감사 로그에 그대로 남았다.
`token_id` 로 바꿨다. `AuthContext` 는 원문을 아예 들고 있지 않아, 앞으로 이
경로로 비밀이 새려면 코드를 되돌려야 한다. 해시는 salt 없는 sha256 이다:
토큰이 고엔트로피 난수라는 전제 위에 서 있고, 그래서 (4)의 생성 기본값과 16자
하한이 장식이 아니라 이 결정의 일부다. 오버레이가 유일한 쓰기 대상이므로
`ROSY_CONFIG` 를 읽기 전용 경로로 지정한 배포는 설정 쓰기가 500 으로 실패하며,
이는 조용히 메모리에만 반영하는 것보다 낫다 — 쓰기가 실패하면 프로세스 상태도
바꾸지 않는다. 남는 구멍 하나: 아직 평문인 항목은 `id` 를 저장할 곳이 없어
`sha256(token)[:12]` 을 쓴다. 재시작 간에 안정된 이름이 필요하기 때문이고, 그
항목은 이미 같은 파일에 평문으로 있으므로 새로 여는 노출은 없다. 첫 쓰기에서
난수 `id` 로 옮겨간다.


## D-31 군집 참조 스트림은 로봇의 소켓이다 — Fleet 은 선택적 중계자

**Status:** Accepted (2026-09-06) — D-20/D-21 구현 결정

**Context:** D-20 은 추종 계산을 로봇에 두고 Fleet 에는 지정·릴레이만 남겼고,
API Ref §7.8 은 그 릴레이 경로를 **Leader → Fleet → Follower** 로 적었다. 그런데
이 리포에는 Fleet 서버가 없고 아웃바운드는 hold 다. 그대로 구현하면 아무도
구동할 수 없는 기능이 생긴다 — 지금까지 swarm 이 "스키마와 우선순위 슬롯은
있는데 라우트는 없는" 상태로 남아 있던 이유이기도 하다. 동시에 CAP-001 은
`swarm.follow: true` 를 광고하고 있었으므로, 계약을 읽은 Fleet 은 404 를 받는다.

**Decision:** **참조 스트림의 양 끝을 로봇에 둔다.** 리더는
`WS /ws/swarm/pose` 로 자기 pose 를 ≥10 Hz 발행하고(SWM-003), 팔로워는
`WS /ws/swarm/reference` 로 참조 pose 를 받는다. 둘은 §7.8 envelope 을 그대로
쓰므로 **리더의 출력을 팔로워의 입력에 바로 물릴 수 있다.** Fleet 이 생기면
가운데 서서 같은 envelope 을 중계하고, 어느 쪽 끝도 바뀌지 않는다 — 이것이
SWM-007 이 요구한 "소비자는 소스를 묻지 않는다"의 실체다. `SwarmManager` 는
전송 계층을 하나도 import 하지 않으며, 테스트가 import 그래프로 그것을 확인한다.

`peer` 소스(D-21)는 **거부한다.** 파라미터는 계약에 있지만 P2P 릴레이가 없고,
받아들인 뒤 조용히 fleet 처럼 처리하면 계약이 거짓말이 된다.

**Consequences:** Fleet 없이 2대로 군집을 검증할 수 있다. 로봇 API 에 인바운드
스트림이 하나 늘었으므로 그 값은 operator 이상이어야 한다 — pose 를 밀어넣는
것은 로봇을 움직이는 일이다. 프레임 하나가 망가져도 소켓을 닫지 않는다: 닫으면
표본 하나가 대형 전체를 HOLD 로 떨어뜨리고, 스트림이 정말 죽었다면 그것을
알아채는 것은 디코딩 실패가 아니라 SWM-004 의 타임아웃이어야 한다.

**`max_speed` 는 어디서 걸리는가.** 처음에는 검증만 하고 흘려보냈다 — Nav2
파라미터 클라이언트가 CORE 에 없고, 추종은 별도 cmd_vel 소스가 아니라 moving
goal 이라(SWM-001) 속도를 정할 지점이 없어 보였기 때문이다. 그러나 지점은
이미 있었다: D-2 가 모든 `cmd_vel` 을 Command Manager 한 곳으로 모아 두었고,
그 출력은 전부 `SafetyManager.clip` 을 지난다. 추종 구간 동안 그 상한을
`max_speed` 로 낮춘다. Nav2 가 무엇을 내보내든 바퀴에 닿는 값이 줄어들므로,
플래너 파라미터를 원격으로 바꾸는 것보다 신뢰할 수 있고 검증도 호스트에서
된다. 상한은 **낮추기만** 한다 — 활동이 프로필 상한(SAF-004)을 넘겨 달릴 수는
없다. 세션이 끝나면 어느 경로로 끝나든 함께 풀린다.

이 상한은 추종 구간 전체의 것이라 같은 시간의 수동 조작에도 적용된다. 대형이
도는 동안 사람이 밀어도 그 위로 못 가는 편이, 조작 주체마다 다른 상한을 두는
것보다 안전하다.

**갱신 주기:** 목표는 ≤2 Hz 로 제한한다(SWM-002). 10 Hz 스트림을 그대로 흘리면
Nav2 플래너가 계속 재시작하고, 군집 속도(≤0.2 m/s)에서 2 Hz 면 충분하다. 창
안에 들어온 표본은 버리지 않고 들고 있다가 다음 창에서 낸다 — 버리면 리더의
최신 위치를 잃는다.

**목표에 세대를 붙인다.** moving goal 은 "Nav2 목표는 한 번에 하나이고 임자는
`goal()` 을 부른 쪽"이라는 전제를 깬다. 선점된 목표는 abort 로 끝나고 그 결과가
뒤늦게 도착하는데, 그것을 현재 목표의 실패로 읽으면 `nav_state` 가 FAILED 로
떨어져 이어지는 HOLD 의 취소가 통째로 무시된다 — 스트림이 끊겼는데 로봇이 계속
달린다. `bridge/goal_tracker.py` 가 세대를 매기고 **살아 있는 핸들 전부**를
들고 있으며, 지난 세대의 수락은 등록하지 않고 즉시 취소한다(send 와 accept
사이의 취소 창). 추종 세션 중에는 단발 `POST /navigation/goal` 을 409 로
거절한다: 0.5 초 뒤 스트림에 조용히 덮이느니 거절이 낫다. NAV-006 stuck 기준점도
목표 교체마다 초기화하지 않는다 — 그러면 30 초 무진척 조건이 영원히 성립하지
않아, 문틀에 낀 팔로워가 아무 신호 없이 계속 밀어붙인다.

**추종은 언제 끝나는가.** 세션을 닫는 길은 하나가 아니다 — 운영자의
`/swarm/cancel`, `/navigation/cancel`, MANUAL 전환, e-stop, NAV-006 stuck.
그래서 `NavigationManager` 가 세션이 닫힐 때 임자에게 알리고, 추종은 거기서
끝난다. 알리지 않으면 추종은 목표를 하나도 내지 못하면서 스냅샷에는
`active: true` 로 남는다 — 참조 프레임이 계속 도착하니 스트림도 신선해 보이고
HOLD 도 걸리지 않아, 대형이 멀쩡해 보이는 채로 아무 일도 하지 않는다. e-stop 은 중단이 아니라 **해제**다 — 해제 뒤 참조 프레임
하나로 다시 달리기 시작하면 안 되고, 운영자가 다시 명령해야 한다. stuck 도
같다: SRS 가 "자동 재시도는 하지 않는다"고 못박았는데, 세션을 살려 두면 0.5 초
뒤 스트림이 목표를 다시 밀어넣고 그것이 곧 자동 재시도다(끼인 로봇이 분당 수백
개의 `nav.stuck` 을 감사 로그에 쌓으며 계속 민다). e-stop 은 `SafetyManager` 의
리스너로 붙는다 — API·배터리 어느 경로로 들어오든 같은 자리를 지나기 때문이다.

**맵핑과는 서로 막는다.** `moving_goal` 은 맵핑 세션 중 목표 투입을 거절하고,
`start_mapping` 은 추종 세션이 열려 있으면 거절한다. 한쪽만 막으면 나머지 방향은
받아들여진 뒤 조용히 아무것도 못 하는 상태가 된다 — 목표 투입이 거절되는데 그
예외는 참조 소켓이 삼킨다. `start_mapping` 이 `_nav_state` 만 보면 부족하다:
HOLD 중에는 나가 있는 목표가 없어 열려 보이지만, 대형은 여전히 목표의 임자이고
스트림이 돌아오면 이어간다.

**도킹에는 양보한다.** DOCKING(4) > NAVIGATION(5) 이고 둘이 같은 Nav2 액션을
쓰므로, 양보하지 않으면 추종이 SAF-005 저배터리 복귀 주행을 계속 선점한다.
양보는 **문 앞에서** 한다 — 받아들인 뒤 다음 틱에 조용히 푸는 것은 거절보다
나쁘다(운영자는 200 을 보고, 로봇은 충전기 위에서 NAVIGATION 에 남는다).
다투는 상태는 `DOCKING`·`UNDOCKING` 뿐이다: `DOCKED`·`CHARGING` 은 주차
상태이고 `DOCK_FAILED` 는 설계상 종착이라, 그것까지 막으면 도킹 실패 한 번이
군집을 영구히 비활성화한다.

**세션 토큰.** 목표에도 취소에도 `NavigationManager` 가 발급한 세션 토큰이 붙는다.
취소가 세션을 닫으면 뒤늦게 도착한 목표는 저쪽 락 안에서 버려지므로, 추종자가
자기 락을 쥔 채 항법을 부를 필요가 없다(락 두 개를 겹쳐 잡지 않는다). HOLD 는
목표만 거두고 세션은 닫지 않는다 — 그래야 돌아온 스트림이 새 follow 명령 없이
이어지고, HOLD 중에도 목표의 임자는 여전히 추종 세션이다. 취소도 같은 규칙을
따른다: 임자가 자기 락을 놓은 사이에 운영자가 대형을 다시 걸었다면 그 새 세션은
남의 것이므로 닫지 않는다. 세션을 여는 것과 무장은 한 구간에서 한다 — 락 밖에서
열면 그 사이에 도착한 취소가 임자 없는 세션을 남기고, 단발 목표가 영영 거절당한다.

**맵 일치 확인.** §7.8 envelope 에 `map_id` 를 더했다(v1.7 additive). 좌표만
보내면 받는 쪽은 그것이 자기 맵의 좌표인지 알 수 없고, 다른 맵의 리더를 따라가면
그럴듯해 보이는 엉뚱한 지점으로 간다 — 웨이포인트를 MAP-002 로 막는 것과 같은
사고다. **양쪽 다 값이 있고 서로 다를 때만** 거부한다: 필드를 모르는 릴레이도,
아직 맵이 없는 로봇도 그대로 동작해야 하고, "확인할 수 없음"을 "확인 실패"로
읽어 멈추면 없던 고장이 생긴다.

거부는 대형을 끝내지 않는다. 스트림 단절과 원인은 다르지만 처신은 같아서 —
목표를 거두고 세션은 살려 둔다 — 리더가 우리 맵으로 돌아오면 새 명령 없이
이어진다. 다만 SWM-004 타임아웃을 걸지는 않는다: 표본은 도착하고 있으므로
단절이라고 말하면 원인을 잘못 말하는 것이다. `swarm.hold` 의 `reason` 이 둘을
구분하고, `swarm/state` 의 `map_mismatch` 가 거부 중인 맵 id 를 보여준다.


---

## D-32 광고한 능력을 못 지키면 200 이 아니라 코드로 실패한다

**Status:** Accepted (2026-09-06) — CAP-003 준수 수정, D-31 과 같은 결함형

**Context:** `POST /api/v1/slam/reset` 은 `{"reset": true}` 와 200 을 돌려주면서
아무 일도 하지 않았다. 두 경로가 독립적으로 거짓말했다. 맵핑 세션이 없으면
매니저가 조용히 되돌아갔고, 실행기 호출은
`hasattr(self.executor, "reset_mapping")` 뒤에 있었는데 `RosBridge` 에는 그
메서드가 아예 없어서 탐지가 실패하고 호출이 건너뛰어졌다. 그런데 CAP-001 은
`slam: true` 를 광고하므로 능력 게이트는 통과한다 — 계약을 읽은 Fleet 은
리셋을 요청하고, 됐다는 답을 받고, 아무 일도 일어나지 않는다.

D-31 이 며칠 전에 고친 것과 같은 형태다. 그때는 `swarm.follow: true` 를
광고하면서 라우트가 404 였고, 지금은 `slam: true` 를 광고하면서 라우트가
거짓 200 이다. 404 는 최소한 정직하다.

**Decision:** **능력을 광고했는데 런타임이 못 지키면 명확한 에러 코드로
실패한다.** CORE SRS CAP-003 이 "일반 실패가 아닌 명확한 에러 코드"를 요구하고,
DNC-003 이 미지원 도킹에 이미 501 `CAPABILITY_NOT_SUPPORTED` 를 쓰고 있으므로
새 규약이 아니라 기존 규약의 적용이다.

세 가지가 따라온다. 첫째, **계약에 없는 멤버를 `hasattr` 로 더듬지 않는다.**
`NavExecutor` 가 `reset_mapping` 을 선언하고, `RosBridge` 가 구현하되 실물
slam_toolbox `Reset` 이 붙기 전까지는 `CAPABILITY_NOT_SUPPORTED` 로 실패한다.
Protocol 은 구조적이고 `RosBridge` 는 베이스 클래스를 선언하지 않으므로 이
선언은 런타임을 구속하지 않는다 — 문서이지 강제가 아니며, 그래서 테스트
페이크 일곱 개는 하나도 고칠 필요가 없었다. 둘째, **능력 답변이 세션 답변보다
먼저 온다.** 실행기가 없으면 501, 있는데 세션이 없으면 400. 순서를 뒤집으면
"이 런타임은 그걸 못 한다"가 400 으로 나가 계약이 틀린다. 셋째, **엔드포인트는
건드리지 않는다.** `api/errors.py` 가 이미 `NavigationError` 를 `_HTTP_BY_CODE`
로 태우므로 501·400 이 기존 핸들러에서 떨어진다. `slam/save` 의
`except RuntimeError` 모양은 일부러 복사하지 않았다 — 다른 예외 계열을 잡고,
서비스 실패를 `CAPABILITY_NOT_SUPPORTED` 로 접는 혼동을 두 번째 엔드포인트로
퍼뜨린다.

**Consequences:** **API-002 의 의미 변경이 아니라 CAP-003 위반의 시정이다.**
200 쪽이 위반이었다. 그래도 응답이 바뀌므로 API Ref 는 v1.7 로 올리고 해당
행에 501 조건을 적는다 — D-31 이 v1.6 에서 한 것과 같은 절차다.

**비파괴로 만드는 것은 D-31 유비가 아니라 blast radius 다.** D-31 은 404 를 동작하는 라우트로 바꿨으니 가산적이고 어떤 소비자도 깨질 수 없었다. 여기는 200 을 에러로 바꾸므로 `response.ok` 로 분기하는 소비자는 깨질 수 있다 — 둘 중 깨질 수 있는 쪽은 이쪽뿐이다. D-31 은 *어떻게 버전을 올리는가*의 선례이지 *왜 파괴적이지 않은가*의 근거가 아니다. 근거는 실측이다: 배포 오버레이 셋이 모두 `slam: false` 이므로 현장에서는 이미 능력 게이트가 501 로 막고 있었고, 거짓 200 은 패키지 기본 설정에서만 도달 가능했다.

소비자 영향은 0 이다. 대시보드는 `slam/start`·`stop`·`save` 만 호출하고
(`web/settings.js`), `fleet_agent/` 에는 slam 참조가 없다. Flask 패리티 E-6 은
"API 완료"에서 **hollow** 로 강등한다 — 체크리스트가 실제보다 앞서 있었다.

실물 리셋(slam_toolbox `Reset` 서비스, 이식원
`rosy_navigation/scripts/nav2_web_server.py`)은 **여기서 구현하지 않는다.**
배포 오버레이 셋이 모두 `slam: false` 이고 CI 에도 slam_toolbox 가 없어서 오늘
어디서도 검증할 수 없다. `mapping/` 패키지 재진입 트리거에 함께 걸어 둔다
(`docs/plans/2026-09-06-module-split-criteria.md`). 그때 리셋이 어떤 이벤트를
발행할지도 함께 정해야 한다 — 지금은 두 경로가 모두 먼저 raise 하므로 기존
`slam.started {"reset": true}` 발행은 도달 불가 코드로 남아 있다.

---

## D-33 로봇 신원은 하나의 로봇 번호에서 나온다

**Status:** Accepted (2026-09-06) — D-6 대체

**Context:** D-6 은 "로봇별 고유 `ROS_DOMAIN_ID`" 를 결정했지만, 구현은 그 결정을
지키지 않았다. `deploy/robot/.env.example` 이 `ROS_DOMAIN_ID=42` 와
`ROSY_NAMESPACE=rosy_01` 을 **값으로** 들고 있었고, `install-pi.sh` 는 그 템플릿을
그대로 복사한다. 그래서 릴리스에서 설치된 모든 기기가 같은 도메인 **그리고** 같은
네임스페이스로 출고됐다 — 도메인만 겹친 것이 아니라 토픽 이름까지 전부 겹쳤다.
개발용 `rosy_env.sh` 는 `40 + N` 이라는 또 다른 규칙을 쓰고 있어서, 스크립트로 띄운
2호기가 기본 배포된 모든 기기와 정확히 충돌했다.

이 결함은 설치 스크립트만 고쳐서는 사라지지 않는다. 값을 채워 넣는 헬퍼
(`set_env_default`) 는 키가 **없을 때만** 쓰므로, 템플릿이 값을 들고 있는 한 영영
발화하지 못한다. 계획 검토 중 이 함정을 두 번 밟았다: 두 번 다 호출은 추가됐고
테스트는 초록이었으며 기기는 여전히 충돌했다.

**Decision:** 로봇 신원은 **로봇 번호 하나**에서 유도한다 — `ROS_DOMAIN_ID = 40 + N`,
`ROSY_NAMESPACE = rosy_%02d`. 그리고 세 계층 모두에서 **기본값을 없앤다**:

- `.env.example` 은 두 키를 **배정하지 않는다** (규칙만 주석으로 남긴다).
- `install-pi.sh` 는 `ROSY_ROBOT_NUMBER` 를 **요구**하고, `0 <= 40+N <= 101` 을
  검증하며, 이미 다른 번호로 자리잡은 기기를 만나면 **두 값을 모두 이름 대어 실패**한다.
- `compose.yaml` 은 여섯 군데 전부 `${VAR:?...}` 를 쓴다 — `:8` 만 고치면 반쪽이다.
  `:51` 이 실제로 노드가 기동에 쓰는 `__ns:=` 인자다.

검증은 "호출이 있는가" 가 아니라 **"신규 설치가 실제로 다른 값을 낳는가"** 로 한다
(`test/test_dds_identity_contracts.py`).

**Consequences:** 신원 미설정은 조용한 충돌이 아니라 기동 실패가 된다 — 의도한 바다.
이미 배포된 기기는 자동으로 재번호되지 않으며, 다음 프로비저닝 때 불일치 검사가
잡는다. 재번호 절차는 `docs/deployment/raspberry-pi-runtime.md` 에 있다.
D-6 의 localhost-only 프로파일 결정은 **그대로 유효하다** — 이 ADR 은 신원 유도만
대체한다.

---

## D-34 발행 주기는 그것을 읽는 쪽에 맞춘다

**Status:** Accepted (2026-09-06)

**Context:** global costmap 은 `publish_frequency: 1.0` 으로 전체 격자를 초당 한 번씩
내보내고 있었다. 그런데 그 격자를 읽는 유일한 소비자는 대시보드이고,
`src/rosy_core/rosy_core/web/app.js:647` 의 `refreshSlowData` 는 **5000 ms 간격**이다.
게다가 스트림이 아니라 캐시에 대한 REST pull 이라, 브라우저가 하나도 열려 있지
않아도 초당 한 장씩 계속 나갔다. 즉 소비자보다 다섯 배 빨랐다.

`publish_voxel_map: True` 는 더 단순한 경우다 — 저장소 전체에서 구독자가 하나도
없다. RViz 디버그 출력인데 `update_frequency: 5.0` 에 물려 있어서, 아무도 보지 않는
격자를 초당 다섯 번 내보내고 있었다.

이 값들에는 어떤 테스트도 걸려 있지 않았다. `publish_frequency` 를 grep 하면 params
파일 자신 말고는 나오지 않는다.

**Decision:** **발행 주기는 측정이 아니라 소비자에게서 읽는다.** 두 costmap 의
`publish_frequency` 를 `0.2` 로, `publish_voxel_map` 을 `False` 로 둔다. 숫자의 출처는
`app.js:647` 의 폴링 간격이며, 그 간격이 바뀌면 이 값도 함께 바뀐다.
`test/test_nav2_bandwidth_contracts.py` 가 둘의 관계를 고정한다.

플래너 품질은 `update_frequency` 가 정하므로 이 변경은 항법 거동과 무관하다.

**Consequences:** 최악의 경우 맵 패널이 약 10초까지 낡을 수 있다. **이것이 너무
낡다고 판단되면 주기를 다시 올리는 것이 아니라 수요 기반 충전으로 간다** — 캐시를
채우는 주체를 타이머에서 요청으로 바꾸는 쪽이다. 그것이 **잠정적인 장기 방향**이며,
`maps.py` / `api/v1/map.py` 의 모듈 소유권 판정
(`docs/plans/2026-09-06-module-split-criteria.md`)에 걸려 미뤄져 있다.

이 ADR 은 주기적 push 를 결정된 구조로 승인하지 않는다. 지금의 주기는 현재 소비자에
맞춘 값일 뿐이고, 소비자가 사라지면 그 값도 0 이 되는 것이 옳다.
RViz 사용자는 `publish_voxel_map` 을 로컬에서만 되살린다 — 배포본에는 켜서 보내지 않는다.


## D-36: Signed runtime delivery and writable generation data (2026-09-08)

**Status:** Accepted for local implementation; ARM64/Pi acceptance pending. D-35 is reserved by the concurrent Fleet work.

**Decision:** Release delivery uses pre-enrolled Ed25519 keys and bounded archive staging. GitHub checking may stage automatically, but activation requires explicit maintenance with the runtime stopped. Boot, activation and rollback start core only. Kernel/rootfs and host-tool updates remain outside this adapter.

Immutable config/data generations remain rollback evidence. Each activation data generation also owns a writable `data-working/<generation>` copied from its snapshot; CORE mounts only that working tree. First migration includes HOME's `.rosy` data. Rollback reuses the prior working tree and does not merge candidate writes. `activation.json` remains the sole active-generation authority. The host-owned previous activation is `/etc/rosy/previous-activation.json`, persisted by the activation journal before success is finalized and restored on rollback.

**Consequences:** Working generations require explicit storage retention; no automatic pruning is wired into the delivery CLI. The signed image digests used by this Docker save/load adapter are Docker content image IDs, not registry index digests. The host-agent socket/dashboard installer remains separate. See `docs/deployment/github-updates.md`.

---

## D-37 Rosy Control을 Rosy OS 내부 기능으로 흡수

**Status:** Accepted (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** Control의 코드·웹·배포를 별도로 유지하면 장치 운영과 정비의 소유권이 나뉜다. 사용자가 Rosy OS 단일 제품 방향을 확정했다.

**Decision:** 제품·저장소·설치 기준은 Rosy OS로 통일한다. src/rosy_control은 호환성을 유지하는 내부 패키지로 편입한다. 외부 API와 웹은 rosy_core, 하드웨어는 IO/bringup, 배포·복구는 기존 deploy가 소유한다. D-1·D-18·D-22·D-23을 유지한다.

**Alternatives:** 별도 Control 제품 유지와 즉시 전면 패키지 분할을 검토했다. 전자는 운영 중복을 남기고 후자는 기능 이전과 import 변경을 결합하므로 채택하지 않는다.

**Consequences:** 원본은 provenance로 보존한다. 역방향 의존성·선택 설치·장애 격리가 필요하면 내부 패키지 경계를 재검토한다.

**Validation / Transition:** T0·T1 소스 편입과 package build는 완료. T2~T8 런타임 통합은 미완료. 원본 checkout 없이 설치·기동·정비·rollback까지 재현해야 흡수를 종료한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-38 흡수된 모든 이동 명령의 최종 중재와 정지는 CORE가 소유

**Status:** Accepted (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** legacy SafetyNode와 CORE RosBridge가 각각 최종 cmd_vel을 발행할 수 있어 무조건 함께 기동할 수 없다.

**Decision:** D-2를 보강한다. CommandManager가 후보를 선택하고 SafetyManager가 최종 제한을 적용하며 RosBridge만 모터 cmd_vel을 발행한다. Control 보정·주행도 이 경로를 통과한다. IO deadman은 D-22대로 유지한다. e-stop·재기동·소유권 교체 때 과거 이동 명령을 폐기하고 새 요청을 요구한다.

**Alternatives:** 기존 SafetyNode를 최종 발행자로 유지하거나 두 발행자를 병렬 활성화하는 안은 CORE 명령 소유권과 충돌한다.

**Consequences:** 센서 기반 제한과 후보별 판단의 정확한 전달 계약은 D-42 Proposed다. Accepted는 물리 안전 인증이나 구현 완료를 의미하지 않는다.

**Validation / Transition:** T3에서 단일 publisher, stale·nonfinite·단절·모순 입력, e-stop 해제 후 자동 재가동 금지를 시험한다. 기록 재생과 무발행 shadow 비교 후 정지 상태에서 전환한다. 정지 지연·거리 한계는 실물 구동 시험 전에 장치별로 고정한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-39 OS 운용·진단·유지보수와 완료 증거를 통합

**Status:** Accepted (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** 소스 편입만으로 단일 제품 운영이나 기존 기능 동등성을 증명할 수 없다.

**Decision:** CORE 대시보드와 기존 인증 역할로 운전·보정·정비를 제공한다. 새 역할을 임의로 만들지 않는다. capability는 실제 준비 상태를 반영하며 stale 데이터는 현재값과 구분한다. D-36의 서명된 runtime 활성화·복구와 generation별 데이터 규칙을 계승한다. SOURCE/BUILD/LOCAL/SIM/ARTIFACT/DEVICE/FIELD 증거를 따로 기록한다.

**Alternatives:** 별도 Control 서버의 상시 유지, 파일 개수나 단위 테스트만으로 인수하는 안은 운용 동등성을 보장하지 않는다.

**Consequences:** 기능별 설정·시험·진단·복구 대장과 단독 운영 runbook을 T8 산출물로 만든다. 장치별 전환 책임자·복귀 조건을 기록한다.

**Validation / Transition:** T5 실제 브라우저 권한·단절·보정 흐름, T6 artifact·복구, G3/T7 Pinky Pro 실측, T8 원본 runtime 없는 운용을 각각 통과한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-40 Nav2 기본 유지와 단일 주행 backend 소유권

**Status:** Accepted (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** CORE는 Nav2 action을 사용하고 Control은 GoalBrain·route·wander를 사용한다. 목표와 취소 결과의 중복 소유를 막아야 한다.

**Decision:** 기존 운영 기본값 Nav2를 유지한다. CORE NavigationManager가 세션·목표·취소·종료 결과를 소유하며 로봇별 활성 backend는 하나다. 취소된 세션의 늦은 결과는 현재 세션에 반영하지 않는다. 안전한 경로가 있으면 우회하고 없으면 정지한다.

**Alternatives:** 즉시 Control로 전환하거나 두 실행기를 동시에 사용하는 안은 현재 API와 취소 수명주기를 보존하지 못한다.

**Consequences:** ControlBackend의 운영 채택은 D-44에서 별도로 검증한다. 이 결정은 Nav2가 모든 시나리오에서 우수하다는 실측 결론이 아니다.

**Validation / Transition:** T4에서 목표·취소·늦은 결과·재시작·우회·막힘을 공통 시나리오로 검증한다. 경로 생성과 실측 도착을 구분한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-41 카메라와 OpenCV worker 실행 위치

**Status:** Proposed (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** Picamera2/libcamera의 ARM64 장치 접근과 frame 전달 지연은 실행 위치에 따라 다르다. 현재 HSV 기반 근거는 박스 의미 인식이나 grasp pose가 아니다.

**Decision:** 장치 내부 처리와 CORE/IO 분리는 유지한다. 최소 권한 hardware/vision 컨테이너와 호스트 장치 서비스를 비교한다. 어느 실행 위치도 아직 최종 채택하지 않는다.

**Alternatives:** CORE에 광범위한 장치 권한을 주는 안은 D-22와 충돌한다. 나머지 두 후보는 실제 캡처와 장애 복구 결과로 비교한다.

**Consequences:** G2에서 실행 위치를 먼저 결정해야 관련 그래프와 배포 계약을 고정할 수 있다. 가속기나 OMX 영상 기능은 이번 선택만으로 지원된 것으로 광고하지 않는다.

**Validation / Transition:** T2 초기 G2에서 실제 캡처, 최소 권한, 재시작, frame 시각·손실·p95 지연, CPU·메모리를 측정한다. 장치가 없으면 HOLD. 결과·선택 사유·복구 경로를 남긴 뒤 Accepted로 승격한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-42 후보 명령과 안전 판단의 내부 전달 계약

**Status:** Proposed (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** 명령에 대해 계산된 안전 결과를 다른 명령에 적용하거나, 오래된 센서 판단을 새 판단으로 재사용하면 안 된다.

**Decision:** 동일 프로세스의 동기 평가와 비동기 ROS 요청/결과 방식을 비교한다. command/source 상관관계, 센서 freshness, 재시작 epoch, revision, 만료와 실패 시 zero 의미를 요구한다. 상세 설계의 decision_id·command_id 등은 내부 스키마 후보이며 공개 API나 구현된 message가 아니다.

**Alternatives:** 동기 평가는 왕복 지연을 줄이지만 제어 주기 예산과 의존성이 문제다. 비동기는 격리되지만 지연·순서 역전·재생 처리 비용이 있다.

**Consequences:** 서로 다른 호스트·ROS sim time·monotonic 시각을 직접 비교하지 않는다. 부팅 식별, sequence, 수신 시각과 관측 나이의 의미를 확정해야 한다. 명령 독립적 센서 제한과 후보별 충돌 판단을 구분한다.

**Validation / Transition:** T3에서 지연·순서 역전·중복·시계 reset·프로세스 재시작·revision 불일치·sensor expiry를 시험한다. 50 Hz 출력과 처리 예산을 실측하고 적용 결과를 보정 acknowledgement까지 연결한 후 승격한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-43 보정 schema와 릴리스 generation 저장 매핑

**Status:** Proposed (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** 보정은 장치별 데이터이며 OS 업데이트와 rollback에서 보존되어야 한다. 임의의 전역 저장 경로는 D-36의 generation 복구 규칙을 우회할 수 있다.

**Decision:** 장치 identity, schema·geometry·calibration revision, 단위·범위, 변경 감사, 원자적 쓰기와 적용 acknowledgement를 요구한다. /var/lib/rosy/calibration/<device-id>/는 컨테이너 내부 후보 경로다. 호스트에서는 D-36의 활성 data-working/<generation>에 대응해야 하며 정확한 파일명·schema·migration은 미확정이다.

**Alternatives:** 읽기 전용 package share에 쓰거나 모든 generation이 하나의 mutable 보정 파일을 공유하는 안은 채택하지 않는다. 기존 보정 형식 보존과 versioned schema 변환을 비교한다.

**Consequences:** 일반 설정 로더의 config/rosy_default.yaml → ~/.rosy/rosy.yaml → ROSY_CONFIG 순서를 바꾸지 않는다. 장치 profile과 측정 보정의 필드별 결합·충돌 규칙은 별도 정의한다.

**Validation / Transition:** T2에서 손상·장치 불일치·범위 초과·쓰기 실패·재부팅을 시험하고 T6에서 activation/rollback 데이터 격리와 schema 호환을 확인한다. 구버전 복구가 검증된 migration 정책을 기록한 뒤 승격한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-44 ControlBackend 채택과 OMX 작업 액션 경계

**Status:** Proposed (2026-09-12). 설계 결정 상태이며 구현·장치 인수 상태와 구분한다.

**Context:** Control의 자율 로직 재사용과 향후 Pinky Pro+OMX 박스 이동·적층이 필요하지만 backend 채택, arm 모델과 적재 조건은 미결정이다.

**Decision:** Control 로직은 Nav2 보조·격리 검증·선택 backend 후보로 비교한다. OMX는 로봇 측 원자 액션과 안전 interlock 확장으로 설계하며 Fleet의 상위 임무 소유권(D-12)을 변경하지 않는다. 로컬 연속 작업 오케스트레이션을 제품 기능으로 채택하려면 D-12 확장 여부를 별도 ADR로 결정한다.

**Alternatives:** ControlBackend 전면 채택, Nav2 보조만 사용, 시험 전용 보존을 동일 시나리오로 비교한다. 베이스·팔 동시 동작과 로컬 임무 엔진은 이번 문서로 승인하지 않는다.

**Consequences:** OMX-F/OMX-AI 등 모델 결정과 하중·중심·도달거리·전원·hand-eye 검증 전에는 arm capability를 활성화하지 않는다. 박스 적층 알고리즘은 T2~T8 흡수 완료 조건에 넣지 않는다.

**Validation / Transition:** T4에서 지도·localization·우회·취소·재기동·namespace·자원 비용으로 backend를 판정한다. OMX 액션은 베이스 정지·고정 확인, 보정 revision, arm 실행·결과 확인을 실물 검증한 후 별도 구현 결정으로 승격한다.

**References:** [상세 설계](../plans/2026-09-12-rosy-os-control-integrated-design.md), [실행 계획](../plans/2026-09-12-rosy-control-absorption-plan.md), [현재 증거](../plans/2026-09-12-control-absorption-results.md).

---

## D-45 저장소 문서와 자산의 단일 기준 경로

**Status:** Accepted (2026-09-13). 경로 정리 결정이며 기존 링크의 호환성 및
실행 인수 상태와 구분한다.

**Context:** Rosy OS 루트에 `doc/`와 `docs/`가 함께 있으면 같은 이름의 문서
책임이 나뉘고, 흡수된 Control과 장치 배포 문서의 기준 경로를 잘못 선택하기
쉽다. `doc/`의 이미지와 ARM64 메모는 코드가 참조하지 않는 독립 자료였다.

**Decision:** 저장소 문서는 `docs/` 아래를 단일 기준으로 둔다. 이미지와 제품
자료는 `docs/assets/`, 현재 ARM64/Pi 절차는 `docs/deployment/`에 둔다. 과거
upstream 절차는 `docs/deployment/legacy-arm64-guide.md`에 provenance로만
보존하며 운영 절차로 취급하지 않는다. 루트 `doc/`는 제거한다.

**Alternatives:** `doc/`와 `docs/`를 계속 병행하거나 이미지를 루트에 두는 안은
탐색 비용과 링크 오류를 유지하므로 채택하지 않는다. 모든 자료를
`docs/reference/`에 넣는 안은 계약 문서와 비규범 자산을 섞으므로 채택하지
않는다.

**Consequences:** 새 문서·이미지는 `docs/`의 소유 하에 추가한다. README와
AGENTS 경로 안내가 갱신되며, 외부에 남은 옛 `doc/` 링크는 별도 redirect가
없는 한 갱신 대상이다. 이 결정은 ARM64 이미지 빌드나 장치 인수를 완료한
것을 의미하지 않는다.

**Validation / Transition:** 이동 후 `doc/`가 존재하지 않고 `docs/assets/`
및 `docs/deployment/arm64-build-notes.md`가 존재하는지 확인한다. 저장소
링크·경로 계약 시험과 `git diff --check`를 통과시키고, 실제 ARM64 빌드와
Pi 인수는 기존 T6/T7 게이트로 별도 판정한다.

**References:** [폴더 구조 계획](../plans/2026-09-13-folder-structure-governance.md), [현재 ARM64 메모](../deployment/arm64-build-notes.md).

---

## D-46 Device 설치 후 readback 증거 계약

**Status:** Accepted (2026-09-13). 소프트웨어 증거 형식의 결정이며 실제 Pi와
Pinky Pro 현장 인수 상태와 구분한다.

**Context:** Pi에 Rosy OS를 설치한 뒤 SSH 성공, HTTP 200, 컨테이너 실행만으로는
어떤 OS·identity·release·image가 실제로 부팅되었는지 재현할 수 없다. 환경 파일에는
API credential이 있어 그대로 수집할 수 없다.

**Decision:** `deploy/robot/device-readback.sh`가 표준 JSON readback을 만든다.
readback은 OS/model/architecture, 로봇 번호·DDS domain·namespace, activation record,
서명된 manifest의 git revision·immutable container digest, systemd/core health,
ROS node와 최종 `cmd_vel` publisher 수를 포함한다. `.env` 전체와 credential은 포함하지
않는다. `device_runtime`은 ARM64 identity·manifest·healthy core·graph가 모두 확인될
때만 GO이고, 물리 주행 `field` gate는 별도로 HOLD로 남긴다.

**Alternatives:** 설치 로그만 보관하거나 dashboard 상태만 캡처하는 안은 재부팅 후
동일 release와 graph를 확인할 수 없고 secret 경계를 보장하지 못하므로 채택하지 않는다.

**Consequences:** installer는 readback 도구를 `/opt/rosy/deploy/robot`에 설치하고
`verify-pi.sh`가 명령을 안내한다. readback 성공은 ARM64 artifact publication이나
Pinky Pro/OMX 물리 인수를 대신하지 않는다.

**Validation / Transition:** fake Device filesystem을 이용한 단위 계약과 AMD64
container package smoke를 CI에서 실행한다. 실제 Pi에서는 설치·재부팅·rollback 뒤
JSON을 release evidence와 함께 보관하고, graph/publisher·모터·카메라·OMX는 D-39와
D-44의 별도 commissioning gate로 승격한다.

**References:** [Device 검증 실행 계획](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md), [Pi runtime](../deployment/raspberry-pi-runtime.md), [ARM64 빌드 메모](../deployment/arm64-build-notes.md).

---

## D-47 CORE sensor adapter calibration binding

**Status:** Accepted (2026-09-13). This is a software startup contract; physical sensor and motion acceptance remain separate Device/FIELD gates.

**Context:** The absorbed `rosy_control` sensor worker must use the calibration record belonging to the mounted Rosy OS data generation. A ROS parameter readback alone cannot prove that the correct record was used, and silently combining explicit parameters with a record can create an unsafe split profile.

**Decision:** When `control.sensor_adapter.enabled` and `control.sensor_adapter.calibration.required` are both true, CORE loads the snapshot before constructing the worker. The loader requires the exact device, hardware, geometry, sensor, and data-generation context, validates the digest and generation-bound path, and accepts only the seven measured SafetyNode parameters. Explicit parameter values must match the snapshot; conflicts fail closed. The worker remains `sensor_only`, and the existing CORE policy remains the only command authority. The packaged default keeps both switches disabled.

**Consequences:** The Device runtime supplies `ROSY_DATA_GENERATION` and `ROSY_DATA_PATH`; a stale, missing, malformed, or cross-device record prevents worker startup before any ROS node is created. CORE exposes the loaded record's revision and digest for diagnostics, while the worker's applied policy revision continues to label observations. Calibration loading is not an acknowledgement of motor policy adoption.

**Validation / Transition:** Unit tests cover pre-construction loading, parameter conflict, generation mismatch, disabled-path non-access, and default YAML opt-in. Device commissioning must still capture the JSON readback, verify the immutable ARM64 manifest, and complete the stationary sensor and motion gates before enabling the switches.

**References:** [calibration binding plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md), [control absorption results](../plans/2026-09-12-control-absorption-results.md), [Device readback contract](../deployment/raspberry-pi-runtime.md).

---

## D-48 Optional camera preprocessing worker telemetry

**Status:** Accepted (2026-09-13). This is an observation and diagnostics
contract; camera output never replaces IR/LiDAR safety authority or grants
motion permission.

**Context:** The absorbed OpenCV path previously combined capture hygiene,
rotation, classification and ROS publication in one node. A bad frame size,
sequence gap or slow preprocessing could therefore be invisible to Device
readback and replay tests.

**Decision:** `rosy_control.sensing.camera_worker.CameraPreprocessWorker` owns
the ROS-free frame contract. It validates the fixed profile resolution and
quarter-turn rotation, counts missing and out-of-order frame IDs, applies a
processing latency budget, and emits secret-free telemetry containing profile
revision, frame ID, dimensions, drops, latency, capture age, CPU time, memory
high-water mark and quality reason. Invalid, stale-order or over-budget frames
are unavailable evidence. The existing `camera_detect_node` uses this worker
when its optional camera is running and publishes the telemetry on
`camera/telemetry`; semantic box/grasp detection remains out of scope.

**Consequences:** The same worker can be exercised with deterministic fixtures
without ROS or Picamera2. A Device profile must keep the camera disabled until
the resolution, latency and real sensor gates are accepted. `camera/telemetry`
is diagnostic evidence and must not be used as a second command authority.

**Validation / Transition:** Worker tests cover profile bounds, rotation,
resolution and corrupt-frame holds, sequence gaps, out-of-order frames,
latency-budget holds and JSON-safe telemetry. The full `rosy_control` suite is
the local software gate; Raspberry Pi camera timing and CSI access remain a
Device/FIELD gate.

**References:** [camera worker](../../src/rosy_control/rosy_control/sensing/camera_worker.py), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-49 Gazebo motion provenance hashes use the absorbed package root

**Status:** Accepted (2026-09-13). This is a source-evidence and maintenance
contract; it does not certify a physical robot or motion trial.

**Context:** The absorbed Gazebo motion contract tool still hashed a historical
`/tmp` checkout path. On a clean Rosy OS checkout or Device that path was
absent, so the evidence could silently contain no runtime source hashes while
appearing to complete.

**Decision:** `measure_motion_contract.py` resolves the current package root
from its own location by default. A measurement host may set
`ROSY_SOURCE_ROOT`, but the path must exist and contain both `package.xml` and
the `rosy_control/` package directory. Hashes are deterministic, relative to
that root, and limited to the runtime package. The old checkout is not a
supported source.

**Consequences:** Source provenance remains valid after folder consolidation,
and a missing or malformed source root fails before ROS initialization. The
measurement tool stays an opt-in simulation aid; its output remains distinct
from ARM64 artifact, Device readback, and FIELD evidence.

**Validation / Transition:** Pure tests cover default discovery, explicit
source-root override, missing-root failure, and the absence of the retired
checkout reference. The full absorbed Control suite remains the local gate.

**References:** [motion contract tool](../../src/rosy_control/tools/gz/measure_motion_contract.py), [folder governance](../plans/2026-09-13-folder-structure-governance.md), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-50 Active rosy_control guides use Rosy OS Device procedures

**Status:** Accepted (2026-09-13). Historical standalone instructions remain
available for provenance, but they are not an install or runtime interface.

**Context:** The absorbed package retained long standalone Control guides that
referenced `/home/pinky/dev_ws` and a separate workspace. A banner labelled
them legacy, but an agent or operator could still copy those commands into a
Rosy OS Device procedure.

**Decision:** `src/rosy_control/CLAUDE.md` and `src/rosy_control/STEPS.txt` are
canonical Rosy OS guides. They use the repository test/build flow and the
Device sequence `install-pi.sh`, `verify-pi.sh`, `runtime-mode.sh`, and
`device-readback.sh --json`. The old standalone guides stay in the workspace
archive and are never required by build, runtime, or tests.

**Consequences:** A package-level guide now agrees with the root README and
Device evidence gates. The absorption inventory records the two files as
adapted with their current destination hashes. Legacy entry points remain
available only for parity tests and still cannot run beside CORE.

**Validation / Transition:** The package ownership contract checks both guide
files for the canonical commands and rejects the old standalone workspace
paths. Device installation and physical acceptance remain separate gates.

**References:** [package guides](../../src/rosy_control/CLAUDE.md), [Device runbook](../../src/rosy_control/STEPS.txt), [absorption inventory](../plans/2026-09-12-control-absorption-inventory.csv), [folder governance](../plans/2026-09-13-folder-structure-governance.md).

---

## D-51 Independent safety and measured Device acceptance contract

**Status:** Proposed (2026-09-13). The source and simulation suites cannot
approve physical motion by equivalence alone.

**Context:** The absorbed Control behavior is useful regression evidence, but
matching it does not establish a safe response to stale, contradictory, or
missing sensors, restart, e-stop release, or a delayed stop. Device acceptance
also needs numeric limits that can be reproduced by another operator.

**Decision:** Before a real command handoff, each Device profile must define
the `NORMAL`, `LIMITED`, `HOLD`, `ESTOP_LATCHED`, and `RECOVERY_PENDING` states,
required-stream deadlines, invalid and contradictory-input behavior, limit
precedence, maximum stop latency, and maximum stop distance. Unset values are
`HOLD`. E-stop release and restart discard the previous candidate and require
fresh evidence plus an explicit new action. Equivalence tests remain a
regression layer; the independent safety matrix is a separate acceptance
layer.

**Consequences:** The implementation plan can report a measured threshold and
an evidence owner for every physical gate. A green Python/ROS test cannot
promote a motor, camera, payload, or OMX capability by itself.

**Validation / Transition:** Add the matrix to the selected Pinky Pro profile
and run boot, restart, CORE loss, sensor loss, tilt, pickup, obstacle, stop,
e-stop, and recovery trials with wheels lifted first. Record repetitions,
fixture, timing source, result, artifact revision, and rollback result.

**References:** [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md), [integrated design](../plans/2026-09-12-rosy-os-control-integrated-design.md).

---

## D-52 ARM64 camera placement and shadow handoff gates

**Status:** Proposed (2026-09-13). Camera execution placement and final command
handoff remain unaccepted Device decisions.

**Context:** Picamera2/libcamera permissions and timing determine whether a
host service or least-privilege container can deliver bounded frames. A new
policy must also be observed with real input before it can own output.

**Decision:** On a native ARM64 bench Pi, compare host capture with a
least-privilege vision container using identical fixtures. Measure permission,
restart, frame freshness/drops, p95 latency, CPU, memory, and fault isolation;
record the selected path in a follow-up accepted ADR. Before changing the
publisher, run the new producer in shadow mode while the approved publisher
alone drives the robot. The shadow record must include sample count, mismatch
classes, worst latency, and owner-approved tolerances. Missing tolerances or a
second real publisher keep the gate `HOLD`.

**Consequences:** The current camera worker and sensor adapter remain
observation-only and disabled by default. Device evidence, rather than a
Windows fixture, decides the placement and handoff.

**Validation / Transition:** Complete the ARM64 spike and shadow replay before
enabling camera or switching final command ownership. Keep the old generation
available for rollback and repeat stationary readback after every change.

**References:** [camera worker ADR](#d-48-optional-camera-preprocessing-worker-telemetry), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-53 Device signature/readback trust evidence

**Status:** Accepted (2026-09-13). Pi and physical release acceptance remain
pending.

**Context:** Rosy release staging verifies the signed checksum list, while the
current readback reports the manifest key ID and immutable digests. A key ID or
digest report alone does not prove that the installed release was verified by
the trusted key or that an unauthorized downgrade was rejected.

**Decision:** Device acceptance retains the signed checksum verification result,
trusted key ID, manifest, image digests, activation record, and readback as one
evidence set. A tampered manifest, missing/untrusted signature, unsupported
downgrade, or digest mismatch quarantines the runtime in core-off state. The
readback contract exposes a cryptographic verification result and requires it
for `device_runtime=GO`.

**Consequences:** Existing release staging remains the first enforcement point;
the Device readback repeats the signed checksum verification without
serializing credentials. A readback with only `signing_key_id`, missing
signature material, or a failed verifier is `HOLD`.

**Validation / Transition:** Fake-device cases cover missing, malformed,
untrusted, and valid signatures. The focused readback and release-boundary
tests pass locally; repeat on a Pi after installing the signed ARM64 artifact
and preserve the JSON alongside the release manifest.

**References:** [release signing](../deployment/release-signing-key.md), [Device readback ADR](#d-46-device-install--readback-evidence-contract), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-54 Nav2 profile limits and field maps fail closed

**Status:** Accepted (2026-09-17). Source/configuration gate. Field-map identity
and physical acceptance remain HOLD.

**Context:** CORE and Nav2 currently receive related limits from different
files. The CORE Pinky profile caps angular velocity at 0.80 rad/s, while Nav2
launch and smoother defaults are higher. Hardware launch also selects a
packaged demo map when the site map is missing. Those defaults are useful for
simulation but can hide a commissioning error on a real robot.

**Decision:** The selected Device profile is the source for Nav2 velocity,
acceleration, goal tolerance, progress and footprint parameters. The launch
path validates the generated values before enabling hardware mode. Demo maps
are allowed only for simulation/bench profiles; a field profile enters HOLD
until a loadable site map, image checksum and matching map ID are present.

**Consequences:** Planner tuning is versioned with the robot profile and the
same limits apply to API, Nav2 and absorbed Control candidates. A missing or
stale map becomes a visible commissioning failure instead of a successful goal
on the wrong map.

**Validation / Transition:** Add source tests for profile/parameter equality,
map fail-closed behavior and waypoint map matching. On a Pi, record map ID,
localization covariance, goal error and minimum clearance on a fixed course.

**Implementation note (2026-09-13):** `rosy_navigation.profile_limits` now
loads the mounted Device profile during `hardware.launch.py`, validates launch
overrides and velocity-bearing Nav2 parameters, and fails before including the
Nav2 graph when a ceiling is exceeded. The same launch defaults to a strict
site-map requirement; only an explicit `allow_demo_map:=true` enables the
packaged demo map. This closes the source/configuration gate; the field-map
identity and physical acceptance gates remain open.

**References:** [hardware launch](../../src/rosy_navigation/launch/hardware.launch.py), [Nav2 parameters](../../src/rosy_navigation/params/nav2_params.yaml), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-55 Mobile manipulation is a robot-local mission capability

**Status:** Accepted (2026-09-17). Architecture. OMX capability stays disabled
until Device payload tests. Pinky+OMX composite Asset is still not v1 (D-71).

**Context:** Nav2 can move the base but does not establish grasp success,
object possession, arm collision safety or pallet stability. The current OS has
no accepted OMX/MoveIt execution path. A second arm or mission process that
publishes base velocity would also bypass the CORE command boundary.

**Decision:** A future `rosy_manipulation` action/state machine owns the
approach, perception, grasp, transport and placement transaction. OMX/MoveIt
publishes arm actions only; CORE remains the sole final `cmd_vel` arbiter. The
carried-object state selects a measured 2-D base footprint and speed envelope,
while MoveIt maintains the corresponding 3-D collision scene. Unknown object,
arm or gripper state causes HOLD after restart or link loss.

**Consequences:** Navigation and manipulation can be tested independently and
then composed with one mission ID and one evidence record. The API does not
advertise OMX until model, mount, power, hand-eye, collision interlock,
payload and recovery tests pass.

**Validation / Transition:** First validate known rectangular blocks and a
fixed placement fixture. Record grasp/placement success, repeatability,
minimum clearance, tip margin, battery/thermal load and recovery outcomes on
the Pi and Pinky bench before enabling a mobile profile.

**Implementation note (2026-09-13):** The Device configuration now carries a
`motion_profiles.yaml` template with explicit `unknown`, `base`, `stowed_arm`,
`carrying_box` and `placing` states. All are unmeasured by default. Hardware
launch accepts a measured state only when its polygon, clearance, payload,
motion envelope and MoveIt scene revision are present; it then injects the
same polygon into both Nav2 costmaps and applies the tighter state speed
limits. No estimated box or arm dimensions are shipped.

**References:** [mobile manipulation research](../plans/2026-09-12-mobile-manipulation-research.md), [Pinky/OMX mounting research](../plans/2026-09-12-pinky-omx-mounting-spec-research.md), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

## D-56 Odometry and IMU fusion is a measured optional profile

**Status:** Accepted (2026-09-17). Encoder baseline. Fusion profile unselected;
`rosy_imu_bno055` is not in the default image (D-84). Physical calibration
remains pending.

**Context:** Nav2 depends on a stable `map → odom → base` transform and fresh
odometry. The current bridge observes IMU data, but observation alone does not
make it a valid localization input. Uncalibrated or contradictory IMU data can
make AMCL and the costmaps appear healthy while the pose is wrong.

**Decision:** Keep encoder odometry as the baseline. Add wheel+IMU fusion only
as an explicitly selected Device profile after covariance, bias, timestamp,
frame-prefix, dropout and restart tests pass. Missing or stale fusion input
keeps navigation in HOLD; it never silently falls back to an unverified pose.

**Consequences:** The baseline remains deployable without the IMU WIP, while a
future fusion profile has a reproducible acceptance boundary and rollback path.

**Validation / Transition:** Run the optional BNO055 driver on ARM64, capture
stationary and repeated-turn data, compare encoder-only versus fused pose
error, then run the same Nav2 goal/cancel/recovery course on a Pi with wheels
lifted first.

**Implementation note (2026-09-13):** `rosy_imu_bno055` now has bounded,
stage-labelled chip/configuration/fusion startup, explicit `reset_on_start`
control (default `false`), signed unit decoding, invalid-sample rejection,
and transient `sensors/imu/status` health telemetry. The package includes an
opt-in launch/config path and injected-bus fault tests, but it is not loaded by
the default Rosy OS image and does not promote IMU data to localization.

**References:** [Pinky profile](../../src/rosy_core/config/profile.pinky_pro.yaml), [ROS bridge](../../src/rosy_core/rosy_core/bridge/ros_bridge.py), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-57 ROS-native first; board and vendor differences stay in adapters

**Status:** Accepted (2026-09-13). This establishes a development direction;
it does not certify a physical device.

**Context:** Rosy OS already uses ROS 2 messages and Nav2, but the Pinky motor
path is a custom Python driver and the OMX path is not implemented. Replacing
those paths with more bespoke middleware would duplicate lifecycle, parameter,
diagnostic and action contracts that ROS already provides.

**Decision:** Prefer ROS 2 standard interfaces and runtime facilities in this
order: launch parameters and YAML profiles, lifecycle and diagnostics, Nav2
actions/costmaps, `sensor_msgs`/`image_transport`, `robot_localization`,
`ros2_control`, and MoveIt 2. Pinky Pro transport/kinematics and OMX vendor
transport/model details are adapter responsibilities. Adapters may translate
hardware and expose standard ROS interfaces, but they must not bypass CORE
safety or publish the final base `cmd_vel`. Unknown or unmeasured hardware
stays disabled and fails closed.

**Consequences:** The current `rosy_bringup` driver remains the baseline while
a measured `ros2_control` replacement is proven. `rosy_bringup.pinky_pro_adapter`
now validates parameters before SDK construction. `rosy_omx_adapter` provides a
disabled-by-default, model-neutral controller contract; it does not pretend a
vendor driver exists, and the Device `io` image ships its profile validator
without activating hardware. ROS-native packages can be selected without
changing the external CORE API.

**Validation / Transition:** Keep parameter and adapter tests ROS-free, then
run launch/graph tests in the Jazzy overlay. On Pi, compare the future
`ros2_control` base adapter with the current driver for encoder sign, odometry,
command limits, deadman, torque-off and restart. Select an OMX model only after
driver, joint limits, MoveIt collision scene, hand-eye, power and payload tests
pass.

**References:** [Pinky adapter](../../src/rosy_bringup/rosy_bringup/pinky_pro_adapter.py), [OMX adapter](../../src/rosy_omx_adapter/rosy_omx_adapter/profile.py), [ROS-native implementation checkpoint](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-58 Hardware motion requires an authoritative readiness gate

**Status:** Accepted (2026-09-13). This closes the software-side gate; ROS
graph, ARM64 image and physical stop-latency evidence remain required.

**Context:** A lifecycle manager or a discovered motor node can exist while
localization, Nav2 controllers, costmaps or the final motor transport is
still inactive. Treating node discovery or a REST `accepted` response as
readiness can therefore pass a velocity candidate into an incomplete graph.

**Decision:** Hardware mode requires active lifecycle transitions from AMCL,
map server, controller server and both costmaps, plus a refreshed latched
`motor/ready` adapter lease. The ROS-free
`NavigationReadinessGate` is the single decision used by navigation requests,
the command mux and the final CORE publisher. Until every required component
is active and fresh, CORE reports `navigation_readiness=ERROR`, refuses new
navigation/teleop requests with `HARDWARE_NOT_READY`, and publishes zero at
the normal 50 Hz cadence. Core/simulation profiles keep the gate disabled
unless explicitly opted in.

**Consequences:** Lifecycle state is no longer inferred from node discovery;
the motor adapter must publish a transient-local ready signal and refresh it
while its transport is alive. This software gate supplements, and never
replaces, the driver deadman and physical E-stop. A missing transition or
expired lease leaves the runtime in HOLD without creating a competing
`cmd_vel` publisher.

**Validation / Transition:** Host tests cover all component combinations,
lease expiry, API/command rejection and zero output. The bridge registration
contract covers the six readiness subscriptions, and bringup tests cover the
latched adapter signal. Repeat lifecycle, restart, UART-loss and stop-latency
measurements on the signed ARM64 image with lifted wheels before promoting
hardware motion.

**References:** [readiness gate](../../src/rosy_core/rosy_core/navigation/readiness.py), [ROS bridge](../../src/rosy_core/rosy_core/bridge/ros_bridge.py), [Pinky bringup](../../src/rosy_bringup/rosy_bringup/bringup.py), [Device validation plan](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-59 사이트 패브릭은 역할별 계약 버스다

**Status:** Accepted (2026-09-14). 설계 결정 상태이며 Fleet 서버·관제 런타임·영상
분리·장치 인수 상태와 구분한다.

**Context:** 디바이스, 리더/팔로워, 인지, 관제 PC가 한 제품으로 계속 맞물려야
한다. 이를 로봇마다 메시지 브로커를 두거나 로봇 간 DDS를 다시 여는 방식으로
풀면 D-5·D-8·D-22·D-33·D-38과 충돌한다. 반대로 역할이 섞이면 비전이 속도를
내거나 Fleet이 `cmd_vel`을 흘리거나 CORE가 장치를 직접 열게 된다.

**Decision:** 현장의 모이는 점은 관제 PC의 **한 Fleet 서버**다. 각 디바이스는
CORE가 노출한 미들웨어 계약(REST 명령, outbound 이벤트, swarm pose 소켓)으로만
모이고 흩어진다. 한 컴포넌트는 한 역할만 수행한다. 로봇 안 제어 버스(L0
localhost ROS)와 CORE EventBus(L1)는 유지한다. 원본 영상은 인지 역할(L3)에
남기고 나중에 프로세스만 분리할 수 있으며, 사이트 계약 버스(L2)의 상시 경로가
되지 않는다. 사이트 오케스트레이터는 미션·등록·중계만 하고 최종 바퀴 명령을
생산하지 않는다.

**Alternatives:** 로봇에 Kafka/NATS/MQTT를 올려 단일 버스로 쓰는 안, 로봇 간
DDS 또는 `rmw_zenoh`를 사이트 패브릭으로 승격하는 안을 검토했다. 전자는 제어
주기와 최소 권한 분리를 깨고, 후자는 D-33의 격리를 되돌린다. 채택하지 않는다.

**Consequences:** `rosy_fleet` 씨앗은 오케스트레이터 역할의 조각으로 남고, 로봇
`FleetAgent`는 서버가 생기기 전에 소켓을 열지 않는다. 관제 UI는 Fleet만 본다.
역할 침범(인지→`cmd_vel`, Fleet→ROS, CORE→`/dev`)은 구현 결함이다. 이 결정은
Fleet 서버 구현 완료나 영상 미리보기 제공을 뜻하지 않는다.

**Validation / Transition:** 역할·import 경계와 단일 `cmd_vel` publisher, 릴레이
단절=0 Hz를 호스트 시험으로 고정한다. 관제 서버와 outbound agent는 서버 착수
시에만 연다. ARM64 이미지와 Pi 인수는 기존 Device 계획을 따른다.

**References:** [사이트 패브릭 설계](../plans/2026-09-14-site-middleware-role-fabric-design.md), [FLEET SRS](../spec/ROSY%20FLEET%20SRS.md), [swarm 슬라이스](../plans/2026-09-08-swarm-formation-slice-design.md).

---

## D-60 추종은 navigation이 아니라 swarm 패키지다

**Status:** Accepted (2026-09-15). 설계 결정 상태이며 코드 이동과 구분한다.

**Context:** `navigation/`이 NAV와 SWM을 같이 주장한다. `SwarmManager`는 이미
별도 파일이지만 import 경로와 항법 오류 문구가 군집을 알고 있다. 항법 실행기가
팔로워 세션을 생각하면 목표 전달 외에 책임이 생긴다. 모듈 분할 기준은 크기
분할을 금지하고, 요구사항 가문이 겹칠 때만 나눈다(C7/B1).

**Decision:** 로봇 쪽 추종(SWM-001~007)은 `rosy_core.swarm`이 소유한다.
`poses.py`는 참조 표본과 오프셋, `manager.py`는 세션이다. 항법은 단발 목표와
moving-goal 세션만 실행한다. 의존은 swarm → navigation 한 방향이다.
`navigation/swarm.py`는 옮긴 뒤 삭제한다. 이중 import 경로는 두지 않는다.
항법 오류는 군집 이름 대신 moving-goal 세션이라고 말한다.

**Alternatives:** 파일을 `navigation/`에 두고 AGENTS만 고치는 안은 경로가 항법을
계속 가리킨다. 최상위 `swarm.py` 한 파일은 B2(두 역할)를 만족하지 못한다.
채택하지 않는다.

**Consequences:** API/WS는 `svc.swarm`만 본다. `rosy_fleet`은 로봇 SwarmManager를
import하지 않는다. 매핑 세션 C7, Hub listen, 동작 변경은 이번 결정이 아니다.

**Validation / Transition:** navigation 트리의 swarm import 금지 시험, 기존 swarm
호스트 시험의 import 경로 갱신, 기하 대조를 새 경로로 옮긴 뒤 승격 완료로 본다.

**References:** [항법·군집 분리 설계](../plans/2026-09-15-navigation-swarm-split-design.md), [module split](../plans/2026-09-06-module-split-criteria.md).

---

## D-61 모듈 상태는 progress·logs·생성 index로 기록하고 계약 시험으로 지킨다

**Status:** Accepted (2026-09-17). 기록 구조이며 ARTIFACT/DEVICE/FIELD 판정과
구분한다.

**Context:** AGENTS.md 96개 중 70개가 2026-09-02에서 멈췄다. 진행 상태는 날짜별
plan 말미, `*-results.md`, git 밖 작업 폴더 `progress.md`에 흩어졌고 같은 항목이
두 번 기록됐다. 모듈의 현재 gate를 한 곳에서 읽을 수 없고, 이 ADR Log는 109KB로
커져 인덱스·ID 연속성을 사람이 맞추고 있다.

**Decision:** 책임자와 증거 gate가 있는 모듈(패키지, `deploy`, `dock`, `docs`)은
`AGENTS.md` 옆에 세 기록을 둔다. `progress.md`는 frontmatter gate 스냅샷을 덮어쓰고
(`GO`는 evidence, `HOLD`는 blocker 필수), `logs.md`는 추가만 하며, `index.md`와 루트
`STATUS.md`는 `tools/harness/rosy_harness.py`가 명시적 참조로만 생성한다. 충돌 시
SRS·API·ADR > progress > logs > AGENTS 순이다. 형식과 생성물 최신성, ADR 인덱스·ID
연속성은 `test/test_harness_contracts.py`가 CI의 host pytest에서 확인한다.
하위 폴더는 AGENTS.md만 유지한다.

**Alternatives:** 모든 AGENTS 폴더에 기록을 두는 안은 정체된 AGENTS.md를 세 배로
늘린다. 중앙 파일 하나에 module 태그를 다는 안은 모듈에서 작업하는 에이전트가 자기
상태를 바로 읽지 못한다. 채택하지 않는다.

**Consequences:** 기존 날짜별 plan과 results는 설계·증거 기록으로 남고, 최신 상태만
모듈 `progress.md`로 옮긴다. 이 결정은 기록 구조이며 ARTIFACT/DEVICE/FIELD 판정을
바꾸지 않는다. ADR의 개별 파일 분리는 후속 단계이며, 분리 후에도 이 Log는 전체
본문을 담은 생성 파일로 유지해 기존 링크와 시험을 보존한다.

**Validation / Transition:** `python tools/harness/rosy_harness.py lint` ·
`python -m pytest test/test_harness_contracts.py test/test_network_topology_contracts.py -q`.
harness.yaml 모듈마다 `progress.md`/`logs.md`와 생성 `index.md`가 있다. 루트
`STATUS.md`는 generate만 고친다. last_verified가 `uncommitted`이면 lint 경고.

**References:** [module harness 설계](../plans/2026-09-15-module-harness-design.md), [폴더 구조 정리](../plans/2026-09-13-folder-structure-governance.md).

---

## D-62 CORE는 필수이고 나머지 런타임은 선택 슬라이스다

**Status:** Accepted (2026-09-16). 설계 결정이며 설치 스크립트·이미지 분리·OMX/AI
실기 인수와 구분한다.

**Context:** Pi 5와 OMX/AI가 같은 미들웨어를 쓰되, 한 이미지에 모터·Nav2·카메라·팔·
추론을 다 넣을 수는 없다. 지금 `core|motor|hardware` 모드는 Nav2와 LiDAR를
hardware에 묶어 두어서 선택 설치가 어렵다. CORE를 프로세스마다 쪼개면 D-1이
깨진다.

**Decision:** `rosy_core` 프로세스와 `rosy-core` 이미지는 필수 슬라이스다. motor,
io, nav, vision, omx, ai는 카탈로그에서 고른다. 각 슬라이스는 localhost ROS
토픽 가족과 프로세스(또는 기존 compose 서비스)를 소유한다. CORE는 슬라이스
패키지를 import하지 않는다. 꺼진 슬라이스의 capability는 false다. 없는
슬라이스를 설치 플래그로 조용히 무시하지 않는다. 사이트 버스와 최종 `cmd_vel`은
바뀌지 않는다.

**Alternatives:** CORE를 메시지 도메인별 노드로 분해하는 안, 단일 이미지+플래그만
쓰는 안을 검토했다. 전자는 단일 프로세스·단일 publisher를 흔들고, 후자는 Pi
이미지에 OMX/NPU를 상시 싣는다.

**Consequences:** `board.yaml` presets가 현재 세 모드와 같게 시작해서 호환을 지킨다.
vision/omx/ai는 카탈로그에만 있고 기본 꺼짐이다. CORE Dockerfile에 이미 있는
OpenCV/`rosy_control`은 부채이며 이 결정이 제거를 강제하지 않는다.

**Validation / Transition:** 카탈로그 시험, CORE import 가드, install preset 해석,
core 스테이지가 omx/imu를 COPY하지 않음을 호스트 시험으로 고정한다.

**References:** [선택 슬라이스 설계](../plans/2026-09-16-optional-runtime-slices-design.md), [실행 계획](../plans/2026-09-16-optional-runtime-slices.md).

---

## D-63 모듈형 미들웨어 목표 — CORE는 얇고 슬라이스는 선택이다

**Status:** Accepted (2026-09-16). 목적지 결정이다. 구현은 자식 ADR이 한 이음새씩 닫는다.

**Context:** Pi 5와 OMX/AI가 같은 미들웨어를 써야 한다. CORE에 카메라·팔·추론·Nav2가
섞이면 설치와 책임이 다시 한 덩어리가 된다. D-62는 카탈로그만 열었다.

**Decision:** 끝 상태는 이것이다. CORE 프로세스와 `rosy-core` 이미지는 필수이고 얇다
(API, 안전, 최종 `cmd_vel`, 사건, 대시보드). motor/io/nav/vision/omx/ai는 선택
슬라이스이며 각자 ROS 메시지 가족과 프로세스를 소유한다. CORE는 슬라이스
패키지를 import하지 않는다. 이미지는 고르지 않은 스택을 싣지 않는다. CORE
프로세스를 쪼개지 않고, 로봇에 사이트 브로커를 올리지 않는다.

**Sequence:** D-62 카탈로그 → D-64 CORE의 rosy_control import 경계 → 이후 이미지
축출, 매핑 분리, nav overlay, vision/omx 설치 가능 overlay.

**Consequences:** 이 ADR만으로 이미지를 바꾸거나 하드웨어를 켜지 않는다. 자식 ADR이
없을 때 “모듈화 완료”라고 말하지 않는다.

**References:** [목표 설계](../plans/2026-09-16-modular-middleware-goal-design.md).

---

## D-64 CORE 생산 코드의 rosy_control import는 센서 어댑터뿐이다

**Status:** Accepted (2026-09-16). 설계 결정이며 이미지 COPY 축출과 구분한다.

**Context:** `safety/manager.py`가 `rosy_control.control.command_gate`와
`actuation`을 import한다. 흡수 어댑터 밖에서도 Control 타입을 알고 있으면
안전 패키지가 센서 스택에 묶인다. D-63 2단계.

**Decision:** `src/rosy_core/rosy_core/` 아래 `rosy_control` import는
`bridge/control_sensor_adapter.py`만 허용한다. SafetyManager의
`bind_control_policy` / `bind_simulation_actuation`은 타입 모듈을 import하지
않고 evaluate/revision 등 공개 속성으로 duck-type 한다. 시험 파일의
rosy_control import는 허용한다. CORE 이미지에서 rosy_control을 빼는 일은
후속이다.

**Alternatives:** SafetyManager에 CommandPolicy를 남기는 안은 경계를 문서만으로
둔다. rosy_control 전체를 이번 단계에서 이미지에서 빼는 안은 센서 어댑터
런타임을 한꺼번에 옮긴다. 채택하지 않는다.

**Validation / Transition:** AST 가드 시험이 어댑터 외 import를 실패시킨다.
기존 control policy 링크 시험은 통과해야 한다.

**References:** [실행 계획](../plans/2026-09-16-core-control-import-boundary.md).

---

## D-65 개념 객체는 CORE와 D-62 슬라이스에 매핑한다

**Status:** Accepted (2026-09-17). inventory API, 어댑터 매니페스트, Phase 3
descriptor availability가 올라왔다.

**Context:** `docs/concept`는 분산 OS 목표(Node/Device/Component/Capability/
Asset/Task, apt 프로파일, 제어면)를 적는다. 살아 있는 스택은 Pinky CORE와
Docker이며, "필요한 것만 설치"는 D-62 슬라이스가 이미 결정했다. D-61–D-64는
기록·슬라이스 카탈로그·미들웨어 목표·import 경계다. 목표 문서를 코드처럼
읽거나 목표 용어를 무시하면 이후 작업이 두 어휘를 만든다.

**Decision:** v1은 concept 객체를 CORE + D-62 슬라이스에 매핑한다. 호스트는
Node(`RuntimeNode`), CORE가 관리하는 로봇은 Device(`device_id` = robot id),
구동·LiDAR 등은 Component, YAML 플래그는 Capability, 단위는 단일 Device
Asset, REST 원자 액션은 Task(`TaskKind`)다. Concept 15 apt/`rosyctl`과 제어면은
concept 13의 이후 단계다. Concept 05 ROS 토픽(`/rosy/{device_id}/state`)은
외부 API가 아니다(CORE SRS §1.3).

**Alternatives:** 저장소를 Debian `rosy-profile-*`와 `rosyctl`로 전면 재작성하는
안, 용어만 고치고 매핑을 남기지 않는 안을 검토했다. 전자는 D-1·D-38·D-62를
버리고, 후자는 목표 문서와 런타임이 계속 어긋난다. 채택하지 않는다.

**Consequences:** `CONCEPTS.md`가 살아 있는 용어집이다. concept 본문 00–15는
목표로 남고 이 결정이 재작성하지 않는다. 복합 Pinky+OMX Asset, compute/AI,
워크플로 엔진은 v1이 아니다(D-12). D-63 모듈형 미들웨어 목표와 D-64 import
경계는 그대로다.

**Validation / Transition:** `CONCEPTS.md` 여섯 객체, `GET /api/v1/system/inventory`,
Pinky/OMX 매니페스트, `TaskKind.concept_id`와 inventory `descriptors`.

**References:** [concept-runtime-alignment 설계](../plans/2026-09-16-concept-runtime-alignment-design.md), [concept 13 이관](../concept/13_ROSY_Current_to_Target_Migration.md).

---

## D-66 CORE 이미지에 rosy_control과 OpenCV가 없다

**Status:** Accepted (2026-09-17). D-63 3단계. 센서 어댑터 소스와 Device ARTIFACT 빌드는 이 결정이 대신하지 않는다.

**Context:** D-64 이후 CORE 생산 코드의 `rosy_control` import는 어댑터 한 파일뿐이다. 그런데 `core` 이미지가 여전히 `python3-opencv`와 `src/rosy_control`을 COPY해서 Pi에 비전 스택을 상시 싣는다. 꺼진 슬라이스가 이미지에 있으면 D-62 카탈로그가 거짓이다.

**Decision:** `rosy-core` 이미지(core-runtime/core-build/core)는 `rosy_control`을 COPY하지 않고 `python3-opencv`를 설치하지 않는다. `rosy_core/package.xml`은 `rosy_control` exec_depend를 두지 않는다. 기본 `control.sensor_adapter.enabled`는 false다. 어댑터를 켠 채 control 슬라이스가 없으면 import가 실패하고 기동은 fail-closed다.

**Alternatives:** 이미지에 패키지를 남기고 capability만 끄는 안(D-62가 버린 안). 어댑터 파일을 토픽 경계로 바꾸는 안은 다음 단계다.

**Consequences:** 기본 CORE는 OpenCV 없이 기동한다. 센서 워커가 필요하면 이후 control/vision 슬라이스 이미지가 패키지를 싣는다. 이 결정이 ARM64 digest를 GO로 만들지 않는다.

**Validation / Transition:** Dockerfile core 스테이지 문자열 가드. `colcon --packages-up-to rosy_core`가 `rosy_control` 소스 없이 성립한다.

**References:** [모듈형 미들웨어 목표](../plans/2026-09-16-modular-middleware-goal-design.md).

---

## D-67 RobotMode가 운용 계약이고 DeviceState는 inventory 파생이다

**Status:** Accepted (2026-09-17). concept 06.

**Context:** concept 06은 BOOTING…UPDATING 장치 수명 주기를 적는다. 살아 있는
계약은 `RobotMode`(`IDLE|MANUAL|NAVIGATION|DOCKING|EMERGENCY`)와 안전 정지다.
두 상태 기계를 명령 경로에 나란히 두면 클라이언트가 어느 쪽이 권위인지
모른다.

**Decision:** 명령·안전·deadman의 권위 상태는 `RobotMode`다. concept
`DeviceState`는 `GET /api/v1/system/inventory`의 파생 값이다. EMERGENCY/e-stop
→ `SAFE_STOP`, diagnostics ERROR → `FAULT`, 바쁜 모드 → `BUSY`, 스냅샷 전
→ `BOOTING`, 그 외 IDLE+정상 → `READY`. `RobotMode` enum을 concept 이름로
바꾸지 않는다.

**Alternatives:** `RobotMode`를 concept 06 enum으로 교체하는 안은 API와 안전
시험을 깨뜨린다. DeviceState를 명령 거절의 유일한 근거로 쓰는 안은 기존
estop/모드 경로와 이중화된다. 채택하지 않는다.

**Consequences:** inventory는 개념 수명 주기를 보여 준다. 텔레옵·내비 거절은
계속 모드·safety·CAP-003이다. 진단이 오기 전 `GET /inventory`는 BOOTING이고
`RobotMode`는 IDLE이다.

**Validation / Transition:** `test_domain_model.py` READY/SAFE_STOP/BOOTING.
`test_api.py::test_inventory_is_booting_before_diagnostics_arrive` 와
`test_inventory_leaves_booting_after_a_diagnostic`. `RobotMode` 스키마 시험은
그대로 통과해야 한다. HOST 2026-09-17: 해당 묶음 19 passed.

**References:** [concept 06](../concept/06_ROSY_Device_State_and_Lifecycle.md), D-65.

---

## D-68 CAP-001과 개념 descriptor는 문서를 나눈다

**Status:** Accepted (2026-09-17). concept 07. `0728125`.

**Context:** D-11은 `GET /api/v1/system/capabilities`에 CAP-001 YAML 불리언을
둔다. concept 07은 `mobility.move` 같은 id와 동적 가용성을 원한다. 한
문서에 둘을 섞으면 CAP-001 소비자가 깨진다(D-32).

**Decision:** CAP-001 본문은 바꾸지 않는다. 개념 id는 inventory
`descriptors[]`(`id`, `available`)와 `capability_ids`에만 둔다. YAML이 true인
플래그만 광고한다. `manipulate.pick` / `scan_rfid` / `infer` / `train`은
슬라이스가 생기기 전에 광고하지 않는다. `available`은 DeviceState가
BOOTING·FAULT·SAFE_STOP·OFFLINE·UPDATING이면 false다. `TaskKind.require()`는
CAP-001 플래그로 501을 유지한다.

**Alternatives:** CAP-001을 개념 id로 교체하는 안, 정적 YAML만 두고 가용성을
숨기는 안. 전자는 D-11 소비자를 깨고, 후자는 concept 07 §5를 무시한다.

**Consequences:** Fleet/SDK는 기존 capabilities를 읽고, 개념 뷰는 inventory를
읽는다. require()가 concept id를 말하게 바꾸는 것은 에러 본문 계약이므로
별도 ADR이 필요하다.

**Validation / Transition:** `test_capability_descriptors.py`,
`test_inventory_is_a_mobile_base_without_pick_or_rfid`. HOST 2026-09-17:
SAFE_STOP/BOOTING에서 `available=false`, pick/rfid/infer/train 없음.

**References:** [concept 07](../concept/07_ROSY_Capability_Model.md), D-11, D-32.

---

## D-69 어댑터는 트리 안 YAML 매니페스트다

**Status:** Accepted (2026-09-17). concept 04, 15.

**Context:** concept 04/15는 `rosy-adapter-pinky` apt와 `rosyctl`을 그린다.
살아 있는 어댑터는 `rosy_bringup`(Pinky)과 꺼진 `rosy_omx_adapter`다. D-62는
설치 모듈을 슬라이스로 이미 정했다.

**Decision:** 장치 어댑터는 워크스페이스 패키지 +
`config/adapter.manifest.yaml`이다. CORE `AdapterRegistry`는 YAML만 읽고
OMX/MoveIt 런타임을 import하지 않는다(D-62, D-64). Debian
`rosy-adapter-*`와 `rosyctl`은 만들지 않는다. 매니페스트 `provides`가 비면
(OMX disabled) 능력이 없다. 어댑터는 운용 `cmd_vel`을 발행하지 않는다(D-38).

**Alternatives:** 패키지를 apt 프로파일로 재배치하는 안은 D-62를 뒤집는다.
setuptools entry-point 동적 로딩은 이번 범위가 아니다.

**Consequences:** Pinky/OMX 매니페스트가 카탈로그다. 새 장치는 패키지+YAML로
추가한다. concept 15 Layer 3 apt는 D-71이 미룬다.

**Validation / Transition:** 매니페스트 파싱 시험, CORE가 `rosy_omx_adapter`
코드를 import하지 않는다는 가드.

**References:** [concept 04](../concept/04_ROSY_Device_Adapter_Specification.md), D-57, D-62.

---

## D-70 워크플로 엔진은 로봇이 아니라 Fleet이다

**Status:** Accepted (2026-09-17). concept 08. D-12를 concept Task/Workflow에
명시한다.

**Context:** concept 08은 Task 상태(PENDING…BLOCKED)와 TransportObject 같은
워크플로를 적는다. D-12는 미션 DSL을 Fleet에만 둔다. 로봇에 두 번째 상태기계를
만들면 원자 액션 API와 미션이 섞인다.

**Decision:** 로봇이 노출하는 Task는 `TaskKind`(MOVE, NAVIGATE, RETURN_HOME,
FOLLOW, DOCK)와 기존 매니저다. PENDING→SUCCEEDED 워크플로 객체, 우선순위
스케줄러, 크로스 디바이스 워크플로는 로봇에 두지 않는다. 미션은 Fleet(미구현)
영역이다. `TaskKind.concept_id`가 필요한 개념 capability를 가리킨다.

**Alternatives:** 로봇에 concept 08 상태기계를 심는 안은 D-12와 로컬 안전
경계를 흐린다. 채택하지 않는다.

**Consequences:** CORE 라우트는 원자 액션만 추가한다. Pick/Place/Transport
워크플로는 D-55·D-71 이전에는 API에 없다.

**Validation / Transition:** `TaskKind` 목록과 inventory `task_kinds`. 새
미션 리소스가 `rosy_core`에 생기면 이 결정을 어긴다.

**References:** [concept 08](../concept/08_ROSY_Task_and_Workflow.md), D-12.

---

## D-71 concept 05·09–12·15 apt는 v1 미들웨어가 아니다

**Status:** Accepted (2026-09-17). 목표 OS 나중 단계의 명시적 연기.

**Context:** concept 폴더는 분산 제어면, `/rosy/{device_id}/state` 토픽 트리,
Pinky+OMX 합성 Asset, Gram/RTX 패브릭, VLA, Teach-Record-Train, apt/`rosyctl`,
concept 14의 Gram/합성 수락을 그린다. 이를 현재 스프린트 백로그로 읽으면
D-1·D-12·D-38·D-62와 충돌한다.

**Decision:** 다음을 v1 미들웨어가 아니라고 고정한다.

- concept 05 공개 토픽/액션 트리. 외부 클라이언트는 REST/WS만 쓴다.
- concept 09 합성 Asset. D-55가 OMX를 켜기 전에는 `asset.type=mobile_base`
  단일 Device다.
- concept 10 Compute Fabric (Gram/RTX 역할 노드).
- concept 11 모델 레지스트리·VLA·정책 배포. vision/ai는 D-62 카탈로그만.
- concept 12 데이터셋/에피소드 파이프라인.
- concept 15 `rosy-runtime-*` apt 메타패키지와 `rosyctl`.
- concept 14의 Gram 인식·합성 태스크 수락. Device GO는 Device 검증 계획이
  정한다.

**Alternatives:** concept 본문을 v1 범위로 다시 쓰는 안은 목표 문서를 지운다.
지금 패브릭을 구현하는 안은 CORE를 제어면으로 만든다. 채택하지 않는다.

**Consequences:** 미들웨어 작업은 D-67–D-70과 Device ARTIFACT 계획 안에서
한다. 09–12 구현 PR은 이 ADR을 먼저 뒤집어야 한다.

**Validation / Transition:** concept README 매핑 표의 target-not-built 행.
합성·패브릭·rosyctl 코드가 `rosy_core`에 생기면 실패로 본다.

**References:** [concept README](../concept/README.md),
[concept 폴더 ADR 계획](../plans/2026-09-17-concept-folder-adr-plan.md).

---

## D-73 모듈마다 자기 코드를 도는 기능 시험 표면이 있다

**Status:** Accepted (2026-09-17). D-61은 상태 기록이다. 이 결정은 기능 시험
표면이다.

**Context:** `tools/harness/harness.yaml`의 `tests:`가 모듈 기능을 가리키는 것처럼
보이지만, `rosy_led`·`rosy_sensor_adc`·`rosy_lamp_control`은 공유
`test/test_nav2_hardware_slice.py`(compose/Nav2 계약)만 가리키고
`rosy_interfaces`는 빈 목록이다. 슬라이스 계약 시험이 통과해도 그 패키지의
공개 함수·파라미터·인터페이스는 한 번도 안 돈다. AST/문자열 가드(C6, Dockerfile)
는 경계를 지키지만 동작을 증명하지 않는다.

**Decision:** harness 모듈은 `functional` 목록을 가진다. 항목은 **그 모듈이
소유한 코드**를 호출하거나 그 모듈 파일만 단언한다.

- `pytest`: ROS 없이 패키지를 import하고 공개 함수·API를 호출한다
  (`rosy_core` TestClient, `rosy_emotion.info_screen.render`).
- `host-contract`: 그 패키지의 package.xml·params·launch·entry point를
  단언한다. 공유 compose 슬라이스 시험은 여기 넣지 않는다.
- `interface-only`: `.srv`/`.msg`/`.action` 산출물이 있다.
- `records`: D-61 기록 모듈(`docs`). 기능 코드가 없다.

`rclpy`/하드웨어가 없으면 `pytest.importorskip`으로 명시 skip 한다. 빈
`functional: []`과 공유 슬라이스 파일만 있는 목록은 오류다. `tests:`(생성
index용)와 `functional:`은 다를 수 있다. D-61 progress `SOURCE.cmd`는 이
표면을 가리켜야 한다.

**Alternatives:** 공유 Nav2 슬라이스 시험으로 모든 드라이버 모듈을 덮는 안은
지금 상태이며 거짓 GO를 만든다. 모든 노드를 호스트에서 rclpy로 띄우는 안은
Windows 개발 호스트에서 돌지 않는다.

**Consequences:** LED/ADC/램프/interfaces는 자기 계약 시험을 가진다. 새 모듈은
harness `functional` 없이 머지하지 않는다. 이 결정이 DEVICE/FIELD GO가 아니다.

**Validation / Transition:** `test/test_module_functional_surface.py`.
`python tools/harness/run_functional.py` — HOST 2026-09-17: 16/16 modules
passed. DEVICE/FIELD 아님.

**References:** D-61, [module harness 설계](../plans/2026-09-15-module-harness-design.md).

---

## D-74 작업 명령은 CORE를 거쳐 내부 ROS로 가고 조회는 CORE에 남는다

**Status:** Accepted (2026-09-17). CORE SRS §1.3을 코드 매핑으로 고정한다.

**Context:** 미들웨어의 자리는 하드웨어 ROS와 외부 REST/WS 사이의 유일한 관문이다
(CORE SRS §1.1). 밖은 ROS 토픽을 몰라도 되고, CORE가 작업 요청을 내부 ROS 2
Topic/Action/Service로 바꾼다. 동시에 모든 HTTP가 ROS 명령은 아니다. inventory·
토큰·identity·Host Agent는 CORE에서 끝난다. 이 구분이 ADR에 없으면 새 엔드포인트가
`/cmd_vel`을 직접 열거나, 조회 API를 가짜 ROS 메시지로 감싼다.

**Decision:**

1. 외부 공개 계약은 REST `/api/v1/*`와 WebSocket `/ws/*`뿐이다. concept 05
   `/rosy/{device_id}/…` 토픽 트리는 공개 API가 아니다(D-71).
2. `TaskKind`(MOVE, NAVIGATE, RETURN_HOME, FOLLOW, DOCK)와 e-stop/safety 작업
   명령은 CORE가 중재한 뒤 **내부 ROS**로 나간다. 최종 `cmd_vel` 퍼블리셔는
   CORE뿐이다(D-2, D-38). Fleet은 `cmd_vel`의 원천이 될 수 없다.
3. UART 모터와 도크 HTTP는 ROS 경로 **뒤**의 드라이버이지, 두 번째 공개
   명령 버스가 아니다.
4. `/api/v1/system`, `/api/v1/host`, `/api/v1/logs`, `/api/v1/events`,
   `/api/v1/diagnostics`는 CORE 로컬이다. ROS 메시지로 바꾸지 않는다.

코드 원천은 `rosy_core.domain.command_mapping`이다. 새 `TaskKind`는 여기에
sink를 적기 전에 API에 넣지 않는다.

**Alternatives:** 외부가 Nav2/`cmd_vel`을 직접 쓰는 안은 SRS §1.3과 D-38을
버린다. 모든 REST를 ROS 서비스로 미러하는 안은 조회·토큰까지 DDS에 태운다.
채택하지 않는다.

**Consequences:** 대시보드·Fleet·SDK는 ROSY API만 본다. 브리지는 내부 통역이다.
워크플로 엔진은 여전히 Fleet이다(D-70).

**Validation / Transition:** `src/rosy_core/test/test_command_mapping.py`.
모든 `TaskKind` sink가 `ros`, system/host는 work prefix와 겹치지 않음.
HOST 2026-09-17: `PYTHONPATH=src/rosy_core python -m pytest
src/rosy_core/test/test_command_mapping.py
src/rosy_core/test/test_domain_model.py
src/rosy_core/test/test_capability_descriptors.py
src/rosy_core/test/test_api.py::test_inventory_is_booting_before_diagnostics_arrive
src/rosy_core/test/test_api.py::test_inventory_leaves_booting_after_a_diagnostic
src/rosy_core/test/test_api.py::test_inventory_is_a_mobile_base_without_pick_or_rfid
test/test_module_functional_surface.py -q` → 19 passed.

**References:** CORE SRS §1.3, D-1, D-2, D-12, D-38, D-70, D-71.

---

## D-72 표면은 법을 공유하고 문법은 나눈다

**Status:** Accepted (2026-09-17). concept 16. L1 색·증거·capability 계약 시험이
올라왔다. 증거 어휘는 G4: `fresh`/`delayed`/`disconnected`/`unavailable`.
capability 표현의 넷째 상태는 `not_provided`(옛 `absent`).

**Context:** 사람이 보는 표면이 넷이다 — 운용자 콘솔, 장비 런타임, Fleet,
그리고 로봇 얼굴(`rosy_emotion` LCD). 지금 살아 있는 둘이 서로 다른 디자인
언어를 쓴다. `rosy_control/web/dashboard.html`은 카드 테두리 대신 바탕으로
위계를 만들고 색을 categorical·status로 닫아 두며 모름·낡음을 구분한다.
`rosy_core/web`은 장식 격자와 gradient를 깔고 CPU·메모리·저장소에 지표별
색(`data-tone`)을 주며, `dom.js`가 모름·낡음·없음을 한 placeholder로 뭉갠다.
둘이 모드·비상정지·배터리를 모두 보여줘서 "이 로봇 괜찮나"에 답이 둘이다.

분할선이 사용자가 아니라 패키지 소유권으로 그어져 있다. 반대로 네 표면을 한
컴포넌트 라이브러리로 묶으면 Fleet이 콘솔처럼 되고 입력이 없는 LCD는
불가능해진다. D-32가 서버에 세운 정직함(속 빈 경로는 501)을 화면이 회색
버튼으로 되돌리고 있다.

**Decision:** 공유 범위를 층으로 가른다.

- L1(법)은 전 표면 구속이다: 증거 4상태(`fresh`/`delayed`/`disconnected`/
  `unavailable` — 값별이며 전송 계층이 아님), 닫힌 3색 집합(categorical/
  status/neutral), 바탕이 위계, 되돌릴 수 없는 명령은 종류가 다르다, 어휘는
  그 표면 청중의 평문이다.
- L2(문법)은 표면마다 독립이며 공유하지 않는다. 레이아웃·상호작용·컴포넌트는
  시청자의 시간 예산과 입력 장치에서 연역한다: 콘솔=공간(스크롤 없음),
  장비 런타임=절차(스크롤이 절차), Fleet=예외(정상은 안 보임),
  얼굴=의도(입력 없음).
- L3(내용)은 이식 가능하다. **capability는 렌더러를 제공하지 않는다.** 데이터
  계약·역할(감지/관측/조작)·우선순위만 제공하고 표현은 표면이 소유한다.
  표현 상태는 `available`/`constrained`/`blocked`/`not_provided`이며
  `blocked`는 이유를 반드시 말한다.

D-68은 유지한다. CAP-001 본문은 게이트로 남고 개념 id·`available`은 inventory
descriptors에만 둔다. 개념 뷰는 inventory를, 기능 게이트는 CAP-001을 읽는다.

합성 자산 규칙(concept 16 §9)은 기록만 하고 구현하지 않는다(D-71, D-55).

**Alternatives:** 표면마다 자유롭게 두는 안은 지금 상태이며 같은 질문에 답이
둘인 문제를 남긴다. 네 표면에 공통 컴포넌트 라이브러리를 두는 안은 Fleet과
LCD의 문법을 파괴한다. 콘솔을 먼저 합치고 토큰을 나중에 뽑는 안은 통합 중에
세 번째 디자인 언어를 만든다.

**Consequences:** 프레임워크와 무관하게 구속한다 — D-7(React) 산출물이든 D-23
로컬 자산이든 같은 법을 지킨다. `rosy_core/web`은 장식·지표별 색·eyebrow를
잃고, `dom.js`는 placeholder 하나 대신 증거 상태를 실어야 한다. 새 capability는
app.js 손배선 대신 역할 슬롯 등록으로 붙는다. 콘솔이 둘인지 하나인지는 D-77.

**Validation / Transition:** HOST 2026-09-17.

- L1 색: `src/rosy_core/test/test_ui_token_contracts.py`
- 증거 판정·게이트: `src/rosy_core/test/test_evidence.py`,
  `src/rosy_core/test/test_dashboard.py`
- `blocked` 이유: `src/rosy_core/test/test_capability_descriptors.py`
- 제어 파이프라인 래스터: `src/rosy_control/test/test_map_raster_color_contract.py`
  (`tokens.css` ↔ `dashboard.html` 교차 단언은 D-73상 거처가 없어 두지 않는다)

콘솔이 둘인지 하나인지는 D-77. G4의 Device viewport·보정 상태기계는
device-validation 계획이 소유하며 이 ADR의 HOST 시험이 DEVICE GO가 아니다.

**References:** [concept 16](../concept/16_ROSY_Interface_Design_Principles.md),
D-7, D-11, D-23, D-32, D-55, D-61, D-68, D-71, D-73, D-75, D-77,
[FLEET SRS](../spec/ROSY%20FLEET%20SRS.md) §1.2,
[device-validation G4](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---
---

## D-75 로봇 로컬 화면은 손으로 쓴 정적 자산이다 — D-7 React 대체

**Status:** Accepted (2026-09-17). D-7을 대체한다. concept 16, D-72.

**Context:** D-7(2026-08)은 로봇 로컬 Web UI를 React 18 + TypeScript + Vite로
개발하고 `dist`를 정적 서빙하기로 했다. D-23(2026-09-01)은 그 뒤에 "별도
React/Node 서비스는 첫 Pi 5 런타임의 프로세스·배포·장애 표면을 늘린다"며
FastAPI가 로컬 HTML/CSS/JavaScript 자산을 직접 제공하도록 결정했고, 실제
구현이 그 길로 갔다. 저장소에 `package.json`도 번들러도 없고 `/dashboard`는
손으로 쓴 ES 모듈을 서빙한다. 그런데 **D-7의 Status가 Accepted로 남아 있어
두 Accepted ADR이 서로 모순**이고, 어느 쪽이 유효한지 문서만 보고는 알 수
없다. D-72 이행 계획이 이 모순 위에서 레이아웃과 렌더러를 손보게 되는데,
D-7을 나중에 이행하면 그 산출물이 폐기된다.

**Decision:** D-7을 Superseded로 표시하고, 로봇 로컬 화면은 **빌드 단계 없는
손으로 쓴 정적 자산**임을 확정한다.

- `rosy_core`가 `web/`의 HTML·CSS·ES 모듈을 직접 서빙한다(D-23).
- 번들러·npm·Node 런타임·외부 CDN·웹폰트를 도입하지 않는다.
- 전송 경량화는 빌드가 아니라 응답 압축으로 한다.
- 색의 단일 출처는 `web/tokens.css`이며 계약 시험이 지킨다(D-72).

**Alternatives:** D-7을 이행해 Vite로 전환하는 안은 Pi 5 로봇 보드에 빌드
파이프라인과 배포 산출물 검증을 새로 얹고 D-23이 줄인 장애 표면을 되돌린다.
두 ADR을 그대로 두는 안은 모순을 남겨 다음 사람이 같은 질문을 다시 한다.

**Consequences:** 프론트엔드 작업은 빌드 산출물이 아니라 소스가 곧 배포물이라는
전제로 한다. 손으로 쓴 자산이므로 규율은 도구가 아니라 계약 시험이 만든다.
React 도입이 필요해지면 이 ADR을 먼저 뒤집어야 하며, 그때 Pi 이미지·서명·
digest 경로를 함께 설계한다.

**Validation / Transition:** `src/rosy_core/test/test_dashboard_no_bundler.py`.
`package.json`/`vite.config.*` 없음. `/dashboard` allowlist는 `api/app.py`.
색 단일 출처는 D-72 시험이 맡는다.

**References:** D-7, D-22, D-23, D-72,
[concept 16](../concept/16_ROSY_Interface_Design_Principles.md),
[이행 설계](../plans/2026-09-17-interface-design-implementation-design.md).
---

## D-76 501 본문의 capability는 CAP-001이고 concept_id는 부가다

**Status:** Accepted (2026-09-17). D-68 잔여. 에러 코드와 CAP-001 feature 필드는 유지한다.

**Context:** TaskKind는 개념 id(mobility.move)를 알고, 501은 CAP-001 플래그(	eleop)만 말한다. 클라이언트가 inventory descriptors와 에러 본문을 맞추려면 concept_id가 필요하지만, feature를 바꾸면 CAP-003 계약이 깨진다.

**Decision:** CapabilityError.feature는 CAP-001 dotted flag로 남고 501 detail.capability도 그대로다. TaskKind.require()가 실패하면 detail.concept_id를 부가한다. slam 등 TaskKind가 아닌 require()는 concept_id를 넣지 않는다. SAFE_STOP에서 거절은 계속 safety/e-stop이지 501이 아니다.

**Alternatives:** feature를 개념 id로 교체하는 안은 기존 501 소비자를 깨뜨린다. 채택하지 않는다.

**Consequences:** 조회는 inventory descriptors, 게이트는 CAP-001, 에러는 둘 다 담는다.

**Validation / Transition:** 	est_taskkind_require_keeps_cap001_flag_and_adds_concept_id, 	est_disabled_navigation_capabilities_return_501의 concept_id 단언.

**References:** D-11, D-32, D-68, D-74.

---

## D-77 운용자 콘솔은 CORE `/dashboard` 하나다

**Status:** Accepted (2026-09-17). D-72 S8. concept 16 §2.

**Context:** D-72가 남긴 질문이다. 운용자가 "이 로봇 괜찮나"에 답이 둘이다 —
`rosy_core` FastAPI `/dashboard`와 `rosy_control` `web_node`가 서빙하는
`dashboard.html`. 선택지는 셋이었다. (a) CSP nonce로 control 단일 파일을
자족 콘솔로 유지. (b) `dashboard.html`을 분해해 CORE 자산에 편입.
(c) 서버 둘을 유지. (a)와 (b)는 ROS-SIM·DEVICE 게이트와 두 맵 파이프라인
(S2), 그리고 `web_node`의 `/cmd_vel_raw` 발행(D-38)을 건드린다.

운용 compose(`deploy/robot/compose.yaml`)는 이미 `rosy_control/launch`를
띄우지 않는다. device-validation 계획 §1은 `robot.launch.py`를 CORE와 함께
돌리지 말라고 적는다. 그런데 문서와 control 페이지 제목은 둘을 같은 콘솔로
부르고 있었다.

**Decision:** v1 운용자 콘솔은 **CORE `/dashboard` 하나**다 (D-23, D-75).

- (c)를 고르되, 두 *운용자* 콘솔이 아니라 역할이 다른 두 HTTP 표면이다.
- `rosy_control` `web_node`+`dashboard.html`은 흡수된 IO 스택의 진단 화면이다.
  레거시 `robot.launch.py`에서만 뜬다. CORE와 같이 올리지 않는다.
- (a)는 기각한다. 두 번째 운용자 콘솔을 자족적으로 만들면 같은 질문에 답이
  둘로 남는다.
- (b)는 DEVICE 전까지 미룬다. CORE `map.js`와 control `/map.png`는 별개
  파이프라인이고, `web_node` teleop은 `cmd_vel_raw`를 낸다. 합치면 D-38과
  S2 경계를 한 번에 연다.

**Alternatives:** (a)는 답이 둘인 문제를 남긴다. (b)를 지금 하는 안은
맵 파이프라인과 명령 경로를 DEVICE 증거 없이 합친다. 둘 다 채택하지 않는다.

**Consequences:** "이 로봇 괜찮나"의 운용자 답은 `/dashboard`다. control
진단 화면은 레거시 런치에 남고, 교차 패키지 토큰 시험은 여전히 D-73 거처가
없다(concept 16 §6). 이 결정이 DEVICE/ARTIFACT GO가 아니다.

**Validation / Transition:** `test/test_control_launch_boundary.py` —
compose에 `web_node`/`dashboard.html`/`rosy_control/launch`가 없다.
concept 16 §2 표면 표. HOST 시험이지 Device viewport가 아니다.

**References:** D-23, D-38, D-72, D-73, D-75,
[concept 16](../concept/16_ROSY_Interface_Design_Principles.md),
[device-validation](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-78 ARTIFACT 빌더는 네이티브 ARM64 Pi다

**Status:** Accepted (2026-09-17). 경로 결정이다. digest·서명·Pi 인수는 아직 HOLD.

**Context:** D-66 CORE 이미지(`rosy_control`/OpenCV 없음)의 ARTIFACT GO가 필요하다.
호스트 QEMU로 Hub `ros:jazzy-ros-base` linux/arm64를 빌드하면 CPython/colcon/
gcc가 0바이트인 hollow 레이어에서 죽었다. `ac81f2f` core/io digest는 D-66 이전이라
재사용할 수 없다. 그런데도 ARTIFACT를 호스트에서 닫으려는 시도가 반복된다.

**Decision:** ARTIFACT의 1순위 빌더는 **네이티브 linux/arm64 Pi**다.

- 호스트 QEMU 성공은 ARTIFACT GO가 아니다.
- Hub `jazzy-ros-base` arm64 현재 태그를 QEMU로 다시 돌리지 않는다.
- D-66 이전 digest는 재사용하지 않는다.
- 실행 순서는 [native Pi 계획](../plans/2026-09-17-arm64-artifact-native-pi-plan.md).

**Alternatives:** 건강한 과거 Hub digest를 QEMU에 핀하는 안은 우회일 뿐 1순위가
아니다. Windows 호스트 pytest로 ARTIFACT를 대체하는 안은 계층을 속인다.

**Consequences:** 이 호스트에서 ARM64 이미지가 없어도 미들웨어 ADR은 진행한다.
ARTIFACT/DEVICE는 deploy·rosy_core gate가 HOLD로 남는다. 이 결정이 이미지를
만들지 않는다.

**Validation / Transition:** `docs/deployment/arm64-build-notes.md`의 QEMU HOLD
기록. native Pi에서 `uname -m` = aarch64 뒤에 core 타깃 빌드. 호스트
`test/test_restore_hollow.py`는 restore 스크립트 가드이지 ARTIFACT GO가 아니다.

**References:** D-36, D-46, D-53, D-66,
[device-validation](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md),
[native Pi 계획](../plans/2026-09-17-arm64-artifact-native-pi-plan.md).

---

## D-79 게이트 GO는 현재 트리 재실행만 인정한다

**Status:** Accepted (2026-09-17). D-61의 증거 규칙이다.

**Context:** device-validation 계획 §1 표는 ROS-SIM을 `GO(기존 증거)`로 적는다.
같은 날 모듈 `progress.md`는 rosy_core ROS-SIM을 HOLD로 두고 "2026-09-13 이후
현재 트리로 재실행하지 않음"을 blocker로 적는다. 옛 GO 행을 그대로 쓰면 호스트
pytest나 지난 컨테이너 한 번이 Device 앞 계층을 닫은 것처럼 보인다.

**Decision:** 모듈 게이트 GO는 **그 모듈 `progress.md`가 가리키는 명령의 현재
트리 재실행**만 인정한다.

- 계획 문서의 옛 GO 행은 대체 증거가 아니다. 충돌하면 progress가 이긴다.
- 재실행하지 않은 과거 결과는 HOLD(blocker: 재실행 필요)다.
- 상위 계층 결과로 하위 계층을 GO로 쓰지 않는다(호스트 pytest ≠ Device).

**Alternatives:** 계획 표만 믿는 안은 지금 모순이다. 모든 옛 증거를 삭제하는 안은
역사를 지운다. 채택하지 않는다.

**Consequences:** rosy_core/control/nav ROS-SIM은 현재 트리 재실행 전까지 HOLD다.
device-validation §1 ROS-SIM 칸은 이 결정을 따른다. ARTIFACT/DEVICE는 변하지
않는다.

**Validation / Transition:** `STATUS.md` HOLD blockers. `tools/harness` lint가
`GO`에 evidence·cmd를 요구한다. 계획 §1 표의 ROS-SIM 행을 HOLD로 정정한다.

**References:** D-39, D-61,
[device-validation](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md),
[module harness](../plans/2026-09-15-module-harness-design.md).

---

## D-80 G4 GO는 Device 표면이다

**Status:** Accepted (2026-09-17). D-72 HOST 조각을 Device GO와 가른다.

**Context:** D-72 S3–S6이 `fresh`/`delayed`/`disconnected`/`unavailable`과 stale
teleop 차단을 HOST 시험으로 올렸다. G4 본문은 다섯 safety 상태, 나열된 Nav2
이름, 보정 상태기계, Device viewport 터치/키보드, 권한 경로의 Device 증거도
요구한다. HOST 조각만으로 G4를 닫으면 벤치 화면이 현장 화면이 된다.

**Decision:** G4 GO는 **Device viewport에서** 다음이 증빙될 때만이다.

- 다섯 상태 `NORMAL`/`LIMITED`/`HOLD`/`ESTOP_LATCHED`/`RECOVERY_PENDING` (G0/D-51)
- G4가 나열한 navigation 이름 또는 그에 대한 사상표
- 보정: check → prepare → confirm → progress → cancel/fail → save → apply
- 권한 경로와 세션 철회
- 지원 Device viewport의 터치·키보드

HOST 증거 4상태와 `/dashboard` 단일 콘솔(D-77)은 G4를 **이행 중이게** 하지
**닫지 않는다.** G4 행의 상태·증거는 device-validation 계획만 쓴다.

**Alternatives:** HOST pytest로 G4를 GO하는 안은 계층을 속인다. G4를 대시보드
색 계약으로 줄이는 안은 D-72가 이미 나눈 법을 다시 섞는다.

**Consequences:** G4는 HOLD. 다섯 상태 매핑은 D-51이 연다. 이 ADR이 보정 UI를
구현하지 않는다.

**Validation / Transition:** device-validation G4 HOST 단락. `test_evidence.py`,
`test_dashboard.py`는 HOST. Device viewport 시험은 아직 없다.

**References:** D-51, D-72, D-77,
[device-validation G4](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

---

## D-81 Fleet 콘솔 v1 gather는 CORE REST 폴링이다

**Status:** Accepted (2026-09-17). D-5 outbound WS를 뒤집지 않는다. 콘솔 v1
경로만 고정한다.

**Context:** D-5는 로봇이 Fleet에 outbound WS로 붙는다고 했다. D-59는 관제 PC의
한 Fleet 서버가 모은다고 했다. 지금 `rosy_fleet console`은 N대를 한 화면에 모으고
목표·취소를 내리지만, `hub --listen`과 CORE `FleetAgent` outbound는 없다. gather는
CORE REST 폴링이다. "Fleet 서버 미구현"과 "콘솔이 이미 있다"가 같이 적혀 혼선이
난다.

**Decision:** v1 콘솔의 gather는 **CORE REST 폴링**이다.

- `rosy_fleet hub --listen`과 `FleetAgent` outbound는 다음 단계다. 없어도 콘솔
  v1은 유효하다.
- D-5 outbound WS는 목표 경로로 남는다. 에이전트가 붙으면
  `FleetConsole.snapshot()` 출처만 바뀐다.
- Fleet은 최종 `cmd_vel` 소스가 아니다(D-38, D-59).
- 물리 대형 실측과 D-35 후보는 이 결정이 닫지 않는다.

**Alternatives:** 콘솔을 outbound 전까지 금지하는 안은 이미 있는 운용 화면을
지운다. REST 폴링을 D-5 대체로 승격하는 안은 로봇→Fleet 푸시를 포기한다.
채택하지 않는다.

**Consequences:** concept README의 "Fleet unimplemented"은 서버 소켓을 말하고
콘솔 v1을 말하지 않는다. sim bench Task 14와 D-35는 별도다.

**Validation / Transition:** `src/rosy_fleet/test` 콘솔 시험. 패키지 `rclpy`
금지(`test_boundaries.py`). hub listen 시험은 이 ADR이 요구하지 않는다.

**References:** D-5, D-12, D-20, D-38, D-59, D-70,
[site fabric](../plans/2026-09-14-site-middleware-role-fabric-design.md).

---

## D-82 팔레트는 OKLCH에서 생성하고 수치 게이트로 지킨다

**Status:** Accepted (2026-09-17). concept 16 §6, D-72 L1. 값 계약이지 Device GO가 아니다.

**Context:** D-72 S1은 `styles.css`의 원시 색 62곳을 `tokens.css`로 옮겼지만
**값은 그대로 두고 의미 배치를 S5로 미뤘다.** 옮기고 나서 값을 재 보니 팔레트가
결정이 아니라 누적이었다.

- 선언된 `--signal-*` 한 벌 외에 Tailwind 계열(`#fbbf24` `#f87171` `#6ee7b7`
  `#94a3b8`)과 세 번째 앰버(`rgba(244,186,84,·)`)가 같은 파일에 있었다.
- `정상 #c4db76`과 `주의 #f2c46d`는 HSL로 밝기 3pt 차이라 괜찮아 보였지만
  **지각 밝기 차는 0.009**다. HSL의 lightness는 지각 밝기가 아니다.
- 적록 색약(남성 약 8%) 시야에서 **`위험` 대 `주의`의 대비가 1.07:1**이다
  (`#d7e06e` 대 `#e2e58f`). 로봇 콘솔에서 주의와 위험이 구분되지 않는다.
  `위험`이 셋 중 가장 밝기까지 하다.

**Decision:** 팔레트를 손으로 고르지 않고 **OKLCH에서 생성**하고, 값이 지켜야
할 성질을 계약 시험(`src/rosy_core/test/test_palette_gates.py`)으로 고정한다.

- **경보는 둘이다.** 주의(H 76)와 위험(H 25). **정상은 색이 아니라 잉크다** —
  셋을 갈라 세우려다 셋 다 못 갈라내느니 둘을 확실히 갈라 놓는다.
- **위험은 글자가 아니라 채움이다.** 토큰에 요구되는 것은 '바탕 위에서 읽히는
  글자색'이 아니라 '잉크를 얹을 수 있는 면'이다(concept 16 Law 3).
- **밝기가 색상보다 먼저다.** 색상 차이는 색약·글레어·흑백에서 사라지고 밝기
  차이는 남는다. 주의와 위험은 지각 밝기로 0.30 떨어뜨린다.
- **색상 온도가 의미를 나른다.** status는 따뜻한 띠에만, series는 차가운 띠에만
  둔다. 화면에 따뜻한 것이 보이면 언제나 무언가 잘못된 것이다.
- **경로와 후보 경로는 확신도다.** 다른 종류가 아니라 확신도가 다른 같은
  것이므로 색상이 아니라 **밝기**로 인코딩한다(`--series-primary` /
  `--route-dim`). 덤으로 색약 시야에서 갈린다.
- **지도 래스터는 무채색이다.** 지형은 계열이 아니라 바탕이므로 채도를 쓰지
  않고 밝기만 단조 증가한다.
- **형태가 먼저 가르고 색은 두 번째다.** 실선·파선·채움으로 갈린 뒤 색이 붙는다.

**Alternatives:** 값을 그대로 두고 의미만 재배치하는 안은 색약 붕괴를 남긴다.
현대 팔레트(Radix 9, Tailwind 500)를 그대로 쓰는 안은 **모든 색상을 같은 밝기에
두어** 가족처럼 보이게 만드는데, 그 균일 밝기가 정확히 색약 분리를 파괴한다 —
측정 결과 색약 대비가 1.22:1까지 떨어졌다. 브랜드 액센트와 의미 인코딩은 다른
작업이고, 이 결정은 후자를 택한다.

**Consequences:** `tokens.css`는 생성물에 가깝다 — 값을 손으로 고치면 게이트가
잡는다. 새 신호 색을 추가하려면 채도·밝기·색약 대비를 먼저 통과시켜야 한다.
`--series-primary`(실선)와 `--series-goal`(채운 사각)은 색약 대비 1.25:1로
색만으로는 갈리지 않으며 **형태에 맡긴다** — sRGB 색역에서 차가운 색 셋을
밝기로 모두 떼어놓을 수 없고, 이 한계를 숨기지 않고 시험 본문에 적는다.
이 ADR은 **값만** 바꾼다. `--status-good-a*`처럼 장식으로 쓰이는 status 파생을
걷어내는 의미 재배치는 D-72 S5에 남아 있다.

`rosy_control`은 건드리지 않는다. concept 16 §6이 `dashboard.html ↔
map_raster.py`를 별개 파이프라인으로 두었고 D-77이 그 표면을 레거시 진단으로
내렸다.

**Validation / Transition:** `src/rosy_core/test/test_palette_gates.py` —
신호 색 채도 >= 0.133, 주의·위험 지각 밝기 차 >= 0.15와 색약 대비 >= 2.0,
위험 면 위 잉크 >= 4.5:1, 같은 형태 계열의 색약 대비 >= 1.5, status는 따뜻한
띠·series는 차가운 띠, 래스터 무채색·단조, 본문 대비 >= 4.5:1, 경보 색상 계열
둘 이하. 값을 손으로 고쳐 이 중 하나라도 깨면 실패한다.

**References:** [concept 16](../concept/16_ROSY_Interface_Design_Principles.md)
§6, D-23, D-72, D-73, D-75, D-77,
[이행 설계](../plans/2026-09-17-interface-design-implementation-design.md).

---

## D-83 ROS-SIM 최소 재실행 묶음

**Status:** Accepted (2026-09-17). D-79의 실행 목록이다. 이 묶음을 돌리기 전까지
ROS-SIM은 HOLD다.

**Context:** 모듈 progress가 ROS-SIM을 HOLD로 두고 명령이 서로 다르다. 어떤
세션은 `gz_multi`만, 어떤 세션은 Nav2 launch만 돌리고 GO를 주장한다. D-79는
현재 트리 재실행을 요구하지만 **무엇을** 재실행하는지는 비어 있었다.

**Decision:** ROS-SIM GO의 최소 묶음은 이것이다. 하나라도 빠지면 그 모듈은 HOLD.

1. `rosy_core` — Jazzy 컨테이너에서 ROS 출력·`cmd_vel` 단일 publisher 스모크
2. `rosy_control` — sensing/camera/planning 노드 그래프. `robot.launch.py`를
   CORE와 같이 띄우지 않는다(D-38, D-77)
3. `rosy_gz_sim` / `rosy_fleet` — `gz_multi robots:=2 mode:=nav core:=true`
   (Task 14). `relay_tx_hz`·HOLD 지연이 나와야 D-35 후보를 논한다
4. `rosy_navigation` / `rosy_bringup` — `hardware.launch.py` 또는 gz Nav2
   include. 호스트 `test_nav2_profile_limits.py`는 ROS-SIM이 아니다

이 Windows 호스트에서 이 묶음을 돌리지 않는다. 실행 장소는 ROS 2 Jazzy
컨테이너 또는 네이티브 Linux.

**Alternatives:** 모듈마다 제각각 스모크하는 안은 지금 혼선이다. 호스트 pytest로
ROS-SIM을 대체하는 안은 D-79를 어긴다.

**Consequences:** Fleet `hub --listen`과 Device G4는 이 묶음이 아니다.
ARTIFACT는 D-78.

**Validation / Transition:** 각 모듈 `progress.md` ROS-SIM blocker가 위 명령을
가리키게 한다. 재실행 증거 전에는 GO로 쓰지 않는다.

**References:** D-38, D-77, D-79,
[device-validation](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md),
[swarm bench](../plans/2026-09-08-swarm-formation-slice.md).

---

## D-84 hardware 장치 패키지는 hardware 프로필 전까지 CORE/io에 없다

**Status:** Accepted (2026-09-17). D-62 슬라이스 규칙의 장치 쪽이다.

**Context:** led / adc / lamp / emotion / `rosy_imu_bno055`는 패키지와 HOST
계약 시험이 있다. `deploy/robot/Dockerfile` core/io는 이들을 복사하지 않는다.
그런데도 이미지에 슬며시 넣으려는 수정이 반복된다. IMU 소스는 다른 커밋과
섞지 않기로 한 WIP다.

**Decision:** 이 다섯 패키지는 **hardware 프로필이 Device 증거로 열리기 전**에
`rosy-core` / `rosy-io` 이미지에 넣지 않는다.

- `test_io_image_packages_nav2_without_slam_or_aux_drivers`가 제외를 지킨다
- IMU 융합은 D-56 Proposed. `src/rosy_imu_bno055/**` 구현 WIP는 다른 주제
  커밋과 섞지 않는다
- HOST 계약 시험 GO는 이미지 편입이 아니다

**Alternatives:** 전부 io에 넣는 안은 Pi 이미지에 드라이버와 OpenCV를 다시
싣는다(D-66과 충돌). 패키지를 지우는 안은 Device 프로필을 막는다.

**Consequences:** ARTIFACT 기본 이미지는 CORE+io(+nav overlay)다. hardware
슬라이스는 G1/G0 증거가 있을 때 연다.

**Validation / Transition:** `test/test_nav2_hardware_slice.py` io 제외 단언.
Dockerfile core/io에 다섯 패키지 COPY가 생기면 이 ADR 위반이다.

**References:** D-56, D-57, D-62, D-66,
[optional slices](../plans/2026-09-16-optional-runtime-slices-design.md).

---

## D-85 도크 펌웨어 ARTIFACT는 ESP32 툴체인 증거다

**Status:** Accepted (2026-09-17).

**Context:** `dock/firmware/rosy_dock/rosy_dock.ino`는 참조 구현이다. HOST
pytest(`test_dock_contract.py`)는 README와 파서 계약만 본다. ESP32 툴체인이
없는 Windows에서 펌웨어 빌드 없이 ARTIFACT GO를 쓰려는 시도가 있다.

**Decision:** 도크 ARTIFACT GO는 **Arduino/ESP32 빌드·플래시 readback**이 있을
때만이다. HOST 계약 시험은 SOURCE/LOCAL이다. 툴체인 없는 호스트는 HOLD다.
물리 벤치 통전은 DEVICE다.

**Alternatives:** `.ino` 존재만으로 ARTIFACT를 닫는 안은 계층을 속인다.

**Consequences:** `dock` SOURCE/LOCAL GO는 펌웨어 발행이 아니다.

**Validation / Transition:** `dock/progress.md` ARTIFACT blocker. HOST
`test/test_dock_contract.py`.

**References:** D-27, D-28, D-36, D-79.

---

## D-86 POSIX identity 시험은 POSIX 호스트에서만 deploy를 찍는다

**Status:** Accepted (2026-09-17). D-79의 deploy 예외다.

**Context:** `test_dds_identity_contracts.py`는 Git Bash로 `lib.sh`를 소스로
한다. 이 Windows 세션은 임시 경로(`X:\DevTemp\...`)를 bash가 읽지 못해 13건이
실패했다. 그 실패로 deploy SOURCE를 HOLD로 내리면 호스트 계약이 있는 다른
시험까지 같이 무너진다. 반대로 실패한 채로 last_verified를 찍으면 D-79를
어긴다.

**Decision:** `require_robot_identity` bash 시험은 **POSIX(Git Bash가 `/` 임시
경로를 쓰는 환경, 또는 Linux)** 에서만 deploy `last_verified`를 채운다.
Windows에서 이 시험이 깨져도 deploy SOURCE GO(다른 계약)를 뒤집지 않는다.
다만 **그 호스트에서는 last_verified를 비운다.**

**Alternatives:** Windows 실패를 SOURCE HOLD로 쓰는 안은 계약 시험을 환경
결함과 섞는다. 실패를 무시하고 SHA를 찍는 안은 D-79 위반이다.

**Consequences:** STATUS.md deploy 행의 `uncommitted`는 이 결정이다. Linux CI
또는 Git Bash가 통과하면 그때 SHA를 넣는다.

**Validation / Transition:** `test/test_dds_identity_contracts.py`.
`deploy/progress.md` last_verified.

**References:** D-33, D-61, D-79.

---

## D-87 ROS-SIM은 그 트리의 colcon install이 있을 때만 시작한다

**Status:** Accepted (2026-09-17). D-83의 전제다.

**Context:** WSL에 `/opt/ros/jazzy`와 `rclpy`가 있다. 워크스페이스
`install/setup.bash`는 없다. 그 상태에서 `ros2 --help`나 호스트 pytest로
ROS-SIM을 닫으려는 시도가 있다. x86 WSL colcon은 편하지만 D-78 ARTIFACT
경로(네이티브 Pi)와 섞이기 쉽다.

**Decision:** D-83 묶음은 **그 커밋이 가리키는 트리에서 colcon으로 만든
`install/setup.bash`가 있는 Linux**에서만 시작한다.

- Jazzy가 깔려 있기만 한 WSL은 전제가 아니다
- Windows 호스트 pytest는 ROS-SIM이 아니다 (D-79)
- x86 워크스페이스 빌드가 성공해도 ARTIFACT GO가 아니다 (D-78)

**Alternatives:** `rclpy` import만으로 ROS-SIM GO는 계층을 속인다. 매번 소스
트리에서 `python`으로 노드를 띄우는 안은 install overlay와 다른 그래프가 된다.

**Consequences:** 지금 트리의 ROS-SIM은 HOLD. maze 로그는 역사이며 승격 증거가
아니다.

**Validation / Transition:** `test -f install/setup.bash` 뒤에 D-83 명령을
progress에 적는다. 그 전 GO는 이 ADR 위반이다.

**References:** D-78, D-79, D-83.

---

## D-88 Fleet 소켓은 사이트 PC 산출물이며 D-83 뒤에 연다

**Status:** Accepted (2026-09-17). D-81의 다음 단계 순서다.

**Context:** 콘솔 v1 gather는 CORE REST다 (D-81). 경로 충돌 대기열도 REST
위에 있다. `rosy_fleet hub --listen`과 CORE `FleetAgent` outbound는 아직 없다.
이것을 로봇 이미지에 넣거나, Task 14 없이 소켓을 열면 사이트 버스와 로봇
런타임이 다시 섞인다 (D-59).

**Decision:**

- `hub --listen`과 `FleetAgent`는 **관제 PC 산출물**이다. `rosy-core` /
  `rosy-io` 이미지에 넣지 않는다
- D-83 `gz_multi robots:=2 mode:=nav core:=true` 증거가 커밋된 트리에서
  다시 나오기 전에는 소켓을 열지 않는다
- REST 콘솔과 경로 대기열은 그 전에도 유효하다 (D-81)

**Alternatives:** 소켓을 로봇에 올리는 안은 D-59 위반이다. REST를 버리고 소켓만
쓰는 안은 콘솔 v1을 멈춘다.

**Consequences:** Fleet ARTIFACT/DEVICE는 PARKED. 로봇 이미지 대상이 아니다.

**Validation / Transition:** `src/rosy_fleet/progress.md`. Dockerfile에
`rosy_fleet hub` COPY가 생기면 이 ADR 위반이다. `test_runtime_slices.py`가
core에 fleet 서버가 없음을 이미 본다.

**References:** D-5, D-12, D-59, D-81, D-83.

---

## D-89 D-35 대형 후보는 D-83 Task 14 재실행 전에는 열지 않는다

**Status:** Accepted (2026-09-17).

**Context:** D-35는 대형 HOLD 실측 대기다. maze/`slam_nav` 로그에 두 대 주행이
있으나 D-79가 말하는 현재 트리 재실행이 아니다. 그 로그로 D-35를 열면 옛
증거가 게이트를 닫는다.

**Decision:** D-35 후보(relay Hz, HOLD 지연, 대형 기하)는 **D-83 항목 3
(`gz_multi robots:=2 mode:=nav core:=true`)을 현재 트리에서 재실행한 기록**이
있을 때만 연다. 그 전 로그는 설계 입력이지 GO가 아니다.

**Alternatives:** 호스트 pytest로 대형을 닫는 안은 그래프가 없다. 옛 WSL 로그로
D-35를 Accepted 하는 안은 D-79 위반이다.

**Consequences:** D-35는 결번/HOLD로 남는다. Fleet 콘솔 대기열 시험은 대형
실측이 아니다.

**Validation / Transition:** D-35 본문을 고치기 전에 D-83 항목 3의 progress
증거를 요구한다.

**References:** D-35, D-79, D-83,
[swarm bench](../plans/2026-09-08-swarm-formation-slice.md).

---

## D-90 축구는 게임 호스트이지 CORE 모드가 아니다

**Status:** Accepted (2026-09-17). 방향 결정이다. 현장 1v1 GO가 아니다.

**Context:** Pinky 두 대로 차체 푸시볼 1v1을 하고 싶다. CORE에 `SOCCER` 모드를
넣으면 게임 규칙·공 좌표·두 대 중재가 로봇 안에 들어가고, 최종 `cmd_vel`과
OpenCV가 다시 CORE 이미지로 돌아온다 (D-38, D-66). 앞 카메라는 320×240 장애물용이지
공 추적이 아니다.

**Decision:** 축구는 기존 `IDLE`/`MANUAL`/`NAVIGATION`/`DOCKING`/`EMERGENCY` 위에
얹는 **노트북 게임 호스트**다.

- `RobotMode.SOCCER` 없음. CORE는 게임을 import하지 않는다
- 1단계는 천장 카메라 + 호스트가 양쪽 CORE teleop (`MANUAL`, SAF-002 워치독)
- 호스트는 최종 `cmd_vel`을 발행하지 않는다
- 코드는 `src/rosy_games`에 산다. `rosy-core`/`rosy-io`에 OpenCV를 넣지 않는다
- DEVICE/FIELD HOLD인 동안 서로 박는 속도의 경기를 GO로 적지 않는다
- 온보드 시야(2단계)는 1단계가 여러 번 반복되기 전에 열지 않는다

설계 본문: [robot soccer game host](../plans/2026-09-17-robot-soccer-game-host-design.md).

**Amendment (2026-09-17):** 경기의 집은 `rosy_games`다. Fleet은 로봇 통로(명단·토큰·일괄
stop)이고 Isaac은 나중에 붙는 시뮬/학습 어댑터다. 축구를 `rosy_fleet` 안에 넣지 않고,
D-62 카탈로그에도 올리지 않는다. `game` 모듈은 `cv2`/Isaac을 모른다. 시작 경로
`tools/soccer/`는 이 패키지 트리로 대체한다. 심판을 Fleet 서버로 “옮긴다”는 문장은
매치 시작 버튼의 자리이지, 규칙 엔진의 이사가 아니다.

**Alternatives:** CORE 모드로 넣는 안은 미들웨어를 게임으로 만든다. Nav2로 공을
쫓는 안은 공을 장애물로 만들고 너무 느리다. Fleet 안에 넣는 안은 관제 패키지가
규칙·RL·Isaac 의존을 떠안는다. Isaac이 경기를 소유하는 안은 학습에는 유리하고
Isaac 없는 실기 1v1을 늦춘다.

**Consequences:** 1단계 실패는 호스트 정책 문제이지 CORE 계약 위반이 아니다.
Fleet 콘솔은 매치를 켤 수 있다. `reset()`은 `rosy_games`가 한다 (D-12, D-88).

**Validation / Transition:** `RobotMode`에 `SOCCER`가 없다.
`src/rosy_core/test/test_protocol_schemas.py`. 구현은 별도.

**References:** D-1, D-2, D-12, D-33, D-38, D-59, D-62, D-66, D-88.

---

## D-91 Device 비교 ADR은 호스트 pytest로 Accepted 하지 않는다

**Status:** Accepted (2026-09-17). D-79의 Device 쪽 적용이다.

**Context:** D-41·D-42·D-43·D-44·D-51·D-52는 본문이 ARM64 캡처, shadow 핸드오프,
보정 generation, OMX 실물, 다섯 safety 상태 실측을 요구한다. 호스트 pytest가
초록이면 이 여섯을 Accepted로 올리려는 시도가 반복된다.

**Decision:** 아래 ADR은 **각 본문의 Validation 측정이 Device/ARM64에 있을 때까지
Proposed**로 남는다.

| ADR | 열기 전에 필요한 증거 |
|---|---|
| D-41 | ARM64 캡처 위치 비교 (호스트 vs 최소권한 컨테이너) |
| D-42 | 50 Hz 예산에서 후보·안전 상관 실측 |
| D-43 | generation 격리 보정 쓰기·rollback |
| D-44 | Nav2 vs ControlBackend 실 시나리오, OMX 실물 interlock |
| D-51 | Pinky 프로필의 다섯 상태 행렬 + 바퀴 든 시험 |
| D-52 | ARM64 카메라 spike + shadow, 두 번째 실 publisher 없음 |

D-54·D-55·D-56은 소스/아키텍처 게이트만 Accepted이며 필드·payload·융합 승격은
HOLD다.

**Alternatives:** 여섯을 지금 Accepted 하는 안은 Validation을 지운다. 전부
Proposed로 남겨 D-54까지 묶는 안은 이미 닫힌 설정 게이트를 다시 연다.

**Consequences:** 다음 세션이 "나머지 ADR 처리"여도 D-41을 호스트에서 닫지 않는다.

**Validation / Transition:** 색인 Status가 Proposed인 여섯 ID. 호스트
`test_nav2_profile_limits.py` 통과는 D-54이지 D-51이 아니다.

**References:** D-79, D-80, D-87,
[device-validation](../plans/2026-09-13-rosy-os-device-validation-implementation-plan.md).

## D-92 L2 컴포넌트는 파일이 아니라 어휘 표로 공유한다

**Status:** Accepted (2026-09-18). concept 16 §4의 v1 적용이며 D-72·D-82를 잇는다.

**Context:** `/dashboard`가 "카드 더미"로 읽힌 원인은 색이 아니라 구조였다.
`styles.css`는 카드 기반 원본 위에 콘솔 패치를 열다섯 겹 얹은 형태였고, 덮어쓰기는
원본을 이기는 척만 했다 — `.region .panel { border: 0 }`으로 카드를 지워도 원본의
카드 여백·리듬·타이포가 계속 밀고 올라와 패치가 한 겹씩 늘었다. 제목도 세 층(영역
머리·패널 제목·소제목)이어서 화면이 목차로 읽혔다.

그 과정에서 표면 스타일시트가 `--ink`·`--line`·`--signal-*` 여덟 개의 **별칭 토큰**을
자체 선언하고 있었다. 단일 출처를 선언해 놓고 그 옆에 두 번째 어휘를 세운 것이며,
값 게이트는 전부 토큰 이름을 보므로 별칭 쪽은 아무도 검사하지 않았다.

다음 단계로 "나머지 컴포넌트를 미리 만들자"는 요구가 자연스럽게 나온다. 그 요구의
기본 형태는 네 표면이 함께 쓰는 컴포넌트 라이브러리인데, concept 16 §4는 그것을
**목표가 아니라 결함**으로 규정한다: Fleet이 콘솔처럼 보이게 되고 LCD는 불가능해진다.

**Decision:**

1. 파일로 공유하는 것은 **L1뿐**이다 — `rosy_core/web/tokens.css`. 표면 사이에 CSS나
   컴포넌트를 import 하지 않는다. `rosy_fleet`, `rosy_emotion`은 각자의 L2를 각자 쓴다.
2. 공유되는 것은 **어휘와 그 규칙**이고 아래 표가 그 목록이다. 같은 이름의 컴포넌트를
   표면마다 자기 문법으로 구현한다 — 이름이 같으면 대화가 되고, 구현까지 같으면
   문법이 무너진다.
3. 콘솔 L2 어휘는 열 개로 닫는다. 새 컴포넌트를 늘리기 전에 이 표에 이름과 규칙을
   먼저 쓴다.

| 컴포넌트 | 규칙 | 지키는 게이트 |
|---|---|---|
| 라벨 | 작은 대문자. `--text-micro` + `--track-label` + `--nominal-quiet`. 값이 아니라 값의 이름이다 | `test_type_sizes_come_from_the_scale` |
| 값 | 등폭 + `tabular-nums`. 넘치면 자르지 않고 접는다 — 잘린 좌표는 좌표가 아니다 | `test_console_layout.py` |
| 묶음 제목 줄 | 라벨 + 이어지는 1px 실선 + 오른쪽 끝 기계 값. 상자를 만들지 않는다 | 없음 — 규칙만. 배치 실측(Playwright)이 간접 증거다 |
| 값 격자 | `gap: 1px` 실선 격자. 칸마다 테두리·모서리를 주면 작은 카드가 여섯 개가 된다 | `test_spacing_comes_from_the_step_scale` |
| 버튼 셋 | 주(가장 밝은 중립) · 조용(테두리 하나) · 되돌릴 수 없는 것(채운 면 + 잉크, 58px) | `test_irreversible_actions_are_a_fill_not_text`, `test_a_danger_fill_carries_ink_not_dark_text` |
| 필드 | 파인 면. 44px 바닥, 포커스는 `--focus-ring`(상태색 아님) | `test_touch_targets_clear_the_floor`, `test_focus_is_interaction_not_status` |
| 태그 | 상태 어휘는 중립·주의·위험 셋뿐. 뱃지·기계 태그·모드 칩·`[data-status]`·이벤트 심각도가 **같은 셋**을 쓴다 | `test_nominal_carries_no_colour` |
| 오버레이 칩 | 지도 위에 얹는 것은 전부 `--scrim` 바탕 + `--surface-line` 테두리 | `test_the_map_controls_ride_on_the_map_instead_of_stealing_its_height` |
| 분류 머리 | 한 줄. 색을 가진 것은 언제나 하나이고 맥락은 색 없이 따라간다 | `test_triage_contract.py` |
| 증거·빈 상태 | `fresh`에는 아무것도 붙이지 않는다. `delayed`·`disconnected`·`unavailable`만 표시한다 | `test_evidence_margin.py` |

4. 표면 스타일시트는 토큰을 **선언하지 않는다**. 간격은 `--space-*`, 글자는
   `--text-*`에서만 온다. 별칭 층을 다시 세우는 것은 게이트가 막는다.
5. 아직 없는 넷은 **설계만 적고 만들지 않는다**. 쓰이지 않는 컴포넌트는 결함을
   숨기기 때문이다 — 실제로 치수 토큰 13개가 사용처 0이었고, 채택하자마자 44px
   미만 터치 타겟 다섯이 드러났다. 구현이 필요해질 때 아래 문단이 시작점이다.

   **(a) 되돌릴 수 없는 조작의 확인.** 지금은 `window.confirm()`이다(`map.js`의 목표·
   초기 자세 전송). 브라우저 대화상자라 Law 3의 "종류가 다르다"를 표현하지 못하고,
   타겟 바닥도 색 규칙도 적용되지 않으며 문구가 OS 언어를 탄다. 설계: 확인은 모달이
   아니라 **조작이 있던 자리**에서 일어난다 — 그 버튼이 두 단계가 된다. 1단계는
   무엇이 일어나는지와 되돌릴 수 있는지를 말하고 2단계가 실행이다. 새 색을 쓰지
   않는다(크기와 면이 이미 종류를 말한다). 무응답은 취소이며 자동으로 1단계로
   돌아간다.

   **(b) Fleet 예외 행.** 기본 화면에는 주의가 필요한 로봇만 있다(§7.3). 콘솔의 값
   격자를 그대로 가져오면 안 된다 — Fleet의 한 줄은 값이 아니라 **로봇 하나**이고,
   정렬 축은 심각도가 아니라 운용자가 지금 할 수 있는 일이다. `triage.js`의
   `CATEGORY_ORDER`를 계약으로 공유하되 **코드가 아니라 이 표로** 공유한다(D-73).
   색 예산이 가장 빡빡한 표면이므로 스무 대 중 한 대가 문제면 색 있는 줄은 하나다.

   **(c) 좁은 화면의 콘솔.** 1080px 이하에서도 영역 셋의 **자리는 바꾸지 않는다** —
   레일 폭만 좁힌다. 조작을 아래 줄로 돌려 봤더니 그 칸이 제 내용만큼 412px를
   가져가 지도가 37px로 눌렸고, 공간 문법을 버리고 얻은 것이 없었다. 720px 이하는
   고정 프레임이라는 전제 자체가 없는 화면이므로 세로로 쌓고 스크롤을 허용한다.

   **(d) face intent.** 1.5 m에서 0.5초, 글을 읽지 않고(§7.4). 이 표의 어휘를
   적용하지 **않는다** — 라벨·격자·태그는 전부 읽기를 전제한다. 두 번째 서체가
   정당화되는 유일한 표면이다.

**Alternatives:** 공용 `components.css`를 `rosy_core`가 배포하고 Fleet이 가져다 쓰는
안은 concept 16 §4가 결함으로 규정한 것이고, D-75 아래서는 Fleet 서버가 `rosy_core`
자산을 서빙해야 해서 모듈 경계도 넘는다(D-73). 넷을 지금 다 만드는 안은 쓰이지 않는
컴포넌트를 늘린다. 어휘를 문서화하지 않는 안은 다음 표면이 색부터 다시 고르게 하고,
그게 D-82 이전 상태다.

**Consequences:** `rosy_fleet`은 `rosy_core`의 CSS를 import 하지 않는다. 공유되는 것은
L1 **값**뿐이고 그 동기화는 각 모듈이 자기 시험으로 지킨다(D-73,
`src/rosy_fleet/test/test_console_palette.py`). 새 컴포넌트는 코드보다 이 표가 먼저다.

**Validation / Transition:** `test_ui_token_contracts.py` — 표면 시트의 토큰 선언 0,
간격은 `--space-*`, 글자는 `--text-*`. 다시쓰기 전 시트에 걸면 별칭 8개 · 계단 밖
간격 118곳(값 53가지) · 계단 밖 글자 95곳(68가지)이 잡힌다. `test_console_layout.py`
9건. Playwright 실측 1280×720에서 지도 469px, `pageScroll` 0. 위 (a)~(d)는 **설계만**
있고 코드가 없다 — 구현 전에는 이 ADR의 문단이 유일한 계약이다.

**References:** concept 16 §4·§7·§10, D-23, D-72, D-73, D-75, D-77, D-82,
커밋 `dc44d4a`·`70a3e53`.

---

## D-93 마주 오는 두 대는 폭으로 풀리지 않는다 — 교행은 Fleet이 중재한다

**Status:** Accepted (2026-09-18).

**Context:** `rosy_fleet/server/bays.py`는 "이 통로는 충분히 넓으니 Fleet이 빠져도
된다"는 면제 기준 `PASSING_WIDTH_M`을 들고 있었다. 처음 값 1.2는 데이터 두 점으로
찍은 것이고, 1.4는 스윕 한 번으로 올린 것이다. 둘 다 근거가 약했다.

핑키 프로는 **폭 0.111 m**다(충돌 메시 실측: 몸통 0.113 x 0.088, 바퀴 바깥
0.0961 + 0.015). 두 대를 나란히 세우면 0.222 m, nav2 풋프린트(반폭 0.06 + 패딩
0.03)로 쳐도 0.36 m면 벽-A-B-벽이 닿는다. 1.4 m는 로봇 폭의 **12.6배**이고, 크기로는
설명되지 않는 숫자였다.

폭만 다른 통로 여섯(1.4/1.2/1.0/0.9/0.8/0.7 m)을 나란히 둔 `rosy_gauntlet.world`로
실측했다.

| 시험 | 1.4 m | 1.2 m | 1.0 m | 0.9 m | 0.8 m | 0.7 m |
|---|---|---|---|---|---|---|
| 자리 맞바꾸기, 팽창 0.15 | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| 자리 맞바꾸기, 팽창 0.08 | PASS | FAIL | FAIL | FAIL | FAIL | FAIL |
| **순수 교행**, 팽창 0.15 | **FAIL** | FAIL | FAIL | FAIL | — | FAIL |

그리고 `rosy_swarm_bench.world`의 **6 x 6 m 빈 방**에서 마주 오는 두 대를 서로
너머로 보내면 **0/3**이다. 세 번 다 방 한가운데에서 0.13~0.17 m 간격으로 맞물려
섰다. 로봇 폭의 54배 공간이다.

원인은 공간이 아니라 컨트롤러다. RPP는 옆으로 피하지 않는다 — 앞에 충돌이 보이면
선다(`RegulatedPurePursuitController detected collision ahead` 2943회). 전역 플래너가
우회를 내도 두 대가 대칭이라 같은 쪽으로 돌고 거기서 다시 만난다. 팽창을 0.15에서
0.08로 줄여도 결과가 같은 이유가 그것이다.

앞선 1.4 m PASS는 두 가지가 겹친 결과였다. (1) 그 시험은 교행이 아니라 **자리
맞바꾸기**였다 — 각 로봇의 목표가 상대가 선 좌표였고, D-93 이전에 장애물 레이어를
고친 뒤로 그 칸은 치명 비용이라 상대가 비켜야만 도착이 성립한다. (2) 단일 시행이었고
같은 폭의 순수 교행은 실패한다.

**Decision:** **통로 폭은 Fleet 중재의 면제 사유가 아니다.** 어떤 폭에서도 마주 오는
두 대가 스스로 지나간다고 가정하지 않는다.

- `PASSING_WIDTH_M`과 그것을 쓰는 면제 분기를 없앤다. 서 있는 로봇이 미션 경로의
  `YIELD_KEEP_OUT_M` 안에 있으면 폭을 묻지 않고 비켜설 자리를 찾는다
- 넓은 곳에서 쓸데없이 비켜서는 것을 막는 장치는 **폭이 아니라 경로**다. 계획 경로는
  이미 아는 장애물을 피해 나온다. 그런데도 경로가 선 로봇 0.45 m 안을 지난다면 그것은
  돌아갈 자리가 없거나 계획 시점에 그 로봇이 코스트맵에 없었다는 뜻이고, 둘 다 중재가
  필요한 경우다
- 자유 폭 계산(`free_width_at`)은 남긴다. 비켜설 자리가 로봇이 설 만큼 넓은지 보는 데
  쓰이며, 그쪽은 정적 기하라 실측과 맞는다

**Alternatives:** 폭 기준을 더 크게(예: 2.0 m) 잡는 안은 6 x 6 m 빈 방 0/3이 부정한다 —
면제가 성립하는 폭이 없다. 컨트롤러를 DWB로 바꿔 측면 회피를 얻는 안은 실제 해법일 수
있으나 항법 전체의 거동이 바뀌므로 이 ADR의 범위가 아니다(후속). 실패를 그대로 두고
로봇이 서로 막게 하는 안은 D-12가 Fleet에 준 책임을 버리는 것이다.

**Consequences:** 관제는 좁은 통로에서 더 자주 개입한다. 그것이 옳다 — 개입하지 않으면
두 대가 선다. 비켜설 자리가 없으면 `NO_YIELD_SPACE`로 사람을 부른다. 반대로 넓은
현장에서 과하게 개입할 위험은 경로 기준이 막는다.

**Validation / Transition:** `src/rosy_fleet/test/test_server_bays.py`,
`test_server_yield.py` — 폭이 넓어도 경로 위에 선 로봇은 비켜선다는 시험. 실환경:
`rosy_factory.world` 폭 0.85 m 통로에서 두 대가 번갈아 물러나며 자리를 맞바꾸고(도착
오차 0.38/0.25 m, 최소 여유 0.17 m), `rosy_swarm_bench.world` 빈 방 교행은 중재 없이는
0/3이다. 후속으로 컨트롤러 교체(DWB)를 검토하면 이 ADR을 Superseded 한다.

**References:** D-12, D-20, D-59,
[site middleware role fabric](../plans/2026-09-14-site-middleware-role-fabric-design.md),
`src/rosy_navigation/logs.md` 2026-09-18 코스트맵 관측 토픽 수정,
`src/rosy_fleet/logs.md` 2026-09-18 양보 항목.

---

## D-94 rosy_games 천장 OpenCV는 노트북 호스트이며 D-41을 닫지 않는다

**Status:** Accepted (2026-09-18). D-90의 관측 경계다.

**Context:** `rosy_games/host/overhead.py`가 `cv2`를 import한다. D-66은 CORE 이미지에
OpenCV가 없다고 했고, D-41·D-52는 **로봇** ARM64에서 카메라 worker가 어디에 사는지
실측을 요구한다. 노트북 천장 웹캠 코드가 있으면 D-41을 Accepted로 올리려는 혼선이
생긴다.

**Decision:**

- `cv2`는 `rosy_games`의 `host/overhead.py`에만 산다. `field/homography.py`는 순수 기하
- CORE 생산 코드와 CORE 이미지는 OpenCV를 갖지 않는다 (D-66)
- 이 파일은 **관제 노트북 관측 어댑터**다. Pinky 앞 카메라·Picamera2·컨테이너
  배치(D-41, D-52)를 닫지 않는다
- LOCAL pytest는 overhead를 import하지 않고 통과해야 한다. 웹캠 실측은 DEVICE/FIELD

**Alternatives:** overhead를 rosy_control 카메라 worker로 합치는 안은 게임 호스트를
로봇 안에 넣는다 (D-90 위반). D-41을 이 코드로 닫는 안은 Validation 실측을 지운다
(D-91).

**Consequences:** 천장 1v1은 노트북에서만 켠다. 로봇 이미지에 `rosy_games`를 COPY하지
않는다.

**Validation / Transition:** `test/test_rosy_games_surface.py`,
`src/rosy_games/test/test_games_boundaries.py`. ADR 색인 D-41 Status는 Proposed.

**References:** D-41, D-52, D-66, D-90, D-91,
[overhead plan](../plans/2026-09-18-rosy-games-overhead-plan.md).

**Amendment (2026-09-18):** `test/test_overhead.py`는 cv2가 있을 때 `overhead.py`를
import해도 된다. 그건 합성 프레임 LOCAL이다. `test_rosy_games_surface.py`와
`test_games_boundaries.py`는 overhead를 로드하지 않는다. DEVICE는 여전히 실제 웹캠이다
(D-95).

---

## D-95 합성 천장 프레임은 DEVICE가 아니다 — 기본 observer는 hold

**Status:** Accepted (2026-09-18). D-91의 games 적용이다.

**Context:** `host/overhead.py`와 합성 ArUco 시험이 LOCAL에 있다. 그 통과를 현장
웹캠 GO로 읽으면 D-91을 우회한다. CLI가 기본으로 `/dev/video0`을 열면 pytest와
실기 실수가 같은 경로가 된다.

**Decision:**

- 합성 프레임·`test_overhead.py`는 LOCAL이다. DEVICE/FIELD로 승격하지 않는다
- 실기 CLI 기본 `--observer`는 `hold`다. 천장 카메라는 `--observer overhead`
- 실제 웹캠으로 구장·공·로봇이 보이는 기록만 D-96 계단 1이다

**Alternatives:** 기본을 overhead로 두는 안은 카메라 없는 호스트가 기동에 실패한다.
합성 통과를 DEVICE로 적는 안은 D-91 위반이다.

**Consequences:** `rosy_games match --config ...`는 카메라를 열지 않고 두 대를
HOLD teleop 0으로 무장한다.

**Validation / Transition:** `src/rosy_games/rosy_games/cli.py` 기본값 `hold`.
`progress.md` DEVICE/FIELD PARKED.

**References:** D-90, D-91, D-94.

---

## D-96 현장 축구 1v1은 다섯 계단이고 충돌 속도는 기기 안전 다음

**Status:** Accepted (2026-09-18). 방향이다. 현장 GO가 아니다.

**Context:** Pinky 프로필 최대 0.20 m/s다. Device 정지·워치독·단일 publisher가
그 기기에서 HOLD인 채 두 대가 공을 두고 달리면 설계 §5를 건너뛴다.

**Decision:** 현장 순서는 고정이다.

1. 모터 없음. `--observer overhead`로 구장·공·로봇·골 20/21(또는 입구 영역)이 보이는지 (D-100)
2. 한 대, `PUT /safety/limits` 0.08–0.10 m/s, 공 밀기 → 골 → HOLD
3. 두 대, 공 없이, 0.35 m 이내면 감속
4. 두 대 + 공, 같은 저속 1v1
5. 득점 후 사람 손 킥오프가 반복 가능한지

충돌 속도(프로필 0.20)는 그 기기의 정지·워치독 500 ms·`cmd_vel` publisher 1이
확인된 다음이다. 호스트 pytest로 이 계단을 건너뛰지 않는다.

**Alternatives:** 시뮬 좌표로 계단 4를 FIELD GO로 적는 안은 D-91이다. Nav2로 공을
쫓는 안은 D-90이 이미 거절했다.

**Consequences:** 사람이 호스트에서 스페이스(`safety/stop`)를 쥔다. 한 대만 뛰는
경기는 없다.

**Validation / Transition:** 설계 §8 현장 순서. `progress.md` FIELD PARKED until
계단 4 기록이 있다.

**References:** D-2, D-90, D-91, D-95, D-100, SAF-002, SAF-004.

**Amendment (2026-09-18):** 계단 1에 골 마커/영역을 넣는다. 피치는 코너 10–13, 골
위치는 20/21이다 (D-100).

**Amendment (2026-09-18):** 계단 1 호스트 스위치는 D-107 (`--observe-only`가
기본). `--drive`는 D-108. 이 두 플래그가 DEVICE 증거를 대신하지 않는다.

**Amendment (2026-09-18):** 첫 접촉 속도 상한은 D-110. 계단 프리셋은 D-111.
`--stair`와 pytest가 현장 GO가 아니다.

**Amendment (2026-09-18):** 계단 1 가시성 보고는 D-112. LOCAL 호스트 트랙 마감은
D-113. 웹캠·Pinky 실측이 남는다.

---

## D-97 온보드 축구 시야는 FIELD 반복 뒤 CMD-001 후보다

**Status:** Accepted (2026-09-18). 아직 구현하지 않는다.

**Context:** Pinky 앞 카메라는 320×240, 8 fps, 바닥 전방용이다. 지금 온보드 blob을
넣으면 시야 밖 공을 잃고, D-41 로봇 카메라 위치를 게임으로 닫게 된다.

**Decision:**

- D-96 계단 4가 여러 번 반복되기 전에 온보드 공 추적을 열지 않는다
- 열릴 때도 최종 `cmd_vel`은 CORE다. 온보드는 CMD-001 속도 후보이거나 호스트가
  쓰는 로컬 관측이다
- 심판(득점, 킥오프, 양쪽 stop)은 노트북 `rosy_games`에 남는다
- 이 코드는 D-41·D-52를 Accepted로 올리지 않는다

**Alternatives:** 앞 카메라만으로 1v1을 시작하는 안은 천장 호스트를 버린다.
온보드가 `cmd_vel`을 내는 안은 D-2·D-38 위반이다.

**Consequences:** 1단계 실기는 천장 카메라다. 온보드 패키지/슬라이스는 별도 계획.

**Validation / Transition:** `isaac/`과 온보드 플레이어 패키지가 트리에 없다.
구현은 D-96 계단 4 기록 다음 문서.

**References:** D-2, D-38, D-41, D-90, D-94, D-96.

**Amendment (2026-09-18):** 호스트 observer 카탈로그 잠금은 D-109. `--onboard`를
지금 만들지 않는다. D-41 Status는 Proposed로 남는다.

---

## D-98 Isaac 축구 env는 FIELD 반복 전 폴더를 만들지 않는다

**Status:** Accepted (2026-09-18). 아직 구현하지 않는다.

**Context:** Isaac은 학습장으로 예약됐다. 빈 `isaac/` 패키지는 학습이 있는 것처럼
보인다. Gazebo(`rosy_gz_sim`)는 CORE ROS-SIM용이다.

**Decision:**

- `src/rosy_games/rosy_games/isaac/`은 D-96 계단 4가 반복되기 전에 만들지 않는다
- 열릴 때 Lab env는 `game.reset` / `game.step`만 호출한다. 규칙을 Isaac 스크립트에
  복제하지 않는다
- `rosy_gz_sim`을 축구 체육관으로 승격하지 않는다
- Isaac이 실기 Command Manager를 대체하지 않는다

**Alternatives:** 지금 빈 폴더를 두는 안은 이미 지웠다. Isaac이 경기를 소유하는 안은
D-90이 거절했다.

**Consequences:** Isaac 없는 실기 1v1이 `game`만으로 성립해야 한다.

**Validation / Transition:** 트리에 `rosy_games/isaac/`이 없다.

**References:** D-83, D-90, D-96, D-99.

**Amendment (2026-09-18):** 카탈로그 거절은 D-109. 빈 `isaac/`을 다시 만들지 않는다.

---

## D-99 학습된 축구 정책은 Policy 플러그인이며 cmd_vel을 내지 않는다

**Status:** Accepted (2026-09-18). 아직 구현하지 않는다.

**Context:** 개념 11은 AI가 액추에이터 루프를 직접 돌리지 않는다고 했다. 축구 RL이
`/cmd_vel`을 내면 D-2를 게임으로 우회한다.

**Decision:**

- `NeuralPolicy`는 `Policy.act(obs, state) -> dict[str, Twist]`만 구현한다
- 호스트 `gate`와 CORE teleop/CMD-001이 그대로 자른다
- 1단계 `MatchState`에 `reward`를 넣지 않는다. 보상은 학습 env가 `step` 결과에서
  계산한다
- `catalog`에 이름을 등록하기 전에는 파일을 만들지 않는다

**Alternatives:** 학습 루프가 모터를 직접 쓰는 안은 개념 11·D-38 위반이다.

**Consequences:** 휴리스틱과 신경망이 같은 구멍이다. D-98 Isaac env가 이 플러그인을
끼운다.

**Validation / Transition:** `POLICIES`에 `heuristic`만 있다.
`src/rosy_games/rosy_games/catalog.py`.

**References:** D-2, D-38, D-90, D-98, [concept 11](../concept/11_ROSY_AI_and_Physical_AI.md).

**Amendment (2026-09-18):** `neural` 이름은 D-109가 카탈로그에서 거절한다. 파일은
등록 전에 만들지 않는다.

---

## D-100 골대는 천장에서 ArUco+영역으로 보이고, 득점은 필드 m 폴리곤이다

**Status:** Accepted (2026-09-18). 관측 결정이다. 구현 GO가 아니다.

**Context:** 지금은 골이 `Field.length_m` 양 끝 기하만이다. 천장에서 골대를 못 보면
호모그래피가 틀려도 심판이 같은 좌표로 득점한다. 골 입구를 QR·색 테이프로 보이게
하면 실측이 쉬워진다. 일반 QR은 페이로드용이고, 코너·로봇은 이미
`DICT_4X4_50` ArUco다. 검출기를 두 개 쓰면 천장 한 프레임이 갈라진다.

**Decision:**

- 골 **위치**는 천장 호스트가 본다. CORE·Fleet·`RobotMode`는 골을 모른다
- v1 마커는 코너와 같은 ArUco 사전이다. 일반 QR(QRCodeDetector)은 v1이 아니다
- id **20** = home 골 (negative_x, away가 넣으면 득점). id **21** = away 골
  (positive_x). 로봇 1–2, 코너 10–13과 겹치지 않는다
- 골 **입구**는 선택 HSV 영역(테이프/매트)이다. 마커가 로봇에 가려져도 입구
  폴리곤을 잡을 수 있다
- 피치 축은 여전히 코너 10–13 호모그래피다. 골 마커가 구장을 정의하지 않는다
- 득점은 `game`이 필드 m 폴리곤으로 판정한다 (`in_home_goal` / `in_away_goal`).
  마커·영역은 그 폴리곤을 **갱신**하거나 확인한다. cv2는 `overhead.py`에만 산다
- 양쪽 골 마커가 한 프레임에 없으면 기하 기본값(필드 끝 + `goal_width_m`)으로
  떨어진다. 추측으로 골을 옮기지 않는다
- D-96 계단 1은 코너·로봇·공에 **골 20/21(또는 입구 영역)** 이 보이는지를 포함한다

**Alternatives:** 일반 QR만 쓰는 안은 사전과 검출기를 나눈다. 골 마커만으로
호모그래피를 하는 안은 코너 4점이 사라지면 피치가 흔들린다. 픽셀에서 바로
득점하는 안은 `game`에 cv2를 넣는다 (D-90, D-94).

**Consequences:** `match.yaml`에 `goals.home_id` / `goals.away_id`(기본 20/21)와
선택 `goals.hsv_*`가 추가된다. 구현은 overhead 관측 확장이지 CORE 변경이 아니다.

**Validation / Transition:** 구현 전 색인만. 합성 시험이 생겨도 DEVICE가 아니다
(D-95). 경계: `game/`·`field/`에 cv2 없음.

**References:** D-90, D-94, D-95, D-96.

**Amendment (2026-09-18):** LOCAL 합성 프레임이 골 20/21과 선택 HSV 입구를
필드 m 폴리곤으로 투영한다. 양쪽 마커가 없으면 필드 끝 기하. DEVICE/FIELD는
실제 웹캠 계단 1 전까지 PARKED (D-95, D-96).

---

## D-101 축구 호스트 화면은 노트북 게임 표면이며 CORE `/dashboard`가 아니다

**Status:** Accepted (2026-09-18). 표면 분할이다. DEVICE/FIELD GO가 아니다.

**Context:** D-96 계단 1은 천장에서 구장·공·로봇·골 20/21이 **보이는지**다.
지금은 CLI와 합성 pytest만 있다. 그 미리보기를 CORE `/dashboard`에 붙이면
운용자 콘솔이 경기를 삼킨다(D-77). `rosy_control` `dashboard.html`에 붙이면
진단 화면이 게임이 된다. CORE CSS를 import하면 L2를 파일로 공유하는 결함이다
(D-92). 번들러를 들이면 D-75를 게임으로 우회한다.

**Decision:**

- 축구 미리보기는 **노트북 게임 표면**이다. 질문: "구장·공·로봇·골이 보이는가"
- CORE `/dashboard`에 경기 보드·천장 JPEG·골 칩을 넣지 않는다
- `rosy_control/web/dashboard.html`에 경기를 넣지 않는다
- 자산은 `rosy_games/web/` 손수 정적 HTML·CSS·ES 모듈이다. 번들러·npm·CDN 없음
- 노트북 `127.0.0.1`만 연다. `rosy_games match --preview`. 기본은 끔 (D-95와 같이
  실기 실수와 pytest를 갈라 둔다)
- 미리보기 서버는 stdlib `http.server`다. cv2는 `overhead.py`에만 산다.
  `host/preview.py`와 `host/loop.py`는 cv2를 import하지 않는다
- 보드가 그리는 것은 필드 m 오버레이(관측 JSON)다. JPEG는 overhead가 준
  바이트를 그대로 붙일 뿐이며, 픽셀에서 득점하지 않는다 (D-100)
- 표면 사이에 CSS·컴포넌트를 import하지 않는다. 게임 L2는 피치·점수·마커 칩이다
- 이 페이지는 teleop·`cmd_vel`·CORE FastAPI를 열지 않는다. 정지는 기존 호스트
  `safety/stop`이다
- 합성 보드 ≠ DEVICE (D-95). D-96 계단 1은 실제 웹캠 기록이다

**Alternatives:** CORE 운용/점검 탭에 축구를 넣는 안은 D-77을 깨뜨린다. 공용
`components.css`를 가져오는 안은 D-92다. `cv2.imshow`만 쓰는 안은 호스트
문법이 없고 시험이 화면을 못 잠근다.

**Consequences:** concept 16 §2에 Game host 행이 생긴다. CORE 이미지·슬라이스·
`dashboard_assets` allowlist에 게임 보드가 없다. D-96 계단 1의 노트북 도구다.

**Validation / Transition:** `test/test_rosy_games_surface.py`,
`src/rosy_games/test/test_preview.py`, `test_games_boundaries.py`.
DEVICE/FIELD PARKED.

**References:** D-23, D-72, D-75, D-77, D-90, D-92, D-94, D-95, D-96, D-100,
[concept 16](../concept/16_ROSY_Interface_Design_Principles.md).

---

## D-102 노트북 매치 루프는 `--ticks`가 없으면 20 Hz로 Ctrl+C까지다

**Status:** Accepted (2026-09-18). 호스트 루프 계약이다. DEVICE GO가 아니다.

**Context:** 설계 §8은 호스트 teleop를 20 Hz로 적는다. D-101 미리보기는
`--ticks`가 없을 때만 그 루프를 열었고, `--observer overhead`만 켜면 1틱 뒤에
프로세스가 죽었다. D-96 계단 1–5는 보드가 있든 없든 관측·teleop가 유지돼야 한다.
`--preview`가 루프 수명을 겸하면 화면 없는 현장 계단이 다시 1틱이 된다.

**Decision:**

- `--dry-run`이 아니고 `--ticks`가 없으면 매치 루프는 **20 Hz** (`period_s=0.05`)로
  Ctrl+C까지 돈다
- `--ticks N`은 유한 시험·스크립트용이다. 이때는 sleep 하지 않아도 된다
- `--preview`는 보드를 켤 뿐 루프를 열거나 닫지 않는다
- 기본 observer는 여전히 `hold`다 (D-95). 루프가 길어진다고 카메라를 열지 않는다
- Ctrl+C는 traceback 없이 `halt()`한다 (이미 `run_match` finally)

**Alternatives:** 미리보기만 길게 두는 안은 계단 2 이후 보드 없이 달리기를 막는다.
기본을 1틱으로 두는 안은 현장 CLI가 시험 CLI와 같아진다.

**Consequences:** `rosy_games match --config … --observer overhead`는 `--preview`
없이도 천장 관측을 유지한다. pytest는 `--ticks`를 명시한다.

**Validation / Transition:** `src/rosy_games/test/test_cli.py`,
`test_session.py`. DEVICE/FIELD PARKED.

**References:** D-90, D-95, D-96, D-101,
[game host 설계 §8](../plans/2026-09-17-robot-soccer-game-host-design.md).

---

## D-103 match.yaml 한계는 게이트 계약이고 유실 HOLD는 즉시다

**Status:** Accepted (2026-09-18). 호스트 안전 계약이다. DEVICE GO가 아니다.

**Context:** `limits.linear: 0.08`은 정책 속도로 들어갔지만 `limits.angular: 0.40`은
YAML에만 있고 휴리스틱은 각속도를 ±1.0까지 낸다. `watchdog.lost_hold_s: 0.5`도
로드만 되고 심판은 유실 즉시 HOLD다. 0.5초를 게임에 디바운스로 넣으면 공을 잃은
뒤에도 마지막 teleop가 남는다. 설계는 유실 즉시 양쪽 정지고, 500 ms는 CORE
워치독(SAF-002)이다.

**Decision:**

- `limits.linear` / `limits.angular`는 **gate의 마지막 클램프**다. 정책이 더 크게
  내도 호스트가 잘라 낸다
- 휴리스틱도 같은 한계를 존중한다. gate가 없으면 안 된다
- 유실 HOLD는 **즉시**다. `lost_hold_s`를 디바운스로 쓰지 않는다
- `lost_hold_s`는 CORE teleop 워치독 상한이다. 호스트 `period_s`는 그 값 이하다
  (20 Hz = 0.05 s ≪ 0.5 s)
- 이 값이 DEVICE에서 워치독 증거를 대신하지 않는다 (D-96)

**Alternatives:** 유실을 0.5 s 참는 안은 마커가 가려진 채 돌게 한다. angular를
정책에만 두는 안은 신경망 플러그인이 한계를 우회한다 (D-99).

**Consequences:** `MatchSetup.angular`가 생긴다. `gate(..., max_linear, max_angular)`.
period > `lost_hold_s`이면 기동하지 않는다.

**Validation / Transition:** `test_gate.py`, `test_cli.py`, `test_heuristic_policy.py`.
DEVICE/FIELD PARKED.

**References:** D-90, D-96, D-99, D-102, SAF-002.

---

## D-104 호스트 arm은 MANUAL 다음에 PUT safety/limits를 건다

**Status:** Accepted (2026-09-18). 호스트 계약이다. DEVICE GO가 아니다.

**Context:** 설계 §4.2와 D-96 계단 2는 첫 접촉을 `PUT /api/v1/safety/limits`로
0.08–0.10 m/s에 묶는다. 호스트 gate(D-103)만 있으면 CORE 프로필 최대 0.20이
그대로다. `HttpPlayerClient`는 mode/teleop/stop만 알았다. PUT limits는 Admin
토큰이다. 같은 토큰으로 403이 나면 `match.local.yaml` 문제이지 PUT을 생략할
이유가 아니다.

**Decision:**

- `MatchHost.arm()`은 각 로봇에 `set_manual` 다음 `PUT /api/v1/safety/limits`
  `{manual_linear, manual_angular}` (match.yaml `limits`)
- `max_linear`가 없으면 PUT하지 않는다 (단위 시험 더블)
- 한쪽 실패는 지금처럼 양쪽 `halt`
- follow / navigation / swarm 경로는 여전히 없다
- 이 PUT이 DEVICE 정지·워치독 증거를 대신하지 않는다 (D-96)

**Alternatives:** gate만 믿는 안은 호스트가 죽으면 워치독 전에 프로필 최대로
달릴 수 있다. 토큰이 operator면 건너뛰는 안은 첫 접촉 속도가 문서와 달라진다.

**Consequences:** `HttpPlayerClient.set_limits`. `test_transport`는 limits를
허용하고 follow/nav/swarm은 계속 금지.

**Validation / Transition:** `test_transport.py`, `test_loop.py`. DEVICE/FIELD PARKED.

**References:** D-90, D-96, D-103, SAF-004,
[API Ref §5](../reference/ROSY%20API%20%26%20Protocol%20Reference.md).

---

## D-105 호스트 정지는 스페이스와 보드 /stop이며 양쪽 safety/stop이다

**Status:** Accepted (2026-09-18). 호스트 입력이다. DEVICE GO가 아니다.

**Context:** 설계 §5는 스페이스·창 닫기·예외가 양쪽 `POST /api/v1/safety/stop`을
부른다고 적는다. 예외와 finally는 이미 `halt()`다. 스페이스와 보드 정지는 없었다.
보드가 CORE FastAPI를 직접 치면 D-101을 깨뜨린다.

**Decision:**

- 라이브 루프는 스페이스를 보면 다음 사이클에서 빠져 `halt()`한다
- 미리보기 `POST /stop`은 **같은 노트북 서버**만 친다. CORE URL을 열지 않는다
- `/stop`은 플래그만 세운다. HTTP 스레드에서 teleop와 동시에 estop하지 않는다
- 창 닫기·프로세스 종료는 기존 finally + CORE 워치독이다
- 보드 정지 버튼은 되돌릴 수 없는 조작이다 (concept 16 Law 3). 새 CORE 색을
  import하지 않는다

**Alternatives:** 보드가 로봇 URL로 stop을 보내는 안은 D-101 위반이다. 스페이스를
운영자 콘솔에만 두는 안은 게임 호스트에 사람이 없다.

**Consequences:** `run_match(..., halt_check=...)`. 미리보기 보드에 정지 버튼.
pytest는 `halt_check`로 키보드를 흉내 낸다.

**Validation / Transition:** `test_session.py`, `test_preview.py`. DEVICE/FIELD PARKED.

**References:** D-90, D-96, D-101, D-102, SAF-001.

---

## D-106 Fleet 매치 시작은 나중에 Fleet→games 한 방향이며 지금은 버튼을 만들지 않는다

**Status:** Accepted (2026-09-18). D-90 남은 통로 결정이다. 콘솔 버튼을 지금
구현하지 않는다.

**Context:** D-90 수정은 "심판을 Fleet 서버로 옮긴다"는 말이 매치 시작 버튼의
자리이지 규칙 엔진의 이사가 아니라고 적었다. 남은 표는 그 버튼을 "지금
구현하지 않음"으로만 남겨 다음 세션이 Fleet 콘솔에 축구를 넣거나
`rosy_games` 보드에 관제 시작을 붙이기 쉽다. Fleet 서버 v1은 REST gather와
목표·전체 정지가 있다 (D-81). `hub --listen`은 D-88 뒤다.

**Decision:**

- 매치 **시작 버튼**이 생기면 **Fleet 콘솔**에만 산다. `rosy_games` 보드·CLI에
  Fleet 시작 UI를 넣지 않는다
- 그 버튼이 하는 일은 `rosy_games` `MatchHost.reset()` / `run_match`를 **한 방향**
  으로 부르는 것이다. 규칙을 Fleet에 복제하지 않는다
- **지금은 버튼을 만들지 않는다.** D-88 소켓과 현장 계단 4(D-96) 앞에 관제
  매치 UI를 열지 않는다
- `rosy_fleet`은 `rosy_games`를 import하지 않는다. `rosy_games`는 `rosy_fleet`을
  import하지 않는다 (이미 경계 시험)
- `reset()`의 주인은 계속 `rosy_games`다 (D-12, D-90)
- games를 D-62 슬라이스에 올리지 않는다 (이미 `test_rosy_games_surface.py`)

**Alternatives:** 지금 Fleet 콘솔에 축구 시작을 넣는 안은 규칙과 관제를 한
화면에 섞는다. games 보드에 "Fleet 시작"을 넣는 안은 노트북 게임 표면이
관제가 된다 (D-101).

**Consequences:** 노트북 경기는 계속 `rosy_games match`다. Fleet 콘솔은 로봇
목표·일괄 stop만 유지한다.

**Validation / Transition:** `test/test_rosy_games_surface.py` —
Fleet 소스가 `rosy_games`를 모르고, 게임 보드/CLI에 fleet 시작이 없다.
`RobotMode.SOCCER` 없음. DEVICE/FIELD PARKED.

**References:** D-12, D-62, D-81, D-88, D-90, D-101.

---

## D-107 D-96 계단 1 호스트는 관측만이며 기본은 모터를 무장하지 않는다

**Status:** Accepted (2026-09-18). 계단 1 호스트 계약이다. DEVICE GO가 아니다.

**Context:** D-96 계단 1은 모터 없이 천장에서 구장·공·로봇·골이 보이는지다.
`rosy_games match --observer overhead --preview`는 MANUAL을 무장하고
`PUT limits`와 teleop 0을 냈다. 공이 중앙에 보이면 휴리스틱이 0.08 m/s를 낼 수
있다. 기본 CLI가 계단 2를 계단 1처럼 열면 안 된다.

**Decision:**

- 라이브 매치 **기본은 관측만**이다. `arm()` / `PUT limits` / teleop를 하지 않는다
- `--observe-only`는 그 기본을 명시한다
- 미리보기·스페이스 halt·`POST /stop`은 그대로다. halt는 무장하지 않은 대에도
  `safety/stop`을 부를 수 있다
- `--observer overhead`가 기본을 드라이브로 바꾸지 않는다 (D-95)
- 합성 pytest로 계단 1 FIELD GO를 하지 않는다 (D-95, D-91)

**Alternatives:** 기본을 드라이브로 두는 안은 계단 1에서 공이 보이면 달린다.
관측만 할 때 HTTP 클라이언트를 안 만드는 안은 스페이스 정지가 없어진다.

**Consequences:** 기존 무장 시험은 `--drive`가 필요하다. 계단 1 CLI:
`rosy_games match --config … --observer overhead --preview`.

**Validation / Transition:** `test_cli.py`, `test_loop.py`. DEVICE/FIELD PARKED.

**References:** D-95, D-96, D-101, D-104, D-105.

---

## D-108 `--drive`는 계단 2+ 스위치이며 FIELD GO가 아니다

**Status:** Accepted (2026-09-18). 호스트 스위치다. DEVICE/FIELD GO가 아니다.

**Context:** D-96 계단 2는 한 대 0.08 m/s, 계단 3–4는 두 대다. 기본이 관측만
(D-107)이므로 달리려면 명시해야 한다. `--drive`가 pytest 통과를 현장 GO로
읽히면 D-91이다. 한 대만 CORE가 살아 있는데 둘 다 무장하면 계단 2가 실패한다.

**Decision:**

- `--drive`는 arm + PUT limits + teleop를 연다
- 인자 없이 `--drive`면 **두 대** (계단 3–4)
- `--drive rosy_01`처럼 id를 주면 **그 대만** 무장·teleop (계단 2). 다른 대는
  teleop하지 않는다. halt는 양쪽
- 없는 id면 기동하지 않는다
- `--drive`와 `--observe-only`는 같이 쓰지 않는다
- `--drive`는 그 기기 정지·워치독·단일 `cmd_vel` 증거가 있기 전에는 FIELD GO가
  아니다 (D-96)

**Alternatives:** 항상 두 대를 무장하는 안은 계단 2에서 꺼둔 CORE가 arm 실패로
둘 다 halt한다. 한 대 경기를 기본으로 하는 안은 D-96 "한 대만 뛰는 1v1은 없다"와
계단 4를 섞는다.

**Consequences:** `MatchHost.drive_ids`. pytest 무장 시험은 `--drive`.

**Validation / Transition:** `test_cli.py`, `test_loop.py`. FIELD PARKED.

**References:** D-91, D-96, D-104, D-107.

---

## D-109 계단 4 전 카탈로그는 soccer/heuristic/hold/overhead만이다

**Status:** Accepted (2026-09-18). D-97·D-98·D-99의 호스트 잠금이다. 온보드·Isaac·
신경망을 지금 구현하지 않는다.

**Context:** D-97은 온보드를 계단 4 뒤에 두고, D-98은 `isaac/`을 만들지 않으며,
D-99는 `NeuralPolicy`를 카탈로그 등록 전에 파일을 만들지 말라고 했다. CLI
`--observer`가 문자열 분기로만 있으면 `--onboard`가 다음 패치에 섞이기 쉽다.
overhead를 catalog가 모듈 상단에서 import하면 cv2가 hold 경로까지 올라온다.

**Decision:**

- `GAMES` = `{soccer}`, `POLICIES` = `{heuristic}`, `OBSERVERS` = `{hold, overhead}`
- `make_observer("onboard")` / `make_policy("neural")` / `make_game` 미등록 이름은
  ValueError
- `host/onboard.py`, `policy/neural.py`, `isaac/`을 지금 만들지 않는다
- `make_observer`는 overhead를 **쓸 때만** import한다. catalog 모듈 로드가 cv2를
  끌어오지 않는다
- 온보드가 열려도 `Observer` 플러그인이다. `cmd_vel`을 내지 않는다 (D-97, D-99)
- 이 잠금이 D-41·D-52를 Accepted로 올리지 않는다

**Alternatives:** 지금 onboard 스텁을 두는 안은 빈 isaac과 같다. catalog가
overhead를 항상 import하는 안은 hold pytest에 cv2가 필요해진다.

**Consequences:** CLI `--observer` 선택지는 카탈로그에서 온다.

**Validation / Transition:** `test_catalog.py`, `test_rosy_games_surface.py`.
D-41 행은 Proposed. DEVICE/FIELD PARKED.

**References:** D-41, D-94, D-96, D-97, D-98, D-99.

---

## D-110 첫 접촉 limits.linear는 0.10을 넘지 않는다

**Status:** Accepted (2026-09-18). 호스트 속도 상한이다. 0.20 m/s FIELD GO가 아니다.

**Context:** D-96은 첫 접촉을 0.08–0.10 m/s로 두고, 프로필 0.20은 그 기기 안전
증거와 계단 4 반복 다음이다. `match.yaml` `limits.linear`를 0.20으로 올리면
호스트 gate가 그대로 CORE에 밀어 넣는다 (D-103, D-104).

**Decision:**

- `load_match`는 `limits.linear` > **0.10** 이면 거부한다
- 기본 0.08은 그대로다
- 0.20은 계단 4 기록이 있는 **다음 ADR**에서만 연다
- 이 상한이 DEVICE 워치독 증거를 대신하지 않는다

**Alternatives:** YAML만 믿고 0.20을 허용하는 안은 계단을 건너뛴다. 0.08만
허용하는 안은 설계의 0.08–0.10 구간을 자른다.

**Consequences:** `FIRST_CONTACT_LINEAR_M = 0.10`. 현장 속도 올리기는 별도 결정.

**Validation / Transition:** `test_cli.py` load_match. DEVICE/FIELD PARKED.

**References:** D-96, D-103, D-104.

---

## D-111 `--stair 1–5`는 호스트 프리셋이며 FIELD GO가 아니다

**Status:** Accepted (2026-09-18). D-96 계단의 CLI 매핑이다. 현장 GO가 아니다.

**Context:** 계단 2는 한 대, 3–5는 두 대다. `--drive`만 있으면 실수가 두 대를
계단 2로 연다. `--stair` 없이 현장 순서를 기억하면 건너뛰기 쉽다.

**Decision:**

- `--stair 1` 관측만. `--drive`와 같이 쓰지 않는다
- `--stair 2`는 `--drive <한 id>`가 필요하다 (한 대)
- `--stair 3|4|5`는 두 대. `--drive`가 없으면 둘 다 연다. 한 id만 주면 거부
- `--stair`는 overhead를 강제하지 않는다. 기본 observer는 여전히 hold (D-95)
- `--stair N` pytest 통과 ≠ 그 계단 FIELD GO (D-91, D-96)
- 킥오프(계단 5)는 계속 사람이 공을 둔다. 호스트는 중앙 공 전에는 PLAY로 넘기지
  않는다 (이미 SoccerGame)

**Alternatives:** 계단 번호를 문서에만 두는 안은 CLI가 두 대를 계단 2로 연다.
`--stair 2`가 첫 로봇을 추측하는 안은 yaml 순서를 드라이브 명단으로 승격한다.

**Consequences:** 현장 명령은 `--stair 1 --observer overhead --preview` 다음
`--stair 2 --drive rosy_01 --drive`가 아니라 `--stair 2 --drive rosy_01`.

**Validation / Transition:** `test_cli.py`. FIELD PARKED.

**References:** D-91, D-95, D-96, D-107, D-108.

---

## D-112 계단 1 가시성은 호스트 보고이며 FIELD GO가 아니다

**Status:** Accepted (2026-09-18). 천장 마커 체크리스트다. 현장 GO가 아니다.

**Context:** D-96 계단 1은 코너 10–13, 로봇 1/2, 공, 골 20/21이 보여야 한다.
보드에 칩은 있으나 호스트가 “계단 1 보임”을 이름 붙여 말하지 않으면 합성
프레임과 실측을 같은 성공으로 적기 쉽다.

**Decision:**

- `stair1_visibility`는 코너·로봇 ArUco·골 id·공 유실을 보고한다
- `ready`는 네 코너와 두 로봇과 공, 그리고 골 20/21(또는 HSV 입구 설정)이
  보일 때다
- `ready`와 pytest는 FIELD GO가 아니다 (D-91, D-95, D-96)
- `--stair 1 --dry-run`은 기대 id를 찍는다. 라이브는 마지막 보고를 찍는다
- 보드 overlay에 `visibility`를 실어 “FIELD GO 아님”을 같이 쓴다
- OpenCV는 계속 `overhead.py`만. `visibility.py`는 cv2를 import하지 않는다

**Alternatives:** 보드 칩만 두는 안은 계단 1 합격 기준이 운영자 기억이다.
`ready`를 FIELD GO로 승격하는 안은 D-95다.

**Consequences:** 현장 계단 1은 보고를 보고 사람이 `logs.md`에 실측을 적는다.

**Validation / Transition:** `test_cli.py`, `test_preview.py`. FIELD PARKED.

**References:** D-91, D-95, D-96, D-100, D-101, D-111.

---

## D-113 D-96 남은 실행은 현장 실측이며 LOCAL 호스트 트랙은 닫힌다

**Status:** Accepted (2026-09-18). 호스트 스위치는 D-107–D-112로 끝이다.

**Context:** 남은 ADR을 호스트에 계속 붙이면 웹캠 없이 계단을 닫는 것처럼
보인다. D-97–D-99·linear 0.20은 계단 4 기록이 전제다.

**Decision:**

- D-96 계단 1–5의 **다음 실행**은 실제 천장 웹캠과 Pinky다
- LOCAL 호스트 계약은 D-107–D-112로 닫는다. 새 호스트 스위치 ADR은 현장
  `logs.md` 실측 항목이 생긴 뒤에만 연다
- DEVICE/FIELD는 PARKED. `--stair`·`ready`·pytest가 GO가 아니다
- 온보드 / `isaac/` / `neural` / 0.20은 여전히 거절 (D-109, D-110)

**Alternatives:** 합성 overhead `ready`로 계단 1을 GO로 적는 안은 D-95다.
호스트 ADR을 더 만들어 현장을 미루는 안은 이 결정이 거절한다.

**Consequences:** 다음 세션 명령은 `--stair 1 --observer overhead --preview`.

**Validation / Transition:** `progress.md` FIELD PARKED. `test_rosy_games_surface.py`.

**References:** D-91, D-95, D-96, D-107, D-108, D-109, D-110, D-111, D-112.

---

## D-114 gz_multi 시뮬은 도메인 하나·네임스페이스·ros_gz_bridge다

**Status:** Accepted (2026-09-18). 시뮬 통신 모델이다. ROS-SIM GO가 아니다.

**Context:** 실기는 `ROS_DOMAIN_ID = 40+N` 과 localhost CycloneDDS 로 로봇 간 DDS를
끊고, 관제는 CORE REST 다 (D-33, D-81). `gz_multi` 는 Gazebo 하나 위에 N대를
띄우므로 도메인을 나누면 spawn·clock·`/tf` 가 깨진다. ROS 2 `domain_bridge` 와
`rosy_env.sh` 를 시뮬에 얹으면 실기 격리를 흉내 내는 것처럼 보이지만, 관제가 쓰는
경로는 HTTP 라 그 브리지는 관제를 닫지 않는다.

2026-09-18 WSL 실측: `parameter_bridge` 두 개가 `rosy_01`/`rosy_02` 의
scan/cmd_vel/odom 을 이었고 `domain_bridge` 프로세스는 없었다. 관제
`127.0.0.1:8090` 은 8080/8081 REST 로 2/2 online 이었다.

**Decision:**

- `gz_multi` 는 **도메인 하나** + `rosy_XX` 네임스페이스다
- Gazebo↔ROS 는 **`ros_gz_bridge` `parameter_bridge`** 다. 로봇마다 YAML 을 만든다
- ROS 2 `domain_bridge` 를 `gz_multi` 에 넣지 않는다
- `rosy_env.sh` / 로봇별 `ROS_DOMAIN_ID` 를 `gz_multi` 에 source 하지 않는다
- 시뮬 관제는 계속 CORE REST (D-81). 관제 UI 가 DDS/`cmd_vel` 에 붙지 않는다
- 이 결정이 ROS-SIM GO 가 아니다 (D-79, D-83, D-87)

**Alternatives:** 시뮬에도 로봇별 도메인을 쓰는 안은 한 Gazebo 월드의 clock/TF 를
나눈다. `domain_bridge` 로 관제 PC 를 도메인 0 에 두는 안은 관제가 이미 HTTP 라
중복이다.

**Consequences:** 실기 D-33 과 시뮬 네임스페이스는 다른 모델이다. 시뮬 DDS
디스커버리 흔들림을 실기 격리가 안 된 증거로 쓰지 않는다.

**Validation / Transition:** `test_gz_package_contract.py`. ROS-SIM HOLD.

**References:** D-6, D-33, D-79, D-81, D-83, D-87.

---

## D-115 gz_multi는 스폰 좌표를 map initialpose로 심는다

**Status:** Accepted (2026-09-18). 시뮬 측위 시드다. ROS-SIM GO가 아니다.

**Context:** 각 로봇 odom 원점은 자기 spawn 이다. AMCL 에 map 시드가 없으면 CORE 는
map TF 가 없어 odom (0,0) 을 보고 pose 로 쓴다 (`odometry.odom_owns_pose`).
2026-09-18 factory `gz_multi` 에서 두 CORE 가 둘 다 pose ≈ (0,0) 을 보고, 관제가
겹친 줄 알고 양보를 걸었다. spawn 은 `(-0.2, 1.05)` / `(0.4, 1.05)` 였다.

CORE 는 이미 `POST /api/v1/localization/initialpose` 와 `{ns}/initialpose` 퍼블리셔가
있다. `gz_multi` 가 스폰 뒤 심지 않을 뿐이다.

**Decision:**

- `mode:=nav` (AMCL) 에서 로봇 i 의 map 시드는
  `(spawn_x + (i-1)*spacing, spawn_y, yaw=0)`
- `gz_multi` 가 `{ns}/initialpose` 로 반복 publish 한다. AMCL 이 늦게 구독해도 받게
- odom (0,0) 을 관제 pose 로 승격하지 않는 것이 목적이다. 시드가 곧 현장 GO 는 아니다
- `seed_initialpose` 는 rosy_core 를 import 하지 않는다

**Alternatives:** 운영자가 콘솔에서 initialpose 를 누르는 안은 매 시뮬마다 원점 겹침
양보가 먼저 난다. CORE 가 odom 폴백을 끄는 안은 맵 없는 teleop 화면을 지운다.

**Consequences:** 스폰 숫자와 시드 숫자는 같은 함수다 (`spawn_xy`). pytest 가
Gazebo 를 대신하지 않는다.

**Validation / Transition:** `test_world_profiles.py`, `test_gz_package_contract.py`.
ROS-SIM HOLD.

**References:** D-79, D-81, D-114, D-116.

---

## D-116 관제 양보는 출발 로봇과 겹친 pose를 길로 보지 않는다

**Status:** Accepted (2026-09-18). 관제 기하 가드다. DEVICE/FIELD GO가 아니다.

**Context:** 양보는 경로 위 `yield_keep_out` 안의 **서 있는** 로봇을 치운다. 출발
로봇과 차단 로봇이 같은 좌표(측위 실패·odom 원점)면, 출발점에서 목표로 그은 직선이
그 좌표를 지나 **자기 원점의 유령**을 길로 본다. 2026-09-18 시뮬에서 `rosy_01` 목표
하달이 `YIELDING` / `blocked_by rosy_02` 가 되고 `rosy_02` 가 양보 벽감으로 돌기
시작했다. 둘 다 pose ≈ (0,0) 이었다.

D-93 은 폭 면제를 거절한다. 겹친 보고를 면제하는 것은 폭이 아니라 **같은 점이라서
누가 길을 막는지 말할 수 없음**이다.

**Decision:**

- mover 와 후보의 pose 거리가 `COINCIDENT_M` (0.05 m) 미만이면 길로 보지 않는다
- 0.05 m 는 풋프린트보다 작고, factory spawn 간격(0.6 m)보다 훨씬 작다
- 이 가드가 AMCL 시드(D-115)를 대신하지 않는다. 둘 다 필요하다
- 실제 0.05 m 안에 두 대가 있는 배치는 이 가드가 중재를 포기한다. 그 배치는 시뮬
  spawn 계약이 아니다

**Alternatives:** (0,0) 만 특수 처리하는 안은 맵 원점 spawn 월드에서 실패한다.
양보를 끄면 D-93 실측(빈 방 맞물림)이 돌아온다.

**Consequences:** `traffic.coincident`. 호스트 pytest 로 DEVICE GO 하지 않는다.

**Validation / Transition:** `test_server_yield.py`. ROS-SIM HOLD.

**References:** D-12, D-93, D-115.

---

## D-117 RMW는 CycloneDDS만 쓴다

**Status:** Accepted (2026-09-18). 미들웨어 선택이다. FastDDS 이중 프로파일이 아니다.

**Context:** ROS 2 Jazzy 기본 RMW는 종종 `rmw_fastrtps_cpp`다. Cyclone 노드와
FastDDS 노드는 서로를 조용히 못 본다 — 토픽이 비어 보이면 코드 버그로 읽힌다.
로봇 compose 와 `rosy_env.sh` 는 이미 `rmw_cyclonedds_cpp`다. 개발 `env.sh` 와
`gz_multi` 는 비어 있어, 2026-09-18 WSL 시뮬은 호스트 기본 RMW에 맡겼다.

**Decision:**

- 로봇·개발·시뮬 모두 `RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`
- FastDDS/`rmw_fastrtps_cpp` 를 두 번째 프로파일로 두지 않는다
- `env.sh` 가 기본값을 채운다. `gz_multi` 가 런치 환경에 고정한다
- compose·Dockerfile·`rosy_env.sh` 의 Cyclone 지정을 지우지 않는다
- 이 결정이 DDS 실측 GO가 아니다

**Alternatives:** 시뮬만 FastDDS 로 두는 안은 "토픽이 안 보인다"를 재현한다.
Zenoh RMW는 v1 범위 밖이다.

**Consequences:** `test/test_dds_rmw_contracts.py`. ROS-SIM HOLD.

**References:** D-6, D-33, D-114.

**Amendment (2026-09-18):** 빈 RMW를 채우고 잘못된 RMW를 거절하는 기동 훅은 D-121.
웹이 RMW를 바꾸는 API는 없다.

---

## D-118 생 Image는 Fleet·보드·gz_multi 브리지에 타지 않는다

**Status:** Accepted (2026-09-18). 전송 경로 계약이다. D-41을 닫지 않는다.

**Context:** `sensor_msgs/Image` 한 장은 스캔보다 수십 배 크다. DDS 로 사이트
WiFi·관제 PC·브라우저까지 실으면 cmd_vel/scan 이 밀린다. 흔한 ROS 함정이다.
CORE 대시보드와 게임 보드는 JPEG/HTTP 다 (D-75, D-101). `gz_multi` 의
`parameter_bridge` 는 이미지를 안 싣는다. 옛 `launch_sim.launch.xml` 은
`ros_gz_image` 를 `/camera/image_raw` 와 `/camera` 에 **두 번** 붙인다.

로봇 안 `camera/front` 는 온보드 검출용으로 남는다. 그걸 Fleet envelope 이나
노트북 천장 호스트로 미는 것이 금지다.

**Decision:**

- `gz_multi` `BRIDGE_TEMPLATE` 과 `rosy_bridge.yaml` 에 `sensor_msgs/msg/Image` 가
  없다
- `gz_multi` 는 `ros_gz_image` / `image_bridge` 를 띄우지 않는다
- `launch_sim.launch.xml` 의 image_bridge 는 `bridge_image:=true` 일 때만, 토픽
  하나 (`/camera/image_raw`)
- Fleet 과 `rosy_games` 는 `sensor_msgs` Image 를 import 하지 않는다
- 운용 화면은 JPEG/HTTP. 생 Image 를 브라우저에 싣지 않는다
- D-41 ARM64 카메라 배치는 이 ADR 이 닫지 않는다

**Alternatives:** compressed Image 토픽을 사이트 DDS 로 여는 안은 여전히
cmd_vel 과 큐를 다툰다. 천장 웹캠을 CORE 대시보드에 넣는 안은 D-101 이다.

**Consequences:** 온보드 `camera/front` 는 로봇 프로세스 안에 남는다.

**Validation / Transition:** `test_gz_package_contract.py`, `test_dds_rmw_contracts.py`.

**References:** D-34, D-41, D-75, D-94, D-101, D-114.

---

## D-119 스캔·이미지·IMU는 sensor-data QoS다

**Status:** Accepted (2026-09-18). 매칭 계약이다. 측정 함정 2를 ADR로 올린다.

**Context:** 센서 드라이버는 BEST_EFFORT + VOLATILE (`qos_profile_sensor_data`)
인 경우가 많다. 구독이 기본 RELIABLE(depth 10)이면 샘플이 한 줄도 안 온다.
`measure-dds-baseline.sh` 함정 2: `ros2 topic bw` 기본 RELIABLE 는 BEST_EFFORT
퍼블리셔에 0 을 준다. `camera_detect_node` 는 `Image` 를 depth 10(기본
RELIABLE)으로 내고, 구독은 `qos_profile_sensor_data`다. CORE `ros_bridge` 의
scan/imu 구독도 depth 10이다.

**Decision:**

- 생산 코드에서 `LaserScan` / `Imu` / `Image` 의 pub·sub 은
  `qos_profile_sensor_data` 다
- `cmd_vel` 과 latched `map` 은 이 규칙이 아니다 (RELIABLE / TRANSIENT_LOCAL)
- Bool 같은 소형 상태 토픽은 기본 depth 10을 유지해도 된다
- 호스트 시험은 소스 grep 이다. DEVICE GO가 아니다

**Alternatives:** 드라이버를 RELIABLE 로 올리는 안은 센서 파이프가 막히면
cmd_vel 까지 막는다. 구독만 고치고 퍼블리셔를 두는 안은 한쪽만 고친 것이다.

**Consequences:** `camera/front` 퍼블리셔와 CORE scan 구독이 같은 QoS 다.

**Validation / Transition:** `test_dds_rmw_contracts.py`. DEVICE PARKED.

**References:** D-34, D-118.

---

## D-120 시뮬 디스커버리는 LOCALHOST 범위이며 ROS_LOCALHOST_ONLY를 쓰지 않는다

**Status:** Accepted (2026-09-18). Jazzy 디스커버리 계약이다. D-6 localhost
프로파일을 대체하지 않는다.

**Context:** Jazzy 는 `ROS_LOCALHOST_ONLY` 를 deprecated 로 두고
`ROS_AUTOMATIC_DISCOVERY_RANGE` 를 쓴다. 2026-09-18 `gz_multi` 로그가 그
경고를 냈다. 로봇 격리는 Cyclone `NetworkInterface name="lo"` 이지 이 env 가
아니다 (D-6, D-33, `RosGraphMonitor`). 시뮬은 도메인 하나·한 기계라 범위
LOCALHOST 면 충분하다 (D-114).

**Decision:**

- `gz_multi` 와 개발 `env.sh` 는 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`
- `ROS_LOCALHOST_ONLY` 를 새로 켜지 않는다
- 로봇 compose/`rosy_env.sh` 는 Cyclone lo XML 을 유지한다. 시뮬에
  `rosy_env.sh` 를 source 하지 않는다 (D-114)
- 이 env 가 WiFi 실측 GO가 아니다

**Alternatives:** 시뮬에도 Cyclone lo XML 만 쓰는 안은 share 경로가 없는
부분 오버레이에서 실패한다. `SYSTEM` 범위는 같은 LAN 의 다른 ROS 그래프와
섞인다.

**Consequences:** 호스트 기본 FastDDS + 멀티캐스트 디스커버리를 시뮬이 물려받지
않는다 (D-117과 함께).

**Validation / Transition:** `test_gz_package_contract.py`, `env.sh`.

**References:** D-6, D-33, D-114, D-117.

---

## D-121 Cyclone 적용은 CORE 기동 전이고 웹은 보고만 한다

**Status:** Accepted (2026-09-18). D-117의 기동 훅이다. 웹이 RMW를 바꾸지 않는다.

**Context:** RMW는 `rclpy.init()` 때 로드된다. 그 다음 `os.environ` 이나 REST 로
FastDDS→Cyclone 을 바꿔도 **이미 떠 있는 노드에는 안 먹는다.** 브라우저 버튼으로
"사이클론 적용"을 주면 화면만 바뀌고 DDS는 그대로다. 미들웨어(`rosy_core`)는
프로세스를 여는 쪽이라, init **앞**에서만 채울 수 있다.

이미 있는 것: compose/`rosy_env.sh`/`env.sh`/`gz_multi` 가 RMW를 박음 (D-117).
`RosGraphMonitor` 는 Cyclone XML 의 lo 여부를 본다. 대시보드는 isolation 을
보여 준다. 빠진 것은 (1) `ros2 run rosy_core` 처럼 env 가 비었을 때 CORE 스스로
채우기, (2) 잘못된 RMW로 기동을 거절, (3) 스냅샷에 `rmw` 이름.

**Decision:**

- `apply_cyclone_rmw(env)` 를 `rclpy.init()` **전에** 부른다
- `RMW_IMPLEMENTATION` 이 비면 `rmw_cyclonedds_cpp` 를 채운다
- 다른 값이면 기동 실패 (`RmwError`). 조용히 덮어쓰지 않는다
- `CYCLONEDDS_URI` 는 compose/`rosy_env.sh` 가 연다. CORE 가 XML 경로를 추측해
  덮지 않는다 (시뮬 D-120 과 로봇 lo 프로파일이 다르다)
- `GET /api/v1/system/runtime` 의 ros 스냅샷에 `rmw` 를 넣는다. 웹은 표시만
- RMW를 바꾸는 REST/WS/대시보드 버튼은 만들지 않는다
- Fleet 은 로봇 RMW를 원격 설정하지 않는다

**Alternatives:** 웹에서 적용하는 안은 init 이후라 거짓 성공이다. 잘못된 RMW를
덮어쓰는 안은 운영자가 FastDDS를 디버그로 켠 이유를 지운다.

**Consequences:** env 가 비어도 CORE 한 프로세스는 Cyclone으로 뜬다. 이미 FastDDS로
init 된 이웃 노드는 이 훅이 고치지 못한다 — 그쪽도 같은 env로 다시 띄운다.

**Validation / Transition:** `test_rmw.py`, `test_ros_graph_monitor.py`,
`test_dashboard.py`. DEVICE PARKED.

**References:** D-1, D-117, D-120.

**Amendment (2026-09-18):** FastDDS 거절은 D-122 가 다음 기동에서 고치는 쪽으로
바꾼다. 웹 버튼·`system.reboot` 로 RMW를 고치지 않는 결정은 유지한다.

---

## D-122 잘못된 RMW는 다음 CORE 기동에서 Cyclone으로 고친다. OS reboot가 아니다

**Status:** Accepted (2026-09-18). D-121의 "거절"을 "다음 기동에서 교정"으로 바꾼다.

**Context:** RMW는 init 뒤에 안 바뀐다. 그래서 "자동으로 설정하고 재부팅하면 된다"는
말이 맞다 — **다시 띄우면** `apply_cyclone_rmw` 가 새 프로세스에서 먹는다. 다만
(1) 커널 `reboot` 는 UART 오버레이·Host Agent 영역이고 CORE가 부르면 안 된다
(D-22). (2) RMW만 고치려면 `rosy-core` 컨테이너/`rosy-runtime.service` 재기동이면
충분하다. (3) compose 는 이미 Cyclone을 박아 두므로 장치 기본 재기동은 이미
Cyclone이다. (4) 웹에서 `system.reboot` 를 누르면 로봇 전체가 내려가 모터·도크까지
같이 죽는다.

D-117 은 FastDDS 프로파일이 없다. 그래서 D-121 의 "틀린 RMW면 기동 실패"는
대시보드조차 못 띄운다. 다음 기동에서 Cyclone으로 **고치고 뜨는** 편이 맞다.

**Decision:**

- `apply_cyclone_rmw` 는 빈 값과 FastDDS/기타 값을 **Cyclone으로 고친다.** 거절하지
  않는다
- 이 교정은 **이 프로세스의 env** 다. `rclpy.init` 전에만 유효하다
- 이미 떠 있는 이웃 노드(같은 스택의 Nav2 등)는 **런타임 재기동**으로 같이 뜬다.
  `systemctl restart rosy-runtime.service` 또는 compose `up`. 커널 `reboot` 가
  아니다
- 웹은 계속 보고만 한다. RMW 적용 버튼·`system.reboot` 연동을 만들지 않는다
- Host Agent `system.reboot` 는 호스트 권한(네트워크·릴리스)용이다. RMW 도구가
  아니다
- `CYCLONEDDS_URI` 추측 덮어쓰기는 여전히 하지 않는다 (D-121)

**Alternatives:** 웹 확인 뒤 Pi reboot 는 동작은 하지만 폭발 반경이 RMW보다 크다.
틀린 RMW로 기동을 막는 안은 고칠 화면이 없다.

**Consequences:** `ros2 run rosy_core` 가 FastDDS env 로 불려도 CORE는 Cyclone으로
뜬다. 같은 셸의 다른 노드는 그 셸을 다시 열어야 한다.

**Validation / Transition:** `test_rmw.py`. DEVICE PARKED.

**References:** D-22, D-117, D-121.

**Amendment (2026-09-18):** CORE 기동이 FastDDS env 를 Cyclone으로 고치는 결정은 유지한다.
운영자가 웹에서 **저장 후 재부팅**하는 경로는 D-123. 라이브 env 패치는 여전히 없다.

---

## D-123 웹은 Cyclone을 오버레이에 저장한 뒤 Host Agent 재부팅을 요청한다

**Status:** Accepted (2026-09-18). persist-then-restart. 라이브 RMW 패치가 아니다.

**Context:** RMW는 init 때 로드된다. 웹에서 값을 바꾸고 **다시 뜨면** 새 프로세스가
Cyclone을 쓴다. 그게 맞다. D-121/D-122 가 거절한 것은 init **이후** env 만 바꾸는
거짓 성공과, CORE 가 직접 `reboot()` 를 부르는 것(D-22)이다.

이미 있는 재부팅 도구는 Host Agent `system.reboot` 다. 확인(`confirmed`) 없이는
실행되지 않는다. CORE 는 그 소켓을 중계만 한다.

**Decision:**

- 관리자 `POST /api/v1/system/dds/cyclone` `{confirmed: true}`
- 먼저 오버레이에 `dds.rmw: rmw_cyclonedds_cpp` 를 쓴다 (D-30). 패키지 기본값은
  건드리지 않는다
- 그다음 Host Agent `system.reboot` 를 중계한다. CORE 프로세스 안에서
  `reboot()` / `systemctl` 을 부르지 않는다
- `confirmed` 가 없으면 저장도 재부팅도 하지 않는다
- 에이전트가 없으면 저장은 이미 된 것이 아니라 **전체 실패**로 두지 않는다:
  오버레이는 쓰고, 재부팅 카드는 `available: false` 로 "런타임을 다시 띄우라"고
  말한다. 저장만 되고 재부팅이 안 된 상태를 숨기지 않는다
- 웹 버튼은 확인 대화 뒤 위 POST 만 부른다. FastDDS 선택 드롭다운은 없다 (D-117)
- compose 의 Cyclone 하드코딩은 유지한다. `.env` 로 FastDDS 를 열어주지 않는다

**Alternatives:** 저장만 하고 SSH 재기동은 웹 수정 뒤에 재부팅하라는 요청을 빠뜨린다.
CORE 가 `reboot(2)` 를 직접 부르는 안은 D-22 다.

**Consequences:** 재부팅은 로봇 전체가 잠시 내려간다. 그것이 운영자가 말한 재부팅이다.

**Validation / Transition:** `test_rmw.py`, `test_host_cards.py`, `test_dashboard.py`.

**References:** D-22, D-30, D-117, D-121, D-122.

---

## D-124 대시보드는 AP on/off와 Wi-Fi 연결을 Host Agent로 확인하고 적용한다

**Status:** Accepted (2026-09-18). 운영 네트워크 카드. nmcli 는 CORE 가 아니다.

**Context:** D-26 은 `SITE_STA`(AP 꺼짐)와 `RELAY_AP_STA`(AP 켜짐)를 장비 모드로
둔다. 대시보드 네트워크 카드는 그 모드·SSID·주소를 보여야 하고, 관리자가 AP를
켜거나 끄고 사업장 Wi-Fi에 다시 붙을 수 있어야 한다. 기존 카드는 자유 텍스트
`profile_id` 만 보냈고, Host Agent `network.status` 는 raw `nmcli` 덤프라
모드를 만들지 못했다.

PSK 를 CORE 로그·오버레이·GET 응답에 남기면 D-22 의 인터넷 표면이 비밀을
보관하게 된다. 그렇다고 대시보드에서 연결을 막으면 운영자가 말한 "확인하고
수정·처리"가 빠진다.

**Decision:**

- `network.status` 는 구조화한다: `mode`, `ap_active`, `ssid`, `ipv4`,
  `default_route`, `dns`, `profile_id`. PSK 필드는 없다
- 관리자 `POST /api/v1/host/network/mode` `{mode: SITE_STA|RELAY_AP_STA,
  confirmed: true}` → Host Agent `network.set_mode`. AP 끄기는 site 프로파일
  up + relay down, AP 켜기는 relay up
- 관리자 `POST /api/v1/host/network/connect` `{ssid, psk, confirmed: true}` →
  Host Agent `network.connect`. PSK 는 한 번 통과하고 NM 에만 남는다. CORE 는
  저장하지 않고 응답에서 제거한다. 감사는 키를 적색한다
- `confirmed` 가 아니면 Host Agent 가 거절한다. CORE 는 `nmcli` 를 부르지 않는다
- 대시보드는 AP 켜기/끄기 버튼과 SSID·암호 폼을 쓴다. GET 으로 암호 칸을 채우지
  않는다. 등록 프로파일 적용은 고급 경로로 남긴다
- 첫 부팅 설정 AP(PROVISIONING_AP)와 복구 AP는 이 카드가 열지 않는다. 업링크
  손실로 AP 를 여는 것도 금지(D-26 NETWORK_HOLD)

**Alternatives:** 프로파일 id 만 받기 — 운영자가 AP/SSID 를 다루지 못한다.
CORE 가 nmcli 를 직접 부르는 안은 D-22.

**Consequences:** 연결 적용 중 대시보드 세션이 끊길 수 있다. RELAY 가 켜져 있으면
로봇 AP 로 다시 붙을 수 있다. SITE_STA 에서 SSID 를 잘못 넣으면 현장 접근이
끊긴다. 그래서 확인이 필수다. 실제 라디오 성공은 DEVICE 증거다.

**Validation / Transition:** `test_host_agent.py`, `test_host_cards.py`,
`test_dashboard.py`.

**References:** D-22, D-26.


---

## D-125 Core 패키지를 논리적 도메인 라이브러리로 분할 (Option A)

**Status:** Accepted (2026-09-19). 모놀리식 core 패키지를 논리적인 단위의 하위 ROS 패키지로 분리하되 단일 노드(Single Process) 아키텍처는 유지한다.

**Context:** 기존 `rosy_core` (현재 `core/core`) 패키지 내부에 api, web, safety, docking, power, navigation 등 모든 도메인 로직이 집중된 모놀리식 구조였다. 프로젝트 규모가 커짐에 따라 코드 결합도를 낮추고 모듈의 독립성을 보장할 필요가 제기되었다. 다중 프로세스(Multi-node)로 분할하는 방안(Option B)도 고려되었으나, 기존의 의존성 주입(`CoreServices`)과 인메모리 `EventBus`를 ROS Topic으로 전면 교체하는 비용이 너무 크고, 아직 물리적 노드 분산의 이점이 뚜렷하지 않다고 판단되었다.

**Decision:** 

- D-1(단일 프로세스 원칙)을 준수하여, 런타임에는 여전히 `core_node`라는 하나의 ROS 노드로 실행된다.
- 소스 코드 레벨에서는 `core` 패키지를 다음과 같은 여러 개의 독립적인 ament_python 패키지(도메인 라이브러리)로 쪼갠다.
  - `core_common`: `identity`, `config`, `protocol`, `capability` 등 핵심 데이터 클래스
  - `core_events`: 인메모리 이벤트 버스
  - `core_features`: `safety`, `power`, `docking`, `navigation` 등 도메인 로직
  - `core_api_web`: `api`, `web` 프론트 및 통신부
  - `core_node`: 위의 모든 라이브러리를 의존성으로 가져와 `main.py`와 `node.py`에서 DI 컨테이너를 조립하고 실행하는 진입점
- 기존의 `module-split-criteria.md`에 명시된 "크기는 분리 기준이 아니다" 등의 엄격한 사내 규칙은, 이번 아키텍처 단위의 도메인 라이브러리 분할(Macro-level split)에는 예외적으로 적용하지 않거나 갱신한다. (마이크로 레벨의 단일 파일 분할 규칙은 유지)

**Alternatives:** 
- Option B (완전한 물리적 마이크로서비스 분할): 각 기능을 별도의 ROS 2 노드로 쪼개는 방식. 구현 및 통신 오버헤드, 디버깅 복잡도 증가로 인해 현 시점에서는 보류.
- 기존 모놀리식 유지: 결합도가 지속적으로 상승하여 유지보수성이 저하되므로 반려.

**Consequences:** 
- `core/` 디렉토리 아래에 여러 개의 ROS 패키지(라이브러리)가 생성된다.
- `colcon build` 시 패키지 간의 의존성(dependency) 트리가 명확해진다.
- 런타임 아키텍처는 변하지 않으므로 기존 테스트 코드의 파괴를 최소화할 수 있으나, 패키지 분리에 따른 `import` 경로 대거 수정이 필요하다.

**Validation / Transition:** 
- 1단계 작업으로 파이썬 모듈들을 논리적 패키지 폴더로 분리하고 `package.xml`과 `setup.py`를 작성한다.
- `colcon build` 정상 통과 및 기존 `pytest` 유닛 테스트 성공 여부 확인.

**References:** D-1, module-split-criteria.md

---

## D-126 완전 모듈 분리 — CORE는 슬라이스 코드를 import하지 않는다

**Status:** Accepted (2026-09-19). 분리 계약(가드 5개 + 영향 스위트)이 초록이다.
수용 범위: `test/test_module_separation.py` 5 passed, 어댑터 23·api/host/rmw/criteria 159 중
158 passed(1건은 Level-3 잔재 `rosy_default.yaml` 경로, D-126 미접촉), control 996 passed(환경성 2건은
패키지 디렉터리 실행 시 PASS 확인), fleet 312·omx 10·games 101·gz_sim 14 passed.
core 스위트의 나머지 실패(dashboard/web 자산·swarm 경로·triage/palette 등)는 9b77daa 구조
개편의 잔재로 D-126 미접촉 파일의 구 경로 참조이며, 별도 백로그로 수용을 막지 않는다.

**Context:** 2026-09-19 작업 트리 결합도 실측에서 이음새 5곳이 나왔다.
S1 `core → control` 미선언 import 3건(`control_sensor_adapter.py:118,140,213`, `package.xml`에는 `control` 없음),
S2 `control`의 최종 `cmd_vel` 구독 잔재 2곳(`web_node.py:431`, `wander/node.py:36`),
S3 `fleet` 선언 과다(`exec_depend: core`이나 생산 코드는 `core_common.protocol.schemas`만),
S4 `gz_sim/swarm_bench.py`의 `fleet.swarm.*` 직접 import,
S5 `core_api_web/api/v1/*` 12개 모듈의 `core_features` 하위 7개 영역 직접 참조.
게다가 D-64 가드(`test_runtime_slices.py`)는 구 경로(`src/rosy_core`)를 가리켜 신 구조에서 검사하지 않는다.

**Decision:**

- 런타임 단일 프로세스(D-1) 유지. 새 ROS 패키지 없음.
- S0 가드 재건이 먼저다: `test/test_module_separation.py`에 가드 5개(CORE의 슬라이스 import 금지,
  control의 최종 토픽 문자열 금지, `package.xml` ⊇ 코드 import, `cmd_vel` 발행 1곳, fleet 생산 코드는
  `core_common`만). 가드는 mutation-prove한다.
- S1은 provider 역전으로 닫는다 (D-63의 "토픽 경계" 예고를 이 메커니즘으로 이행): 어댑터가
  `control.*`를 정적으로 import하지 않고, worker/policy/calibration loader를
  `rosy.sensor_provider` 엔트리포인트(`control.sensor_provider:PROVIDER`) 또는 생성자
  주입으로 받는다. 검증(프로파일 revision·sensor-only·명령권 deny-list·보정 바인딩·측정
  파라미터 allow-list)은 CORE에 남아 덕타입 데이터에 동작하므로 provider 부재·변형은
  fail-closed. worker 생성은 스트림이 아니라 조립이라 토픽 경계로 바꿀 수 없고, 이 방식이
  D-1 단일 프로세스·무복사 handoff·호스트 테스트 가능성을 모두 보존한다. D-64의 `ALLOWED` 집합은 비운다.
- S2는 토픽명 개명·삭제(핀된 레거시 발행자 선언 1곳은 parity 계약으로 유지),
  S3은 `exec_depend: core_common`(+ 시험용 `test_depend: core_features`),
  S4는 시뮬→함대/내비 하향 의존 선언으로 고정,
  S5는 `CoreServicesLike` Protocol + `rmw.py→core_common`·`host_agent_client.py→api` 이동으로
  `core` 역참조만 제거한다. `core_features.*` 직접 참조는 선언 범위 안이라 유지한다 (X5).
- `core_features` 추가 분할과 멀티 프로세스화는 하지 않는다. 전자는 B1~B3 미충족, 후자는 D-125에서 보류한 Option B다.

**Alternatives:** 미선언 import를 선언으로 덮기(`package.xml`에 `control` 추가하고 끝내기) —
싸고 거짓말을 없애지만 D-63 끝 상태(토픽 경계)에서 멀어지므로 S1의 중간 단계로도 채택하지 않는다.

**Consequences:** S1·S5는 동작 불변 리팩토링이며 각 단계마다 기존 어댑터·api 시험이 PASS해야 한다.
Accepted 조건은 가드 5+1 초록과 관련 회귀 전체 PASS다. SOURCE/LOCAL 증거만 만들며
ARTIFACT/DEVICE/FIELD gate는 변하지 않는다.

**Validation / Transition:** `test/test_module_separation.py`, `src/core/core/test`,
`src/apps/control/test`, `src/site/fleet/test`, `src/sim/gz_sim/test`.

**References:** D-1, D-2, D-38, D-62, D-63, D-64, D-125.
설계: `docs/plans/2026-09-19-full-module-separation-design.md`,
실행: `docs/plans/2026-09-19-full-module-separation.md`.
