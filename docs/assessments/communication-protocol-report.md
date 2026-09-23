# 통신·프로토콜 평가 보고서

작성일: 2026-09-22 / 대상: `Rosy OS` 작업 트리 (src 6도메인 + deploy + dock + signal)
범위: **전송·규약 관점** — 물리 버스 → ROS 그래프(QoS) → 프로세스 내/호스트 → 로봇 API → 사이트/함대 → ESP32 장비 계약 → 배포 네트워크. 모듈 import 결합도는 `module-coupling-report.md`(2026-09-21)이 이미 다루므로 제외.
계약 원천: `docs/reference/ROSY API & Protocol Reference.md`(v1.12), `rosy-host-agent-contract.md`, `dock/README.md`(ROSY-DOCK-001), `signal/README.md`(ROSY-SIGNAL-001), ADR Log(D-1~D-168), CORE/FLEET SRS.

## 1. 통신 계층 지도

| 계층 | 전송 | 근거(대표) |
|---|---|---|
| L0 물리 버스 | Dynamixel UART(`/dev/ttyAMA4`, 1 Mbaud), LiDAR UART(`/dev/ttyAMA0` 460800), I2C×2(`/dev/i2c-1` ADC 0x08, `/dev/i2c-0` BNO055 0x28), WS2811 DMA/PWM(GPIO19), SPI LCD(spidev0.0 80 MHz), `/dev/video0` | `bringup.py:37-39`, `dynamixel_driver.py:65`, `sllidar` 핀 커밋, `sensor_adc/src/main_node.cpp:25,37`, `bno055_device.cpp:37-39`, `rosy_lcd.py:30-33` |
| L1 ROS 그래프(DDS) | CycloneDDS 단일(RMW 고정), namespace `rosy_%02d` + 상대 토픽, domain `40+N`, **lo 인터페이스로 제한** | D-117/D-4/D-33, `cyclonedds_localhost.xml:5-13` |
| L2 프로세스 내 | in-proc 이벤트 버스(D-8), DI(`CoreServices`), entrypoint 센서 provider(D-126) | `core_events`, `services.py` |
| L3 호스트 로컬 | unix socket `/run/rosy/host-agent.sock`(라인 JSON 64 KiB 상한, SO_PEERCRED, allowlist 10명령, 멱등 256건) | ROSY-HOSTAGENT-001, `host_agent.py:37-96` |
| L4 로봇 API | FastAPI REST `/api/v1` + WS 4종, 단일 포트 8080(기본 `0.0.0.0`), 시뮬은 8080+N | `node.py:103-104`, `gz_multi.launch.py:579` |
| L5 사이트/함대 | 로봇→Fleet 아웃바운드 WS(잠자는 구현체), SiteHub `/ws/robots`, 군집 pose/reference 소켓, Fleet 콘솔 :8090(폴링 v1), 도크·신호등 HTTP :80, 관측자 :8095 | D-5/D-31/D-59/D-81, `cli.py:63-64` |
| L6 릴리스·유지보수 | 서명 릴리스(Ed25519+SHA256SUMS), systemd 네이티브(D-161), Wi-Fi 상태머신(SITE_STA 기본, NETWORK_HOLD) | `updater.py:70-93`, `deploy/release/network.py:55-64`, D-26 |

## 2. 물리 버스·장치 인벤토리 (L0)

| 링크 | 전송/속도 | 프로토콜 | 근거 | 비고 |
|---|---|---|---|---|
| 구동 모터 | `/dev/ttyAMA4`(UART4, GPIO12/13 dtoverlay), 1,000,000 baud | Dynamixel Protocol 2.0, ID[1,2], sync-write GOAL_VELOCITY @104 / bulk-read | `bringup.py:37-39`, `dynamixel_driver.py:65,75-85`, `configure-uart-pi5.sh:6,51` | 초기화 순서에 zero-RPM 기록·재독기 검증 포함(`dynamixel_driver.py:120-182`) |
| LiDAR (RPLidar C1) | `/dev/ttyAMA0`, 460800(업스트림 기본) | sllidar_ros2, 핀 커밋 고정 | `bringup_robot.launch.py:85`, `Dockerfile:107-111` | `scan_mode:=DenseBoost` |
| IR/초음파/배터리 ADC | `/dev/i2c-1`, addr `0x08`, 20/5/2 Hz(절전 3단계) | 레지스터 raw R/W `{0x88,0xC8,0x98,0xD8,0xF8}`, 12-bit | `sensor_adc/src/main_node.cpp:25,103-118` | **오류 처리 없음 — §8-E 참조** |
| IMU BNO055 | `/dev/i2c-0`, addr `0x28`, 100 Hz | wiringPi, 32B 블록 @0x08, IMUPLUS 융합, 칩ID 0xA0 검증 | `bno055_device.cpp:37-69,102-113`, `main_node.cpp:22,31-33` | 건강 토픽 `sensors/imu/status`(latched, 1 Hz) — 실패 시 **발행 생략** (fail-closed) |
| 램프 | WS2811, GPIO19/DMA10, 8px GBR, 100 Hz 갱신 | rpi_ws281x | `lamp_control/src/main_node.cpp:12-27,106-159` | Pi5는 out-of-tree `rp1_ws281x_pwm.ko` 필요(§8-F) |
| LCD | spidev0.0 mode0 80 MHz, GPIO27 RST/25 DC/18 BL-PWM | ST7789류 RGB565 240×320 | `rosy_lcd.py:7-9,30-33` | `set_emotion` 서비스, `power/mode`·`display/info` 구독 |
| 카메라 | `/dev/video0` | V4L2→OpenCV | `compose.yaml:161` | |
| 배터리 퍼블리셔(선택) | rosylib | `battery/percent`·`battery/voltage` 5 s | `battery_publisher.py:12-36` | 모든 런타임에서 기본 비활성. 노드명 오타 `battery_publihser`(`:8`) |

판정: UART 2개·I2C 2버스가 기능별 분리. 단 **안정적 장치명이 dtoverlay 순서에만 의존** — udev by-id 규칙이 전무하다(§8-D).

## 3. ROS 그래프·QoS (L1)

### 3.1 CORE 브리지 (ROS-101 — 모든 ROS I/O의 단일 창구)

- 발행 5: `cmd_vel`(Twist, depth10, **50 Hz**), `initialpose`, `power/mode`(latched), `display/info`, `docking/collision_exemption`(latched) — `ros_bridge.py:88-90,141-144,150`
- 구독 24: 센서 3종 sensor-data QoS(`scan`/`imu_raw`/`us_sensor/range`), `camera/preview/compressed`(BEST_EFFORT depth1), 라이프사이클 `transition_event` 6종(준비 게이트), `motor/ready`(latched 리스), `map`(latched), `costmap_raw` 2종(타입 불일치 리더 정리 이력 — `_raw`만), 증거 4종(`line/observation`·`detection_evidence`·`road/observation`·preview), `odom`/`battery/voltage`/`nav_cmd_vel`/`batt_state`/`plan`/`hitl`/`degraded` — `ros_bridge.py:96-139`
- 서비스 클라이언트 4: `set_led`, LiDAR `start_motor`/`stop_motor`, `slam_toolbox/save_map`(옵션) / 액션: `navigate_to_pose`(GoalTracker 세대 관리) — `ros_bridge.py:92,145-148,175`
- 타이머 7: 50 Hz cmd_vel / 10 Hz state(설정) / 1 Hz 진단 / 5 Hz power·dock·swarm / 20 Hz line-follow — `ros_bridge.py:150-156`
- 구조는 `test_bridge_timers.py`가 고정. HOLD 중에는 50 Hz 발행은 유지하되 반드시 0 twist(`ros_bridge.py:382-391`)

### 3.2 QoS 원칙 정합 (D-119)

| 규칙 | 발행 측 | 구독 측 | 판정 |
|---|---|---|---|
| 센서 sensor-data | `camera_detect_node.py:121` 등 | `ros_bridge.py:128-130` | 일치 |
| TRANSIENT_LOCAL 래치 | `power/mode`(`ros_bridge.py:68,141`), `motor/ready`(`bringup.py:51-55` — 포트 개방 전 false 선발행), `sensors/imu/status`(IMU 노드) | emotion `_LATCHED`, CORE `_LATCHED` | 양측 일치 |
| 지도 latched | Nav2 map_server | `ros_bridge.py:132` | 일치 |
| 프리뷰 BEST_EFFORT depth1 | `road_observer_node.py:162-165`(2 FPS 최신 1장, D-152) | `ros_bridge.py:105-109` | 일치 |

매칭 불가 조합(RELIABLE 구독 ↔ BEST_EFFORT 발행) 없음. `measure-dds-baseline.sh:137-145`는 측정 함정(구독자 유발 트래픽, bw의 RELIABLE 구독, latched 0)까지 문서화 — 측정 계약 수준이 높다. 단 **잠복 리스크 4건**(현재는 정상 동치, 향후 파열):

1. **D-119의 IMU 조항은 소비자 측에서만 지켜진다** — `imu_bno055`의 `imu_raw` 발행은 `SystemDefaultsQoS`(RELIABLE)이고 CORE만 SENSOR(BEST_EFFORT)로 구독. 호환(발행 ≥ 구독 요구)이라 동작하나, `startup_calibration_node.py:90`이 `imu_raw`를 평범한 d10(RELIABLE)으로 구독 — 향후 IMU 발행을 SENSOR로 바꾸는 순간 **이 구독자만 조용히 매칭 불가**가 된다. `us_sensor/range`·`ir_sensor/range`도 CORE(SENSOR)와 control safety(d10)가 같은 토픽에 상반된 정책으로 붙어 있다.
2. **`map` 소비자 3정책 혼재** — 발행(map_server/slam, TRANSIENT_LOCAL)에 대해 CORE·localization_node는 LATCHED로 받고 `web_node`·`startup_calibration_node`·비정적 `goal_node`는 SENSOR로 받는다. 후자는 레이트 조이너가 다음 발행까지 빈 지도를 본다.
3. **`estop`(Bool) LATCHED 구독에 in-tree 발행자가 없다**(`safety/node.py:216`) — 운영자가 `ros2 topic pub` 기본 QoS로 발행하면 transient_local 구독과 **영원히 매칭되지 않는다**. `estop/cmd`(String, d10)만 친화적 경로.
4. 서비스 QoS는 전면 기본값(로컬 서비스라 수용 가능하나 기록 필요).

### 3.2.1 토픽 중복·어휘 잔재

- **`ir_sensor/range` 하드웨어 이중 발행**: C++ `sensor_adc`와 Python `ir_adc_node`가 같은 버스를 읽어 같은 토픽에 발행. `line_follow.launch.py`가 ir_adc_node를 띄우고 `hardware.launch.py`가 sensor_adc를 띄우면 소비자(safety/wander/line_observer)가 **두 판독기의 교차 배열**을 받는다.
- **보정 어휘 2벌 공존**: OS 경로 `calibration/*`(status·ready·drive_scale·profile·applied)와 레거시 FSM `calib/*`(status·phase·step). `safety/mode`(폐기 예정 별칭), `safety/can_reverse`≡`safety/rear_clear`(중복값)도 같은 성격.
- **다생산자 토픽(원칙적·관리 필요)**: `cmd_vel_raw`(wander·control·calib·startup_calibration·web teleop·safety zero-pub — watch.py 허용 목록에서 `control_node`만 누락), `wander/cmd` 4곳, `initialpose` 3곳(CORE·localization·시뮬 시드), `nav_cmd_vel` 2곳(Nav2 velocity_smoother 리맵 vs `map_v2_runner` — 병행 금지), `camera/front` 시뮬 2곳(실센서 vs rendered adapter). `sensors/imu/status`는 **소비자가 없다**.
- **emotion 노드명·서비스 충돌**: `emotion.py`와 `emotion_server.py`가 같은 노드명 `emotion` + 같은 `set_emotion` 서비스 — 두 엔트리포인트 병행 시 충돌.
- **watch_node 감시 계약 스테일**(`control/watch.py:10-42`): REQUIRED 노드가 여전히 `pinky_*` 이름(현행 `bringup`/`sensor_adc`/`imu_bno055`), `EXCLUSIVE['/cmd_vel']='safety_node'`는 D-2/D-38(소유자=`core`)과 모순, FOREIGN 목록도 구 `pinky_control` 잔재. **현재 그래프에서 실행하면 항상 인터럽트를 오탐하고, 레거시 그래프에서는 CORE를 침입자로 지목한다** — 단일 발행자 원칙의 런타임 감시장치가 정책과 반대로 되어 있다.
- **레거시 launch는 namespace 인자 자체가 없음**(`robot.launch.py`/`wander.launch.py`) — 레거시 스택은 다중 로봇·CORE 병행 불가 구조(의도와 부합). 또한 `ROSY_NAMESPACE` 환경변수만으로는 rclpy 노드 namespace가 설정되지 않는다(`config.py:73-79`는 frame_prefix·robot.id만 유도) — namespace는 launch/compose `__ns:`가 유일한 설치 경로. `ros2 run core core`를 환경변수만으로 띄우면 프리픽스된 TF 프레임을 가진 무namespace 노드가 되는 분열 구성이 가능하다.

### 3.3 주기·타임아웃 예산 대조 (D-34, CORE SRS §25)

| 항목 | 계약 | 구현 | 상태 |
|---|---|---|---|
| cmd_vel 50 Hz (D-2) | 50 Hz | `ros_bridge.py:150` | 일치 |
| 상태 스냅샷 5~10 Hz | ≥5 Hz | `state.rate_hz` 기본 10 | 일치 |
| Teleop watchdog ≤500 ms | ≤500 ms | CORE 감시 + 드라이버 deadman 0.5 s 이중, 정지는 **확인될 때까지 재시도**(`command_deadman.py:9-49`) | 일치 |
| 이벤트 전파 ≤200 ms | ≤200 ms | in-proc 버스(D-8) | 실측 DEVICE 대기 |
| Fleet heartbeat 1 Hz (PRT-003) | 1 Hz | `fleet_agent/agent.py:137` | 일치 |
| 리더 pose ≥10 Hz (SWM-003) | 하한 강제 | `ws.py:126-127` `max(rate,10.0)` + 마감시각 스케줄 | 일치 |
| 참조 단절 1000 ms→HOLD (SWM-004) | 마감시각 판정 | swarm 5 Hz tick(`ros_bridge.py:633-635`) | 일치 |
| 신호등 감독 침묵 | 페일세이프 | `HEARTBEAT_TIMEOUT_MS=10000`(2 s 폴링×5), 부팅 즉시 FAILSAFE, NVS 무저장(`rosy_signal.ino:32,65,359-368`) | 일치(인수 기준 AC-11은 12 s 관측) |
| 릴레이 스트림 정지 | 0 Hz(마지막 프레임 반복 금지) | 바이트 그대로 팬아웃 + latest-wins depth1(`relay.py:80-91,238-250`) | 일치 |
| odom/관절 | — | bringup 30 Hz(`bringup.py:191-197`), cmd_vel 50 Hz ↔ deadman 0.5 s = 25프레임 여유 | 무결 |
| 대기 모드 센서 듀티 | 2 Hz(PWR-001) | sensor_adc 20/5/2 Hz — 대기 2 Hz(0.5 s 간격) vs safety `sensor_timeout` 1.0 s는 표본 2개 여유로 **한계적** | 주목 |
| Nav2 출력 신선도 | CORE 내비 감시 ≥2 Hz | `map_v2_runner`가 10 Hz 마감시각 발행을 명시적으로 맞춤(`:157-165` 주석) | 일치 |

## 4. 웹 게이트웨이 (L4) — 계약 대비 구현

- 단일 프로세스(D-1): rclpy 메인 + uvicorn 데몬 스레드, `network.api_host`(0.0.0.0):`api_port`(8080) — `node.py:102-115`. api_port는 **YAML 전용**(환경변수 직접 오버라이드 없음).
- REST 카탈로그가 계약 문서와 경로·역할 단위로 일치(시스템/로봇/내비/맵/웨이포인트/제어·안전/도킹/군집/이벤트·진단/host 릴레이/라인-팔로우/교통/비전 프리뷰). E-Stop은 Viewer 허용(계약 AUTH-102 예외), `PUT system/info`의 `IDENTITY_LOCKED` 409(D-33)도 구현.
- WS 4종: `/ws/state`(10 Hz), `/ws/events`(glob), `/ws/swarm/pose`(capability `swarm.lead`), `/ws/swarm/reference`(Operator, 유일 인바운드 — 형식 위반 프레임은 버리고 소켓 유지) — `ws.py:37-210`, close `4401`/`4403` 계약 일치.
- 인증: sha256 저장·불투명 id·16~128자 규칙(`deps.py:90-129`), 레거시 평문 마이그레이션. **개발 기본 토큰 3종이 `rosy_default.yaml:48-55`에 존재**("교체 필수" 명시).
- 프리뷰(v1.12/D-152): no-store, sequence 페어링 409, 400 ms 레이트리밋 429, `X-Rosy-Camera-*` 헤더 — 원본 영상은 WS·Fleet·명령 경로 미탑재(D-118).
- Host Agent 릴레이: `/api/v1/host/*` → unix socket(기본 경로·5 s), PSK 미회귀(`v1/host.py:23-28,118-127`).

판정: 표면 정합 A. 단 **버전 표기 3원 불일치**(`app.py:55` "(v1.2)" vs 문서 v1.12 vs `PROTOCOL_VERSION="1.0"` — §8-I), CORS 부재가 계약에 미기술(동일 출신 대시보드 설계이나 외부 브라우저 클라이언트는 조용히 실패), 에러→HTTP 매핑이 3중 병행(`errors.py:30-48`, `docking.py:18-28`, `swarm.py:17-23` — 선상 일관, 코드 비일관).

## 5. 함대·사이트 프로토콜 (L5)

- **로봇 측 FleetAgent**: PRT-002/003 구현체 — hello/welcome, 1 Hz heartbeat+스냅샷, 이벤트 seq 버퍼(1000 cap)·`last_event_seq` 이후 재전송, backoff(`agent.py:43-137`). `hub_url`+`pairing_token` 설정이 없으면 잠자기(중앙 Fleet 미구현, D-5 방향 유지).
  - **편차 ①**: backoff 상한 60 s vs 계약 §7.6 "최대 30 s"(`agent.py:119`).
  - **편차 ②**: hello의 `device_uid/device_name/model/hardware_serial`을 `hasattr` 폴백 `""`로 채움 — `RobotIdentity`에 해당 필드가 없어 허브의 `DUPLICATE_IDENTITY`/`IDENTITY_DRIFT` 방어(`hub.py:80-92`)가 이 에이전트에서는 발동 불가.
  - **문서 모순**: `fleet_agent/AGENTS.md` "start()는 소켓을 열지 않는다" — 현재 코드와 불일치(스텁 시절 기술).
- **PRT-004 미구현**: `Envelope.correlation_id`는 계약·스키마에 존재하나 **어떤 런타임 경로도 설정·소비하지 않음**. `AckPayload`도 문서 §9.5(`TIMEOUT`·`issued_by`·`ts_issued/ts_final`)보다 얇다. 명령 추적은 현재 REST 요청/응답 + 이벤트 `seq`로 대체.
- **SiteHub(D-59)**: `/ws/robots` Envelope 검증(위반 1008), hello 거부 4401, `pairing_token` in-band 신뢰. **`GET /registry` 무인증**(`hub/server.py:16-25`, private `registry._robots` 직접 접근), 소켓 자체 무인증. CLI `fleet hub`는 **죽은 코드** — dispatch는 있으나 subparser가 없어 파싱 불가(`cli.py:47-69,299-301`).
- **Fleet 콘솔 v1(D-81)**: gather=REST 폴링, 기본 `127.0.0.1:8090`, 루프백 밖 `--token` 필수(`cli.py:248-276`). 경로는 `/api/fleet/*`로 로봇 계약과 의도적 구분. e-stop은 부분 실패에도 200(로봇별 결과), 대형 해제 후 정지, resume은 trigger 클리어 전 불가(FOR-004).
  - **잠복 결함**: `_manage_swarm_speed`가 `spec.name` 존재하지 않는 속성을 참조 → `AttributeError`가 `except Exception: pass`로 삼켜져 ADR-1000 자동 감속이 **조용한 no-op**(`console.py:413-422`, `arming.py:34-40`).
- **문서 §10 ↔ 구현 불일치**: 계약의 Fleet REST(포트 8081, `/api/v1/fleet/*`, 페어링 토큰·명령 추적·미션)는 미구현. 시드 콘솔은 8090 `/api/fleet/*`. 의도된 차이이나 문서에 "미구현" 표기가 없다.
- **신호등(ROSY-SIGNAL-001)**: `X-Rosy-Token`+단조 `seq`(409 stale), red+green 400, 침묵 10 s→전등 적색 점멸, 미프로비저닝 장치는 탈출 불가능한 fail-closed 읽기전용. 관측자(`observer/`)는 읽기전용 :8095, 프리즈 5 s 성능 저하 표기.
- **도크(ROSY-DOCK-001)**: 읽기전용 `GET /status`, **도크는 연결 개시 금지·로봇이 폴링**(timeout 1 s, `docking/agent.py`), `charging` 확정은 도크 전류+팩 전압 이중(D-27 억제 전제). 펌웨어 규칙 순서 준수(부팅 즉시 비에너지, 과류/과압 래치 오프).

판정: 방향성 일관 — **모든 원격은 로봇/클라이언트가 아웃바운드 개시**, 로봇 간 DDS 차단(D-33)으로 로봇 간 데이터는 전부 이 계층을 지난다. 미구현 표기 정합(§10)과 PRT-004가 주 갭.

## 6. 배포·네트워크 규약 (L6)

- 신원 강제: `ROS_DOMAIN_ID`(40+N, 0~101 가드)·`ROSY_NAMESPACE`(`rosy_%02d`)를 `${VAR:?}`·빈 템플릿으로 강제(D-33) — `compose.yaml:4,9`, `install-pi.sh:290-310`, `test_dds_identity_contracts.py`.
- RMW 단일(D-117): Cyclone 고정, fastrtps 금지는 시험 고정(`test_dds_rmw_contracts.py:8-21`). **저장소 유일 DDS XML**이 lo 전용이며 컨테이너(`Dockerfile:25`)와 네이티브 이미지(`build-native-payload.sh:51,103`) 양쪽에 복사 — 로봇 간 Wi-Fi 디스커버리 원천 차단(의도적). 시뮬은 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`(D-120).
- 최소권한: CORE `cap_drop ALL`+`read_only`+장치 없음(native `PrivateDevices=true`), I/O만 dialout/i2c/video/gpio/spi 그룹 + `DeviceAllow` 열거. 호스트 root는 Host Agent 유일.
- Wi-Fi 상태머신(D-26): **WLAN 유실=NETWORK_HOLD(자동 AP 금지)**, 복구 AP는 1회성 마커로만, 모터/IO 활성 중 AP 거부, PSK는 저장·회귀·로그 금지(`deploy/release/network.py:39-75,422-430`).
- 하드코딩 포트 감시: 28161/28162(레거시 web_node)는 배포 구성 전체 스캔으로 차단(`test_control_launch_boundary.py:39-53`). 잔여 하드코딩: `native/wait-core-ready.py:13`이 8080 고정(api_port 무시).

## 7. 규약 일관성 — 잘 지켜지고 있는 원칙

1. **fail-closed 3계층 동일 어휘**: 스키마(필수 필드 누락=오류 — 도크/신호등 공통), 신호등(침묵=적색 점멸, 재부팅 부활 금지), 준비 게이트(HOLD=0 twist), line-follow(불명확 증거=0 명령), IMU(읽기 실패=발행 생략). — 단 sensor_adc는 예외(§8-E).
2. **버저닝 규율**: 경로 `/api/v1`, additive 원칙, Must Ignore, 문서 이력표 v1.0~v1.12와 코드 동행. — 단 표기 3원 불일치(§8-I).
3. **신선도 서버 산출**: `stale_after_s` 서버 판정(D-18/D-72), 프리뷰 `captured_at`/`age_ms` 분리.
4. **대역폭 예산**: raw Image 미탑재(D-118), 프리뷰 2 FPS 최신 1장(D-152), pose 하한 강제, 릴레이 latest-wins.
5. **재접속·멱등**: 로봇 백오프, 릴레이 0.1→2 s, 이벤트 갭 보정(REST reconcile), Host Agent 멱등(성공만 기억 — 실패 재생 방지), 릴리스 저널-선행 기록·전원 유실 복구.
6. **비밀 최소화**: 토큰 sha256, PSK 비저장, Wi-Fi/장비 자격증명 소스 스캔 차단, 감사 redaction.

## 8. 등급표

| 영역 | 등급 | 근거 |
|---|---|---|
| ROS QoS·토픽·주기 규약 | A- | 매칭 불가 0·단일 발행자·주기 일치. 단 잠복 QoS 드리프트 4건(§3.2)과 토픽 중복·어휘 잔재(§3.2.1) |
| 단일 발행자 감시장치 | C | watch_node의 EXCLUSIVE/REQUIRED 테이블이 pinky_* 시절 그대로 — 정책(D-2/D-38)과 반대로 오탐(`control/watch.py:10-42`) |
| REST/WS 표면 정합 | A | 경로·역할·close code·프리뷰 규칙이 계약 그대로 |
| ESP32 장비 계약(도크·신호등) | A- | 계약↔펌웨어↔Fleet 클라이언트 정렬 + 소스 스캔 시험. 실기 ARTIFACT/DEVICE 미증명(STATUS HOLD) |
| Host Agent 전송·인증 | A | unix socket+SO_PEERCRED+allowlist+멱등+감사 redaction, 14/14 변이 증명 |
| 배포 신원·DDS·Wi-Fi | A | 도메인 강제, lo 전용 DDS, NETWORK_HOLD 규칙 |
| **제품 런타임 장치 배관** | **D** | `/dev/rosy-motor` udev 부재로 네이티브 IO가 모터 버스를 못 엶; emotion/lamp/led/imu 장치가 compose·DeviceAllow 어디에도 없음(§8-F) |
| 하드웨어 드라이버 전송 견고성 | C+ | IMU는 우수(건강 토픽·발행 생략) vs **sensor_adc 무음 결함**(§8-E), lamp init `assert(false)` |
| Fleet 프로토콜(로봇 측) | B | 구현 완결이나 상대 부재, backoff 30→60 편차, hello 신원 빈 필드, PRT-004(correlation_id) 미구현 |
| Fleet 시드(허브·콘솔) | B- | `/registry` 무인증, `fleet hub` 죽은 CLI, ADR-1000 no-op 결함, 레지스트리 무퇴거 |
| 시뮬/벤치 도구 토픽 위생 | C | `tools/gz/driver.py:91` 절대 `/cmd_vel` 발행 잔류, 레거시 `/pinky/` 프리픽스 1건 |
| 시간·표기 일관성 | B- | ISO/float-unix/monotonic 혼재, enum 대소문자 혼재(LOWER/UPPER), `power/mode` 토픽만 lowercase |
| 시간 동기화 | B- | chrony 권장(SRS §25)이 이미지/서비스에 미명시 — 타임스탬프 상관 전제 |

공통 한계: 정적 코드·계약 대조. 성능 수치(p95 100 ms, 이벤트 200 ms, heartbeat RTT, DDS 베이스라인) 실측은 DEVICE 게이트(`measure-dds-baseline.sh` 대기, 하드웨어 계열 DEVICE HOLD).

### 주요 리스크 상세

- **§8-D 장치명**: ttyAMA0/ttyAMA4 구분이 dtoverlay 열거 순서에만 의존 — udev by-id 규칙 전무, 향후 UART 추가 시 재열거 위험.
- **§8-E sensor_adc**: `wiringPiI2CRawWrite/Read` 반환 미점검, init 실패 `assert(false)`, 재시도·건강 토픽·stale 플래그 없음 — 버스 결함 시 **0 값을 계속 발행**하여 CORE 신선도 게이트(evidence)를 무효화할 수 있다. 도크·신호등·IMU가 지키는 fail-closed 원칙의 유일한 대형 예외.
- **§8-F 제품 배관**: compose는 `/dev/rosy-motor` 매핑을 만들지만 네이티브 systemd는 `DeviceAllow=/dev/rosy-motor`를 하드코딩 — **호스트에 그 이름을 만드는 udev 규칙이 어디에도 없다**. 또 compose devices·native DeviceAllow에 spidev0.0·i2c-0·gpiomem·PWM이 전무해 emotion/lamp_control/led/imu_bno055는 현재 제품 런타임에서 **실행 자체가 불가**(`measure-dds-baseline.sh:93`은 `imu_raw`를 기대하는데). lamp는 Pi5 커널 모듈 수동 설치 문서뿐.
- **§8-I 프로토콜 버전 표기**: `schemas.py:10`(MINOR 상승 선언) vs `PROTOCOL_VERSION="1.0"` 동결 vs `app.py:55` "(v1.2)" vs 문서 v1.12 — 3개 산출물 3개 답. 문서 v1.8 노트는 "MINOR는 문서 쪽"이라 모듈 docstring과 모순.

## 9. 조치 제안 (우선순위순)

1. **`/dev/rosy-motor` udev 규칙 추가**(by-id/ttyAMA4 심볼릭) 또는 네이티브 유닛을 `ROSY_MOTOR_DEVICE`에서 읽게 변경 — 없으면 D-161 제품 런타임이 모터 버스를 못 연다. DEVICE 게이트 직전 필수.
2. **sensor_adc 전송 견고화**: I2C 반환 점검, 실패 시 발행 생략(IMU 패턴), `sensors/adc/status` 건강 토픽(latched), init `assert` 제거·종료 코드로 교체. CORE의 stale 게이트가 사실상 동작하려면 필수.
3. **제품 장치 표면 결정**: emotion/lamp/led/imu를 (a) 제품 DeviceAllow·compose devices에 배관하거나 (b) 공식적으로 "벤치 전용"으로 계약·capabilities에 명시. 현재는 코드는 있고 운영 경로가 없는 애매 상태.
4. **watch_node 감시 계약 현행화**(`control/watch.py`): REQUIRED를 현행 노드명으로, `EXCLUSIVE['/cmd_vel']` 소유자를 `safety_node`→`core`로, FOREIGN 목록을 D-147 체계로. 단일 발행자 원칙의 런타임 감시장치가 정책과 반대 방향으로 있어, D-149 예외 운용 전 반드시 정렬.
5. **`ir_sensor/range` 이중 발행 가드**: `ir_adc_node`(Python)와 `sensor_adc`(C++)가 동시 구동되지 못하게 launch 상호배제 또는 어댑터 단일화. 교차 배열은 IR 기반 안전 판단(cliff/line)을 교란한다.
6. **프로토콜 버전 표기 3원 정렬**: `schemas.py:10` docstring을 문서 v1.8 노트 방식("envelope 1.0, MINOR는 문서")으로 수정하고 `app.py` 버전 문자열 갱신. `Deprecation`/`Sunset` 헤더(API-003)도 미구현인 만큼 "구현 시" 명시.
7. **PRT-004 방향 결정**: correlation_id·AckPayload 확장을 (a) 중앙 Fleet 착수와 함께 구현하거나 (b) 문서에 "v1 시드 미구현" 표기. 계약만 있고 코드가 없는 상태가 가장 위험한 드리프트.
8. **FleetAgent 정합 3건**: backoff 60→30 s(§7.6), hello 신원 필드를 `RobotIdentity` 확장으로 실값 공급(허브 이중/드리프트 방어 활성화), `fleet_agent/AGENTS.md` 현행화(스텝→설정 게이팅 구현체).
9. **Fleet 시드 결함**: ADR-1000 자동 감속 no-op 수정(`spec.name`→`spec.formation` 또는 속성 추가 — 현재는 조용히 죽음), `fleet hub` 죽은 dispatch 제거 또는 subparser 추가, `/registry` 인증/제거, 레지스트리 퇴거 정책.
10. **QoS 잠복 리스크 청소**: `imu_raw`·`us_sensor/range`·`ir_sensor/range`의 소비자 정책을 SENSOR로 통일(또는 발행자를 SENSOR로 전환할 때 매칭 깨지는 구독자 목록을 계약 테스트로 고정), `map` 소비자 3정책을 LATCHED로 통일(실시간 갱신이 필요한 곳만 SENSOR 명시), `estop` 부재 발행자는 운영자 가이드에 transient_local 발행 명령 예시로 기록.
11. **문서 현행화 2건**: `bridge/AGENTS.md` "6 timers/22 subs"→7/24, API Ref §10에 "미구현(시드는 8090 `/api/fleet/*`)" 표기.
12. **시뮬 도구 토픽**: `tools/gz/driver.py:91` `/cmd_vel` → `cmd_vel_raw` 개명 또는 병행 금지 계약 테스트. D-149 예외 목록에 무단 포함된 형국. `rendered_camera_adapter.py:40`의 `/pinky/rendered_camera`도 개명 후보.
13. **시간·표기 통합(점진)**: 신규 필드는 ISO-8601 통일, `/api/fleet/state`의 `ts` monotonic→ISO 병기, enum 대소문자 표를 문서에 고정, `calibration/*`↔`calib/*` 어휘를 신규 발행분부터 `calibration/*`로 통합. **chrony** 이미지 포함·readback 증거 추가(상관 분석 전제).
14. 소소: `battery_publisher` 노드명 오타, `rosylib` 의존 확인, `wait-core-ready.py` 8080 하드코딩, `v1/system.py` 부실 타입 어노테이션(`CoreServices` 미임포트), CORS 부재를 API Ref에 제약으로 명시, emotion 이중 엔트리포인트 병행 방지 주석/가드, `cmd_vel_raw` 허용 목록에 `control_node` 추가, `sensors/imu/status` 소비자 결정.

## 10. 검증에 사용한 방법

- 계약 문서 4종 + ADR 인덱스 + CORE/FLEET SRS 통신 조항 대독
- `create_publisher/create_subscription/QoSProfile/create_timer` 전체 grep 및 발행·구독·QoS 교차 대조
- 핵심 파일 전문 정독: `ros_bridge.py`, `bringup.py`, `command_deadman.py`, `dynamixel_driver.py`, `ws.py`, `deps.py`, `fleet_agent/agent.py`, `hub/{hub,server}.py`, `swarm/{transport,relay,session,arming}.py`, `server/{app,console}.py`, `node.py`, `host_agent*.py`, C++ 드라이버 3종, `dock/signal` 펌웨어·계약, compose/native/env/Dockerfile/이미지 빌더
- 배포 DDS·신원 추적(`build-native-payload.sh`, `verify-mounted-image.py`, `test_dds_*`, `test_control_launch_boundary.py`)
- 포트 전수 조사(8080/8081/8090/8095/8765/28161-2/시뮬 8080+N)와 타임스탬프·ID 관행 조사

재현은 `Rosy OS` 트리에서 동일 grep·파일 대독으로 가능하다. 본 보고서는 정적 평가이며 STATUS.md 게이트 판정을 대체하지 않는다.
