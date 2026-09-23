## D-181 벤치 장치의 제품 편입 조건과 절차를 고정한다 — 장치별 실기 수요·D-84 프로필 항목·배관/capabilities/가드가 한 변경에서 충족될 때만 편입한다

**Status:** Proposed (2026-09-23). D-169가 정한 편입 조건(하드웨어 프로필 D-84 + 실기
수요)이 아직 확정되지 않았으므로, 이 ADR은 편입 **결정 자체가 아니라 수용 조건과 절차**를
선기록한다. 조건이 확정되는 날에 이 파일의 Status를 `Accepted`로 바꾸고, 편입한 장치와
실기 증거를 아래 Decision 표에 채운다 — 새 번호를 발급하지 않는다. 조건 없이 Status만
바꾸는 것은 편입 없는 편입 기록이며 무효다.

**Context:** D-169가 v1 제품 장치 표면을 모터·LiDAR·카메라·I2C-1 ADC로 고정하고
`emotion`(SPI LCD)·`lamp_control`(WS2811)·`led`(GPIO)·`imu_bno055`(I2C-0) 4개 패키지를
벤치 전용으로 소급 선언했다. 그 판정의 전제는 "코드로는 존재하지만 제품 런타임에서 실행
경로(D-161 DeviceAllow/compose devices)도, capabilities 광고(D-32)도, 실기 검증도 없다"는
점이었다. 편입은 세 축이 **동시에** 열려야 하는데, 셋 중 하나만으로는 표면만 넓어진다.
편입 시점에 매번 기준을 재논의하면 기준이 시즌마다 바뀌므로, 지금 고정해 둔다.

**Decision:** 다음 조건을 **장치별로 모두** 충족할 때만 해당 장치를 제품 장치 표면에
편입하고, 배관·capabilities·이미지·가드를 **한 변경에서** 함께 갱신한다.

| # | 조건 | 증거 형태 |
|---|------|-----------|
| 1 | 실기 수요 확정 — 누구가 왜 그 장치를 제품에서 요구하는지가 문서로 존재 | 수요/명세 ID, 요구 문서 |
| 2 | D-84 프로필 항목 — `profile.*.yaml`/capabilities에 장치가 선언 가능 | 프로필/capabilities diff (D-32: 선언 전에 지킬 수 있을 때만) |
| 3 | 배관 수용 — compose `devices` + native `DeviceAllow` + 커널 모듈/spi/i2c/gpio 노드가 이미지에 포함 | 이미지 readback (D-161), 해당 장치의 디바이스 노드 실기 기동 |
| 4 | 계약 가드 갱신 — `test/test_device_surface_contract.py`가 해당 장치를 허용으로 바꾼 상태에서 초록, 나머지 표면은 여전히 적색 유지 | 변이 증명 (permit 단계 변경→적색→복구→초록) |

조건을 충족하지 못한 장치는 D-169 그대로 **벤치 전용**이다 — 전체가 아니라 장치 단위로
판정하며, 표에 장치별로 충족일과 증거를 기록한다.

**편입 기록 (장치별):**

| 장치 | 1 수요 | 2 프로필 | 3 배관 | 4 가드 | 상태 |
|------|--------|----------|--------|--------|------|
| LCD ST7789 (`/dev/spidev0.0`, `/dev/gpiochip4` 선 18·25·27) | D-190 동등성 표(US-006) | `board.yaml` `boot_display.lcd`. CORE capability 아님(API가 구동하지 않음, D-32) | `rosy-boot-display.service` `DeviceAllow` + `99-rosy-display.rules`(spi 0660) + apt `python3-spidev`·`python3-rpi-lgpio`, 이미지 probe·검사기 | `test_device_surface_contract.py`: 표시 unit에만 허용, 다른 unit에 넣는 변이는 적색 | 2026-09-24 조건 1·2·4 충족, 3은 host·이미지 정적 확인까지. 실기 기동은 D-190 S3 |
| 부저 (`/dev/gpiochip4` 선 22) | 같음 | `boot_display.buzzer`, `enabled_by_default: false` | 같은 unit·같은 칩 노드. 기본 꺼짐 | 같은 시험 | 핀 미확인. 사람이 장치에서 확인한 뒤 D-190 표에 기록하고 켠다 |
| ADC 읽기(표시) (`/dev/i2c-1` 0x08 ch4) | 같음 | `boot_display.battery_adc`, 실제 허용은 `access: rw-any-address`, `lock: advisory-flock` | 같은 unit `DeviceAllow`, dialout. D-192 `flock`으로 `rosy-io`와 공존 | 같은 시험 | 2026-09-24 host 완료, 실기 ±0.05 V는 D-190 S3 |

**남은 위험(보안 리뷰 M2):** 허용은 노드 단위다. `gpiochip4`는 54개 선 전부, `i2c-1`은 모든 주소다. `rosy-display`가
탈취되면 모터 UART 핀이나 I2C 센서를 흔들 수 있다. 입구는 root가 쓰는 파일뿐이고 `PrivateNetwork=true`다. 좁히는
후속(커널 패널 드라이버, 파일로 받는 배터리)은 D-190 "열린 항목"에 있다.

세 장치 모두 조건 3의 "실기 기동" 증거가 D-190 S3에서 나오면 날짜와 증거를 이 표에 적고 이 ADR의 Status를
바꾼다. 그 전까지 이 ADR은 Proposed다.

**Alternatives:** 4개 장치를 한 번에 편입하는 안 — 서로 무관한 조건(라임의 커널 모듈,
이모션의 SPI 충돌, IMU의 i2c-0 검증)을 한 번에 검증하기 어려워 미검증 장치가 편입을
탕막한다. capabilities만 먼저 광고하는 안 — D-32(광고한 능력은 지킨다) 위반이다. 실기
수요 없이 조건 2·3만으로 먼저 편입하는 안 — "표면만 넓히는 일"로 D-169가 기각한 것과
같다.

**Consequences:** STATUS 게이트는 이 ADR으로 움직이지 않는다 — 4개 장치 게이트는 여전히
DEVICE HOLD이며(D-169의 HOLD 정상화), 편입은 장치별 실기 증거와 함께 상승한다.
`test/test_device_surface_contract.py`는 편입 시점에 해당 장치 가드만 넓히는 변이를 같은
변경에서 증명해야 한다. `measure-dds-baseline.sh`의 `imu_raw` 주석("벤치 IMU 기동 시에만")
은 imu가 편입되는 순간 기대 항목으로 전환한다. 편입이 하나도 안 일어나도 이 ADR은
"언제/how"의 재논쟁을 막는 것으로서 그 자체로 유효하다.

**Validation:** 활성화 시 — `python -m pytest test/test_device_surface_contract.py
test/test_robot_runtime.py test/test_nav2_hardware_slice.py -q` + 해당 장치 디바이스의
이미지/런타임 readback(DEVICE 게이트 절차). 현 시점(Proposed) — 조건 표가 D-169/D-84와
모순 없이 정합하는지만 확인한다.

**References:** D-169(부모 — 표면 고정 + "후속 ADR로만 연다"), D-84(하드웨어 프로필
게이트), D-32(capability 정직성), D-161(네이티브 런타임 DeviceAllow),
[communication-protocol remediation plan](../plans/2026-09-22-communication-protocol-remediation-plan.md) §G1,
`docs/assessments/communication-protocol-report.md` §8-F.

---
