## D-282 장치별 ROS 실행 인스턴스가 할당된 하드웨어만 소유한다

**Status:** Proposed (2026-09-26). 이 결정은 ROS 그래프와 물리 장치의 소유권 경계만 정한다. 하드웨어 제어, 신규 API, 브리지, 배포 또는 `omx` capability 활성화를 승인하지 않는다.

**Context:** Pinky Pro는 로봇별 identity에서 파생된 ROS domain과 namespace로 onboard CORE를 실행하고 CORE가 최종 `cmd_vel`을 발행한다(D-33, D-38). OMX-AI는 고정 작업대 장치이며 Pinky의 이동 로봇 graph와 다른 actuator, serial bus, camera, 정지·복구 조건을 가진다. 현재 OMX OCI/Compose는 개발 및 ROS-SIM 후보이며 실물 장치 제어 런타임으로 수용되지 않았다(D-246, D-281). D-273은 고정 작업대에서 OMX 팔 제어와 작업 카메라 연결을 단계별로 결합하도록 이미 정했다. 장치별 그래프, 공유 host에서의 인스턴스 구분, 상위 조정의 연결 규칙을 함께 정하지 않으면 같은 UART 또는 카메라를 여러 프로세스가 점유하거나 서로 다른 로봇의 actuator 명령이 섞일 수 있다.

**Decision:**

1. **물리 장치의 실행 소유자를 하나로 제한한다.** `robot_id`, `workcell_id`, `instance_id`, `host_id`는 서로 다른 identity다. 각 actuator bus와 camera capture/control device는 한 시점에 하나의 실행 인스턴스에만 할당한다. 동일 장치의 중복 할당, 식별 불명, 권한 누락은 runtime 시작 전에 실패해야 한다. 재시작은 기존 명령을 자동 재생하지 않는다.
2. **각 로봇 또는 작업대는 자기 ROS 제어 graph를 소유한다.** Pinky domain과 namespace는 D-33에 따라 `ROSY_ROBOT_NUMBER`에서 파생하고 임의로 바꾸지 않는다. OMX는 작업대별 domain과 namespace를 명시 배정·기록한다. 개발용 domain 기본값은 여러 작업대의 배포 identity로 재사용하지 않는다. domain과 namespace는 명명·탐색 경계이며 사용자 권한이나 안전 격리의 대체물이 아니다.
3. **각 actuator에는 단일 최종 명령 소유자가 있다.** Pinky 주행의 최종 `cmd_vel` 발행자는 CORE다. OMX 팔은 장치 검증 후 로컬 adapter/controller 경로 하나만 trajectory 명령을 제출한다. leader teleop, MoveIt, 규칙 기반 작업, 학습 정책은 arbiter가 승인한 단일 owner만 사용할 수 있다. 명령에는 작업/세션 identity, 제한, fresh joint state, 활성 보정 revision을 확인한다. 연결 상실·상태 stale·worker 종료·재부팅은 HOLD이며 재연결만으로 동작을 재개하지 않는다.
4. **카메라는 소유 작업대의 관측 장치로 관리한다.** Pinky 전면 카메라, OMX 상부/손목 카메라, 사이트 천장 카메라는 별도 source와 frame/profile을 가진다. 카메라 인스턴스는 capture와 허용된 설정만 소유하고, 영상 소비자는 read-only다. 원본 프레임은 촬영 시각과 대응 `CameraInfo`, source/frame, calibration revision을 함께 가져야 한다. stale frame, 불일치 보정, 식별 불명의 카메라 영상은 팔 동작 좌표로 쓰지 않는다. 화면 미리보기는 D-152 상한을 따르고 제어/인식용 원본 스트림과 분리한다.
5. **로봇 간 조정은 공개 API 계약을 경유한다.** UI, Fleet, Vision 서버는 DDS graph나 `/cmd_vel`/팔 trajectory에 직접 연결하지 않는다. Pinky는 기존 CORE REST/WebSocket 계약을 사용한다. OMX 원격 작업 API는 작업대 identity, 허용 capability, 명령 ID, 만료, 취소, 상태 readback을 정의한 별도 계약이 승인되기 전까지 제공하지 않는다. D-269 경계를 넘는 DDS bridge가 필요하면 방향, topic/action allowlist, identity/authentication, QoS, freshness/rate, 장애 시 HOLD를 명시한 별도 ADR과 시험을 요구한다. 원본 카메라 영상은 Fleet으로 중계하지 않는다.
6. **host 배치는 별도 결정과 물리 증거를 따른다.** D-246의 native 제어 기본을 유지한다. D-281의 OMX별 native systemd 인스턴스와 단일 host 내 복수 작업대는 아직 Proposed이며, 중복 장치 배정, graph 간섭, stop/recovery, 자원 경합 시험을 통과하기 전에는 운영 배치로 간주하지 않는다. 개발용 container를 실물 UART/video 제어로 전환하려면 D-246을 다루는 별도 결정과 DEVICE 수용 증거가 필요하다.

**Alternatives:**

- **Pinky, OMX, 카메라를 하나의 ROS domain/graph에 둔다.** discovery와 빠른 prototype은 단순하지만 권한·장치 소유 경계가 흐려지고 잘못된 publisher나 장치 중복 점유의 영향 범위가 커지므로 선택하지 않는다.
- **중앙 ROS 프로세스 하나가 모든 robot hardware를 직접 소유한다.** 연결은 쉬워도 현장별 장치, 정지 경로, 장애와 재시작을 분리하기 어렵다. 사이트 서버/Fleet에 actuator 소유권을 두지 않는 기존 경계와도 맞지 않아 선택하지 않는다.
- **장비별 로컬 ROS owner와 API 조정 계층을 둔다.** 로봇/작업대가 actuator 안전과 상태를 직접 책임지고 상위 계층은 계약된 작업만 조정한다. 구현량은 더 들지만 장치 identity, stop, 테스트, 배포 경계를 일치시킬 수 있어 권장한다.

**Implementation order and gates:**

| Phase | Work | Exit evidence |
|---|---|---|
| P0 | Pinky, OMX, 카메라별 모델·revision·host·serial/camera identity·정지 수단 inventory | 모든 물리 장치에 owner 후보, 연결, 명령 종류, 장애 시 기본 동작 기록 |
| P1 | identity/domain/namespace/device-assignment 설정 계약과 중복 할당 거부 구현 | 로봇·작업대 identity 누락/중복/domain 충돌/동일 serial 재할당 음성 테스트 통과 |
| P2 | Pinky 단독 제어 소유권과 CORE 최종 `cmd_vel` 경로 검증 | 명령 publisher 단독성, stale 입력 HOLD, 재시작 후 자동 재개 없음; 현재 Pinky device gate 유지 |
| P3 | OMX vendor ROS-SIM과 native 제어 adapter/action ownership/fault 경로 검증 | 실제 controller·joint state, 한 명령 owner, 제한/취소/timeout/fault HOLD 확인; 현재 시뮬 타이밍·그리퍼 한계는 해소 전까지 HOLD |
| P4 | 각 카메라 source/profile/CameraInfo/시간 동기와 보정 연결 | 지속 장치 식별, frame·calibration revision 일치, FPS/drop/latency/stale 측정, 별도 기준점 오차 통과 |
| P5 | Pinky API와 OMX 작업 API 사이 선택적 작업 조정 | 별도 API 계약·인증·취소·결과 readback; DDS 직접 접근이나 raw image relay 없음 |
| P6 | 작업대/현장 acceptance와 필요 시 복수 인스턴스 시험 | 독립 stop, 단절·전원·재시작, 자원 경합, 장치 소유권 readback 및 운영자 승인 기록 |

SOURCE/LOCAL 통과는 ROS-SIM, ARTIFACT, DEVICE 또는 FIELD 통과를 대신하지 않는다. 실제 actuator 권한은 해당 장치의 독립 정지 수단과 fault/recovery를 DEVICE에서 측정하기 전까지 비활성으로 둔다. Pinky 이동과 고정 OMX 작업을 조합하는 것은 별도 FIELD 수용이다.

**Consequences:** 신규 hardware profile은 장치 identity, owning instance, ROS domain/namespace, RMW, 허용 capability, device binding, `config_generation`을 명시해야 한다. OMX 작업대 설정에는 camera/frame/calibration revision도 포함한다. 제품별 ROS graph가 통신할 수 있다는 사실만으로 cross-device 명령을 허용하지 않는다. 기존 Pinky identity와 D-273의 OMX 팔→상부 RGB 순서를 유지한다. API/schema 변경은 D-18에 따라 API Reference와 공유 schema를 함께 갱신하고 관련 device/release gate 후에만 노출한다.

**References:** [D-33](D-33-.md), [D-38](D-38-core.md), [D-55](D-55-mobile-manipulation-is-a-robot-local-mission-capability.md), [D-117](D-117-rmw-cyclonedds.md), [D-152](D-152-core-1-preview.md), [D-246](D-246-runtime-flexibility-native-default-container-sidecar-lane.md), [D-269](D-269-device-server-contracts-and-ros-boundary.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [OMX workstation plan](../plans/2026-09-26-omx-ai-workstation-runtime.md), [site/OMX host placement plan](../plans/2026-09-26-site-host-placement-implementation.md).
