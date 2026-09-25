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
| D-140 | ARM64 ?? ??? ?? arm64 ??? ?? ????? ? ARTIFACT ? ?? ?? ??? | Accepted |
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
| D-177 | correlation_id 3단계 추적과 AckPayload 확장은 중앙 Fleet 착수와 같은 변경에서 함께 구현 — 활성화 시 설계를 선기록 | Proposed |
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
| D-193 | 대시보드 로그인은 로봇 화면의 일회용 코드로 한다 — 장기 토큰은 화면에 띄우지 않고, 장치 기본값에는 로그인이 없다 | Proposed |
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
| D-218 | 확인 문법의 졸업 — 네이티브 window.confirm이 공유 컴포넌트다: 거부는 호출 0회, alert/prompt는 금지, 확인 문장은 결과를 묻는 평문이다 | Accepted |
| D-219 | 운용 요약 어휘의 실행 계약 — 콘솔 분류 범주와 Fleet 큐가 닫힌 선언적 표로 고정되며 D-159가 승격된다: 빈 큐는 부재다, 초록이 아니다 | Accepted |
| D-220 | 정지 계약 — 움직임 예산은 0이다: 상태 변화는 점프 컷이며 보간은 없는 값을 있는 것처럼 보이게 한다, 예외는 ADR로만 | Accepted |
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
| D-255 | UI/UX 평가 회차 2 | Proposed |
| D-258 | 디자인 리뷰 루프 | Proposed |
| D-259 | 지도 키보드 조작 | Accepted |
| D-262 | 웹 예산 판정 제안 | Proposed |
| D-260 | 로봇은 부팅음·LED·LCD·운용 화면 요약줄 네 곳에서 같은 상태를 같은 말로 보여준다 | Proposed |
| D-246 | 런타임 유연성 — 네이티브가 기본값이고 컨테이너는 선언된 비안전 워크로드에만, 장치별 차이는 profile/slice로만 | Accepted |
| D-247 | 대시보드는 보드의 모든 장치가 붙어 있고 응답하는지를 보여준다 — 장치 관측과 제품 기능을 가른다 | Proposed |
| D-256 | 공개 무결성 값은 이름으로 지우고, 스캔는 매처를 넙히지 않는다 | Accepted |
| D-257 | 사이트 관제 지도는 차선 그래프 — 로봇 위치는 폰 천장 카메라가 보고, 영상은 Fleet 밖에서만 | Proposed |
| D-261 | 천장 카메라 안드로이드 앱 — 골격 범위·위치·기술·첫 버전 약속 | Accepted |
| D-263 | 메뉴는 사용자의 질문을 찾는 길이다 — 화면 책임과 확장 규칙 | Accepted |
| D-264 | 장치 진단 도구는 이미지에 넣는다 — 읽기 도구(i2c-tools·pinctrl·gpiod·rpicam-apps)는 제품 이미지에, 커널 헤더는 디버그 프로필에만 | Proposed |
---
