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
| D-196 | 로봇은 장치의 조합이다 — `src/devices/<계열>/`과 `src/robots/<robot>/`을 두고, 로봇 지식은 그 안에만 둔다 | Proposed |
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
| D-209 | 인식과 학습 백엔드의 자리 — 몸통 인식은 control/sensing/perception, VLA는 backend_learned, 재생과 학습 세트는 로봇 이미지 밖 | Accepted |
| D-210 | 실사용 1차 범위 — 2대 관제+군집을 실물 1대+시뮬 1대로 닫는다 | Proposed |
| D-211 | ROS-SIM 재실행 묶음 — 현재 트리에서 2대 관제+군집을 증명한다 | Proposed |
| D-212 | ARTIFACT 네이티브 경로 — Pi 5에서 서명 이미지까지만 간다 | Proposed |
| D-213 | DEVICE→FIELD 승격 순서 — 실물 1대 stationary부터 2대(실물+sim) 현장 반복까지 | Proposed |
| D-214 | 텍스트 대비의 바닥 — 모든 보이는 글자는 4.5:1(큰 값 3.0:1) 이상이다: 팔레트는 표면의 자유지만 읽힘은 청중의 권리이며 선택도 읽기를 희생하지 않는다 | Accepted |
| D-215 | 명령 추적 `TIMEOUT`은 Fleet 기록 전용 상태다 — 로봇 ack enum에 넣지 않는다 | Accepted |
| D-216 | CAP-001 예시의 `protocol_version` 오타를 고친다 — `"1"`이 아니라 `"1.0"`이다 | Accepted |
| D-217 | SEC-102의 CORS 문장을 좁힌다 — 로봇 API는 CORS를 제공하지 않는다 | Accepted |
| D-222 | First-boot 소비자는 `rosy-first-boot.py` 하나다 — `apply-sd-provision.py` stub을 폐기한다 | Accepted |
| D-225 | 카드 재기록은 마지막 수단이다 — 기존 로봇은 서명 payload 전환으로 갱신하고, 남는 재기록은 리더·재개·이미지 크기로 줄인다 | Proposed |
| D-218 | 확인 문법의 졸업 — 네이티브 confirm이 공유 컴포넌트다. alert/prompt 금지, confirm은 핀된 횟수, 없는 조종은 버튼이 아니다 | Accepted |
| D-219 | 운용 요약 어휘의 실행 계약 — D-159를 Accepted로 승격하고 Fleet 큐 규칙을 콘솔 분류와 같이 고정한다 | Accepted |
| D-220 | 정지 계약 — 움직임 예산은 0이다. 보이는 요소의 전이와 애니메이션은 없다 | Accepted |
| D-221 | 얼굴 웨이크 카드의 어휘 — 라벨은 기계 약어로 남는다: 행인의 채널은 형태·색·만료이지 글자가 아니며, 폰트 의존(이미지에 CJK 폰트 없음)과 enum 값 번역 없는 라벨 번역은 다 이득이 없다 | Accepted |
| D-224 | 표면의 키보드 어휘 — 약속한 키는 동작한다: Fleet 로스터 ↑/↓ 순회·Enter 목표·Escape 해소, 게임 스페이스는 /stop 1회, 카드 착지점은 tabindex -1 | Accepted |
| D-226 | 문서는 공개 여부를 먼저 가르고, 그다음 주인 폴더에 둔다 — 비밀·식별·권리 불명·전략 초안은 private/, 코드가 읽으면 데이터, 날짜 증거는 docs/validation, 모듈 설명은 모듈 docs/ 하나, 출처 있는 자산 묶음은 통째로 | Accepted |
| D-227 | 여섯 책임은 지금 트리 위의 이름이다 — 새 루트와 명령 봉투와 AI 워커는 만들지 않는다 | Proposed (결정 1은 Superseded by D-231) |
| D-228 | 판단은 core_features/decision 이다 — 런타임 개명과 제품 이름 패키지는 만들지 않는다 | Accepted |
| D-229 | 모듈 경계는 지금 폴더를 따라 한 방향으로만 흐른다 — 인식은 증거, 판단은 동작 id, 추종기는 FOLLOW 다음의 속도 | Accepted |
| D-231 | 소스 영역은 층으로 나눈다 — contracts·runtime·devices·products·hmi·site·sim과 firmware/, 디렉터리만 옮기고 패키지 이름은 유지, 제품 이름 런타임·src 안 AI 워커·원격 판단 경로·새 액션은 받지 않는다 | Accepted |
| D-230 | SD writer 멈춤은 두 단계로 다룬다 — soft 경고, hard 중단, CLI 진행률 우선 | Accepted |
| D-232 | OMX 제품 설정은 products/omx 이고, 보드 핀맵과 AI 자리는 그대로다 | Accepted |
| D-233 | 디자인 시스템 초안 — 토큰 동결, 컴포넌트 3층 | Accepted |
| D-241 | core 계열 폴더는 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다 | Accepted |
| D-242 | 나머지 폴더도 역할 이름을 쓴다 — 패키지 이름과 import 는 유지한다 | Accepted |
| D-243 | 운용 화면은 hmi 에 두고 API 는 런타임에 둔다 | Accepted |
| D-245 | E-Stop 파일럿 — 종류·물음형·권한 병기 | Accepted |
| D-248 | AuthBar — 잠금 폴링 중단 | Accepted |
| D-249 | FieldMap — spec 고정, 코드 미추출 | Accepted |
| D-250 | TeleopHold — 홀드-티커 추출 | Accepted |
| D-251 | 절차 카드 — 크롬 규칙 고정 | Accepted |
| D-252 | Fleet 큐·대형 — 머리 triage·대기 요약 | Accepted |
| D-253 | 게임·진단 마무리 — 관전 없음·진단 동결 | Accepted |
| D-254 | 디자인 철학과 토큰 전집 | Accepted |
| D-255 | UI/UX 평가 회차 2 | Accepted |
| D-258 | 디자인 리뷰 루프 | Accepted |
| D-259 | 지도 키보드 조작 | Accepted |
| D-270 | 역할 게이팅은 표면이 정한다 | Accepted |
| D-266 | 진단 PARKED 해제 조건 | Proposed |
| D-262 | 웹 예산 판정 제안 | Proposed |
| D-260 | 로봇은 부팅음·LED·LCD·운용 화면 요약줄 네 곳에서 같은 상태를 같은 말로 보여준다 | Proposed |
| D-246 | 런타임 유연성 — 네이티브가 기본값이고 컨테이너는 선언된 비안전 워크로드에만, 장치별 차이는 profile/slice로만 | Accepted |
| D-247 | 대시보드는 보드의 모든 장치가 붙어 있고 응답하는지를 보여준다 — 장치 관측과 제품 기능을 가른다 | Proposed |
| D-256 | 공개 무결성 값은 이름으로 지우고, 스캔는 매처를 넙히지 않는다 | Accepted |
| D-257 | 사이트 관제 지도는 차선 그래프 — 로봇 위치는 폰 천장 카메라가 보고, 영상은 Fleet 밖에서만 | Proposed |
| D-261 | 천장 카메라 안드로이드 앱 — 골격 범위·위치·기술·첫 버전 약속 | Accepted |
| D-263 | 메뉴는 사용자의 질문을 찾는 길이다 — 화면 책임과 확장 규칙 | Accepted |
| D-264 | 장치 진단 도구는 이미지에 넣는다 — 읽기 도구(i2c-tools·pinctrl·gpiod·rpicam-apps)는 제품 이미지에, 커널 헤더는 디버그 프로필에만 | Proposed |
| D-265 | 기반 화면은 패널 수와 무관하게 남는다 — 메뉴·정지 진입 계약 | Accepted |
| D-267 | Ubuntu 상시 관제 노트북은 Fleet·영상·GPU·저장을 분리하고 자동·수동 작업을 같은 검증 경로로 처리한다 | Proposed |
| D-268 | Fleet 자동 작업은 sighting이 아닌 별도 수용된 정책 증거만 사용한다 | Proposed |
| D-269 | 장비는 역할별 계약으로 사이트 서버에 접속하고 DDS는 CORE 안에 둔다 | Proposed |
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
| D-374 | 앱의 폴더·패키지·식별자·표시 이름은 역할 이름 하나에서 나온다 — 역할 id(kebab)·snake·compact·표시 네 표기; 와이어 계약 이름(mDNS 종류, `rosy-overhead/1`, `/api/fleet`·`/api/vision`, `rosyov://`, 웹 경로, 설정·저장소 키, compose 서비스)은 바꾸지 않는다 | Accepted (2026-09-30, 사용자 결정: 규칙·대응표 그대로, 관제 화면 안 B(화면 자산만 `site_console`, 서비스 `fleet` 유지), 폰 재설치·재페어링 1회 수용, games·제어 진단·시뮬 라이브 뷰는 지금 제외; D-370 2항 "식별자 그대로" 대체, D-339 1항·D-231 2항을 앱 패키지에 한해 대체; 실행은 계획의 단계별 브랜치) |
| D-376 | OMX PICK_PLACE planning stays local and trajectory execution stays with the Action owner | Accepted (2026-09-30, SOURCE contract and fail-closed planner gate only; production planner configuration, profile activation, ROS-SIM, DEVICE/FIELD acceptance remain HOLD/PARKED) |
| D-377 | 앱 이름 규칙: Rosy + 영어 한 단어 — 표시 이름 `Rosy <Word>`, id·폴더 끝 `<word>`, 패키지 `rosy_<word>`, Android `io.github.livsbittt.rosy.<word>`, Gradle `rosy-<word>`, 아이콘 `<word>.svg`; Rosy Cam·Vision·Console·Robot·Pilot | Accepted (2026-09-30, 사용자 결정; D-370 2항 이름표와 D-374 1·2항(규칙·대응표, `rosy_` 접두 금지 포함) 대체; D-374 3–5항(와이어 불변·재페어링·단계 게이트) 유지; Vision 실행 파일 `rosy-vision`, 옛 `site_vision`·`overhead`는 한 릴리스 별칭) |
| D-378 | 실물 로봇은 실물 녹화로 통과한 로직으로만 스스로 간다 — 주행 오류를 기록하고, 차선·정지선·신호는 재생 → 그림자 → 누르는 동안 순서로 들인다 | Accepted (2026-09-30, 오류 기록·도입 순서; 실물 반영은 단계마다 사용자 승인) |
| D-380 | 램프는 로봇 상태(D-260)에 이어 운용 모드도 밝힌다 — CORE가 status-inputs 핸드오버에 RobotMode를 더해 넘기고, 같은 규칙표(core_common.robot_state)가 우선순위(실패 > 비상정지 > 주의 > 부팅 > 도킹 > 내비게이션 > 수동 > 준비)대로 램프 패턴과 LCD 상태줄 접미를 정한다. 모드 변경은 소리 없이 패턴만 바꾼다 | Accepted (2026-09-30, 램프·LCD가 건강 상태만 말하고 운용 모드는 대시보드에만 있던 갭; lamp_pattern.c에 manual/navigating/docking/emergency 추가, 부저는 D-260 결정 2의 건강 상태 전환에만 그대로) |
