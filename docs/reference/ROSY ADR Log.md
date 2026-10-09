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
| D-22 | Raspberry Pi OS 런타임: Core/I/O 컨테이너 분리 + 드라이버 deadman | Superseded by D-161 (safety intent retained) |
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
| D-88 | Fleet 소켓은 사이트 PC 산출물이며 D-83 뒤에 연다 | Partially superseded by D-154 |
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
| D-127 | 276커밋 백로그는 직접 FF 푸시하지 않고 슬라이스별 단계 통합한다 | Accepted |
| D-128 | Level-3 구 경로 시험 잔재는 별도 백로그로 묶고 D-125/D-126을 막지 않는다 | Accepted |
| D-129 | L1 토큰 파일은 하나이고 어휘 표는 보인다 — D-92 제1항을 대체한다 | Accepted |
| D-130 | L2 문법 분리는 게이트가 지키고, 로직 행위는 headless로 한 번 뽑는다 | Accepted |
| D-131 | Fleet 콘솔은 군집 제어의 말을 되풀이한다 — 세 단계로 | Accepted |
| D-132 | 무장은 스트림이 연 뒤에 한다 | Accepted |
| D-133 | CORE SIGSEGV 는 재현 경로로 쫓고, 흔들리는 환경에서의 반복은 폐기한다 | Accepted |
| D-134 | 릴레이 준비 신호는 실측으로 말한다 | Accepted |
| D-135 | CI 러너는 Ubuntu 버전을 고정하고, 다음 LTS 이동은 기한 전에 리허설한다 | Accepted |
| D-136 | 영상 대역폭은 예산으로 다룬다 — 경로 분리 + 상한 + 자동킬 | Superseded by D-152 |
| D-137 | YOLO는 자문역이다 — LiDAR/IR가 결정하고 영상은 증거만 낸다 | Proposed |
| D-138 | 도크 검출기는 센서 provider 포트를 탄다 — 새 정적 간선 없음 | Accepted |
| D-139 | OS는 자리만 내고, 무엇을 볼지는 제품이 정한다 | Accepted |
| D-140 | ARM64 소스 검증은 공개 arm64 러너로 매주 리허설한다 — ARTIFACT gate 의 코드 수준 선검증 | Accepted |
| D-141 | 대형 주행 실측은 네 게이트를 순서대로 통과한다 — 단일 세션 묶음 | Accepted |
| D-142 | 실물 전에 소프트웨어 계약을 닫는다 — 잔여 3건 | Accepted |
| D-143 | IR·카메라 차선 추종은 NAVIGATION 내부의 배타적 evidence 소스다 | Accepted |
| D-144 | 하드웨어 맵 생성은 runtime mode가 아니라 검증된 navigation backend다 | Accepted |
| D-145 | 네이티브 ARM64 빌드는 unsigned artifact까지만 자동화한다 | Accepted |
| D-146 | unsigned ARM64 handoff는 검증 후에만 오프라인 서명 입력이 된다 | Accepted |
| D-147 | src 패키지를 6개 도메인 그룹으로 재편한다 — 소급 공식화 | Accepted |
| D-148 | 벤치는 fleet이 소유한 공개면(fleet.bench)만 소비한다 | Accepted |
| D-149 | control 단독 모드의 최종 발행 토픽은 계약된 예외다 | Accepted |
| D-150 | web_node는 control 디버그 서피스로 잔류하고 맵의 단일 홈은 navigation/map이다 | Accepted |
| D-151 | 도로 의미 인식·정책·최종 명령을 분리하고 관제 변경은 정지 상태에서만 적용한다 | Accepted |
| D-152 | CORE 관제의 카메라 표시는 저주기 최신 1장 preview 예외다 | Accepted |
| D-153 | UI/UX 평가는 세 계층이고 판정 단위는 표면이다 | Accepted |
| D-154 | 공통 OS 이미지와 장치별 SD 개인화를 분리한다 | Accepted |
| D-155 | Zero-Coupling AST Validation (Build-time Guard) | Accepted |
| D-156 | ROS 2 Namespace Strict Segregation (Runtime Guard) | Proposed |
| D-157 | Shared Headless UI Package (Monorepo Web Decoupling) | Accepted |
| D-158 | UI Component Consistency: Strict Outline Borders (Law 2) | Accepted |
| D-159 | State Summary Visibility: Management by Exception (Law 0) | Accepted |
| D-160 | Games Domain Strict Decoupling (AST Validation) | Accepted |
| D-161 | Ubuntu Server 24.04 + ROS 2 Jazzy 네이티브 제품 런타임으로 즉시 전환 | Accepted (supersedes D-22 runtime mechanism; 5항 컨테이너 범위는 D-246로 명시) |
| D-162 | 학습된 장면은 설정이지 권한이 아니다 — 장면 상황 프로파일은 등록·리비전·보수 폴백으로만 적용한다 | Proposed |
| D-163 | 신호등 관측은 제어와 분리된 읽기 전용 평면이며, 카메라 역할은 표시·계측·상태관측 셋으로 나눈다 | Accepted |
| D-164 | Pinky Pro 제품 산출물은 ISO가 아니라 서명된 Raspberry Pi 디스크 이미지다 | Accepted |
| D-165 | Pinky Pro 네이티브 ROS 패키지의 하드웨어 의존성도 이미지 입력으로 고정한다 | Accepted |
| D-166 | 과속 반응은 기록 전용이며, 자동 감속은 로봇 계약 확인과 판정 검증 후에만 상향한다 | Accepted |
| D-167 | 미들웨어 목표는 평가표로 측정한다 — 8개 판정 축과 기준선 | Proposed |
| D-168 | ROS 패키지 구조 기준 — 인정 조건, 필수 구성, 도메인 방향표를 시험으로 고정한다 | Accepted (영역 목록은 Superseded by D-231) |
| D-169 | v1 제품 장치 표면은 모터·LiDAR·카메라·I2C-1 ADC로 고정한다 — emotion/lamp/led/imu는 벤치 전용을 소급 공식화 | Accepted |
| D-170 | PRT-004 명령 추적 확장은 중앙 Fleet 착수와 함께 간다 — 그 전까지 correlation_id는 계약 전용 필드 | Accepted |
| D-171 | control 구조 개선은 host 시험 가능한 판단 비율로 재고, ROS 경계 → 노드 판단 추출 → 패키지 분리 순서로 한다 | Accepted |
| D-172 | 구조 개편 이전의 미병합 브랜치는 태그로 보존하고, 재구현·독립 리뷰를 거쳐서만 main에 들인다 — Python 3.12가 기준 | Accepted |
| D-173 | 첫 Pinky Pro 카드는 머지된 커밋의 서명 이미지를 검토된 plan에 고정해 굽는다 | Accepted |
| D-174 | 첫 실기 부팅 결함을 고치고, 부팅 상태는 CORE 밖의 표시 계층이 사람에게 알린다 | Accepted |
| D-175 | 디버그 로그는 CORE가 죽어도, 네트워크가 없어도, 장비가 없어도 읽을 수 있어야 한다 | Accepted |
| D-176 | 카드의 `rosy-config.yaml`로 기본 설정을 심고, 업링크가 없으면 카드별 비밀번호의 AP를 연다 | Accepted |
| D-177 | correlation_id 3단계 추적과 AckPayload 확장은 중앙 Fleet 착수와 같은 변경에서 함께 구현 — 활성화 시 설계를 선기록 | Superseded by D-297 |
| D-178 | 모듈의 병렬 작업 가능성은 평가표로 측정한다 — 5개 판정 축(M1–M5), 컷 게이트, 기준선 | Accepted |
| D-179 | 벤치 CORE 수정은 설치 트리 위의 읽기 전용 바인드이고, 그 장치는 릴리스로 세지 않는다 | Accepted |
| D-180 | SD 카드 기록은 전체 readback 한 번으로만 검증하고, Imager 검증과 raw 해시 사전 패스는 끈다 | Accepted |
| D-181 | 벤치 장치의 제품 편입은 장치별 실기 수요·D-84 프로필 항목·배관/capabilities/가드가 한 변경에서 충족될 때만 — 조건과 절차를 선기록 | Proposed |
| D-182 | 안전·명령·내비게이션 코드는 시뮬 파티션과 도메인 리터럴을 모른다 | Accepted |
| D-183 | 그래프 감시는 제품 그래프와 control 단독 그래프를 나눈다 | Accepted |
| D-184 | 동작 시험은 그 패키지가 가지고, core 시험은 공개 계약만 본다 | Accepted |
| D-185 | control 런타임 CPU는 측정한 비용 순으로 줄이고, 항목마다 검증 방식을 미리 정한다 — R1–R8 | Accepted |
| D-186 | 스크립트와 수집 데이터는 주인 폴더에만 둔다 | Accepted |
| D-187 | SD 카드 writer는 자기 실패를 감지해 안전하게 멈추고, 카드 상태와 다음 행동을 알린다 | Accepted |
| D-188 | SD 카드 쓰기는 전문가 없이 운영한다 — 분리 실행, 상태 명령, readback 멈춤 감시, 사전 속도 측정, 카드 신원 | Accepted |
| D-189 | unit의 샌드박스·HOME·Python 의존성은 제품의 일부다 — 서명 전에 실제로 돌려 보고 통과시킨다 | Accepted |
| D-190 | 부팅 표시는 공식 Pinky Pro와 같게 동작한다 — 증거 먼저, 장치 편입은 한 변경에, 장치에서 즉석 수정하지 않는다 | Proposed |
| D-191 | 이미지는 실기 평가표가 모두 PASS(또는 사람 대기)일 때만 배포한다 — 격차는 스토리 하나씩 저장소→이미지→카드로 닫는다 | Proposed |
| D-192 | 하드웨어 런타임은 이미지에 들어간다 — UART4·LiDAR 드라이버·DYNAMIXEL SDK·rosylib·io unit을 굽고, 기본은 CORE-only와 무동작이다 | Proposed |
| D-193 | 대시보드 로그인은 로봇 화면의 일회용 코드로 한다 — 장기 토큰은 화면에 띄우지 않고, 장치 기본값에는 로그인이 없다 | Proposed (D-352가 개정: pair-site 수명, operator 회수) |
| D-194 | 브라우저 조작 부품은 한 벌이다 | Accepted |
| D-195 | 치수와 진단 팔레트도 닫힌 집합이다 | Accepted |
| D-196 | 로봇은 장치의 조합이다 — `src/devices/<계열>/`과 `src/robots/<robot>/`을 두고, 로봇 지식은 그 안에만 둔다 | Proposed (추가 2026-10-01: 로봇 패키지 `config/core.yaml` CORE 설정 층) |
| D-197 | Docker는 제품 아티팩트 체인에서 퇴역한다 — 제품 경로의 신규 Docker 의존은 지금 금지하고, OCI·Compose 체인은 native payload가 ARTIFACT를 통과하면 한 변경으로 정리한다 | Accepted (비안전 사이드카 레인은 D-246가 한정 허용) |
| D-198 | Docker 시대의 장치 운영면을 철거한다 — 안전 검증 게이트의 native 대체는 지금 만들고, 설치기·모드 전환은 대체 없이 폐기한다 | Accepted |
| D-199 | 카메라 인식은 두 층의 고정 계약과 교체 가능한 백엔드로 나눈다 — 규칙 기반으로 시작하고 학습 모델은 같은 자리에 끼운다 | Proposed |
| D-200 | 도킹은 DOCKING 모드와 전용 명령 슬롯을 쥔다 — 모든 도크 기종이 처음부터 끝까지 DOCKING에서 움직인다 | Accepted |
| D-201 | 고정 문법 표면의 적합 계약 — 스크롤도 아니고 분쇄도 아니다: 선언 뷰포트에서 문서가 스크롤되지 않고 조작이 눌려 사라지지 않으며, 목록만 프레임 안에서 스크롤되고 안전 조작은 항상 보인다 | Accepted |
| D-202 | 위험은 채움이다 — 경보 텍스트의 대비 계약: status-crit는 글자색으로 쓰지 않고, 따뜻한 색 글자는 4.5:1 이상이어야 한다 | Accepted |
| D-203 | 계산 척급 폐쇄 — 화면에 보이는 계산 폰트 크기는 토큰 여섯 단계뿐이다: 선언이 아니라 렌더 결과가 닫혀 있어야 한다 | Accepted |
| D-205 | 실물 차선 미션으로의 전환: 시뮬레이션 현실화, 인식 재작업, 재합격 순서 | Proposed |
| D-206 | P0 실측은 기록지가 표준이고 확정 카메라 프로필은 revision으로 보관한다 — 게이트 판정은 프로토타입 `camcal`로 잇고 `src/robots/pinky_pro/config/`은 D-196 머지 뒤 만든다 | Proposed |
| D-207 | 제품과 장치 종류는 주인이 하나다 — 제품 기록은 src/products, 새 칩은 종류 안의 구현, 조명 두 서비스와 현장 펌웨어와 맵은 부르는 쪽에 둔다 | Proposed (결정 5의 루트 위치는 Superseded by D-231) |
| D-208 | 감지 프로파일은 속도를 발행하지 않는다 — full만 D-149의 단독 최종 발행 예외이고 sensing은 safety_node와 Twist 발행자를 만들지 않는다 | Accepted |
| D-209 | 인식과 학습 백엔드의 자리 — 몸통 인식은 control/sensing/perception, VLA는 backend_learned, 재생과 학습 세트는 로봇 이미지 밖 | Accepted (§4 D-427이 부분 대체) |
| D-210 | 실사용 1차 범위 — 2대 관제+군집을 실물 1대+시뮬 1대로 닫는다 | Proposed |
| D-211 | ROS-SIM 재실행 묶음 — 현재 트리에서 2대 관제+군집을 증명한다 | Proposed |
| D-212 | ARTIFACT 네이티브 경로 — Pi 5에서 서명 이미지까지만 간다 | Proposed |
| D-213 | DEVICE→FIELD 승격 순서 — 실물 1대 stationary부터 2대(실물+sim) 현장 반복까지 | Proposed |
| D-214 | 텍스트 대비의 바닥 — 모든 보이는 글자는 4.5:1(큰 값 3.0:1) 이상이다: 팔레트는 표면의 자유지만 읽힘은 청중의 권리이며 선택도 읽기를 희생하지 않는다 | Accepted |
| D-215 | 명령 추적 `TIMEOUT`은 Fleet 기록 전용 상태다 — 로봇 ack enum에 넣지 않는다 | Accepted |
| D-216 | CAP-001 예시의 `protocol_version` 오타를 고친다 — `"1"`이 아니라 `"1.0"`이다 | Accepted |
| D-217 | SEC-102의 CORS 문장을 좁힌다 — 로봇 API는 CORS를 제공하지 않는다 | Accepted |
| D-218 | 확인 문법의 졸업 — 네이티브 confirm이 공유 컴포넌트다. alert/prompt 금지, confirm은 핀된 횟수, 없는 조종은 버튼이 아니다 | Accepted |
| D-219 | 운용 요약 어휘의 실행 계약 — D-159를 Accepted로 승격하고 Fleet 큐 규칙을 콘솔 분류와 같이 고정한다 | Accepted |
| D-220 | 정지 계약 — 움직임 예산은 0이다. 보이는 요소의 전이와 애니메이션은 없다 | Accepted |
| D-221 | 얼굴 웨이크 카드의 어휘 — 라벨은 기계 약어로 남는다: 행인의 채널은 형태·색·만료이지 글자가 아니며, 폰트 의존(이미지에 CJK 폰트 없음)과 enum 값 번역 없는 라벨 번역은 다 이득이 없다 | Accepted |
| D-222 | First-boot 소비자는 `rosy-first-boot.py` 하나다 — `apply-sd-provision.py` stub을 폐기한다 | Accepted |
| D-224 | 표면의 키보드 어휘 — 약속한 키는 동작한다: Fleet 로스터 ↑/↓ 순회·Enter 목표·Escape 해소, 게임 스페이스는 /stop 1회, 카드 착지점은 tabindex -1 | Accepted |
| D-225 | 카드 재기록은 마지막 수단이다 — 기존 로봇은 서명 payload 전환으로 갱신하고, 남는 재기록은 리더·재개·이미지 크기로 줄인다 | Proposed |
| D-226 | 문서는 공개 여부를 먼저 가르고, 그다음 주인 폴더에 둔다 — 비밀·식별·권리 불명·전략 초안은 private/, 코드가 읽으면 데이터, 날짜 증거는 docs/validation, 모듈 설명은 모듈 docs/ 하나, 출처 있는 자산 묶음은 통째로 | Accepted |
| D-227 | 여섯 책임은 지금 트리 위의 이름이다 — 새 루트와 명령 봉투와 AI 워커는 만들지 않는다 | Proposed (결정 1은 Superseded by D-231) |
| D-228 | 판단은 core_features/decision 이다 — 런타임 개명과 제품 이름 패키지는 만들지 않는다 | Accepted |
| D-229 | 모듈 경계는 지금 폴더를 따라 한 방향으로만 흐른다 — 인식은 증거, 판단은 동작 id, 추종기는 FOLLOW 다음의 속도 | Accepted |
| D-230 | SD writer 멈춤은 두 단계로 다룬다 — soft 경고, hard 중단, CLI 진행률 우선 | Accepted |
| D-231 | 소스 영역은 층으로 나눈다 — contracts·runtime·devices·products·hmi·site·sim과 firmware/, 디렉터리만 옮기고 패키지 이름은 유지, 제품 이름 런타임·src 안 AI 워커·원격 판단 경로·새 액션은 받지 않는다 | Accepted |
| D-232 | OMX 제품 설정은 products/omx 이고, 보드 핀맵과 AI 자리는 그대로다 | Accepted |
| D-233 | 디자인 시스템 초안 — 토큰 동결, 컴포넌트 3층 | Accepted |
| D-241 | core 계열 폴더는 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다 | Accepted |
| D-242 | 나머지 폴더도 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다 | Accepted |
| D-243 | 운용 화면은 hmi 에 두고 API 는 런타임에 둔다 | Accepted |
| D-245 | E-Stop 파일럿 — 종류·물음형·권한 병기 | Accepted |
| D-246 | 런타임 유연성 — 네이티브가 기본값이고 컨테이너는 선언된 비안전 워크로드에만, 장치별 차이는 profile/slice로만 | Accepted |
| D-247 | 대시보드는 보드의 모든 장치가 붙어 있고 응답하는지를 보여준다 — 장치 관측과 제품 기능을 가른다 | Proposed |
| D-248 | AuthBar — 잠금 폴링 중단 | Accepted |
| D-249 | FieldMap — spec 고정, 코드 미추출 | Accepted |
| D-250 | TeleopHold — 홀드-티커 추출 | Accepted |
| D-251 | 절차 카드 — 크롬 규칙 고정 | Accepted |
| D-252 | Fleet 큐·대형 — 머리 triage·대기 요약 | Accepted |
| D-253 | 게임·진단 마무리 — 관전 없음·진단 동결 | Accepted |
| D-254 | 디자인 철학과 토큰 전집 | Accepted |
| D-255 | UI/UX 평가 회차 2 | Accepted |
| D-256 | 공개 무결성 값은 이름으로 지우고, 스캔는 매처를 넙히지 않는다 | Accepted |
| D-257 | 사이트 관제 지도는 차선 그래프 — 로봇 위치는 폰 천장 카메라가 보고, 영상은 Fleet 밖에서만 | Proposed |
| D-258 | 디자인 리뷰 루프 | Accepted |
| D-259 | 지도 키보드 조작 | Accepted |
| D-260 | 로봇은 부팅음·LED·LCD·운용 화면 요약줄 네 곳에서 같은 상태를 같은 말로 보여준다 | Proposed |
| D-261 | 천장 카메라 안드로이드 앱 — 골격 범위·위치·기술·첫 버전 약속 | Accepted |
| D-262 | 웹 예산 판정 제안 | Proposed |
| D-263 | 메뉴는 사용자의 질문을 찾는 길이다 — 화면 책임과 확장 규칙 | Accepted |
| D-264 | 장치 진단 도구는 이미지에 넣는다 — 읽기 도구(i2c-tools·pinctrl·gpiod·rpicam-apps)는 제품 이미지에, 커널 헤더는 디버그 프로필에만 | Proposed |
| D-265 | 기반 화면은 패널 수와 무관하게 남는다 — 메뉴·정지 진입 계약 | Accepted |
| D-266 | 진단 PARKED 해제 조건 | Proposed |
| D-267 | Ubuntu 상시 관제 노트북은 Fleet·영상·GPU·저장을 분리하고 자동·수동 작업을 같은 검증 경로로 처리한다 | Proposed |
| D-268 | Fleet 자동 작업은 sighting이 아닌 별도 수용된 정책 증거만 사용한다 | Proposed |
| D-269 | 장비는 역할별 계약으로 사이트 서버에 접속하고 DDS는 CORE 안에 둔다 | Proposed |
| D-270 | 역할 게이팅은 표면이 정한다 | Accepted |
| D-271 | 사이트 Fleet이 작업 순서를 소유하고 브로커는 실행 전달에만 쓴다 | Accepted |
| D-272 | AP 비밀번호는 로봇마다 다르되 읽기 쉬운 형식과 LCD QR로 보여준다 | Accepted |
| D-273 | OMX 팔 제어와 작업 카메라 스트림은 고정 작업대에서 단계별로 결합한다 | Accepted |
| D-274 | 로컬 브라우저 검토는 실제 CORE 경로를 쓰고 장치 수용은 분리한다 | Accepted |
| D-275 | 웹 화면과 영상 처리는 실행 위치와 권한별로 나눈다 | Accepted |
| D-276 | 사이트 Fleet API는 개인별 credential과 역할로 요청을 인가한다 | Accepted (전용 사이트 정지의 명령 전 감사 실패 규칙만 D-330이 대체) |
| D-277 | ROSY 이름 색은 장미색 토큰으로 식별한다 | Accepted |
| D-278 | 역할별 표면은 작업 흐름으로 구분하고 색은 의미를 지킨다 | Accepted |
| D-279 | 역할별 빈 상태와 복구 안내 | Accepted |
| D-280 | ROSY 제품 디자인 철학은 차분한 지능에 은은한 따뜻함이다 | Accepted |
| D-281 | 장비·실행 인스턴스·호스트를 분리해 OMX 한두 대의 공유/분리 배치를 검증한다 | Proposed |
| D-282 | 장치별 ROS 실행 인스턴스가 할당된 하드웨어만 소유한다 | Proposed |
| D-283 | 운용 콘솔은 고정 3영역을 유지하고 조작 그룹을 선택한다 | Accepted |
| D-284 | 역할 화면의 상태·복구 표현은 공용 UI 부품과 Rosy 토큰을 사용한다 | Accepted |
| D-285 | 역할별 패널은 공용 폼 배치와 필드 라벨 패턴을 사용한다 | Accepted |
| D-286 | 역할 패널의 라벨·값 목록은 공용 readout 배치를 사용한다 | Accepted |
| D-287 | 역할 패널의 읽기 전용 섹션은 공용 readback 배치를 사용한다 | Accepted |
| D-288 | Pinky Pro Pi 5 카메라 사용자 공간은 공식 소스를 고정해 네이티브 이미지에서 빌드한다 | Proposed |
| D-289 | Role console entry, action groups, and map readout | Accepted |
| D-290 | ROSY Platform 이름과 현장 대화·미션·통신 책임을 구분한다 | Accepted |
| D-291 | Pinky Pro 첫 부팅은 무구동 I/O를 포함하고, 제어 변경은 새 서명 이미지로 SD에 기록한다 | Accepted |
| D-292 | 시각 토큰은 의미·기초 척도·컴포넌트 역할로 나누고 메뉴마다 다시 쌓지 않는다 | Accepted |
| D-293 | 사이트 Fleet API는 의도를 받고 서버 규약으로 해석한다 | Accepted |
| D-294 | Shared typography and interaction tokens use a closed scale | Accepted |
| D-295 | 네이티브 Pinky의 주행·맵핑 능력은 실행 모드와 검증 기록에 맞춰 공개한다 | Accepted |
| D-296 | 장치 미들웨어와 사이트 조정 계층의 이름과 책임을 구분한다 | Accepted |
| D-297 | 명령 ACK와 Fleet 추적 레코드를 분리한 PRT-004 활성화 설계 | Proposed |
| D-298 | Fleet 미션·장치 액션·정지 증거의 용어를 분리한다 | Accepted |
| D-299 | OMX LeRobot 실험 경로와 운영 팔 제어권을 분리한다 | Proposed |
| D-300 | Surface typography and focus feedback use shared tokens | Accepted |
| D-301 | Site Fleet 후보 묶음은 오프라인 Ed25519 서명으로 발행자를 인증한다 | Accepted |
| D-302 | Site Fleet 사용자 API와 CORE registry 자격 증명을 분리한다 | Accepted |
| D-303 | 소스 폴더는 로컬 제어 권한과 사이트 정본을 먼저 드러낸다 | Rejected (D-231 유지; 제품별 실행 루트·배포 개명 보류) |
| D-304 | 플랫폼 확장은 제어권·계약·배포 증거로 경계를 결정한다 | Superseded by D-305 |
| D-305 | 플랫폼 경계는 안전 결과 불변식과 독립 검증 게이트로 판정한다 | Accepted (결과 불명 표시 조건은 Superseded by D-307) |
| D-306 | 화면별 책임과 UI/UX 개선 완료 기준 | Accepted |
| D-307 | 장치 최종 결과와 물리 정지 증거를 별도로 판정한다 | Accepted (D-305 결과 분류 정정) |
| D-308 | 의도 해석과 장치별 Action 해석의 책임을 분리한다 | Accepted (의미·소유권·검증 기준; D-293 Decision 2 적용 범위 명확화) |
| D-309 | UI/UX의 프론트·백엔드 책임과 시간·예외·안전 증거를 분리한다 | Accepted (구조 결정; 화면 G2/G3 및 실물 수용은 별도 HOLD) |
| D-310 | 제품 전용 소스와 장치 로컬 실행 소스를 구분한다 | Accepted (기존 8개 패키지 소스 배치에 한정; D-231·D-305 위치 조항 부분 대체; native ARTIFACT·DEVICE/FIELD HOLD) |
| D-311 | 네이티브 G4 실측 증거를 내비게이션 기동 조건으로 검증한다 | Accepted (소스 결정; 장치·현장 수용 HOLD) |
| D-312 | G4 정지 시험은 지면에서도 제한된 이동량으로 수행한다 | Accepted (소스 결정; 실물 G4/G5 HOLD) |
| D-313 | 전면 카메라 고장 시 관제 영상과 로컬 센서로 제한된 시연을 선택한다 | Accepted (구조·작업 선택; 구현·장치·현장 HOLD) |
| D-314 | 지면 G4는 실측으로 간소화하고 수동 운전의 반복 확인을 없앤다 | Accepted (소스 결정; 장치·현장 수용 HOLD) |
| D-315 | 소스 폴더 책임은 소스 분류이며 실행 권한·배포 단위를 대신하지 않는다 | Accepted (분류·문서 기준만; 패키지명/경로·writer·설치·장치 수용 변경 없음) |
| D-316 | Pinky Fleet task의 dispatch attempt ID를 CORE navigation 결과까지 연결한다 | Accepted (Site Fleet SOURCE/LOCAL; PRT-004·물리 정지 readback 별도) |
| D-317 | 장치별 해석과 공유 계약은 실제 소비·실행 경계로 분류한다 | Accepted (현재 소스 배치와 후속 재배치 기준; 새 패키지·API·운영 수용 없음) |
| D-318 | Site Fleet 관제 카메라 미리보기에 실측 렌즈·평면 보정을 지원한다 | Accepted (표시 전용 조정; 현장 보정·DEVICE/FIELD 증거는 별도) |
| D-319 | SETUP 뒤 현장 입회 하에 모터 구동 준비를 자동화한다 | Accepted (2026-09-29 사용자 승인; 무인 토크 활성화·G4 수용·현장 운영은 별도 게이트) |
| D-320 | 로봇 배포 소스는 제품별로 묶고 사이트 배포는 분리한다 | Accepted (소스 경로만; 설치 closure·OMX field runtime 별도 HOLD) |
| D-321 | 현장 보정과 G4 실측을 한 세션으로 모으고 지도 생성은 승인 뒤에 시작한다 | Accepted (설계 결정; 구현·서명 릴리스·실물 G4/G5 HOLD) |
| D-322 | Isaac Sim은 Gazebo와 별개 시뮬레이터로 연결한다 | Accepted (소스 설계·구현 범위; Isaac 실제 실행·ROS-SIM·DEVICE/FIELD 수용 별도 HOLD) |
| D-323 | 원격 조종 표면은 CORE가 same-origin으로 서빙하는 정적 PWA Rosy Pilot(src/hmi/pilot)이며 기기 종류별 드라이버 확장점을 v1 Pinky 주행과 함께 선행한다 | Accepted (설계·소스 배치 결정; 구현·장치·현장 수용 별도 HOLD) |
| D-325 | 기존 Pinky 배포는 변경에 맞는 가장 작은 산출물을 선택한다 | Accepted (산출물 범위 선택만; 서명·설치·장치 수용 게이트 유지) |
| D-326 | 자율 판단 루프는 네 역할로 분리 배치하고 재판단 밸브는 별도 승격으로만 연다 | Accepted (경계·자리 결정만; 구현·폐루프 개방·AI 승격 없음) |
| D-327 | 의미 기반 조작 Action과 장치별 ROS 실행 어댑터를 분리한다 | Proposed (의미·권한·검증 기준; API·운영 capability·DEVICE/FIELD 수용 아님) |
| D-328 | 모델 제안 Mission과 독립 목표 증거를 분리한다 | Proposed (Fleet 원장·장치 Action·목표 판정 경계; API·자동 dispatch·장치 수용 아님) |
| D-329 | 표면은 등록으로 계약을 받고, 육안 기준은 저장소에 남는다 | Proposed (표면 계약 적용 범위 단일 출처·G2 기준선 저장소 보존만; 번들러·공유 컴포넌트 코드·자동 픽셀 판정·D-153 체계 변경·DEVICE/FIELD 수용 아님) |
| D-330 | Fleet의 단일 발행 권한과 정지·재시작 차단을 Mission과 기존 작업에 공통 적용한다 | Accepted (구조 결정; D-276 전용 정지 감사 규칙 부분 대체; 구현·물리 정지 수용 HOLD) |
| D-331 | Gemini Robotics ER 2를 상태 비저장·제안 전용 Fleet provider로 연결한다 | Accepted (provider boundary/source adapter만; runtime/actuation/pilot HOLD) |
| D-332 | 사람 확인은 고정 단계가 아니라 조건이다 — 사전 등록 승인, 예외 조정, 자율 재발의 승인에만 둔다 | Accepted (위치·의미 결정만; 밸브 개방·자동 실행·구현 없음) |
| D-333 | ER 2 조작 후보의 Mission 승인, 장치 Action 수락, 정지와 목표 증거를 분리한다 | Accepted (계약 경계·구현 순서만; 신규 wire/API·장치 실행·물리 수용 HOLD) |
| D-334 | ER 2의 도구 목록과 진행 조회를 Fleet 원장 경계에 둔다 | Accepted (도구·진행 의미만; 새 provider loop/API·자동 실행·물리 수용 HOLD) |
| D-335 | 브랜드 홈 링크를 ui-brand 공용 동작으로 넣는다 | Accepted (ui.js href 동작 확장 + components.css가 hover·포커스 소유; 새 토큰·부품·문법 아님, /dashboard 목적지 회차는 별도) |
| D-336 | Fleet와 OMX 제어 owner 사이 첫 연결은 같은 호스트의 local IPC로 제한한다 | Accepted (SOURCE/LOCAL 연결 경계만; 배치·원격 API·물리 수용 HOLD) |
| D-337 | 로봇의 제2 신호 소스는 관측 서비스의 실측(빛)뿐이다 — ESP32 접점 주장(`/status`)과 신호등 명령 경로는 로봇이 소비하지 않고, 소스 불일치·소등은 진입을 허가하지 않는다 | Accepted (경계·융합 규칙 결정만; 폴러 구현·ROS-SIM·DEVICE/FIELD 수용 HOLD — 설계 `2026-09-29-robot-signal-source-integration-design.md`) |
| D-338 | 브리지 콜백의 판정은 ROS-free 시블리가 소유하고 ros_bridge는 적응만 남는다 | Accepted (2026-09-24 구현·2026-09-29 기록; 소스 구조 원칙만, 실기 콜백 증거 별도) |
| D-339 | 화면 제목과 폴더 이름은 역할을 드러낸다 — 패키지 이름은 그대로 두고 대응표를 시험으로 고정한다 | Accepted (표시 이름·폴더 경로·대응표; 패키지 이름 불변) |
| D-340 | 설치형 앱은 웹 표면을 감싸는 셸로 만든다 — PWA가 먼저, Capacitor 셸은 저장소 루트 `apps/`에 둔다 | Proposed (방향·위치만; apps/·npm 프로젝트 미생성) |
| D-341 | 천장 카메라 앱은 mDNS로 사이트를 찾고, 관제 콘솔 승인으로 연결 자격을 받는다 — 발견은 여전히 자격을 주지 않는다 | Accepted (2026-10-01 설계 수용; 신뢰 모델·첫 조각 계약·닫힘 코드 분류; 구현·DEVICE/FIELD HOLD — 계획 `2026-09-29-overhead-console-pairing-plan.md`) |
| D-342 | 실기 수동 한도는 녹화 증거로 한 계단씩만 올린다(L0 0.03·0.1 → L1 0.06·0.3 → L2 0.10·0.6) | Accepted (2026-09-29 절차; 이미지 기본값 불변) |
| D-343 | Pilot 은 로봇이 찾아 준 이웃 목록으로 방(로비)을 보이고, 로봇 한 대에는 운전석 하나만 둔다 | Accepted (2026-09-29 설계; D-340 셸 조건 2 기록; 구현·장치 HOLD) |
| D-344 | Pilot 의 자동 주행은 누르고 있는 동안만 진행하는 보조 자율이며, 스틱을 건드리면 즉시 수동이다 | Accepted (2026-09-29 설계; 가제보 검증 전 실기 금지) |
| D-345 | D-280 디자인 철학은 사람이 보는 모든 표면에 같은 방식으로 적용한다 — 웹이 아닌 표면도 레지스트리·토큰 사본 검사·이름 규칙을 받는다 | Accepted (적용 범위·색 원본·이름·알림 규칙; D-280 원칙 불변); 라이트 팔레트 금지 문장은 D-359로 대체) |
| D-346 | 병행 세션 충돌은 커밋 시점 검사로 막는다 — ADR 번호는 행 추가 즉시 선점하고 깨진 인코딩·중복 번호는 lint가 잡는다 | Accepted (2026-09-29, 저장소 도구·작업 규칙만) |
| D-347 | capability 상태는 단일 생애 어휘로 말한다 — 조정된 플래그별 lifecycle(ready/activating[예약]/unavailable)를 두 표면이 같은 함수에서 낸다 | Accepted (2026-09-29, 계약·어휘만; 그래프 기동·신규 이벤트 없음) |
| D-348 | 목표 증거 생산자 등록 계약과 검증기 연결은 Fleet이 소유한다 — 사람 확인은 등록 시점뿐, 종단 Action 뒤 자동 증거 검증으로 `GOAL_CONFIRMED`를 연다 | Accepted (2026-09-30, 등록·제출·검증 트리거 계약만; 실물 생산자·도구 개방·밸브 불변) |
| D-349 | 도크 자동 충전의 코드는 전부 준비됐다 — 남은 것은 물리 조립과 capabilities 전환뿐 | Accepted (2026-09-30, 준비 상태 기록; 실물 조립·D0–D5·분리력 실측은 별도 회차) |
| D-350 | 도크 하드웨어는 세 단계로 붙는다 — 선만(계측 없음)·ESP32(2소스)·향상(온도·카메라) — 각 단계에서 소프트웨어가 하는 일을 미리 정한다 | Accepted (2026-09-30, 단계 계약·선구현 착수; 실물 조립은 별도 회차) |
| D-351 | 도킹 재시도는 실패 종류를 가린다 — 도달 못 함은 재시도, 도달했는데 전류 없음은 즉시 폴트, 충전 중 단절은 DOCKED 유지 | Accepted (2026-09-30, 행동 결정 + 구현) |
| D-352 | 도크·신호등은 같은 패턴의 외부 장비다 — 폴링 실패 어휘·준비 프레임(wire/instrumented/verified)·계약 상호 참조를 공유한다 | Accepted (2026-09-30, 구조 결정 + 패턴 정리) |
| D-353 | 외부 장비 설계는 바뀐다 — 바뀌어도 코드가 아니라 설정·전략이 바뀌게 한다 | Accepted (2026-09-30, 구조 결정 + 봉합점 3개 구현) |
| D-354 | 외부 장비는 mDNS로 서로를 찾는다 — IP 하드코딩 없이, 전원만 연결하면 발견된다 (_rosy-dock._tcp·_rosy-signal._tcp) | Accepted (2026-09-30, 구조 결정 + 펌웨어·유틸리티 구현) |
| D-355 | 도크·외부 장비 구현은 자재→벤치→실기→활성화→통합의 5단계로 간다 — 각 단계의 게이트·의존성·완료 조건을 확정한다 | Accepted (2026-09-30, 실행 순서 확정; 구현은 플랜 참조) |
| D-356 | 인식 학습 루프 — 학습은 저장소 밖, manifest 약속·접수·데이터 세대 전달·섀도 추론은 안 | Proposed (2026-09-30, 섀도 전용; 주행 활성화는 D-205 P3 뒤 별도) |
| D-357 | ER 2 consumes bounded Fleet feedback and returns candidates while Mission/device control remain independent | Accepted (2026-09-30, standard provider feedback/tool-result boundary only; autonomous dispatch and physical acceptance remain HOLD) |
| D-358 | ER 2 feedback turns use trusted scope, fenced candidates, and explicit ambiguity | Accepted (2026-09-30, D-357 implementation contract refinement only; provider, policy dispatch, ROS/OMX, and physical acceptance remain HOLD) |
| D-359 | 테마는 팔레트 한 블록만 바꾼다 — 토큰을 팔레트·파생·역할로 나누고, 공용 부품이 표면별 사본을 대체하며, 반응형은 세 단 어휘를 쓴다 | Accepted (2026-09-30, 웹 토큰 구조·공용 부품·반응형·계약 시험; D-345의 라이트 팔레트 금지 문장 대체; 네이티브·LCD는 dark 고정) |
| D-360 | 천장 카메라 경기장 자동 검출은 제안일 뿐이다 — Vision이 네 모서리를 제안하고, 관제는 운용자가 확인한 모서리로 보정·마스킹한 경기장 뷰를 보여 준다 | Proposed (검출 위치·제안 API·불일치 표시·레이어 토글; 사이트 설정·sighting 반영 미결정) |
| D-361 | 사이트 콘솔이 로봇 화면 코드로 로봇을 등록한다 — Fleet이 코드를 로봇에서 직접 교환하고, 자격은 Fleet 소유 저장소에 둔다 | Proposed (등록 흐름·자격·결속·저장·수명 결정만; 구현·CORE 이미지·TLS·DEVICE/FIELD 수용 아님) |
| D-362 | 파일 크기 예산은 코드 유형별 단일 게이트가 지킨다 — 생산 `.py`/`.cpp`/`.hpp`/`.sh` 600줄, 웹 자산 `.js`/`.html`/`.css` 800줄, 1000줄 초과 파일은 성장 허용량 0; 게이트는 `src/` 패키지와 `deploy/`·`tools/`·`firmware/`까지 본다. 줄 수는 분할 근거가 아니라 `split`/`accept` 판정 의무의 트리거다 (X1 계승, D-168 P6 확장) | Accepted (2026-09-30, 정책·게이트 범위만; 시험 코드·데이터 파일 면제, 분할 실행은 계획 `2026-09-30-file-size-budget-and-refactor-queue.md`의 P0–P2 대기열) |
| D-363 | 주행 화면의 카메라는 원본 비율 그대로 잘림 없이 보이고, 조작부·HUD 는 영상을 가리지 않으며, 현장 운용은 설치 앱으로 연다 | Accepted (2026-09-29 화면; D-323 §5.2 풀블리드 변경; 운전자 배율 확대 보강) |
| D-364 | 차선 자동은 선을 따라가는 것이 아니라 차로 안을 지키는 것이며, 인식은 녹화 재생 벤치와 헤드리스 가제보에서 먼저 통과한다 | Accepted (2026-09-30 설계; 실물은 로봇 복귀 뒤 승인 핫픽스) |
| D-365 | Rosy Pilot 설치형은 PWA로 우선하고 Capacitor 래퍼는 네이티브 전용 수요가 실측될 때까지 보류한다 | Accepted (설치 형식 결정; 구현·장치·현장 수용 별도 HOLD) |
| D-366 | Rosy Pilot 조종 대상 확장은 기기 종류별 드라이버 레지스트리로 수용하며, 장치별 조종 컨트롤(그리퍼·팔 위치 등)은 그 장치의 계약이 열 때 프런트에 반영한다 | Accepted (로드맵·프런트 경계 결정; Pinky 가제보 최우선, 타 장치 수용은 각 게이트별) |
| D-367 | Rosy Pilot 의 체감 응답속도는 카메라 폴링 150ms·명령 루프 100ms·햅틱 10ms 로 잡는다 | Accepted (응답속도 설계; 실측 teleop 5ms 근거) |
| D-368 | 운전 중인 한 사람에게만 인증된 MJPEG 실시간 영상을 주고, 그동안만 로봇 미리보기 발행을 올린다 | Accepted (2026-09-29 설계; D-367 결정 1 대체, D-323 §5 부분 변경; 구현·장치 HOLD) |
| D-369 | Mission 제어·장치 실행·ROS 제어·안전 정지의 책임을 분리한다 | Accepted (2026-09-30, 사용자 확인 역할 경계; API 변경·provider/OMX 활성화·실물 수용 아님) |
| D-370 | 앱과 표면은 한 역할씩 맡는다 — 역할·이름·아이콘·화면 소유를 한 표로 고정하고, 발견·기기 연결·실패 어휘는 공유 벡터로 하나로 맞춘다 | Proposed (2026-09-30, 역할·이름·아이콘·화면 소유 규칙과 공유 조각·이행 순서만; 코드·리소스·와이어 변경 없음) |
| D-371 | 목록 행의 되돌릴 수 없는 행동은 조용한 버튼으로 시작하고, 위험 채움은 확인 단계에만 둔다 | Accepted (2026-09-30, 목록 행 한정; 비상정지·단일 대상·확인 실행 버튼은 위험 채움 유지; D-292/D-359 좁힘) |
| D-372 | 브랜치·worktree 이름은 처음부터 내용대로 짓고, 공유 main 체크아웃의 남의 작업은 지우지 않고 보존만 한다 — 접두어+주제(+ADR 항목), 한 브랜치 한 주제; 미커밋 남의 작업은 임시 인덱스로 주제별 브랜치에 보존·해시 검증, 되돌리기는 사용자 승인+24시간 무수정일 때만 | Accepted (2026-09-30, 작업 규칙만; D-346 규칙 5 확장) |
| D-373 | 학습 인식 두 번째 바퀴 — onnxruntime·모델 디렉터리는 Pinky 이미지 계층, 섀도·캡처는 기본 꺼진 페이로드, 불일치 60 s 스냅샷, 사이트 PC가 새 모델을 섀도까지 자동 반영; 정본은 store 폴더(로컬→NAS·Drive), HF는 선택 | Proposed (2026-09-30, 섀도 전용; 주행 활성화 자동화 없음) |
| D-374 | 앱의 폴더·패키지·식별자·표시 이름은 역할 이름 하나에서 나온다 — 역할 id(kebab)·snake·compact·표시 네 표기; 와이어 계약 이름(mDNS 종류, `rosy-overhead/1`, `/api/fleet`·`/api/vision`, `rosyov://`, 웹 경로, 설정·저장소 키, compose 서비스)은 바꾸지 않는다 | Accepted (2026-09-30, 사용자 결정: 규칙·대응표 그대로, 관제 화면 안 B(화면 자산만 `site_console`, 서비스 `fleet` 유지), 폰 재설치·재페어링 1회 수용, games·제어 진단·시뮬 라이브 뷰는 지금 제외; D-370 2항 "식별자 그대로" 대체, D-339 1항·D-231 2항을 앱 패키지에 한해 대체; 실행은 계획의 단계별 브랜치) |
| D-375 | 천장 카메라→지도 보정도 제안일 뿐이다 — Vision이 알려진 차선 페인트를 영상에 맞춰 homography·coverage·가려진 쪽을 제안하고, 운용자가 확인하기 전에는 어디에도 쓰지 않는다 | Proposed (2026-09-30, D-360 부록; `GET /api/vision/sources/{id}/map-proposal`, recall·precision·방향 차 거부 기준, 계산 중 읽기는 이전 결과 `X-Proposal-State: previous`; 관제 표시·수락은 브라우저 표시 초안(`GET /api/fleet/site-lanes`); 사이트 설정·`CameraMap` 반영 미결정) |
| D-376 | OMX PICK_PLACE planning stays local and trajectory execution stays with the Action owner | Accepted (2026-09-30, SOURCE contract and fail-closed planner gate only; production planner configuration, profile activation, ROS-SIM, DEVICE/FIELD acceptance remain HOLD/PARKED) |
| D-377 | 앱 이름 규칙: Rosy + 영어 한 단어 — 표시 이름 `Rosy <Word>`, id·폴더 끝 `<word>`, 패키지 `rosy_<word>`, Android `io.github.livsbittt.rosy.<word>`, Gradle `rosy-<word>`, 아이콘 `<word>.svg`; Rosy Cam·Vision·Console·Robot·Pilot | Accepted (2026-09-30, 사용자 결정; D-370 2항 이름표와 D-374 1·2항(규칙·대응표, `rosy_` 접두 금지 포함) 대체; D-374 3–5항(와이어 불변·재페어링·단계 게이트) 유지; Vision 실행 파일 `rosy-vision`, 옛 `site_vision`·`overhead`는 한 릴리스 별칭) |
| D-378 | 실물 로봇은 실물 녹화로 통과한 로직으로만 스스로 간다 — 주행 오류를 기록하고, 차선·정지선·신호는 재생 → 그림자 → 누르는 동안 순서로 들인다 | Accepted (2026-09-30, 오류 기록·도입 순서; 실물 반영은 단계마다 사용자 승인) |
| D-379 | 학습 데이터는 실물 세션 카탈로그로 모으고, 라벨은 주행 궤적·지도 투영·측정 신호로 자동으로 달며, 이 PC 저장소를 정본으로 Google Drive 에 사본을 둔다 | Accepted (2026-09-30, 사용자 결정; D-356 의 HF 전제를 대체) |
| D-380 | 램프는 로봇 상태(D-260)에 이어 운용 모드도 밝힌다 — CORE가 status-inputs 핸드오버에 RobotMode를 더해 넘기고, 같은 규칙표(core_common.robot_state)가 우선순위(실패 > 비상정지 > 주의 > 부팅 > 도킹 > 내비게이션 > 수동 > 준비)대로 램프 패턴과 LCD 상태줄 접미를 정한다. 모드 변경은 소리 없이 패턴만 바꾼다 | Accepted (2026-09-30, 램프·LCD가 건강 상태만 말하고 운용 모드는 대시보드에만 있던 갭; lamp_pattern.c에 manual/navigating/docking/emergency 추가, 부저는 D-260 결정 2의 건강 상태 전환에만 그대로) |
| D-381 | 막힌 내비게이션은 같은 청록을 2 Hz로 깜빡이고(blocked), 비상정지 진입은 2.5 kHz 네 번을 한 번만 울린다 — nav_state도 robot_mode와 같은 핸드오버·검증을 타고, 유지 중 무음·해제 시 ready 차임 | Accepted (2026-10-01, 사용자 위임; D-380 잔여 갭 two종 — BLOCKED/FAILED가 "가는 중"으로 보이던 것, 자발 정지의 무음; PLANNING·ARRIVED·CANCELED는 무늬 안 바꿈) |
| D-382 | 로봇 ↔ 사이트 관제 통신은 계약 스냅샷 하나로 판정하고, 실물 확인은 읽기 전용 적합성 탐침으로 시작한다 | Accepted (2026-10-01; 판정 기준·증거 등급·탐침 경계; 이미지 교체·토큰 발급·이동 명령·관제 DEVICE 수용 아님) |
| D-383 | 편대 역할은 계기 셋의 네 번째 칸 — swarm.role가 leader/follower일 때만 나타나고(기본 hidden, hidden이 flex를 이김) 한국어 라벨·색 없음(역할은 경보가 아니다), 식별줄은 software_version을 계보에 함께 말한다 | Accepted (2026-10-01, 사용자 요청·위임; emoji 대신 기존 계기 문법·토큰 체계, D-280/D-82/D-359 준수; 렌더는 telemetry.js가 담당 — D-362 분할) |
| D-384 | 도로 상태 추정기와 도로 주행 행동 — 주행기록계 예측으로 선이 사라져도 예상 도로를 잇고, 모르면 오른쪽(우측통행 동점 규칙), 모든 교차로 일단정지·양보·추월 없음 | Proposed (rev 4; R0 replay run on 124745Z, road-side failures owned by the estimator; R2 gated on validated_on_curves) |
| D-385 | Rosy가 스스로 표현한다 — 모드가 표정을 고른다(IDLE basic·MANUAL interest·NAVIGATION happy·DOCKING fun·EMERGENCY sad, 막힘은 bored)를 set_emotion 으로 LiDAR 문법(재시도) 전달, 부팅 카드는 BOOTING 중 무대 제목이 0.5 Hz 두 밝기로 숨쉬고 끝난 상태는 고요, 절전의 "꼭 필요한 것만"은 기존 WAKE_BATTERY 체계로 확인·문서화 | Accepted (2026-10-01, 사용자 요청·위임; 표정에 깜빡임 축 없음 — 모드 변경 시 한 번, D-280/D-82 준수) |
| D-386 | OMX phases bind asynchronous ROS goal acceptance and fresh execution state | Accepted (2026-10-01; SOURCE contract only; ROS-SIM, profile activation, ARTIFACT, DEVICE/FIELD remain gated) |
| D-387 | 로봇은 카드 이미지까지 네 계층(payload·이미지 계층·기반 시스템·전체 이미지)을 서명 릴리스로 네트워크에서 받는다. 스테이징은 자동이고, 적용은 운영자 승인과 호스트 소유 정비 리스(/run/rosy-maintenance + /var/lib/rosy 영속 기록)가 있어야 하며, 로봇 위 systemd-run 트랜잭션이 journal로 한다. 쓰지 않거나 도킹한 로봇부터 한 대씩(canary 10분), 부적격은 건너뛰고 되돌림이 나면 멈춘다. 3계층은 revert가 있는 멱등 migration과 나란히 설치한 런타임, 부팅 변경은 단독 릴리스로 rosy-a/rosy-b 두 os_prefix 슬롯과 tryboot로 한다. 4계층은 A/B(GPT, 32 GB 이상, RAUC 1순위). P1~P4에 게이트를 둔다 | Accepted (2026-10-01; 사용자 승인 — "승인 후 자동"과 다섯 기본값, 독립 리뷰 ACCEPT WITH EDITS 반영; 문서만, 구현 GO·DEVICE 아님) |
| D-388 | 페이로드 릴리스를 올리면 이미지 계층도 활성 릴리스 사본으로 맞춘다 — 릴리스에 실린 `sync-image-layer.py`가 검증된 `/opt/rosy/current`에서 native-runtime·rosy 유닛·udev·modprobe 허용 목록만 백업 후 원자 설치(드라이런·멱등·재시작은 호출자); `rosy-release-push.ps1`이 활성화·롤백 뒤 실행, `-SkipImageLayerSync` | Accepted (2026-09-30, 호스트 시험만; 실기 실행 대기; D-225 확장) |
| D-389 | 긴급 카드 쓰기(`write-card.ps1 -Emergency -EmergencyReason`)는 전체 readback만 건너뛰고 서명·시리얼·plan·ERASE 게이트와 MBR 점검은 지킨다; receipt·진행 파일·상태가 검증 안 됨을 적고, 후속 readback(`verify-emergency-card.ps1`)이나 표준 재기록으로 메운다 | Accepted (2026-10-01, CPU 부족으로 readback 1.5 h ETA였던 release 009 카드의 로컬 stub을 대체; 긴급 receipt는 표준 재공급에서만 수용) |
| D-390 | Pilot의 OMX-AI 연습은 시뮬레이션 전용 장치 API를 거쳐 로컬 팔 명령 소유자에 연결한다 | Accepted (2026-10-01, 설계·실행 순서 결정; API·Pilot·Gazebo 통합과 ROS-SIM·실물 수용은 별도) |
| D-391 | 앱은 사이트 연결을 같은 모양(이름·CA·자격, IP 없음)으로 저장하고, 기기 연결 서버는 Fleet "기기 연결"이 맡는다 | Proposed (2026-10-01; 사이트 연결 기록 모양·사이트 호스트 설정 원천·기기 연결 구현 순서; 구현·담당은 결정 회차) |
| D-392 | 모델 도구 호출은 provider 중립 메시지 계약과 Fleet 소유 allowlist를 따른다 | Accepted (2026-10-01, 내부 호출·결과 경계; 도구는 요청이지 device Action이 아니며 actuation·stop/E-stop 권한과 provider 활성화는 미결정) |
| D-393 | Pinky 트랙 Nav2 위치추정은 AMCL `update_min_d` 0.02, 목표 허용오차 0.05 m / 0.10 rad, 주차 자세 출발·global localization 금지 운용 규칙을 제안한다 | Proposed (2026-10-01; sim 1대 n=1 증거, 설정 미변경; 반복 sim A/B와 승인된 실물 주행 전 적용 안 함) |
| D-394 | 화면 카드는 계약이고 장치는 프로파일이다 — display/info 페이로드의 kind 디스패치(render_card 단일 입구)가 재사용 단위, 장치는 DisplayProfile(size·animation) 하나로 말하고 색은 토큰 사본이 유일, 운용 중에만 20 s마다 5 s 주행 카드(kind: drive — 큰 모드 단어·속도·배터리, 결측 속도는 None), 전자잉크(animation=False) 렌더러 자리 예약 | Accepted (2026-10-01, 사용자 요청·위임; IDLE에 얼굴이 주인, 발행은 기존 display/info 퍼블리셔 재사용) |
| D-395 | Fleet 보조 위치 확정 — 로봇(sensing)이 LiDAR 전역 탐색 후보(적합도·페인트 점수·지도 밖 물체)를 CORE로 올리고 Fleet arbiter가 채점·중재, 확인 기동 → CORE 실행 귀환 미션 → "위치 확인 필요" 사다리, 상태 UNKNOWN/CANDIDATES/LOCALIZED/SUSPECT(자율 주행은 LOCALIZED만), 출발 슬롯은 바닥 기준 사각형 2개(A·B, 영상 유래 ±3 cm)가 사전 정보이자 귀환 기준점(벽 모서리는 대칭이라 단서 수집용, 개정 1), 직접 좌표 포함 모든 주입을 로봇이 3 s 스캔/지도 일치로 검증, 위치 프레임 표시(map 또는 odom) 추가. D-257 5항·D-393 3항 일부 개정 제안 | Proposed (2026-10-01; 개정 1 2026-10-01 기준 사각형; 개정 2 슬롯 방향 축; 개정 3 비대칭 단서 필수·수신 기준 유효 시간; 개정 4 2단계 결정·감시 한계; 설계만, 코드·설정·API 참조서 미변경; S1 sim 2대 이후 단계는 별도 승인) |
| D-396 | UI/UX 공용화·일관성 목표 체계 — 여섯 목표(단일 언어·문법 일관성·장치 독립·역할 소유·검증 상시화·지식 단일 출처)를 세우고, 강제 가능한 것은 계약 시험으로: web_common 밖 커스텀 엘리먼트 정의와 서피스 :root 토큰 재선언을 금지(예외는 등록부 raw_colours 로 선언), 승격(2서피스+ → web_common)은 계약이 만드는 압력 | Accepted (2026-10-01, 사용자 승인; 실행 추적 docs/plans/2026-10-01-ui-ux-consistency-goals.md; G2·G5 강제 시험은 이미 존재 — 실측으로 확인) |
| D-397 | Pinky Pro 기하 기본값은 URDF NOMINAL(생성된 `geometry.yaml`, 드리프트 테스트)이고, 로봇마다 승인된 캘리브레이션 레코드가 다듬으며 운영자 덮어쓰기가 둘 다 이긴다 | Proposed (2026-10-01; 저장소 기본값·계약만 변경, 바퀴 0.027→0.028·sensing LiDAR 190→180°·카메라 높이 0.067→0.0634는 기기 배포 전 사용자 승인 필요) |
| D-398 | 증거 한국어 어휘(EVIDENCE_LABEL 최신·지연·연결 끊김·정보 없음 + ` · N초 전` 규격)는 core_ui_logic.js 단일 출처로 승격(D-396 G1 첫 적용; 노드 순수 시험 파일은 예외), 2026-10-01 감사의 P0 네 곳(죽은 토큰 참조·LCD 장미색 #e31b5d 드리프트와 parity 정규식 우회·Pilot 장미색 인터랙션 남용·`stale` 다섯째 증거 상태)을 고치고, 철학 범위 게이트 네 종(정지 D-220·장미색 부정 D-277·역할 우선 두 쌍·100vh 금지)을 test_design_scope_gates.py 로 강제 — 펄스·페이드·전이는 걷히고 기다림은 조용한 뮤트 대시, 컴포넌트 수는 실측(엘리먼트 16)으로 말한다 | Accepted (2026-10-01, 사용자 승인 2026-09-29 ADR 확장 범위; 돌연변이 증명 2026-10-01; LCD 실물 사진·운용자 G3 관찰은 별건) |
| D-399 | ROSY 계층 아키텍처: Application · Fleet(사이트) · 장치별 Command Pipeline — 숙고형 AI는 Fleet 제안, 반응형 정책은 같은 호스트 엔벌로프 스킬 | Proposed |
| D-400 | CORE 안전 정책(`control.sensor_adapter`)은 off·shadow·enforce 세 모드로 켜고(그림자는 판정만 기록), 파라미터는 보정 저장소 하나(URDF NOMINAL < 승인 레코드 < 운영자)에서 오며, 집행 중 짧은 센서 끊김은 HOLD·긴 끊김은 래치 | Proposed (2026-10-01, 설계 사용자 승인; 계획 1 소스 반영, 기본 off; 그림자 실주행·집행은 로봇별 별도 승인) |
| D-401 | Rosy Cell 애플리케이션: 셀 설정·레시피 분리, 해시로 묶은 Job(Step 목록), 팔레타이징 패턴 v1 | Accepted |
| D-402 | OMX 모션 플래너 v1: 장치 로컬 해석 5축 수직하향 IK(고정 open_manipulator URDF), `CELL_TRANSFER`·simulation 한정으로 D-376 §2·§3 HOLD를 좁게 개방, 충돌 장면 없음, owner만 제출, MoveIt은 같은 Protocol의 두 번째 구현 | Accepted |
| D-403 | Fleet Cell Job 경로: Rosy Cell Job → Fleet 제안(재컴파일 검증)·승인 → Step마다 `CELL_TRANSFER` Action 하나, 정지 세대 의미, D-330 §2 하달 보류는 simulation에서만 ROS-SIM 정지 세대 시험 후 개방, 셀 해시 검사는 OMX owner | Accepted |
| D-404 | OMX 셋업·티칭 API(시뮬 우선): D-390 pairing·seat·제한 jog + 읽기 전용 TCP(FK) 조회, 마법사는 팔로워 FK 저장, 장치 셀 수락, 실물 장치 API는 닫힘 | Accepted |
| D-405 | 반복 크롬 컨트롤(테마 trio·설정·새로고침·카드 측정 라벨)은 아이콘이 얼굴이고 한국어 이름은 sr-only·title로 남는다(표준 trio: 달/해/모니터 — shadcn mode-toggle·GitHub·Linear 준용), 아이콘 크기는 글자 척도 value 단계 재사용(공용 .ui-icon, currentColor, 인라인 SVG만), 동사 버튼은 글자 유지, 높이 함수는 dvh로(Fleet 남은 vh 4곳 교정, 대시보드 잔존은 다음 회차), 폭·격자는 여전히 표면 소유 | Accepted (2026-10-02, 사용자 지시 — 공간 절약·아이콘 최대·표준 패턴; D-292·D-359·D-398 좁힘) |
| D-406 | 관제 카메라 구역은 운용 무대(영상)와 설치·보정 묶음(details#camera-install-tools, 기본 접힘 — 제안 도구·맵 맞춤·크기·보정)으로 나뉘고(D-201 '한 화면에 다 보인다'를 설치 흐름에 대해 좁힘), 목표 받기 버튼은 kind=toggle + aria-pressed로 위계를 가진다(눌림 = 계열 파랑 = 지도를 찍으면 이 로봇), 측정 라벨 아이콘은 라벨 척도 | Accepted (2026-10-02, 사용자 지시 — 위계 산만함 해소·역할별 컴포넌트화; 별도 설치 뷰는 다음 단계, 이 묶음이 뿌리) |
| D-407 | 차선 자율 막힘 복구: 앞물체·차선 상실이 이어지면 관제에 판단 요청(WAIT·RESUME·BACK_AND_RETRY·MANUAL·ABORT), 답이 없으면 뒤 여유 확인 후 짧은 후진과 재판단(최대 2회, 기본 꺼짐) | Proposed |
| D-408 | 차선 추종 페인트 입력: 학습 모델 바닥 차선(수평선 아래) 기본, 실패 시 프레임 단위 OpenCV 반사 제거 예비, 밝기 문턱은 진단용; 재학습 클래스 재정의; 장치 기본값 불변 | Proposed |
| D-409 | 기기 연결 묶음(로봇 등록·카메라 연결 승인)도 details#device-install-tools 설치 서랍으로 접히고(아이디·조상 구조 보존), 컴팩트(<30rem) 로스터 카드는 요약(위치·방향 숨김 — 지도가 말한다, data-fact 칸 이름, 안쪽 여백 한 단 축소), 대시보드 잔존 높이 함수 4곳 dvh로 교정(console-detail 31vh·60vh, shell 24vh 2곡) — D-405 잔존 목록 소진 | Accepted (2026-10-02, 사용자 지시 — 남은 설치 요소 분리·역할 명확화; 별도 설치 뷰는 다음 단계) |
| D-410 | 관제 콘솔은 운용 화면(/console — 로스터·지도·대형·신호등·기록·카메라 프리뷰)과 설치·보정 화면(/console/install — 기기 등록·카메라 승인·경기장/맵 보정·설치 기록, 문법 procedure)의 두 문서로 나뉘고, 운용 문서는 링크만 남기며 토큰을 sessionStorage로 공유하고 전체 정지는 양쪽 첫 화면에 있으며, vision-view는 보정 칸 없는 프리뷰 전용 모드(빈 패널 스텁)를 지원하고 이관 마크업은 아이디·조상 보존 | Accepted (2026-10-02, 사용자 지시 — 역할 명확화 완성; D-406/D-409 서랍 이관, 별도 표면 등록은 다음 단계) |
| D-411 | Pilot 로봇측 학습 녹화(카메라 유닛 소유, CORE는 시작·정지 요청, `teleop/intent` 원 입력·주체 기록, 1회 10분)와 정지 중에만 허용하는 HTTP 수신(목록·tar·sha256 manifest, `rosy_ml fetch --http`); 기기가 알리는 조작부 서술자 `rosy.controls/1`(base_velocity·joint_jog·gripper, 드라이버는 전송·위젯은 kind별, 팔 조이스틱은 이전 목표 종료 후 순차 제한 목표); OMX 그리퍼 전용 절대 목표·쥠 readback(시뮬레이션만, D-390 유지) | Proposed (2026-10-02, 사용자 승인 — A→B→C) |
| D-412 | 로봇은 GitHub Releases `payload-<id>`에서 서명된 payload와 서명된 `rollout.json`을 스스로 받아(10분 타이머, ETag), 쉬고 있을 때(IDLE·정지·주행/도킹/교정 없음·배터리 40%/충전·claim 없음) 승인 없이 적용하고 건강 판정에 실패하면 스스로 되돌린다. 배포는 이 PC의 발행 명령 하나(서명 키는 PC에만), 카나리 1대 커밋 뒤 `canary_ok`와 10분 대기로 나머지, 실패면 철회. 로봇별 hold(만료 필수, 봉인된 G4/G5는 자동 hold)가 시험·봉인을 지킨다. D-387 결정 2·5와 완전 자동·GitHub 기각을 개정 | Accepted (2026-10-01) |
| D-413 | ROSY는 modules·integrations·apps·profiles로 책임을 나누고 고정 셀 한 흐름부터 이전한다 | Accepted (2026-10-02; target architecture and phased migration only; runtime and device gates unchanged; §1 D-427이 부분 대체) |
| D-414 | 관제 콘솔 바로 동작: 비상 정지는 확인 없는 한 번 누름(브라우저 시험의 전체 정지 확인 폐지 — 비상 출구에 마찰은 사고), /console/install 발견(mDNS) 목록이 장치 카드+등록 버튼을 그린다(D-410 이관 때 빠진 렌더 충원), 상시 안내 문단은 제목 title로 물러나고 기록 패널이 제목을 얻는다 | Accepted (2026-10-02, 사용자 지시 — 설명 대신 즉시 동작; 비활성 사유 등 접근성 안내는 글로 유지) |
| D-415 | 관제 콘솔 운용 가시성: 로그 뷰어(펼침/지우기/120줄), 진단 패널(상태 주기·로봇별 오류·발견 검색기·API 경로), 신호등 빈 상태 안내, 카메라 프리뷰 마지막 영상 시각 | Accepted (2026-10-02, 사용자 지시 — 로그·디버그 가시성; 네 단계 순차 실행) |
| D-416 | 관제 콘솔 디버그 강화: 로스터 오프라인 카드에 마지막 응답 시각, 대형 RUNNING/HOLDING일 때 폼 대신 요약+해제 버튼(모니터링 모드), 카메라 프리뷰 소스 없을 때 플레이스홀더 | Accepted (2026-10-02, 사용자 지시 — 이어서 개선; 세 단계 순차 실행) |
| D-417 | 관제 콘솔 밀도 정리: 카메라 소스 없으면 한 줄 상태 바로 접힘(선택 시 펼침), 대형 RUNNING 요약이 dl 격자(진단 패널 규격), 로그 패널을 좌열 지도 아래로 이동해 열 균형 | Accepted (2026-10-02, 사용자 지시 — 이어서; 세 단계 순차 실행) |
| D-418 | 로봇 SSH 접속은 세 길: LCD 일회용 코드로 기기별 키 등록(CORE administrator API → root `rosy-ssh-access` 도우미, `/var/lib/rosy/ssh/authorized_keys`, `expiry-time`), 필요할 때만 켜는 로봇별 임시 비밀번호(최대 60분, 사설 대역, `MaxAuthTries 3`, 재부팅 시 해제), passphrase로 잠근 회수 가능한 팀 키 묶음 공유(`tools/ssh/rosy_ssh_share.py`). 공통 기본 비밀번호와 마스터 키 공유는 기각 | Accepted (2026-10-02) |
| D-419 | SAF-003: FleetAgent 링크가 끊긴 순간 진행 중이던 Fleet 주행 목표(correlation_id, D-316)가 마지막 허브 수신부터 `safety.fleet_loss_timeout_s`(기본 5 s, 4–60, ≥ 1 + 하트비트 답 시한 + 1) 동안 그대로면 정책을 한 번 적용 — STOP 취소(e-stop 아님), HOLD 같은 정지 + 재개용 목표 기록(자동 재개 없음), RETURN_HOME `__home__` 귀환(없으면 선 채로), CONTINUE 이벤트만; 이벤트 `safety.fleet_lost`·`safety.fleet_restored`, `safety/state.fleet_link`(API v1.86). 로컬 목표·teleop·follow·Fleet 없는 로봇은 대상 아님, `fleet.enabled`는 읽히지 않음으로 문서화 | Accepted (2026-10-02, 사용자 승인 — 범위 한정 구현) |
| D-420 | Fleet 다단계 Mission의 Pinky Device Action은 `NAVIGATE_TO_POSE`·`FOLLOW_LANE_TO_STOPLINE`(CAMERA_LINE, 신선한 정지선 관측일 때만 성공)·`DOCK`·`UNDOCK`(시뮬 전용) 넷, Fleet `attempt_id`를 CORE `correlation_id`로 docking·차선 실행·취소까지 넓히고(D-316 확장, 상관된 취소 409), CORE는 MANUAL·도킹 완료 상태의 상관 시작을 거절, 결과는 CORE 이벤트 투영·목표 증거는 goal_evidence 경로를 Step 키·조건별 필드·Fleet 판정으로 넓힌 `robot_state`, Task Executor 하나에 장치별 전송 어댑터, Step 원장은 C4가 확정할 표 하나(요구 S1–S12), claim 단계 표, 재개는 새 세대 Mission 재승인, D-419(범위·HOLD 재개)·D-421(전체 취소가 Mission HOLD·도킹·차선 취소) 개정 제안, CORE 출처 `fleet` 은퇴·`fleet_linear`는 Fleet Action 상한 | Proposed |
| D-421 | Fleet STOP ALL을 두 동작으로 나눈다: 기존 `/api/fleet/estop`은 "전체 비상 정지"(래치·로봇별 관리자 해제, 의미 불변)로 이름만 드러내고, 새 `POST /api/fleet/cancel-all` "전체 주행 취소"는 래치 없이 대기 Fleet 작업 취소(`FLEET_CANCEL_ALL`)·대형 해제·로봇별 swarm/navigation 취소·line-follow OFF를 내리며 발행된 작업은 CORE 증거로만 바뀌고(`awaiting_core_result`) 발행 겹침은 울타리로 다시 취소, 로봇별 cancelled/failed/unreachable, 응답은 물리 정지 증거 아님. FLEET SRS CTR-002 개정, API Ref v1.81 | Proposed (2026-10-02, 사용자 승인 — 작업 C) |
| D-422 | 차선 추종 앞물체 정지(path)는 URDF 몸 윤곽(앞끝 `footprint.front_x_m`·반폭·회전 반경)을 의도한 차선 호를 따라 쓸어 몸 간격으로 재고, 정지 간격은 여유 + v·지연 + v²/(2·감속)으로 유도(재출발 +0.03, `obstacle_stop_m`/`resume_m` 은 LiDAR 원점 기준 덮어쓰기로 남음), 제자리 회전은 회전 반경, 신선한 앞 초음파를 점으로 합쳐 더 일찍만 멈추고 없으면 LiDAR `range_min` 사각 하한 | Proposed |
| D-423 | 카메라 영역 거리: `camera_detect_node` 에 NOMINAL 바닥 평면(URDF `camera_nominal.yaml` < 승인 `camera_profile` 기록 < 운영자, 두 번 켜기)과 LiDAR 방위 폭 연계(`lidar_mount` 앞 방향, 가까운 쪽 우선, 낮은 물체는 바닥), 증거 `s`('L'/'G', 뒤 호환)·화면 "0.42m L"; 물체 검출 `object_det`(int8 ONNX, 320×240, 2–3 Hz, 6 클래스, `DetectionEvidence`, D-137 자문 전용) 결정; 작업별 모델 슬롯 `/var/lib/rosy/models/<task>/{shadow,active,previous}`·promote/rollback·PC 전용 .pt→ONNX 동등성 검사·매니페스트 서명·Pilot 모델 패널; 장치 기본값 불변 | Proposed |
| D-424 | 몸 하나, 센서 여럿: CORE(D-422)·sensing 게이트·교정 도구가 공유 `core_common.robot_body.RobotBody`(geometry.yaml < 승인 교정 기록 < overlay)와 같은 간격 g(v)=0.02+0.15v+v²/(2·0.5)로 근접을 판정; 모든 센서를 base_footprint 점으로, 반사 없는 빔은 `range_min` 까지 UNKNOWN 띠(평행 이동을 막고 앞쪽은 원뿔 안 실제 초음파 메아리만 풀어 줌; 회전 쓸기를 지나면 뒤쪽은 결코 풀리지 않음), 회전은 base 기준 ρ+여유·8 구간 관측(ρ 아래 금지), 위치 미션은 도는 동안도 감시, 교정 직진은 중단 대신 줄이기, 카메라는 앞 속도 제한만, 만료 envelope 는 ρ 판정으로 | Proposed |
| D-425 | 앱·웹의 작업 소유권과 공유 경계를 고정하고 실행 조합 apps와 사용자 화면 ui를 분리한다 | Accepted (2026-10-03, 사용자 승인; 목표 구조·문서 기록, 실제 소스 이전·실기 gate 변화 없음; §4 D-427이 부분 대체) |
| D-426 | Fleet–Gazebo 실제 REST/WS·Task/attempt·CORE 결과와 독립 운동/접촉 관측을 함께 검증; 두 로봇/한 Fleet부터 run별 GZ_PARTITION 격리, 진입 경계 grant 재검사·점유 해제 증거·재시작 이전 실행 대조·CORE 독립 base 명령 만료, M01–M08 반복 수용 및 증거 등급 분리 | Proposed (2026-10-03, 사용자 구현 목표 설정) |
| D-427 | ROSY Platform 최상위를 middleware·operations·learning 세 파트와 공용 contracts·integrations·shared/web으로 나누고 import 규칙을 구조 시험으로 강제; ER2·VLM은 operations/decision, 학습 정책·모델·판정기는 공통 L0~L3 승격; 실물 RL은 파이프라인 경유 학습 모드만; D-209 §4·D-413 §1·D-425 §4 부분 대체 제안 | Accepted (2026-10-03, 사용자 승인 B 목표 + C 시작; 문서만, 코드·폴더 이전 없음; D-413/D-425 최상위 경로로 새 이전 동결; 이행 기록 2026-10-04: wave 0–3a origin, 3b–4e push 전, 동등성 증거·safety rename 리뷰 대기) |
| D-429 | D-427 세 파트 위에 다섯 관심사(학습·판단·로봇 제어·통신 규약·기타) view(매니페스트 `concern:`)와 층별 판단 표(숙고형·조정·장치 지역 규칙·중재·안전·반응형·판정기·MANUAL); 최상위 `decision/` 기각; 사이트 장치 owner는 `operations/site_devices/<kind>`, 관측기는 operations, 로봇 도킹은 middleware, 신호 순서는 Fleet; ER2는 사이트 장치 변경을 사람 운영자 승인 후보로만, 승인은 Fleet 신호·교통 로직의 입력(D-392 §4에 신호·문·컨베이어·PLC 구동 금지 추가); 공통 제어 바탕 + 로봇 Motion Intent·DeviceControlPort / `rosy.site-device/1`; integrations는 contracts와 kind가 허용된 파트의 `api: true` root만 import; 로봇 출력은 장치당 binding 하나인 DeviceControlPort; `fleet.ai` → `rosy.decision` 개명(D-231 유일 예외); 승인 후보 재확인 실패는 stale·재시도 없음; D-427 §1·§2 보강·§3 확장 제안 | Accepted (2026-10-03, 사용자 승인; 문서만, 코드·폴더·매니페스트 변경 없음; 안전은 D-430) |
| D-430 | 안전은 판단·제어와 분리된 여섯째 관심사(D-429 `concern:`에 `safety`, 디렉터리 하위 root + `safety_modules:` 모듈 목록, 폴더는 장치 옆 그대로); 층별 안전 체인 표(물리 E-stop·사이트 장치 failsafe·Safety Guard+D-400·반응형 엔벌로프·Arbiter+MANUAL·Fleet 정지/래치/fence/admission·모델 도구 제한)와 현재 상태; 분리 불변식 5개를 wave 0 시험으로 강제(안전은 판단·학습·모델 SDK를 import하지 않음, 판단·학습은 안전을 우회하지 않음, DeviceControlPort binding은 Safety Guard·Arbiter 뒤, 학습 정책·모델 출력은 안전 기능 아님, ROSY는 안전 코일에 쓰지 않음); Fleet·네트워크·모델·감독 상실 시 fail-closed(로봇 D-419/D-400, 신호 적색 점멸, 도크 0 V), 자동 재개 없음; safety 태그 변경은 독립 리뷰 + gate 증거 | Accepted (2026-10-03, 사용자 승인; 문서만, 시험·매니페스트·CI 검사는 wave 0; 상태 정정 2026-10-04: 층 7 시험 있음, `KNOWN_SAFETY_VIOLATIONS` 21건) |
| D-431 | 라즈베리파이 YOLO 추론은 NCNN을 목표로 하고 OpenCV 영상 처리와 학습 모델의 의미를 유지한다 | Accepted (2026-10-03; NCNN export and runtime implemented; device acceptance pending) |

| D-432 | 모든 앱·장치는 공통 발견·연결 규약을 쓰고, 개발 모드에서는 코드 없이 연결한다 | Accepted (2026-10-03, 사용자 승인; 공통 발견·개발 연결 모드·운영 페어링 목표 계약, 문서만; 주소 자동 추종은 신원 검증 전환 후, 구현·DEVICE/FIELD 별도) |
| D-433 | 로봇 몸의 화면·소리·빛(LCD·부저·램프)은 ROS 밖 한 프로세스 `rosy-face`(구 `rosy-boot-display`)가 평생 소유하고, 상황표 순수 함수 하나(`core_common`)가 그릴 것을 정한다; CORE는 1 s `face-inputs.json` 핸드오버로 얼굴·주행 카드 내용을 넘기고 신선하지 않으면 상태 카드로 돌아간다; 026 이주·롤백 경로 포함, Q1–Q5 사용자 결정(권고안) | Proposed (2026-10-03) |
| D-434 | 모델 PC와 관제 PC를 나눈다 — 모델 PC가 학습 모델 처리와 시뮬레이션(Isaac Sim 5.1)을, 관제 PC는 사이트 스택만 맡는다 | Accepted (2026-10-03, 사용자 결정; 역할 분담·운용 규칙, 모델 PC GPU 학습·NCNN·Isaac 실행과 관제 PC 이전은 미수용) |
| D-435 | 작업 오케스트레이션·Fleet·장치 실행을 역할과 권한으로 구분한다 | Proposed (2026-10-03, 책임 모델 재검토 초안; 기존 Accepted 계약·API·코드·실행 gate 변경 없음) |
| D-436 | 호스트 시험은 변경 범위로 고른다 — 반복과 PR CI는 affected 티어, 공용 기반·미분류 변경과 main·야간·릴리스는 풀 | Accepted (2026-10-03, 사용자 요청; 저장소 도구·CI·작업 규칙만) |
| D-437 | 공개 저장소의 빌드는 GitHub Actions hosted runner에서 하고, 서명만 로컬 오프라인 키로 한다 | Accepted (2026-10-03, 사용자 결정; 사이트 후보 workflow 첫 실행은 push 승인 뒤, 사이트 키 미준비) |
| D-438 | 막힌 로봇의 판단은 Fleet 판단기가 규칙 → 비전 모델 → 사람 순으로 내린다 | Accepted (2026-10-03, 사용자 승인; D-407 §2 의 답하는 주체와 Fleet 쪽 영상 해석을 고침, 사전 주의점은 다음 ADR, 문서만) |
| D-439 | 웹 앱은 공용 디자인과 작업 중심 정보 위계로 순차 개선한다 | Accepted (2026-10-03) |
| D-441 | 사이트 스택 자동 업데이트: main push 빌드 → 서명 PC 자동 서명 → 사이트 호스트 자동 설치·롤백 | Accepted (2026-10-04, 사용자 결정; D-437 수동 실행·손 서명과 D-301 운영자 승인 개정, workflow push 실행·서명 PC 예약 작업·호스트 설치와 첫 자동 갱신은 미검증, 사이트 키 미준비) |
| D-442 | 로봇 움직임 요청은 ROS 무의존 Motion Intent(`contracts/motion`, 목표형 `base.pose_goal`·`base.path_follow`·`arm.tcp_pose`와 서보형 `base.twist`·`arm.joint_trajectory`·`arm.gripper`; SI 단위·frame·출처·등록표가 정하는 우선순위 등급·`attempt_id`·`envelope_ref`·유효 기간·정지 의미)로, 장치 출력은 장치당 binding 하나인 DeviceControlPort(`capabilities`·`submit(GuardedMotion)`·`cancel`·`state`·`estop_status`, writer만 쥐고 Arbiter→Safety Guard 뒤; Pinky `/cmd_vel` Twist, OMX `ActionPort`)로; OMX 우선순위표(EMERGENCY>SAFETY>MANUAL>SKILL>POLICY)와 HOLD를 거치는 MANUAL 선점; 행동 불변 이행 a→b→c→d | Accepted (2026-10-04, 사용자 수용; D-429 후속 1·D-399 후속 5; 문서만, 요청 번호 D-439는 다른 브랜치에서 사용 중; 리뷰 REVISE 반영과 사용자 결정 U1–U3 — 자율 출처는 활성 MANUAL을 빼앗지 못함(Pinky 주행 목표 409, 착지 전까지 알려진 예외), `PinkyTwistPort`는 publish를 옮기지 않는 얇은 래퍼, OMX는 Arbiter 전용 `preempt(reason)`→owner HOLD; 이전 직후 첫 안전 작업) |
| D-443 | `rosy.site-device/1` — 사이트 장치(신호등·도크, 나중에 컨베이어·문·PLC)의 공통 호스트 타입 계약: 식별·자격증명, measured/claimed를 가른 상태, heartbeat·`last_seq`, kind별 semantic 동사, ack와 관측된 효과의 분리, 버전; 지금 신호등·도크 HTTP는 wire 변경 없이 `signal/1`·`dock/1` profile; 장치별 단일 감독자(신호등은 Fleet), 로봇은 읽기만, ER2는 후보만, 장치 로컬 failsafe(신호 10 s 적색 점멸, 도크 0 V), 안전 회로 쓰기 금지; PLC/Modbus 어댑터 `integrations/fieldbus/modbus` 레지스터 맵·범위 단위 안전 주소 거부(시험은 D-430 소유)·변하는 watchdog·연결당 어댑터 하나; 재단언은 감독 연속성과 의도 나이 안에서만(현재 코드 위반, 이행 (b2)), seq 재동기화와 안전 방향 1회 재시도, non-agree 열거와 admission 술어; 동작 변경 없는 이행 (a)–(d); Fleet 상시 감독과 운영자 presence 동안만 수동 점등(떠나면 failsafe); Q1–Q10 결정(Q5·Q8·Q9 사용자 결정, 나머지 권고안; 2026-10-04); 코드 결함은 이전 직후 첫 안전 작업 | Accepted (2026-10-04, 사용자 수용; D-429 후속 2; 리뷰 1차 반영; 문서만, 코드·펌웨어·wire 변경 없음) |
| D-444 | 웹 표면 게이트는 release 이미지를 탄다 — dashboard·pilot ARTIFACT는 서명 release 안 share/ 설치 관측, pilot DEVICE는 실기 페달·e-stop 정지 계약 측정 | Proposed (2026-10-04, 사다리 계획 승인; 문서 결정, 관측·측정 별도) |
| D-445 | Fleet 승격 경로(ROS-SIM D-426 → ARTIFACT D-437 첫 실행·D-301 서명 → DEVICE 사이트 PC·2대)와 중앙 Fleet(8081) 착수 전제 3개를 고정한다. 착수 자체는 별도 ADR | Proposed (2026-10-04, 사다리 계획 승인; 문서 결정, 승격·착수 별도) |
| D-446 | 모델 PC도 서명 코드 자동 업데이트에 포함하고 작업·GPU 환경·모델 승격을 분리한다 | Accepted (2026-10-04, implementation authorized; device acceptance tracked separately) |
| D-447 | 웹 표면의 실시간 상태는 이미 열린 소켓을 재사용한다 — Fleet gather는 hub-fresh 로봇을 registry 스냅샷으로 먼저 읽고(신선도 `hub_state_max_age_s`, REST 폴백), 로봇 셸 `store.js`의 `/ws/state` 전환이 그 뒤를 잇는다. 새 전송 계약 없음, 응답 스키마 불변, 행마다 `gather_source` | Proposed (2026-10-04, 사용자 지시; (a) Fleet 출처 전환 구현 동반, 승격 무관) |
| D-449 | 학습 산출물은 출처·시계·단위·owner binding과 승격 증거를 공용 계약으로 보존한다 | Proposed (2026-10-04, active learning closure implementation; 구조·wire 초안이며 runtime 활성화·장치 수용 승인 아님) |
| D-450 | 팔레타이징 앱은 화면의 한 작업 흐름과 박스 전용 Gazebo 수용을 먼저 완성한다 | Accepted (2026-10-04, 사용자 구현 요청; 목표별 수용·배포·실물 증거는 별도) |
| D-451 | 한 줄에서 만나는 양보는 Fleet 알고리즘이 고르고, 로봇은 그 한 수를 실행하거나 거부한다 | Accepted (2026-10-04, 사용자 결정; Fleet 순수 판단과 room_hold·wait_both, CORE 전달·cmd_vel·막힘 어휘·DEVICE·ROS-SIM은 다음 결정) |
| D-452 | 주소 대신 장비 신원과 역할로 네트워크 연결 대상을 찾는다 | Accepted (2026-10-04, 사용자 구현 요청; 공통 역할 발견·승인 신원 대상·기존 인증 보존, 구현 및 DEVICE/FIELD 증거 별도) |
| D-453 | 양보 한 구간은 기존 막힘 답 YIELD 로 보내고, CORE 는 돌려 확인한 뒤 앞으로만 간다 | Accepted (2026-10-04, 사용자 결정; 한 구간 YIELD, CORE 는 확인 후 전진, 운용자 다섯 단어 유지, 합류·D-442·DEVICE·ROS-SIM은 다음) |
| D-454 | 중앙 Fleet 착수 — 시드(`operations/fleet`) 위 성장, 단계 순서 §10.1 레지스트리 → §10.2 명령 추적·PRT-004 활성화(D-170·D-297 유보 해제) → §10.3 미션/대형 → §10.4 지도/백업 → §10.5 사건/감사. (2)단계 착공 전 D-426 ROS-SIM 선행 | Accepted (2026-10-04, 사용자 지시 "착수해"; 전제 ③ 관측·①② 병행, DEVICE/FIELD 승격 주장 없음) |
| D-455 | 방에서 선으로 돌아오는 구간은 지도 자세가 정하고, 오도메트리 좌표는 차선에 올리지 않는다 | Accepted (2026-10-04, 사용자 결정 "그것도 개선해 봐"; 합류는 기존 YIELD·RESUME, 오도메트리 좌표는 차선에 올리지 않음, DEVICE·ROS-SIM 없음) |
| D-456 | 같은 LAN에서 장비를 선택하고 상대 화면에서 승인한다 — 오프라인과 로그인 만료는 페어링 해제가 아니다 | Accepted (2026-10-04, 사용자 결정: 상대 화면 승인 기본·QR/코드 보조·LAN 우선; 구조 결정이며 구현·DEVICE/FIELD 수락 별도) |
| D-457 | 마커 우선과 무마커 폴백으로 천장 카메라 위치를 지도에 표시한다 | Accepted (2026-10-04, 사용자 구현 지시; DEVICE/FIELD 별도) |
| D-458 | 학습 앱·웹 공통 작업 화면과 결과 확인 경계 | Accepted (2026-10-04, 사용자 학습 관련 앱·웹 전체 점검·구현 요청; 로컬 작업 연결, 학습·장치 수용 별도) |
| D-459 | Pinky 학습 검수는 저장되는 웹앱으로 제공하고 자동 초안·수동 정답·학습 수용을 분리한다 | Accepted (2026-10-04, 사용자 전담 구현·디자인 철학·자동/수동 라벨·기능 테스트 기록 요청; 로컬 앱, 학습 qualification HOLD, 배포·모델 활성화 없음) |
| D-460 | 운전석 임대는 만들지 않는다 — 조종 소유권은 지금의 어휘(링크·수락 teleop·보정 lease)로 유지한다. D-343 2.4 거절, 방 목록에 운전자 라벨 표시로 잇는다 | Proposed (2026-10-04, Ralph 대기열; D-427·D-429와 무관계, D-430 구현 없음 — 결정 1·2·3의 채택·거절) |
| D-461 | ROSY 작업 화면은 상태·다음 작업·행동을 먼저 보여주고 공용 작업 부품으로 구성한다 | Accepted (2026-10-04, 사용자 실제 UI 개선·공용 디자인 체계·로컬 병합 지시; 장치/현장 수용 별도) |

| D-462 | Pinky 반복 검수는 프레임 정체성·객체/픽셀 독립 revision·최신 결정 확인을 보존한다 | Accepted (2026-10-05, 사용자 다중 영상·픽셀 검수·CAD 연결·직접 세션 협업 지시; 로컬 앱, 학습/장치 수용 별도) |
| D-463 | 차선 경로는 Fleet이 고른 간선 폴리라인을 따라 다음 짧은 점만 보낸다 | Accepted (2026-10-05, 사용자 결정: 브랜치·ADR·커밋·로컬 병합; 지도 정착 자세만 보내고 위치 미보고는 거절, 장치 수용 별도) |
| D-464 | Pinky 승인 픽셀은 원본·최신 결정·평가 분리를 검증해 immutable 데이터셋으로 만든다 | Accepted (2026-10-05, 사용자 Pinky 사람 검수·학습 반복 연결 구현 지시; 실제 정답/학습/장치 수용 별도) |
| D-465 | 모델 PC에서 픽셀 자동 라벨 초안을 만들고 검수·학습 자격을 분리한다 | Accepted (2026-10-05, 사용자 차선·바닥·벽 픽셀 우선 및 ADR 기록 요청) |
| D-466 | 머리와 사이드바는 각각 한 자리만 갖는다 — 머리는 brand·cluster·estop, 절차 열은 --sidebar-track | Accepted (2026-10-05, 사용자 지시: 헤더·사이드바 레이아웃을 ADR로 고정; 새 중단점 없음, 장치 수용 별도) |
| D-467 | 병합된 작업트리는 증거를 확인한 뒤 종료하고, X: 임시 공간은 출처별로 정리한다 | Accepted (2026-10-05, 사용자 작업트리 정리·X: 용량 확보·교훈 ADR 기록 지시; 작업 절차만, 현장 수용 별도) |
| D-468 | 차선 이탈은 로컬 복귀·재탐색을 먼저 소진하고 Fleet에 요청한다 | Accepted (2026-10-05, 사용자 ADR 결정·목표·구현 지시; SOURCE/DEVICE/FIELD 별도) |
| D-469 | 검수 웹은 원본 이미지를 ETag 재검증으로 다시 받고, 미분류 승인을 화면에서 먼저 막는다 | Accepted (2026-10-05, 사용자 웹 성능·오류 안내 개선 요청; 반복 검수 체감 개선, 착지·push 별도) |
| D-470 | main CI 통과부터 로봇 서명 배포까지 고정된 로컬 서명기가 자동 연결한다 | Accepted (2026-10-05, 사용자 GitHub CI/CD 자동 로봇 업데이트 지시; DEVICE/FIELD 별도) |
| D-471 | 같은 네트워크 무인증 연결 요청은 기각하고, 같은 망 무코드 접속은 개발 연결 모드로만 제공한다 | Accepted (2026-10-06, 사용자 요청 기록 + 방향 결정; 구현 변경 없음) |
| D-472 | Rosy Cam 현장 영상을 지도에 표시하고 후면 LED 점멸로 로봇 신원을 대조한다 | Accepted (2026-10-08, 사용자 결정 "LED 대조 구현"; addendum: 모서리·상단 마커 없이 D-484 보정 + LED 확인 트랙을 D-511 입력으로 허용, trip·initialpose 불가) |
| D-473 | 관제 콘솔도 개발 연결 모드에서는 토큰 없이 같은 망 PC에 운용자 세션을 준다 | Accepted (2026-10-06, 사용자 방향 결정; 구현·ARTIFACT·FIELD 별도) |
| D-474 | 로봇은 주의점 정지선에서 멈추고 Fleet의 구역 허가를 받아 진입하며, 출구 표시를 지나면 점유를 푼다 | Accepted (2026-10-06, 사용자 설계 승인; 구현·SIM·DEVICE·FIELD 별도) |
| D-475 | 고정 평가 세트에 사람이 검수한 정답 버전을 두고, MCAP 프레임의 출처를 증명해 검수 앱으로 받는다 | Proposed (2026-10-06, 사용자 "ADR 초안부터" 선택; 구현·실제 검수·평가 게이트 전환 별도) |
| D-476 | 차선을 잃으면 곧바로 멈추지 않고, 알던 차로의 연장선을 짧게 잇는다(예상 도로 bridge) | Proposed (2026-10-06; 문서만, 기본 꺼짐; SOURCE/SIM/DEVICE/FIELD 별도) |
| D-477 | 현장 LAN 밖 팀 협업 접속은 Tailscale tailnet으로 연다 — 전송 계층만 추가하고 SSH·콘솔 권한은 그대로 | Accepted (2026-10-06, 사용자 결정: 4명 팀 협업 원격 접속·비상업 확인·개발 기기 1대 우선; 구현·DEVICE/FIELD 별도) |
| D-478 | Pinky 검수 웹앱은 명시한 신뢰 망 주소(loopback·사설·Tailscale)에만 선택적으로 바인딩한다(`--host`, 무인증, D-459 확장) | Accepted (2026-10-06, 사용자 결정; 구현은 `--host` 옵션; 착지·배포 승인 아님) |
| D-479 | 카메라 AE/AWB 잠금은 한 번이 아니라, 잠긴 노출이 길 위를 못 쓰게 만들면 다시 건다 | Proposed (2026-10-06; rosy_26 실기 결함 — 어두운 곳에서 잠긴 노출이 밝은 곳에서 길 띠를 포화시킴; 코드·호스트 pytest까지, DEVICE 별도) |
| D-480 | sim2real 차이는 세 갈래로 나눈다 — 싸게 그릴 것은 시뮬에, 그리기 어려운 것은 실주행 재생에, 예외는 장치의 런타임 지원으로 | Proposed (2026-10-06, 사용자 결정: 시뮬 전용 enforce는 명시 플래그, 기본 기하 8kcn 보정, 레지스트리 harness YAML, Isaac 제외; 레지스트리 lint만, 시뮬·CORE 구현과 ROS-SIM/DEVICE/FIELD 별도) |
| D-481 | Fleet이 지도 자세로 차선 경로를 주행시키고, 카메라 인식과 무관하게 녹화하며, 지도 초안 라벨을 검수 대기로만 만든다 | Proposed (2026-10-06, 사용자 요청; 설계만, 장치 자세 게이트 D-395 미해결로 실행 불가; 코드·API·주행 없음) |
| D-482 | Payload 빌드는 이미지가 쓴 ROS 날짜 스냅샷에 고정한다 | Accepted (2026-10-06; payload ROS ABI 불일치 211/314 — 워크플로가 라이브 packages.ros.org에서 설치; 락의 snapshots.ros.org/jazzy/2026-09-11로 고정) |
| D-483 | 화면 입력이 없는 수신 장비는 요청마다 LCD에 승인 코드를 띄우고, 요청한 기기가 그 코드를 입력해 승인한다 | Proposed (2026-10-06; 사용자 결정: 콘솔 승인과 화면 코드 둘 다, 요청별 6자 LCD 코드·5회·168 h·지속 아님) |
| D-484 | 천장 카메라 측정 캘리브레이션에 코너 마커 없는 필드 경계 자동 캘리브레이션 추가: D-360 사각형·D-375 페인트 정합을 orientation 획득으로 승격, 로봇 마커·전선·정책 증거 불변, 미리보기 자동 보정 | Proposed (2026-10-06; 구현 브랜치 feat/vision-field-auto-calib; sighting은 표시 전용 유지, tracking(D-457)·지도 표시(D-472)는 후속) |
| D-485 | 검수 앱 클래스셋(review class sets)은 불변 record(task+순서 있는 class names sha256)로 두고 작업 공간(`--state`)이 객체·픽셀 클래스셋을 하나씩 고른다. 로봇 D-423 6클래스·D-373 lane role 계약은 그대로 | Proposed (2026-10-06, 구현·착지 별도) |
| D-487 | 사이트 관제 화면 표시 이름은 Rosy Fleet — 관제는 천장 카메라 버드아이, 로봇 한 대는 Rosy Robot; 카메라 원본 한 번만, 지도 없으면 카메라가 주 화면; 접속 전 안내 하나 | Accepted (2026-10-07, 사용자 결정; D-377 2항 관제 행 표시 이름 대체; id `console`·`console.svg`·`/console` 경로·저장소 키 유지) |
| D-488 | 관제(Fleet)가 현장 지도의 주소·방향 있는 길로 경로를 잡아 로봇을 보낸다 — 위치는 Rosy Cam이 주, 지도는 주행으로 가르치고 콘솔에서 확정한다 | Proposed (2026-10-06; 사용자 결정 4건: Rosy Cam 주·odom 보조, 로봇별 lane/free, 주행으로 가르치고 확정, 주소·좌표 둘 다; D-257 5항 범위 개정) |
| D-489 | 관제 경로 계획은 방향 있는 차로 그래프에서 "차로 단위 상태"로 시간 비용 A*를 푼다 — 전역 경로는 Fleet, 국소 추종은 로봇, 다중 로봇 교통은 별도 층 | Proposed (2026-10-06; 사용자 요청: path planning 개념·알고리즘 ADR) |
| D-490 | 관제 경로 계획기 구현 — `fleet/routing` 순수 모듈, 표준 라이브러리 A*, 설정·오류 코드·API·시험 기준 | Proposed (2026-10-06; D-489 구현 결정) |
| D-491 | IR 차선 가드는 알려진 횡단보도 구간에서만 쉬고, 구간은 지도나 카메라가 정해 odom으로 잇는다 | Accepted (2026-10-07, 사용자 확정; 구현 전; 260919 횡단보도 줄무늬가 IR 가드를 가짜 이탈로 멈춤 — 중앙 위상은 detect_ir_line 수정, 가운데만 줄무늬 위상은 지도·카메라 구간 필요; 문서만) |
| D-492 | D-438 비전 단계는 LiDAR가 확인한 막힘의 정체 사실(`wall`·`object`·`robot`·`person`·`unknown`) 하나만 ai PC 로컬 Qwen3-VL 로 채우고, 답은 규칙표가 고른다(R4 `person`·`robot` → WAIT) — 실험 3건(결정 47/47 동일, 앞바닥 오판, LiDAR+정체만 그럴듯), V0·V1 은 정체 정확도 관문, 구현은 D-503 SQL 트리거 뒤 | Proposed (2026-10-07; rev 2 같은 날; 사용자 결정: 로컬 Qwen3-VL·ai PC·V0+V1; ai PC 소유자 동의 전 V0 만; 문서만) |
| D-493 | Rosy Fleet 관제 화면은 지도가 주인공 — 지도 3 : 오른쪽 열 2(예외 큐·로봇·카메라 썸네일·대형), 큐와 카드는 `attentionItems` 한 규칙, 천장 카메라는 한 곳에만(지도 없음·크게 보기면 지도 칸), 설치 순서 막대·"…에서 합니다" 문장 제거, 다른 문서 링크는 머리에 하나씩 | Accepted (2026-10-07, 사용자 결정; D-201 같은 폭·큐 왼쪽 고정과 D-487 3항 카메라 배치 대체; 1920×1080 무스크롤 유지) |
| D-494 | 관제 trip 실행(D-488 M2)의 계약 — 로봇 능력 필드, 시각 있는 odom 자세, Rosy Cam 주 지도 자세, 교차로 동작 API, 서버 trip 루프, 주행 가르치기 | Proposed (2026-10-07; 사용자 지시 "M2 처리해"; 지시 없는 교차로는 멈춤, 옛 로봇 trip 거절) |
| D-495 | 차선 로봇은 교차로에서 멈춘 뒤 Fleet이 지도에서 정한 각도만큼 제한된 회전 동작을 하고 새 가지에서 차선 추종을 다시 잡는다 — 교차로 감지와 bridge는 로봇 기본값으로 켠다 | Proposed (2026-10-07; 사용자 결정: 회전 동작 먼저·분기 인식 후속, 기본값 켜기; 릴리스는 모델 PC SIM + 실기 통과 뒤) |
| D-496 | OMX 실물 팔 조종 수용 — 실측 프로필과 벤치 관문 없이는 활성화하지 않는다 | Proposed (2026-10-07, 실물 하드웨어 없음 — OMX-AI 스펙 기반 조건 설계) |
| D-497 | 현장 카메라의 관측 차선으로 Fleet 지도 초안을 만든다 | Proposed (2026-10-07; SOURCE/LOCAL implementation, field acceptance pending) |
| D-498 | 교차로 제한 회전은 D-400 enforce가 아니어도 bridge와 같은 현장 근거(IR 가드 + 몸체 근접 정지 + 현장 수용 선언)로 허용한다 | Proposed (2026-10-07; 사용자 지시; 기본 꺼짐, junction_turn_site_accepted 새 설정, SIM/DEVICE 별도) |
| D-499 | 관제는 사이트 경로와 로봇 링크를 이미 있는 조회의 결과로만 보여 준다 | Proposed (2026-10-07; 사용자 개념 확인, 구현 전) |
| D-500 | 정지 성능은 로봇별로 실측해 보정 저장소에 두고, 정지 간격·좁은 공간 속도는 CORE 한 곳에서 그 기록으로 강제한다 | Proposed (2026-10-07; 독립 비평 15건·동료 세션 질문 반영; 사용자 결정: CORE 입구 강제, 99 %/95 % 상한, 짧은 덮어쓰기는 표시·L0·승격 금지, 재확인은 조건 변경 때만, 정지 감시·creep 포함; 9dfk 후진 벽 접촉 사고 계기; 문서만) |
| D-501 | Rosy Fleet 네 문서(관제·설치·보정·현장 지도·Cell)는 머리 아래 같은 탭 줄을 쓴다 — 다른 문서로 가는 길은 탭 하나(돌아가기 문장·설명 칸·머리 링크 제거), operator 역할의 한국어는 "운영자"(Fleet 웹 범위) | Accepted (2026-10-07, 사용자 결정; D-493 4항 머리 링크 대체; 머리 구성 통일·시작점 이동은 다음 단계) |
| D-502 | 배터리 정지는 SAF-001 E-Stop이다: EMERGENCY로 들어가고 관리자 해제로만 풀린다. 배터리 입력의 결측·낡음은 API에 드러낸다 | Accepted (2026-10-07; 사용자 지시; 자동 해제 미채택, 호스트 pytest만) |
| D-503 | 자율 사슬은 다섯 층(Perception → World State → Autopilot Supervisor → Skill → Planner/Control) — 모델은 출처·나이 붙은 사실만(VLM = 정체, SAM/Qwen 점 = 오프라인 초안, judge = 검수 순서), 규칙이 고르고 CORE가 확인, 운용 판단 요청은 예외 큐 하나(로봇 화면 처리는 D-407대로); D-361 개정(등록 로봇 `stuck_resolver` 추가 자격 `robot_enrollment_credentials`), 막힘 에피소드 표, 데이터 먼저, VLM SQL 트리거 | Proposed (2026-10-07; 문서만; 구현·배포는 단계별 사용자 승인) |
| D-504 | 로봇 얼굴 애니메이션은 작은 LCD에서 표정의 형태를 먼저 구별하게 한다 | Accepted (2026-10-07, 사용자 요청; SOURCE/LOCAL 구현, DEVICE/FIELD 별도) |
| D-505 | 로봇 상태 전환에서 화면·램프를 먼저 갱신하고 소리로 알린다; 막힘과 내비게이션 실패를 LCD 문구로 구분한다 | Proposed (2026-10-07, SOURCE/LOCAL 구현; DEVICE/FIELD 별도) |
| D-506 | Pilot 녹화는 바닥 IR 원시값(`ir_sensor/range`, 좌·중·우 ADC)을 라이다와 같은 증거로 남긴다. 초음파 `us_sensor/range`는 넣지 않는다 | Proposed (2026-10-07; 사용자 지시; D-411 A에 토픽 하나 추가, D-504는 얼굴 ADR, D-505는 상태 전환 화면이 먼저 씀) |
| D-507 | 차선 trip의 한 구간은 CORE가 추종 → 접근 → 회전 축 → 회전 → 재획득 상태 기계로 실행하고 Fleet은 지도에서 그 구간의 기대만 준다; 현장 근거는 지도 하나에 묶인 바닥 선언 `site_floor_map_id` 하나로 합치고, D-468은 이탈의 양의 증거가 있을 때만 연다 | Accepted (2026-10-07, 사용자 결정: 7·9항 수락, 6항 변경 — 현장 근거로 D-468 역추적 후진 허용, 뒤쪽 바닥은 선언이 진다; 옛 현장 키는 시작 거부; 구현·SIM·DEVICE 별도; 2026-10-08 7항 개정 — 이탈은 경계 밖 측정 또는 자세 불연속·epoch 변경 또는 체크포인트 아닌 차로) |
| D-510 | 한 줄이 한 기록인 이어 쓰기 파일(ADR Log, adr_gaps.txt)은 git 내장 union 머지로 합치고, ADR 번호는 `refs/adr/D-nnn` ref를 만들어 선점한다 | Accepted (2026-10-07, 사용자 결정) |
| D-508 | 제어 고리(명령→센서→판단)는 로봇 안 또는 같은 LAN의 현장 PC에서 돌고, 판단용 영상은 생긴 곳에서 숫자로 바꿔 보내며, 사람용 영상은 요청 때만 경로에 맞춰 보낸다; 운영자 경로 p95가 감시 타이머 절반을 넘으면 직접 조종을 거절; 무선망은 제어 우선 | Proposed (2026-10-07, 사용자 요청; 현장 측정: 노트북 LTE+Tailscale 0.5–1 s, 현장 PC→로봇 7–10 ms; 문서만) |
| D-509 | 관제는 Pinky의 충전·건강 근거와 다음 조치를 보여 주고, 장치 설정은 소유 화면에서 실행한다 | Proposed (2026-10-07, 2026-10-08 계약 점검; 구현·배포·장치 수용 별도) |
| D-511 | Fleet은 Rosy Cam 지도 자세로 움직이는 모든 로봇의 차로 준수를 지켜보고, 벗어나면 주행을 끊지 않고 알리며 모드별로 보정을 지시한다(CORE 가장자리 신호는 IR 가드와 같은 가지, IR 우선); 1차 방어는 로봇의 바닥 IR | Accepted (2026-10-07, 사용자 수락 "수락, M0 시작"; 선행은 D-497 지도 + sighting 연결, M2 가장자리 신호는 Safety-Review) |
| D-512 | 에이전트가 실기 시험을 직접 수행한다 — 카메라 사전 점검(머리 위 Rosy Cam + 로봇 카메라, 케이블 근처는 받아들인 위험·경로/바퀴면 중단), 안전 장치 유지, 임시 설정은 finally에서 바이트 그대로 복원, 증거는 sha256 요약; D-476 rev 2 장치 시험은 순서 예외 | Proposed (2026-10-08, 사용자 결정; 도구 `tools/device_test/` 호스트 시험만, 장치 실행 전) |
| D-513 | 시연 출발 자리는 현장 지도 장소 종류 `start`(`yaw` 필수)로 두고, 방향은 로봇을 놓아 기록하며, 활성화는 trip이 출발할 수 없는 출발 자리를 `SITE_MAP_START_INVALID`로 거절한다 | Accepted (2026-10-08, 사용자 확인: 벽 = 카메라 화면 오른쪽, 두 출발 방향 수락; SOURCE/LOCAL 구현, 현장 지도 입력 F2 별도) |
| D-515 | 관제 지도의 천장 카메라 실영상은 수락된 보정으로 편 위에서 본 직사각형 — 지도 미터 뷰(+y 위) 위에 576 삼각형 아핀으로 그리고 따로 돌리지 않음, 영상 밖은 비움, 클릭·로봇·차로는 같은 미터 좌표, 표시 전용 | Accepted (2026-10-08, 사용자 결정; D-513 7항의 메인 지도 실영상 회전을 대체, 썸네일·조감도 원본 회전은 유지) |
| D-514 | 객체·픽셀 검수는 서로 다른 클래스 계약을 쓰고, 물체 종류와 통로 점유 판단을 분리한다 | Proposed (2026-10-08, 사용자 요청에 따른 검수 기준 초안; 클래스셋 전환·학습·로봇 배포 미승인) |
| D-519 | 관제 콘솔 사람은 아이디·비밀번호로 로그인하고 HttpOnly 세션 쿠키(유휴 12시간, 이 브라우저 기억 30일, 서버 DB 해시)를 쓰며, 토큰은 기계 클라이언트에만 남긴다 | Accepted (2026-10-08, 사용자 결정 "C 지금 + A 다음"의 A; 구현·ARTIFACT·FIELD 별도) |
| D-518 | 관제 웹의 위치는 문서 네 개(운용·설치·Cell·현장 지도)와 공유 읽기이고, 패키지는 Fleet 서버 안에 둔다. 공유 읽기는 web/shared, Cell은 web/cell이고 나머지 문서는 하나씩 옮긴다 | Accepted (2026-10-08, 사용자 선택: 문서 소유 + 하위 폴더; 울타리, warpImage 분리, 공유 읽기 web/shared, Cell web/cell 이동까지 구현) |
| D-516 | AI PC의 Decision 후보는 동일한 오프라인 사건으로 비교하고, VLM 관측과 실행 권한을 분리한다 | Accepted (2026-10-08, 사용자 결정: 모델 PC 학습·평가, AI PC 추론 전용, Fleet 판단·승인, CORE 재검사; 현장 활성화 별도) |
| D-517 | 여러 로봇이 같은 차로망을 동시에 달린다: 로봇마다 trip 하나·반복 운행, Fleet 고정 블록 통행권(블록 길이는 몸체·정지 거리·위치 불확실성·경로 감시 거리에서 계산, 구역·양방 차로는 블록 묶음, 고리 수용 N·h ≤ S−1), CORE는 자세 odom 기준 통행권 끝·`ttl_s` 만료에서 서고 통행권은 줄지 않는다, 막히면 로봇 → Fleet 해결기 → 사람(D-494 1·14항 개정) | Accepted (2026-10-08, 사용자 결정 "바로 처리" + 리더–팔로워 포함 로드맵 9항 M0–M7; rev 2 독립 검토 반영; CORE 통행권·따라가기는 단계별 Safety-Review) |
| D-520 | 곡률을 아는 차로 구간(회전교차로 ring)에서는 CORE가 지도의 호(ω = v·κ)를 주 명령으로 달리고 카메라는 바깥선을 반지름 고정 원으로 맞춰 옆 보정만 준다; 구간 기하는 D-507 교차로 지시의 `exit_segment`로 보내고 IR 가드(`clear`만)와 D-422가 지킨다 | Accepted (2026-10-08, 사용자 확정; 결정 방향: 지도 호 feed-forward 주 명령 + 카메라 호 맞춤 보정, 단계 1 feed-forward SIM → 단계 2 보정; 문서만, 구현·SIM·DEVICE 별도) |
| D-523 | AI PC 질의는 정체 사실 또는 허용 후보만 반환한다 | Accepted (2026-10-08, 사용자 계획 승인; 내부 파서, 현장 활성화 아님) |
| D-521 | Rosy Cam 원격 입회로 G4/G5를 진행하고 별도 현장 담당자를 필수로 두지 않는다 | Accepted (2026-10-08, 사용자 결정; DEVICE/FIELD 미수용) |
| D-522 | 개발 환경 원격 이동은 사용자 지시로 진행하며 반복 승인 대신 장치 증거를 확인한다 | Accepted (2026-10-08, 사용자 지시; DEVICE/FIELD 미수용) |
| D-526 | Fleet가 충전 케이블 tether를 감시하고 한도에서 CORE E-Stop으로 세운다 | Proposed (2026-10-08, 사용자 결정 D-512 개정 1 5항; 1단계 Fleet 감시·정지·표시 구현, 호스트 시험만, 독립 Safety-Review 전) |
| D-524 | Service Control. 관제 API가 사이트·AI·모델 Ubuntu의 재부팅과 허용된 systemd 유닛 정지·재시작만 받는다. pkill·셸·프로세스 이름은 거절하고, 재부팅은 shutdown -r +10이다 | Proposed (2026-10-08, 사용자 지시; 구현은 feat/host-control, 현장 설치·재부팅 없음) |
| D-525 | 가상 신호등: 실물 신호기 없이 Fleet 교통 규칙이 D-517 구역 입구(정지선)를 신호 단계(녹·황·적·전체 적색)로 열고 닫는다, 녹색 접근로만 새 구역 허가, 받은 허가는 줄지 않음, 구역이 비어야 다음 녹색, 로봇은 신호 색을 받지 않고 D-517 통행권만 따른다(CORE 무변경), 실물 신호기를 붙이면 D-443 다섯 술어가 더해진다 | Accepted (2026-10-08, 사용자 결정; rev 2 독립 검토 반영; S0 착수, S1–S3 구현·SIM·DEVICE 별도, D-517 M2 Safety-Review 선행) |
| D-527 | Decision 시험은 개발 로컬 PC 계약·푸시 검사 → 모델 PC 독립 L0(텍스트 Laya/Kev·별도 VLM) → AI PC 승인 버전 적재·스모크 → 현장 Fleet/CORE 수용으로 나눈다; D-516의 AI PC 첫 평가 문장을 개정한다 | Accepted (2026-10-09, 사용자 결정; 문서·호스트 역할만, 모델 PC L0·AI PC GPU·현장 수용 별도) |
| D-528 | v13 과노출은 검수 우선순위 신호이며 정답을 판단할 수 없을 때만 제외한다 | Accepted (2026-10-09, 사용자 기준 수정; SOURCE·모델 PC 검수 기록 확인, 픽셀 정답 승인·학습은 별도) |
| D-530 | 팀 호스트는 저장소의 역할별 바라는 상태(`deploy/*/host-state/`), 호스트별 드리프트 점검 타이머(safe만 자동 수정), 관제 PC 가드(N번 → 유닛 재시작 → 2N번 → 재부팅, 새벽 창 제외, 로봇은 확인만)로 사람 없이 유지한다; 접근 변경은 사용자 승인 뒤 | Proposed (2026-10-09, 사용자 목표; 저장소 첫 조각만, 실제 장비 미적용) |
| D-529 | 시험 실행은 역할별 호스트에 배치하고 커밋별 증거로 판정한다 | Accepted (2026-10-09, 사용자 지시; 실행기와 현장 수용 증거는 별도 확인) |
| D-532 | 주행 가능 영역 추가 모델은 v13-drivable 계열로 구분하고 불변 revision·승인 데이터·기존 차선 모델의 계보를 각각 기록한다 | Accepted (2026-10-09, 사용자 결정; SOURCE 이름 규칙, 실제 학습·접수·배포 별도) |
| D-531 | CORE가 지금 받아 둔 교차로·굽이·호 지시에서 경로 문맥을 만들어 `line/route_context`(String JSON, VOLATILE, 5 Hz, 만료 포함)로 인식 keeper에 준다; 문맥은 거부(HOLD 쪽)로만 쓰고 없거나 낡으면 keeper는 main과 같다; B9 `bend_expected`는 이 통로로만 켜진다; 실물 434프레임 HOLD → 주행은 독립 검증 없이 0 | Proposed (2026-10-09, 사용자 방향 결정 "둘 다": D-520 단계 2 먼저, 경로 문맥은 다음 단계; 문서만, 구현·SIM·DEVICE 별도) |
| D-533 | Fleet의 TLS 공개 identity 조회는 source별 300회/분으로 따로 세고, 승인 challenge/session 증명은 기존 30회/분을 유지한다; 매 REST 요청의 CA·hostname·identity 검사를 생략하지 않는다 | Accepted (2026-10-09, 현장 429 재현; SOURCE 수정, DEVICE/FIELD 별도) |
| D-535 | 연결이 안 되면 이유 코드 하나(21개, `connect-reasons.v1.json`)와 운영자 문장·할 일을 보인다; CORE 피어 승인·`/auth/connection` 거절은 기존 상태·`detail`에 `error.code`를 더하고, `/auth/connection`은 인증 없이 LAN·출발지별 30회/분으로 `core_ready`·`release`·`tls_hostname`·`pairing`을 답한다; 닿지 못한 실패는 클라이언트가 같은 코드로 분류(Fleet `link_reason`, Pilot `LinkReason`) | Proposed (2026-10-09, 8kcn 조사; SOURCE, Pilot 채택·DEVICE·FIELD 별도) |
| D-536 | Fleet 로봇 상황과 좌표 안내: 로봇마다 지도 자세·u·몸체 반경·차로 문맥(옆 벗어남, 방향 오차, 구역, 다음 장소)을 한 기록으로 내고(`GET /api/fleet/guide`), 문제마다 좌표 목표가 붙은 안내(카메라 못 봄, 로봇 시계 앞섬, 위치 모름, 차로 이탈, 역주행, 구역 안 정지, 너무 가까움)를 예외 큐에 낸다; 관제 지도에 몸체 원·방향·불확실성 고리·목표 점선을 그린다; 로봇에 아무것도 보내지 않는다 | Accepted (2026-10-09, 사용자 요청; G1 읽기·표시 구현, G2 동작 버튼·G3 좌표 확장·G4 자동은 별도) |
| D-537 | 현장 일회성 기체 몸체 대조는 인증된 장치 시험과 연속 영상으로 판정한다 | Accepted (2026-10-09, 두 Pinky 현재 배치 몸체 대조; Fleet 자동 추적·이동 수용 별도) |
| D-534 | Pinky Pilot 녹화는 모델 PC가 정지 확인 후 자동 수신하고 검수 대기로 넘긴다 | Accepted (2026-10-09, 사용자 지시; SOURCE 계약·수신 타이머, 모델 PC 활성화와 실제 녹화 수신은 별도 확인) |
| D-538 | 객체·픽셀 검수 스튜디오는 같은 작업 순서와 단축키를 보여주되 독립 결정·저장 조건을 유지한다 | Accepted (2026-10-09, 사용자 지시; SOURCE/브라우저·모델 PC 별도) |
| D-539 | Rosy Cam 추적은 운영자가 다시 학습한 빈 트랙 배경을 재시작 뒤에도 쓴다 | Accepted (2026-10-09, 사용자 지시; SOURCE·호스트 테스트, 현장 배포·재시작 확인 별도) |
| D-543 | UI는 화면의 목적과 작업 전환 이유를 먼저 설명하고 공간을 그 목적에 배분한다 | Accepted (2026-10-09, 사용자 요청; 개별 화면 구현·G1/G2/G3 수용 별도) |
| D-542 | 객체·픽셀 검수는 사진 중심 작업대와 결과 피드백을 공유하고 사람 표시를 AI 보완의 경계로 쓴다 | Accepted (2026-10-09, 사용자 결정; 현장 브라우저 조사와 ADR, 화면 구현·모델 PC 적용·사람의 라벨 수용 별도) |
| D-540 | Rosy Fleet 콘솔 구조 v2 — 동작마다 한 자리: 공통 머리(세션·역할·테마·시계·`#estop` 규칙 하나), 관제는 지도 3 : 레일 2에 레일 하나만 스크롤, 예외 큐 항목이 그 자리에서 결정으로 펼침(막힘·재계획 확인·Cell 승인·위치 확인), 로봇 카드가 그 로봇의 유일한 동작 자리(목표·운행…·운행 취소·LED·주소 이동; 정상은 한 줄, 예외·선택은 펼침), 대형·대열 한 블록; 현장 지도는 편집·가르치기·미리보기 + 로봇 위치(운행 조작 없음); 설치·보정이 시작점·배경 다시 학습·카메라 승인 하나·호스트 서비스를 받음; Cell 승인·진행은 큐·카드로; 문구는 `core_ui_logic.js` 한 출처, "운영자", 멈춤·취소는 비상 정지만 위험 채움(`#cancel-all`·카드 운행 취소 quiet); 1920·1440·1024·390 맞춤; 움직이는 Fleet 경로는 모두 이름 있는 운영자, 멈춤은 열림; D-517 10항 운행 줄 대체 | Proposed (2026-10-09, 사용자 결정 3건; 감사 `fleet-ui-audit`; 구현 계획 `docs/plans/2026-10-09-fleet-console-v2.md`) |
| D-549 | 사람 인증은 현장 하나의 Rosy Auth가 발급한 계정(아이디·비밀번호)으로 하고, 로봇은 그 서명을 검증만 한다 | Proposed (2026-10-09, 사용자 방향 "추후 auth service로 id·비번 로그인"; 단계 A Fleet 안 auth 모듈 → B 로봇 접근 토큰 Ed25519 서명·CORE 검증 → C 별도 서비스; 열린 질문 4개) |
| D-548 | 로봇 하나를 개발 모드로 열 때는 root가 `/etc/rosy/dev-mode` 파일을 만든다 — 공용 개발 토큰만 열리고, 셸은 열리지 않으며, LCD는 DEV를 띄운다 | Accepted (2026-10-09, 사용자 결정 "로봇별 파일 스위치"; D-193 7 개정, Fleet 미션 API는 개발 세션으로도 시작; FIELD 별도) |
| D-545 | 모델 PC 검수 앱 코드를 버전별 릴리스와 current 링크로 전환하고 검수 DB를 외부에 유지하며 실패 시 이전 서비스로 복구한다 | Accepted (2026-10-09, 사용자 지시; 모델 PC 적용·HTTP 확인·검수 수용은 별도) |
| D-544 | 천장 카메라(Rosy Cam)는 나쁜 조명을 스스로 재고 노출 보정만 한정된 범위에서 고친다 — 기본 꺼짐, 폰이 닫는 고리, 기하 보정은 건드리지 않는다 | Proposed (2026-10-09, 사용자 요청; 1단계 폰 측정 + 로컬 노출 보정만 구현, DEVICE 대기) |
| D-541 | CORE trip lease — Fleet trip이 로봇을 쥐고 있음을 CORE가 안다(`PUT/DELETE /api/v1/trip-lease`, `/takeover`, TTL 1–10 s·Fleet 주기 갱신), 주인 아닌 `/mode`·`/teleop`·구동 쓰기는 409 `TRIP_LEASED`(멈춤·비상 정지는 늘 열림), 명시적 넘겨받기 = lease 끝 + IDLE, MANUAL 모드 로봇에는 열지 않음, IDLE·MANUAL·도킹·ABORT·만료·비상 정지·넘겨받기면 lease와 trip이 끝나고(주인의 lane ↔ free 전환은 유지, 검사는 `require_calibration_owner` 한 곳, 해결기 토큰은 WAIT·ABORT만) Fleet은 다시 열지 않음; 보정 lease와 배타, 비상 정지 우선; D-460에 넷째 소유 어휘 추가 | Proposed (2026-10-09, 사용자 결정; Safety-Review 대상, SOURCE·SIM·DEVICE 별도) |
| D-546 | 복구 기동 신호와 Fleet 위치 요청 — RECOVERING 중 `face-inputs.recovery`(retrace·return·bridge) → 앰버 1.5 Hz 비상등(`recovering`, 다리는 앰버 호흡 `bridging`), 후진(retrace) 동안만 1 kHz 80 ms 1.0 s 주기 경고음, LCD `Recovering: ...` 띠, 우선순위 비상정지 > 복구 > 식별; CORE→Fleet `localization/request`·Fleet은 자기 로직(천장 카메라·D-395 중재·차선 그래프) 먼저, 실패할 때만 VLM `pose_hint`(D-492 `thing`과 별도 계약)·로봇 스캔 확인은 설계만; D-395·D-468·D-492 개정 목록 | Proposed (2026-10-09, 사용자 결정; 신호 구현·위치 요청 설계만, SIM·DEVICE 별도) |
| D-552 | 램프·화면·소리는 한 레코드 `Presentation`(`core_common.presentation.present`)에서 나온다 — 우선순위 FAILED > EMERGENCY(걸린 e-stop 포함) > RECOVERING > CAUTION(CORE 주의 코드 포함) > ..., 심각도는 램프의 것이고 표정은 그 심각도가 허용하는 얼굴만; 화면은 위 32 px 상태 바(문구·심각도 색·배터리 % 아이콘·충전·모름)와 아래 320×208 표정 영역으로 나뉘고, 주행·웨이크 카드는 표정 영역을 대신하며 전체 화면 상태 카드는 바 없이 그대로; D-433 9–11행·D-546 우선순위 개정 | Proposed (2026-10-09, 사용자 요청; SIM·DEVICE 별도) |
| D-547 | Rosy Cam 추적은 배경에 굳은 로봇을 추측으로 보이고, 떠난 자리의 유령은 그 자리만 다시 배운다 | Accepted (2026-10-09, 사용자 지시 "배경이 잘못돼도 추측하는 폴백"; SOURCE·호스트 테스트·실프레임 오프라인 평가, 현장 확인 별도) |
| D-550 | Fleet↔로봇 통신 계약: 아는 쪽이 보냄, 두 상호작용(물음/답·관찰/전달), 네 종류(허가·명령·참고·사실; 허가 만료=정지, 참고 만료=모름, 허가와 참고는 필드·엔드포인트를 나누지 않음), 위치 의존 데이터는 `leg_id`+`pose_stamp`+경로 미터, `ttl_s`는 받는 쪽 단조 시계, 순서 `(pose_stamp, seq)`, 추가만·능력 플래그, 허가·명령은 REST만(하트비트 답은 페어링 로봇의 참고만, 허브 COMMAND/ACK 예약); 움직임×링크 끊김 표와 규칙 M(로봇마다, 지금은 경고만), 목표 임대 `lease_ttl_s`(Safety-Review), 허브 페어링 목표(비용 받아들임) | Accepted (2026-10-09, 사용자 결정 J1 목표 임대·J2 아직은 경고만·J3 표시 먼저·J4 지금 페어링; 페어링은 로봇마다 명시적 진행 뒤) |
| D-551 | D-525 신호 참고(advice) 전달: Fleet이 trip 주기마다 `POST /api/v1/line-follow/advice`(`advice_id`, `leg_id`, `seq`, `fleet_epoch`, `pose_stamp`, `ttl_s` ≤ 2, `signal` 또는 null, `map_version`, `route_rev`)로 밀고 CORE 저장소 하나가 odom으로 다시 재어 `GET /line-follow` `advice`와 로봇 얼굴에 보임; 능력 `line_follow_advice`, Fleet `fleet.traffic.signal_advice`(기본 false), 통행권과 같은 주기·통행권을 늦추지 않음, 통행권 모듈 import-lint; 속도 상한은 뒤로(마지막 min 클램프, `v_floor` ≥ 바퀴 데드밴드, 같은 구간 통행권을 쥘 때만, D-407 래치 안 씀) | Accepted (2026-10-09, 사용자 결정 J3 표시 먼저; 속도 상한은 Safety-Review 뒤) |
| D-553 | CD 속도: CI `fleet` 3·`sensing` 2 파일 샤드, `robot_cd`가 main push 즉시 서명 없는 ARM64 빌드를 보내고 서명은 그 sha CI 성공 뒤(실패면 거래 종료·번호 빈자리), 더 큰 payload 태그가 있으면 superseded, 준비 실패 세 번이면 failed·예외도 감사 기록, `remote_pytest`는 invocation 여럿을 닿는 시험 PC 모두에 나눠 동시 실행; self-hosted 러너·현장 PC는 쓰지 않음 | Accepted |
| D-554 | `v13-drivable` 학습 라벨은 사람 검수 차선 마스크(AI PC `data-v13`)의 좌·우 선 사이 배경을 drivable로 유도하고, 선 바깥은 255, 벽만 음성; 9항 선 바깥 띠(0.5·도로 폭) 음성; 판정자(카나리아 90% 이상 검출 필수, Qwen3-VL 8B는 0/17로 탈락)는 `concern` 프레임만 제외; `annotation_origin: derived_from_reviewed_lanes`로 사람 승인과 구분, 평가 정답 아님; provisional 카메라 출처는 이 shadow candidate에만 허용(`camera_provenance: provisional` 표시); shadow intake는 재생·지연·부모 차선 동등성 게이트(heldout drivable 정의 불일치로 고정 평가 제외); 결과는 candidate이며 lane_seg shadow 슬롯까지만, 조향 권한 없음 | Accepted (2026-10-09, 사용자 결정; 학습·shadow 주행 별도 증거) |
| D-557 | 링 주행의 다음은 새 제어가 아니라 모델 PC에서 D-520 호 한 바퀴다 | Accepted (2026-10-09, 사용자 요청으로 순서를 기록. 시뮬 실행·바닥 이동·코드 변경은 이 기록이 하지 않음) |
| D-555 | 콘솔 등록 로봇의 허브 페어링 — Fleet이 로봇마다 허브 자격을 만들어 digest만 남기고, TLS로 묶인 등록으로만 로봇에 보낸다 | Accepted (2026-10-09, 사용자 설계 승인 Q1 TLS 신원에 묶인 관리자급 자리·Q2 TLS 등록만; 보안 검토·Safety-Review 대상, SOURCE·호스트 테스트만) |
| D-562 | 천장 마커 번호는 로봇 번호와 같다 — 로봇은 40–49번, 스티커는 40 mm, 검출기 둘레 하한 0.015 | Accepted (2026-10-09, 사용자 결정; SOURCE·호스트 테스트만, 기존 로봇 번호 바꾸기·스티커 부착은 별도 운영 단계) |
| D-558 | drivable 모델은 불변 revision(D-532) 옆에 `model_version` `v<major>.<minor>.<patch:2자리>`를 붙인다: major=학습 계열(원본 자료 세대·부모 차선 모델), minor=라벨·출력·게이트 규칙, patch=같은 규칙의 재학습; 한 버전에 revision 하나, 원장 `drivable_versions.yaml`, intake가 형식·major·중복을 확인; 982b09a9=`v13.0.00`(rejected), D-554 9항 첫 후보=`v13.1.00` | Accepted (2026-10-09, 사용자 결정) |
| D-561 | 모델 PC 검수 UI는 승인된 서명 코드 릴리스를 따라간다 | Accepted (2026-10-09, 사용자 요청; 모델 PC 자동 전환·현장 화면 검증 별도) |
| D-569 | 사이트 코드 갱신과 로봇 등록 차이 분리 — 인증된 Fleet·카메라 목록의 설치 전후 회귀를 막고, 옛 필수 ID 누락은 별도 경고로 남긴다; mDNS는 등록 신원이 아니다 | Accepted (2026-10-09, SOURCE·Linux 호스트 테스트; 관제 PC 설치·로봇 재등록 별도) |
