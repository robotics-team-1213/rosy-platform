## D-165 Pinky Pro 네이티브 ROS 패키지의 하드웨어 의존성도 이미지 입력으로 고정한다

**Date:** 2026-09-22

**Status:** Accepted

**Context:** D-161은 Ubuntu Server 24.04 arm64와 ROS 2 Jazzy 네이티브 런타임을,
D-164는 Raspberry Pi에 직접 기록할 제품 디스크 이미지를 채택했다. 그러나 Pinky Pro의
필수 ROS 패키지 중 `sensor_adc`와 `imu_bno055`는 WiringPi를, `lamp_control`은
`rpi_ws281x`를 필요로 한다. 이 의존성을 빌드 러너의 우연한 사전 설치 상태에 맡기면
필수 패키지 inventory는 선언되어 있어도 실제 ARM64 빌드는 재현되지 않는다.

**Decision:**

1. Pinky Pro 제품 이미지의 필수 ROS 패키지 집합에는 `sensor_adc`, `imu_bno055`,
   `lamp_control`을 포함하며, CI 편의를 위해 이들을 건너뛴 산출물을 제품 이미지로
   승인하지 않는다.
2. WiringPi는 공식 ARM64 deb의 버전, HTTPS URL, SHA-256을 `inputs.lock.yaml`에
   고정한다. 같은 검증된 패키지를 native ARM64 빌드 호스트와 대상 Ubuntu rootfs에
   모두 설치한다.
3. `rpi_ws281x`는 Raspberry Pi 5 지원 branch의 정확한 commit, source archive URL,
   SHA-256을 고정하고 빌드 호스트에서 정적 라이브러리로 컴파일한다.
   `lamp_control`은 이를 정적으로 링크하므로 제품 rootfs에 출처가 불명확한 공유
   라이브러리를 별도로 복사하지 않는다.
4. checksum 검증은 `dpkg` 또는 CMake 실행보다 먼저 끝나야 하며, 불일치하면 이미지
   빌드를 즉시 중단한다.
5. 패키지가 이미지에 포함되는 것과 하드웨어가 승인되는 것은 별도다. 공통 이미지는
   계속 CORE-only로 부팅한다. Pi 5의 LED kernel module/device-tree overlay, 실제 I2C
   장치, GPIO와 모터는 DEVICE 단계에서 각각 검증되고 승인되기 전까지 자동 활성화하지
   않는다.

**Consequences:** native ARM64 image build는 Pinky Pro 필수 ROS 패키지를 생략하지 않고
재현할 수 있다. 반면 외부 하드웨어 소스와 deb도 release provenance의 일부가 되며,
업데이트 시 버전·commit·해시를 함께 검토해야 한다. 빌드 성공은 LED/I2C 실장 동작이나
군집 제어의 현장 성공을 대신하지 않는다.

**Validation / Transition:** `test_native_ros_payload.py`가 고정값, 선검증 설치 순서,
ARM64 workflow 연결을 검사하고 `test_image_customization_contract.py`가 검증된 WiringPi
runtime의 rootfs 설치를 고정한다. 이후 native ARM64 workflow에서 모든 필수 패키지의
colcon build와 image inventory를 통과시키고, SD readback 뒤 Pinky Pro에서 별도의
DEVICE/FLEET 절차를 수행한다.

**References:** D-84, D-145, D-161, D-164,
`deploy/image/inputs.lock.yaml`, `deploy/image/required-ros-packages.txt`,
[WiringPi](https://github.com/WiringPi/WiringPi),
[rpi_ws281x](https://github.com/jgarff/rpi_ws281x).
