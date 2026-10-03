## D-433 로봇 몸의 화면·소리·빛은 ROS 밖 한 프로세스 `rosy-face`가 평생 소유하고, 무엇을 그릴지는 상황표 함수 하나가 정한다

**Status:** Proposed (2026-10-03, 사용자 결정 "한 프로세스가 LCD·부저·램프를 계속 소유" 반영 초안). Q1–Q5는 2026-10-03 사용자가 모두 권고안으로 답했다(아래 "사용자 결정"). 독립 리뷰 전까지 Proposed로 둔다.

잇는 결정: [D-190](D-190-vendor-parity-boot-display.md) · [D-260](D-260-robot-shows-its-state-by-sound-light-screen-and-summary.md) · [D-380](D-380-lamp-mode-patterns-from-core-status-inputs.md) · [D-381](D-381-blocked-navigation-and-emergency-entry-sound.md) · [D-385](D-385-rosy-expresses-itself-mode-faces-and-breathing-boot.md) · [D-394](D-394-display-cards-are-a-contract-devices-are-profiles.md) · [D-388](D-388-payload-push-syncs-image-layer.md) · [D-412](D-412-robots-self-update-from-signed-github-releases-when-idle.md) · [D-185](D-185-runtime-cpu-budget-order.md) · [D-427](D-427-platform-three-parts-middleware-operations-learning.md)

### Context

2026-10-03 실기(release 026, 두 대)에서 확인했다. D-385의 모드 얼굴·대기 심심함과 D-394의 주행 카드(CORE 브리지 `display/info`, `kind: "drive"`, `drive_due` 20 s)가 Pinky Pro LCD에 한 번도 나오지 않는다.

- `emotion` 패키지는 페이로드에 있다(`install/lib/emotion`). 그러나 네이티브 런타임에서 `emotion_server`를 띄우는 것이 없다. systemd unit도 없고 bringup·camera launch에도 없다. `robot.launch.py`에는 주석뿐이다(D-169 벤치 전용, D-190 결정 5).
- LCD는 `deploy/robot/pinky_pro/native/rosy-boot-display.py`가 쥔다. 비특권 사용자 `rosy-display`로 돌며 `info_screen.render_boot`만 그린다. ST7789 백라이트는 GPIO18 소프트웨어 PWM이라 프로세스가 사는 동안만 켜진다(D-190 S0: 한 번 그리고 끝나면 화면이 어둡다). 같은 프로세스가 부저(BCM 4)와 WS2812 램프(D-380 모드 무늬)도 몰고, CORE_READY에서 일회용 로그인 코드를 보인다(D-193).
- 그래서 얼굴·주행 카드 코드는 계약 시험을 통과했지만(D-385·D-394 Validation) 실제 화면 경로에는 연결된 적이 없다.

먼저 검토한 안은 "CORE_READY 뒤에 LCD를 `emotion_server`에 넘기고, 실패하면 부팅 표시가 되찾는다"였다. 사용자는 이를 버리고 한 프로세스 소유로 정했다(아래 Alternatives).

코드 조사에서 함께 확인한 사실:

1. **핸드오버가 느리다.** CORE는 `/run/rosy/status-inputs.json`을 10 s마다 쓰고(`core_api_web/api/v1/host.py` `STATUS_INPUTS_PERIOD_S`), root `rosy-boot-status`가 30 s 타이머로 검증해 `boot-status.json`에 옮긴다(신선도 60 s). 램프 모드 무늬에는 충분하지만, 모드가 바뀐 순간 얼굴을 바꾸거나 5 s짜리 주행 카드를 띄우기에는 최대 40 s 늦다.
2. **이미 실려 있는 입력.** status-inputs schema 2(D-412)에는 `robot_mode`·`nav_state`·`swarm_role`·`estop`·`docking_state`·`battery_charging`·`line_follow_mode`/`state`·`activity_kind`(CALIBRATING)·속도가 있다. 없는 것은 얼굴 이름(대기 시간을 아는 CORE의 `emotion_map.emotion_for`), 목표 좌표, 웨이크 카드(PWR-003 근접·배터리), 절전 모드(`power/mode` active/idle/standby)다.
3. **`/run/rosy`는 읽을 수 있다.** `rosy-core.service`의 `RuntimeDirectory=rosy`는 기본 0755이고 status-inputs는 0644로 쓴다. 비특권 표시 사용자가 root 중계 없이 직접 읽을 수 있다. CORE는 root보다 덜 믿으므로 읽기는 `rosy-boot-status._read_core_file`와 같은 규칙(링크·FIFO 거부, 16 KiB 상한, 정규 파일, schema·`written_at` 확인)을 따라야 한다.
4. **GIF가 크다.** 8종 770프레임, 1000×750, 합계 32 MB. `emotion_server`는 시작할 때 `load_frame_skip=2`로 모두 RGB로 풀어(약 385프레임 × 2.25 MB ≈ 860 MB) 두고, `rosy_lcd.img_show`가 프레임마다 LANCZOS로 320×240에 줄이고 RGB565로 바꾼다(10 Hz). Pi 5에서 이 경로를 그대로 쓰면 메모리와 CPU 모두 D-185 예산을 깬다.
5. **페이로드는 계정을 못 만든다.** `sync-image-layer.py`(D-388)는 `/etc/passwd`·`/etc/group`을 금지 목록에 둔다. 이미지가 아닌 페이로드로 026에서 올라오는 로봇에는 새 사용자 `rosy-face`를 만들 경로가 없다. 또 `rosy-display` 그룹 이름은 udev 규칙(`99-rosy-display.rules`·`99-rosy-lamp.rules`), `rosy-network.py`의 `ap-display.txt`, `rosy-login-code.py`의 `login-display.txt`, `rosy-hw-test.py`의 넘김 판정에 박혀 있다.
6. **롤백은 옛 코드가 돌린다.** 026의 `sync-image-layer.py`는 나중 릴리스가 추가한 unit을 `disable --now`로 지우고 바꾼 파일을 백업에서 되살리지만, 나중 릴리스가 끈 unit을 다시 켜는 법은 모른다. 동기화는 unit을 재시작하지 않고(`restart_units`는 활성 unit만), 자동 업데이트는 그 목록만 재시작한다. 롤백 뒤 비활성인 옛 표시 unit은 다음 부팅까지 아무도 시작하지 않는다.

### Decision

#### 1. 한 프로세스, 평생 소유

- 이름을 역할대로 바꾼다. unit `rosy-face.service`, 프로그램 `deploy/robot/pinky_pro/native/rosy-face.py`(이미지에서는 `/opt/rosy/native-runtime/rosy-face.py`). `rosy-boot-display`는 은퇴한다(결정 6).
- `rosy-face`는 전원이 들어온 뒤부터 꺼질 때까지 **LCD 패널·백라이트 PWM·부저·램프 넷을 모두** 쥔다. 다른 프로세스는 이 넷을 몰지 않는다. 네이티브에서는 `emotion_server`를 띄우지 않는다.
- `rosy-face`는 ROS를 쓰지 않는다. 입력은 파일뿐이다(결정 3). 그래서 CORE가 없을 때, 즉 화면이 가장 필요할 때도 동작한다.
- 부저·램프의 동작(D-260 결정 2·3, D-380, D-381, D-247 시험 넘김)은 그대로 옮긴다. 소리·빛은 바꾸지 않는다.
- 렌더러는 릴리스의 것을 쓴다. 지금 부팅 표시가 `emotion.info_screen`을 import하는 방식 그대로, `emotion.info_screen.render_boot`·`render_card`(웨이크·주행 카드)와 `emotion`의 GIF 자산을 `PYTHONPATH`(현재 릴리스 site-packages)와 share 경로에서 읽는다. `emotion_server`는 시뮬레이션·벤치의 ROS 어댑터로 남고 같은 렌더러와 같은 상황표를 쓴다(결정 2).
- `emotion` 패키지와 `src/hmi/face`의 이름·위치는 바꾸지 않는다(D-427 이동 동결). 패키지 이름 정리는 후속 과제로 기록한다.

#### 2. 상황표는 순수 함수 하나다

`core_common`에 ROS·pydantic 없는 표준 라이브러리 모듈 하나를 둔다(`robot_state` 옆, 가칭 `core_common.face_screen`). 함수 `screen_for(inputs, now)`가 지금 LCD에 무엇을 그릴지 하나의 답을 낸다. `rosy-face`와 `emotion_server`가 같은 함수를 부르므로 둘은 어긋날 수 없다. 부저·램프는 지금처럼 `robot_state.evaluate`·`lamp_pattern`이 정한다. 상황표는 그 결과(`robot_state`)를 입력으로 받아 같은 말을 화면에 옮긴다.

입력(모두 이미 검증된 값, 없으면 None):

- `stage`·`failed_unit`(boot-status), `robot_state` 결과(D-260), `network.mode`와 AP 표시 여부(`ap-display.txt`)
- 로그인 코드 상태(`login-display.txt`: 코드 있음 / BURNED / 없음)
- CORE 핸드오버(결정 3)와 그 신선도
- 업데이트·활성화 진행(결정 5), D-247 시험 요청, 종료 신호(SIGTERM)

출력: `kind`(아래 표의 화면 종류), `face`(GIF 이름 또는 None), `overlay`(주행·웨이크 카드 또는 None), `strip`(얼굴 아래 띠 문구 또는 None), `backlight`(%), `awake`(패널 sleep 여부).

**상황 → 화면 표** (위가 이긴다. "얼굴 대비"는 얼굴이 보이는가):

| # | 상황 (판정 입력) | 화면 (`kind`) | 그리는 것 | 얼굴 대비 | 정하는 곳 |
|---|---|---|---|---|---|
| 1 | 종료·재부팅 (SIGTERM, `systemctl is-system-running`=stopping) | `shutdown` | "Shutting down" 카드 한 장. 프로세스가 끝나면 백라이트도 꺼진다 | 얼굴 없음 | rosy-face 신호 처리 |
| 2 | 부팅 실패·unit 실패 (`stage` FAILED, `robot_state`=failed) | `status` (실패) | 부팅 카드의 빨강 `FAILED`·실패 unit·할 일 줄(D-190·D-260) | 얼굴 없음 | boot-status → 상황표 |
| 3 | 페이로드 업데이트·활성화 진행 (D-412 `applying`, push 활성화) | `update` | "Updating to <release>" 카드, 현재 릴리스, 숨쉼(D-385 문법) | 얼굴 없음 | 결정 5 파일 → 상황표 |
| 4 | 비상정지·EMERGENCY 래치 (`estop` 또는 `robot_mode`=EMERGENCY, 핸드오버 신선) | `stopped` | 전체 빨강 "STOPPED" 카드: 원인 한 줄, 해제 방법 한 줄(Q1) | 얼굴 없음 | 핸드오버 → 상황표 |
| 5 | AP 대체 모드 (`network.mode`=ap) | `status` (AP) | 부팅 카드 + SSID·PW·Wi-Fi QR(D-190·D-272). 로그인 코드 줄도 같은 카드에 | 얼굴 없음 | network.json·ap-display → 상황표 |
| 6 | 부팅 중 (BOOTING·PROVISIONED·SETUP) | `status` (부팅) | 부팅 카드, 단계 제목 숨쉼(D-385 결정 3) | 얼굴 없음 | boot-status → 상황표 |
| 7 | CORE 정지·충돌·응답 없음 (`stage` CORE_READY인데 핸드오버 없음·오래됨·형식 위반) | `status` (CORE 없음) | 부팅 카드 + 상태 줄 "CORE not responding"(LCD 영어) | 얼굴 없음, 자동 복귀 | 핸드오버 신선도 → 상황표 |
| 8 | CORE_READY, 로그인 코드가 아직 안 쓰임 | `status` (로그인) | 부팅 카드 전체(이름·IP·코드·역할)를 코드가 쓰이거나 BURNED될 때까지(Q2) | 얼굴 없음 | login-display → 상황표 |
| 9 | 주의 (저배터리, 제품 장치 응답 없음, 핸드오버가 넘기는 열화 사유 — 예 라인 추종 NOMINAL 상실) | 아래 줄의 화면 + 띠 | 얼굴(또는 그 순간의 화면) 아래 주황 띠, D-260 할 일 문구(Q3) | 얼굴 유지 | robot_state + 핸드오버 → 상황표 |
| 10 | 하드웨어 시험 (D-247 부저·램프 넘김 요청 처리 중) | 현재 화면 유지 + 띠 | 띠 "Testing buzzer"/"Testing lamp"(최대 `LAMP_TEST_S`) | 얼굴 유지 | 시험 요청 → 상황표 |
| 11 | 캘리브레이션 (`activity_kind`=CALIBRATING) | `face` + 띠 | `interest` 얼굴 + 띠 "CALIBRATING - keep clear" | 얼굴 유지 | 핸드오버 → 상황표 |
| 12 | 웨이크 카드 (PWR-003 근접·배터리 웨이크, 핸드오버 `wake` 블록) | `face` + 카드 | `render_card`(kind 없음) `hold_s` 동안, 끝나면 얼굴 | 카드가 잠시 이김 | CORE가 내용, 상황표가 시간 |
| 13 | 도킹·충전 (`robot_mode`=DOCKING / IDLE이고 `battery_charging`) | `face` (+ 주행 카드) | DOCKING: `fun` + 주행 카드(도크 상태 `docking_state`) 20 s마다 5 s. 충전 중 대기: `basic` + 띠 "Charging 63%" | 얼굴 주인 | 핸드오버 → 상황표 |
| 14 | 내비게이션 (`robot_mode`=NAVIGATION) | `face` + 주행 카드 | `happy`, 막히면(BLOCKED·FAILED) `bored`(D-385). 주행 카드 20 s마다 5 s(D-394) | 얼굴 주인 | CORE가 얼굴 이름, 상황표가 카드 주기 |
| 15 | 라인 추종·차선 주행 (`line_follow_mode` 활성) | `face` + 주행 카드 | 모드의 얼굴. 주행 카드에 라인 추종 상태 한 줄 | 얼굴 주인 | 핸드오버 → 상황표 |
| 16 | 수동 조종 (`robot_mode`=MANUAL) | `face` + 주행 카드 | `interest` + 주행 카드 20 s마다 5 s | 얼굴 주인 | 핸드오버 → 상황표 |
| 17 | 대기 준비 (`robot_mode`=IDLE) | `face` | `basic`, 5분 뒤 `bored`(`emotion_map.IDLE_BORED_AFTER_S`). 주행 카드 없음 | 얼굴 주인 | CORE가 얼굴 이름 |
| 18 | 절전 (`power_mode`=standby) | `sleep` | 패널 sleep, 백라이트 0(D-385 결정 4). 위 1–9가 생기면 깨운다 | — | 핸드오버 → 상황표 |

규칙:

- **1–9는 "상태 카드" 줄**이다. 얼굴보다 위이고, 사람이 읽어야 할 사실이 있다. 10–17은 얼굴이 주인이고 카드·띠는 잠시 얹힌다.
- **신선하지 않은 핸드오버는 없음이다.** 4·9(핸드오버 부분)·11–18은 핸드오버가 신선할 때만 성립한다. 끊기면 표가 자동으로 7(또는 2·6)로 떨어진다. 죽은 CORE의 과거 모드를 얼굴이 배회하지 않는다(D-380 결정 1과 같은 문법).
- **모르는 값은 추측하지 않는다.** 모르는 얼굴 이름은 모드의 기본 얼굴, 모르는 모드는 무시(D-385 결정 1의 None 규칙).
- **주행 카드 주기는 상황표가 정한다.** D-394의 `drive_due`·`DRIVE_EVERY_S`·`DRIVE_HOLD_S`를 `core/bridge/display.py`에서 이 모듈로 옮기고, CORE 브리지는 그것을 import한다(시뮬레이션 `display/info` 경로도 같은 함수). CORE는 카드 **내용**만 넘긴다.
- 화면 글은 지금처럼 ASCII 영어다(카드 글꼴에 한글이 없다, D-260).

#### 3. CORE는 기존 핸드오버를 넓힌다 — 별도 빠른 파일 하나

- CORE는 같은 모듈(`core_api_web/api/v1/host.py`, status-inputs를 쓰는 곳)에서 **`/run/rosy/face-inputs.json`**을 하나 더 쓴다. 0644, 원자적 교체, schema 1.
- **주기는 1 s, 그리고 바뀌면 즉시**(상태 틱 5 Hz 안에서 내용이 바뀐 틱에). status-inputs의 10 s를 줄이지 않는 이유: 그 파일은 `host_hardware` 전체를 다시 계산하고 자동 업데이트의 "10 s 간격 두 표본" 판정이 그 주기를 전제한다.
- 내용(전부 형식이 정해진 값이거나 null, 16 KiB 상한):
  - `written_at`, `robot_mode`, `nav_state`, `estop`, `activity_kind`, `docking_state`, `battery_charging`, `line_follow_mode`/`state`
  - `face`: CORE `emotion_map.emotion_for(mode, nav_state, idle_seconds)`의 결과(GIF 어휘 8개 중 하나)
  - `drive`: `display.drive_payload`의 본문(`kind: "drive"` 제외, 같은 반올림 계약, 목표 좌표 포함)
  - `wake`: 웨이크 카드 본문과 `hold_s`(창이 열려 있을 때만)
  - `power_mode`: `active`/`idle`/`standby`
  - `caution`: CORE만 아는 열화 사유 코드 목록(예 `line_nominal_lost`), 어휘는 `robot_state`에 고정
- **`rosy-face`가 직접 읽는다.** root 중계(30 s)를 거치지 않는다. 읽기는 `_read_core_file` 규칙을 공유 함수로 옮겨 쓴다: `O_NOFOLLOW`, 정규 파일, 소유자 uid가 `rosy-core`, 16 KiB, schema 확인, `written_at`이 **3 s 안**(1 s 주기의 세 배). 하나라도 어기면 핸드오버 전체가 없음이다(얼굴 이름만 틀리면 그 값만 None, D-380 결정 6과 같은 부분 규칙).
- `boot-status.json` 경로(상태·램프·부저)는 바꾸지 않는다.

#### 4. unit

| 항목 | 값 | 이유 |
|---|---|---|
| 사용자 | `rosy-display` 그대로(Q4) | Context 5: 페이로드로 계정을 만들 수 없고 그룹 이름이 다섯 곳에 박혀 있다 |
| 그룹 | `SupplementaryGroups=dialout spi gpio` | 지금과 같다(i2c-1, spidev0.0, gpiochip4) |
| 장치 | `DevicePolicy=closed`, `DeviceAllow` spidev0.0·gpiochip4·i2c-1·ws281x_pwm만 | D-190·D-260과 같다. 늘리지 않는다 |
| ROS 환경 | 없음. `PYTHONPATH`는 현재 릴리스 site-packages, GIF는 `/opt/rosy/current/install/share/emotion/emotion` | ROS 없이 동작한다. namespace(예 `/rosy_60`)도 필요 없다 |
| 순서 | `After=local-fs.target systemd-udevd.service`. CORE·`rosy-runtime.target`에는 걸지 않는다 | 부팅·실패를 보여야 한다(D-190) |
| 재시작 | `Restart=on-failure`, `RestartSec=5`, 5회/300 s | 지금과 같다. 패널이 없는 보드는 0으로 끝난다 |
| 이주 | `Conflicts=` 없음. 교대는 동기화가 명시적으로 `stop` → `enable --now` 한다(결정 6) | `Conflicts=`는 양방향이라, 은퇴 unit을 시작하는 명령 하나가 조건 실패와 상관없이 rosy-face를 멈출 수 있다 |
| 샌드박스 | 지금 unit 그대로(`PrivateNetwork`, `AF_UNIX`, 빈 capability, `ProtectSystem=strict` …) | 입력이 파일뿐이다 |
| 우선순위 | `Nice=5` | 지금과 같다 |

- **선을 보지 않고 몰지 않는다.** `chip_label` 확인(`pinctrl-rp1`), 6회 재시도, 패널 없음 0 / 구동 실패 1 규칙(D-190 보안 리뷰 L1·L2)을 그대로 옮긴다.
- **CPU·메모리 예산(D-185).** GIF를 매 프레임 줄이지 않는다. 얼굴 하나를 처음 쓸 때 320×240 RGB565 바이트로 한 번 변환해 둔다(얼굴당 최대 80프레임 × 150 KB ≈ 12 MB, 8종 모두 ≈ 60 MB). 재생은 SPI 쓰기뿐이다. 변환은 CORE_READY 뒤, 첫 사용 때만 한다(부팅과 경쟁하지 않는다). 재생은 10 fps, `idle` 절전에서는 5 fps, standby에서는 0이다. 목표는 평균 한 코어의 10 % 이하, RSS 120 MB 이하이고, 실기 측정 전에는 `CPUQuota`·`MemoryMax`를 걸지 않는다(초과 시 재시작 고리가 화면을 어둡게 만든다). 측정값이 목표를 넘으면 빌드 때 미리 변환한 자산을 싣는다.

#### 5. 업데이트·종료 화면의 입력

- D-412 업데이터(root)가 `applying`에 들어갈 때 `/run/rosy-boot/update-display.txt`(root:rosy-display 0640, `ap-display.txt`와 같은 방식)에 단계와 후보 릴리스 두 줄만 쓰고, 끝나면 지운다. `rosy-release-push.ps1`의 활성화도 같은 파일을 쓴다. 비밀은 없다.
- 업데이트 중 `rosy-face` 자신도 재시작될 수 있다. 재시작 사이 2–5 s는 화면이 어둡다(백라이트 PWM이 프로세스와 함께 사라진다). 이 공백은 받아들인다.
- 종료(1행)는 SIGTERM에서 한 장 그리고 `TimeoutStopSec=5` 안에 끝낸다.

#### 6. 026에서 올라오는 로봇의 이주와 롤백

새 이미지(`customize-rootfs.sh`): `rosy-face.service`를 설치·enable하고 `rosy-boot-display.service`는 설치하지 않는다. 계정·그룹·udev 규칙은 Q4 결정대로다. `probe-display-runtime.py`와 마운트 검사기는 새 unit 이름을 본다.

페이로드 N(첫 `rosy-face` 릴리스)이 026 위에 올 때, `sync-image-layer.py`(N의 것)가:

1. `rosy-face.service`와 `rosy-face.py`를 설치한다(`UNITS`·`ENABLED_UNITS`에 추가).
2. `rosy-boot-display.service`를 **지우지 않고 바꾼다.** 새 내용은 지금과 같되 `ConditionPathExists=!/etc/systemd/system/rosy-face.service` 한 줄을 더한다. 바꾼 파일은 백업되므로 026의 롤백이 원래 파일을 되살린다. enable 상태는 건드리지 않는다.
3. 새 단계 "교대": `systemctl stop rosy-boot-display` 다음 `systemctl enable --now rosy-face`. pending.json에 기록해 실패하면 다음 실행이 끝낸다.
4. 다음 부팅부터는 조건 때문에 `rosy-boot-display`가 건너뛰고 `rosy-face`만 뜬다.

롤백(N → 026): 026의 동기화가 `rosy-face.service`를 `disable --now`로 지우고 원래 `rosy-boot-display.service`를 되살린다. 그 unit은 enable 상태 그대로이므로 다음 부팅에는 뜬다. 그 사이 공백(Context 6)을 메우려고:

- N의 자동 업데이터(롤백을 실행하는 것은 이미 메모리에 올라 있는 N의 코드다)는 롤백 동기화 뒤 `rosy-boot-display`가 enable이고 비활성이면 `systemctl start rosy-boot-display`를 한 번 부른다.
- `rosy-release-push.ps1 -Rollback`도 같은 단계를 갖는다.
- `recover-release.sh`는 부팅 경로라 조건과 enable 상태만으로 맞다.

`rosy-hw-test.py`의 넘김 판정(`DISPLAY_UNIT`)은 `rosy-face.service`를 먼저 보고, 없으면 `rosy-boot-display.service`를 본다(롤백된 로봇).

#### 7. 바뀌는 앞선 결정

- D-190 결정 5("LCD 소유자는 하나, emotion이 돌면 비켜 준다")는 이 결정으로 구체화한다. 소유자는 `rosy-face` 하나이고, 네이티브에서 `emotion_server`를 띄우는 unit·launch가 생기면 실패하는 가드를 유지한다.
- D-385 결정 2(브리지 → `set_emotion` 서비스)와 D-394 결정 4(`display/info` 퍼블리셔)는 시뮬레이션·벤치 경로로 남는다. 네이티브 경로는 결정 3의 파일이다.
- D-260 결정 7의 "부팅 표시 프로그램"은 `rosy-face`를 가리킨다.

### Alternatives

- **LCD 소유를 나눈다(부팅은 rosy-boot-display, CORE_READY 뒤는 emotion_server, 실패 시 되찾기).** 거부. 패널은 하나다. 백라이트 PWM은 그것을 연 프로세스와 함께 살고 죽으므로 넘길 때마다 화면이 꺼진다. "누가 지금 주인인가"를 정하는 규칙이 두 프로세스에 하나씩 생겨 어긋난다. 그리고 `emotion_server`는 ROS에 기대므로, CORE·ROS가 없는 순간, 즉 화면이 가장 필요한 순간에 없다.
- **이름을 `rosy-boot-display`로 둔다.** 거부. 부팅 뒤에도 얼굴·주행 카드·소리·빛을 맡는 프로세스를 "부팅 표시"라 부르면 이름이 역할을 속인다. 다음 사람이 또 "부팅 뒤는 다른 프로세스"라고 읽는다.
- **`emotion_server`를 네이티브 unit으로 띄우고 부팅 표시가 `Conflicts=`로 비킨다(D-190 결정 5 원안).** 거부. 분할 소유와 같은 문제에 더해, 모든 GIF를 원본 크기로 풀어 두는 지금 구현은 메모리 약 860 MB와 프레임당 LANCZOS 축소를 쓴다(Context 4).
- **status-inputs의 주기를 1 s로 줄인다.** 거부. 장치 행 전체를 매초 다시 계산하고, 자동 업데이트의 유휴 판정이 그 주기를 전제한다(결정 3).
- **CORE가 LCD를 직접 그린다.** 거부. CORE는 비특권이고 네트워크에 노출된다(D-161). 장치 허용을 CORE에 줄 수 없다.

### 사용자 결정 (2026-10-03)

다섯 질문 모두 권고안으로 정했다. 아래는 질문과 근거의 기록이다.

- **Q1. 비상정지 화면.** (a) 전체 경고 카드: 빨강 "STOPPED", 원인(사람 정지 / 감시 정지), 해제 방법 한 줄. (b) `sad` 얼굴 + 주행 카드 20 s 주기(D-394가 EMERGENCY를 포함한다). **결정 (a).** 로봇이 스스로 멈춘 경우(D-381 Context) 옆 사람이 1 m 밖에서 "왜, 어떻게 풀지"를 읽어야 하고, 슬픈 얼굴은 그 말을 하지 못한다. 램프 빨강 4 Hz·진입음과 같은 무게로 맞춘다.
- **Q2. 쓰이지 않은 로그인 코드.** (a) 코드가 쓰이거나 BURNED될 때까지 부팅 카드 전체. (b) 얼굴 아래 띠 `Login XXXX-XXXX operator`. **결정 (a).** 코드는 처음 한 번 읽히면 되는 일회용이고, 그 전에는 아무도 로그인하지 않았으니 얼굴을 볼 사람도 없다. 카드에는 IP도 함께 있어 첫 접속에 둘 다 필요하다. 쓰인 뒤 얼굴로 넘어간다.
- **Q3. 주의.** (a) 얼굴 아래 주황 띠(할 일 문구). (b) 진입 시 5 s 주의 카드 뒤 얼굴. **결정 (a).** 주의는 해결될 때까지 계속되는 상태라 띠가 계속 말해야 한다. 진입은 이미 낮은음 두 번과 주황 램프가 알린다(D-260). 카드는 사라지면 사실도 같이 사라진다.
- **Q4. 시스템 계정 이름.** (a) `rosy-display` 유지, unit·프로그램만 `rosy-face`. (b) `rosy-face`로 개명: D-388 금지 목록을 넓혀 `sysusers.d` 단계를 동기화에 더하고, udev 규칙 둘·`rosy-network`·`rosy-login-code`·`rosy-hw-test`의 그룹 이름을 같은 릴리스에서 바꾼다. **결정 (a).** 계정은 장치 접근 그룹이지 프로세스 역할이 아니다. (b)는 페이로드가 계정을 만들게 하는 새 권한이고, 실패하면 화면·소리·빛이 한꺼번에 사라진다.
- **Q5. 롤백 공백.** 결정 6의 "롤백 뒤 옛 표시 unit 한 번 시작"으로 충분한가, 아니면 자동 업데이트 롤백을 재부팅으로 끝낼 것인가. **결정: 한 번 시작**(재부팅은 실패한 업데이트를 두 번 흔든다).

구현이 정한 작은 것(사용자 결정 불필요): 캘리브레이션 띠 문구, 라인 추종 주행 카드 한 줄, 충전 중 띠, 시험 띠 길이.

### 구현 기록 (2026-10-03, 브랜치 `feat/d385-native-face-handoff`, 리뷰 전)

- **상황표.** `core_common.face_screen`(표준 라이브러리만): `screen_for`, `drive_due`·`drive_card_visible`(`core.bridge.display`는 다시 내보내기만 한다), `validate_face_inputs`·`read_face_inputs`. 시험 `src/contracts/foundation/test/test_face_screen.py`가 모든 행과 1–8행의 우선순위 쌍, 신선도 경계(3 s / 미래 5 s), 필드 단위 None 규칙을 본다.
- **CORE.** 브리지 5 Hz 전원 틱이 바뀔 때와 1 s마다 `face-inputs.json`을 쓴다(`display.face_inputs_payload`, `host.write_face_inputs`). rosy-core의 `UMask=0027`이 0644를 0640으로 만들기 때문에 쓴 뒤 `chmod 0644`를 한다. 얼굴 이름은 `set_emotion` 서비스가 없어도 `emotion_for`로 정한다(기동 10초 `hello` 포함).
- **rosy-face.** 0.5 s 폴(파일·상황표·부저·램프), 0.1 s 틱(얼굴 프레임, 백라이트가 낮으면 절반). GIF 프레임은 처음 재생할 때 틱마다 한 장씩 320×240 RGB565로 줄여 저장하고 다시 쓴다. 띠는 패널 바이트 위에 마스크로 얹는다. 소유자 검사는 `getpwnam("rosy-core")`의 uid다. SIGTERM에서 `/run/nologin`이 있으면 "Shutting down", 없으면 "Display restarting" 한 장을 그린다.
- **정지 카드 원인 줄(Q1).** 스냅샷에는 래치(`estop`)만 있고 누가 눌렀는지는 없다. 그래서 원인은 "E-stop latched"(래치) 또는 "Emergency stop"(모드만 EMERGENCY) 두 가지다. 감시 정지(SAF-002) 사유를 싣는 것은 후속이다.
- **업데이트 표시.** D-412 업데이터만 `update-display.txt`를 쓴다(적용 일지가 있는 동안). `rosy-release-push.ps1`의 활성화는 쓰지 않는다 — 수 초짜리이고, 쓰려면 원격 단계가 하나 더 필요하다. 후속.
- **이주.** `rosy-boot-display.service`는 릴리스에만 은퇴 사본(`ConditionPathExists=!/etc/systemd/system/rosy-face.service`)으로 실린다. 동기화는 그 파일이 이미 있는 로봇에서만 교체하고(새 이미지에는 설치하지 않는다), 재시작 목록에 올리지 않는다. rosy-face를 새로 더할 때 `stop rosy-boot-display` → `enable --now rosy-face`를 pending.json에 남겨 끊겨도 다음 실행이 끝낸다. 롤백 뒤 시작(Q5)은 업데이터 `_rollback_tail`과 `rosy-release-push.ps1 -Rollback`의 `display-restore` 단계 두 곳이다.
- **발견한 결함.** 부팅 카드의 숨쉼 프레임은 페이로드(`view["frame"]`)에 실렸지만 `render_boot(payload, frame=0)`가 인자로만 받아 실기에서 숨쉬지 않았다(D-385 결정 3). 카드 렌더러가 이제 `frame=`으로 넘긴다.
- **크기 판정.** `rosy-face.py` 1021줄(구 판정 대체), `ros_bridge.py` 799줄, `rosy_auto_update.py` 1559줄로 다시 판정했다(`test/architecture/test_module_structure.py`).

### Consequences

- 로봇 몸의 표면(화면·소리·빛)이 한 프로세스·한 규칙표로 모인다. 얼굴과 주행 카드가 처음으로 실기 화면에 나온다.
- CORE에 1 s 쓰기가 하나 는다(작은 JSON, tmpfs 원자 교체). `emotion_for`의 대기 시간 계산은 CORE에 그대로 있다.
- `rosy-face`의 메모리가 GIF 캐시만큼 는다(최대 약 60 MB). CPU는 실기 측정으로 확인한다.
- `drive_due`가 `core_common`으로 옮겨 가므로 CORE 브리지·`emotion_server`가 import를 바꾼다. 시뮬레이션 화면 동작은 같다.
- 이미지·페이로드·롤백 세 경로 각각에 이주 시험이 필요하다.
- 후속: `emotion` 패키지·`src/hmi/face` 이름 정리(D-427 동결 해제 뒤), 커널 패널 드라이버(D-190 열린 항목)는 그대로 열려 있다.

### Validation (구현 때)

- 계약 시험(호스트, rclpy 없음): `screen_for` 전 표(행마다 하나 이상, 우선순위 쌍, 신선도 경계 3 s, 모르는 값), `face-inputs.json` 키 셋과 쓰기 규칙, 엄격 읽기(링크·FIFO·크기·소유자·오래됨), 주행 카드 주기 이동 뒤 CORE·`emotion_server` 동일 결과, GIF 변환 캐시 크기, 부저·램프 기존 시험 그대로 통과.
- unit·이미지 계약: `test_native_systemd_contract.py`·`test_image_customization_contract.py`·`test_device_surface_contract.py`에 `rosy-face`(장치 허용 넷, 다른 unit 금지), 이미지에 `rosy-boot-display` 없음.
- 이주 시험: `sync-image-layer.py`가 026 상태에서 교대 명령을 내는지, 026 동기화로 롤백할 때 옛 파일이 되살아나고 N 업데이터가 옛 unit을 시작하는지(가짜 runner).
- 변이 증명: 신선도 규칙 제거, 1–9 우선순위 뒤집기, 교대 단계 제거 → 각각 빨강.
- 기기(사람 확인, 다음 릴리스): 아래 목록.
  1. 전원 → BOOTING 카드 숨쉼 → CORE_READY에서 로그인 코드 카드(Q2) → 로그인 뒤 `basic` 얼굴.
  2. 5분 대기 뒤 `bored`.
  3. 대시보드 수동 조종: `interest` 얼굴, 20 s마다 5 s 주행 카드.
  4. 내비게이션: `happy`, 막힘 유도 시 `bored`, 주행 카드.
  5. e-stop: Q1 화면, 램프 빨강 4 Hz, 진입음 4회, 해제 시 얼굴 복귀.
  6. `sudo systemctl stop rosy-core`: 3 s 안에 "CORE not responding" 카드, 다시 시작하면 얼굴.
  7. 현장 Wi-Fi 없이 부팅: AP SSID·PW·QR 카드가 CORE_READY 뒤에도 유지.
  8. 배터리 경고: 주황 띠(Q3)와 낮은음 두 번.
  9. 대시보드 부저·램프 시험이 `rosy-face`를 거쳐 울리고 켜지는지.
  10. 026 → N 페이로드: 화면이 끊김 2–5 s 안에 돌아오고 `systemctl is-active rosy-boot-display`=inactive, `rosy-face`=active. 재부팅 뒤에도 같음.
  11. N → 026 롤백: 화면·램프·부저가 재부팅 없이 돌아오는지.
  12. `top`/`pidstat`으로 `rosy-face` CPU(얼굴 재생 중 평균)와 RSS가 결정 4의 목표 안인지.
