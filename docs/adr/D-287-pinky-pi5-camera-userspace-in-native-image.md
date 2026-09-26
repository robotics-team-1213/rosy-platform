## D-287 Pinky Pro Pi 5 카메라 사용자 공간은 공식 소스를 고정해 네이티브 이미지에서 빌드한다

**Status:** Proposed (2026-09-26). ARM64 이미지 빌드와 새 SD의 촬영 검증 전에는 Accepted가 아니다.

잇는 결정: [D-161](D-161-ubuntu-server-native-ros-runtime.md) · [D-165](D-165-pinky-pro-native-hardware-dependencies.md) · [D-192](D-192-hardware-runtime-in-the-image.md) · [D-264](D-264-on-device-diagnostic-tools-in-the-image.md).

**Context:** Pinky Pro Pi 5의 OV5647은 CAM1에 연결된다. ROSY SD에서 `camera_auto_detect=0`과 `dtoverlay=ov5647`을 적용한 뒤 센서 probe와 실제 2592×1944 JPEG 촬영에 성공했다. 촬영에는 공급사 카드의 사용자 공간을 일시적으로 사용했다. 기존 ROSY 이미지에는 PiSP 지원 libcamera, `rpicam-still`, Picamera2가 없었다. Ubuntu Noble의 잠긴 apt 소스에서는 해당 `rpicam-apps`, `python3-picamera2`, `libpisp1` 후보를 찾지 못했다. 따라서 부팅 오버레이만 고쳐도 새 SD에서 독립적으로 촬영할 수 없다.

**Decision:**

1. 네이티브 ARM64 제품 이미지 빌드 중 Raspberry Pi 공식 `libpisp`, `libcamera`, `rpicam-apps`, `picamera2` 소스를 이 순서로 설치한다. 커밋과 아카이브 SHA-256은 `deploy/image/camera-sources.lock.json`에 고정한다. URL은 `codeload.github.com/raspberrypi/<프로젝트>`로 한정한다. PPA, 공급사 카드의 바이너리 복사, 장치 부팅 시 다운로드는 허용하지 않는다.
2. Pi 5 `rpi/pisp` 파이프라인과 IPA, OV5647용 `rpi/vc4`를 빌드한다. Picamera2의 ARM64 Python 의존은 별도 해시 잠금 파일에 고정하고, 시스템 런타임 패키지는 잠긴 Noble apt에서 설치한다. 이미지에 소스 잠금 사본을 남긴다. 빌드 전용 컴파일러와 헤더는 설치 전 패키지 목록을 기준으로 제거한다.
3. 빌드 실패, 입력 해시 불일치, Python import 또는 `rpicam-still --version` 실패 시 이미지를 생성하지 않는다. mounted-image 검증기는 카메라 실행 파일과 소스 잠금 기록을 확인한다. 실제 센서 열거와 JPEG 촬영은 새 SD로 부팅한 장치에서 별도 검증한다.
4. D-264의 카메라 행에 적힌 “Noble 패키지가 없으면 생략하고 소스 빌드하지 않는다”는 제한을 이 결정으로 대체한다. D-264의 I2C·GPIO 진단 도구, 제품 이미지의 빌드 도구 제외, 사람 확인 원칙은 유지한다.
5. 사용자 공간 설치는 CORE-only 기본 부팅을 바꾸지 않는다. `rosy-io` 카메라 노드 활성화, 장치 ACL, 대시보드 영상 전달은 별도 운용 검증 뒤 결정한다. CLI 사진 촬영 가능성과 제품 스트림 수용을 혼동하지 않는다.

**Alternatives:** Noble apt만 사용하면 현재 잠긴 소스에서 카메라 사용자 공간을 채울 수 없다. 공급사 SD의 라이브러리 복사는 출처·ABI·재현성을 제품 이미지에서 검증할 수 없다. 장치별 설치는 SD를 바꿀 때마다 같은 결함을 되풀이한다.

**Consequences:** 이미지 빌드 시간과 산출물 크기가 늘어난다. PiSP/libcamera ABI가 함께 바뀌므로 네 소스의 커밋을 한 묶음으로 검증하고 갱신한다. 해시 고정은 소스 무결성의 근거이며 빌드·촬영 성공의 증거는 아니다.

**Validation / Transition:** 호스트에서 잠금·호출 순서·검증기 계약 시험과 문서 lint를 통과시킨다. 이후 네이티브 ARM64 빌드에서 입력 검증, 이미지 검증, 패키지 목록, 크기를 기록한다. 새 이미지로 기록한 Pinky에서 `rpicam-hello --list-cameras`, `rpicam-still` 실제 JPEG, Picamera2 캡처를 확인하고 촬영 파일의 해시·치수·장치 상태를 `docs/validation/`에 남긴 뒤 Accepted 여부를 판단한다.

**References:** [Raspberry Pi camera software](https://www.raspberrypi.com/documentation/computers/camera_software.html), [official libcamera fork](https://github.com/raspberrypi/libcamera), [official rpicam-apps](https://github.com/raspberrypi/rpicam-apps), D-161, D-165, D-192, D-264.
