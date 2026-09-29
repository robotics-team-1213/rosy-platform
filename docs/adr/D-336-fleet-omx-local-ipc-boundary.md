## D-336 Fleet와 OMX 제어 owner 사이 첫 연결은 같은 호스트의 local IPC로 제한한다

**Status:** Accepted (2026-09-29, SOURCE/LOCAL 연결 경계만). 실제 호스트 배치, 설치 서비스, OMX capability, 원격 장치 API, ROS graph 연결, 물리 정지·DEVICE/FIELD 수용을 승인하지 않는다.

### Context

D-281은 Site Fleet과 OMX가 같은 Ubuntu 호스트나 서로 다른 호스트에 놓일 수 있다고 두지만 OMX 원격 작업 요청·상태 API를 열지 않았다. D-246은 장치 제어·안전 owner의 native 실행을 기본으로 둔다. 현재 `deploy/robot/omx`는 ROS 2 Jazzy amd64 개발/ROS-SIM 이미지와 비활성 interactive shell이며, `omx_adapter`는 in-process `RosArmCommandRuntime`, 별도 SQLite `ActionStore`, evidence-only `PickPlaceTransaction`을 제공한다. 이들은 한 실행 서비스로 연결되지 않았고 원격 API·local IPC·물리 stop 입력도 없다. 채워진 실장치 host inventory, OMX serial identity, gripper/driver 수용 자료도 없다.

### Decision

1. **첫 소프트웨어 연결은 co-located source profile로 고정한다.** Site Fleet과 한 workcell의 native control owner가 같은 Linux host에 있을 때만 Fleet dispatcher가 per-instance Unix domain socket을 통해 local owner에 요청한다. Socket path는 `/run/rosy/omx/<instance_id>/control.sock`; 경로의 각 parent는 root/service 전용이고 socket owner/group/mode는 전용 service identity에 한정한다. 실제 field host 선택은 D-281 inventory 절차에 남긴다.
2. **IPC peer도 인증한다.** OMX owner는 `SO_PEERCRED`의 UID를 전용 Fleet service UID allowlist와 비교한다. filesystem mode만으로 인증하지 않는다. 연결당 최대 frame 64 KiB, versioned JSON message, 한 요청/한 응답 framing을 쓴다. `mission_id`, `step_id`, `action_id`, `attempt_id`, digest, workcell/instance, authority epoch, dispatch generation, grant expiry는 서버에서 검증하며 caller의 actor identity를 신뢰하지 않는다. 응답의 acceptance는 durable journal 수락만 뜻한다.
3. **action journal과 ROS goal client는 workcell owner 안에 둔다.** 각 workcell마다 native systemd service instance 하나가 local ActionStore와 ROS 2 action client의 단일 owner가 된다. Fleet은 ROS/DDS graph에 참여하지 않는다. Store/driver ACK 모호성은 UNKNOWN/HOLD이며 자동 재제출하지 않는다.
4. **Fleet 부재와 물리 정지는 다른 경계다.** UDS `StopLocal`은 authenticated Fleet 요청 없이 workcell owner에 전달 가능한 software stop 요청이다. 이는 독립된 물리 E-stop 회로·driver stop 증거를 대신하지 않는다. physical stop chain, driver readback, restart reconciliation이 수용되기 전에는 motion capability를 비활성으로 유지한다.
5. **다른 host의 Fleet→OMX 연결은 닫아 둔다.** Remote TLS API는 D-281과 D-273의 장치 검증, 인증·권한·재생 방지·stop/recovery 계약 및 producer/consumer 시험을 다루는 별도 ADR 전까지 제공하지 않는다. 서로 다른 host의 배치에서는 Fleet dispatch를 HOLD한다. Container가 serial/camera를 직접 소유하는 경로도 열지 않는다.

### Consequences

SOURCE/LOCAL에서는 UDS framing, peer identity, duplicate/late request와 owner journal을 hardware-free 시험할 수 있다. 이는 field 배치나 실물 제어 승인으로 승격되지 않는다. 실제 service UID/GID, systemd hardening, filesystem permissions, boot/restart/readback 및 독립 stop chain은 배포·장치 gate에서 검증해야 한다.

### Validation / Transition

1. SOURCE/LOCAL: 비허가 UID·잘못된 framing/version·초과 크기·만료 generation·다른 digest의 재사용을 거부하고 Fleet 미접속 StopLocal 경로를 software 수준에서 시험한다.
2. ROS-SIM: workcell별 action graph isolation, local owner restart, late ACK, cancel/stop 분리를 검증한다.
3. ARTIFACT/DEVICE/FIELD: D-281 inventory와 serial/camera identity, native systemd owner, real UID/GID, 물리 stop 회로 및 driver readback을 입증하기 전에는 활성화하지 않는다.

**References:** [D-18](D-18-rosy-core.md), [D-246](D-246-runtime-flexibility-native-default-container-sidecar-lane.md), [D-273](D-273-omx-camera-stream-and-arm-control-order.md), [D-281](D-281-site-host-placement-and-omx-instance-isolation.md), [D-282](D-282-per-hardware-ros-ownership-and-control-boundaries.md), [D-333](D-333-er2-mission-device-action-contract-closure.md), [D-334](D-334-er2-tool-and-progress-read-boundary.md).


### SOURCE implementation note (2026-09-29)

The adapter now contains a newline-framed UDS handler, Linux peer-UID check, 64 KiB input bound, grant digest validation, and a disabled-by-default Action runner. It records Fleet-issued action and attempt IDs before driver submission, reports acceptance uncertainty as UNKNOWN, and does not retry an existing submission. The socket parent remains service-manager provisioned. The local stop API persists `REQUESTED` then `LOCAL_LATCHED`, derives request source from peer UID, serializes the latch with the final submission call, and closes on restart or a stale Fleet fence. Re-arm requires a newer generation, a Fleet-current fence, named operator confirmation, and zero unresolved Actions read from the local journal. No systemd entrypoint, selected ROS/gripper ActionPort, device profile enablement, physical stop proof, or field acceptance is included.
