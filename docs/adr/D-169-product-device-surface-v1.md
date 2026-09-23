## D-169 v1 제품 장치 표면은 모터·LiDAR·카메라·I2C-1 ADC로 고정한다 — emotion/lamp/led/imu는 벤치 전용을 소급 공식화

**Status:** Accepted (2026-09-22). 행위 변경 없음 — 이미 시험과 capabilities가 강제하던
상태의 소급 공식화다(D-147 선례). 뒤집으려면 후속 ADR로 대체한다.

**Context:** 통신·프로토콜 평가(2026-09-22 §8-F)가 드러낸 갭: `emotion`(SPI LCD),
`lamp_control`(WS2811, Pi5 out-of-tree 커널 모듈 필요), `led`(rosylib), `imu_bno055`(I2C-0)
4개 장치 패키지는 코드로 존재하지만 compose `devices`와 native `DeviceAllow` 어디에도
spidev0.0·i2c-0·gpiomem·PWM이 없어 **제품 런타임에서 실행 자체가 불가능**하다. 반면
제품 capabilities는 이미 `sensors: [lidar, encoder]`만 광고하고 있고, io 이미지가 aux
드라이버를 싣지 않는 것은 시험이 고정해 왔다. 즉 코드는 있고 계약상 광고도 없고 운영
경로도 없는 — 의도인지 유기인지 분간되지 않는 애매 상태였고, `measure-dds-baseline.sh`는
`imu_raw`를 기대 항목에 두어 미묘하게 어긋났다.

**Decision:** v1 제품 장치 표면을 **모터(`/dev/rosy-motor`, UART4)·LiDAR(`/dev/ttyAMA0`)·
카메라(`/dev/video0`)·I2C-1 ADC(`ir_adc_node`)** 로 고정하고, 4개 장치 노드는 **벤치
전용**으로 선언한다. 장치 노드의 제품 편입(장치 배관 + capabilities 확장 + 이미지 수용)은
하드웨어 프로필(D-84)과 실기 수요가 확정되는 후속 ADR로만 연다.

**Alternatives:** 지금 곧 4개 노드를 제품에 배관하는 안 — lamp의 Pi5 커널 모듈 수동 설치,
emotion의 SPI 충돌, IMU의 i2c-0 버스 검증이 전부 실기 증거 없는 상태라 벤치 없이
DeviceAllow를 넓히는 것은 표면만 넓히는 일이다. capabilities에 imu를 광고한 채 두는 안 —
D-32(광고한 능력은 지킨다) 위반이다.

**Consequences:** compose devices·native `DeviceAllow`·capabilities가 이 면에서 넓어지면
`test/test_device_surface_contract.py`가 적색이 된다(각 가드 변이 증명 완료).
`measure-dds-baseline.sh`의 `imu_raw`는 벤치 IMU 기동 시에만 잰다는 주석을 달았다.
4개 노드의 게이트(STATUS)는 여전히 ARTIFACT/DEVICE HOLD이며, 이 ADR은 그 HOLD를
정상화한다 — 벤치 장치가 제품을 기다리게 두는 것이 아니라, 제품이 벤치를 기다리는
상태를 명문화한 것이다.

**Validation:** `python -m pytest test/test_device_surface_contract.py
test/test_nav2_hardware_slice.py test/test_robot_runtime.py -q`

**References:** D-84(하드웨어 프로필), D-161(네이티브 런타임), D-32(capability 정직성),
D-147(소급 공식화 선례),
[communication-protocol remediation plan](../plans/2026-09-22-communication-protocol-remediation-plan.md) §G1,
`docs/assessments/communication-protocol-report.md` §8-F.

---
