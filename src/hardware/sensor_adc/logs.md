# sensor_adc logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/sensor_adc`를 본다.

## 2026-09-15 · uncommitted · docs(harness): start the sensor_adc harness record
- 변경: `progress.md`, `logs.md` 추가
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed; LOCAL은 미실행 — `src/sensor_adc`에 `test/` 디렉터리가 없어 host-runnable 대상이 없음 (2026-09-15 Windows)
- gate 변화: 없음(신규 기록). SOURCE GO, LOCAL/ROS-SIM HOLD, ARTIFACT/DEVICE/FIELD N/A(이미지에 미포함)
- 결정: D-61 Proposed
- 교훈: 없음

## 2026-09-16 · uncommitted · docs(harness): regrade sensor_adc gates after review
- 변경: 2차 리뷰 반영. 이미지 제외 시험은 패키지 내용을 읽지 않으므로 SOURCE에서 ARTIFACT 근거로 옮기고, 배선 대기 중인 배포 gate를 N/A에서 HOLD/PARKED로
- 증거: `python3 -m pytest test/test_nav2_hardware_slice.py::test_io_image_packages_nav2_without_slam_or_aux_drivers -q` 1 passed (2026-09-16 재실행)
- gate 변화: SOURCE GO→HOLD, ARTIFACT N/A→HOLD, DEVICE N/A→PARKED, FIELD N/A→PARKED
- 결정: 없음
- 교훈: 없음

## 2026-09-22 · uncommitted · chore: update ARTIFACT blocker to Native Image Builder (D-164)

- 변경: deploy/robot/Dockerfile 의존성을 Native Pi Image Builder로 일괄 변경
- 증거: D-161, D-164
- gate 변화: 없음


# sensor_adc logs

추가만 한다. 형식: [module harness 설계](../../docs/plans/2026-09-15-module-harness-design.md) §4.2.
2026-09-15 이전 이력은 `git log -- src/sensor_adc`를 본다.

## 2026-09-22 · uncommitted · sensor_adc(robustness): 버스 결함은 발행 생략 + 건강 토픽 (T4)
- 변경: `src/main_node.cpp` — ① read_channel/read_cycle 헬퍼로 wiringPiI2CRawWrite/RawRead 반환 점검(쓰기 <1, 읽기 !=2 실패) ② 실패 주기는 us/ir/batt 발행을 전부 건너뛴다(무음 0값 발행 금지 — imu_bno055 패턴, CORE 신선도 게이트가 도착 기준으로 동작하게) ③ sensors/adc/status latched(QoS 1 transient_local) 1 Hz JSON 건강 토픽 신설(ok/consecutive_failures/last_error/standby) ④ init 실패 assert 대신 RCLCPP_FATAL + throw(비정상 종료, 감시자가 재시작 소유) ⑤ RCLCPP_WARN_THROTTLE 2 s 실패 로그. AGENTS.md 갱신.
- 증거: `python -m pytest src/hardware/sensor_adc/test/ -q` 5 passed(계약 시험 3건 적색 후 초록 — 반환 점검·건강 토픽·assert 부재). 컴파일·실측은 ARM64/DEVICE 게이트 남음(Windows 호스트는 빌드 불가). 근거: communication-protocol-report.md §8-E — 버스 결함 시 0값이 신선도 게이트를 무효화하던 유일한 대형 fail-closed 예외.
- gate 변화: 없음(SOURCE 유지). ROS-SIM/DEVICE는 ARM64 빌드 후 판정.
- 결정: 없음 — 기존 fail-closed 원칙(도크·신호등·IMU)에 정렬.
- 교훈: 없음.

## 2026-09-23 · uncommitted · hardware(sensor_adc): wiringPi RawWrite const 호환 (WSL 구문 검사 적색→초록)
- 변경: T4 의 `static constexpr registers[]` 를 그대로 `wiringPiI2CRawWrite(&registers[ch])` 에 넘기면 비-const 시그니처에서 컴파일 실패 — 로컬 `uint8_t reg` 사본을 넘긴다(const/non-const 양쪽 시그니처 호환). T4 fail-closed 자체는 회귀 4350 passed 로 이미 초록.
- 증거: WSL `g++ -fsyntax-only -std=c++17 (ROS Jazzy 헤더 + wiringPi 스텁) src/hardware/sensor_adc/src/main_node.cpp` — 원본 적색(invalid conversion const uint8_t*) → 수정 후 `ADC_SYNTAX_OK` (2026-09-23). 실제 ARM64 네이티브 빌드는 아직 DEVICE 게이트.
- gate 변화: 없음.
- 결정: 없음 — wiringPi 시그니처 불확실성(버전별 const 유무)에 대한 양쪽 호환.
- 교훈: x86 호스트 계약 시험은 C++ 소스를 컴파일하지 못한다 — WSL + wiringPi 스텁으로 -fsyntax-only 를 돌리면 ARM64 전야의 컴파일 결함을 잡을 수 있다.
