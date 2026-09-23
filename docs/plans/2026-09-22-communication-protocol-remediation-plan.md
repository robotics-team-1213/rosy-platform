# 통신·프로토콜 정합 개선 실행 계획 (Communication Protocol Remediation Plan)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

- Date: 2026-09-22
- Status: **전 페이즈·전 태스크 완료(T1~T15).** Phase 1(T1~T4) — 998b9f9·545cb0b·2d47b5a·56355f9. Phase 2(T5~T9) — 4ee66a7·e23ca18·745bb80·7b09b0d·455f48f. Phase 3(T10~T11) — a29caee·10ceb53. Phase 4(T12~T14) — e65a5a0·f9d6f09·9742084(+d927cea 정정분). T15 — 8e88de4(최종 전체 회귀 **4350 passed·0 failed**). 결정 게이트 G1·G2 — D-169·D-170 Accepted(451223c). Linux 측 추가 검증(2026-09-23, WSL x86_64 ROS 2 Jazzy) — colcon 20패키지 빌드 성공, sensor_adc `g++ -fsyntax-only` 적색→초록(16811e5), CI 동등 부트 스모크에서 `ros_bridge ready`·`core up`·우아한 종료 확인. 남은 것: ARM64/DEVICE 게이트(native ARM64 빌드·udev 심링크 실측·chrony 동기화 품질)와 후속 ADR **D-176·D-177(Proposed 로 등록 완료)** — 조건(D-84 프로필+실기 수요 / 중앙 Fleet 착수) 확정 시 Status 를 Accepted 로 바꾸기만 하면 된다.
- Goal: `communication-protocol-report.md`(2026-09-22, Rosy 폴더 — git 루트 밖)의 §9 조치 14건을 test-first로 실행한다.
- Architecture: 4개 페이즈(안전·차단 해소 → Fleet 정합 → 계약·문서 정합 → 잔여 위생). 모든 태스크는 **Windows host pytest로 검증 가능**하며, C++ 빌드·실측이 필요한 것만 "ARM64 게이트"로 표시한다. 계약 결정이 필요한 2건은 태스크가 아니라 결정 게이트로 분리했다.
- Tech Stack: pytest(host), colcon/ament(Linux), udev, systemd, FastAPI/websockets, pydantic
- 커밋: 태스크 단위로 `Rosy OS` git 루트에서. 메시지는 짧은 명령형(행위 요약).
- 공통 사전 확인: 각 모듈 `progress.md`·`logs.md`를 읽고 시작한다(D-61). 태스크 완료 시 해당 모듈 `logs.md` append.

## 우선순위 요약

| Phase | 내용 | 긴급도 | 근거(보고서 §) |
|---|---|---|---|
| 1 | 그래프 감시·이중 발행·udev·sensor_adc | 최우선 | §8-D/E/F, §3.2.1 |
| 2 | FleetAgent·Fleet 시드 정합 | 높음 | §5 |
| 3 | 계약 문서·표기 정합 | 중간 | §4, §8-I |
| 4 | 잔여 위생(QoS·포트·chrony·소소) | 낮음 | §3.2, §6 |
| G | 결정 게이트 2건(제품 장치 표면, PRT-004) | 판정 대기 | §8-F, §5 |

---

## Phase 1 — 안전·차단 해소 — **완료 (2026-09-22)**

### T1: watch_node 감시 계약 현행화 [최우선] — ✅ 커밋 998b9f9

실제 이행: EXCLUSIVE 값을 소유자 **집합**으로 바꾸고 `/cmd_vel` 허용 소유자를 `{core, safety_node}`로 확정 — 단, **동시에 두 소유자가 발행하면 co_owner 인터럽트**(D-38 병행 금지의 런타임 감시)를 신종 이슈로 추가했다. 신규 시험 8건(test_watch.py 계약+행위), pinky_* 참조 시험 3건은 브리지 트윈(parameter_bridge/image_bridge)으로 갱신.

### T2: ir_sensor/range 이중 발행 상호배제 [최우선] — ✅ 커밋 545cb0b

실제 이행(계획 대비 조정): 시험 위치를 repo `test/test_ir_source_exclusivity.py`로 옮김(스캔이 navigation·hardware 트리를 건드림). `install-pi.sh`(레거시 컴포즈 경로) 대신 **이미지 오버레이가 규칙을 굽는 경로**로 T3에서 처리하고, T2는 launch 마커 주석("ir_sensor/range single-publisher rule") + 전 launch 교차 스캔(주석 라인 제외) + calib_node의 pinky_sensor_adc 메시지 2건 정정으로 구성. launch 인자(`ir_source`) 추가는 하지 않았다 — `start_ir_adc` 게이트가 이미 존재하여 YAGNI.

### T3: /dev/rosy-motor udev 규칙 [최우선 — DEVICE 블로커] — ✅ 커밋 2d47b5a

실제 이행(계획 대비 조정): `install-pi.sh` 경로 대신 **`build-native-payload.sh` 이미지 오버레이에 규칙 굽기**(+소스 존재 가드)와 `configure-uart-pi5.sh` 소급 설치(멱등 조기 종료 경로 **앞에** 배치해 재실행도 규칙 설치)의 2중 경로(D-161 정합). 시험 `test/test_rosy_motor_udev.py` 4건(규칙 내용·스크립트 배치·이미지 베이킹·유닛/프로브 별칭 교차 검증). bash -n 구문 0.

### T4: sensor_adc 전송 견고화 [최우선] — ✅ 커밋 56355f9 (소스 계약 host 통과, 빌드·실측은 ARM64 게이트)

실제 이행: read_channel/read_cycle 헬퍼(쓰기 <1·읽기 !=2 점검), 실패 주기 **발행 전면 생략**, `sensors/adc/status` latched 1 Hz JSON 건강 토픽(ok/consecutive_failures/last_error/standby), init `assert(false)`→`RCLCPP_FATAL`+`throw`, WARN_THROTTLE 2 s. 계약 시험 3건 신설(`test_adc_package_contract.py`).

**Phase 1 공통 증거**: control 스위트 1292 passed/28 skipped, udev·네이티브·이미지 계약 118 passed, sensor_adc 5 passed (2026-09-22 Windows host). 전체 호스트 회귀는 실행 중(완료 시 docs/logs.md에 기록).

---

*(T1~T4 원본 계획 단계는 위 이행 요약으로 대체했다 — 실행 세부·시험은 각 커밋과 모듈 logs.md 에 있다.)*

## Phase 2 — Fleet 정합

### T5: FleetAgent backoff 상한 30 s

**Files:**
- Modify: `src/core/core_features/core_features/fleet_agent/agent.py:60,117-119`
- Test: `src/core/core/test/test_fleet_agent.py`

**Step 1 — 실패 시험.** 모듈 상수 `MAX_BACKOFF_S == 30.0` 주장 + backoff cap 계산이 상수를 쓰는지 소비(리터럴 `60.0` 부재 스캔). 근거: API Ref §7.6 "1s → 2s → … 최대 30s".

**Step 2 — 적색.** Run: `python -m pytest "src/core/core/test/test_fleet_agent.py" -q`

**Step 3 — 구현.** `MAX_BACKOFF_S = 30.0` 추출, `backoff = min(backoff * 2, MAX_BACKOFF_S)`.

**Step 4 — 통과.** Step 5 — 커밋. `fleet_agent: reconnect backoff caps at 30s (PRT-006/API Ref §7.6)`

### T6: RobotIdentity 신원 필드 + hello 실값

**Files:**
- Modify: `src/core/core_common/core_common/identity.py:40-67` (additive)
- Modify: `src/core/core_features/core_features/fleet_agent/agent.py:70-77` (hasattr 제거)
- Test: `src/core/core/test/test_fleet_agent.py`, `src/site/fleet/test/test_hub.py`

**Step 1 — 실패 시험.** (a) `RobotIdentity`가 `device_uid`, `device_name` 속성을 가짐(기본 `""`, config `robot.device_uid`/`robot.device_name`에서 유도, `device_name` 폴백 `robot_name`), (b) hello payload가 `model=profile_model`, `hardware_serial=serial`을 실값으로 싣고 `hasattr` 문자열이 agent.py에 없음, (c) test_hub.py에 `device_uid` 중복 → `DUPLICATE_IDENTITY`, `hardware_serial` 드리프트 → `IDENTITY_DRIFT`가 **비어 있지 않은 값에서 발동**하는 케이스(현재는 발동 불가 경로).

**Step 2 — 적색.** Run: `python -m pytest "src/core/core/test/test_fleet_agent.py" "src/site/fleet/test/test_hub.py" -q`

**Step 3 — 구현.** identity는 additive 선택 필드만. agent의 hello 생성을 직접 속성 접근으로 교체.

**Step 4 — 통과 + schema suite 회귀.** Run: `python -m pytest "src/core/core/test/test_protocol_schemas.py" "src/core/core/test/test_fleet_agent.py" "src/site/fleet/test/test_hub.py" -q`

**Step 5 — 커밋.** `identity: device_uid/device_name additive; fleet_agent hello carries real identity`

### T7: ADR-1000 자동 감속 no-op 수정

**Files:**
- Modify: `src/site/fleet/fleet/server/console.py:411-422`
- Test: `src/site/fleet/test/test_server_console.py`

**Step 1 — 실패 시험.** 저하 멤버가 있을 때 `formation_reform`이 **실제로 호출**됨을 fake 세션으로 증명(현재는 `spec.name` 부재 `AttributeError`가 `except Exception: pass`에 흡수되어 미호출 — 이 시험이 적색). 호출 시 인자가 현재 formation(`spec.formation`)임을 함께 주장.

**Step 2 — 적색.** Run: `python -m pytest "src/site/fleet/test/test_server_console.py" -q`

**Step 3 — 구현.** `formation=session.spec.formation`으로 수정. `except Exception: pass`는 최소 `logger.warning("auto speed reform failed: %s", exc)`로 교체(재시도 폭주 방지는 기존 `current_speed > degraded_speed + 0.01` 가드가 담당).

**Step 4 — 통과.** Step 5 — 커밋. `fleet: fix ADR-1000 auto-slowdown no-op (spec.formation, logged failures)`

### T8: `fleet hub` 죽은 CLI 제거

**Files:**
- Modify: `src/site/fleet/fleet/cli.py:253-266,299-301`
- Test: `src/site/fleet/test/test_cli.py`

**Step 1 — 실패 시험.** (a) `parse_args`의 subparser choices에 `hub` 부재 주장, (b) 소스에 `args.command == "hub"` dispatch 부재 스캔. (허브 서버 자체는 유지 — 테스트가 직접 `create_hub_app`을 쓴다.)

**Step 2 — 적색 → Step 3 — 구현.** `main()`의 hub 분기와 `run_hub` 함수 제거(YAGNI; 부활은 중앙 Fleet 착수 시 subparser와 함께).

**Step 4 — 통과.** Run: `python -m pytest "src/site/fleet/test/test_cli.py" "src/site/fleet/test/test_boundaries.py" -q`
**Step 5 — 커밋.** `fleet: remove dead 'hub' CLI dispatch (server stays test-reachable)`

### T9: hub /registry 선택적 인증

**Files:**
- Modify: `src/site/fleet/fleet/hub/server.py:12-25`
- Test: `src/site/fleet/test/test_hub.py`

**Step 1 — 실패 시험.** `create_hub_app(hub, token=None)`: 토큰 없으면 현재 동작(개방 — 로컬 시드), 토큰 있으면 `/registry`가 `Authorization: Bearer` 불일치 시 401. private `registry._robots` 직접 접근을 `hub.registry.snapshot()` 같은 공개 메서드로 대체(캡슐화).

**Step 2 — 적색 → Step 3 — 구현 → Step 4 — 통과.**
Run: `python -m pytest "src/site/fleet/test/test_hub.py" -q`
**Step 5 — 커밋.** `fleet hub: optional bearer token on /registry, no private registry access`

---

## Phase 3 — 계약·문서 정합

### T10: 프로토콜 버전 표기 3원 정렬 + API Ref 갱신

**Files:**
- Modify: `src/core/core_common/core_common/protocol/schemas.py:1-11,24` (docstring만)
- Modify: `src/core/core_api_web/core_api_web/api/app.py:52-56` (버전 문자열)
- Modify: `docs/reference/ROSY API & Protocol Reference.md` (§1, §2, §4, §7.5, §10 + 변경 이력 v1.13)
- Test: `src/core/core/test/test_protocol_schemas.py` (회귀), 문서 인덱스 재생성

**Step 1 — 실패 시험.** (a) schemas.py docstring에 "envelope `protocol_version` 은 1.0 고정, additive 는 문서 MINOR 로 기록" 문구 존재(리터럴 "MINOR 상향" 구문 제거), (b) `app.py`의 FastAPI `version`/description이 문서 v1.13과 일치("v1.12" 문자열 부재), (c) API Ref §10 상단에 "미구현 — 시드 콘솔은 :8090 `/api/fleet/*`" 표기 존재.

**Step 2 — 적색.** Run: `python -m pytest "src/core/core/test/test_protocol_schemas.py" -q` (+ 문구 스캔 시험)

**Step 3 — 구현.**
- schemas.py docstring을 문서 v1.8 노트와 동일한 규칙으로 교체(코드·문서·앱 3자 동일 답).
- API Ref: §1에 `Deprecation`/`Sunset` 헤더 "구현 전 — 폐기 시점에 구현" 명시, §2에 CORS 부재 제약 명시(동일 출신 대시보드 전제, 외부 브라우저 클라이언트는 서버 측 프록시 필요), §4에 enum 대소문자 표(UPPER: mode/navigation/dock/power, lower: severity/battery/presence/swarm) 추가, §7.5에 "PRT-004 correlation_id·확장 AckPayload는 중앙 Fleet 착수와 함께 구현 — v1 로봇 측 미구현" 표기. 이력표에 v1.13 행.
- `app.py` description/버전 갱신.

**Step 4 — 통과 + harness.**
Run: `python -m pytest "src/core/core/test/" -q` → `python tools/harness/rosy_harness.py lint` → `python tools/harness/rosy_harness.py generate`
**Step 5 — 커밋.** `docs+api: align protocol version notation (envelope 1.0, doc MINOR), mark §10 unimplemented`

### T11: AGENTS 현행화 2건 + 소소 수정 팩

**Files:**
- Modify: `src/core/core_features/core_features/fleet_agent/AGENTS.md` (스텁→설정 게이팅 구현체 기술, T5/T6 반영)
- Modify: `src/core/core/core/bridge/AGENTS.md` ("6 timers/22 subs" → "7 timers/24 subs, line-follow 20 Hz 포함")
- Modify: `src/hardware/bringup/bringup/battery_publisher.py:8` (`battery_publihser`→`battery_publisher`)
- Modify: `src/core/core_api_web/core_api_web/api/v1/system.py` (부실 어노테이션 `CoreServices`→`CoreServicesLike` 또는 import 추가)
- Test: 해당 패키지 계약 시험 회귀

**Step 1 — 확인.** `python -m pytest "src/core/core_api_web/test/" -q` (현행 통과 확인 후 문서·문자열만 수정 — 이 태스크는 행위 변화 없음, 시험은 회귀 용도)
**Step 2 — 구현** (위 4건 + bridge AGENTS에 구독 24 목록 갱신).
**Step 3 — 회귀.** Run: `python -m pytest "src/core/core_api_web/test/" "src/hardware/bringup/test/" -q`
**Step 4 — 커밋.** `docs: refresh fleet_agent/bridge AGENTS to current code; fix battery node name typo`

---

## Phase 4 — 잔여 위생 — **완료 (2026-09-22/23, T15 진행 중)**

이행 요약: T12(커밋 e65a5a0) — tools/gz 6개 파일 발행 토픽 상대화 + 전 스캔 가드 `test_gz_tools_topics.py`(구독 제외). PowerShell BOM 사고 학습됨. T13(f9d6f09) — startup_calibration·safety 의 us/ir/imu 구독 SENSOR 통일(호환성 확대만), STEPS.txt 에 /estop transient_local 발행 예시, 가드 3건 변이 증명. T14(9742084) — wait-core-ready 가 ROSY_API_PORT 따름(행위 시험), chrony 설치+enable+이미지 검증(픽스처 2종 갱신, 부재/비활성 거부 케이스), 타 세션의 API Ref 버전 고정 시험 헤더 판독형으로 수선.

### T12: tools/gz 절대 토픽 정리

**Files:**
- Modify: `src/apps/control/tools/gz/driver.py:91` (`'/cmd_vel'`→`'cmd_vel'` 상대화 + "core와 병행 금지" 주석)
- Test: `src/apps/control/test/test_gz_tools_topics.py` (신규)

**Step 1 — 실패 시험.** `tools/gz/*.py` 전체 스캔: `create_publisher` 첫 인자 토픽 문자열이 `/`로 시작하면 실패(절대 토픽 발행 금지 — 구독은 제외, `rendered_camera_adapter.py:40`의 `/pinky/rendered_camera` **구독**은 허용하되 주석 요구).
**Step 2 — 적색 → Step 3 — 구현** (driver.py 상대화; 필요 시 노드 namespace 파라미터 통과).
**Step 4 — 통과.** Run: `python -m pytest "src/apps/control/test/test_gz_tools_topics.py" -q`
**Step 5 — 커밋.** `control tools: gz drivers publish relative topics only`

### T13: QoS 잠복 리스크 고정

**Files:**
- Modify: `src/apps/control/control/startup_calibration_node.py:90` (`imu_raw` d10→`qos_profile_sensor_data`)
- Modify: `src/apps/control/control/safety/node.py:221-226` (`us_sensor/range`·`ir_sensor/range` d10→SENSOR)
- Modify: `src/apps/control/control/AGENTS.md` 또는 `STEPS.txt` (estop 운영자 발행 예시: `ros2 topic pub --qos-durability transient_local --qos-reliability reliable ...`)
- Test: `src/apps/control/test/test_os_calibration_graph.py` (+ wiring 계약에 QoS 패턴 주장)

**Step 1 — 실패 시험.** 대상 구독문이 `qos_profile_sensor_data`를 쓰는지 문자열 패턴 주장. 호환성 근거: 발행 측은 RELIABLE(≥구독 BEST_EFFORT 요구)이라 매칭 유지, 센서 유실 시계에서 소비자 정책만 통일.
**Step 2 — 적색 → Step 3 — 구현** (`map` 소비자 3정책은 동작 변경 없이 `bridge/AGENTS.md`에 현행 매칭 표로 고정 — T11과 병합 가능).
**Step 4 — 통과.** Run: `python -m pytest "src/apps/control/test/" -q`
**Step 5 — 커밋.** `control: unify sensor-topic subscriber QoS (D-119 consumer side)`

### T14: wait-core-ready 포트 파라미터화 + chrony 계약

**Files:**
- Modify: `deploy/robot/native/wait-core-ready.py:13` (`ROSY_API_PORT` 환경변수, 기본 8080)
- Modify: `deploy/image/customize-rootfs.sh:124` (패키지 목록에 `chrony`)
- Modify: `deploy/image/verify-mounted-image.py` (+ 체크리스트: chrony 설치·서비스 활성)
- Test: `test/test_native_systemd_contract.py`, `test/test_verify_mounted_image.py`

**Step 1 — 실패 시험.** (a) wait-core-ready에 8080 리터럴이 환경변수 폴백 형태(`os.environ.get("ROSY_API_PORT", "8080")`)로만 존재, (b) customize-rootfs.sh에 `chrony`, (c) verify 스크립트 검사 목록에 chrony 서비스. 근거: CORE SRS §25 시간 동기화 — 타임스탬프 상관·`received_at` 신선도의 공동 전제. 동기화 **품질**은 DEVICE.
**Step 2 — 적색 → Step 3 — 구현 → Step 4 — 통과.**
Run: `python -m pytest test/test_native_systemd_contract.py test/test_verify_mounted_image.py -q`
**Step 5 — 커밋.** `deploy: parameterize readiness port; chrony install+enable contract`

### T15: 하네스 갱신 (통합 마감)

**Files:** 변경된 각 모듈의 `progress.md`/`logs.md`, `STATUS.md` 재생성

**Step 1.** control/fleet/core(deploy)/sensor_adc 각 `logs.md`에 이번 변경 append, 게이트가 움직인 것만 `progress.md` 갱신.
**Step 2.** repo root에서 `python tools/harness/rosy_harness.py lint` → `generate`.
**Step 3.** 전체 회귀:
Run: `python -m pytest "src/core/core/test/" "src/apps/control/test/" "src/site/fleet/test" "src/apps/omx_adapter/test" "src/apps/games/test" test/ -q`
Expected: 전체 PASS (Windows host 범위).
**Step 4 — 커밋.** `harness: refresh module gates after protocol-remediation pass`

---

## 결정 게이트 — **판정 완료 (2026-09-22, D-169·D-170 Accepted)**

### G1: 제품 장치 표면 — emotion/lamp/led/imu → **D-169 Accepted**

- **Context**: compose devices·native `DeviceAllow`에 spidev0.0·i2c-0·gpiomem·PWM이 없어 4개 장치 패키지(emotion, lamp_control, led, imu_bno055)가 제품 런타임에서 실행 불가하다. 코드는 존재하나 운영 경로가 없는 애매 상태였고, 제품 capabilities는 이미 `sensors: [lidar, encoder]`만 광고 중(통신 보고서 §8-F).
- **Decision**: v1 제품 장치 표면을 **모터(UART4)·LiDAR(ttyAMA0)·카메라(video0)·I2C-1 ADC(ir_adc_node)** 로 고정하고, 4개 장치 노드는 **벤치 전용을 소급 공식화**한다. 이는 이미 시험이 강제하던 상태(compose devices 열거, io 이미지 aux 드라이버 제외, capabilities sensors 표)의 공식화일 뿐 행위 변경이 없다.
- **Consequences**: ① 장치 노드의 제품 편입(장치 배관·capabilities 확장)은 하드웨어 프로필(D-84)과 실기 수요가 확정되는 후속 ADR로만 연다. ② `measure-dds-baseline.sh`의 `imu_raw`는 벤치 IMU 노드 기동 시에만 잰다는 주석을 달았다. ③ 결정은 `test/test_device_surface_contract.py`가 고정한다(compose devices·native DeviceAllow·capabilities가 D-169 면 외에 넓어지면 적색).

### G2: PRT-004 (correlation_id·AckPayload) → **D-170 Accepted**

- **Context**: `Envelope.correlation_id`는 계약·스키마에 존재하지만 어떤 런타임 경로도 설정·소비하지 않으며, `AckPayload`는 문서 §9.5보다 얇다(통신 보고서 §5).
- **Decision**: PRT-004 확장 구현은 **중앙 Fleet 서버 착수(FLEET SRS Phase 4)와 함께** 간다. 그 전까지 correlation_id는 계약 전용 필드로 남고, API Ref §7.5가 이 상태를 명시한다(v1.13 상태 표기 정정).
- **Consequences**: ① 로봇 측에 선제 구현을 넣지 않는다(계약-코드 반대 방향 드리프트 방지). ② 중앙 Fleet 착수 시 correlation_id 설정·소비와 `AckPayload`의 `TIMEOUT`·`issued_by`·`ts_issued/ts_final` 확장을 같은 변경에 담는다. ③ `schemas.py`의 `correlation_id` 주석이 D-170을 가리킨다.

## 범위 밖 (본 계획이 하지 않는 것)

- DDS XML 와이딩(로봇 간 직접 DDS) — D-33 위반, 별도 아키텍처 결정 필요
- TLS/전송 암호화(로봇 API·도크·신호등 평문 HTTP) — 계약이 명시적으로 수용한 위험, 명령 표면 확장 시 재판정
- 중앙 Fleet 서버 구현, `correlation_id` 런타임 도입(G2)
- `calibration/*`↔`calib/*` 어휘 통합 마이그레이션 — 신규 발행분부터 통일하는 가이드만(T11 문서에 반영 가능), 일괄 개명은 별도 계획
- 성능 실측(p95, 이벤트 200 ms, DDS 베이스라인) — DEVICE 게이트(`measure-dds-baseline.sh`)
- C++ 3종(led/lamp/imu)의 제품화 — G1 판정 후 별도 계획

## 검증 명령 요약 (Windows host, repo root `Rosy OS`)

```bash
python -m pytest "src/core/core/test/" "src/apps/control/test/" "src/site/fleet/test" "src/apps/omx_adapter/test" "src/apps/games/test" test/ -q
python tools/harness/rosy_harness.py lint
```

Linux/Pi(ARM64) 추가: `cd src && colcon build --symlink-install` → sensor_adc/led/lamp/imu 빌드 → hardware 모드 실측.
