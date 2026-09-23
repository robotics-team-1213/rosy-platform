# 부팅 표시 공식 동등성 실행 계획 (D-190)

> 순서를 건너뛰지 않는다. 각 단계는 앞 단계의 증거가 있어야 시작한다.
> 장치에 손으로 넣는 변경은 증거 수집용일 때만 하고, 넣은 즉시 D-190 "응급 조치 기록"에 적는다.

**목표:** 전원을 넣으면 공식 Pinky Pro처럼 부저가 울리고 LCD에 상태가 뜬다.
LCD에는 이름, IP, 부팅 단계(실패 시 실패 unit), 배터리, 그리고 AP가 열렸을 때 SSID·비밀번호가 나온다.
이 동작은 저장소 → 이미지 → 서명 → 카드 경로로만 들어간다.

---

## S0. 공식 동작 증거 (구현 없음)

**사람:** 여분 SD 카드 1장에 공식 Pinky Pro 이미지(`pinky_pro_v1.9` 이상)를 굽고 로봇에 넣어 부팅한다.
**에이전트:** 그 카드에서 `deploy/robot/capture-vendor-baseline.sh`를 실행하고, 공식 소스를 읽는다.

확정할 것(각각 파일·명령 출력으로 증거를 남긴다):

1. 부팅 때 LCD를 그리는 주체. systemd unit인지 cron인지 rc 스크립트인지, 실행 사용자, 시작 순서를 확인한다.
2. Pi 5에서 쓰는 GPIO 라이브러리. `python3 -c "import RPi.GPIO; print(RPi.GPIO.__file__, RPi.GPIO.VERSION)"`로 본다.
3. 백라이트 구동: PWM인지 단순 HIGH인지, 프로세스가 계속 떠 있는지. D-190 가설(한 번 그리고 끝나면
   백라이트가 꺼진다)을 여기서 확인하거나 기각한다.
4. 부저 핀, 소리 패턴, 구동 방식.
5. 표시 폰트, 화면 방향, 문구.
6. 배터리 백분율 계산법과 LCD 표시 여부.
7. 결과를 `docs/validation/vendor-baseline-2026-09-XX/`에 남긴다. 비밀 스캐너를 통과한 것만 올린다.

**완료 조건:** 위 6개 항목이 모두 "확인됨 + 증거 경로"로 채워진다. 하나라도 비면 S1로 가지 않는다.

### S0 결과 (2026-09-24, 공개 소스 조사)

| 항목 | 결과 | 근거 | 확실도 |
|---|---|---|---|
| 백라이트 | `GPIO.PWM(18, 1000)`은 그 Python 프로세스가 살아 있는 동안만 돈다. `close()`가 `bl.stop()`과 `GPIO.cleanup`을 부른다. 한 번 그리고 끝나는 스크립트는 화면이 꺼진다 | `pinky_pro/pinky_emotion/pinky_emotion/pinky_lcd.py` 1-33행, 140-147행 | 확정 → 표시 unit은 상주 프로세스 |
| LCD 드라이버 | `spidev` 0.0, RST 27 / DC 25 / BL 18, `RPi.GPIO` | 같은 파일. Rosy `rosy_lcd.py`와 동일 | 확정 |
| Pi 5 GPIO | `RPi.GPIO` 호환층 `python3-rpi-lgpio`, `python3-spidev`(apt) | 형제 보드 `pinklab-art/pinky_violet` README "dependence 설치" | 유력(Pro 문서에는 없음) |
| 부저 | Pro 핀은 공개되지 않았다. 형제 보드 두 종이 BCM 22, 패시브, `GPIO.PWM`을 쓴다 | `pinky_violet/.../pinkylib/buzzer.py` 1-9행, `pinky_study/1_pinky_blue/part1/01_buzzer.ipynb` | 미확정 → 실기에서 들어 보고 확정(사람 입회) |
| 부팅 완료 부저 | 공개 자료에 없다. 위키 초기 설정의 "부저가 3번 울리는지 확인"은 수동 시험이다 | `pinky_study` wiki "0. 초기설정(PinkyPro)" | 미확정 |
| 부팅 LCD의 Wi-Fi 정보 | 공개 코드에 없다. 공식 Wi-Fi 설정은 BLE 앱 `pinky_desktop`(v1.8+)이고, 위키의 LCD 시험은 "초록 화면 3초"다. 연구 문서 §4의 "LCD에 SSID·비밀번호"와 충돌한다 | `pinky_desktop` README, 위키 | 재확인 필요 → Rosy는 AP가 열렸을 때만 AP 정보를 LCD에 표시한다(D-176 연계) |
| 배터리 % | `pinkylib` 내부라 공개되지 않았다. 공개된 값은 저전압 기준 `LOW_BATTERY_THRESHOLD = 6.8` V뿐이다 | `pinky_bringup/bringup.py`, `battery_publisher.py` | 미확정 → Rosy `BatteryCurve.default()`(2S 곡선)를 쓴다 |
| 카메라 | Pro 모델은 공개되지 않았다(`pinkylib.Camera`). 형제 보드는 CSI + Picamera2다 | `pinky_violet/.../camera.py` | 유력 → 실기 센서 열거가 먼저다(평가표 16행) |

**S0 남은 확인(사람 입회, 증거 수집으로 기록):** 짧은 PWM 톤으로 BCM 22가 부저인지 확인한다. 공식 동작에 없는
부팅 부저 패턴은 Rosy가 정한다(`CORE_READY` 한 번, `FAILED` 세 번).

## S1. 장치 편입 결정 (D-181 표 채우기)

1. 수요: D-190 동등성 표가 수요 문서다.
2. 프로필: `profile.*.yaml`·capabilities에 `display.lcd`, `display.buzzer`, `power.battery_adc`를 선언할 수
   있는지 확인한다. D-32에 따라 지킬 수 있을 때만 광고한다.
3. 배관 범위를 확정한다.
   - `spidev0.0`
   - gpiochip 선 18·25·27과 부저 선
   - `i2c-1`(CORE-only 모드에서 읽기 전용 사용)
4. 결정 내용을 D-181 Decision 표에 장치별로 적는다.

## S2. 구현 (한 브랜치, 한 PR)

1. `deploy/robot/native/rosy-boot-display.py` + `rosy-boot-display.service`
   - CORE 밖에서 돈다. 전용 사용자 `rosy-display`, `DevicePolicy=closed`, 위 장치만 `DeviceAllow`,
     `ProtectSystem=strict`, 로그인 셸 없음, `PYTHONNOUSERSITE=1`로 둔다(D-189 계약).
   - 입력: `/run/rosy-boot/boot-status.json`, `/run/rosy-boot/network.json`, AP 자격 증명 파일.
     AP 자격 증명은 root 소유 0600이므로 읽는 방식을 정한다(root 헬퍼가 화면 문자열만 넘기는 방식 등).
   - 출력: LCD 화면(`emotion.info_screen` 렌더러 확장)과 부저 패턴.
   - 계속 떠 있는 프로세스로 둔다(S0 결과에 따름). 단계가 바뀌면 즉시 다시 그리고, 배터리는 주기적으로 갱신한다.
   - 배터리: `rosy-io`가 활성이면 CORE API 값을 쓰고, 아니면 ADC를 직접 읽는다(D-190 결정 4).
   - `Conflicts=` `emotion` 실행 unit.
2. `rosy-boot-status-ready.service`: `After=rosy-runtime.target`, `WantedBy=multi-user.target`.
   2026-09-24 장치에서 CORE_READY 표시를 t+67 s에서 t+45 s로 앞당긴 것을 저장소로 옮긴다.
3. 이미지: S0에서 확정한 GPIO·SPI 라이브러리와 폰트를 해시 고정 목록에 넣는다(D-189 방식).
   `customize-rootfs.sh`가 표시 unit을 `rosy-display`로 실행해 import와 장치 접근 준비를 probe한다.
4. 가드
   - `test_device_surface_contract.py`: LCD·부저·ADC만 허용으로 바꾸는 변이를 증명한다.
   - `test_native_systemd_contract.py`: 새 unit의 쓰기 집합과 HOME 규칙을 검사한다.
   - 렌더러: 단계별 화면(BOOTING/PROVISIONED/CORE_READY/FAILED/AP)을 골든 이미지로 시험한다.
   - 배터리 출처 선택 로직 시험.
5. 문서: D-190 동등성 표 갱신, 런북 "전원을 넣으면 보이는 것", `deploy/logs.md`.

## S3. 이미지와 실기 검증 (손으로 하는 설치 없음)

새 릴리스를 빌드하고 서명한 뒤 `write-card.ps1 -Detach`로 굽는다. 로봇에서 다음을 기록한다.

| 확인 | 기대 |
|---|---|
| 전원 → LCD 첫 화면 | 공식 OS와 같은 시점 이내(S0에서 잰 값) |
| 부저 | `CORE_READY` 때 공식 패턴 |
| 배터리 | ADC 직접 값과 ±0.05 V |
| 실패 | unit 하나를 일부러 실패시켜 LCD에 `FAILED:<unit>` |
| AP | 현장 Wi-Fi 없이 켜서 120 s 뒤 LCD에 SSID·비밀번호 |
| 재부팅 | 수동 조치 없이 위 결과 반복 |

## S4. 마무리

D-190을 Accepted로 바꾸고 D-181 표에 편입 날짜와 증거를 적는다. 교훈이 있으면 `docs/solutions/`에 남긴다.

---

## 현재 위치 (2026-09-24)

- 006 이미지: 빌드 성공(`CORE_RUNTIME_PROBE_OK`). D-189 수정만 담고 D-190은 담지 않는다.
- 005 카드 장치: 응급 조치 상태. 006으로 다시 구우면 D-190 기록의 응급 조치가 모두 사라진다.
- 다음 사람 행동: S0용 공식 이미지 카드 준비.
