# Rosy OS 기능·Device 검증 통합 구현 계획

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 흡수된 `rosy_control` 기능을 Rosy OS의 단일 명령·안전 경로에 연결하고, 자동화 시험에서 ARM64 이미지·Device 설치·readback·Pinky Pro 현장 인수까지 재현 가능한 증거 사슬을 만든다.

**Architecture:** `rosy_core`는 FastAPI/rclpy와 최종 `cmd_vel` 발행자로 남긴다. `rosy_control`은 ROS 의존성이 낮은 worker와 sensor-only typed evidence를 제공한다. Device는 Raspberry Pi OS Lite 64-bit 호스트에서 서명된 ROS 2 Jazzy ARM64 컨테이너를 실행하며, `core`를 먼저 고정 운용하고 이후 `motor`와 `hardware` 프로필을 순서대로 승격한다.

**Tech Stack:** ROS 2 Jazzy, Python 3.12, rclpy, FastAPI, pytest, NumPy/OpenCV, colcon, Docker Buildx, Raspberry Pi OS Lite 64-bit, systemd, Docker Compose, signed release tooling.

---

## 1. 기준선과 범위

현재 소스·문서·정적 테스트와 ARM64 개발 이미지 후보 검증은 완료되었지만, Device에서 sensor-only adapter를 실제 활성화하는 작업, 서명된 release publication, Pi 설치·readback, 물리 장치 검증은 남아 있다. 기존 `src/rosy_control/launch/robot.launch.py`는 legacy full stack이므로 CORE와 함께 실행하지 않는다. 최종 `cmd_vel` publisher는 `rosy_core/bridge/ros_bridge.py` 한 곳이어야 한다.

증거는 서로 대체하지 않는 다음 계층으로 기록한다.

| 계층 | 확인 내용 | 현재 상태 | 승격 조건 |
| --- | --- | --- | --- |
| SOURCE | 소스·ADR·경계·패키지 구조 | GO | 변경마다 diff와 ADR 연결 |
| LOCAL | Windows의 순수 Python/문서/계약 테스트 | GO(환경 의존 일부 제외) | 반복 가능한 명령과 결과 저장 |
| ROS-SIM | ROS 2 Jazzy graph, parameter, topic, safety 시나리오 | HOLD | 현재 트리로 container smoke 재실행 (D-79). 2026-09-13 증거는 대체 GO가 아니다 |
| ARTIFACT | linux/arm64 이미지·digest·서명·manifest | HOLD | 빌드와 서명 readback. D-66 이후 CORE 이미지는 `rosy_control`/OpenCV를 포함하지 않으므로 이전 digest는 재사용하지 않는다. 2026-09-17 호스트 QEMU는 Hub `jazzy-ros-base` arm64 hollow 이미지에서 실패했다. 다음 실행: `docs/plans/2026-09-17-arm64-artifact-native-pi-plan.md`. |
| DEVICE | Pi OS 설치·identity·systemd·컨테이너·센서 readback | HOLD | 설치 전후 manifest와 health 증거 |
| FIELD | Pinky Pro 구동·정지·카메라·적재·암 | PARKED | 안전 담당자와 실물 시험 승인 |

각 단계의 결과는 `GO`, `HOLD`, `PARKED` 중 하나로 남기며, 상위 계층 결과를 하위 계층의 증거로 표현하지 않는다.

## 2. 작업 순서

### Task 0 — 기준선 고정과 시험 환경 확인

1. `docs/plans/2026-09-12-rosy-os-control-integrated-design.md`, `docs/plans/2026-09-12-control-absorption-results.md`, `docs/reference/ROSY ADR Log.md`, `docs/deployment/arm64-build-notes.md`, `deploy/robot/install-pi.sh`, `deploy/robot/verify/verify-pi.sh`를 읽고 계획의 입력 revision을 기록한다.
2. `git status --short`, `git rev-parse HEAD`, `git worktree list`를 저장한다. `src/rosy_imu_bno055/**`의 기존 WIP는 명시적 파일 목록 없이 stage/reset/overwrite하지 않는다.
3. 순수 테스트를 실행한다.

   ```powershell
   python -m pytest test/test_control_absorption_package.py test/test_network_topology_contracts.py -q --basetemp .pytest-tmp-device
   ```

4. ROS Jazzy 컨테이너에서 `/opt/ros/jazzy/lib/python3.12/site-packages`를 보존한 상태로 `rosy_core`와 `rosy_control`의 graph/parameter smoke를 실행한다. Windows에서 `bash` 또는 `openssl`이 없는 경우 해당 실패를 환경 제한으로 기록하고 성공으로 포장하지 않는다.

**산출물:** 기준선 revision, 명령, 통과/실패/skip 수, 환경 제한을 `docs/plans/2026-09-12-control-absorption-results.md`에 연결한다.

### Task 1 — ROS-free 정책 계약을 먼저 잠근다

대상은 `src/rosy_control/rosy_control/control/command_gate.py`, `lidar_guard.py`, `obstacle_risk.py`, `policy_handoff.py`와 해당 단위 테스트다.

- `GateInputs`, `Observations`, `ControlPolicyProducer`의 required sensor, timestamp, sequence, revision, evidence를 불변 snapshot으로 유지한다.
- non-finite 수치, 누락·stale 센서, revision 불일치, 순서 역전은 fail-closed 한다.
- producer는 ROS publisher나 e-stop endpoint를 만들지 않고 후보 정책과 근거만 반환한다.
- candidate와 최종 `cmd_vel`을 혼동하지 않도록 이름과 테스트 fixture를 분리한다.

시험은 정상 후보, missing/stale/non-finite, revision 변경, immutable evidence, sequence 역전, stop/zero candidate, 멱등 재평가를 포함한다.

```powershell
$env:PYTHONPATH = "$PWD/src/rosy_control;$PWD/src"
python -m pytest src/rosy_control/test -q --basetemp .pytest-tmp-control
```

### Task 2 — CORE에 명시적 sensor-only adapter를 연결한다

새 파일 `src/rosy_core/rosy_core/bridge/control_sensor_adapter.py`를 만들고 `rosy_core/node.py`, `rosy_core/services.py`, `rosy_core/safety/manager.py`와 연결한다.

- adapter는 camera/LiDAR/odom/IMU의 ROS 입력을 typed observation으로 변환하여 `ControlPolicyProducer`에 전달한다.
- 기본 프로필은 `disabled`다. 비활성일 때 callback, timer, device access, command side effect가 없어야 한다.
- 활성화할 때도 같은 rclpy executor 안에서 worker를 구동하며 최종 `cmd_vel`, e-stop HTTP route, legacy calibration authority를 만들지 않는다.
- `SafetyManager.bind_control_policy`가 실제 production node에서 호출되는지 확인하고, missing handoff는 자동으로 정지 후보가 되게 한다.
- CORE가 기존 `RosBridge`의 단일 최종 publisher를 유지하는지 graph guard로 검증한다.

시험 항목은 adapter disabled/enabled, camera/LiDAR/odom 누락, invalid transform, stale timestamp, callback 예외, node restart, revision 변경, executor shutdown, duplicate publisher 검출이다.

### Task 3 — 최종 출력과 안전 상태를 검증한다

`src/rosy_core/rosy_core/bridge/ros_bridge.py`, `src/rosy_core/rosy_core/safety/manager.py`, `src/rosy_control/rosy_control/safety/node.py`의 handoff를 정리한다.

- 정책 후보는 timestamp·sequence·revision을 포함하고, 최종 발행 직전에 다시 stale/범위/e-stop 조건을 확인한다.
- e-stop 해제는 fresh evidence와 명시적 operator action을 모두 요구한다.
- legacy launch와 CORE를 동시에 올리는 경우를 시작 단계에서 거부한다.
- 취소·정지는 늦게 도착한 callback이 덮어쓸 수 없도록 generation과 sequence를 비교한다.

`python -m pytest src/rosy_core/test -q`와 ROS graph smoke에서 publisher 수, stale hold, e-stop release, late-cancel, clean shutdown을 확인한다.

### Task 4 — calibration 적용·readback과 bounded sweep을 추가한다

calibration snapshot/storage, `rosy_control/safety/node.py`, CORE profile/manager를 변경 대상으로 삼는다.

- schema, sensor ID, generation, digest, 범위와 단위를 검증한다.
- 적용 전에는 모터를 정지시키고, 임시 파일과 atomic rename으로 generation을 바꾼다.
- write 후 readback이 입력 digest와 다르면 새 generation을 폐기하고 이전 정상 generation을 유지한다.
- 센서·안전 증거가 부족하면 bounded sweep을 시작하지 않는다. sweep은 simulation에서 먼저 재현하고, Device에서는 명시적 opt-in으로만 연다.

시험은 identity mismatch, schema mismatch, 범위 초과, digest 불일치, rollback, 재시작 후 readback, sweep timeout과 stop-distance를 포함한다.

### Task 5 — OpenCV 전처리 worker를 선택형 기능으로 제품화한다

현재 `src/rosy_control/rosy_control/camera_detect_node.py`의 HSV 결과는 바닥·절벽·전경 evidence이며 semantic box/grasp 판정이 아니다. 다음을 분리한다.

- camera worker의 입력 해상도·FPS·회전·노출을 profile로 고정하고, frame ID/time/revision/drop/latency/CPU/memory를 telemetry로 남긴다.
- `requirements*.txt`, `deploy/robot/Dockerfile`, `deploy/robot/compose.yaml`에 선택형 vision 의존성을 추가하되 CORE 컨테이너에 광범위한 `/dev`를 주지 않는다.
- Picamera2/CSI를 host service로 둘지 least-privilege container로 둘지는 실제 Pi에서 동일 시나리오를 비교한 뒤 결정한다.
- 이미지 전처리 evidence는 LiDAR/IR metric safety authority를 대체하지 않는다.

자동 시험은 고정 frame fixture, corrupt/empty frame, 색상·조명 변화, frame drop, latency budget, worker restart를 포함한다. 실제 카메라 시험은 Device 계층으로 남긴다.

### Task 6 — Nav2/ControlBackend와 OMX 경계를 고정한다

Nav2와 absorbed Control backend를 동일한 scenario fixture로 비교하고 한 번에 하나의 backend만 활성화한다. cancel, timeout, stale route, obstacle detour, stop distance 결과를 동일한 evidence schema로 기록한다.

OMX는 robot-local action capability로만 둔다. 모델(신형 OMX-F/OMX-AI 또는 구형 RM-X52-TNM), mount, payload, 전원 budget, hand-eye calibration, collision/interlock, recovery가 모두 정해지고 물리 시험을 통과하기 전에는 capability와 Device profile을 disabled로 유지한다. Pinky Pro에 실을 박스의 크기·질량·무게중심은 측정값으로 대체하기 전까지 요구사항 가정으로만 표시한다.

### Task 7 — linux/arm64 artifact를 재현 가능하게 만든다

deploy/robot/Dockerfile builds the absorbed package and worker dependencies while the core/motor/hardware profiles remain the accepted baseline. Vision and arm profiles are intentionally deferred until the camera placement and OMX capability gates produce Device evidence.

- `inputs.lock.yaml`, package manifest, source revision을 artifact metadata에 넣는다.
- build 후 이미지 안에 accepted worker가 있고 legacy publisher가 없으며 CORE에 device binding이 없음을 검사한다.
- Buildx 실행 예:

  ```powershell
  docker buildx build --platform linux/arm64 --target core -t <registry>/rosy-core:<sha> --file deploy/robot/Dockerfile --load .
  docker image inspect <registry>/rosy-core:<sha>
  ```

- registry digest, manifest, 서명과 검증 결과를 기록한다. 이미지 존재만으로 Device 설치나 현장 운용을 GO로 만들지 않는다.
- x86 Docker Desktop에서 ARM64 binfmt가 없으면 `exec format error`가 발생한다. 이 경우
  native ARM64 Pi/build host 또는 승인된 binfmt builder를 준비하기 전까지 ARTIFACT는 HOLD다.

### Task 8 — Raspberry Pi OS Device 설치와 readback을 구현한다

대상 Device는 Raspberry Pi OS Lite 64-bit 호스트이며, 초기에는 모터·암을 연결하지 않은 bench device다.

1. OS image, hostname, Wi-Fi/SSH, 시간 동기화, UART4, Docker와 최소 host package를 준비한다.
2. `deploy/robot/deploy-from-windows.ps1 -RobotNumber 1 -PiHost <pinky-host> -PiUser rosy`로 immutable `/opt/rosy`를 배포한다. `ROSY_ROBOT_NUMBER`가 없거나 충돌하면 설치를 중단한다.
3. Pi에서 `deploy/robot/verify/verify-pi.sh`와 `deploy/robot/runtime-mode.sh up`을 실행하여 identity, config generation, unit, container health를 확인한다.
4. `rosy-core`를 stationary 상태로 올리고 readback한다: robot ID, profile, capabilities, image digest, source revision, config generation/digest, container ID, ROS graph, 최종 `cmd_vel` publisher 수.
5. `/opt/rosy/deploy/robot/verify/device-readback.sh --json` 결과와 설치 전 manifest를 함께 보관한다. SSH 성공이나 HTTP 200만으로 설치 성공을 선언하지 않으며 credential은 readback에 포함하지 않는다.

### Task 9 — Device commissioning을 위험도 순서로 진행한다

- D0: Pi OS/SSH/time/identity — GO
- D1: signed ARM64 artifact/readback — HOLD until Task 7
- D2: core stationary health/graph — HOLD until Task 8
- D3: sensor-only camera/LiDAR/odom/IMU — HOLD until real hardware attached
- D4: motor runtime down 상태의 wiring/encoder/power probe — `verify-motors.sh`로 수행
- D5: deadman/e-stop/stale evidence/tilt/pickup/cancel/stop-distance controlled motion — safety owner 입회
- D6: pallet/box placement와 반복성 — 측정된 payload와 workspace에서만 수행
- D7: OMX arm interlock, hand-eye, grasp/release — 모델·mount·payload 승인 후 수행
- D8: rollback/reboot/update/maintenance — signed generation과 old generation readback

각 단계가 실패하면 zero hold와 이전 정상 generation을 유지하고 다음 단계로 진행하지 않는다. D7까지 통과하기 전에는 OMX capability를 API와 UI에 노출하지 않는다.

### Task 10 — 운영·롤백·유지보수까지 닫는다

`deploy/robot/systemd`, release/deploy scripts, operator/admin diagnostics, `docs/deployment` runbook과 smoke test를 함께 갱신한다.

- 활성화는 source revision → image digest → manifest/signature → Device readback의 연결을 보장한다.
- start/health/calibration mismatch가 나면 새 generation을 활성화하지 않고 이전 generation으로 유지한다.
- 일반 operator 화면에는 동작·상태만 두고, ID/token/error/grant/artifact/SHA-256 같은 내부 진단은 관리자 diagnostics에 둔다.
- 매 릴리스마다 install, verify, rollback, reboot, log collection, disk cleanup, key rotation 절차를 dry-run한다.

## 3. 실행 명령과 증거 형식

모든 단계는 `command`, `input revision`, `environment`, `result`, `artifact/digest`, `next gate` 필드를 가진 Markdown 또는 JSON evidence를 생성한다. 순수 테스트와 ROS-SIM은 CI에서 매번 실행하고, ARTIFACT/DEVICE/FIELD는 장비·서명 키·현장 로그가 있는 실행에서만 GO로 변경한다.

계획 구현 중 각 task는 작은 변경 단위로 커밋한다. 커밋 전에는 `git diff --check`와 관련 focused test를 실행하며, 현재 IMU WIP는 stage 대상에서 제외한다. ARM64 build나 Pi SSH가 없는 Windows 세션에서는 계획과 fixture/test harness까지만 진행하고 실제 gate는 HOLD로 남긴다.

## 4. Definition of Done

1. `rosy_control` sensor-only 기능이 명시적 profile로 CORE에 연결되고, 최종 `cmd_vel` publisher가 하나다.
2. 정책·adapter·calibration·OpenCV worker·rollback에 focused test와 ROS graph smoke가 있다.
3. ARM64 이미지가 source revision, digest, 서명, profile metadata와 함께 재현된다.
4. Pi OS Device 설치가 `install-pi.sh`/`verify-pi.sh`와 readback 증거로 반복된다.
5. motor·camera·safety·payload·OMX 시험 결과가 각각 독립 계층으로 기록된다.
6. 문서·ADR·runbook이 실제 경로와 일치하며, 미완료 실물 항목은 `HOLD` 또는 `PARKED`로 남는다.

현재 전체 상태는 **IN_PROGRESS**다. SOURCE/일부 LOCAL·ROS-SIM은 GO이고, ARTIFACT/DEVICE/FIELD는 아직 HOLD 또는 PARKED다.

---

## 2026-09-13 implementation checkpoint: calibration and Device handoff

The current software slice now has a concrete startup path for Device-local calibration:

1. The packaged `src/rosy_core/config/rosy_default.yaml` keeps the sensor adapter and calibration loader disabled. A Device overlay may set `control.sensor_adapter.enabled: true` and provide `calibration.required: true`, an exact record path, `data_root`, active generation, and the five-field identity context.
2. `RosyCoreNode` fills missing `active_generation` and `data_root` from `ROSY_DATA_GENERATION` and `ROSY_DATA_PATH`. The adapter loads and validates the snapshot before constructing a ROS worker, so a stale generation, bad digest, selector error, or path escape fails closed without creating the worker.
3. Only the seven measured SafetyNode values are admitted. An explicit override must equal the snapshot value. The worker is still `sensor_only`; `SafetyManager` and the existing CORE bridge retain final command ownership. The loaded snapshot revision and digest are available for administrator diagnostics.
4. Focused tests cover pre-construction load, conflict rejection, generation mismatch, disabled non-access, node environment binding, and packaged default opt-in. This is LOCAL/ROS-SIM evidence only; it does not certify sensors, motors, or arm motion.

Device enablement remains a staged operation. Publish an immutable signed ARM64 image and manifest first; install Raspberry Pi OS Lite 64-bit and `/opt/rosy`; run `verify-pi.sh`; capture `device-readback.sh --json`; then enable calibration only after the stationary graph and sensor gates pass. Keep the previous generation active on any mismatch and record the new readback before moving to motor, box/pallet, or OMX commissioning. OMX model, mount, payload, power, hand-eye, collision interlock, and recovery remain PARKED until measured on the Pinky Pro.

## 2026-09-13 implementation checkpoint: bounded OpenCV worker

The optional camera path now has a reusable ROS-free preprocessing boundary in
`src/rosy_control/rosy_control/sensing/camera_worker.py`:

1. `CameraPreprocessProfile` fixes width, height, FPS, quarter-turn rotation,
   profile revision and the maximum processing latency.
2. `CameraPreprocessWorker` validates BGR8 frames, rejects wrong resolution,
   rotates only after validation, counts frame gaps and out-of-order IDs, and
   marks corrupt or over-budget frames as unavailable evidence.
3. `CameraTelemetry` is JSON-safe and secret-free. It carries frame identity,
   profile revision, dimensions, drop count, processing/capture age, CPU time,
   memory high-water mark and quality reason.
4. `camera_detect_node` keeps its existing HSV evidence and camera policy, but
   routes frames through the worker and publishes `camera/telemetry`. No camera
   output becomes a command or safety authority; semantic box/grasp detection
   is still not implemented.

The worker and existing camera tests pass locally (`995 passed, 26 skipped` for
the full `src/rosy_control/test` suite). This advances SOURCE/LOCAL evidence;
CSI timing, Picamera2 access, and real frame-quality acceptance remain HOLD at
the Device/FIELD gates until a Raspberry Pi is available.

## 2026-09-13 implementation checkpoint: module boundary regression

The C6 set-equality guard now includes the fourteen compatibility probes
introduced by the absorbed sensor adapter and ROS namespace guard. Each probe
has an explicit accepted verdict in
`docs/plans/2026-09-06-module-split-criteria.md`; a new probe must update both
the document and `src/rosy_core/test/test_module_criteria.py`.

The full CORE suite is green: `747 passed, 10 skipped`. This closes the
source-level boundary regression. It does not advance ARTIFACT, DEVICE, or
FIELD status: those still require the immutable ARM64 image, Pi installation
and readback, then real sensor, motor, payload, and OMX evidence.

## 2026-09-13 implementation checkpoint: host-contract and release-scan regression

The Device contract tests now probe for an executable Bash implementation
before invoking shell scripts. This distinguishes a usable Git/MSYS Bash from
the Windows `System32\bash.exe` WSL stub, so unsupported host tooling is
reported as a skip instead of a false runtime failure. The README contract
also follows the canonical Device sequence: pass `ROSY_ROBOT_NUMBER` to
`install-pi.sh`, then start `runtime-mode.sh`.

The shared release scanner now ignores only two documented public-data cases:
slash-separated provenance paths in release prose and the source/destination
SHA-256 columns of the dated Control absorption inventory. A regression test
keeps those exceptions scoped; the same digest-shaped value in another CSV is
still reported.

Fresh root contract evidence with the Git-provided Bash/OpenSSL path available:
`800 passed, 24 skipped`; Pi deployment contracts alone: `30 passed`; release
boundary guards: `62 passed`. This is host/source evidence. It does not create
an ARM64 artifact, a Pi readback, or physical camera, motor, payload, or OMX
evidence.

## 2026-09-13 implementation checkpoint: motion provenance after consolidation

The Gazebo motion contract now hashes the absorbed package under the current
Rosy OS source tree. It discovers `src/rosy_control` from the tool location by
default, accepts an explicit `ROSY_SOURCE_ROOT` only when that package root
contains `package.xml` and `rosy_control/`, and fails before ROS initialization
when the source root is missing or malformed. Hash keys are stable paths
relative to the package root. The retired temporary Control checkout is no
longer a runtime or evidence dependency.

Four pure tests cover default discovery, explicit override, missing-root
failure, and the retired-reference guard. ADR D-49 records this maintenance
boundary. The full absorbed Control suite remains the local gate; this change
does not advance ARM64, Device, or FIELD evidence.

## 2026-09-13 implementation checkpoint: active guide cleanup

The active `rosy_control` guides no longer contain standalone Control
workspace commands. `CLAUDE.md` and `STEPS.txt` now point to the Rosy OS test,
ROS 2 build, `install-pi.sh`, `verify-pi.sh`, runtime startup, and JSON
readback sequence. The original standalone guides remain in the workspace
archive for historical comparison and are not needed by the package, image, or
Device runtime. ADR D-50 and the package ownership test record this boundary.

This removes an operator/agent path ambiguity; it does not change the legacy
entry points or promote any physical capability.

## 2026-09-13 review-driven completion gates

The following gates are required before the source-level work can be called a
Device-ready implementation. They make the remaining decisions measurable and
keep a passing regression suite separate from a physical safety approval.

### G0 — independent safety contract

Existing Control equivalence is regression evidence only. Before any real
`cmd_vel` handoff, the selected Device profile must define and test these
states: `NORMAL`, `LIMITED`, `HOLD`, `ESTOP_LATCHED`, and
`RECOVERY_PENDING`. For every required sensor, the profile records the stale
deadline, non-finite/missing behavior, contradictory-sensor behavior, speed
limit precedence, maximum stop latency, and maximum stop distance. An empty
threshold is `HOLD`; it is never treated as an implicit pass.

The test matrix covers boot, process restart, CORE loss, sensor loss, tilt,
pickup, obstacle, operator stop, e-stop release, and recovery. E-stop release
and process restart discard the previous candidate and require fresh evidence
plus an explicit new operator action. The result is an independent safety
decision, not only a comparison with the absorbed implementation.

### G1 — ARM64 camera placement decision

Before enabling the camera profile, run the same fixture on a native ARM64 Pi
with (a) a least-privilege vision container and (b) a host Picamera2/libcamera
service. Measure capture permission, restart behavior, frame freshness and
drops, p95 processing latency, CPU, memory, and failure isolation. Record the
selected placement and device path in a follow-up ADR. Until that ADR and its
readback exist, `camera` remains disabled and its evidence cannot authorize
motion.

### G2 — backend and shadow decision

Nav2 remains the default. A Control backend can become active only after the
same goal/cancel/timeout/obstacle/restart fixture is run against both backends
and the result records localization compatibility, route quality, detour
success, cancel latency, recovery time, CPU/memory, namespace isolation, and
maintenance cost. Before changing the final publisher, run the new producer in
shadow mode: it records candidate selection, limits, reason, revision, and
latency while the approved publisher alone drives the robot. The release record
must contain sample count, mismatch classes, worst latency, and owner-approved
tolerances; missing tolerances keep the gate `HOLD`. Never run two real
`cmd_vel` publishers as a comparison.

### G3 — Device trust and update evidence

The release stage already verifies the signed checksum list before activation,
and `device_readback.py` now repeats that verification against the installed
trusted key. Device commissioning must retain the verification result, trusted
key ID, manifest, image digests, and activation record together with the
readback.
Tampered manifest, missing signature, untrusted key, unsupported downgrade, or
digest mismatch leaves the runtime quarantined in core-off state. A JSON
readback with a missing or non-verified signature is `HOLD` even when the image
digest matches.

### G4 — operator and maintenance state contract

The web surface maps the five safety states and the navigation states
`INPUT`, `PLANNING`, `MOVING`, `DETOUR`, `LIMITED`, `BLOCKED`, `CANCELING`,
`SUCCEEDED`, and `FAILED`. Each live value shows last-received time and
`fresh`, `delayed`, or `disconnected`; stale values disable hazardous actions.
Calibration follows device check, preparation, confirmation, progress, safe
cancel/failure, save, apply-pending, and apply-confirmed states. Operator,
maintenance, and administrator routes are tested for authorization, existing
session revocation, direct-route access, audit events, and camera/map/diagnostic
retention. Touch and keyboard behavior is verified on the supported Device
viewport.

HOST slice (2026-09-17, D-72 S3–S6). This paragraph is not DEVICE GO.
`rosy_core` `StateSnapshot.evidence` is server-judged
`fresh`/`delayed`/`disconnected`/`unavailable` with `received_at` and
`stale_after_s`. The dashboard binds those strings as `data-evidence` and
refuses teleop unless pose and velocity are `fresh` (click-to-goal needs
pose). Tests: `src/rosy_core/test/test_evidence.py`,
`src/rosy_core/test/test_dashboard.py`. Operator console is CORE
`/dashboard` only (D-77); `rosy_control` `web_node` is not composed with
CORE.

Still HOLD for G4 GO: mapping of the five safety states and the listed
Nav2 names (CORE navigation enum is not that list), the calibration
state machine, Device viewport touch/keyboard, and Device evidence for
authorization routes.

### G5 — objective package split trigger

`rosy_control` stays one absorbed package while its pure logic, ROS adapter, and
Device profile remain coherent. Reconsider a split only when a measured trigger
appears: ROS-free logic needs independent reuse, a device dependency requires
selective installation, a reverse import to CORE appears, fault isolation
requires a separate process, or release cadences diverge. The trigger and the
chosen boundary must be recorded before implementation, rather than after a
large import rewrite.

### Device promotion order

The executable promotion order is now explicit:

1. Flash Raspberry Pi OS Lite 64-bit and record the image checksum, hostname,
   user, Wi-Fi, SSH, timezone, and device model.
2. Run `install-pi.sh` with `ROSY_ROBOT_NUMBER`; the installer derives identity,
   installs Docker/systemd, preserves data/config, and leaves the runtime in
   `core` mode.
3. Run `verify-pi.sh`, activate only a signed immutable ARM64 release, and
   capture `device-readback.sh --json`.
4. Keep hardware power and torque disabled while checking the stationary CORE
   graph, one `cmd_vel` publisher, image digest, config/data generation, and
   signature result.
5. Enable the context-bound calibration and sensor-only adapter on one bench
   generation, then repeat readback and sensor freshness checks.
6. Commission motor deadman, e-stop, UART loss, boot recovery, thermal, and
   storage behavior with wheels lifted before floor motion.
7. Commission camera placement/quality, navigation backend, box/pallet payload,
   and only then OMX mount, payload, hand-eye, collision interlock, and recovery.
8. Promote a capability only when its evidence record has the measured values,
   artifact revision/digest, Device identity, operator, timestamp, and rollback
   result. Any failed gate restores the last known-good generation and leaves
   field capabilities disabled.

## 2026-09-13 Nav2 and system improvement review

The current Nav2 slice is a usable default backend, but several values and
responsibilities are still split across files or depend on physical evidence.
These are the next improvements, ordered by their effect on safety and field
repeatability.

### P0 — close before floor motion

1. **Make the Pinky profile the single source for motion limits.** The CORE
   profile currently limits angular velocity to 0.80 rad/s while the Nav2
   launch defaults and velocity smoother permit higher values. Generate or
   validate the Nav2 controller, smoother, goal checker, acceleration and
   progress limits from the selected Device profile. A mismatch fails the
   profile check before hardware mode starts.
2. **Fail closed on a missing site map.** `hardware.launch.py` currently falls
   back to a packaged demo map when `/var/lib/rosy/maps/site.yaml` is absent.
   Keep that fallback for simulation and bench profiles only. A field profile
   must enter `HOLD` and refuse navigation until the YAML and referenced image
   exist, have a recorded map ID, and match the waypoint map ID.
3. **Replace the placeholder footprint with measured profiles.** The current
   0.12 m square describes neither the measured Pinky base nor a mounted arm or
   payload. Record base, stowed-arm, carried-box and placement footprints with
   clearance margins. Nav2's 2-D footprint and the arm's 3-D collision scene
   must be derived from the same physical state; an arm extension changes the
   allowed base motion.
4. **Make lifecycle and safety gates authoritative.** If localization,
   controller, costmap or the final motor adapter is not active, CORE must show
   `HOLD` and publish zero. Recovery, cancel and e-stop must be recorded with
   the same generation and stop-latency evidence; the software deadman remains
   supplementary to a hardware E-stop.

### P1 — improve navigation quality and diagnosis

5. **Stabilize odometry and TF before tuning planners.** Measure encoder
   scale, wheel separation, timestamp age, frame prefix and covariance. When
   the BNO055 path is ready, evaluate a `robot_localization` EKF (wheel odom +
   IMU) as a separate profile; do not add IMU data to Nav2 until covariance,
   bias and restart behavior are accepted.
6. **Expose real Nav2 feedback, not only a state enum.** Return an operation ID,
   goal acceptance, current pose, distance remaining, recovery count, result
   code and cancel completion. A REST `accepted` response must not imply that
   the Nav2 action server accepted or completed the goal.
7. **Define recovery policy and budgets explicitly.** Bind spin, backup and
   wait behaviors to obstacle, localization and controller failure reasons.
   Bound retries and time, then escalate to `BLOCKED`/`HOLD` with an evidence
   record. The `docking/collision_exemption` topic remains intent only until a
   real costmap integration is tested.
8. **Add repeatable navigation metrics.** For every test run retain map ID,
   profile revision, goal error, path length, time to goal, minimum clearance,
   stop latency/distance, recovery count, localization covariance, CPU, memory,
   temperature and frame/scan drops. Use rosbag2 or an equivalent bounded
   recorder on the Pi, with automatic disk limits and run IDs.

### P2 — connect perception and manipulation without creating a second driver

9. **Keep camera/OpenCV local and observation-only first.** Compare host
   Picamera2/libcamera capture with a least-privilege container on native ARM64;
   measure p95 latency, drops, CPU, memory and restart isolation. Start with
   AprilTag or known rectangular blocks for deterministic pose estimation.
   Camera evidence may refine a goal or grasp pose but cannot replace LiDAR,
   odometry or the safety authority.
10. **Add a robot-local manipulation mission layer.** Nav2 should own base
    navigation, while a future `rosy_manipulation` action/state machine owns
    `approach → stop-confirm → detect → pre-grasp → grasp-verify → lift →
    transport → place-verify → retreat`. OMX/MoveIt must never publish the
    final base `cmd_vel`; CORE remains the single command arbiter.
11. **Treat the carried object as a navigation state.** Arm pose, gripper
    state, box dimensions, mass and centre of gravity select the footprint,
    speed, acceleration and turning limits. Navigation is disabled when the
    carried-object state is unknown after restart or communication loss.

### Execution order

Implement P0 items as source/profile and contract tests first. Validate P1
items on a stationary Pi and lifted-wheel bench, then on a measured floor
course. Run P2 only after the base navigation and safety gates are accepted.
No recommendation in this review advances `ARTIFACT`, `DEVICE` or `FIELD` to
`GO` without the corresponding signed release, Pi readback and physical
evidence.

## 2026-09-13 ROS-native adapter implementation checkpoint

The implementation direction is now explicit: use standard ROS messages,
launch parameters, lifecycle, Nav2, `ros2_control` and MoveIt 2 wherever their
contracts fit. Board or vendor differences stay behind adapters; CORE remains
the external API and the only final base `cmd_vel` publisher.

### Implemented source boundary

- `rosy_bringup.pinky_pro_adapter.PinkyProAdapter` validates the complete
  Pinky Pro parameter set before the Dynamixel SDK is constructed. It emits a
  ROS launch parameter mapping and performs no UART access itself.
- `pinky_pro_adapter.yaml` is loaded by the Pinky bringup launch before
  commissioning overrides. The existing driver-side validation and deadman
  remain the second device-side guard.
- `rosy_omx_adapter` validates an unselected or model-selected OMX profile and
  emits standard `joint_state_broadcaster` and
  `joint_trajectory_controller`/MoveIt names. Its disabled profile returns no
  controller contract, creates no fake joint state, and opens no transport.
- The Device `io` image builds and ships `rosy_omx_adapter`, so the same
  profile validator is available on Raspberry Pi without enabling an arm or
  adding a vendor plugin.

### Remaining adapter work

1. Replace the current custom base driver with a measured
   `ros2_control` hardware plugin only after its DYNAMIXEL transport,
   encoder sign, torque and deadman behavior are proven equivalent on Pi. The
   current `rosy_bringup` path remains the accepted baseline until then.
2. Select OMX-F, OMX-AI or legacy OpenMANIPULATOR-X. Add the selected vendor
   transport behind `ros2_control`, expose `FollowJointTrajectory`, and build
   MoveIt 2 planning scene, joint limits, gripper action and recovery from ROS
   parameters. Model selection, power and payload measurements are still HOLD.
3. Prefer `sensor_msgs`, `image_transport`, `camera_info_manager`,
   `robot_localization` and Nav2 lifecycle/diagnostic topics over bespoke
   transports. Any custom logic remains an observation or policy adapter and
   cannot create a competing final command publisher.

The new adapter tests are source-only evidence. They do not assert that a
vendor plugin exists, that a motor can move, or that an OMX arm can carry a
payload. Those claims require a signed ARM64 image, Pi readback and physical
commissioning.

## 2026-09-13 P0 motion-limit guard implementation

The first P0 item is now wired into the hardware launch path. The selected
Device profile is mounted into the motor and IO containers as
`/etc/rosy/profile.yaml`. `rosy_navigation.profile_limits` reads the profile's
`max_linear_velocity` and `max_angular_velocity`, rejects launch overrides
above those ceilings, and checks the velocity-bearing Nav2 parameters before
the Nav2 graph is included. The Pinky bringup and Compose defaults now match
the current measured-profile envelope of `0.20 m/s` and `0.80 rad/s`.

The same launch now exposes `allow_demo_map`, which defaults to `false` for
hardware mode. A missing or unloadable site YAML/image therefore stops launch;
simulation or an explicitly declared bench run can opt into the packaged demo
map with `allow_demo_map:=true`.

P0-3 now has a parameter boundary as well. `motion_profiles.yaml` defines the
states `base`, `stowed_arm`, `carrying_box` and `placing`, but keeps each state
`measured: false` until the Pinky/OMX geometry and payload are recorded. When a
measured state is selected with `footprint_profile_file` and
`footprint_state`, the launch rewrites both Nav2 costmap footprints and lowers
the effective speed envelope to the state profile. Selecting an unmeasured
state, or requiring a measured profile without one, fails before Nav2 starts.

This is a startup/configuration guard, not a physical calibration result. The
footprint, acceleration, wheel scale and stop distance still require Pi and
floor-course evidence. A future carried-box profile must provide a new
measured envelope rather than increasing these values by launch override.

## 2026-09-13 Verification snapshot

The source and contract checks for the current ROS/device slice pass:

```text
test/test_network_topology_contracts.py
test/test_footprint_profiles.py
test/test_nav2_hardware_slice.py
test/test_nav2_profile_limits.py
test/test_robot_runtime.py
test/test_bringup_motor_contracts.py
test/test_pi_wifi_deployment.py
112 passed, 14 skipped

src/rosy_bringup/test/test_pinky_pro_adapter.py
src/rosy_bringup/test/test_command_deadman.py
19 passed

src/rosy_omx_adapter/test/test_omx_profile.py
9 passed
```

`python -m py_compile` for the changed Python modules and `git diff --check`
also pass. A complete `python -m pytest test/` run reached 743 passed and 50
skipped; its 22 failures and 27 errors are confined to release/signature and
device-readback fixtures that invoke `openssl`, which is not installed in the
current Windows environment. That run does not promote ARTIFACT or DEVICE.

The remaining promotion gates are unchanged: build and sign the ARM64 image,
install it on a Raspberry Pi 5, capture readback, select a measured Pinky/OMX
profile, and run lifted-wheel then floor-course payload and safety trials.

## 2026-09-13 BNO055 optional-driver implementation checkpoint

The BNO055 WIP is now a self-contained optional package. `main_node.cpp`
delegates I2C ownership and bounded initialization to `bno055_device`, keeps
the deployed acceleration and degrees-per-second unit contract in the
ROS-free decoder, rejects invalid quaternion/short-read samples, and publishes
freshness telemetry on `sensors/imu/status`. Startup failures exit nonzero so
the supervisor can hold the runtime rather than publishing synthetic zeros.

`reset_on_start` defaults to `false`; a reset is sent only when explicitly
requested and is followed by the required quiet wait. The package now exposes
`bno055.launch.py` and `config/bno055.yaml` for an explicit opt-in run, while
the default Rosy OS compose image remains IMU-disabled until ARM64 and
calibration evidence exists.

The ROS-free decoder, package-contract tests, and injected-bus fault harness
are part of the source evidence. `colcon`/ARM64 compilation, a real BNO055,
stationary bias data, and `robot_localization` fusion remain DEVICE/FIELD
gates and are still HOLD on this Windows workspace.

The Windows run currently reports `3 passed, 10 skipped` for the BNO055 Python
package/fault tests; the skips are the expected Linux ARM64 executable harness
without `BNO055_TEST_EXECUTABLE`.

## 2026-09-13 P0 lifecycle and motor readiness implementation checkpoint

P0-4 now has a source-level safety boundary. `NavigationReadinessGate` is a
ROS-free state machine shared by `NavigationManager` and `CommandManager`.
Hardware mode requires active lifecycle transitions from AMCL, map server,
controller server and both costmaps, plus the Pinky bringup adapter's
transient-local `motor/ready` lease. The lease is refreshed by the motor node;
an expired lease or any inactive/missing lifecycle observation keeps the gate
in HOLD. CORE still publishes the single `cmd_vel` topic at 50 Hz, but forces
the outgoing twist to zero while the gate is held. New navigation and teleop
requests return `HARDWARE_NOT_READY` (HTTP 503) before changing mode.

The default core/simulation configuration leaves the gate disabled for
host-only and bench tests. The device example configuration enables it and
lists the six required components explicitly. Lifecycle and adapter wiring is
covered by bridge/bringup contract tests, while the gate and command behavior
are covered by ROS-free tests.

The current focused verification is `112 passed, 14 skipped` across the
readiness, API/core, bridge registration, Nav2 hardware-slice and
motor-contract tests. The complete `src/rosy_core/test` suite is `758 passed,
10 skipped`; the smaller ROS-free core subset is `86 passed`. The full
root suite remains subject to the existing Windows `openssl` fixture blocker;
ARM64 lifecycle, UART-loss, restart and physical stop-latency evidence remain
DEVICE/FIELD HOLD gates.
