# ROSY Pi 5 OS 후보: 공식 지원 근거

> 2026-09-13 편입 안내: 이 문서는 작성 당시의 조사·평가 근거다. 현재 제품 경계와 구현 순서는 [ADR D-37~D-44](../reference/ROSY%20ADR%20Log.md), [흡수 실행 계획](2026-09-12-rosy-control-absorption-plan.md), [최신 실행 결과](2026-09-12-control-absorption-results.md)를 우선한다. 조사 당시의 미실행·별도 Control 표기는 현재 배포 상태를 뜻하지 않는다.

조사일: 2026-09-08. 공개된 공식 문서에 대한 조사이며, 이미지 생성·Pi 부팅·센서 동작을 검증한 결과는 아니다. 이 문서는 기존 OS 계약을 변경하지 않는다.

## 확인한 사실

| 후보 | 공식 근거 | ROSY에 주는 의미 |
|---|---|---|
| Ubuntu Server 24.04 arm64 | ROS Jazzy는 Ubuntu Noble 24.04 arm64를 Tier 1으로 지정한다. Jazzy 지원 기간은 2029년 5월까지다. [REP-2000 공식 원문](https://raw.githubusercontent.com/ros-infrastructure/rep/master/rep-2000.rst) | 호스트에 ROS를 직접 설치할 때 가장 명확한 지원 조합이다. Docker를 유지하는 것도 가능하다. |
| Raspberry Pi OS Lite Trixie arm64 + Ubuntu/Jazzy 컨테이너 | ROS의 Raspberry Pi 안내는 Ubuntu arm64 설치와 Pi OS arm64에서 Ubuntu ROS Docker 실행을 모두 안내한다. [ROS 공식 안내 원문](https://raw.githubusercontent.com/ros2/ros2_documentation/jazzy/source/How-To-Guides/Installing-on-Raspberry-Pi.rst) | ROS를 위해 호스트까지 Ubuntu로 바꿔야 하는 것은 아니다. Tier 1 근거는 컨테이너 안 ROS 사용자 공간에 해당하며, 전체 로봇 하드웨어 인증을 의미하지 않는다. |
| Ubuntu Core 24 | Pi 5 지원·인증이 명시되어 있다. [Ubuntu Pi 다운로드·지원표](https://ubuntu.com/download/raspberry-pi) | 지원되는 장비 OS 후보지만 일반 Ubuntu Server와 설치·배포 구조가 다르다. |

현재 Raspberry Pi OS Lite 64-bit는 Debian 13 Trixie 기반이고 Pi 5가 호환 목록에 포함된다. Bookworm은 Legacy로 제공된다. [Raspberry Pi 공식 OS 목록](https://www.raspberrypi.com/software/operating-systems/)

Jazzy의 REP-2000에는 Debian Bookworm arm64가 Tier 3으로 나와 있고, Debian Trixie는 Jazzy 대상 플랫폼으로 명시되어 있지 않다. 따라서 **Trixie 호스트에 Jazzy를 직접 설치하는 것을 Tier 1 조합이라고 부르면 안 된다.** Ubuntu/Jazzy 컨테이너 사용과 구별해야 한다. [REP-2000](https://raw.githubusercontent.com/ros-infrastructure/rep/master/rep-2000.rst)

Docker Engine 공식 Debian 설치 문서는 Trixie 13과 arm64를 지원 목록에 넣고 있다. 재현 가능한 이미지 제작은 버전을 지정한 패키지 설치가 적합하다. 공식 convenience script는 시험·개발 용도로 권고되므로 출하 이미지에서 매번 최신 버전을 가져오는 기본 경로로 삼지 않는다. [Docker Debian 설치](https://docs.docker.com/engine/install/debian/)

## 호스트 선택에서 놓치면 안 되는 부분

Ubuntu의 Pi 지원표는 Pi 5의 Ubuntu 24.04 Server 지원을 명시한다. 같은 문서는 **25.04 이전 Ubuntu에서 libcamera 스택이 작동하지 않는 제한**도 기재한다. 따라서 CSI 카메라를 쓸 계획이라면 Ubuntu 24.04를 무조건 더 좋은 선택으로 단정할 수 없다. USB 카메라·LiDAR·UART·I2C도 실제 모델과 드라이버 단위로 별도 검증해야 한다. [Ubuntu Pi 지원·제한](https://ubuntu.com/hardware/docs/boards/how-to/ubuntu_supported/raspberry-pi/)

컨테이너는 호스트 커널을 공유한다. Ubuntu 컨테이너를 올려도 호스트의 커널·장치 드라이버·디바이스 트리 문제가 없어지지 않는다. 카메라 사용자 공간 라이브러리와 호스트 드라이버의 호환도 확인해야 한다. [Docker 컨테이너 설명](https://docs.docker.com/get-started/docker-concepts/the-basics/what-is-a-container/)

Ubuntu 24.04의 표준 보안 유지 기간은 2029년 5월까지다. ROS Jazzy와 시간축을 맞추기 쉽다는 장점은 있지만, 모든 추가 ROS·벤더 패키지의 동일한 보안 보장을 뜻하지 않는다. [Ubuntu 지원 주기](https://ubuntu.com/about/release-cycle)

## 업데이트·이미지 제작 비교

| 후보 | 이미지·초기 설정 | 업데이트와 추가 설계 |
|---|---|---|
| Pi OS + Docker | `rpi-image-gen`으로 전용 이미지 제작. 공식 지원 빌드 호스트는 Debian Bookworm/Trixie arm64이며 다른 아키텍처·컨테이너/QEMU 환경은 공식 지원 범위 밖이다. [공식 프로젝트](https://github.com/raspberrypi/rpi-image-gen) | ROSY 컨테이너 교체와 호스트 OS 교체를 분리해야 한다. Pi OS 공식 문서는 배포판 주요 버전 변경 시 재설치를 권고한다. 자동 A/B OS 복구는 ROSY가 별도로 마련해야 하는 설계 과제다. [Pi OS 업데이트 안내](https://www.raspberrypi.com/documentation/computers/os.html) |
| Ubuntu Server + Docker | Pi용 preinstalled arm64 이미지를 SD/USB/NVMe에 기록하고 부트 파티션의 `user-data`, `network-config`를 통한 cloud-init 초기 설정을 사용할 수 있다. [Ubuntu 설치](https://ubuntu.com/hardware/docs/boards/how-to/ubuntu_supported/raspberry-pi/) | 패키지 업데이트와 ROSY 릴리스 복구를 구분해야 한다. 일반 Server 선택만으로 전체 rootfs의 원자적 업데이트가 완성되는 것은 아니다. |
| Ubuntu Core 24 | kernel/gadget/base/snapd/app snap과 모델을 조합한다. [Core 설치 구조](https://documentation.ubuntu.com/core/explanation/how-installation-works/) | 커널·OS·앱의 트랜잭션 업데이트와 이전 버전 복구를 제공한다. [Core OTA](https://ubuntu.com/core/features/ota-updates) ROSY를 이 체계로 이식하려면 패키징·권한·업데이트 소유권을 재설계해야 한다. |

Ubuntu Core는 `core24` 기반 ROS 2 Jazzy snap 제작 경로를 제공한다. 따라서 ROS 미지원이라 배제하는 것이 아니라, 기존 Docker/systemd 릴리스 방식을 snap 체계로 바꾸는 비용을 비교해야 한다. [Snapcraft ROS 2 통합](https://ubuntu.com/docs/snapcraft/9/how-to/integrations/craft-an-ros-2-app/)

Core의 recovery 모드도 공식 제공되지만, Pi 5에서 ROSY의 전원 중단·데이터 보존·장비 신원 유지가 검증됐다는 뜻은 아니다. 또한 Core를 선택한다고 Pi의 보안 부팅·전체 디스크 암호화가 자동으로 보장되는 것은 아니다. ARM/Pi의 암호화 구현은 보드별 작업이 필요할 수 있다. [Core recovery](https://documentation.ubuntu.com/core/how-to-guides/manage-ubuntu-core/use-a-recovery-mode/), [Core FDE 요구사항](https://documentation.ubuntu.com/core/explanation/full-disk-encryption/)

## 근거를 바탕으로 한 판단

**Pi 주변장치 지원과 기존 Docker 분리를 우선한다면 Pi OS Lite arm64 + 고정된 Ubuntu/Jazzy 런타임이 합리적인 1차 후보**다. 반대로 ROS 개발 환경과 호스트를 통일하고 CSI 카메라 같은 Pi 전용 스택 의존이 없다면 Ubuntu Server 24.04 arm64도 타당하다. 이는 공식 문서의 추천을 그대로 인용한 결론이 아니라 ROSY의 목적에 적용한 판단이다.

Ubuntu Core는 전체 OS OTA·장기 무인 운용을 초기부터 필수로 요구할 때 별도 시제품으로 평가할 가치가 있다. 단순히 자동 업데이트라는 한 항목만 보고 현재 배포 체계를 즉시 교체할 이유는 부족하다.

우선 같은 ARM64 ROSY 런타임으로 호스트 후보를 비교하고, 부팅·네트워크·장치 접근·자원 사용·재부팅·전원 중단 복구 결과를 기록해야 한다. 공식 플랫폼 지원, 컨테이너 실행 성공, 실제 로봇 운용 가능은 서로 다른 증거다.

## 현재 ROSY와 연결한 적용 범위

병행 저장소 점검에서 확인한 제약은 다음과 같다. 출처는 이 저장소 파일이며 외부 플랫폼 인증과 구분한다.

- `deploy/robot/install-pi.sh`는 `raspbian`/`debian`만 허용하고 Debian Docker 저장소를 사용한다. Ubuntu 호스트로 바꾸려면 설치 경로 수정이 필요하다.
- `deploy/robot/verify/verify-pi.sh`와 Host Agent 네트워크 구현은 `nmcli`/NetworkManager에 의존한다. Ubuntu를 택하면 네트워크 관리자를 포함한 등록·복구 동작을 정합해야 한다.
- `deploy/release/manifest.py` 및 `cli.py`의 장비 OS 계열은 `raspberry-pi-os-lite`로 구성되어 있다. 호스트 변경은 이미지 교체만의 일이 아니며 릴리스 타깃 계약과 함께 검토해야 한다.
- `deploy/robot/Dockerfile`의 ROS 기반은 `ros:jazzy-ros-base`다. 호스트 Pi OS와 Ubuntu/Noble ROS 런타임을 분리하는 방향이 이미 존재한다.
- UART 설정은 Pi 부트 설정 경로와 실제 UART 장치 이름에 의존한다. 또한 현재 하드웨어 프로필의 SLAM 미지원 상태를 Nav2 패키지 설치만으로 준비 완료라고 바꾸면 안 된다.

따라서 v1은 **Pi OS Lite 64-bit Trixie 호스트 + Ubuntu Noble/Jazzy ARM64 컨테이너를 조건부 우선안**으로 두고 기존 계약을 유지하는 것이 적절하다. Ubuntu Server 24.04는 개발·비교 기준과 대안 호스트로 남긴다. 이 조사로 OS 설정이나 버전 잠금 파일을 변경하지 않는다.

최종 확정에는 Pi 5에서 다음 증거가 필요하다: 냉간 부팅과 자동 등록, 장비별 신원 유지, UART/모터·LiDAR·IMU 및 장착 시 카메라 파이프라인, Wi-Fi 재접속, DDS 장비 간 격리, 로그·디스크 사용 상한, ARM64 릴리스 적용·복구, 전원 중단 후 복구. 카메라는 Pi OS 호스트라는 이유만으로 Ubuntu 컨테이너의 libcamera/HAT 사용자 공간 호환이 해결된다고 가정하지 않는다.

## 제안하는 v1 이미지 구성

아래는 조사에 따른 제품 구성 제안이다. 설치 완료 목록이 아니다.

| 영역 | 기본 구성 | 책임·제한 |
|---|---|---|
| 호스트 | Pi OS Lite 64-bit Trixie, Pi 커널·펌웨어, systemd | 데스크톱 제외, OS 이미지·패키지 버전 고정 |
| 네트워크 | NetworkManager, 이름 탐색, 시간 동기화 | 자동 등록·재연결·현장 네트워크 복구 |
| 장비 관리 | 등록용 호스트 서비스, 전용 장비 키, 서명 업데이트 도구 | root 권한 작업 한정, 정상 설치에 SSH 불필요 |
| 컨테이너 실행 | 고정 버전 Docker Engine·Compose | 로봇별 현장 빌드 없이 검증된 ARM64 이미지를 사전 적재 |
| ROS CORE | Ubuntu Noble 기반 Jazzy, CycloneDDS, rosy_core | 비root 서비스 계정, 외부 제어의 단일 API |
| ROS IO | 지원 하드웨어 프로필에 맞춘 드라이버·Nav2 | 초기 core 모드 이후 별도 운용 검증, SLAM은 추가 대상 |
| 영속 저장 | 신원·등록 저널과 운용 데이터 분리 | 릴리스 롤백으로 장비 신원이나 폐기 인증 복원 금지 |
| 관측 | 로그 크기 제한, 디스크·온도·부팅·건강 상태 | 메모리·부팅 시간·제어 지연은 실측, OS 이름으로 우열 단정 금지 |

공식 Jazzy ros-base Dockerfile은 Noble ros-core를 기반으로 하고 ros-core는 `ubuntu:noble`을 사용한다.
출하 때는 움직이는 태그 대신 검증한 ARM64 이미지 digest를 고정해야 한다.
[공식 ros-base Dockerfile](https://raw.githubusercontent.com/osrf/docker_images/master/ros/jazzy/ubuntu/noble/ros-base/Dockerfile),
[공식 ros-core Dockerfile](https://raw.githubusercontent.com/osrf/docker_images/master/ros/jazzy/ubuntu/noble/ros-core/Dockerfile)

PC의 Gazebo/RViz 개발 환경과 Pi의 현장 실행 이미지를 구분한다. Pi에 시뮬레이터나 데스크톱을
기본 포함할지는 로컬 화면·디버깅 요구로 결정한다. 무화면 현장 구성에서는 제외하되,
로컬 GUI가 필요한 개발·운용 구성에는 검증된 그래픽 스택을 추가하는 방향이다.
실시간 커널도 최초 기본값으로 넣지 않고, 제어 주기·지터 요구를 수치화하고 실측한 뒤 검토한다.

`deploy/image/inputs.lock.yaml`에는 Trixie와 Docker Trixie 제공 여부를 미확인으로 적은 오래된 설명이 남아 있다.
공식 제공 여부는 이번 조사에서 확인했지만, 실제 버전·커밋·digest 고정과 ARM64 검증은 남아 있으므로
`verified: false`를 문서 조사만으로 true로 바꾸지 않았다. 이미지 제작 스크립트도 여전히 미완성이다.

결정 기준: Pi 주변장치·기존 배포 구조가 우선인 현재 v1은 위 구성을 먼저 검증한다.
하드웨어 호환 문제나 ROS 호스트 직접 실행 요구가 확인되면 Ubuntu Server 24.04를 비교한다.
전체 OS의 원자적 무인 업데이트가 첫 출하 필수 조건으로 바뀌면 이미지 레이아웃을 고정하기 전에
Ubuntu Core 또는 별도 A/B OS 업데이트 체계를 다시 선정한다. 앱 업데이트만으로 이 요구를 충족했다고 하지 않는다.

## 재검토: OpenCV와 확장 기능을 고려한 선택

사용자 보완 요구: Lite를 용량 절감만으로 결정하지 않고 OpenCV와 향후 추가 기능을 고려한다.
이 절은 위 우선안을 보완한다. **호환성과 기능을 먼저 선정하고, 이미지 크기는 그다음 최적화한다.**

Lite는 데스크톱이 없는 기본 구성이지 OpenCV를 사용할 수 없는 별도 제한 OS가 아니다.
현재 공식 카메라 문서는 최근 Lite 이미지에도 GUI 의존성을 제외한 Picamera2가 포함된다고 설명한다.
배포 이미지별 실제 패키지 목록을 확인해야 하며 오래된 README의 사전 설치 설명과 혼동하지 않는다.
[Raspberry Pi 카메라 문서](https://www.raspberrypi.com/documentation/computers/camera_software.html)

OpenCV는 영상 처리, 영상 입출력, HighGUI 백엔드를 구분한다. 화면 없이 연산·인식·저장은 가능하며,
`cv2.imshow()` 같은 로컬 창에는 사용 가능한 GUI 빌드와 디스플레이 환경이 필요하다.
OpenCV headless Python 패키지는 GUI 의존성을 제외하는 선택이지 모든 비전 기능을 제거하는 선택이 아니다.
단, 필요한 contrib 모듈·GStreamer·FFmpeg·코덱·가속 백엔드가 실제 빌드에 들어 있는지는 별도 확인한다.
[OpenCV 빌드 옵션](https://docs.opencv.org/4.x/db/d05/tutorial_config_reference.html),
[OpenCV Python 패키지 선택](https://github.com/opencv/opencv-python)

| 예상 기능 | OS 결정 전에 확인할 호환 조합 |
|---|---|
| CPU OpenCV, 태그·영상 처리 | Python/NumPy/OpenCV 버전, 필요한 모듈, 실제 ARM64 연산 |
| ROS 영상 처리 | ROS 배포판과 cv_bridge·OpenCV의 ABI 및 Python 환경, 영상 인코딩 |
| USB 카메라 | 장치 모델·V4L2·노출 제어·지원 영상 형식 |
| CSI 카메라 | Pi 커널·센서 드라이버·libcamera/Picamera2·컨테이너 사용자 공간 |
| Hailo AI HAT | 호스트 드라이버·HailoRT·펌웨어·모델 형식·카메라 파이프라인 |
| 다른 AI 런타임 | 해당 SDK의 OS/ARM64 지원, 연산자·모델 지원과 메모리 요구 |
| 로컬 RViz·영상 창·터치 화면 | 그래픽 드라이버·디스플레이 서버·Qt/GTK, 화면 유지 요구 |
| 원격 관제 영상 | 인코딩·전송 지연·대역폭, CORE 제어 경로와 자원 격리 |

Raspberry Pi 공식 Hailo AI 안내는 Pi 5 + 64-bit Pi OS Trixie 기반 설치 경로를 제공한다.
이는 Pi OS 우선안을 뒷받침하지만 임의의 AI 모델이나 모든 SDK가 지원된다는 뜻은 아니다.
OpenCV 설치 자체가 NPU 가속을 켜 주는 것도 아니다. 가속기별 런타임과 모델 경로를 검증해야 한다.
[Raspberry Pi AI 소프트웨어](https://www.raspberrypi.com/documentation/computers/ai.html)

제안 구성은 같은 OS 계열과 버전 잠금을 공유하는 공통 기반 위에 다음 묶음을 얹는 방식이다.
이 묶음은 제품 배포 구성 제안이며 기존 `ROSY_RUNTIME_MODE` enum을 늘리는 결정이 아니다.

- 공통 기반: 부팅·등록·네트워크·업데이트·ROS CORE. 단독으로 동작한다.
- 비전 확장: OpenCV·입출력 백엔드·카메라 어댑터. 기존 비전 설계의 별도 `rosy-vision` 경계를 따른다.
- 가속기 확장: 검증된 보드별 호스트 드라이버와 대응 런타임·모델. 컨테이너만 교체하면 되는 것으로 가정하지 않는다.
- 로컬 화면/개발 확장: 필요할 때 그래픽 환경·RViz·미리보기·진단 도구 포함. 공통 런타임 버전은 유지한다.

기존 [비전 가속 설계](2026-09-05-vision-accelerator-shield-design.md)는 Draft다.
CORE에 카메라 장치나 추론 의존성을 몰아넣지 않는 방향은 유지하지만, 모든 라이브러리를
Noble 컨테이너 하나에 넣을 수 있다고 확정하지 않는다. 특히 CSI/Hailo 조합의 호스트/사용자 공간
호환을 시제품으로 확인하고 필요하면 어댑터 내부 분리를 설계한다.
배포 시 묶음의 의존성과 이미지·드라이버 버전을 함께 검사하고 비전이 없어도 CORE는 기동해야 한다.

확정 전 최소 시험: 동일 카메라·해상도·FPS·모델로 프레임 획득 → OpenCV 처리 → ROS 연동 →
원격 표시를 실행하고, 가속기 장착 구성도 별도 시험한다. 패키지 import 성공만으로 통과하지 않는다.
Nav2 동시 실행 시 처리 지연·프레임 손실·CPU/RAM·온도·제어 주기 지연을 기록하고,
비전 중단·재시작이 안전 경로를 방해하지 않는지 확인한다. 요구 FPS와 지연 상한은 기능별로 먼저 정한다.

따라서 Lite 우선안은 **무화면 장비의 기본 이미지 후보**로 한정한다. 데스크톱 기본 탑재 여부보다
지원할 실제 카메라·AI 가속기·ROS 영상 처리를 묶은 호환성 표가 최종 OS 선정 기준이다.
SDK가 다른 OS를 요구하면 호스트 우선안을 재검토한다. 이번 보완은 문서 조사이며 벤치 시험 결과가 아니다.
