## D-190 부팅 표시는 공식 Pinky Pro와 같게 동작한다 — 증거 먼저, 장치 편입은 한 변경에, 장치에서 즉석 수정하지 않는다

**Status:** Proposed (2026-09-24). D-174 T1(LCD)·T2(부저)를 실행 계획으로 올린다.
D-169(v1 장치 표면)·D-181(장치 편입 조건)·D-161(CORE 비특권)을 그대로 따른다.

**Context:** 공식 Pinky Pro OS는 전원을 넣으면 부저가 울리고 LCD(ST7789)에 Wi-Fi 이름과
비밀번호가 뜬다(`docs/plans/2026-09-21-pinky-pro-os-research.md` §4). Rosy OS는 D-174 T0로
보드 ACT LED, HDMI 콘솔, mDNS만 한다. 2026-09-24 실기에서 확인한 것:

- 재부팅하면 `CORE_READY`까지 23.5 s(커널 4 s + 사용자 공간 19.5 s)가 걸린다.
- 부팅 표시가 CORE 준비보다 약 30 s 늦었다. 30 s 주기 타이머 탓이다. `rosy-runtime.target` 뒤에
  한 번 더 판정하는 unit을 장치에 넣자 PC에서 처음 볼 수 있는 순간(t+45 s)에 `CORE_READY`가 떴다.
- LCD에는 아무것도 보이지 않는다. 공식 LCD 드라이버(`pinky_emotion/pinky_lcd.py`)와 우리 사본
  (`src/apps/emotion/emotion/rosy_lcd.py`)은 sleep/wake 두 메서드 말고는 같다. 제품 이미지에는
  `spidev`·`RPi.GPIO`가 없다(D-169에서 LCD를 벤치 전용으로 뺐기 때문이다).
- 제품 이미지에서 배터리는 CORE-only 모드라 아무도 읽지 않는다. ADC(I2C-1, 0x08, 채널 4,
  레지스터 0xF8, `(d0<<4)+(d1>>4)`, 분압 13/28)를 직접 읽자 8.67 V(`BatteryCurve.default()` 100 %)였다.

같은 날 LCD를 확인하려고 장치에 apt 패키지를 넣고 한 번 그리고 끝나는 스크립트를 돌렸는데 화면은
보이지 않았다. 가설: Pi 5에서 백라이트 PWM(GPIO18)이 프로세스 종료와 함께 멈춘다. 공식 OS는 표시
프로세스가 계속 떠 있다. 이 시도는 원인을 증거 없이 추측했고, 다시 구우면 사라지는 변경을 장치에
남겼다. 앞 단계(D-189)의 응급 조치도 같은 방식이었다. 이 방식으로는 공식 OS와 같은 동작에 닿지 못하고
같은 일을 반복하게 된다.

**Decision:**

1. **기준은 공식 Pinky Pro다.** 부팅 신호(부저, LCD 내용, 표시 시점), 배터리 값, AP 안내가 공식 OS와
   같거나, 다르면 그 이유를 이 ADR의 동등성 표에 적는다. 다름은 결정이지 누락이 아니다.
2. **증거가 먼저다(S0).** 공식 이미지 카드에서 `deploy/robot/capture-vendor-baseline.sh`를 돌리고,
   공식 소스(`pinklab-art/pinky_pro`, `pinky_lcd`)를 읽어 다음을 확정한 뒤에야 구현한다.
   - 부팅 때 LCD를 그리는 주체(서비스·스크립트)와 시점
   - Pi 5에서 쓰는 GPIO 라이브러리와 버전
   - 백라이트 구동 방식
   - 부저 핀과 소리 패턴
   - 폰트
   - 배터리 백분율 계산법
3. **장치 편입은 D-181대로 한 변경에서 한다(S1-S2).** LCD(`spidev0.0` + gpiochip 선 18·25·27),
   부저 GPIO, ADC 읽기를 CORE 밖 표시 전용 unit에만 준다. 이미지 패키지(해시 고정), unit 샌드박스,
   capabilities·프로필 항목, `test_device_surface_contract.py` 변이, D-189식 설치 위치 probe를 같은
   변경에 넣는다.
4. **배터리 값은 한 출처만 버스를 만진다.** `rosy-io`(sensor_adc)가 돌면 표시 unit은 CORE의 배터리 값을
   읽는다. CORE-only 모드에서만 ADC를 직접 읽는다. 두 프로세스가 같은 I2C 장치의 레지스터 포인터를
   번갈아 쓰면 값이 섞이기 때문이다.
5. **LCD 소유자는 하나다.** 얼굴(`emotion`)이 돌면 표시 unit이 비켜 준다(`Conflicts=`).
6. **장치에서 즉석 수정하지 않는다.** 장치에 손으로 넣는 변경은 증거를 얻기 위한 응급 조치일 때만
   허용한다. 넣는 즉시 해당 ADR에 "무엇을, 왜, 어느 이미지에서 사라지는지"를 적는다. 동작은 저장소 →
   이미지 → 서명 → 카드 경로로만 들어간다.

**동등성 표 (2026-09-24 현재):**

| 공식 Pinky Pro 동작 | Rosy OS 현재 | 목표 | 단계 |
|---|---|---|---|
| 부팅 완료 시 부저 | 없음 | 같은 패턴(`CORE_READY`) + 실패 패턴 | S0 핀 확인 → S2 |
| LCD에 AP SSID·비밀번호 | 없음 | AP가 열렸을 때 같은 정보 | S2 |
| LCD 배터리 | 없음 | 배터리 %·전압 | S2 |
| (공식에는 없음) | — | LCD에 이름·IP·부팅 단계·실패 unit | S2 |
| 자체 AP `pinky_XXXX` / 공통 비밀번호 `pinkypro` | 대체 AP, 카드별 무작위 비밀번호(D-176) | 유지. 공통 비밀번호는 쓰지 않는다 | 결정된 차이 |
| SSH `pinky` / 비밀번호 `1` | `rosy` 키 전용(D-174 F3) | 유지 | 결정된 차이 |
| WS2812 lamp(`lamp_bringup.service`) | 벤치 전용(D-169) | 이 ADR 범위 밖 | D-181 |
| 부팅 표시가 CORE 준비 직후 갱신 | 30 s 타이머 지연 | 런타임 뒤 즉시 판정 | S2 |

**응급 조치 기록(장치 `rosy-pinky-e4us`, 카드 005):**

- D-189 수정 4건: drop-in 2개, `/usr/local` pip, 소유권 되돌림.
- 로그인 셸·user site 차단 drop-in.
- `rosy-boot-status-ready.service`.
- apt `python3-spidev` `python3-rpi-lgpio` `fonts-dejavu-core`.

모두 006 이상으로 다시 구우면 사라진다. 006은 D-189 수정을 담았고, 나머지는 D-190 구현 이미지에 들어간다.

**Alternatives:**

- 지금처럼 장치에서 고쳐 가며 맞추기: 빨라 보이지만 다시 구우면 사라지고, 공식 동작과 같은지 판단할
  근거가 남지 않는다.
- LCD를 CORE나 `emotion`에 맡기기: CORE는 비특권이고 인터넷에 노출된다(D-161). `emotion`은 CORE가
  떠야 뜨므로 부팅 실패를 보이지 못한다.
- 공식 OS의 표시 스크립트를 그대로 복사하기: 권한 모델(root, 공통 비밀번호)이 D-161·D-176과
  충돌한다. 동작은 맞추고 권한은 우리 모델을 쓴다.

**Consequences:**

- S0에는 공식 이미지를 구운 여분 카드 한 장과 사람의 손이 필요하다.
- 구현 뒤에는 전원만 넣어도 LCD와 부저로 상태를 알 수 있다.
- 장치 표면이 LCD·부저·ADC 읽기만큼 넓어진다. D-181 가드가 그 범위를 고정한다.
- 앞으로 장치 응급 조치는 ADR 기록 없이는 하지 않는다.

**실행 계획:** [`docs/plans/2026-09-24-vendor-parity-boot-display.md`](../plans/2026-09-24-vendor-parity-boot-display.md)
