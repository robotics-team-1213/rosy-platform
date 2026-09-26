## D-281 사이트 호스트 배치와 OMX 실행 인스턴스를 분리한다

**Status:** Proposed (2026-09-26). 배치 설계 제안이다. 현재 Compose가 OMX 두 대를 구동하거나, 실제 장치의 안전·성능이 수용됐다는 뜻은 아니다.

잇는 결정: D-33, D-55, D-59, D-117, D-118, D-197, D-246, D-267, D-269, D-271, D-273, D-275.

**Context:** Pinky Pro는 각 로봇의 Pi에서 native CORE를 실행한다. 사이트 Fleet·천장 Vision·Caddy는 한 Ubuntu 호스트의 Compose 후보이며, OMX-AI는 별도의 amd64 워크스테이션 이미지와 비활성 작업대 프로필을 갖는다. 현재 `deploy/omx/compose.yaml`은 한 팔로워/리더 직렬 장치 쌍을 받는 대화형 개발 셸만 제공한다. D-246은 UART/video를 직접 소유하는 제어·안전 런타임의 컨테이너화를 제한하므로, OMX OCI 개발 후보만으로 운영 제어의 컨테이너 배포가 승인된 것은 아니다. 향후 OMX-AI가 한 대 또는 두 대가 될 수 있지만, 장비 수만으로 워크스테이션 수를 고정하면 작은 현장의 설치 비용과 이후 분리 가능성을 함께 다루기 어렵다. 또한 현행 Fleet `robots.yaml`은 CORE REST를 가진 이동 로봇 목록이므로 OMX를 그 목록에 추가할 수 없다.

**Decision (제안):**

1. **장비, 실행 인스턴스, 호스트는 각각 식별한다.** Pinky의 `robot_id`, OMX의 `workcell_id`, 실행 인스턴스 ID, 물리 `host_id`를 구별한다. 한 OMX 작업대에는 한 시점에 제어 인스턴스 하나만 활성화한다. 인스턴스의 호스트 배치는 현장 비밀 설정과 배포 기록이 결정하며 장비 ID나 사이트 API 이름으로 인코딩하지 않는다. 같은 호스트는 여러 인스턴스를 실행할 수 있다.
2. **소규모 현장의 첫 배치 후보는 공유 Ubuntu 호스트다.** 사이트 Fleet·천장 Vision·Caddy의 Compose와 OMX 한두 대의 제어 런타임은 한 PC에 둘 수 있다. D-246에 맞춘 운영 기본 후보는 OMX마다 별도 native systemd 제어 인스턴스다. 인스턴스마다 영속 장치 식별자, 카메라·보정 revision, 로그/상태, 실행 설정과 자원 예산을 둔다. OMX OCI 이미지는 현 단계의 빌드/개발·ROS-SIM 후보로 유지한다. UART/video를 여는 운영 컨테이너를 채택하려면 D-246과의 충돌을 별도 결정으로 해결하고 DEVICE 정지·복구 증거를 확보해야 한다. 이 배치는 실물 동시 부하와 장애 시험 전에는 제품 기본 배치로 확정하지 않는다.
3. **프로세스 분리가 물리 안전 경계는 아니다.** 같은 호스트의 전원·커널·USB 컨트롤러·GPU 장애는 모든 동거 인스턴스에 영향을 준다. 각 OMX의 물리 정지 경로, 링크 상실 시 HOLD, 재시작 후 명시적 장치 재승인과 명령 재개 절차는 장치별로 검증한다. 프로세스 재시작으로 이전 trajectory를 자동 재생하지 않는다. Pinky의 로컬 CORE와 최종 `cmd_vel` 권한은 사이트 호스트와 독립이다.
4. **장치 소유권은 로봇마다 고정한다.** OMX 인스턴스는 검증된 팔로워·리더의 `/dev/serial/by-id/`와 선택된 카메라만 받는다. 두 인스턴스의 직렬 장치 또는 제어 카메라 중복 할당은 시작 전에 거부한다. 동일 장치를 ROS 제어와 native LeRobot/수동 도구가 동시에 점유하지 않는다. vendor ROS graph의 action·topic·TF·RMW 격리는 실제 launch/ROS-SIM에서 확인한다. 도메인 번호나 namespace만 바꾸면 분리된다고 가정하지 않는다.
5. **PC 간 연결은 역할별 계약이다.** 호스트별 Compose 네트워크는 해당 호스트 안에만 있다. 사이트 Fleet은 Pinky CORE에 기존 인증 REST/WSS 계약으로 접속한다. 천장 카메라는 사이트 Vision ingress에 접속하고 Fleet에는 파생 관측값만 보낸다. OMX의 원격 작업 요청·상태/API는 D-273 장치 검증과 별도 계약이 수용될 때까지 열지 않는다. `robots.yaml`을 범용 장비 등록부로 확장하거나 OMX에 이동 목표를 보내지 않는다. 향후 GPU/학습 호스트도 actuator에 직접 명령하지 않는다.
6. **배치 변경은 설정·산출물·검증의 변경이다.** 인스턴스를 다른 PC로 옮길 때 장비 ID와 작업 이력의 의미는 유지하고, 호스트 인벤토리·장치 허가·TLS/자격 증명·이미지 digest·보정 revision·백업/복구 기록을 갱신한다. 이전 호스트의 제어 인스턴스가 종료됐음을 확인한 뒤 새 호스트를 승인한다. 두 호스트에서 같은 장비를 동시에 제어하지 않는다.

**Alternatives:**

- OMX마다 전용 PC를 고정: 장애 격리는 단순하지만 1~2대 규모에서 설치·유지 비용을 선결한다. 동시 부하 또는 장애 요구가 이를 필요로 할 때 선택한다.
- 두 OMX를 한 ROS 프로세스/제어 graph로 결합: 장치, 명령 소유권, 재시작과 복구를 로봇별로 검증하기 어려워 채택하지 않는다.
- 사이트·OMX를 하나의 Compose 프로젝트/공유 DB로 결합: 서비스의 수명과 장치 권한을 얽으므로 채택하지 않는다. 한 물리 PC에서 사이트 Compose와 OMX native 서비스를 함께 운영할 수 있다.

**Transition / Validation:** [호스트 배치 설계](../plans/2026-09-26-site-host-placement-design.md)의 정적 인벤토리 → 2개 격리 인스턴스 ROS-SIM → 단일 OMX DEVICE → 2개 동시 DEVICE → 공유 호스트 장애/FIELD 순서로 판단한다. 동시 부하, USB 충돌, 정지·복구, 물리 거리 또는 가용성 요구가 공유 호스트를 벗어나면 같은 인스턴스를 별도 PC로 옮긴다. 현재 `omx.enabled: false`와 Fleet의 기존 CORE 계약은 그대로다.

**References:** [D-246](D-246-runtime-flexibility-native-default-container-sidecar-lane.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-275](D-275-web-surface-and-video-runtime-ownership.md), [OMX 실행 계획](../plans/2026-09-26-omx-ai-workstation-runtime.md), [사이트 Compose](../../deploy/site/compose.yaml), [OMX Compose](../../deploy/omx/compose.yaml).
