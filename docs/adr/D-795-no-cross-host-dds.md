## D-795 DDS는 호스트 하나 안에서만 흐른다 — 기계 사이 DDS 금지

**Status:** Accepted (2026-10-18). 사용자 결정: "DDS로 처리하는 것들은 꼭 없애라." 계측 없이 바로 적용한다. D-6(로봇 간 DDS 차단)과 D-120(시뮬 LOCALHOST)을 모든 호스트로 넓히고, D-524 4항의 AI PC 유닛 목록을 고친다. D-117(Cyclone)·D-121~D-123은 그대로 둔다. D-136/D-152의 영상 예산 원칙과 같은 방향이다.

### Context

Pinky는 이미 lo 전용 Cyclone 프로파일(`middleware/devices/pinky/bringup/config/cyclonedds_localhost.xml` → `/etc/rosy/cyclonedds.xml`)로 DDS를 호스트 안에 가둔다. 저장소의 다른 곳에는 기계 사이 DDS가 남아 있었다.

1. OMX 작업대 compose `omx-hardware-shell`은 `ROS_AUTOMATIC_DISCOVERY_RANGE` 기본값이 `SUBNET`이었고 `.env.example`도 `SUBNET`이었다. Dockerfile은 `ROS_LOCALHOST_ONLY=0`을 넣었다.
2. OMX 카메라 유닛 `rosy-omx-camera@.service`는 디스커버리 범위를 정하지 않았다. Jazzy 기본은 `SUBNET`이다. 카메라는 원본 640×480 bgr8(장당 약 0.9 MB)을 발행한다. 상한은 코드에 박힌 10 Hz였다.
3. Service Control(D-524)의 AI PC 허용 유닛에 `pinky-nav2`, `pinky-rosbridge-d12`, `pinky-rosbridge-d13`이 있었다. AI PC에서 Pinky의 DDS 도메인(12·13)에 붙는 옛 경로다. Pinky가 lo 전용이 된 뒤로는 닿지도 않고, 저장소 안에 쓰는 곳이 없다.
4. 개발 `env.sh`는 셸에서 물려받은 `SUBNET`을 그대로 썼다. `rosy_env.sh`는 프로파일 파일이 없으면 경고만 하고 기본 `SUBNET`으로 떴다. Isaac 문서는 Isaac과 CORE가 같은 호스트인지 적지 않았다.

WiFi·LAN에서 원본 Image나 디스커버리 트래픽이 흐르면 다른 로봇과 관제 경로의 대역을 먹는다(D-136 S-2).

### Decision

1. **DDS는 한 호스트 안에서만 흐른다.** 배포·런타임 설정은 `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST`이고 `ROS_STATIC_PEERS`는 비어 있다. `SUBNET`/`SYSTEM_DEFAULT`, `ROS_LOCALHOST_ONLY=0`, `domain_bridge`, `rosbridge`는 쓰지 않는다.
2. **Cyclone 프로파일은 loopback만 묶는다.** 저장소의 모든 `<CycloneDDS>` XML은 `NetworkInterface name="lo"`(또는 `127.*` 주소)만 갖고 `<Peers>`가 없다. 새 프로파일을 만들지 않고 Pinky 프로파일을 다시 쓴다. OMX compose는 그 파일을 `/etc/rosy/cyclonedds.xml`로 읽기 전용 마운트하고 `CYCLONEDDS_URI`를 연다.
3. **기계 사이는 HTTP/WebSocket(또는 WebRTC)만 쓴다.** OMX 카메라의 DDS 소비자(`commissioning_view.py`, 수집, pilot 시뮬)는 카메라 호스트에서 돈다. 다른 기계는 `commissioning_view.py`의 loopback HTTP/JPEG를 SSH localhost forward로 보거나, 진행 중인 WebRTC 경로(`feat/webrtc-camera-migration`)가 들어오면 그것을 쓴다. 수집은 컨트롤러 그래프와 같은 호스트에서만 돈다.
4. **systemd 유닛과 실행 스크립트는 ROS setup을 source한 뒤 범위를 고정한다.** `EnvironmentFile`이나 setup 스크립트가 범위를 넓히지 못한다(`rosy-omx-camera@`, `rosy-omx-camera-view`, `run_collection.sh`).
5. **OMX 카메라 프레임률은 인자로 제한한다.** `camera_source.py --max-fps`(기본 10, (0, 30]), 유닛은 `ROSY_CAMERA_MAX_FPS`. 기본값은 이전 고정 상한과 같아 동작이 바뀌지 않는다.
6. **AI PC의 `pinky-nav2`, `pinky-rosbridge-d12`, `pinky-rosbridge-d13`을 Service Control에서 뺀다.** D-524 4항의 `ai` 유닛은 `pinky-backend`, `pinky-frontend`, `pinky-r2-watch` 셋이다.
7. **개발·시뮬 도구도 같은 규칙이다.** `env.sh`는 `LOCALHOST`를 강제한다. `rosy_env.sh`는 프로파일이 없어도 `LOCALHOST`다. Isaac Sim과 그 CORE는 한 GPU 호스트에서 돈다.

### 일부러 하지 않는 것

- 계측하지 않는다(사용자 결정). 바뀐 설정의 실물 확인은 아래 열린 항목이다.
- OMX 카메라 미리보기 viewer의 `rmw_fastrtps_cpp`(D-117과 어긋남)는 이 결정 범위 밖이다. 같은 호스트 안에서만 흐르므로 그대로 두고 따로 정리한다.
- WebRTC 영상 경로(`middleware/media`, `operations/site_ui/media`)는 다른 세션이 끝낸다.

### 열린 항목

- AI PC에 설치된 사용자 유닛 `pinky-nav2.service`, `pinky-rosbridge-d12.service`, `pinky-rosbridge-d13.service`는 저장소 밖에 있다. 사람이 AI PC에서 멈추고 지운다(`systemctl --user disable --now ...`, 유닛 파일 삭제). host-guard `/etc/rosy/host-guard/units`에 남아 있으면 그 줄도 지운다.
- 이미 배포된 OMX 작업대의 `~/.config/rosy/omx-camera-*.env`와 `.env`에서 `OMX_ROS_AUTOMATIC_DISCOVERY_RANGE`·`SUBNET`을 지우고 유닛을 다시 설치한다.

### Consequences

- `test/test_no_cross_host_dds.py`가 배포·런타임 파일에서 위 금지 설정과 loopback이 아닌 Cyclone 프로파일을 찾으면 실패한다. 시험 파일과 문서는 검사하지 않는다.
- 다른 기계에서 OMX 카메라 화면이 필요하면 HTTP/JPEG 또는 WebRTC 경로를 쓴다. DDS 구독으로 붙일 수 없다.

### Validation

- `test/test_no_cross_host_dds.py`, `test/test_omx_workstation.py`, `middleware/devices/omx/adapter/test/test_camera_source.py`, `operations/fleet/test/test_host_control.py`, `test/test_host_guard.py`.

**References:** D-6, D-117, D-120, D-136, D-152, D-273, D-524.
