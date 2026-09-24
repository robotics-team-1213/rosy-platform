# Pinky Pro 실기 평가표 (D-191)

- **장치:** `rosy-pinky-e4us`(#18, Raspberry Pi 5 Model B Rev 1.1).
- **카드:** release `2026.09.23-005`와 D-189·D-190 응급 조치.
- **관측 조건:** 2026-09-24, PC와 같은 Wi-Fi(`1213_device`), 원격 읽기 전용 검사. 설치나 구동은 하지 않았다.
- **기준:** 공식 Pinky Pro 소스 `pinklab-art/pinky_pro`(로컬 사본 `pinky_pro-main`)와 `docs/plans/2026-09-21-pinky-pro-os-research.md`.

판정:
- **PASS**: 공식 동작과 같거나, 결정된 차이 안에서 동작한다.
- **FAIL**: 동작하지 않는다. 고칠 스토리가 있다.
- **BLOCKED**: 사람이나 추가 증거가 있어야 판정할 수 있다.

| # | 영역 | 공식 Pinky Pro | Rosy 검사 | 결과 (2026-09-24) | 판정 | 스토리 |
|---|---|---|---|---|---|---|
| 1 | 부팅 | 전원 → 사용 가능 | 재부팅 후 PC에서 5 s 간격 관측(`boot-watch.sh`), `systemd-analyze` | 커널 4 s + 사용자 공간 19.5 s = 23.5 s. `--failed` 없음. **005의 응급 조치 상태 기준** | PASS(조건부) | US-002(006에서 조치 없이) |
| 2 | 부팅 표시 시점 | 부팅 완료 시 부저·LCD | `/run/rosy-boot/boot-status.json` 단계 변화 시각 | CORE 준비는 ~20 s였는데 표시는 53-55 s(30 s 타이머). 런타임 뒤 판정 unit을 넣자 t+45 s(PC에서 처음 보이는 시점) | FAIL | US-003 |
| 3 | 현장 Wi-Fi | `wifi_setup.sh` → netplan | NM 활성 프로필, mDNS | `rosy-site-sta:wlan0`, `rosy-pinky-e4us.local` → 10.160.175.16 | PASS | — |
| 4 | 대체 AP | 항상 AP `pinky_XXXX` / `pinkypro` | 현장 Wi-Fi 없이 120 s 대기 | 미시험 | BLOCKED(현장 Wi-Fi 끄는 시험 필요) | US-007 |
| 5 | 원격 접속 | SSH `pinky`/`1` | `ssh -i <operator key> rosy@` | 키 로그인 성공, 비밀번호 로그인 불가(D-174 F3 결정된 차이) | PASS | — |
| 6 | CORE / API | (공식에 없음: Rosy 제품 API) | `/openapi.json`, 인증 경로 | 경로 72개. 인증 없는 요청은 401. **이미지 경로에서 토큰을 발급하지 않아** 대시보드·API에 아무도 로그인할 수 없다(`/etc/rosy/initial-credentials.txt`는 Docker 경로에만 있다) | FAIL | US-009 |
| 7 | 릴리스 복구 게이트 | — | `rosy-release-recover` 상태 | 005는 샌드박스 결함으로 실패, 응급 조치 뒤 `{"ok": true}`. 수정은 006(D-189)에 있다 | FAIL→006 | US-002 |
| 8 | 권한 경계 D-161 | — | `/var/lib/rosy` 소유, unit 환경 | 005는 CORE가 전체를 소유했다. 응급 조치로 root로 되돌렸다. 수정은 006에 있다 | FAIL→006 | US-002 |
| 9 | 모터 버스 | DYNAMIXEL XL330 ×2, `/dev/ttyAMA4` 1 Mbaud (`pinky_bringup/bringup.py` 23-24행) | `/dev/ttyAMA4`, `/dev/rosy-motor` | **둘 다 없음.** udev 규칙은 `ttyAMA4`를 기대하지만 `config.txt`에 `dtoverlay=uart4-pi5`가 없다. 저장소의 `configure-uart-pi5.sh`는 이미지에 반영되지 않는다 | FAIL | US-004 |
| 10 | 모터 SDK | `dynamixel_sdk` 사전 설치(package.xml 미선언) | `import dynamixel_sdk` | 없음(Docker 경로만 `dynamixel-sdk==3.8.4`를 pip로 설치) | FAIL | US-005 |
| 11 | 라이다 | RPLIDAR C1, `/dev/ttyAMA0`, `sllidar_ros2` 외부 패키지 | 장치 노드, `ros2 pkg prefix sllidar_ros2` | `ttyAMA0` 있음. **`sllidar_ros2` 없음**(Docker 경로만 고정 커밋으로 빌드) | FAIL | US-005 |
| 12 | 배터리(하드웨어) | ADC I2C-1 0x08 ch4, `pinkylib.Battery` | ADC 직접 읽기(읽기 전용) | 8.665-8.682 V, 5회 안정. `BatteryCurve.default()` 100 % | PASS | — |
| 13 | 배터리(소프트웨어) | `battery_publisher`(pinkylib) → `/battery/*` | `import rosylib`, `rosy-io` | **`rosylib` 없음**(pinkylib를 이름만 바꿔 import했고, 공개 소스가 없다). `rosy-io` unit이 이미지에 없다 | FAIL | US-005 |
| 14 | 하드웨어 런타임 | bringup_robot(description, sllidar, bringup, battery_publisher) | `rosy-io.service` 설치 여부 | 릴리스 안에 unit 파일은 있으나 이미지 overlay와 enable에 없다(D-189 열린 항목) | FAIL | US-005 |
| 15 | IMU | BNO055 `/dev/i2c-0` 0x28, 공식 bringup_robot에는 없음 | `/dev/i2c-0` | 없음. 벤치 전용(D-169)이고 공식 기본 bringup에도 없다 | PASS(결정된 차이) | — |
| 16 | 카메라 | ROS 노드 없음. `pinkylib.Camera`·데스크톱 스트리밍(v1.9+) | 센서 열거 | `/dev/video19-37`은 ISP·코덱뿐이고 센서는 열거되지 않는다 | BLOCKED(연결·드라이버 증거 필요) | US-004 |
| 17 | LCD | ST7789 SPI0 CE0, RST27/DC25/BL18, 부팅 시 AP 정보 | `/dev/spidev0.0`, 한 번 그리기 | spidev 노드는 있다. 제품 이미지에 `spidev`·`RPi.GPIO`가 없다. 응급 설치 뒤 한 번 그린 화면은 보이지 않았다 | FAIL | US-006 |
| 18 | 부저 | 부팅 완료 시 울림(pinkylib.Buzzer) | 핀 | 핀이 공개되지 않았다(pinkylib 비공개) | BLOCKED(핀 증거) | US-006 |
| 19 | LED / lamp | pinkylib.LED, WS2812 `lamp_bringup.service` | — | 벤치 전용(D-169). `rosylib.LED`도 없다 | PASS(결정된 차이) | D-181 |
| 20 | 모터 구동 | — | 런북 G4(바퀴 들고, E-stop, 두 사람) | 사람이 있어야 한다 | BLOCKED | US-008 |

## 행 17·18 계획 (US-006, D-190 S1·S2 완료 2026-09-24)

005 카드의 판정은 위 표 그대로다. 다음 이미지에서 두 행을 다시 채울 때의 기준이다.

| # | 다음 이미지에 들어간 것 | 확인 방법 | PASS 조건 |
|---|---|---|---|
| 17 | `rosy-boot-display.service`(enable, 사용자 `rosy-display`, 장치 3개만), apt `python3-spidev`·`python3-rpi-lgpio`, 상주 프로세스(백라이트 PWM 유지), 부팅 카드(이름·IP·단계·실패 unit·배터리·AP) | D-190 "S3 실기 확인" 1-8, 10 | 전원 뒤 LCD에 BOOTING → READY, 배터리 ±0.05 V, 실패 unit 표시, AP 모드 SSID·비밀번호, 재부팅 반복 |
| 18 | 부저 BCM 22, **기본 꺼짐**. `CORE_READY` 1회·`FAILED` 3회 | D-190 "부저 핀 확인" 뒤 "S3 실기 확인" 9 | 사람이 핀을 확인해 D-190 표에 기록하고, 켠 상태에서 `CORE_READY`에 한 번 울림. 확인 전에는 BLOCKED(핀 증거) 유지 |

## 우선순위 (배포 가능 기준)

1. **US-002:** 006으로 다시 구워 1·7·8을 응급 조치 없이 PASS로 만든다.
2. **US-009:** 카드마다 API 토큰을 발급해 6을 PASS로 만든다. 대시보드와 API를 쓰려면 반드시 필요하다.
3. **US-004 → US-005:** 모터 UART, 라이다 드라이버, 모터 SDK, 배터리 라이브러리, 하드웨어 런타임 unit(9-11, 13, 14)을 해결한다.
4. **US-003:** 부팅 표시 시점(2)을 고친다.
5. **US-006:** LCD·부저(17, 18)를 고친다(D-190 S0부터).
6. **US-007:** 007 이미지로 전체를 다시 검사한다.
7. **US-008:** 사람과 함께 모터 구동을 검사한다.
