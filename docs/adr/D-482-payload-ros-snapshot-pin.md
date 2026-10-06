## D-482 Payload 빌드는 이미지가 쓴 ROS 날짜 스냅샷에 고정한다

**Status:** Accepted (2026-10-06, 사용자 결정; 워크플로·락·테스트까지. 실기 적용은 payload 릴리스 ABI 검사로 확인한다).

잇는 결정:
- D-161/D-164: 이미지 입력 락(`inputs.lock.yaml`). 이 결정은 `ros` 절에 키 하나를 더한다.
- D-225: native payload 릴리스. ABI 검사(`prepare_payload_release.py`)는 그대로다.

### Context

- 릴리스 2026.10.06-046(a075a0bba)이 ROS ABI 검사에서 실패했다. `ros-jazzy-*` 314개 가운데 211개가 로봇(192.168.1.201)과 달랐다. 예: `ros-jazzy-action-msgs` 2.0.4-1noble.20260911.052651 대 로봇 20260902.015428, `ros-jazzy-ament-cmake-ros` 0.12.2(20260911) 대 0.12.1(20260603).
- `build-native-payload.yml`은 `ros2-apt-source` 패키지의 체크섬만 고정하고, 그 패키지가 가리키는 `packages.ros.org` 라이브 저장소에서 설치한다. 러너가 매번 그날의 ROS를 받으므로 이미지와 벌어진다.
- 이미지 2026.09.22-001(`deb-packages.txt`)의 `ros-jazzy-*` 342개는 모두 `snapshots.ros.org/jazzy/2026-09-11`의 arm64 `Packages`에 같은 버전으로 있다(차집합 0). 그 스냅샷의 action-msgs는 20260902.015428, ament-cmake-ros는 0.12.1-1noble.20260603.145943으로 로봇 값과 같다. 앞선 스냅샷 2026-06-18은 action-msgs가 20260612라 맞지 않는다.

### Decision

1. `inputs.lock.yaml`의 `ros.apt_snapshot_url`(`https://snapshots.ros.org/jazzy/2026-09-11/ubuntu`)이 날짜의 유일한 출처다.
2. payload 워크플로는 `ros2-apt-source`를 설치한 뒤 `/etc/apt/sources.list.d/ros2.sources`의 `URIs:`를 락 값으로 바꾸고 `apt-get update` 한다. 값은 `snapshots.ros.org/jazzy/<날짜>/ubuntu` 형태만 받는다. 서명은 기존 ROS 키링으로 apt가 검증한다.
3. 이미지 빌드(`customize-rootfs.sh`, `build-pinky-image.yml`)는 이 결정으로 바꾸지 않는다. 다음 이미지 빌드에서 같은 락 키를 쓰는 것은 별도 결정이다.
4. 스냅샷 날짜를 올릴 때는 새 이미지 빌드와 같은 커밋에서 올리고, 로봇에 깔린 이미지의 `deb-packages.txt`와 대조한다.

### Consequences

- payload의 `ros-packages.txt`가 이미지 세트와 같아져 ABI 검사가 통과해야 한다. 어긋나면 기존대로 payload를 로봇에 올리지 않는다.
- 스냅샷에 없는 날짜의 패키지는 받을 수 없다. 이미지가 더 새 ROS로 다시 구워지면 락의 날짜를 같이 올려야 한다.
