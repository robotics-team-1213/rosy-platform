## D-190 부팅 표시는 공식 Pinky Pro와 같게 동작한다 — 증거 먼저, 장치 편입은 한 변경에, 장치에서 즉석 수정하지 않는다

**Status:** Proposed (2026-09-24). D-174 T1(LCD)·T2(부저)를 실행 계획으로 올린다.
D-169(v1 장치 표면)·D-181(장치 편입 조건)·D-161(CORE 비특권)을 그대로 따른다.
**S1·S2 완료(2026-09-24, US-006, 브랜치 `feat/boot-display-lcd`):** 저장소 구현과 host 시험이 끝났다. 아래
"S1·S2 구현 기록"을 본다. S3(새 이미지로 구운 카드의 실기 확인)과 부저 핀 확인이 남았다.
**부저 핀 확인(2026-09-26, `rosy_18`, D-247 슬라이스 2):** Pinky Pro 부저는 BCM 4다. 사람이 귀로 확인했다. BCM 22는
2 kHz PWM에서도 상시 high에서도 조용했다. 허용 목록 {4, 5, 6, 16, 17, 20, 21, 23, 24, 26}을 차례로 울려 찾았다.
`/etc/rosy/boot-display.env`에 `ROSY_BUZZER_ENABLED=true`와 `ROSY_BUZZER_PIN=4`를 쓰고 표시를 다시 띄우자
`CORE_READY` 한 번 울림(2 kHz, duty 10 %)이 들렸다. 그래서 기본 핀을 4로 바꿨다(`board.yaml`, unit, 프로그램).
기본으로 켤지는 아래 절차대로 별도 변경으로 정한다. 지금은 꺼져 있다.

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
4. **배터리 값은 표시 unit이 ADC를 직접 읽는다(S2에서 고침).** 처음 결정은 "`rosy-io`가 돌면 CORE의 값을
   읽고, CORE-only 모드에서만 ADC를 직접 읽는다"였다. 두 프로세스가 같은 I2C 장치의 레지스터 포인터를 번갈아
   쓰면 값이 섞이기 때문이었다. D-192가 그 위험을 버스에서 닫았다: Rosy의 모든 0x08 독자(`rosylib.Battery`,
   `ir_adc_node`, 벤치 `sensor_adc`)는 포인터 쓰기부터 읽기까지 같은 `flock`을 잡는다. 그래서 표시 unit은
   `rosy-io`가 돌든 말든 `rosylib.Battery`로 15 s마다 한 번(6 ms 트랜잭션) 읽는다. 결합이 가장 적은 길이다.
   - CORE API: 표시가 CORE(토큰, 네트워크)에 묶이고, CORE가 실패하면 배터리도 보이지 않는다. 표시는 CORE가
     없을 때 보여야 한다.
   - `battery_publisher`가 쓰는 작은 파일: `rosy-io`에 새 쓰기 경로가 생기고, 표시가 파일 신선도와 모드 전환을
     판정해야 한다.
   - 직접 읽기: 모드 분기가 없고, `battery/voltage`와 같은 공식·같은 곡선이다(S3에서 ±0.05 V 확인).
5. **LCD 소유자는 하나다.** 얼굴(`emotion`)이 돌면 표시 unit이 비켜 준다(`Conflicts=`). S2 확인: 제품
   이미지에서 `emotion`을 띄우는 unit·launch가 없다(D-169 벤치 전용, `control/robot.launch.py`도 따로 띄우라고만
   한다). 그래서 지금은 `Conflicts=`를 두지 않는다. `test_boot_display.py`의 가드가, emotion을 띄우는 unit이
   `Conflicts=rosy-boot-display.service` 없이 생기거나 launch가 emotion을 띄우면 실패한다.
6. **장치에서 즉석 수정하지 않는다.** 장치에 손으로 넣는 변경은 증거를 얻기 위한 응급 조치일 때만
   허용한다. 넣는 즉시 해당 ADR에 "무엇을, 왜, 어느 이미지에서 사라지는지"를 적는다. 동작은 저장소 →
   이미지 → 서명 → 카드 경로로만 들어간다.

**동등성 표 (2026-09-24 현재):**

| 공식 Pinky Pro 동작 | Rosy OS 현재 | 목표 | 단계 |
|---|---|---|---|
| 부팅 완료 시 부저 | S2 구현, 기본 꺼짐(핀 미확인) | 같은 시점(`CORE_READY` 1회) + 실패 3회 | 핀 확인 → S3 |
| LCD에 AP SSID·비밀번호 | S2 구현 | AP가 열렸을 때 같은 정보 | S3 |
| LCD 배터리 | S2 구현 | 배터리 %·전압 | S3 |
| (공식에는 없음) | S2 구현 | LCD에 이름·IP·부팅 단계·실패 unit | S3 |
| 자체 AP `pinky_XXXX` / 공통 비밀번호 `pinkypro` | 대체 AP, 카드별 무작위 비밀번호(D-176) | 유지. 공통 비밀번호는 쓰지 않는다 | 결정된 차이 |
| SSH `pinky` / 비밀번호 `1` | `rosy` 키 전용(D-174 F3) | 유지 | 결정된 차이 |
| WS2812 lamp(`lamp_bringup.service`) | 벤치 전용(D-169) | 이 ADR 범위 밖 | D-181 |
| 부팅 표시가 CORE 준비 직후 갱신 | D-192 US-003(`rosy-boot-status-ready`) | 런타임 뒤 즉시 판정 | S3 |

**응급 조치 기록(장치 `rosy-pinky-e4us`, 카드 005):**

- D-189 수정 4건: drop-in 2개, `/usr/local` pip, 소유권 되돌림.
- 로그인 셸·user site 차단 drop-in.
- `rosy-boot-status-ready.service`.
- apt `python3-spidev` `python3-rpi-lgpio` `fonts-dejavu-core`.

모두 006 이상으로 다시 구우면 사라진다. 006은 D-189 수정을 담았고, 나머지는 D-190 구현 이미지에 들어간다.

**S1·S2 구현 기록 (2026-09-24, US-006):**

- **unit.** `deploy/robot/native/rosy-boot-display.service` → `/opt/rosy/native-runtime/rosy-boot-display.py`.
  - 전용 사용자 `rosy-display`(uid·gid 962, `/usr/sbin/nologin`, 홈 없음), `SupplementaryGroups=dialout spi gpio`.
  - `DevicePolicy=closed`, `DeviceAllow`는 `/dev/spidev0.0`·`/dev/gpiochip4`·`/dev/i2c-1`뿐이다.
  - `ProtectSystem=strict`, `ProtectHome=true`, `PrivateNetwork=true`, `RestrictAddressFamilies=AF_UNIX`, 빈
    `CapabilityBoundingSet`, `NoNewPrivileges`, 셸 없이 `python3 -B`로 직접 실행한다.
  - `HOME`·`WorkingDirectory`·`LG_WD`는 `StateDirectory=rosy/display`이다(lgpio 알림 파일 자리). `PYTHONNOUSERSITE=1`.
    `emotion`·`rosylib`는 `PYTHONPATH`로 현재 릴리스에서 온다.
  - `Restart=on-failure`, 5회/300 s 제한. `WantedBy=multi-user.target`, 순서는 `local-fs.target`·`systemd-udevd`뿐이다.
    CORE에도 `rosy-boot-status`에도 순서를 걸지 않고 1 s마다 파일을 읽는다. 그래서 BOOTING·PROVISIONED·FAILED도 보인다.
- **상주와 갱신.** 프로세스가 살아 있어 백라이트 PWM이 계속 돈다(S0). 1 s마다 `boot-status.json`·`network.json`·
  AP 파일을 읽고, 그릴 내용이 바뀐 때만 다시 그린다. 배터리는 15 s마다 읽는다.
- **장치가 없을 때(보안 리뷰 L1·L2 반영).** 두 경우를 나눈다.
  - `/dev/spidev0.0` 자체가 없으면 그 보드에는 SPI 패널이 없다(SPI를 켜지 않은 보드, 다른 모델). 고장이 아니라 고정된
    구성이므로 한 번 기록하고, 부저도 꺼져 있으면 0으로 끝난다. 재시작도 실패 표시도 없다.
  - 노드는 있는데 구동하지 못하면 고장이다. 매 시도마다 먼저 `/dev/gpiochip4` label을 읽고, 읽지 못하면(udev 경합,
    ioctl 오류) 패널을 건드리지 않고 다시 시도한다. label이 `pinctrl-rp1`이 아니면 바로 포기한다. 5 s 간격 6회 안에
    열지 못하거나, 라이브러리 import가 실패하면 1로 끝나 systemd에 `failed`로 보인다. `StartLimitBurst=5`/300 s가
    재시작을 막는다(한 회차가 약 30 s라 다섯 번이면 한도에 걸린다). 어떤 경우에도 선을 보지 않고 구동하지 않는다.
  - 배터리 버스가 없으면 `--`로 그리고 조용히 다시 시도한다.
- **gpiochip4.** Pi 5의 40핀 헤더 GPIO는 RP1(label `pinctrl-rp1`)이다. Ubuntu 24.04 raspi 커널에서는 `gpiochip4`로 알려져
  있고(`gpiochip0`은 SoC 쪽), Raspberry Pi 커널은 6.6.45 무렵부터 RP1을 `gpiochip0`으로 옮겼다(확실도: 유력, 장치 미확인).
  그래서 프로그램은 `GPIO_GET_CHIPINFO` ioctl로 `/dev/gpiochip4`의 label을 읽고 `pinctrl-rp1`이 아니면 LCD를 구동하지
  않고 한 번 기록한다. unit은 `RPI_LGPIO_CHIP=4`를 준다. noble의 `python3-rpi-lgpio` 0.5-0ubuntu1은 `setmode()`에서
  `os.environ.get('RPI_LGPIO_CHIP')`을 읽고, 없으면 BCM2712에서 4를 쓴다(2026-09-24 패키지 소스 확인). 그래서 shim은 없다.
  이미지 probe가 설치된 `RPi/GPIO/__init__.py`에 그 읽기가 있는지 확인한다. 번호가 다르면 `DeviceAllow`·udev 규칙·
  `board.yaml`·시험을 한 변경에서 바꾼다.
- **AP 문자열.** `ap-credentials.json`은 root 0600이고 표시는 비특권이다. 이미 그 파일을 읽는 root 프로세스
  `rosy-network.py`가 AP를 연 직후 두 줄(SSID, 비밀번호)만 `/run/rosy-boot/ap-display.txt`에 쓴다. 소유
  root:rosy-display, 0640이고, 빈 임시 파일에 그룹·모드를 먼저 건 뒤 내용을 쓴다. AP가 닫히거나 열기에 실패하거나 제어기가
  시작하면 지운다. `rosy-display` 그룹이 없으면 쓰지 않는다. 표시는 `network.json` mode가 `ap`일 때만 그 파일을 쓴다.
  어느 쪽도 비밀번호를 stdout·journal에 쓰지 않는다(폴링 예외도 예외 종류만 기록). 새 root 헬퍼 unit을 만들지 않은 이유:
  AP를 여는 순간과 같은 프로세스·같은 시점이라 30 s 타이머를 기다리지 않고, 비밀을 읽는 root 코드가 하나로 남는다.
- **부저.** 기본 BCM 22, **기본 꺼짐.** `ROSY_BUZZER_ENABLED`는 `true`/`false`만 받고(그 밖은 꺼짐),
  `ROSY_BUZZER_PIN`은 허용 목록 {4, 5, 6, 16, 17, 20, 21, 22, 23, 24, 26}만 받는다(보안 리뷰 M1). 나머지 헤더 선은
  주인이 있다: I2C0 0/1, I2C1(ADC) 2/3, SPI0 7-11, UART4 모터 12/13, UART0 LiDAR 14/15, LCD 18·25·27, 벤치 lamp 19.
  목록과 주인은 `board.yaml` `boot_display`에 있고 시험이 둘이 겹치지 않고 0-27을 모두 덮는지 본다. 켜는 방법은 사람이 장치에서 소리를 확인한 뒤
  `/etc/rosy/boot-display.env`에 `ROSY_BUZZER_ENABLED=true`를 쓰는 것이다(unit의 기본값보다 우선한다). 패턴(Rosy가
  정함): `CORE_READY`에 한 번, `FAILED`에 세 번, 80 ms 켬 / 120 ms 쉼, 2 kHz, duty 10 %. 단계가 바뀔 때만 울린다.
- **화면.** `emotion.info_screen.render_boot`(D-82 팔레트): 이름, 릴리스, 단계(`FAILED`는 빨강 + 실패 unit), `IP:포트`,
  배터리 %·전압, AP일 때 `Wi-Fi <SSID>`·`PW <비밀번호>`. 정상은 잉크색이고 빨강은 `FAILED`와 배터리 임계뿐이다.
- **이미지.** customizer가 apt `python3-spidev`·`python3-rpi-lgpio`·`python3-numpy`·`python3-pil`·`fonts-dejavu-core`를
  잠근 Ubuntu suite에서 깐다(다른 apt 패키지와 같은 방식, 버전은 `deb-packages.txt`). `rosy-display` 사용자와 `spi`·`gpio`·
  `i2c` 그룹, `99-rosy-display.rules`(spidev0.0 → spi, gpiochip4 → gpio, 0660), unit enable을 넣는다. chroot에서
  `probe-display-runtime.py`를 unit처럼(`setpriv` rosy-display, `env -i`, 그 HOME, `PYTHONNOUSERSITE=1`, 릴리스
  `PYTHONPATH`) 돌려 `spidev`·`lgpio`·`numpy`·`PIL`(apt), `RPi.GPIO`(rpi-lgpio), `rosylib`·`emotion.info_screen`(릴리스)
  import, 네 단계 카드 렌더, 폰트, unit 샌드박스·enable을 확인한다. Pi가 아닌 빌더에서 `RPi.GPIO` import 실패는
  rpi-lgpio의 거부(`RuntimeError`, 메시지에 "Raspberry Pi")이고 `/proc/device-tree/model`에 Pi가 없을 때만 허용한다.
  마운트 검사기는 unit enable, udev 규칙, dpkg 설치 상태,
  `dtparam=spi=on`을 본다.
- **D-181 편입.** D-181 편입 기록 표, `board.yaml` `boot_display`(CORE capability가 아니므로 `capabilities.*.yaml`에는
  광고하지 않는다, D-32), `test_device_surface_contract.py` 변이(세 노드는 표시 unit에만, 다른 unit에 넣으면 적색).
- **시험.** 렌더러 19(단계별 행·색, FAILED, AP, 배터리 없음, IP 없음, 긴 문자열), 루프·부저·배터리·LCD 열기·AP
  핸드오프·unit·이미지 35(`test/test_boot_display.py`), 장치 표면 13(변이 포함), 샌드박스 계약에 새 unit의
  쓰기·읽기 선언. 0640과 그룹 확인은 WSL(POSIX)에서 돌렸다.

**남은 위험 (보안 리뷰 M2, 2026-09-24):** 장치 허용은 노드 단위다. `DeviceAllow=/dev/gpiochip4`는 RP1의 54개 선
전부를 주고, `/dev/i2c-1`은 버스의 모든 주소를 읽고 쓰게 한다. 프로그램은 LCD 선·허용 목록의 부저 선·0x08만 쓰지만,
`rosy-display`가 탈취되면 모터 UART 핀(12/13)을 GPIO로 바꿔 모터 버스를 끊거나 I2C 센서를 흔들 수 있다. D-192의
`flock`은 권고 잠금이라 막지 못한다. 완화: 입력은 root가 쓰는 파일(`/run/rosy-boot`)뿐이고 `PrivateNetwork=true`,
`AF_UNIX`만, 권한 없음이다. 원격에서 닿는 입구가 없다. 배터리 직접 읽기는 CORE가 죽었을 때도 보여야 하므로 유지한다.

**열린 항목:** 커널이 패널을 소유하게 한다. `dtoverlay=mipi-dbi-spi`(또는 fbtft `st7789v`)에 reset·dc·backlight GPIO를
주면 unit에는 framebuffer/DRM 노드 하나만 남고 `gpiochip4` 허용이 사라진다. 배터리는 root나 `rosy-io`가 쓰는 파일에서
읽어 `i2c-1` 허용도 뺀다. 둘 다 이미지·실기 확인이 필요한 별도 변경이다.

**S3 실기 확인 (새 이미지 카드, 사람 입회, 장치에 손으로 설치하지 않는다):**

1. `readlink -f /sys/bus/gpio/devices/gpiochip4`가 RP1 노드(`…/1f000d0000.gpio/…`)를 가리키고,
   `sudo python3 -c 'import lgpio; h=lgpio.gpiochip_open(4); print(lgpio.gpio_get_chip_info(h)); lgpio.gpiochip_close(h)'`가
   label `pinctrl-rp1`을 보이는지 본다. 아니면 이 ADR의 gpiochip4 항목대로 한 변경에서 고친다.
   - 2026-09-24 읽기 전용 확인(release 005, rosy-pinky-e4us): `gpiochip4` → `axi/1000120000.pcie/1f000d0000.gpio/gpiochip4`,
     sysfs `gpiochip569` label `pinctrl-rp1`, ngpio 54. 나머지 gpiochip0-3은 `gpio-brcmstb`. **확인됨** (새 이미지에서 다시 본다).
2. `ls -l /dev/spidev0.0 /dev/gpiochip4 /dev/i2c-1`: `root spi 0660`, `root gpio 0660`, `root dialout 0660`.
3. `systemctl is-enabled rosy-boot-display` = enabled, `systemctl show -p User,DevicePolicy rosy-boot-display`,
   `journalctl -b -u rosy-boot-display`에 경고가 없거나 한 번씩만 있는지. customizer 로그에 `DISPLAY_PROBE_OK`.
4. 전원 → LCD 첫 화면(BOOTING)까지의 시간을 초시계로 재고, 공식 OS(S0) 값과 비교한다. PROVISIONED → READY 전환이
   `boot-status.json` 갱신 1 s 안에 보이는지.
5. 백라이트가 계속 켜져 있는지(10분). `systemctl restart rosy-boot-display` 뒤에도 다시 그리는지.
6. 배터리: 화면 전압과 `sudo -u rosy-io … rosylib.Battery().get_voltage()`(D-192 확인 5)의 차이 ±0.05 V. `rosy-io`를
   시작한 상태에서도 같은지(두 독자 공존).
7. 실패: 모터를 건드리지 않는 unit 하나를 실패시킨다. `sudo mv /etc/rosy/runtime.env /etc/rosy/runtime.env.s3`,
   `sudo systemctl restart rosy-core`(EnvironmentFile이 없어 시작 한도까지 실패한다). LCD에 `FAILED`와 `rosy-core`가
   빨갛게 뜨는지 본다. 되돌리기: `sudo mv /etc/rosy/runtime.env.s3 /etc/rosy/runtime.env`,
   `sudo systemctl reset-failed rosy-core && sudo systemctl start rosy-core`. 이 조작은 증거 수집용 응급 조치로 기록한다.
8. AP: 현장 Wi-Fi 없이 켜서 120 s 뒤(최대 130 s) LCD에 `Wi-Fi rosy-pinky-xxxx`와 `PW …`가 보이는지, 그 값이
   운영 PC DPAPI 저장소 값과 같은지. `journalctl -b -u rosy-network -u rosy-boot-display`에 비밀번호가 없는지
   (`journalctl … | grep -c <비밀번호>` = 0). `ls -l /run/rosy-boot/ap-display.txt` = `root rosy-display 0640`.
   업링크가 돌아오면 파일이 사라지고 AP 줄이 없어지는지.
9. 부저: 아래 "부저 핀 확인"을 한 뒤에만 `/etc/rosy/boot-display.env`에 켠다. 재부팅해 `CORE_READY`에 한 번 울리는지,
   너무 크지 않은지.
10. 재부팅 두 번: 수동 조치 없이 1-8이 반복되는지.

**부저 핀 확인 (사람 입회, D-190 결정 6의 증거 수집):** 장치에서 `rosy-boot-display`를 멈추고
(`sudo systemctl stop rosy-boot-display`), `sudo python3 -c 'import RPi.GPIO as G, time; G.setmode(G.BCM);
G.setup(22, G.OUT); p=G.PWM(22, 2000); p.start(10); time.sleep(0.2); p.stop(); G.cleanup()'`로 짧은 톤을 낸다.
들렸으면 아래 표에 적고, 기본값을 켤지는 별도 변경(이 ADR 갱신 + 이미지)으로 정한다. 장치에 남기는 설정은
`/etc/rosy/boot-display.env` 한 줄이며, 넣으면 즉시 "응급 조치 기록"에 적는다.

| 날짜 | 이미지 | 장치 | BCM | 들렸는가 | 확인자 |
|---|---|---|---|---|---|
| (미확인) | | | 22 | | |
| 2026-09-26 | release 012 | `rosy_18` (`rosy-pinky-e4us`) | 22 | 아니오(PWM 2 kHz·상시 high 모두) | 사람 입회 |
| 2026-09-26 | release 012 | `rosy_18` (`rosy-pinky-e4us`) | 4 | 예(500 Hz 50 %, 부팅 표시 2 kHz 10 %) | 사람 입회 |

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
